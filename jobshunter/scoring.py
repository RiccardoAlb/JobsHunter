from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from .models import Job


# stage e tirocini: bonus predefinito, valido anche se la configurazione non li elenca
CAT_BONUS_TITLE = 4  # bonus massimo di una categoria personale che riconosce l'annuncio (parola nel titolo)
CAT_BONUS_BODY = 2   # idem, parola solo nel testo
DEFAULT_BONUS = {"stage": 10, "tirocinio": 10, "tirocinante": 8, "internship": 8, "apprendistato": 6}


# desinenze ammesse dopo la parola chiave: "pentest" riconosce anche "pentester" e "pentesting",
# "penetration test" anche "penetration tester". Con i confini di parola "soc" continua a non matchare "social".
_SUFFIX = r"(?:er|ers|ing|s)?"


def _has(term: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}{_SUFFIX}(?![a-z0-9])", text) is not None


def _location_ok_legacy(job: Job, cfg: dict) -> bool:
    loc = cfg.get("location", {})
    place = job.location.lower()
    haystack = f"{place} {job.title.lower()}"
    strong = [i.lower() for i in loc.get("include", []) if i.lower() not in ("remote", "remoto")]
    if any(_has(i, haystack) for i in strong):
        return True  # sede esplicitamente in una zona che ci interessa
    if any(_has(x, place) for x in loc.get("exclude", [])):
        return False  # remoto ristretto a paesi non utili (es. "Remote - USA")
    if job.remote and loc.get("allow_remote", True):
        return True
    return place.strip() in ("remote", "worldwide", "anywhere", "emea", "europe")


def _score_legacy(job: Job, cfg: dict) -> Job | None:
    """Punteggio storico (solo cybersecurity, tutto da `cfg`). Ritorna None se l'annuncio va scartato."""
    title = job.title.lower()
    body = job.description.lower()

    if any(_has(b, title) for b in cfg["penalties"]["blacklist"]):
        return None

    if job.posted_at:
        age = datetime.now(timezone.utc) - job.posted_at
        if age > timedelta(days=cfg["general"]["max_age_days"]):
            return None

    totals: dict[str, int] = {}
    matched: list[str] = []
    for cat in cfg["keywords"].values():
        sub = 0
        for term, weight in cat["terms"].items():
            if _has(term, title):
                sub += weight * 3
                matched.append(term)
            elif _has(term, body):
                sub += weight
                matched.append(term)
        totals[cat["label"]] = sub

    score = sum(totals.values())
    if score == 0:
        return None

    for term, delta in cfg["penalties"]["title_terms"].items():
        if _has(term, title):
            score += delta
    for term, delta in {**DEFAULT_BONUS, **cfg["bonus"]["title_terms"]}.items():
        if _has(term, title):
            score += delta

    # categoria: la piu' forte, ma se RED e BLUE sono entrambe alte e' "PURPLE"
    loc_cfg = cfg.get("location", {})
    place = job.location.lower()
    if job.near_home or any(_has(h.lower(), place) for h in loc_cfg.get("home_names", [])):
        job.near_home = True
        if score >= loc_cfg.get("home_min_score", 20):
            score += loc_cfg.get("home_bonus", 20)

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    category = ranked[0][0]
    if totals.get("RED", 0) >= 12 and totals.get("BLUE", 0) >= 12:
        category = "PURPLE"

    job.score = max(score, 0)
    job.category = category
    job.matched = sorted(set(matched))
    return job


# ------------------------------------------------------------------ profili ----
def fold(text: str) -> str:
    """Minuscolo e senza accenti: 'contabilità' e 'contabilita' sono la stessa parola."""
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


@lru_cache(maxsize=4096)
def _flex_pattern(term: str):
    """Come `_has`, ma riconosce anche femminile/plurale: infermiere, infermiera, infermieri; developer, developers."""
    t = fold(term).strip()
    if len(t) >= 5 and t[-1] in "aeio":
        core, ends = re.escape(t[:-1]), r"(?:[aeio]|er|ers|s)?"
    else:
        core, ends = re.escape(t), r"(?:s|es|er|ers|ing|i|e)?"
    return re.compile(rf"(?<![a-z0-9]){core}{ends}(?![a-z0-9])")


def has_flex(term: str, text: str) -> bool:
    return _flex_pattern(term).search(text) is not None


def _country_aliases(code: str) -> list[str]:
    from .profiles import COUNTRIES

    c = COUNTRIES.get(code, {})
    return [a for a in c.get("aliases", [])] + [c.get("name", "").lower(), c.get("local", "").lower()]


_IT_REGIONS = ("lombardia", "lazio", "sicilia", "piemonte", "veneto", "campania", "puglia", "toscana", "emilia romagna",
               "emilia-romagna", "liguria", "sardegna", "calabria", "marche", "abruzzo", "umbria", "friuli venezia giulia",
               "trentino alto adige", "trentino-alto adige", "basilicata", "molise", "valle d'aosta")


def _city_in_countries(location: str, countries: list[str]) -> bool:
    """La prima parte della sede e' una citta' di uno dei paesi indicati? (dataset offline di geonamescache)"""
    from . import geo

    first = (location or "").split(",")[0]
    for c in countries:
        hit = geo.lookup(first, c)
        if hit and hit["country"].lower() == c:
            return True
    return False


