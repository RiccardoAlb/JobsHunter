"""Scansione "da sola": blocco contro scansioni sovrapposte, cronologia, notifiche.

Serve sia alla scansione pianificata (anche con l'app chiusa) sia al pulsante Scan della GUI, cosi' una sola
scansione alla volta tocca il database e ogni esecuzione finisce nella cronologia.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from . import APP_NAME, osinfo, proc, settings
from .filelock import FileLock
from .db import DB
from .notify import send_ntfy
from .scanner import ScanResult, run_scan

log = logging.getLogger("jobshunter.autoscan")


class ScanLock:
    """Blocco su file: se un'altra scansione e' in corso, `acquire()` ritorna False senza aspettare."""

    def __init__(self) -> None:
        self.path = settings.home() / "scan.lock"
        self._lock = FileLock(self.path)

    @property
    def fh(self):
        return self._lock.fh

    def acquire(self) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        self._lock.release()


_REAL_SUBPROCESS_RUN = subprocess.run

_TOAST_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime];"
    "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
    "$t=$x.GetElementsByTagName('text');"
    "[void]$t.Item(0).AppendChild($x.CreateTextNode($env:JH_TITLE));"
    "[void]$t.Item(1).AppendChild($x.CreateTextNode($env:JH_BODY));"
    "$id='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show([Windows.UI.Notifications.ToastNotification]::new($x))"
)


def notify_native(title: str, body: str) -> bool:
    """Notifica del sistema: macOS (osascript), Windows (toast tramite PowerShell), Linux (notify-send). Sempre best effort: False se non disponibile."""
    system = osinfo.current()
    if os.environ.get("PYTEST_CURRENT_TEST") and subprocess.run is _REAL_SUBPROCESS_RUN:
        return False  # sotto pytest nessuna notifica vera (nemmeno osascript su macOS), a meno che il test non sostituisca subprocess.run
    title, body = str(title).replace("\x00", ""), str(body).replace("\x00", "")  # un NUL farebbe rifiutare il comando al sistema
    try:
        if system == "mac":
            def esc(s: str) -> str:
                return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

            script = f'display notification "{esc(body)[:220]}" with title "{esc(title)[:80]}"'
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=10)
            return True
        if system == "windows":
            if not shutil.which("powershell"):
                return False
            env = {**os.environ, "JH_TITLE": title[:80], "JH_BODY": body[:220]}  # per variabile d'ambiente: nessun problema di virgolette
            r = proc.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _TOAST_SCRIPT], env=env, capture_output=True, timeout=20)
            return r.returncode == 0
        if shutil.which("notify-send"):
            r = subprocess.run(["notify-send", "--app-name", APP_NAME, "--", title[:80], body[:220]], capture_output=True, timeout=10)
            return r.returncode == 0
        return False
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def build_message(db: DB, cfg: dict, started: str, res: ScanResult) -> tuple[str, str] | None:
    """Titolo e testo della notifica, o None se non c'e' nulla da dire."""
    if res.new <= 0:
        return None
    min_score = int(cfg.get("notify", {}).get("min_score", 40))
    rows = db.new_since(started, limit=50)
    good = [r for r in rows if r["score"] >= min_score]
    head = f"{res.new} nuovi annunci" + (f", {len(good)} con punteggio alto" if good else "")
    top = (good or rows)[:3]
    body = "; ".join(f"{r['title'][:44]} ({r['company'][:22]})" for r in top)
    if res.closed_found:
        body += f". {res.closed_found} annunci risultano chiusi."
    return f"{APP_NAME}: {head}", body


def run_auto(cfg: dict, db: DB, *, kind: str = "auto", cancel=None, on_event=None,
             notify: bool = True, profile_ids: list[int] | None = None) -> tuple[ScanResult | None, dict]:
    """Esegue una scansione completa con blocco, cronologia e (se richiesto) notifiche.

    Ritorna (risultato, info). Se un'altra scansione e' in corso, risultato None e info["skipped"] True.
    """
    lock = ScanLock()
    if not lock.acquire():
        return None, {"skipped": True, "message": "un'altra scansione è già in corso"}
    started = datetime.now(timezone.utc).isoformat()
    try:
        res = run_scan(cfg, db, cancel=cancel, on_event=on_event, profile_ids=profile_ids)
        notified = 0
        if notify and not res.cancelled and cfg.get("schedule", {}).get("notify", True):
            msg = build_message(db, cfg, started, res)
            if msg and notify_native(*msg):
                notified = 1
            notif = cfg.get("notify", {})
            if notif.get("topic"):  # ntfy: arriva anche sul telefono
                rows = db.unnotified(int(notif.get("min_score", 40)))
                if rows and send_ntfy(notif, rows):
                    db.mark_notified([r["uid"] for r in rows])
                    notified = 1
        run_id = db.add_scan_run(
            started=started, finished=datetime.now(timezone.utc).isoformat(), kind=kind, read=res.read, kept=res.kept,
            new=res.new, closed=res.closed_found, dups=res.dups_new, cancelled=int(res.cancelled),
            blocked=int(res.check_blocked), errors="; ".join(f"{n}: {e}" for n, e in res.errors), notified=notified)
        return res, {"skipped": False, "run_id": run_id, "notified": bool(notified)}
    finally:
        lock.release()


def run_headless(kind: str = "auto") -> int:
    """Punto d'ingresso senza finestra: lo usano `./jh scan-auto` e `JobsHunter --scan-once`."""
    cfg = settings.load_config(create_if_missing=settings.auto_create())
    db = DB(settings.resolve_path(cfg["general"]["db_path"]))
    res, info = run_auto(cfg, db, kind=kind)
    if info.get("skipped"):
        log.info("scansione saltata: %s", info["message"])
        return 0
    log.info("scansione completata: %d letti, %d rilevanti, %d nuovi, %d chiusi, %d duplicati%s",
             res.read, res.kept, res.new, res.closed_found, res.dups_new,
             f", errori: {json.dumps([n for n, _ in res.errors])}" if res.errors else "")
    return 0


def main_scan_once() -> None:
    """Esecuzione dall'app impacchettata (senza finestra), pianificata da launchd."""
    from pathlib import Path

    from . import migrate

    data_dir, _ = migrate.migrate_app_data()  # prima di tutto: non deve nascere una cartella nuova vuota accanto ai dati vecchi
    os.environ.setdefault("JOBSHUNTER_HOME", str(data_dir))
    log_dir = migrate.log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir / "scan.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        sys.exit(run_headless())
    except Exception:
        log.exception("scansione automatica fallita")
        sys.exit(1)
