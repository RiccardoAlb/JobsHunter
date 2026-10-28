"""Rilevamento di possibili annunci duplicati (stesso lavoro da fonti diverse).

Il programma PROPONE le coppie con una percentuale di somiglianza; la decisione finale
(duplicato / non duplicato) la prende l'utente dalla GUI e resta salvata.

Come funziona, in tre passi:
1. **Normalizzazione**: ogni annuncio viene ridotto a azienda, titolo e citta' "pulite" (senza forma societaria,
   genere "(m/f)", accenti, punteggiatura, sigle puntate, parole come "remoto" o "part time").
2. **Blocking** (`candidate_pairs`): si confrontano solo le coppie plausibili, cioe' della stessa azienda (o di
   aziende dal nome quasi uguale), con citta' compatibile. Cosi' 5.000 annunci non richiedono 12 milioni di confronti.
3. **Somiglianza** (`similarity`): formula storica `titolo * azienda - penalita'` con le stesse soglie del config.
   Rispetto a prima il confronto del titolo guarda le PAROLE (non solo le lettere): un titolo con qualcosa in piu'
   in coda ("... - Roma", "(EMEA)") e' lo stesso lavoro, mentre due titoli che hanno ciascuno una parola diversa
   ("Frontend" / "Backend", "clienti" / "fornitori") sono lavori diversi anche se le lettere sono quasi uguali.

Criteri per le parole (`same_word`): due parole sono "la stessa" se uguali, se una e' una sigla nota dell'altra (Dev/Developer,
Mgr/Manager, Admin/Administrator, Resp./Responsabile; elenco ABBREV, la sigla deve essere una sottosequenza che inizia con la stessa
lettera), per plurale o genere regolare (analyst/analysts, infermiere/infermiera), per uno scambio di due lettere vicine
(Vendedor/Vendedro, da 5 lettere), per una lettera in piu' o in meno (da 8 lettere) o per due (da 11 lettere). Le parole corte quasi
uguali restano DIVERSE (Picker/Packer, Driver/Diver, Cleaner/Cleaver): un duplicato mancato costa meno di due mestieri uniti.

Citta': stesso nome e stessa qualifica (dopo la virgola, fra parentesi, "am Main") sono lo stesso posto. Qualifiche diverse sono compatibili
solo se entrambe amministrative e note (Lombardia, Provincia di Milano, contea, "kraj"...). Con una qualifica sola, e' compatibile se e'
amministrativa nota o se il nome non e' ambiguo (San Francisco, CA si', Cambridge, MA no). Una qualifica fra parentesi e' sempre una
disambiguazione (Halle (Saale) / Halle (Westfalen)). Nessuna regola "una citta' contiene l'altra": Newcastle / Newcastle-under-Lyme sono diverse.
Costo accettato: si perdono alcuni duplicati rari (Grenzach / Grenzach-Wyhlen) per non nascondere mai un annuncio vero.

Aziende: le forme societarie di molti paesi (LEGAL_FORMS, con puntini e barre normalizzati) e le parole generiche non contano. Un nome
contenuto nell'altro vale 90% se le parole in piu' stanno davanti ("Robert Bosch") o sono descrittive (COMPANY_TYPE: Group, Retail, Kliniken,
Ingegneria Informatica, punti cardinali...), altrimenti 70% (Siemens / Siemens Energy sono aziende diverse).

Criterio per la coda: parole in piu' a un titolo sono "rumore" (stesso lavoro) solo se stanno DOPO un separatore (" - ", "(", ":", "|"),
oppure sono la citta' dell'annuncio o parole come "turni". Senza separatore una parola in piu' specializza il ruolo (Infermiere /
Infermiere pediatrico) e il titolo vale al massimo il 70%. Lo stesso per le aziende: un nome contenuto nell'altro vale il 90% solo se
le parole in piu' sono descrittive (Banca, Ristorante, Group...) o una citta'; altrimenti (Restaurante O Pescador / O Pescador Novo) il 70%.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterator

from .db import DB

# Forme societarie e sigle di molti paesi (i puntini si tolgono prima: "S.r.o." = "sro", "A/S" = "a s", "Sdn. Bhd." = "sdn bhd").
LEGAL_FORMS = {
    "spa", "srl", "srls", "sas", "snc", "sapa", "s", "p", "a", "r", "l", "sa", "sl", "slu", "gmbh", "ag", "se", "kg", "ug", "ohg",
    "gbr", "ev", "eg", "mbh", "ltd", "limited", "llc", "llp", "lp", "inc", "incorporated", "corp", "corporation", "plc", "bv",
    "nv", "bvba", "cvba", "vof", "ab", "oy", "oyj", "as", "asa", "aps", "sarl", "eurl", "sasu", "sci", "pty", "pte", "ltda",
    "lda", "sgps", "sp", "z", "oo", "zoo", "sro", "kft", "zrt", "nyrt", "doo", "dd", "sdn", "bhd", "pvt", "pjsc", "ooo", "cv",
    "co", "company", "coop", "kgaa", "sac", "srl", "ei", "gk", "kk",
}
# parole che non distinguono l'azienda: generiche, paesi, regioni del mondo
COMPANY_NOISE = LEGAL_FORMS | {
    "the", "group", "gruppo", "grupo", "groupe", "holding", "italia", "italy", "espana", "spain", "france", "deutschland",
    "germany", "uk", "usa", "international", "europe", "emea", "latam", "apac", "global", "worldwide",
}
GENERIC_CITIES = {"", "italia", "italy", "remote", "remoto", "emea", "europe", "europa", "worldwide", "anywhere", "hybrid",
                  "ibrido", "uk", "united kingdom", "germany", "deutschland", "france", "spain", "espana", "usa",
                  "united states"}
# (m/f), (m/w/d), (f/m/x), H/F, (h/m): lettere di genere separate da barre
GENDER = re.compile(r"\(?\b[mfdwxhg]\s*/\s*[mfdwxhg](\s*/\s*[mfdwxhg])?\b\)?|\(?\ball genders\)?")
GENDER_END = re.compile(r"(?<=[a-z])/(?:a|e|o|ia|essa|ra|trice|ora|euse|ice|in|innen)\b")  # cuoco/a, educatore/trice, Lehrer/in
SEPARATOR = re.compile(r"\s[-\u2013\u2014:|]\s|[(\[:|]")
DOTTED = re.compile(r"\b(?:[a-z]\.){2,}")  # S.O.C. -> SOC, S.p.A. -> SpA
LEVEL_ALIAS = {"jr": "junior", "jnr": "junior", "sr": "senior", "snr": "senior", "internship": "intern",
               "stagista": "intern", "tirocinante": "intern", "tirocinio": "intern", "stage": "intern",
               "apprendista": "intern", "coordinator": "coordinatore", "coord": "coordinatore", "mgr": "manager", "resp": "responsabile", "leader": "lead"}
LEVEL_WORDS = {"junior", "senior", "lead", "principal", "staff", "trainee", "intern", "graduate", "entry", "expert",
               "specialist", "associate", "manager", "head", "coordinatore", "responsabile", "supervisor", "director",
               "direttore", "capo", "ii", "iii", "iv"}
LEVEL_CODE = re.compile(r"^(?:l[1-4]|tier[1-4])$")
STOP = {"of", "the", "and", "di", "de", "del", "della", "dei", "delle", "da", "d", "l", "la", "le", "lo", "il", "gli", "el",
        "los", "las", "en", "y", "und", "der", "die", "das", "et", "e", "a", "al", "alla", "for", "per", "para", "pour",
        "fuer", "in", "im", "du", "des", "un", "una", "ein", "eine"}
TITLE_NOISE = {"remote", "remoto", "hybrid", "ibrido", "urgent", "urgente", "immediato", "immediate"}
TITLE_NOISE_PHRASES = ("part time", "full time", "parttime", "fulltime", "tempo pieno", "tempo parziale")
CITY_ALIAS = {"milan": "milano", "rome": "roma", "turin": "torino", "naples": "napoli", "florence": "firenze",
              "venice": "venezia", "genoa": "genova", "padua": "padova", "munich": "muenchen", "munchen": "muenchen",
              "cologne": "koeln", "vienna": "wien", "lisbon": "lisboa", "seville": "sevilla", "brussels": "bruxelles",
              "geneva": "geneve", "zurich": "zuerich", "prague": "praha", "warsaw": "warszawa", "cracow": "krakow",
              "kobenhavn": "copenhagen", "gothenburg": "goteborg", "cologne": "koeln", "turin": "torino", "athens": "athina"}

ABBREV = {"dev", "eng", "engr", "admin", "asst", "assist", "resp", "ing", "mgr", "mgmt", "dir", "coord", "acct", "amm", "entw"}
TAIL_NOISE = {"turni", "turno", "stagionale", "immediato", "urgente"}
# parole che descrivono il TIPO di azienda, non quale azienda e': non distinguono due nomi (Banca Intesa / Intesa)
COMPANY_TYPE = {
    "banca", "bank", "ristorante", "restaurante", "restaurant", "coffee", "hotel", "hotels", "studio", "studios", "cooperativa",
    "sociale", "farmacia", "clinica", "kliniken", "ospedale", "hospital", "universita", "university", "universitaetsmedizin",
    "klinikum", "services", "servizi", "solutions", "consulting", "associati", "partners", "partnerschaft", "academy", "retail",
    "wind", "systems", "sistemi", "technologies", "technology", "tech", "software", "digital", "labs", "ingegneria",
    "informatica", "engineering", "gestion", "gestione", "freres", "stiftung", "iletisim", "hizmetleri", "manufacturing",
    "logistics", "logistica", "farmaceutici", "pharma", "farma",
    "nord", "sud", "ovest", "est", "centro", "nordovest", "nordest", "north", "south", "east", "west", "central",
    "assicurazioni", "insurance", "capital", "finance", "financial", "trasporti", "transport", "construction", "costruzioni",
}
COMPANY_PARTIAL = 0.7     # un nome contenuto nell'altro ma con parole in piu' che distinguono
SECTOR_TAIL = 0.92        # titolo con qualcosa in piu' in coda: stesso lavoro, un po' meno sicuro
SECTOR_INSERT_CAP = 0.7   # parola in piu' in mezzo o davanti: probabilmente un altro ruolo
TOKEN_FUZZY = 0.9         # due parole sono "la stessa" (refusi, plurali) sopra questa somiglianza di lettere
SMALL_BLOCK = 60          # sotto questo numero di annunci per azienda si confrontano tutte le coppie


# ------------------------------------------------------------ normalizzazione ----
def fold(s: str) -> str:
    """Minuscolo, senza accenti (Société = societe), '&' come separatore."""
    return unicodedata.normalize("NFKD", (s or "").lower().replace("&", " ")).encode("ascii", "ignore").decode()


def _alnum(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", fold(s)).split())


def _undot(s: str) -> str:
    return DOTTED.sub(lambda m: m.group().replace(".", ""), s)


def norm_company(s: str) -> str:
    words = [w for w in _alnum(_undot(fold(s))).split() if w not in COMPANY_NOISE]
    return " ".join(words) or _alnum(s)


def norm_title(s: str) -> str:
    t = fold(s)
    t = GENDER.sub(" ", t)
    t = GENDER_END.sub("", t)
    t = _undot(t)
    t = re.sub(r"\bc\s*#", "csharp ", t)
    t = re.sub(r"\bf\s*#", "fsharp ", t)
    t = t.replace("c++", "cpp ").replace("node.js", "nodejs ")
    t = re.sub(r"\.net\b", " dotnet ", t)
    t = re.sub(r"\btier\s*([1-4])\b", r"tier\1", t)
    t = _alnum(t)
    for ph in TITLE_NOISE_PHRASES:
        t = re.sub(rf"\b{ph}\b", " ", t)
    words = [LEVEL_ALIAS.get(w, w) for w in t.split() if w not in TITLE_NOISE]
    return " ".join(words)


_ADMIN_WORDS = {"provincia", "province", "metropolitana", "metropolitan", "county", "kraj", "lan", "region", "regione", "state",
                "bezirk", "kreis", "departement", "oblast", "voivodeship", "wojewodztwo", "comarca", "gemeente", "district",
                "greater", "area", "land", "canton", "kanton"}
# regioni, stati federati e paesi che qualificano una citta' senza cambiarla ("Milano, Lombardia"); NON i codici americani (MA, AL)
_BENIGN = {
    "lombardia", "lazio", "sicilia", "piemonte", "veneto", "campania", "puglia", "toscana", "emilia romagna", "liguria",
    "sardegna", "calabria", "marche", "abruzzo", "umbria", "friuli venezia giulia", "trentino alto adige", "basilicata", "molise",
    "valle d aosta", "bayern", "bavaria", "hessen", "nordrhein westfalen", "baden wurttemberg", "sachsen", "niedersachsen",
    "berlin", "hamburg", "brandenburg", "thuringen", "ile de france", "occitanie", "auvergne rhone alpes", "provence alpes cote d azur",
    "bretagne", "normandie", "nouvelle aquitaine", "cataluna", "catalunya", "andalucia", "comunidad de madrid", "madrid",
    "valencia", "pais vasco", "galicia", "england", "scotland", "wales", "northern ireland", "greater london", "west midlands",
    "west yorkshire", "south yorkshire", "greater manchester", "main", "italy", "italia", "uk", "united kingdom", "gb", "germany",
    "deutschland", "france", "spain", "espana", "portugal", "poland", "polska", "netherlands", "austria", "switzerland", "schweiz",
    "belgium", "ireland", "usa", "united states", "denmark", "sweden", "norway", "finland", "czechia", "czech republic",
    "turkey", "romania", "hungary", "europe",
}


def city_parts(s: str) -> tuple[str, str]:
    """(nome, qualifica): "Milano, Lombardia" -> ("milano", "lombardia"); "Halle (Saale)" -> ("halle", "saale");
    "Frankfurt am Main" -> ("frankfurt", "main"). Il nome non ha quartieri numerati ("Praha 4") ne' prefissi come "Provincia di"."""
    c = fold(s or "")
    qual = ""
    m = re.search(r"\(([^)]*)\)", c)
    if m:
        qual = "(" + m.group(1)  # una qualifica fra parentesi e' una disambiguazione esplicita: "Halle (Saale)", "Frankfurt (Oder)"
        c = c[:m.start()] + " " + c[m.end():]
    parts = [p.strip() for p in c.split(",")]
    name = parts[0]
    if len(parts) > 1 and not qual:
        qual = parts[1]
    m = re.search(r"\s(?:am|im|an der|bei)\s+(.+)$", name)
    if m:
        qual = qual or m.group(1)
        name = name[:m.start()]
    name = re.sub(r"^(?:provincia di|provincia del|citta metropolitana di|area metropolitana di|greater|grande)\s+", "", name.strip())
    name = re.sub(r"\s+(?:area|e provincia)$", "", name.strip())
    name = " ".join(re.sub(r"[^a-z0-9 ]", " ", name).split())
    name = re.sub(r"\s+\d+$", "", name)
    paren = qual.startswith("(")
    qual = " ".join(re.sub(r"[^a-z0-9 ]", " ", qual).split())
    if paren and qual:
        qual = "(" + qual
    return CITY_ALIAS.get(name, name), qual


