"""Scansione pianificata (parte anche con l'app chiusa), con lo strumento del sistema:

- macOS: un LaunchAgent (launchd): se il Mac dorme all'ora prevista, parte al risveglio. Il file sta in ~/Library/LaunchAgents.
- Windows: un'attivita' dell'utente nell'Utilita' di pianificazione (`schtasks`), nome "JobsHunter scan"; se il PC era spento parte appena possibile.
- Linux: un timer `systemd --user` (jobshunter-scan.timer, con recupero delle esecuzioni perse) oppure, se systemd non c'e', una riga di `cron` marcata "# JobsHunter".

Si toglie dalle Impostazioni (o con `./jh schedule off`). Nei test nessun comando di sistema parte davvero (vedi `_guard_system`).
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from . import fsperm, osinfo, proc, settings

LABEL = "local.jobshunter.scan"
LEGACY_LABELS = ("local.jobhunter.scan",)  # nome precedente (JobHunter): va tolto
ALLOWED_HOURS = (1, 2, 3, 4, 6, 8, 12, 24)
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def legacy_plist_paths() -> list[Path]:
    return [Path.home() / "Library" / "LaunchAgents" / f"{lb}.plist" for lb in LEGACY_LABELS]


def log_path() -> Path:
    if osinfo.is_mac():
        return Path.home() / "Library" / "Logs" / "JobsHunter" / "scan.log"
    return osinfo.log_dir() / "scan.log"


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
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)


def _domain() -> str:
    return f"gui/{os.getuid() if hasattr(os, 'getuid') else 0}"  # os.getuid non esiste su Windows (nei test si simula launchd)


TASK_NAME = "JobsHunter scan"          # Windows
SYSTEMD_UNIT = "jobshunter-scan"       # Linux (systemd --user)
CRON_MARK = "# JobsHunter"             # Linux (cron)
_ALLOWED_TOOLS = {"launchctl", "schtasks", "systemctl", "crontab", "powershell", "notify-send"}


def _run(cmd: list[str], input: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Unico punto da cui partono i comandi di sistema della pianificazione (i test lo sostituiscono con uno finto)."""
    if not cmd or Path(cmd[0]).stem.lower() not in _ALLOWED_TOOLS:
        raise RuntimeError("comando non ammesso")
    # codifica esplicita: l'output di schtasks usa la tabella OEM di Windows (byte non UTF-8): i caratteri illeggibili si sostituiscono
    return proc.run(cmd, input=input, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


_REAL_RUN = _run


def _guard_system() -> None:
    """Sotto pytest nessun comando di sistema vero (schtasks, systemctl, crontab) puo' partire se il test non ha sostituito `_run`."""
    if os.environ.get("PYTEST_CURRENT_TEST") and globals().get("_run") is _REAL_RUN:
        raise RuntimeError("test: la pianificazione del sistema non si tocca")


def _tool_ok(cmd: list[str]) -> bool:
    try:
        return _run(cmd, timeout=10).returncode == 0
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return False


def backend() -> str:
    """Strumento di pianificazione disponibile: 'launchd' (macOS), 'schtasks' (Windows), 'systemd' o 'cron' (Linux), '' se nessuno."""
    system = osinfo.current()
    if system == "mac":
        return "launchd"
    if system == "windows":
        return "schtasks" if shutil.which("schtasks") else ""
    if shutil.which("systemctl") and _tool_ok(["systemctl", "--user", "show-environment"]):
        return "systemd"
    if shutil.which("crontab"):
        return "cron"
    return ""


def supported() -> bool:
    return bool(backend())


def method_label() -> str:
    return {"launchd": "launchd", "schtasks": "Utilita' di pianificazione di Windows", "systemd": "systemd (timer dell'utente)", "cron": "cron"}.get(backend(), "")


def unsupported_reason() -> str:
    system = osinfo.current()
    if system == "windows":
        return "Non trovo l'Utilita' di pianificazione di Windows (schtasks): la scansione automatica non e' disponibile."
    if system == "linux":
        return "Non trovo ne' systemd (utente) ne' cron: la scansione automatica non e' disponibile su questo computer."
    return "La scansione automatica non e' disponibile su questo sistema."


def is_loaded() -> bool:
    b = backend()
    if b == "launchd":
        return _launchctl("print", f"{_domain()}/{LABEL}").returncode == 0
    if b == "schtasks":
        return _tool_ok(["schtasks", "/Query", "/TN", TASK_NAME])
    if b == "systemd":
        return _tool_ok(["systemctl", "--user", "is-enabled", f"{SYSTEMD_UNIT}.timer"])
    if b == "cron":
        try:
            return any(_is_ours(line) for line in _crontab_read().splitlines())
        except RuntimeError:
            return False
    return False


# ---- file di stato (solo Windows e Linux): serve a riscrivere la pianificazione se l'app o la cartella dei dati cambiano ----
def _state_path() -> Path:
    return settings.home() / "schedule_state.json"


def _wanted_state(kind: str, times: list[tuple[int, int]], hours: int) -> dict:
    return {"backend": backend(), "command": _task_command(), "home": str(settings.home()), "kind": kind,
            "times": [list(t) for t in times], "hours": int(hours)}


def _task_command() -> list[str]:
    """Il comando lanciato dalla pianificazione, con la cartella dei dati esplicita (la pianificazione non eredita l'ambiente)."""
    base = scan_command()
    if base[-2:] == ["--scan-once"] or len(base) < 4:  # app impacchettata: sa da sola dove sono i dati
        return base
    cmd = [*base[:-1], "--home", str(settings.home()), base[-1]]
    if osinfo.is_windows():  # pythonw non ha una console: il registro va su file
        cmd += ["--log-file", str(log_path())]
    return cmd


def scan_command() -> list[str]:
    """Come `command()`, ma su Windows usa pythonw.exe (nessuna finestra nera) se c'e'."""
    cmd = command()
    if osinfo.is_windows() and not getattr(sys, "frozen", False):
        pw = Path(sys.executable).with_name("pythonw.exe")
        if pw.exists():
            cmd = [str(pw), *cmd[1:]]
    return cmd


# ---- Windows: Utilita' di pianificazione ----
def _task_xml(kind: str, times: list[tuple[int, int]], hours: int, now: datetime | None = None) -> str:
    now = now or datetime.now()
    day = now.strftime("%Y-%m-%d")
    if kind == "every":
        if int(hours) >= 24:
            triggers = [f"<CalendarTrigger><StartBoundary>{day}T09:00:00</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"]
        else:
            triggers = [f"<CalendarTrigger><StartBoundary>{day}T00:00:00</StartBoundary><Enabled>true</Enabled>"
                        f"<Repetition><Interval>PT{int(hours)}H</Interval><Duration>P1D</Duration></Repetition>"
                        "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"]
    else:
        triggers = [f"<CalendarTrigger><StartBoundary>{day}T{h:02d}:{m:02d}:00</StartBoundary><Enabled>true</Enabled>"
                    "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>" for h, m in times]
    cmd = _task_command()
    args = subprocess.list2cmdline(cmd[1:])
    return ('<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            "<RegistrationInfo><Description>JobsHunter: scansione automatica degli annunci</Description></RegistrationInfo>"
            f"<Triggers>{''.join(triggers)}</Triggers>"
            '<Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>'
            "<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
            "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable>"
            "<ExecutionTimeLimit>PT1H</ExecutionTimeLimit><Enabled>true</Enabled></Settings>"
            f'<Actions Context="Author"><Exec><Command>{_xml_escape(cmd[0])}</Command><Arguments>{_xml_escape(args)}</Arguments>'
            f"<WorkingDirectory>{_xml_escape(str(settings.SOURCE_ROOT))}</WorkingDirectory></Exec></Actions></Task>")


def _install_schtasks(kind, times, hours) -> None:
    xml = settings.home() / "schedule_task.xml"
    xml.parent.mkdir(parents=True, exist_ok=True)
    xml.write_bytes(_task_xml(kind, times, hours).encode("utf-16"))  # l'Utilita' di pianificazione vuole UTF-16 con BOM
    try:
        r = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml), "/F"])
    finally:
        xml.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"l'Utilita' di pianificazione non ha creato l'attivita': {(r.stderr or r.stdout).strip()[:200]}")


