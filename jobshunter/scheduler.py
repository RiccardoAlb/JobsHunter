"""Scansione pianificata su macOS tramite un LaunchAgent (parte anche con l'app chiusa).

Un LaunchAgent e' un'attivita' dell'utente gestita da launchd: se il Mac dorme all'ora prevista, parte al
risveglio. Il file sta in ~/Library/LaunchAgents e si toglie dalle Impostazioni (o con `./jh schedule off`).
"""
from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import settings

LABEL = "local.jobshunter.scan"
LEGACY_LABELS = ("local.jobhunter.scan",)  # nome precedente (JobHunter): va tolto
ALLOWED_HOURS = (1, 2, 3, 4, 6, 8, 12, 24)
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def legacy_plist_paths() -> list[Path]:
    return [Path.home() / "Library" / "LaunchAgents" / f"{lb}.plist" for lb in LEGACY_LABELS]


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "JobsHunter" / "scan.log"


def parse_times(text: str) -> list[tuple[int, int]]:
    """'09:00, 18:30' -> [(9, 0), (18, 30)]. Al massimo 4 orari, senza doppioni. ValueError se il formato e' sbagliato."""
    out = []
    for part in re.split(r"[,\s;]+", (text or "").strip()):
        if not part:
            continue
        m = _TIME.match(part)
        if not m:
            raise ValueError(f"orario non valido: {part}")
        t = (int(m.group(1)), int(m.group(2)))
        if t not in out:
            out.append(t)
    if not out or len(out) > 4:
        raise ValueError("indica da 1 a 4 orari, per esempio 09:00, 18:30")
    return sorted(out)


def parse_request(b: dict) -> dict:
    """Valida le impostazioni di pianificazione ricevute dalla GUI. ValueError con messaggio in italiano."""
    for key in ("enabled", "notify"):
        if key in b and not isinstance(b[key], bool):
            raise ValueError(f"{key}: serve vero o falso")
    kind = b.get("kind") if b.get("kind") in ("daily", "every") else "daily"
    try:
        times = parse_times(str(b.get("times") or "09:00"))
    except ValueError:
        raise ValueError("orari non validi (esempio: 09:00, 18:30)") from None
    raw = b.get("hours") or 6
    try:
        if isinstance(raw, bool):
            raise ValueError
        hours = int(raw)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("frequenza non valida") from None
    if hours not in ALLOWED_HOURS:
        raise ValueError("frequenza non valida")
    return {"enabled": bool(b.get("enabled")), "kind": kind, "times": times, "hours": hours,
            "notify": bool(b.get("notify", True))}


def format_times(times: list[tuple[int, int]]) -> str:
    return ", ".join(f"{h:02d}:{m:02d}" for h, m in times)