def norm_city(s: str) -> str:
    return city_parts(s)[0]


def _benign(qual: str) -> bool:
    qual = qual.lstrip("(")
    return qual in _BENIGN or bool(set(qual.split()) & _ADMIN_WORDS)


def _ambiguous(name: str) -> bool:
    """Il nome e' di piu' citta' importanti? (dataset offline di geonamescache; Cambridge si', San Francisco no)."""
    try:
        from . import geo

        cands = geo._index()[0].get(geo._norm(name), [])
    except Exception:
        return True
    pops = sorted({(c["countrycode"], c["population"]) for c in cands}, key=lambda t: -t[1])  # la stessa citta' compare piu' volte
    pops = [p for _, p in pops]
    return len(pops) >= 2 and pops[1] >= 0.15 * pops[0]


def levels(title_norm: str) -> set[str]:
    """Livelli presenti in un titolo normalizzato (Junior/Senior, L1/L2, Tier 1/2, Specialist/Expert...)."""
    out = set()
    for w in title_norm.split():
        w = LEVEL_ALIAS.get(w, w)
        if w in LEVEL_WORDS or LEVEL_CODE.match(w):
            out.add(w)
    return out


def _ratio(a: str, b: str) -> float:
    sm = SequenceMatcher(None, a, b)
    if sm.real_quick_ratio() < 0.6 or sm.quick_ratio() < 0.6:
        return 0.0
    return sm.ratio()


