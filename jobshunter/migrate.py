"""Migrazione dal vecchio nome (JobHunter) a JobsHunter, senza mai cancellare dati dell'utente.

- Dati: ~/Library/Application Support/JobHunter viene COPIATO in .../JobsHunter (l'originale resta dov'e').
  Se esistono entrambe le cartelle si usa la nuova. Il database copiato viene verificato (integrity_check);
  se qualcosa non torna, la copia incompleta viene tolta e per quella sessione si continua a usare la vecchia cartella.
- LaunchAgent: vedi `scheduler.remove_legacy` (toglie il vecchio `local.jobhunter.scan`).
"""
from __future__ import annotations

import fcntl
import glob
import logging
import os
import re
import shutil
import sqlite3
from pathlib import Path

from . import APP_NAME

log = logging.getLogger("jobshunter.migrate")

OLD_APP_NAME = "JobHunter"
SUPPORT = ("Library", "Application Support")
_SKIP = {"scan.lock"}  # il blocco di una scansione in corso non si copia
_PRIVATE = ("config.toml", "settings.json", "cv.json", "skills_extra.json")


def support_dir(name: str = APP_NAME, home: Path | None = None) -> Path:
    return (home or Path.home()).joinpath(*SUPPORT, name)


def log_dir(name: str = APP_NAME, home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "Logs" / name


_KEY_FILES = ("config.toml", "settings.json", "cv.json", "skills_extra.json")


def _has_content(d: Path) -> bool:
    return d.is_dir() and any(d.iterdir())


def _has_data(d: Path) -> bool:
    """La cartella ha dati veri (un database, la configurazione, le impostazioni o il CV)? Scarti come `webview/` o i log non contano."""
    try:
        return d.is_dir() and any(c.is_file() and (c.suffix == ".db" or c.name in _KEY_FILES) for c in d.iterdir())
    except OSError:
        return False


def _uri(path: Path) -> str:
    return Path(path).absolute().as_uri() + "?mode=ro"  # as_uri codifica % # ? e gli spazi


def db_ok(path: Path) -> bool:
    """True se il file e' un database SQLite integro (apertura in sola lettura)."""
    try:
        con = sqlite3.connect(_uri(path), uri=True)
        try:
            return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _copy_db(src: Path, dst: Path) -> None:
    """Copia coerente anche se il database e' in uso (API di backup di SQLite)."""
    a = sqlite3.connect(_uri(src), uri=True)
    b = sqlite3.connect(dst)
    try:
        with b:
            a.backup(b)
    finally:
        a.close()
        b.close()
    os.chmod(dst, 0o600)


def _copy_tree(src: Path, dst: Path) -> None:
    _copy_impl(src, dst, True)


def _copy_impl(src: Path, dst: Path, top: bool) -> None:
    dst.mkdir(parents=True)
    for item in sorted(src.iterdir()):
        if item.name in _SKIP or item.name.endswith(("-journal", "-wal", "-shm")):
            continue
        target = dst / item.name
        key_file = top and (item.suffix == ".db" or item.name in _KEY_FILES)
        if item.is_symlink():
            # un collegamento a un file di dati (db, config, CV, magari su Dropbox) si copia come file vero;
            # gli altri collegamenti non si seguono (potrebbero portare fuori dalla cartella)
            if not (key_file and item.is_file()):
                log.warning("collegamento simbolico non copiato: %s", item)
                continue
        if item.is_dir():
            _copy_impl(item, target, False)
        elif item.suffix == ".db":
            try:
                _copy_db(item, target)
            except sqlite3.Error:
                if top:
                    raise  # il database principale deve essere valido
                shutil.copy2(item, target)  # un backup non valido si porta dietro com'e' (byte per byte)
                log.warning("file .db non valido copiato com'e': %s", item)
        else:
            shutil.copy2(item, target)
            if item.name in _PRIVATE:
                os.chmod(target, 0o600)
    try:  # i permessi della cartella non devono essere piu' larghi dell'originale (ma l'utente deve poterci scrivere)
        os.chmod(dst, (src.stat().st_mode & 0o777) | 0o700)
    except OSError:
        pass


def _rewrite_paths(tmp: Path, old: Path, new: Path) -> None:
    """Percorsi assoluti verso la vecchia cartella dentro config.toml e settings.json: si riscrivono verso la nuova."""
    for name in ("config.toml", "settings.json"):
        f = tmp / name
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="surrogateescape")
        new_text = re.sub(re.escape(str(old)) + r'(?=[/"\'])', lambda m: str(new), text)
        if new_text != text:
            f.write_text(new_text, encoding="utf-8", errors="surrogateescape")
            log.info("percorsi assoluti in %s riscritti verso %s", name, new)


class _Lock:
    """Blocco tra processi (app e scansione pianificata che partono insieme): chi arriva dopo aspetta e poi trova la cartella nuova."""

    def __init__(self, path: Path):
        self.path, self.fh = path, None

    def __enter__(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = open(self.path, "w")
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except OSError:
            self.fh = None
        return self

    def __exit__(self, *a):
        if self.fh:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
            finally:
                self.fh.close()


def migrate_app_data(old: Path | None = None, new: Path | None = None) -> tuple[Path, str]:
    """Ritorna (cartella da usare, esito). Esiti: 'new' (c'era gia' la nuova), 'fresh' (nessuna cartella),
    'copied' (copiata e verificata), 'failed' (copia non riuscita: si usa la vecchia)."""
    old = old or support_dir(OLD_APP_NAME)
    new = new or support_dir(APP_NAME)
    if _has_data(new):
        return new, "new"
    if not _has_data(old) and not _has_content(old):
        return new, "fresh"
    with _Lock(new.with_name(f".{new.name}.migrate.lock")):
        if _has_data(new):  # un altro processo ha finito mentre aspettavamo
            return new, "new"
        for stale in new.parent.glob(glob.escape(new.name) + ".migrating-*"):
            shutil.rmtree(stale, ignore_errors=True)  # residui di tentativi interrotti (siamo gli unici a migrare: c'e' il blocco)
        tmp = new.with_name(new.name + f".migrating-{os.getpid()}")
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            _copy_tree(old, tmp)
            for db in tmp.glob("*.db"):
                if not db_ok(db):
                    raise RuntimeError(f"verifica del database non riuscita: {db.name}")
            _rewrite_paths(tmp, old, new)
            if new.exists():  # solo scarti (webview/, log): si portano dentro la copia, poi la cartella resta vuota
                if _has_data(new):
                    return new, "new"
                for item in new.iterdir():
                    dest = tmp / item.name
                    if dest.exists():  # stesso nome nella copia: lo scarto della nuova cartella si conserva con un altro nome
                        dest = tmp / (item.name + ".nuovo")
                    shutil.move(str(item), str(dest))
                new.rmdir()
            tmp.rename(new)
        except BaseException as e:  # noqa: BLE001 - qualunque cosa (anche Ctrl+C): i dati veri restano dove sono
            shutil.rmtree(tmp, ignore_errors=True)
            if not isinstance(e, Exception):
                raise
            if _has_data(new):  # qualcun altro ha vinto la corsa: si usa la sua cartella, mai quella vecchia
                return new, "new"
            log.error("migrazione dei dati non riuscita (%s): si continua con la cartella %s", e, old)
            return old, "failed"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    log.info("dati copiati da %s a %s (l'originale e' rimasto)", old, new)
    return new, "copied"
