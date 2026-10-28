"""Geolocalizzazione offline delle sedi degli annunci (nome citta' -> coordinate).

Usa il dataset di geonamescache (citta' con oltre 15.000 abitanti, nomi alternativi inclusi,
quindi "Milano", "Roma", "Torino" funzionano). Le distanze sono in linea d'aria.
"""
from __future__ import annotations

import math
import re
import unicodedata
from functools import lru_cache

# quartieri/zone che compaiono come "citta'" negli annunci
ALIASES = {"ostiense": "roma", "eur": "roma", "garbatella": "roma", "lingotto": "torino"}
PROVINCE_PREFIX = re.compile(r"^(provincia di|provincia del|citta metropolitana di|province of|metropolitan city of)\s+")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.replace("'", "")).split())


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, list[dict]], list[dict]]:
    import geonamescache

    cities = list(geonamescache.GeonamesCache().get_cities().values())
    idx: dict[str, list[dict]] = {}
    for c in cities:
        for name in [c["name"], *c.get("alternatenames", [])]:
            key = _norm(name)
            if key:
                idx.setdefault(key, []).append(c)
    return idx, cities


def _best(cands: list[dict], country: str | None = None) -> dict:
    """Preferisce una citta' del paese indicato (senza indicazione: l'Italia), poi la piu' popolosa."""
    cc = (country or "IT").upper()
    own = [c for c in cands if c["countrycode"] == cc]
    return max(own or cands, key=lambda c: c["population"])


def lookup(name: str, country: str | None = None) -> dict | None:
    """Trova una citta' per nome (accetta 'Provincia di X'). Ritorna dict con name/lat/lon o None.

    `country` (codice a due lettere) fa preferire le citta' di quel paese quando il nome e' ambiguo."""
    key = _norm(name)
    key = ALIASES.get(key, PROVINCE_PREFIX.sub("", key))
    cands = _index()[0].get(key)
    if not cands:
        return None
    c = _best(cands, country)
    return {"name": c["name"], "lat": c["latitude"], "lon": c["longitude"], "country": c["countrycode"]}


def locate(location: str, country: str | None = None) -> tuple[float, float] | None:
    """Coordinate di una sede testuale tipo 'Milano, Provincia di Milano'. None se generica/ignota.

    Con `country` le citta' omonime di quel paese hanno la precedenza (Birmingham in gb, non negli us)."""
    parts = [p for p in (location or "").split(",")]
    for p in parts[:2]:  # prima la citta', poi eventualmente la provincia
        hit = lookup(p, country)
        if hit:
            return hit["lat"], hit["lon"]
    return None


# nomi inglesi del dataset -> forma italiana usata nei suggerimenti
IT_NAMES = {"Milan": "Milano", "Rome": "Roma", "Turin": "Torino", "Naples": "Napoli", "Florence": "Firenze",
            "Venice": "Venezia", "Genoa": "Genova", "Padua": "Padova", "Mantua": "Mantova", "Syracuse": "Siracusa",
            "Leghorn": "Livorno", "Bolzano-Bozen": "Bolzano", "Reggio nell'Emilia": "Reggio Emilia"}


@lru_cache(maxsize=1)
def _display_names() -> list[tuple[str, dict]]:
    """(nome normalizzato, citta') per i suggerimenti: solo nomi 'normali', italiani per primi."""
    rows = []
    for c in _index()[1]:
        disp = IT_NAMES.get(c["name"], c["name"]) if c["countrycode"] == "IT" else c["name"]
        rows.append((_norm(disp), {"label": disp, "name": c["name"], "country": c["countrycode"], "pop": c["population"]}))
    rows.sort(key=lambda r: (r[1]["country"] != "IT", -r[1]["pop"]))
    return rows


def suggest(prefix: str, limit: int = 8) -> list[dict]:
    """Suggerimenti per l'autocompletamento: nomi che iniziano con `prefix`, citta' italiane per prime."""
    q = _norm(prefix)
    if len(q) < 2:
        return []
    out, seen = [], set()
    for key, info in _display_names():
        if key.startswith(q) and info["label"] not in seen:
            seen.add(info["label"])
            out.append({k: info[k] for k in ("label", "name", "country")})
            if len(out) >= limit:
                break
    return out


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))