# ----------------------------------------------------------------- elementi ----
def _f(row, key, default=""):
    """Campo di una riga (sqlite3.Row o dict), con valore di riserva se manca."""
    try:
        v = row[key]
    except (KeyError, IndexError):
        return default
    return default if v is None else v


@dataclass
class Item:
    """Un annuncio ridotto alle sole cose che servono al confronto (calcolate una volta sola)."""
    row: object
    company: str
    ctoks: tuple
    city: str
    cqual: str
    country: str
    title: str
    ttoks: tuple
    levels: frozenset
    sep: int = 0   # indice della prima parola dopo un separatore (" - ", "(", ":", "|"); = len(ttoks) se non c'e'


def prepare(row) -> Item:
    comp = norm_company(_f(row, "company"))
    title = norm_title(_f(row, "title"))
    toks = tuple(w for w in title.split() if w not in STOP) or tuple(title.split())
    raw = GENDER.sub(" ", fold(_f(row, "title")))
    m = SEPARATOR.search(raw)
    head = norm_title(raw[:m.start()]) if m else title
    sep = len([w for w in head.split() if w not in STOP]) if m else len(toks)
    cname, cqual = city_parts(_f(row, "location"))
    return Item(row, comp, tuple(comp.split()), cname, cqual, str(_f(row, "country")).lower(),
                title, toks, frozenset(levels(title)), min(sep, len(toks)))


