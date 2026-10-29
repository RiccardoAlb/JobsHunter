"""Operazioni su file che su Windows possono fallire per un attimo (file aperto da un altro processo o thread, antivirus).

Su Windows `os.replace` e l'apertura di un file ricevono `PermissionError` se qualcun altro lo sta leggendo in quell'istante;
su macOS e Linux questo non succede. Qui si riprova qualche volta a breve distanza, SOLO su Windows: altrove il comportamento e' identico a prima.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from . import osinfo

TRIES = 12
DELAY = 0.05


def retry(fn, *args, tries: int = TRIES, delay: float = DELAY):
    """Esegue `fn(*args)`; su Windows riprova se riceve PermissionError (l'ultimo errore viene sollevato)."""
    if not osinfo.is_windows():
        return fn(*args)
    for i in range(tries):
        try:
            return fn(*args)
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(delay * (1 + i / 2))


def replace(src, dst) -> None:
    """`os.replace` che su Windows riprova se il file di destinazione e' aperto per un attimo."""
    retry(os.replace, src, dst)


def read_text(path, encoding: str = "utf-8") -> str:
    return retry(lambda: Path(path).read_text(encoding=encoding))


def unlink(path, missing_ok: bool = True) -> None:
    retry(lambda: Path(path).unlink(missing_ok=missing_ok))