def location_ok(job: Job, cfg: dict, profile=None) -> bool:
    """Filtro sede. Senza profilo: regola storica (Italia/remoto). Con profilo: paesi del profilo o remoto."""
    if profile is None:
        return _location_ok_legacy(job, cfg)
    from .profiles import as_profile

    p = as_profile(profile)
    place = fold(job.location or "")
    loc = cfg.get("location", {}) or {}
    remote_flag = bool(job.remote) or place.strip() in ("remote", "remoto", "worldwide", "anywhere", "emea", "europe")
    if remote_flag and not p.remote:
        return False
    if job.country:
        if job.country in p.countries:
            return True
        if not (p.remote and remote_flag):
            return False
    # sede di paese ignoto (fonti globali) o remoto di un altro paese: si guarda il testo
    names = {a for c in p.countries for a in _country_aliases(c) if a}
    if p.city:
        names.add(fold(p.city))
    if "it" in p.countries:  # elenco storico di citta' del config (retrocompatibilita')
        names |= {i.lower() for i in loc.get("include", []) if i.lower() not in ("remote", "remoto")}
    haystack = f"{place} {fold(job.title)}"  # come in fase 1: anche il titolo puo' dire "Italy", "EMEA", "Europe"
    if any(_has(n, haystack) for n in names):
        return True
    if "it" in p.countries and any(_has(r, place) for r in _IT_REGIONS):
        return True  # sede = una regione italiana (Lombardia, Lazio...) e il paese non e' noto
    if place.strip() and _city_in_countries(job.location, p.countries):
        return True
    own = {a for c in p.countries for a in _country_aliases(c)}
    if any(_has(x, place) for x in loc.get("exclude", []) if x.lower() not in own):
        return False  # remoto ristretto a paesi che non interessano (es. "Remote - USA")
    return bool(p.remote and remote_flag and loc.get("allow_remote", True)) or (
        p.remote and place.strip() in ("remote", "remoto", "worldwide", "anywhere", "emea", "europe"))


def score_job(job: Job, cfg: dict, profile=None, rules=None) -> Job | None:
    """Assegna score/categoria. Ritorna None se l'annuncio va scartato.

    Senza profilo vale la regola storica (cybersecurity dal config). Con un profilo si usano le sue parole chiave
    (preset + extra + titoli liberi), le parole da escludere, il livello e i contratti scelti."""
    if profile is None:
        return _score_legacy(job, cfg)
    from .meta import detect_contract
    from .profiles import as_profile, build_rules

    p = as_profile(profile)
    r = rules or build_rules(p, cfg)
    match = has_flex if r.flex else (lambda term, text: _has(term, text))
    title, body = fold(job.title), fold(job.description)
    if any(match(b, title) for b in r.blacklist):
        return None
    if job.posted_at and datetime.now(timezone.utc) - job.posted_at > timedelta(days=cfg["general"]["max_age_days"]):
        return None
    if p.contracts and detect_contract(job.title, job.description) not in p.contracts:
        return None

    totals: dict[str, int] = {}
    matched: list[str] = []
    for label, terms in r.groups:
        sub = totals.get(label, 0)
        for term, weight in terms.items():
            if match(term, title):
                sub += weight * 3
                matched.append(term)
            elif match(term, body):
                sub += weight
                matched.append(term)
        totals[label] = sub
    score = sum(totals.values())
    for term, weight in r.extra.items():
        if match(term, title):
            score += weight * 3
            matched.append(term)
        elif match(term, body):
            score += weight
            matched.append(term)
    if score == 0:
        return None
    # categorie personali (fase 6): decidono l'etichetta; danno al massimo un piccolo bonus (+4 se una parola e' nel titolo, +2 se solo nel testo)
    # e solo se l'annuncio e' gia' pertinente per titoli/parole chiave (da sole non lo fanno entrare)
    cat_totals = dict(totals) if r.label_groups else {}
    cat_bonus = 0
    for label, terms in r.cats:
        sub, in_title = 0, False
        for term, weight in terms.items():
            ft = fold(term)  # titolo e testo sono gia' senza accenti: le parole dell'utente ("perché") si piegano allo stesso modo
            if match(ft, title):
                sub += weight * 3
                in_title = True
                matched.append(term)
            elif match(ft, body):
                sub += weight
                matched.append(term)
        if sub:
            cat_totals[label] = cat_totals.get(label, 0) + sub
            cat_bonus = max(cat_bonus, CAT_BONUS_TITLE if in_title else CAT_BONUS_BODY)
    score += cat_bonus
    for term, delta in r.adjust.items():
        if match(term, title):
            score += delta

    loc_cfg = cfg.get("location", {})
    place = fold(job.location or "")
    names = [fold(h) for h in loc_cfg.get("home_names", [])]
    if p.city:
        city = fold(p.city)
        names = names if city in names else [city]
    else:
        names = []
    if (p.city and fold(p.city) in job.near_where) or any(_has(n, place) for n in names) or (
            job.near_home and not job.near_where):  # near_home senza near_where = segnalazione della fonte
        job.near_home = True
        if score >= loc_cfg.get("home_min_score", 20):
            score += loc_cfg.get("home_bonus", 20)

    ranked = sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)
    category = ranked[0][0] if ranked and ranked[0][1] > 0 else "ALTRO"
    if r.cyber and totals.get("RED", 0) >= 12 and totals.get("BLUE", 0) >= 12:
        category = "PURPLE"
    job.score = max(score, 0)
    job.category = category
    job.matched = sorted(set(matched))
    return job