# ------------------------------------------------------------- somiglianza ----
def _edit1(a: str, b: str) -> bool:
    """Distanza di Levenshtein <= 1 (una lettera in piu', in meno o diversa)."""
    if abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] or a[i:] == b[i + 1:] or a[i + 1:] == b[i:]


def _edit2(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 2:
        return False
    return _ratio(a, b) >= 0.85 and SequenceMatcher(None, a, b).ratio() >= 0.85 and (
        _edit1(a[1:], b[1:]) or _edit1(a[:-1], b[:-1]) or _edit1(a, b) or _edit1(a[1:], b) or _edit1(a, b[1:]))


def _transposed(a: str, b: str) -> bool:
    if len(a) != len(b) or a == b:
        return False
    d = [i for i in range(len(a)) if a[i] != b[i]]
    return len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]]


def _subseq(a: str, b: str) -> bool:
    it = iter(b)
    return all(c in it for c in a)


def _inflection(a: str, b: str) -> bool:
    """Plurale o genere regolare: analyst/analysts, infermiere/infermiera, cuoco/cuoca (da 5 lettere)."""
    if min(len(a), len(b)) < 5:
        return False
    if b in (a + "s", a + "es") or a in (b + "s", b + "es"):
        return True
    return len(a) == len(b) and a[:-1] == b[:-1] and a[-1] in "aeio" and b[-1] in "aeio"


