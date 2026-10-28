"""Dati derivati dagli annunci: RAL annua in euro, modalita' di lavoro e citta'.

Sono ricavati dal testo con regole prudenti: se un dato non e' chiaro resta "non indicato" invece di
indovinare. Se cambi le regole, aumenta META_VERSION: gli annunci gia' salvati vengono rivalutati.
"""
from __future__ import annotations

import re

META_VERSION = 4

# ---------------------------------------------------------------- RAL ----
_NUM = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?")
_IT_NUM = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")   # 22.816,92
_EN_NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")   # 26,500


def _to_float(tok: str) -> float:
    if _IT_NUM.fullmatch(tok):
        return float(tok.replace(".", "").replace(",", "."))
    if _EN_NUM.fullmatch(tok):
        return float(tok.replace(",", ""))
    return float(tok.replace(",", "."))


# valute riconosciute: (codice, espressione). Le forme specifiche ("c$", "a$") vengono prima del generico "$".
_CURRENCIES = [
    ("CAD", r"\bc\$|\bcad\b|ca\$"), ("AUD", r"\ba\$|\baud\b|au\$"), ("NZD", r"\bnz\$|\bnzd\b"),
    ("SGD", r"\bs\$|\bsgd\b"), ("BRL", r"\br\$|\bbrl\b"), ("MXN", r"\bmx\$|\bmxn\b"),
    ("USD", r"\$|\busd\b|\bdollar"), ("GBP", r"\u00a3|\bgbp\b|\bsterlin"), ("CHF", r"\bchf\b|\bsfr\b"),
    ("PLN", r"\bpln\b|z\u0142|\bzl\b"), ("INR", r"\u20b9|\binr\b"), ("ZAR", r"\bzar\b"),
    ("SEK", r"\bsek\b"), ("NOK", r"\bnok\b"), ("DKK", r"\bdkk\b"),
    ("EUR", r"\u20ac|\beur\b|\beuro\b|\beuros\b"),
]
_CUR_RE = [(c, re.compile(p)) for c, p in _CURRENCIES]


def detect_currency(text: str | None) -> str | None:
    """Codice valuta (EUR, GBP, USD, CHF, PLN...) dichiarato nel testo, oppure None se non c'e' nessun simbolo."""
    t = (text or "").lower()
    for code, rx in _CUR_RE:
        if rx.search(t):
            return code
    return None


def parse_salary_ex(text: str | None) -> tuple[int, int, str] | None:
    """Come `parse_salary`, ma con la valuta: (minimo, massimo, codice). Senza simbolo si assume l'euro."""
    rng = parse_salary(text)
    if rng is None:
        return None
    return rng[0], rng[1], detect_currency(text) or "EUR"


def parse_salary(text: str | None) -> tuple[int, int] | None:
    """Da testo libero a (minimo, massimo) lordi annui nella valuta indicata, oppure None se non affidabile.

    Gestisce "40.000 \u20ac - 50.000 \u20ac", "26,500-31,000 EUR", "22.816,92 \u20ac", "28k", "1.000 \u20ac/mese" (x12), anche in
    sterline, dollari, franchi, zloty... (la valuta si legge con `detect_currency`). Scarta i compensi orari o
    giornalieri, dove un'annualizzazione sarebbe un'ipotesi."""
    t = (text or "").lower()
    if not t:
        return None
    if re.search(r"/\s*(?:ora|h|hr)\b|per hour|all'ora|hourly|giornalier|al giorno|per day|/\s*(?:giorno|day)\b", t):
        return None
    vals = []
    for m in _NUM.finditer(t):
        v = _to_float(m.group())
        if re.match(r"\s*k\b", t[m.end():m.end() + 3]):
            v *= 1000
        vals.append(v)
    if not vals:
        return None
    mult = 12 if re.search(r"mese|month|mensil|/\s*mo\b", t) else 1
    lo, hi = min(vals[:2]) * mult, max(vals[:2]) * mult
    if not (5_000 <= lo <= 500_000 and 5_000 <= hi <= 500_000):
        return None
    return int(lo), int(hi)


# ------------------------------------------------------ modalita' di lavoro ----
_REMOTE_STRONG = re.compile(r"full[- ]?remote|fully remote|100 ?% ?(?:remot|da remoto)|completamente da remoto|interamente da remoto|remote[- ]first")
_REMOTE_HEAD = re.compile(r"\bremot[eo]\b")
_REMOTE_BODY = re.compile(r"da remoto|lavoro remoto|in remoto|remote working|work(?:ing)? remotely|remote (?:position|role|work|job)|telelavoro|work from home")
_HYBRID = re.compile(r"\bibrid[oa]\b|\bhybrid\b|smart[- ]?working|modalit[aà] mista|lavoro agile|alcuni giorni (?:da|in)")
_ONSITE = re.compile(r"\bin sede\b|on[- ]?site|\bonsite\b|in presenza|presso la sede|presso il cliente|sede di lavoro|work from office")