def _uninstall_schtasks() -> None:
    try:
        _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])  # se non c'era, l'errore si ignora
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass


# ---- Linux: systemd --user e cron ----
def _systemd_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base and os.path.isabs(base) else Path.home() / ".config") / "systemd" / "user"


def _systemd_quote(arg: str, exec_line: bool = False) -> str:
    out = arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    if exec_line:
        out = out.replace("$", "$$")  # in ExecStart systemd espande $VAR e ${VAR}: un "$" nel percorso va raddoppiato
    return '"' + out + '"'


def _systemd_files(kind: str, times: list[tuple[int, int]], hours: int) -> tuple[str, str]:
    cmd = command()
    env_lines = f"Environment={_systemd_quote('JOBSHUNTER_HOME=' + str(settings.home()))}\n"
    if not getattr(sys, "frozen", False):
        env_lines += f"Environment={_systemd_quote('PYTHONPATH=' + str(settings.SOURCE_ROOT))}\n"
    service = ("[Unit]\nDescription=JobsHunter: scansione automatica degli annunci\n\n[Service]\nType=oneshot\n" + env_lines
               + f"ExecStart={' '.join(_systemd_quote(a, True) for a in cmd)}\nNice=10\n")
    if kind == "every":
        when = "OnCalendar=*-*-* 09:00:00\n" if int(hours) >= 24 else f"OnCalendar=*-*-* 00/{int(hours)}:00:00\n"
    else:
        when = "".join(f"OnCalendar=*-*-* {h:02d}:{m:02d}:00\n" for h, m in times)
    timer = ("[Unit]\nDescription=JobsHunter: pianificazione della scansione\n\n[Timer]\n" + when
             + f"Persistent=true\nUnit={SYSTEMD_UNIT}.service\n\n[Install]\nWantedBy=timers.target\n")
    return service, timer