def same_word(x: str, y: str) -> bool:
    """Stessa parola a meno di sigle note, scambio di lettere, plurali, refusi (criteri nel docstring del modulo).

    Il refuso di UNA lettera si tollera solo da 8 lettere (Developper/Developer): su parole corte unirebbe mestieri
    diversi (Driver/Diver, Cleaner/Cleaver). Per le parole corte valgono solo uguaglianza, sigle e scambio di lettere vicine."""
    if x == y:
        return True
    a, b = (x, y) if len(x) <= len(y) else (y, x)
    if a in ABBREV and a[0] == b[0] and len(b) > len(a) and _subseq(a, b):
        return True
    if len(a) >= 5 and _transposed(a, b):
        return True
    if _inflection(x, y):
        return True
    if min(len(x), len(y)) >= 8 and _edit1(x, y):
        return True
    return min(len(x), len(y)) >= 11 and _edit2(x, y)


def company_score(a: Item, b: Item) -> float:
    """0 = aziende diverse; 1 = stessa azienda; 0.9 = una e' contenuta nel nome dell'altra ("Banca Intesa Sanpaolo" / "Intesa Sanpaolo")."""
    if a.company == b.company or sorted(a.ctoks) == sorted(b.ctoks) or "".join(a.ctoks) == "".join(b.ctoks):
        return 1.0
    sa, sb = set(a.ctoks), set(b.ctoks)
    if sa and sb and (sa <= sb or sb <= sa):
        short, long_ = (a, b) if sa <= sb else (b, a)
        city = set((a.city + " " + b.city).split())
        n = len(short.ctoks)
        if long_.ctoks[-n:] == short.ctoks:
            return 0.9  # solo parole DAVANTI al nome ("Robert Bosch", "Banca Intesa"): qualifiche
        extra = [w for w in long_.ctoks if w not in sa or w not in sb]
        descriptive = all(w in COMPANY_TYPE or w in city for w in extra)
        return 0.9 if descriptive else COMPANY_PARTIAL
    # refusi ("Acenture"): ogni parola deve essere quasi uguale, altrimenti "Deutsche Bank" e "Deutsche Bahn" si confondono
    xa, xb = sorted(a.ctoks), sorted(b.ctoks)
    if len(xa) == len(xb) and xa:
        rs = [1.0 if x == y else _ratio(x, y) for x, y in zip(xa, xb)]
        if min(rs) >= TOKEN_FUZZY:
            return round(_ratio(a.company, b.company), 3)
    return 0.0