MODES = ("remote", "hybrid", "onsite", "unknown")


def detect_mode(title: str, location: str, text: str, remote_flag: bool = False) -> str:
    """remote | hybrid | onsite | unknown. Se si citano sia il remoto sia la sede, e' ibrido."""
    head = f"{title or ''} {location or ''}".lower()
    body = (text or "").lower()
    both = f"{head} {body}"
    if _REMOTE_STRONG.search(both):
        return "remote"
    hybrid = _HYBRID.search(both)
    remote = remote_flag or _REMOTE_HEAD.search(head) or _REMOTE_BODY.search(body)
    onsite = _ONSITE.search(both)
    if hybrid or (remote and onsite):
        return "hybrid"
    if remote:
        return "remote"
    if onsite:
        return "onsite"
    return "unknown"


# --------------------------------------------------------------- citta' ----
_ALIASES = {"ostiense": "Roma", "eur": "Roma", "garbatella": "Roma", "lingotto": "Torino"}
_GENERIC = {"", "italia", "italy", "remote", "remoto", "worldwide", "europe", "emea", "hybrid", "anywhere"}
_REGIONS = {"lombardia", "lazio", "sicilia", "piemonte", "veneto", "campania", "puglia", "toscana", "emilia romagna",
            "emilia-romagna", "liguria", "sardegna", "calabria", "marche", "abruzzo", "umbria",
            "friuli venezia giulia", "trentino alto adige", "basilicata", "molise", "valle d'aosta"}


def city_of(location: str | None) -> str:
    """Nome della citta' per il filtro, oppure '' se la sede e' generica (Italia, Remote, una regione)."""
    first = (location or "").split(",")[0].strip()
    low = re.sub(r"^provincia di\s+", "", first.lower())
    if low in _GENERIC or low in _REGIONS:
        return ""
    if low in _ALIASES:
        return _ALIASES[low]
    return " ".join(w.capitalize() for w in low.split())


# ------------------------------------------------------ tipo di contratto ----
CONTRACTS = ("internship", "apprenticeship", "fixed", "permanent", "other", "unknown")
_INTERN_HEAD = re.compile(r"\b(?:stage|stagista|tirocinio|tirocinante|internship|interns?|trainee|werkstudent|working student)\b")
_INTERN_BODY = re.compile(
    r"\b(?:tirocinante|stagista)\b"
    r"|\b(?:stage|tirocinio) (?:retribuito|extracurricolare|curricolare|formativo|in azienda|di \d+ mesi|di inserimento|di orientamento)"
    r"|\b(?:offriamo|proponiamo|cerchiamo|ricerchiamo|inseriremo|per)\s+(?:uno|un|1)\s+(?:stage|tirocinio)\b"
    r"|\binternship (?:position|role|opportunity)\b")
_SENIOR_HEAD = re.compile(r"\b(?:senior|sr|lead|principal|manager|head|director|architect|staff|esperto|expert)\b")
_APPRENTICE = re.compile(r"\bapprendistato\b|\bapprendista\b|\bapprenticeship\b")
_PERMANENT = re.compile(r"\btempo indeterminato\b|\bcontratto indeterminato\b|\bpermanent (?:contract|position)\b")
_FIXED = re.compile(r"\btempo determinato\b|\bcontratto a termine\b|\bfixed[- ]term\b|\bcontratto determinato\b")
_OTHER = re.compile(r"somministrazione|interinale|partita iva|\bp\.? ?iva\b|freelance")


def detect_contract(title: str, text: str) -> str:
    """internship | apprenticeship | permanent | fixed | other | unknown.

    Lo stage si riconosce soprattutto dal titolo ("Stage", "Tirocinio", "Intern"); gli altri tipi solo se il testo
    li dichiara, e di solito non lo fa: per questo la maggior parte resta "unknown"."""
    head, body = (title or "").lower(), (text or "").lower()
    both = f"{head} {body}"
    # nel testo contano solo affermazioni forti (non "in caso di stage...") e mai per titoli senior
    if _INTERN_HEAD.search(head) or (not _SENIOR_HEAD.search(head) and _INTERN_BODY.search(body)):
        return "internship"
    if _APPRENTICE.search(both):
        return "apprenticeship"
    if _PERMANENT.search(both):
        return "permanent"
    if _FIXED.search(both):
        return "fixed"
    if _OTHER.search(both):
        return "other"
    return "unknown"
