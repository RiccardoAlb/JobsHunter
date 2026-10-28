from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone

import httpx

from .. import net
from ..models import Job

def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Client HTTP. `transport` permette ai test di sostituire la rete con httpx.MockTransport."""
    return net.client(transport=transport, timeout=20, follow_redirects=True)


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            if value > 1e11:  # millisecondi
                value /= 1000
            return datetime.fromtimestamp(value, tz=timezone.utc)
        value = re.sub(r"(\.\d{6})\d+", r"\1", str(value).replace("Z", "+00:00"))
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# Ricerche dedicate a stage e tirocini (usate da Adzuna e Jooble, disattivabili dalle Impostazioni)
DEFAULT_INTERNSHIP_QUERIES = ["stage cyber security", "tirocinio sicurezza informatica", "internship cybersecurity", "stage sistemista"]


class Cancelled(Exception):
    """Scan interrotto (stop manuale o tempo massimo)."""


class Source:
    name = "base"
    cancel: threading.Event | None = None
    deadline: float | None = None

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def check(self) -> None:
        """Da chiamare tra una richiesta e l'altra: permette di fermare lo scan."""
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled("fermato dall'utente")
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise Cancelled("tempo massimo raggiunto")

    def queries_with_pages(self, default: list[str], pages: tuple = (1, 2)) -> list[tuple[str, tuple]]:
        """Le ricerche da fare, ciascuna con le pagine da leggere. Gli stage si cercano solo in prima pagina."""
        out = [(q, pages) for q in self.cfg.get("queries", default)]
        if self.cfg.get("_internships", True):
            out += [(q, pages[:1]) for q in self.cfg.get("internship_queries", DEFAULT_INTERNSHIP_QUERIES)]
        return out

    def http(self) -> httpx.Client:
        return client(self.cfg.get("_transport"))

    def pause(self) -> None:
        """Piccola attesa tra due richieste allo stesso sito (cortesia verso il servizio, interrompibile)."""
        delay = float(self.cfg.get("delay", 0.0))
        end = time.monotonic() + delay
        while delay > 0 and time.monotonic() < end:
            self.check()
            time.sleep(min(0.1, max(0.0, end - time.monotonic())))

    def fetch(self) -> list[Job]:
        raise NotImplementedError

    def fetch_queries(self, queries: list) -> list[Job]:
        """Legge gli annunci per le ricerche dei profili (`profiles.Query`).

        Le fonti che non cercano per parole chiave (elenchi globali, pagine carriere) ignorano le ricerche e
        restituiscono tutto: il filtro lo fa poi il punteggio di ciascun profilo."""
        return self.fetch()
