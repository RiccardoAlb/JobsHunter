"""Avvio di programmi esterni: su Windows senza far comparire una finestra nera (CREATE_NO_WINDOW), altrove niente di diverso."""
from __future__ import annotations

from . import osinfo

CREATE_NO_WINDOW = 0x08000000  # lo stesso valore di subprocess.CREATE_NO_WINDOW (che esiste solo su Windows)


def extra() -> dict:
    """Argomenti in piu' per subprocess.run/Popen: {"creationflags": CREATE_NO_WINDOW} su Windows, {} su macOS e Linux. Va usato con `**`."""
    return {"creationflags": CREATE_NO_WINDOW} if osinfo.is_windows() else {}


def run(cmd, **kw):
    """`subprocess.run` che su Windows parte senza finestra nera. (Se un sistema non-Windows simulato rifiuta `creationflags`, si riprova senza.)"""
    import subprocess

    try:
        return subprocess.run(cmd, **{**extra(), **kw})
    except ValueError as e:
        if "creationflags" not in str(e):
            raise
        return subprocess.run(cmd, **kw)
