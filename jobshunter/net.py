"""Client HTTP del progetto: un solo punto da cui nascono tutte le richieste in uscita.

JobsHunter si presenta sempre con il proprio nome (User-Agent dichiarato), mai come un browser. Il contatto
(per esempio un indirizzo email o l'indirizzo della pagina del progetto) e' opzionale e si imposta in
Impostazioni > Avanzate (`net.contact`). Chi vuole un'intestazione diversa puo' impostare `net.user_agent`.
Se un sito rifiuta le richieste (HTTP 403 o 429) il programma non insiste e non cerca di aggirare nulla:
l'annuncio resta "non verificato", mai "chiuso".
"""
from __future__ import annotations

import logging
import re

import httpx

from . import APP_NAME, __version__

# httpx scrive l'indirizzo completo delle richieste (con eventuali chiavi API) nei log di livello INFO: mai
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

MAX_UA = 200
MAX_CONTACT = 120
_BAD = re.compile(r"[^\x20-\x7e]")  # solo ASCII stampabile: niente a capo (header injection) ne' caratteri strani
_current: dict[str, str] = {"ua": ""}


def clean_contact(text: str) -> str:
    text = (text or "").strip()
    if len(text) > MAX_CONTACT:
        raise ValueError(f"contatto troppo lungo (massimo {MAX_CONTACT} caratteri)")
    if _BAD.search(text) or any(c in text for c in "()"):
        raise ValueError("il contatto puo' contenere solo caratteri ASCII e nessuna parentesi")
    return text


def clean_user_agent(text: str) -> str:
    text = (text or "").strip()
    if len(text) > MAX_UA:
        raise ValueError(f"User-Agent troppo lungo (massimo {MAX_UA} caratteri)")
    if _BAD.search(text):
        raise ValueError("l'User-Agent puo' contenere solo caratteri ASCII stampabili")
    return text


def build_user_agent(cfg: dict | None = None) -> str:
    """User-Agent dichiarato: `JobsHunter/<versione> (+personal job search tool; contact: <contatto>)`."""
    net = (cfg or {}).get("net", {}) if isinstance((cfg or {}).get("net", {}), dict) else {}
    try:  # valori a mano nel file di configurazione: quelli non validi si ignorano, uno per uno
        custom = clean_user_agent(str(net.get("user_agent") or ""))
    except ValueError:
        custom = ""
    try:
        contact = clean_contact(str(net.get("contact") or ""))
    except ValueError:
        contact = ""
    if custom:
        return custom
    tail = f"; contact: {contact}" if contact else ""
    return f"{APP_NAME}/{__version__} (+personal job search tool{tail})"


def configure(cfg: dict | None) -> str:
    """Imposta l'User-Agent per tutte le richieste successive del processo (lo chiama settings.load_config)."""
    _current["ua"] = build_user_agent(cfg)
    return _current["ua"]


def user_agent() -> str:
    return _current["ua"] or build_user_agent(None)


def client(*, transport: httpx.BaseTransport | None = None, timeout: float = 20, follow_redirects: bool = False) -> httpx.Client:
    """httpx.Client con l'User-Agent dichiarato. `transport` serve ai test (httpx.MockTransport)."""
    return httpx.Client(headers={"User-Agent": user_agent()}, timeout=timeout, follow_redirects=follow_redirects, transport=transport)


_SECRET_URL = re.compile(r"(?i)((?:app_key|app_id|api_key|key|token)=)[^&\s'\"]+|(/api/)[A-Za-z0-9._-]{8,}")


def redact(text: str) -> str:
    """Toglie chiavi e identificativi dagli indirizzi dentro un messaggio (parametri `app_key=...`, percorsi `/api/<chiave>`)."""
    return _SECRET_URL.sub(lambda m: (m.group(1) or m.group(2)) + "***", str(text))


def _public_host(host: str) -> bool:
    """False per localhost, indirizzi IP privati, di loopback o link-local e per nomi tipici di reti locali (nessuna risoluzione DNS)."""
    import ipaddress

    h = (host or "").strip("[]").lower().rstrip(".")
    if not h or h == "localhost" or h.endswith((".localhost", ".local", ".lan", ".internal", ".home", ".intranet")) or "." not in h and ":" not in h:
        return False
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return True
    return ip.is_global


def safe_get(client: httpx.Client, url: str, max_redirects: int = 5) -> httpx.Response:
    """GET che segue i redirect a mano e si rifiuta di andare verso reti non pubbliche (localhost, LAN, Tailscale...): un annuncio ostile non puo' far interrogare la tua rete."""
    for _ in range(max_redirects + 1):
        if not _public_host(httpx.URL(url).host):
            raise UnsafeURL(f"indirizzo non pubblico: {httpx.URL(url).host}")
        r = client.get(url, follow_redirects=False)
        if r.is_redirect and r.headers.get("location"):
            url = str(r.url.join(r.headers["location"]))
            continue
        return r
    raise UnsafeURL("troppi reindirizzamenti")


class UnsafeURL(httpx.HTTPError):
    """Indirizzo (o reindirizzamento) verso una rete non pubblica: la richiesta non parte."""

    def __init__(self, message: str):
        super().__init__(message)


def ensure_ok(r: httpx.Response) -> None:
    """Come raise_for_status, ma il messaggio non contiene mai l'indirizzo (che puo' portare la chiave API)."""
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} da {r.url.host}")