def command() -> list[str]:
    """Cosa lancia launchd: l'app impacchettata con --scan-once, oppure il Python del progetto in sviluppo."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--scan-once"]
    return [sys.executable, "-m", "jobshunter", "scan-auto"]


def build_plist(kind: str, times: list[tuple[int, int]], hours: int) -> dict:
    d: dict = {
        "Label": LABEL,
        "ProgramArguments": command(),
        "EnvironmentVariables": {"JOBSHUNTER_HOME": str(settings.home()), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
        "RunAtLoad": False,
        "ProcessType": "Background",
        "LowPriorityIO": True,
    }
    if not getattr(sys, "frozen", False):  # da sviluppo: `python -m jobshunter` deve trovare il pacchetto anche da launchd
        d["EnvironmentVariables"]["PYTHONPATH"] = str(settings.SOURCE_ROOT)
    if kind == "every":
        d["StartInterval"] = int(hours) * 3600
    else:
        d["StartCalendarInterval"] = [{"Hour": h, "Minute": m} for h, m in times]
    return d


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=20)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def is_loaded() -> bool:
    return sys.platform == "darwin" and _launchctl("print", f"{_domain()}/{LABEL}").returncode == 0


def install(kind: str, times: list[tuple[int, int]], hours: int) -> None:
    """Scrive il LaunchAgent e lo carica (sostituendo quello precedente)."""
    if sys.platform != "darwin":
        raise RuntimeError("la scansione automatica e' disponibile solo su macOS")
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        plistlib.dump(build_plist(kind, times, hours), f)
    os.chmod(path, 0o644)
    _launchctl("bootout", f"{_domain()}/{LABEL}")  # se non c'era, l'errore si ignora
    r = _launchctl("bootstrap", _domain(), str(path))
    if r.returncode != 0:
        raise RuntimeError(f"launchctl non ha caricato l'attivita': {(r.stderr or r.stdout).strip()[:200]}")


def remove_legacy() -> bool:
    """Toglie il LaunchAgent del vecchio nome (scarica da launchd e cancella il suo plist). True se c'era.
    Il file cancellato e' solo quello creato in passato da questa stessa app."""
    found = False
    for lb, path in zip(LEGACY_LABELS, legacy_plist_paths()):
        if path.exists():
            found = True
        if sys.platform == "darwin" and (path.exists() or _launchctl("print", f"{_domain()}/{lb}").returncode == 0):
            found = True
            _launchctl("bootout", f"{_domain()}/{lb}")
        path.unlink(missing_ok=True)
    return found


def uninstall() -> None:
    if sys.platform == "darwin":
        _launchctl("bootout", f"{_domain()}/{LABEL}")
    plist_path().unlink(missing_ok=True)
    remove_legacy()


def next_run(kind: str, times: list[tuple[int, int]], hours: int, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now()
    if kind == "every":
        return None  # dipende da quando e' stata caricata e dal risveglio del Mac
    cands = []
    for h, m in times:
        dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        cands.append(dt if dt > now else dt + timedelta(days=1))
    return min(cands) if cands else None


def current_settings(cfg: dict) -> dict:
    s = cfg.get("schedule", {})
    kind = s.get("kind", "daily") if s.get("kind", "daily") in ("daily", "every") else "daily"
    try:
        times = parse_times(str(s.get("times", "09:00")))
    except ValueError:
        times = [(9, 0)]
    hours = int(s.get("hours", 6)) if int(s.get("hours", 6)) in ALLOWED_HOURS else 6
    return {"enabled": bool(s.get("enabled", False)), "kind": kind, "times": format_times(times),
            "hours": hours, "notify": bool(s.get("notify", True)), "_times": times}


def status(cfg: dict) -> dict:
    cur = current_settings(cfg)
    nxt = next_run(cur["kind"], cur["_times"], cur["hours"])
    return {
        "supported": sys.platform == "darwin", "enabled": cur["enabled"], "installed": is_loaded(),
        "kind": cur["kind"], "times": cur["times"], "hours": cur["hours"], "notify": cur["notify"],
        "next": nxt.strftime("%d/%m/%Y alle %H:%M") if nxt and cur["enabled"] else "",
    }


def ensure_current(cfg: dict) -> bool:
    """All'avvio: se la scansione e' attiva ma il LaunchAgent manca o punta a un eseguibile diverso
    (app ricostruita, cartella cambiata), lo riscrive. Ritorna True se ha riscritto."""
    cur = current_settings(cfg)
    if sys.platform != "darwin":
        return False
    legacy = remove_legacy()  # il vecchio agente (nome JobHunter) non deve restare: farebbe partire scansioni doppie
    if not cur["enabled"]:
        return legacy
    path = plist_path()
    try:
        old = plistlib.loads(path.read_bytes()) if path.exists() else {}
    except Exception:
        old = {}
    want = build_plist(cur["kind"], cur["_times"], cur["hours"])
    if old.get("ProgramArguments") == want["ProgramArguments"] and old.get("EnvironmentVariables") == want["EnvironmentVariables"] and is_loaded():
        return legacy
    install(cur["kind"], cur["_times"], cur["hours"])
    return True
