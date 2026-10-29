"""Permessi riservati su file e cartelle dell'utente (database, impostazioni, CV, chiavi, copie di sicurezza).

- POSIX (macOS, Linux): `chmod` 600 per i file e 700 per le cartelle, come sempre.
- Windows: `chmod` non protegge niente, quindi si prova `icacls` (solo l'utente corrente ha accesso, nemmeno SYSTEM). E' un tentativo: se non riesce
  non solleva errori e lo scrive nel log una volta sola. L'utente si indica per SID (`whoami /user`), con ripiego su DOMINIO\\utente e sul solo nome
  (solo se icacls risponde 1332 "nessun mapping"). Prima si AGGIUNGE l'accesso, poi si tolgono i permessi ereditati, e si controlla di poter ancora
  aprire il file (altrimenti `/reset`): un errore non puo' mai lasciare il file inaccessibile.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from . import osinfo, proc

log = logging.getLogger("jobshunter.fsperm")
_warned = [False]


def _warn_once(msg: str) -> None:
    if not _warned[0]:
        _warned[0] = True
        log.warning("%s", msg)


ERROR_NONE_MAPPED = 1332  # icacls: "nessun mapping tra nomi di account e SID"


def _windows_user() -> str:
    user = os.environ.get("USERNAME") or ""
    domain = os.environ.get("USERDOMAIN") or ""
    return f"{domain}\\{user}" if domain and user else user


def _whoami_output() -> str | None:
    """Output di `whoami /user /fo csv /nh` (solo su Windows vero), oppure None. Le prove lo sostituiscono."""
    if not sys.platform.startswith("win"):
        return None
    try:
        r = proc.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, timeout=20)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 and isinstance(r.stdout, bytes) else None


_SID = re.compile(r"^S-1-\d+(?:-\d+)+$")


def _user_sid() -> str | None:
    """SID dell'utente corrente (S-1-5-21-...): funziona con account locali, Microsoft, di dominio e di gruppo di lavoro, dove `DOMINIO\\utente` a volte non si risolve."""
    out = _whoami_output()
    if not out:
        return None
    for line in out.splitlines():
        parts = [x.strip().strip('"') for x in line.split(",")]
        if len(parts) >= 2 and _SID.match(parts[-1]):
            return parts[-1]
    return None


def _grant_candidates() -> list[str]:
    """Come indicare l'utente a icacls, dal piu' affidabile: il SID (con l'asterisco), poi DOMINIO\\utente, poi il solo nome."""
    out = []
    sid = _user_sid()
    if sid:
        out.append("*" + sid)
    user, plain = _windows_user(), os.environ.get("USERNAME") or ""
    for who in (user, plain):
        if who and who not in out:
            out.append(who)
    return out


def _accessible(p: Path, is_dir: bool) -> bool:
    """Il file (o la cartella) si puo' ancora leggere dopo aver tolto i permessi ereditati?"""
    try:
        if is_dir:
            os.listdir(p)
        else:
            with open(p, "rb") as f:
                f.read(1)
        return True
    except OSError:
        return False


def _icacls(path: Path, is_dir: bool) -> bool:
    """Lascia l'accesso al solo utente corrente. Mai toglie l'ereditarieta' se nessuna concessione e' riuscita e, dopo averla tolta,
    controlla di poter ancora aprire il file (altrimenti ripristina con /reset). Si guardano solo i codici di ritorno: l'output e' localizzato."""
    names = _grant_candidates()
    if not names:
        return False
    run = dict(capture_output=True, timeout=20)  # byte (l'output di icacls usa la tabella OEM): mai decodificato
    try:
        granted = False
        for who in names:
            grant = f"{who}:(OI)(CI)F" if is_dir else f"{who}:F"
            rc = proc.run(["icacls", str(path), "/grant:r", grant], **run).returncode
            if rc == 0:
                granted = True
                break
            if rc != ERROR_NONE_MAPPED:
                return False  # un altro errore (permesso negato...): non si insiste
        if not granted:
            return False
        if proc.run(["icacls", str(path), "/inheritance:r"], **run).returncode != 0:
            return False
        if not _accessible(path, is_dir):
            proc.run(["icacls", str(path), "/reset"], **run)  # ripristina i permessi ereditati: meglio meno protetto che inaccessibile
            return False
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _secure(path, mode: int, is_dir: bool) -> bool:
    """Protegge SOLO un file (o una cartella) che esiste davvero: percorso vuoto, "." e tipi sbagliati non toccano niente."""
    try:
        if path is None or str(path).strip() in ("", "."):
            return False  # Path("") e' "." = la cartella corrente: non la si deve mai toccare
        p = Path(path)
        if not (p.is_dir() if is_dir else p.is_file()):
            _warn_once("Non sono riuscito a proteggere un file dei dati (non esiste o non e' del tipo atteso)")
            return False
        if osinfo.is_windows():
            ok = _icacls(p, is_dir)
            if not ok:
                _warn_once("Non sono riuscito a limitare l'accesso ai file dei dati (icacls): su questo computer potrebbero essere leggibili da altri utenti.")
            return ok
        os.chmod(p, mode)
        return True
    except (OSError, TypeError, ValueError) as e:
        _warn_once(f"Non sono riuscito a proteggere un file dei dati ({type(e).__name__})")
        return False


def secure_file(path) -> bool:
    """Solo l'utente puo' leggere e scrivere il file. True se riuscito; mai eccezioni."""
    return _secure(path, 0o600, False)


def secure_dir(path) -> bool:
    """Solo l'utente puo' entrare nella cartella. True se riuscito; mai eccezioni."""
    return _secure(path, 0o700, True)
