"""Verifica se un annuncio e' ancora aperto o se non accetta piu' candidature.

Regole prudenti: un annuncio e' "chiuso" solo con un segnale affidabile (pagina rimossa con HTTP 404 o 410,
data di scadenza dichiarata nella pagina e gia' passata). Un blocco del sito (HTTP 403 o 429) NON vuol dire che
l'annuncio e' chiuso: il controllo si ferma e l'annuncio resta "non verificato".

Fonti: Adzuna (pagina), Greenhouse e Lever (API pubbliche). Jooble non e' verificabile (pagine protette da
anti-bot, che non si aggirano). Per le altre fonti si riconosce solo la pagina rimossa.
"""
from __future__ import annotations

import re
import time
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx

from . import net
from .fulltext import parse_adzuna

OPEN, CLOSED, UNKNOWN = "open", "closed", "unknown"
DELAY = 2.0  # secondi tra una richiesta e l'altra: i siti limitano le raffiche


@dataclass
class Result:
    state: str = UNKNOWN
    note: str = ""
    valid_until: str | None = None
    text: str = ""
    salary: str = ""
    blocked: bool = False


def adzuna_pages_enabled(cfg: dict | None) -> bool:
    """Interruttore "Scarica il testo completo degli annunci Adzuna" (predefinito: attivo). Spento, le pagine Adzuna non si leggono mai."""
    if not cfg:
        return True
    return bool((cfg.get("sources", {}).get("adzuna", {}) or {}).get("full_text", True))


def checkable(source: str, url: str, cfg: dict | None = None) -> bool:
    if (source or "").startswith("adzuna") and not adzuna_pages_enabled(cfg):
        return False
    return bool(url) and not (source or "").startswith("jooble")


def is_stale(checked_at: str | None, hours: float) -> bool:
    if not checked_at:
        return True
    try:
        then = datetime.fromisoformat(checked_at)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - then > timedelta(hours=hours)


def day_label(iso_day: str | None) -> str:
    if not iso_day:
        return ""
    y, m, d = iso_day[:10].split("-")
    return f"{d}/{m}/{y}"


def _blocked(status: int) -> Result:
    return Result(UNKNOWN, f"il sito sta limitando le richieste (HTTP {status}): riprova piu' tardi", blocked=True)


def _check_adzuna(client: httpx.Client, url: str) -> Result:
    r = net.safe_get(client, url)
    if r.status_code in (404, 410):
        return Result(CLOSED, f"annuncio rimosso (HTTP {r.status_code})")
    if r.status_code in (403, 429):
        return _blocked(r.status_code)
    if r.status_code != 200:
        return Result(UNKNOWN, f"risposta inattesa del sito (HTTP {r.status_code})")
    p = parse_adzuna(r.text)
    if not p:
        return Result(UNKNOWN, "pagina in un formato non riconosciuto")
    res = Result(OPEN, "annuncio presente", p["valid_until"], p["text"], p["salary"])
    if p["valid_until"] and p["valid_until"] < date.today().isoformat():
        res.state, res.note = CLOSED, f"scaduto il {day_label(p['valid_until'])}"
    return res


def _check_greenhouse(client: httpx.Client, url: str, source: str) -> Result:
    board = source.split(":", 1)[1] if ":" in source else ""
    m = re.search(r"/jobs/(\d+)", url) or re.search(r"gh_jid=(\d+)", url)
    if not (board and m):
        return Result(UNKNOWN, "non verificabile: identificativo non riconosciuto")
    r = client.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{m.group(1)}")
    if r.status_code in (404, 410):
        return Result(CLOSED, "posizione non piu' presente sulla pagina carriere")
    if r.status_code in (403, 429):
        return _blocked(r.status_code)
    return Result(OPEN, "posizione presente sulla pagina carriere") if r.status_code == 200 else Result(UNKNOWN, f"risposta inattesa (HTTP {r.status_code})")


def _check_lever(client: httpx.Client, url: str, source: str) -> Result:
    company = source.split(":", 1)[1] if ":" in source else ""
    m = re.search(r"lever\.co/[^/]+/([0-9a-f-]{36})", url)
    if not (company and m):
        return Result(UNKNOWN, "non verificabile: identificativo non riconosciuto")
    r = client.get(f"https://api.lever.co/v0/postings/{company}/{m.group(1)}")
    if r.status_code in (404, 410):
        return Result(CLOSED, "posizione non piu' presente sulla pagina carriere")
    if r.status_code in (403, 429):
        return _blocked(r.status_code)
    return Result(OPEN, "posizione presente sulla pagina carriere") if r.status_code == 200 else Result(UNKNOWN, f"risposta inattesa (HTTP {r.status_code})")


def _check_generic(client: httpx.Client, url: str) -> Result:
    r = net.safe_get(client, url)
    if r.status_code in (404, 410):
        return Result(CLOSED, f"pagina rimossa (HTTP {r.status_code})")
    if r.status_code in (403, 429):
        return _blocked(r.status_code)
    return Result(UNKNOWN, "non verificabile: la fonte non indica se l'annuncio e' ancora aperto")


def check(client: httpx.Client, url: str, source: str) -> Result:
    """Controlla un annuncio con UNA richiesta. Non solleva eccezioni di rete: le riporta come 'non verificato'."""
    if (source or "").startswith("jooble"):
        return Result(UNKNOWN, "non verificabile: le pagine di Jooble sono protette da anti-bot")
    try:
        if "adzuna." in url:
            return _check_adzuna(client, url)
        if source.startswith("gh:"):
            return _check_greenhouse(client, url, source)
        if source.startswith("lever:"):
            return _check_lever(client, url, source)
        return _check_generic(client, url)
    except httpx.HTTPError as e:
        return Result(UNKNOWN, f"errore di rete ({type(e).__name__})")


def apply(db, row, res: Result) -> None:
    """Salva l'esito di un controllo (e il testo completo, se la pagina l'ha dato e mancava)."""
    db.set_avail(row["uid"], res.state, res.valid_until, res.note)
    if res.text and not row["full_text"]:
        db.set_full_text(row["uid"], res.text, res.salary)


def run_check(db, cfg: dict, *, uids: list[str] | None = None, limit: int = 30, force: bool = False,
              cancel: threading.Event | None = None, on_progress=None, delay: float | None = None) -> dict:
    """Controlla un lotto di annunci, uno alla volta e con calma. Si ferma al primo blocco del sito.

    uids: solo questi annunci (con force=True si ricontrollano anche quelli recenti o gia' chiusi).
    Ritorna {checked, open, closed, unknown, blocked, total}.
    """
    hours = cfg.get("availability", {}).get("recheck_hours", 24)
    rows = [r for r in db.to_check(hours=hours, limit=limit, uids=uids, force=force) if checkable(r["source"], r["url"], cfg)]
    out = {"total": len(rows), "checked": 0, "open": 0, "closed": 0, "unknown": 0, "blocked": False}
    pause = DELAY if delay is None else delay
    with net.client(timeout=20, follow_redirects=True) as c:
        for i, row in enumerate(rows, 1):
            if cancel is not None and cancel.is_set():
                break
            res = check(c, row["url"], row["source"])
            if res.blocked:
                out["blocked"] = True
                break
            apply(db, row, res)
            out["checked"] += 1
            out[res.state] += 1
            if on_progress:
                on_progress(i, len(rows), row, res)
            if i < len(rows):
                time.sleep(pause)
    return out