def title_score(a: Item, b: Item) -> float | None:
    """Somiglianza dei titoli 0..1, oppure None se sono ruoli diversi (ciascuno ha una parola che l'altro non ha)."""
    if a.title == b.title or "".join(a.ttoks) == "".join(b.ttoks) or sorted(a.ttoks) == sorted(b.ttoks):
        return 1.0
    if not a.ttoks or not b.ttoks:
        r = _ratio(a.title, b.title)
        return r if r >= 0.6 else None
    la, lb = list(a.ttoks), list(b.ttoks)
    pos_a, pos_b = list(range(len(la))), list(range(len(lb)))
    # 1) parole identiche, 2) parole equivalenti (sigle, scambi di lettere, refusi)
    for i in list(pos_a):
        for j in pos_b:
            if la[i] == lb[j]:
                pos_a.remove(i)
                pos_b.remove(j)
                break
    fuzzy = False
    for i in list(pos_a):
        for j in pos_b:
            if same_word(la[i], lb[j]):
                pos_a.remove(i)
                pos_b.remove(j)
                fuzzy = True
                break
    # 3) parole spezzate in modo diverso ("front end" / "frontend", "software entwickler" / "softwareentwickler")
    if pos_a and pos_b:
        ja, jb = "".join(la[i] for i in pos_a), "".join(lb[j] for j in pos_b)
        if ja == jb or (min(len(ja), len(jb)) >= 6 and _ratio(ja, jb) >= TOKEN_FUZZY):
            pos_a, pos_b, fuzzy = [], [], True
    if not pos_a and not pos_b:
        return 0.97 if fuzzy else 1.0
    if pos_a and pos_b:
        return None  # ciascuno ha una parola che manca all'altro: ruoli diversi
    extra, long_toks = (pos_a, la) if pos_a else (pos_b, lb)
    matched = [i for i in range(len(long_toks)) if i not in extra]
    longer = a if pos_a else b
    city = set(longer.city.split())
    noise = all(i >= longer.sep or long_toks[i] in TAIL_NOISE or long_toks[i] in city for i in extra)
    if matched and min(extra) > max(matched) and noise:
        return SECTOR_TAIL  # coda dopo un separatore ("- Roma", "(EMEA)") o solo rumore ("turni", la citta')
    return min(_ratio(a.title, b.title), SECTOR_INSERT_CAP)