def _install_systemd(kind, times, hours) -> None:
    d = _systemd_dir()
    d.mkdir(parents=True, exist_ok=True)
    service, timer = _systemd_files(kind, times, hours)
    (d / f"{SYSTEMD_UNIT}.service").write_text(service, encoding="utf-8")
    (d / f"{SYSTEMD_UNIT}.timer").write_text(timer, encoding="utf-8")
    for cmd in (["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"]):
        r = _run(cmd)
        if r.returncode != 0:
            raise RuntimeError(f"systemd non ha attivato il timer: {(r.stderr or r.stdout).strip()[:200]}")


def _uninstall_systemd() -> None:
    d = _systemd_dir()
    try:
        if (d / f"{SYSTEMD_UNIT}.timer").exists() or (d / f"{SYSTEMD_UNIT}.service").exists():
            _run(["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT}.timer"])
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass
    for ext in ("timer", "service"):
        (d / f"{SYSTEMD_UNIT}.{ext}").unlink(missing_ok=True)
    try:
        if shutil.which("systemctl"):
            _run(["systemctl", "--user", "daemon-reload"])
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass


def _crontab_read() -> str:
    """Il crontab dell'utente. SOLO "nessun crontab" vale come vuoto: ogni altro errore (permesso negato, timeout, strumento occupato)
    solleva, cosi' non si riscrive mai un crontab che non si e' riusciti a leggere (si perderebbero le righe dell'utente)."""
    try:
        r = _run(["crontab", "-l"])
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"non riesco a leggere il tuo crontab ({type(e).__name__}): non lo modifico") from None
    if r.returncode == 0:
        return r.stdout
    msg = f"{r.stderr or ''} {r.stdout or ''}".lower()
    if "no crontab" in msg or "nessun crontab" in msg:
        return ""  # "no crontab for <utente>": e' vuoto
    raise RuntimeError(f"non riesco a leggere il tuo crontab: non lo modifico ({(r.stderr or r.stdout or '').strip()[:120]})")


def _is_ours(line: str) -> bool:
    """Una riga scritta da JobsHunter: finisce esattamente con il marcatore (non basta che lo contenga)."""
    return line.rstrip().endswith(" " + CRON_MARK) or line.strip() == CRON_MARK


def _crontab_write(text: str) -> None:
    r = _run(["crontab", "-r"]) if not text.strip() else _run(["crontab", "-"], input=text)
    if r.returncode != 0 and text.strip():
        raise RuntimeError(f"cron non ha salvato la pianificazione: {(r.stderr or r.stdout).strip()[:200]}")


