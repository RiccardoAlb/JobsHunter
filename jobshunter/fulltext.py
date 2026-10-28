"""Legge la pagina di un annuncio Adzuna: testo completo, stipendio e data di scadenza."""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from . import net

_VALID_THROUGH = re.compile(r'"validThrough"\s*:\s*"(\d{4}-\d{2}-\d{2})')


def _tidy(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # i titoli interni all'annuncio non devono rubare i livelli di heading al report
    text = re.sub(r"(?m)^#{1,6}\s+", "#### ", text)
    return text.strip()


def parse_adzuna(html: str) -> dict | None:
    """Estrae {text, salary, valid_until} da una pagina annuncio, o None se il formato non e' riconosciuto.

    valid_until e' la data di scadenza dichiarata nei dati strutturati della pagina (YYYY-MM-DD), se c'e'.
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("section.adp-body")
    if not body:
        return None
    for br in body.find_all("br"):
        br.replace_with("\n")
    paragraphs = [p.get_text("").strip() for p in body.find_all("p")] or [body.get_text("\n")]
    text = _tidy("\n\n".join(p for p in paragraphs if p))
    sal = soup.select_one("[class*=salary]")
    m = _VALID_THROUGH.search(html)
    return {"text": text, "salary": sal.get_text(" ", strip=True) if sal else "", "valid_until": m.group(1) if m else None}


def fetch_full(client: httpx.Client, url: str) -> tuple[str, str]:
    """Ritorna (testo, stipendio). Testo vuoto se la pagina non e' parsabile o non e' di Adzuna."""
    if "adzuna." not in url:
        return "", ""
    r = net.safe_get(client, url)
    if r.status_code in (403, 429):  # il sito limita le richieste: niente testo, nessun tentativo di aggirare
        return "", ""
    r.raise_for_status()
    p = parse_adzuna(r.text)
    return (p["text"], p["salary"]) if p else ("", "")