def _city_compat(a: Item, b: Item) -> int | None:
    """Penalita' per la citta' (0 uguale, 10 sede generica da una parte), oppure None se sono posti diversi."""
    if a.country and b.country and a.country != b.country:
        return None
    if a.city == b.city and a.city not in GENERIC_CITIES:
        qa, qb = a.cqual, b.cqual
        if qa == qb:
            return 0
        # Stesso nome, qualifiche diverse. Due qualifiche diverse sono compatibili solo se entrambe amministrative e note
        # (Lombardia / Provincia di Milano). Una sola qualifica e' compatibile se e' amministrativa nota o se il nome non e'
        # ambiguo (San Francisco, CA). Altrimenti sono citta' diverse (Birmingham / Birmingham, Alabama; Halle (Saale) / (Westfalen)):
        # meglio perdere un duplicato raro che nascondere un annuncio vero.
        if qa and qb:
            return 0 if _benign(qa) and _benign(qb) else None
        q = qa or qb
        return 0 if _benign(q) or (not q.startswith("(") and not _ambiguous(a.city)) else None
    if a.city == b.city:
        return 0
    if a.city in GENERIC_CITIES or b.city in GENERIC_CITIES:
        return 10
    return None


def compare(a: Item, b: Item) -> int | None:
    """Percentuale 0-100, o None se le due righe non sono confrontabili."""
    cs = company_score(a, b)
    if cs == 0.0:
        return None
    penalty = _city_compat(a, b)
    if penalty is None:
        return None
    ts = title_score(a, b)
    if ts is None or ts < 0.6:
        return None
    pct = ts * cs * 100 - penalty
    if a.levels != b.levels:
        pct -= 25  # Junior vs Senior, L1 vs L2, Specialist vs Expert...
    return round(max(pct, 0))


def similarity(a, b) -> int | None:
    """Percentuale di somiglianza 0-100, oppure None se le due righe non sono confrontabili."""
    return compare(prepare(a), prepare(b))


# ------------------------------------------------------------------ blocking ----
def _trigrams(s: str) -> set[str]:
    p = f"  {s} "
    return {p[i:i + 3] for i in range(len(p) - 2)}


def _company_neighbors(reps: list[Item]) -> Iterator[tuple[int, int]]:
    """Coppie di aziende DIVERSE ma dal nome simile (una contenuta nell'altra, o con un refuso).

    Indice invertito su parole e su gruppi di 3 lettere: costo proporzionale ai nomi che condividono qualcosa,
    non al quadrato delle aziende. Le parole/gruppi troppo comuni (es. "ing") non servono a distinguere e si saltano."""
    by_tok: dict[str, list[int]] = defaultdict(list)
    by_tri: dict[str, list[int]] = defaultdict(list)
    tris = [_trigrams("".join(r.ctoks)) for r in reps]
    for i, r in enumerate(reps):
        for t in set(r.ctoks):
            by_tok[t].append(i)
        for g in tris[i]:
            by_tri[g].append(i)
    seen: set[tuple[int, int]] = set()

    def consider(i: int, j: int):
        key = (i, j) if i < j else (j, i)
        if key in seen:
            return None
        seen.add(key)
        return key if company_score(reps[key[0]], reps[key[1]]) > 0 else None

    for lst in by_tok.values():
        if 1 < len(lst) <= 150:
            for x in range(len(lst)):
                for y in range(x + 1, len(lst)):
                    k = consider(lst[x], lst[y])
                    if k:
                        yield k
    for i in range(len(reps)):
        cnt: Counter = Counter()
        for g in tris[i]:
            lst = by_tri[g]
            if len(lst) <= 150:
                for j in lst:
                    if j > i:
                        cnt[j] += 1
        for j, c in cnt.items():
            if c >= max(3, int(0.6 * min(len(tris[i]), len(tris[j])))):
                k = consider(i, j)
                if k:
                    yield k