def _cron_lines(kind: str, times: list[tuple[int, int]], hours: int) -> list[str]:
    cmd = " ".join(shlex.quote(a) for a in command())
    # notify-send da cron non trova da solo il bus della sessione: si indica (l'id utente si calcola al momento: `$(id -u)`) e lo schermo
    env = "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus DISPLAY=${DISPLAY:-:0} " + f"JOBSHUNTER_HOME={shlex.quote(str(settings.home()))}"
    if not getattr(sys, "frozen", False):
        env += f" PYTHONPATH={shlex.quote(str(settings.SOURCE_ROOT))}"
    log = shlex.quote(str(log_path()))
    body = f"{env} {cmd} >> {log} 2>&1".replace("%", "\\%")  # in cron il % e' un fine riga
    if kind == "every":
        specs = ["0 9 * * *"] if int(hours) >= 24 else [f"0 */{int(hours)} * * *"]
    else:
        specs = [f"{m} {h} * * *" for h, m in times]
    return [f"{sp} {body} {CRON_MARK}" for sp in specs]


def _install_cron(kind, times, hours) -> None:
    log_path().parent.mkdir(parents=True, exist_ok=True)
    keep = [line for line in _crontab_read().splitlines() if not _is_ours(line)]  # se la lettura fallisce solleva: niente viene riscritto
    _crontab_write("\n".join(keep + _cron_lines(kind, times, hours)) + "\n")


def _uninstall_cron() -> None:
    try:
        current = _crontab_read()
        if not any(_is_ours(line) for line in current.splitlines()):
            return
        keep = [line for line in current.splitlines() if not _is_ours(line)]
        _crontab_write(("\n".join(keep) + "\n") if keep else "")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass


def install(kind: str, times: list[tuple[int, int]], hours: int) -> None:
    """Crea (o sostituisce) la pianificazione con lo strumento del sistema."""
    b = backend()
    if not b:
        raise RuntimeError(unsupported_reason())
    if b == "launchd":
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
        return
    _guard_system()
    log_path().parent.mkdir(parents=True, exist_ok=True)
    {"schtasks": _install_schtasks, "systemd": _install_systemd, "cron": _install_cron}[b](kind, times, hours)
    # se il Linux ha cambiato strumento (prima cron, ora systemd) non devono restare due pianificazioni
    if b == "systemd":
        _uninstall_cron()
    elif b == "cron":
        _uninstall_systemd()
    st = _state_path()
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps(_wanted_state(kind, times, hours), ensure_ascii=False), encoding="utf-8")
    fsperm.secure_file(st)


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
    """Toglie la pianificazione (e quella del vecchio nome su macOS). Senza orfani: ripulisce anche gli strumenti non piu' in uso."""
    system = osinfo.current()
    if system == "mac":
        _launchctl("bootout", f"{_domain()}/{LABEL}")
        plist_path().unlink(missing_ok=True)
        remove_legacy()
        return
    _guard_system()
    if system == "windows":
        if shutil.which("schtasks"):
            _uninstall_schtasks()
    else:
        if shutil.which("systemctl"):
            _uninstall_systemd()
        if shutil.which("crontab"):
            _uninstall_cron()
    _state_path().unlink(missing_ok=True)


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
        "supported": supported(), "method": method_label(), "platform": osinfo.current(), "reason": "" if supported() else unsupported_reason(),
        "enabled": cur["enabled"], "installed": is_loaded(),
        "kind": cur["kind"], "times": cur["times"], "hours": cur["hours"], "notify": cur["notify"],
        "next": nxt.strftime("%d/%m/%Y alle %H:%M") if nxt and cur["enabled"] else "",
    }


def ensure_current(cfg: dict) -> bool:
    """All'avvio: se la scansione e' attiva ma la pianificazione manca o punta a un eseguibile o a una cartella diversi
    (app ricostruita, cartella cambiata), la riscrive. Ritorna True se ha riscritto. Mai eccezioni fuori da macOS."""
    cur = current_settings(cfg)
    if not osinfo.is_mac():
        if not cur["enabled"] or not supported():
            return False
        try:
            want = _wanted_state(cur["kind"], cur["_times"], cur["hours"])
            try:
                have = json.loads(_state_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                have = {}
            if have == want and is_loaded():
                return False
            install(cur["kind"], cur["_times"], cur["hours"])
            return True
        except Exception:  # noqa: BLE001 - all'avvio non deve mai rompere l'app
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
