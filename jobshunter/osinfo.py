"""Sistema operativo e cartelle predefinite (macOS, Windows, Linux), in un solo posto.

- macOS (invariato): dati in `~/Library/Application Support/JobsHunter`, log in `~/Library/Logs/JobsHunter`.
- Windows: dati in `%APPDATA%\\JobsHunter`, log in `%LOCALAPPDATA%\\JobsHunter\\Logs`.
- Linux: dati in `$XDG_DATA_HOME/jobshunter` (o `~/.local/share/jobshunter`), log in `$XDG_STATE_HOME/jobshunter` (o `~/.local/state/jobshunter`).

`JOBSHUNTER_HOME` (e la variabile del vecchio nome) restano gestite da `settings.home()`: qui si dice solo dove sta la cartella dell'APP.
Le funzioni accettano `platform`, `env` e `home` per poterle provare simulando un altro sistema (con `PureWindowsPath` e simili).
"""
from __future__ import annotations

import os
import posixpath
import sys
from pathlib import Path

from . import APP_NAME

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")


def current(platform: str | None = None) -> str:
    """'mac', 'windows' o 'linux' (qualunque altro sistema POSIX conta come linux). Legge sys.platform a ogni chiamata."""
    p = platform if platform is not None else sys.platform
    if p == "darwin":
        return "mac"
    if p.startswith("win") or p == "cygwin":
        return "windows"
    return "linux"


def is_mac() -> bool:
    return current() == "mac"


def is_windows() -> bool:
    return current() == "windows"


def is_linux() -> bool:
    return current() == "linux"


def _env(env) -> dict:
    return os.environ if env is None else env


def _home(home):
    return Path.home() if home is None else home


def _folder(base, home, *parts):
    """`base` (testo da una variabile d'ambiente) nella stessa famiglia di percorsi di `home` (Path normale o PureWindowsPath nei test)."""
    return type(home)(base).joinpath(*parts)


def _app_slug(name: str) -> str:
    return name.lower()


def data_dir(name: str = APP_NAME, *, platform: str | None = None, env=None, home=None):
    """Cartella dei dati dell'app (database, configurazione, report, CV)."""
    system, e, h = current(platform), _env(env), _home(home)
    if system == "mac":
        return h / "Library" / "Application Support" / name
    if system == "windows":
        base = e.get("APPDATA")
        return _folder(base, h, name) if base else h / "AppData" / "Roaming" / name
    base = e.get("XDG_DATA_HOME")
    return (_folder(base, h, _app_slug(name)) if base and posixpath.isabs(base) else h / ".local" / "share" / _app_slug(name))


def log_dir(name: str = APP_NAME, *, platform: str | None = None, env=None, home=None):
    """Cartella dei log dell'app."""
    system, e, h = current(platform), _env(env), _home(home)
    if system == "mac":
        return h / "Library" / "Logs" / name
    if system == "windows":
        base = e.get("LOCALAPPDATA")
        return _folder(base, h, name, "Logs") if base else h / "AppData" / "Local" / name / "Logs"
    base = e.get("XDG_STATE_HOME")
    return (_folder(base, h, _app_slug(name)) if base and posixpath.isabs(base) else h / ".local" / "state" / _app_slug(name))


def default_report_dir(*, platform: str | None = None, env=None, home=None):
    """Dove proporre i report: una cartella 'JobsHunter' nei Documenti dell'utente (esiste su tutti e tre i sistemi)."""
    return _home(home) / "Documents" / APP_NAME


def schedule_log_path(**kw):
    return log_dir(**kw) / "scan.log"


def ensure_utf8_streams() -> None:
    """Su Windows la console usa spesso una codifica a 8 bit: i simboli dell'interfaccia a righe di comando non devono mai dare errore."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and (getattr(stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
