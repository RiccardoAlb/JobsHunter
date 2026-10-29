"""Blocco di file tra processi, uguale su macOS, Linux (fcntl) e Windows (msvcrt).

Serve a far partire una sola scansione alla volta (`autoscan.ScanLock`) e a far aspettare chi arriva dopo durante la
migrazione dei dati (`migrate`). Il blocco cade da solo se il processo muore. Questo e' l'unico modulo che importa fcntl/msvcrt.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

try:  # POSIX
    import fcntl  # type: ignore
except ImportError:  # Windows
    fcntl = None
try:  # Windows
    import msvcrt  # type: ignore
except ImportError:
    msvcrt = None


class FileLock:
    """Blocco esclusivo su un file. `acquire(blocking=False)` ritorna False senza aspettare se qualcun altro lo tiene."""

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.fh = None

    def acquire(self, blocking: bool = True, poll: float = 0.1) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            while True:
                if self._try_lock(fh):
                    self.fh = fh
                    return True
                if not blocking:
                    fh.close()
                    return False
                time.sleep(poll)
        except BaseException:
            fh.close()
            raise

    @staticmethod
    def _try_lock(fh) -> bool:
        if fcntl is not None:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False
        if msvcrt is not None:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        return True  # nessun meccanismo disponibile: nessun blocco (mai un errore)

    def release(self) -> None:
        fh, self.fh = self.fh, None
        if fh is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)
            elif msvcrt is not None:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            fh.close()

    @property
    def held(self) -> bool:
        return self.fh is not None

    def __enter__(self):
        try:
            self.acquire(blocking=True)
        except OSError:
            self.fh = None  # cartella non scrivibile: si prosegue senza blocco, come prima
        return self

    def __exit__(self, *a):
        self.release()