def _title_keys(it: Item) -> set[str]:
    keys = set(it.ttoks)
    j = "".join(it.ttoks)
    if len(j) >= 5:
        keys.add("#" + j[:5])
    return keys


def _pairs_within(items: list[Item], idx: list[int]) -> Iterator[tuple[int, int]]:
    if len(idx) <= SMALL_BLOCK:
        for x in range(len(idx)):
            for y in range(x + 1, len(idx)):
                if _city_compat(items[idx[x]], items[idx[y]]) is not None:
                    yield idx[x], idx[y]
        return
    index: dict[str, list[int]] = defaultdict(list)
    seen: set[tuple[int, int]] = set()
    for i in idx:
        for k in _title_keys(items[i]):
            for j in index[k]:
                key = (j, i)
                if key not in seen and _city_compat(items[j], items[i]) is not None:
                    seen.add(key)
                    yield key
            index[k].append(i)


def _pairs_between(items: list[Item], ia: list[int], ib: list[int]) -> Iterator[tuple[int, int]]:
    if len(ia) * len(ib) <= SMALL_BLOCK * SMALL_BLOCK:
        for i in ia:
            for j in ib:
                if _city_compat(items[i], items[j]) is not None:
                    yield i, j
        return
    index: dict[str, list[int]] = defaultdict(list)
    for j in ib:
        for k in _title_keys(items[j]):
            index[k].append(j)
    for i in ia:
        got: set[int] = set()
        for k in _title_keys(items[i]):
            got.update(index.get(k, ()))
        for j in got:
            if _city_compat(items[i], items[j]) is not None:
                yield i, j


def _blocks(items: list[Item]) -> Iterator[tuple[int, int]]:
    """Indici delle coppie plausibili: stessa azienda (o nome quasi uguale) e citta' compatibile."""
    groups: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        groups[it.company].append(i)
    keys = list(groups)
    reps = [items[groups[k][0]] for k in keys]
    for k in keys:
        yield from _pairs_within(items, groups[k])
    for ci, cj in _company_neighbors(reps):
        yield from _pairs_between(items, groups[keys[ci]], groups[keys[cj]])


def candidate_pairs(rows) -> Iterator[tuple]:
    """Coppie (riga_a, riga_b) plausibili: stessa azienda o nome quasi uguale, citta' compatibile (o generica).

    Non calcola la percentuale: serve solo a non confrontare tutte le coppie. Non perde coppie che
    `similarity` potrebbe proporre."""
    rows = list(rows)
    items = [prepare(r) for r in rows]
    for i, j in _blocks(items):
        yield rows[i], rows[j]


# ----------------------------------------------------------------- salvataggio ----
def pick_keeper(a, b):
    """Quale dei due tenere: candidato > testo completo > fonte leggibile (non Jooble) > stipendio > score."""
    def rank(r):
        return (r["status"] == "applied", bool(r["full_text"]), not r["source"].startswith("jooble"),
                bool(r["salary"]), r["score"])
    return (a, b) if rank(a) >= rank(b) else (b, a)


def find_duplicates(db: DB, cfg: dict) -> int:
    """Calcola le coppie candidate e le salva. Ritorna quante coppie NUOVE sono state proposte."""
    dcfg = cfg.get("dedupe", {})
    min_pct = dcfg.get("min_percent", 75)
    auto_pct = dcfg.get("auto_confirm_percent", 100)  # >100 = mai in automatico
    rows = db.conn.execute(
        "SELECT uid, title, company, location, country, status, source, salary, score, (length(full_text)>0) AS full_text "
        "FROM jobs WHERE status!='discarded' AND uid NOT IN "
        "(SELECT hidden_uid FROM dup_pairs WHERE status='confirmed')"
    ).fetchall()
    items = [prepare(r) for r in rows]
    new = 0
    for i, j in _blocks(items):
        pct = compare(items[i], items[j])
        if pct is None or pct < min_pct:
            continue
        a, b = rows[i], rows[j]
        keep, hide = pick_keeper(a, b)
        new += db.upsert_dup(a["uid"], b["uid"], pct, keep["uid"], hide["uid"], auto=pct >= auto_pct)
    db.commit()
    return new
