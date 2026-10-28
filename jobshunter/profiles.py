"""Profili di ricerca: cosa cerca l'utente (settore, paesi, livello, luogo).

Un profilo è un dizionario JSON salvato nella tabella `profiles`. La cybersecurity e' solo un *preset*: ce ne sono
altri (assistenza IT, sviluppo, dati, ufficio, vendite) e il profilo `custom`, che ricava tutto dai titoli scritti
liberamente dall'utente (es. "infermiere", "magazziniere carrellista").
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

# ---------------------------------------------------------------- paesi ----
# Codici Adzuna. `aliases`: come compare il paese (o le sue citta' principali) nel campo "sede" degli annunci.
COUNTRIES: dict[str, dict] = {
    "it": {"name": "Italia", "local": "Italia", "currency": "EUR", "languages": ["it"], "adzuna": True,
           "aliases": ["italy", "italia", "italie", "italien"]},
    "gb": {"name": "Regno Unito", "local": "United Kingdom", "currency": "GBP", "languages": ["en"], "adzuna": True,
           "aliases": ["uk", "united kingdom", "england", "scotland", "wales", "london", "great britain"]},
    "de": {"name": "Germania", "local": "Deutschland", "currency": "EUR", "languages": ["de"], "adzuna": True,
           "aliases": ["germany", "deutschland", "berlin", "munich", "muenchen", "hamburg", "frankfurt"]},
    "fr": {"name": "Francia", "local": "France", "currency": "EUR", "languages": ["fr"], "adzuna": True,
           "aliases": ["france", "paris", "lyon", "marseille"]},
    "es": {"name": "Spagna", "local": "Espana", "currency": "EUR", "languages": ["es"], "adzuna": True,
           "aliases": ["spain", "espana", "madrid", "barcelona", "spagna"]},
    "nl": {"name": "Paesi Bassi", "local": "Nederland", "currency": "EUR", "languages": ["nl"], "adzuna": True,
           "aliases": ["netherlands", "nederland", "holland", "amsterdam", "rotterdam", "utrecht"]},
    "at": {"name": "Austria", "local": "Oesterreich", "currency": "EUR", "languages": ["de"], "adzuna": True,
           "aliases": ["austria", "oesterreich", "osterreich", "wien", "vienna"]},
    "ch": {"name": "Svizzera", "local": "Schweiz", "currency": "CHF", "languages": ["de", "fr", "it"], "adzuna": True,
           "aliases": ["switzerland", "schweiz", "suisse", "svizzera", "zurich", "geneva", "basel"]},
    "be": {"name": "Belgio", "local": "Belgique", "currency": "EUR", "languages": ["fr", "nl"], "adzuna": True,
           "aliases": ["belgium", "belgique", "belgie", "brussels", "bruxelles", "antwerp"]},
    "pl": {"name": "Polonia", "local": "Polska", "currency": "PLN", "languages": ["pl"], "adzuna": True,
           "aliases": ["poland", "polska", "warsaw", "warszawa", "krakow"]},
    "us": {"name": "Stati Uniti", "local": "United States", "currency": "USD", "languages": ["en"], "adzuna": True,
           "aliases": ["usa", "united states", "u.s.", "new york", "california", "texas"]},
    "ca": {"name": "Canada", "local": "Canada", "currency": "CAD", "languages": ["en"], "adzuna": True,
           "aliases": ["canada", "toronto", "vancouver", "montreal"]},
    "au": {"name": "Australia", "local": "Australia", "currency": "AUD", "languages": ["en"], "adzuna": True,
           "aliases": ["australia", "sydney", "melbourne"]},
    "br": {"name": "Brasile", "local": "Brasil", "currency": "BRL", "languages": ["pt"], "adzuna": True,
           "aliases": ["brazil", "brasil", "sao paulo", "rio de janeiro"]},
    "in": {"name": "India", "local": "India", "currency": "INR", "languages": ["en"], "adzuna": True,
           "aliases": ["india", "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad"]},
    "mx": {"name": "Messico", "local": "Mexico", "currency": "MXN", "languages": ["es"], "adzuna": True,
           "aliases": ["mexico", "mexico city", "ciudad de mexico"]},
    "nz": {"name": "Nuova Zelanda", "local": "New Zealand", "currency": "NZD", "languages": ["en"], "adzuna": True,
           "aliases": ["new zealand", "auckland", "wellington"]},
    "sg": {"name": "Singapore", "local": "Singapore", "currency": "SGD", "languages": ["en"], "adzuna": True,
           "aliases": ["singapore"]},
    "za": {"name": "Sudafrica", "local": "South Africa", "currency": "ZAR", "languages": ["en"], "adzuna": True,
           "aliases": ["south africa", "johannesburg", "cape town"]},
}
DEFAULT_COUNTRY = "it"

SENIORITY = ("any", "junior", "mid", "senior")
CONTRACTS = ("internship", "apprenticeship", "fixed", "permanent", "other")
LANGS = ("it", "en", "de", "fr", "es")

# ---------------------------------------------------------------- preset ----
_SENIOR_PEN = {"senior": -12, "sr.": -12, "lead": -10, "principal": -15, "head of": -20, "director": -20,
               "manager": -12, "staff": -10, "vp": -25, "architect": -8}
_JUNIOR_BONUS = {"junior": 12, "entry": 10, "trainee": 10, "intern": 6, "graduate": 8, "associate": 4}

# Cybersecurity: gli stessi termini e pesi di config.example.toml. Se config.toml li modifica, vince il config
# (vedi `Rules`): il preset e' il valore predefinito, non un'imposizione.
_CYBER_GROUPS = [
    {"label": "BLUE", "terms": {"soc analyst": 12, "soc": 6, "blue team": 12, "siem": 8, "splunk": 6, "wazuh": 8,
                                "qradar": 6, "sentinel": 5, "edr": 5, "incident response": 9, "dfir": 9,
                                "threat hunting": 8, "threat detection": 7, "detection engineer": 9,
                                "security analyst": 9, "forensic": 6, "malware analysis": 6,
                                "threat intelligence": 6, "mdr": 4}},
    {"label": "RED", "terms": {"penetration test": 12, "pentest": 12, "pen tester": 12, "red team": 12,
                               "offensive security": 12, "vulnerability assessment": 9, "vulnerability": 4,
                               "ethical hacker": 10, "exploit": 6, "oscp": 8, "ejpt": 8, "security researcher": 7,
                               "application security": 6, "appsec": 6, "bug bounty": 5, "metasploit": 4, "burp": 4}},
    {"label": "SYSADM", "terms": {"sistemista": 12, "system administrator": 12, "sysadmin": 12, "systems engineer": 8,
                                  "tecnico informatico": 8, "tecnico sistemista": 10, "it support": 6,
                                  "help desk": 4, "active directory": 7, "windows server": 7, "linux": 5,
                                  "vmware": 4, "proxmox": 5, "infrastructure": 3, "network administrator": 8,
                                  "networking": 3, "backup": 3}},
    {"label": "SEC", "terms": {"cybersecurity": 8, "cyber security": 8, "information security": 7, "infosec": 7,
                               "security engineer": 6, "security": 2, "sicurezza informatica": 8}},
]
_CYBER_BLACKLIST = ["sales", "account executive", "marketing", "recruiter", "legal", "counsel", "customer success",
                    "business development", "finance", "accountant", "designer"]
_CYBER_BONUS = {"junior": 12, "entry": 10, "trainee": 10, "intern": 6, "graduate": 8, "associate": 4,
                "tier 1": 8, "l1": 6}

PRESETS: dict[str, dict] = {
    "cybersecurity": {
        "label": "Cybersecurity: Blue, Red, Sysadmin",
        "description": "Sicurezza informatica (SOC, pentest) e amministrazione di sistemi.",
        "default_titles": ["soc analyst", "penetration tester", "sistemista", "security analyst"],
        "queries": {
            "it": ["cyber security", "soc analyst", "penetration tester", "sistemista", "system administrator",
                   "tecnico informatico", "security analyst"],
            "en": ["cyber security", "soc analyst", "penetration tester", "security analyst",
                   "system administrator", "security engineer", "incident response"],
            "de": ["cyber security", "it security", "soc analyst", "systemadministrator", "penetration tester"],
            "fr": ["cyber securite", "analyste soc", "administrateur systemes", "pentester"],
            "es": ["ciberseguridad", "analista soc", "administrador de sistemas", "pentester"],
        },
        "internship_queries": {
            "it": ["stage cyber security", "tirocinio sicurezza informatica", "stage sistemista"],
            "en": ["internship cybersecurity"], "de": ["praktikum it security"], "fr": ["stage cybersecurite"],
            "es": ["practicas ciberseguridad"],
        },
        "groups": _CYBER_GROUPS,
        "blacklist": _CYBER_BLACKLIST,
        "level_penalties": {"senior": -12, "sr.": -12, "lead": -10, "principal": -15, "head of": -20,
                            "director": -20, "manager": -12, "staff": -10, "vp": -25, "architect": -8},
        "level_bonus": _CYBER_BONUS,
    },
    "it_support": {
        "label": "Sistemista e assistenza IT",
        "description": "Assistenza tecnica, help desk, sistemisti e reti.",
        "default_titles": ["tecnico informatico", "help desk", "sistemista", "supporto it"],
        "queries": {
            "it": ["tecnico informatico", "help desk", "sistemista", "assistenza it", "tecnico di rete", "supporto it"],
            "en": ["it support", "help desk", "system administrator", "desktop support", "network technician",
                   "it technician"],
            "de": ["it support", "systemadministrator", "it techniker", "helpdesk"],
            "fr": ["technicien informatique", "support informatique", "administrateur systemes", "helpdesk"],
            "es": ["tecnico informatico", "soporte it", "administrador de sistemas", "helpdesk"],
        },
        "groups": [
            {"label": "SUPPORTO", "terms": {"help desk": 12, "helpdesk": 12, "it support": 12, "supporto it": 12,
                                            "assistenza tecnica": 10, "assistenza it": 12, "service desk": 10,
                                            "desktop support": 10, "tecnico informatico": 12, "it technician": 10,
                                            "ticket": 4, "assistenza": 4, "soporte": 6, "support informatique": 10}},
            {"label": "SISTEMI", "terms": {"sistemista": 12, "system administrator": 12, "sysadmin": 12,
                                          "systemadministrator": 12, "administrador de sistemas": 12,
                                          "administrateur systemes": 12, "windows server": 7,
                                          "active directory": 7, "linux": 5, "vmware": 4, "microsoft 365": 4,
                                          "office 365": 4, "virtualizzazione": 4, "backup": 3}},
            {"label": "RETI", "terms": {"network administrator": 10, "tecnico di rete": 10, "networking": 4,
                                       "cisco": 5, "firewall": 4, "lan": 3, "wifi": 3, "network technician": 10}},
        ],
        "blacklist": ["sales", "marketing", "recruiter", "account executive", "legal", "finance", "designer",
                      "business development", "accountant"],
        "level_penalties": _SENIOR_PEN, "level_bonus": _JUNIOR_BONUS,
    },
    "software_dev": {
        "label": "Sviluppo software",
        "description": "Sviluppatori e ingegneri del software (backend, frontend, mobile, DevOps).",
        "default_titles": ["sviluppatore software", "backend developer", "frontend developer"],
        "queries": {
            "it": ["sviluppatore software", "programmatore", "sviluppatore web", "full stack developer",
                   "sviluppatore python", "sviluppatore java"],
            "en": ["software developer", "software engineer", "backend developer", "frontend developer",
                   "full stack developer", "devops engineer"],
            "de": ["softwareentwickler", "software engineer", "webentwickler", "backend entwickler"],
            "fr": ["developpeur logiciel", "developpeur web", "ingenieur logiciel", "developpeur full stack"],
            "es": ["desarrollador de software", "programador", "desarrollador web", "ingeniero de software"],
        },
        "groups": [
            {"label": "BACKEND", "terms": {"backend": 10, "back end": 10, "back-end": 10, "python": 6, "java": 6,
                                          "node.js": 6, "golang": 6, "php": 5, "c#": 5, ".net": 5, "django": 5,
                                          "spring": 4, "api": 3, "microservizi": 4, "microservices": 4,
                                          "sql": 3, "postgresql": 3}},
            {"label": "FRONTEND", "terms": {"frontend": 10, "front end": 10, "front-end": 10, "react": 7,
                                           "angular": 7, "vue": 7, "typescript": 5, "javascript": 5, "css": 3,
                                           "html": 3, "sviluppatore web": 10, "web developer": 10, "webentwickler": 10}},
            {"label": "SOFTWARE", "terms": {"sviluppatore software": 12, "software developer": 12,
                                           "software engineer": 12, "programmatore": 12, "developer": 8,
                                           "sviluppatore": 8, "softwareentwickler": 12, "full stack": 10,
                                           "fullstack": 10, "programmer": 8, "desarrollador": 8,
                                           "developpeur": 8, "ingeniero de software": 12}},
            {"label": "MOBILE", "terms": {"android": 7, "ios": 7, "swift": 6, "kotlin": 6, "flutter": 6,
                                         "react native": 7, "mobile developer": 10}},
            {"label": "DEVOPS", "terms": {"devops": 10, "kubernetes": 6, "docker": 5, "ci/cd": 5, "terraform": 5,
                                         "aws": 3, "azure": 3, "site reliability": 8, "sre": 6}},
        ],
        "blacklist": ["sales", "marketing", "recruiter", "account executive", "legal", "finance", "designer",
                      "business development", "accountant", "customer success"],
        "level_penalties": _SENIOR_PEN, "level_bonus": _JUNIOR_BONUS,
    },
    "data": {
        "label": "Dati e analisi",
        "description": "Analisti dei dati, data scientist, data engineer e business intelligence.",
        "default_titles": ["data analyst", "data scientist", "business intelligence"],
        "queries": {
            "it": ["data analyst", "analista dati", "data scientist", "data engineer", "business intelligence",
                   "analista bi"],
            "en": ["data analyst", "data scientist", "data engineer", "business intelligence", "machine learning engineer",
                   "bi developer"],
            "de": ["data analyst", "data scientist", "datenanalyst", "data engineer"],
            "fr": ["analyste de donnees", "data scientist", "data engineer", "business intelligence"],
            "es": ["analista de datos", "data scientist", "ingeniero de datos", "business intelligence"],
        },
        "groups": [
            {"label": "ANALISI", "terms": {"data analyst": 12, "analista dati": 12, "analista di dati": 12,
                                          "datenanalyst": 12, "analyste de donnees": 12, "analista de datos": 12,
                                          "business analyst": 8, "excel": 3, "reporting": 4, "kpi": 3,
                                          "business intelligence": 10, "power bi": 7, "tableau": 7, "looker": 6,
                                          "analista bi": 10, "bi developer": 10}},
            {"label": "SCIENZA", "terms": {"data scientist": 12, "machine learning": 9, "ml engineer": 9,
                                           "deep learning": 8, "statistica": 5, "statistics": 5, "nlp": 6,
                                           "intelligenza artificiale": 6, "artificial intelligence": 6, "scikit": 4,
                                           "pytorch": 5, "tensorflow": 5}},
            {"label": "DATA ENG", "terms": {"data engineer": 12, "ingeniero de datos": 12, "etl": 7, "spark": 6,
                                            "airflow": 6, "dbt": 5, "data warehouse": 7, "snowflake": 5,
                                            "bigquery": 5, "sql": 5, "python": 3, "pipeline": 3}},
        ],
        "blacklist": ["sales", "marketing", "recruiter", "account executive", "legal", "designer",
                      "business development", "customer success"],
        "level_penalties": _SENIOR_PEN, "level_bonus": _JUNIOR_BONUS,
    },
    "admin_office": {
        "label": "Amministrazione e ufficio",
        "description": "Segreteria, contabilità, amministrazione, risorse umane e back office.",
        "default_titles": ["impiegato amministrativo", "segretaria", "contabile"],
        "queries": {
            "it": ["impiegato amministrativo", "segretaria", "addetto contabilita", "back office",
                   "impiegata amministrativa", "assistente di direzione"],
            "en": ["administrative assistant", "office administrator", "bookkeeper", "back office", "accounts assistant",
                   "executive assistant"],
            "de": ["verwaltungsangestellter", "buchhalter", "sekretaer", "bueroassistent"],
            "fr": ["assistant administratif", "comptable", "secretaire", "gestionnaire administratif"],
            "es": ["administrativo", "auxiliar administrativo", "contable", "secretaria"],
        },
        "groups": [
            {"label": "AMMINISTRAZIONE", "terms": {"impiegato amministrativo": 12, "impiegata amministrativa": 12,
                                                    "addetto amministrativo": 12, "amministrativo": 9,
                                                    "administrative assistant": 12, "office administrator": 12,
                                                    "auxiliar administrativo": 12, "administrativo": 9,
                                                    "assistant administratif": 12, "back office": 9,
                                                    "data entry": 6, "fatturazione": 6, "archiviazione": 3}},
            {"label": "CONTABILITA", "terms": {"contabile": 12, "addetto contabilita": 12, "contabilita": 8,
                                               "bookkeeper": 12, "accounts assistant": 10, "comptable": 12,
                                               "buchhalter": 12, "contable": 12, "prima nota": 6, "bilancio": 5,
                                               "payroll": 6, "paghe": 6}},
            {"label": "SEGRETERIA", "terms": {"segretaria": 12, "segretario": 12, "segreteria": 9,
                                              "assistente di direzione": 12, "executive assistant": 12,
                                              "receptionist": 10, "reception": 6, "sekretaer": 12,
                                              "secretaire": 12, "bueroassistent": 12, "centralino": 5}},
        ],
        "blacklist": ["sviluppatore", "developer", "engineer", "ingegnere", "sales", "marketing", "recruiter"],
        "level_penalties": _SENIOR_PEN, "level_bonus": _JUNIOR_BONUS,
    },
    "sales_marketing": {
        "label": "Vendite e marketing",
        "description": "Commerciali, account, marketing digitale e comunicazione.",
        "default_titles": ["addetto vendite", "marketing specialist", "account manager"],
        "queries": {
            "it": ["addetto vendite", "commerciale", "marketing specialist", "social media manager",
                   "account manager", "digital marketing"],
            "en": ["sales representative", "account manager", "marketing specialist", "digital marketing",
                   "social media manager", "business development"],
            "de": ["vertriebsmitarbeiter", "marketing manager", "account manager", "online marketing"],
            "fr": ["commercial", "charge de marketing", "responsable marketing", "account manager"],
            "es": ["comercial", "especialista en marketing", "ejecutivo de ventas", "community manager"],
        },
        "groups": [
            {"label": "VENDITE", "terms": {"addetto vendite": 12, "commerciale": 10, "sales representative": 12,
                                          "sales executive": 12, "account manager": 10, "account executive": 10,
                                          "business development": 9, "vendite": 7, "vertriebsmitarbeiter": 12,
                                          "ejecutivo de ventas": 12, "comercial": 9, "vendeur": 8,
                                          "venditore": 12, "agente di commercio": 10}},
            {"label": "MARKETING", "terms": {"marketing specialist": 12, "digital marketing": 12,
                                            "social media manager": 12, "marketing manager": 10, "marketing": 7,
                                            "seo": 6, "sem": 5, "content": 3, "community manager": 10,
                                            "online marketing": 10, "copywriter": 7, "brand": 3}},
        ],
        "blacklist": ["sviluppatore", "developer", "engineer", "ingegnere", "recruiter", "accountant"],
        "level_penalties": _SENIOR_PEN, "level_bonus": _JUNIOR_BONUS,
    },
    "custom": {
        "label": "Personalizzato",
        "description": "Scrivi tu i lavori che cerchi (es. infermiere, magazziniere carrellista).",
        "default_titles": [],
        "queries": {l: [] for l in ("it", "en")},
        "groups": [],
        "blacklist": [],
        "level_penalties": _SENIOR_PEN, "level_bonus": _JUNIOR_BONUS,
    },
}

STOPWORDS = {
    "it": {"di", "da", "del", "della", "dello", "dei", "delle", "il", "lo", "la", "le", "gli", "un", "una", "uno",
           "per", "con", "su", "in", "e", "ed", "al", "alla", "ai", "alle", "addetto", "addetta", "tra", "fra"},
    "en": {"the", "of", "and", "for", "a", "an", "to", "in", "at", "with", "on", "or"},
    "de": {"der", "die", "das", "und", "fuer", "mit", "von", "im", "in", "zu", "m", "w", "d"},
    "fr": {"le", "la", "les", "de", "du", "des", "et", "pour", "un", "une", "en", "au", "aux"},
    "es": {"el", "la", "los", "las", "de", "del", "y", "para", "un", "una", "en", "con"},
}
ALL_STOP = set().union(*STOPWORDS.values())
INTERN_PREFIX = {"it": "stage", "en": "internship", "de": "praktikum", "fr": "stage", "es": "practicas"}

# pesi dei termini ricavati dai titoli liberi: la frase intera conta molto, le singole parole meno
TITLE_PHRASE_WEIGHT = 12
TITLE_WORD_WEIGHT = 5
# Parole che da sole non dicono il mestiere ("engineer" vale per ingegneri di ogni tipo, "software" anche per i tester):
# pesano poco, cosi' una sola di esse nel titolo (peso x3) resta sotto la soglia minima e serve almeno una parola specifica
# o un'altra parola del titolo. Parole specifiche (infermiere, carrellista, backend) continuano a bastare da sole.
GENERIC_WORD_WEIGHT = 2
GENERIC_WORDS = {
    "engineer", "engineering", "developer", "software", "manager", "analyst", "specialist", "assistant", "consultant",
    "technician", "officer", "expert", "senior", "junior", "lead", "head", "agent", "worker", "operator", "executive",
    "administrator", "coordinator", "supervisor", "director", "responsabile", "addetto", "addetta", "tecnico", "operatore",
    "operatrice", "impiegato", "impiegata", "consulente", "esperto", "specialista", "ingegnere", "sviluppatore",
    "assistente", "coordinatore", "analista", "gestione", "ingenieur", "entwickler", "mitarbeiter", "berater",
    "ingenieria", "desarrollador", "tecnico", "responsable", "technicien", "developpeur",
}


PROFILE_LOCK = threading.Lock()  # creare/modificare/eliminare un profilo + ricalcolarne gli annunci: uno alla volta (ordine dei blocchi: COMPLETE_LOCK della guida, poi questo)


class ProfileError(ValueError):
    """Profilo non valido: il messaggio e' in italiano e adatto a essere mostrato all'utente."""


# --------------------------------------------------------------- modello ----
@dataclass
class Profile:
    name: str
    preset: str = "custom"
    active: bool = True
    titles: list[str] = field(default_factory=list)
    include: dict[str, int] = field(default_factory=dict)
    exclude: list[str] = field(default_factory=list)
    seniority: str = "any"
    contracts: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=lambda: [DEFAULT_COUNTRY])
    location: dict = field(default_factory=lambda: {"city": "", "radius_km": 100})
    remote: bool = True
    internships: bool = True
    categories: list[dict] = field(default_factory=list)   # categorie personali: [{"label", "terms", "weights"?}]
    id: int | None = None
    created: str = ""
    updated: str = ""

    def to_dict(self, *, meta: bool = False) -> dict:
        d = {"name": self.name, "preset": self.preset, "active": self.active, "titles": list(self.titles),
             "include": dict(self.include), "exclude": list(self.exclude), "seniority": self.seniority,
             "contracts": list(self.contracts), "countries": list(self.countries), "location": dict(self.location),
             "remote": self.remote, "internships": self.internships}
        if self.categories:  # assente = vuoto = comportamento di sempre (i profili salvati prima della fase 6 non hanno la chiave)
            d["categories"] = [_cat_out(c) for c in self.categories]
        if meta:
            d.update(id=self.id, created=self.created, updated=self.updated)
        return d

    @property
    def city(self) -> str:
        return (self.location or {}).get("city", "") or ""

    @property
    def radius_km(self) -> int:
        return int((self.location or {}).get("radius_km") or 100)


def as_profile(p) -> Profile:
    """Accetta un Profile o un dizionario (anche incompleto) e ritorna un Profile senza controlli severi."""
    if isinstance(p, Profile):
        return p
    d = dict(p or {})
    loc = d.get("location") or {}
    return Profile(
        name=str(d.get("name") or ""), preset=str(d.get("preset") or "custom"), active=bool(d.get("active", True)),
        titles=[str(t) for t in d.get("titles") or []], include={str(k): int(v) for k, v in (d.get("include") or {}).items()},
        exclude=[str(t) for t in d.get("exclude") or []], seniority=str(d.get("seniority") or "any"),
        contracts=[str(c) for c in d.get("contracts") or []], countries=[str(c) for c in d.get("countries") or [DEFAULT_COUNTRY]],
        location={"city": str(loc.get("city") or ""), "radius_km": int(loc.get("radius_km") or 100)},
        remote=bool(d.get("remote", True)), internships=bool(d.get("internships", True)),
        categories=_cats_lenient(d.get("categories")),
        id=d.get("id"), created=d.get("created") or "", updated=d.get("updated") or "")


# ------------------------------------------------------------ categorie ----
MAX_CATEGORIES = 12
MAX_CAT_TERMS = 20            # parole per categoria scritte dall'utente
MAX_CAT_TOTAL = 40            # tetto assoluto (preset con molti gruppi nel config)
TRUSTED_TERMS = 300           # parole di una categoria COPIATA da un preset (con i pesi di sempre): si accetta cio' che il preset o il config danno
CAT_LABEL_MAX = 16
CAT_TERM_MIN, CAT_TERM_MAX = 2, 40
CAT_DEFAULT_WEIGHT = 5
RESERVED_LABELS = {"ALTRO"}
_LABEL_OK = re.compile(r"^[^\W_](?:[^\W_]| |-)*$")   # lettere e numeri (anche accentati), spazio, trattino; mai simboli


def _cat_out(c: dict) -> dict:
    out = {"label": c["label"], "terms": list(c["terms"])}
    if c.get("weights"):
        out["weights"] = dict(c["weights"])
    return out


def _cats_lenient(value) -> list[dict]:
    """Legge le categorie salvate senza mai sollevare errori (un profilo vecchio o rovinato si legge comunque)."""
    out = []
    if not isinstance(value, list):
        return out
    for c in value[:MAX_CAT_TOTAL]:
        if not isinstance(c, dict) or not isinstance(c.get("label"), str) or not isinstance(c.get("terms"), list):
            continue
        terms = [t for t in c["terms"] if isinstance(t, str) and t.strip()]
        if not terms:
            continue
        w = c.get("weights")
        weights = {str(k).lower(): int(v) for k, v in w.items() if isinstance(v, (int, float)) and not isinstance(v, bool)} if isinstance(w, dict) else {}
        out.append({"label": c["label"], "terms": terms, **({"weights": weights} if weights else {})})
    return out


def normalize_label(raw) -> str:
    """Etichetta di categoria pulita e in maiuscolo, oppure ProfileError.

    Normalizzata in forma NFKC: le lettere con accento combinante diventano quelle normali e le forme "larghe" (ＡＬＴＲＯ) diventano ASCII,
    cosi' ne' i doppioni ne' il nome riservato si aggirano con trucchi di scrittura."""
    if not isinstance(raw, str):
        raise ProfileError("categorie: l'etichetta deve essere un testo")
    label = " ".join(_CTRL.sub(" ", unicodedata.normalize("NFKC", raw)).split()).upper()
    if not label:
        raise ProfileError("categorie: scrivi un nome per la categoria")
    if len(label) > CAT_LABEL_MAX:
        raise ProfileError(f"categorie: il nome «{label[:20]}» e' troppo lungo (massimo {CAT_LABEL_MAX} caratteri)")
    if not _LABEL_OK.match(label):
        raise ProfileError("categorie: il nome puo' avere solo lettere, numeri, spazi e trattini")
    if label in RESERVED_LABELS:
        raise ProfileError(f"categorie: «{label}» e' un nome riservato, scegline un altro")
    return label


def own_labels(preset_key: str, cfg: dict | None = None) -> set[str]:
    """Etichette (maiuscole) dei gruppi del preset: le categorie con questi nomi e con i pesi sono i gruppi di punteggio del tipo di profilo."""
    return {c["label"].upper() for c in preset_categories(preset_key, cfg)}


def _trusted(label: str, preset: str | None) -> bool:
    """Una categoria pesata di un tipo di profilo (non personalizzato) e' "copiata dal preset": limiti larghi, nessuna modifica dei suoi valori.
    Per la cybersecurity i nomi possono venire dal config, quindi basta il tipo; per gli altri serve il nome di un gruppo del preset."""
    if not preset or preset == "custom" or preset not in PRESETS:
        return False
    return preset == "cybersecurity" or label.upper() in {g["label"].upper() for g in PRESETS[preset]["groups"]}


TRUSTED_MAX_WEIGHT = 12       # il peso piu' alto di tutte le categorie dei preset reali (e di config.example.toml)
TRUSTED_TERMS_NO_CFG = 100    # senza il config da confrontare (uso da libreria) si accettano al massimo cosi' tante parole
_LABEL_SAFE = re.compile(r"^[^\W_][\w \-/&+.]*$")   # etichette di un tipo di profilo: niente < > virgolette o simboli strani


def _clean_trusted(c: dict, label_raw, preset: str, cfg: dict | None) -> dict:
    """Categoria che si presenta come "copiata da un tipo di profilo" (ha i pesi).

    La fiducia non viene dalla richiesta ma dal server: vale senza limiti SOLO se coincide esattamente (etichetta, parole e pesi) con una
    categoria che il tipo di profilo (e il config) produrrebbe. Altrimenti e' una modifica dell'utente e ha limiti stretti:
    etichetta sicura, al massimo 20 parole (100 se non c'e' il config da confrontare), pesi da 1 a 12."""
    if not isinstance(label_raw, str):
        raise ProfileError("categorie: l'etichetta deve essere un testo")
    label = " ".join(_CTRL.sub(" ", unicodedata.normalize("NFKC", label_raw)).split()).upper()
    if not label or len(label) > 40:
        raise ProfileError("categorie: nome non valido")
    if label in RESERVED_LABELS:
        raise ProfileError(f"categorie: «{label}» e' un nome riservato, scegline un altro")
    terms = c.get("terms")
    if not isinstance(terms, list) or not terms or len(terms) > TRUSTED_TERMS or any(not isinstance(t, str) or not t.strip() or len(t) > 200 for t in terms):
        raise ProfileError(f"categorie: {label}: parole non valide")
    clean, seen = [], set()
    for t in terms:
        t = unicodedata.normalize("NFC", _clean_text(t))
        if t and t.lower() not in seen:
            seen.add(t.lower())
            clean.append(t)
    weights = {}
    for k, v in (c.get("weights") or {}).items():
        if not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, (int, float)) or not 1 <= v <= 1000:
            raise ProfileError(f"categorie: {label}: il peso deve essere un numero")
        if k.lower() in seen:
            weights[k.lower()] = int(v)
    item = {"label": label, "terms": clean, "weights": weights}
    expected = next((e for e in preset_categories(preset, cfg) if e["label"].upper() == label), None)
    if expected is not None and {t.lower() for t in expected["terms"]} == seen and \
            {k.lower(): int(v) for k, v in expected["weights"].items()} == weights:
        return item  # identica a quella del tipo di profilo: si accetta com'e' (anche se il config ha parole o pesi fuori dai limiti degli utenti)
    if not _LABEL_SAFE.match(label):
        raise ProfileError("categorie: il nome puo' avere solo lettere, numeri, spazi e - / & + .")
    if expected is not None:  # nome di un gruppo del tipo di profilo (o del config): si puo' modificare di poco anche se il gruppo e' grande
        limit = max(40, len(expected["terms"]) + 20)
        if cfg is None:
            limit = max(limit, TRUSTED_TERMS_NO_CFG)  # senza il config il gruppo originale non e' noto: mai piu' stretto del caso senza confronto
    else:
        limit = MAX_CAT_TERMS if cfg is not None else TRUSTED_TERMS_NO_CFG
    if len(clean) > limit:
        raise ProfileError(f"categorie: {label}: massimo {limit} parole")
    if any(len(t) > 80 for t in clean):
        raise ProfileError(f"categorie: {label}: ogni parola puo' avere al massimo 80 caratteri")
    if any(not 1 <= w <= TRUSTED_MAX_WEIGHT for w in weights.values()):
        raise ProfileError(f"categorie: {label}: il peso deve essere un numero da 1 a {TRUSTED_MAX_WEIGHT}")
    return item


def clean_categories(value, preset: str | None = None, cfg: dict | None = None) -> list[dict]:
    """Controlla le categorie ricevute dall'esterno. ProfileError con messaggi in italiano che iniziano con «categorie:»."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProfileError("categorie: serve un elenco")
    if len(value) > MAX_CAT_TOTAL:
        raise ProfileError(f"categorie: massimo {MAX_CATEGORIES} per profilo")
    out, seen, own_count = [], set(), 0
    for c in value:
        if not isinstance(c, dict):
            raise ProfileError("categorie: ogni categoria deve avere un nome e delle parole")
        raw_w = c.get("weights")
        if raw_w is not None and not isinstance(raw_w, dict):
            raise ProfileError("categorie: pesi non validi")
        trusted = bool(raw_w) and isinstance(c.get("label"), str) and _trusted(" ".join(unicodedata.normalize("NFKC", c["label"]).split()), preset)
        if trusted:
            item = _clean_trusted(c, c["label"], preset, cfg)
            label = item["label"]
            own_count += 1
        else:
            label = normalize_label(c.get("label"))
            terms = c.get("terms")
            if isinstance(terms, str):  # comodo per chi scrive "cuoco, chef" in un campo solo
                terms = [t for t in re.split(r"[,;\n]", terms)]
            if not isinstance(terms, list):
                raise ProfileError(f"categorie: {label}: servono delle parole")
            terms = [unicodedata.normalize("NFC", t) if isinstance(t, str) else t for t in terms]
            clean = _clean_words(terms, f"categorie: {label}: parole", maxn=MAX_CAT_TERMS, maxlen=CAT_TERM_MAX, minlen=CAT_TERM_MIN)
            if not clean:
                raise ProfileError(f"categorie: {label}: scrivi almeno una parola che la riconosce")
            item = {"label": label, "terms": clean}
            if raw_w:
                have = {t.lower() for t in clean}
                weights = {}
                for k, v in raw_w.items():
                    if not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, (int, float)) or not 1 <= v <= 20:
                        raise ProfileError(f"categorie: {label}: il peso deve essere un numero da 1 a 20")
                    if k.lower() in have:  # i pesi di parole tolte si scartano in silenzio
                        weights[k.lower()] = int(v)
                if weights:
                    item["weights"] = weights
        if label in seen:
            raise ProfileError(f"categorie: «{label}» e' ripetuta")
        seen.add(label)
        out.append(item)
    if len(out) - own_count > MAX_CATEGORIES:
        raise ProfileError(f"categorie: massimo {MAX_CATEGORIES} per profilo")
    return out


def cat_terms(c: dict) -> dict[str, int]:
    """{parola: peso} di una categoria (le parole senza peso valgono quanto una parola di un titolo)."""
    w = c.get("weights") or {}
    return {t: int(w.get(t.lower(), CAT_DEFAULT_WEIGHT)) for t in c["terms"]}


def preset_categories(preset_key: str, cfg: dict | None = None) -> list[dict]:
    """Le categorie di un preset (gruppi di parole con i pesi di sempre), pronte da copiare in un profilo.

    Per la cybersecurity valgono le parole del config se le ha cambiate (come fa il punteggio di sempre). Niente viene troncato ne'
    ritoccato (etichette, parole, pesi): il punteggio del profilo copiato e' identico a quello dei gruppi. Le copie si salvano di nuovo
    senza errori perche' la validazione le riconosce come "categorie di un tipo di profilo" (vedi `_trusted`)."""
    preset = PRESETS.get(preset_key)
    if not preset or preset_key == "custom":
        return []
    if preset_key == "cybersecurity" and cfg and cfg.get("keywords"):
        groups = [(c["label"], dict(c["terms"])) for c in cfg["keywords"].values()]
    else:
        groups = [(g["label"], dict(g["terms"])) for g in preset["groups"]]
    out = []
    for label, terms in groups:
        label = str(label).upper()
        terms = {str(k): v for k, v in terms.items() if str(k).strip() and isinstance(v, (int, float)) and not isinstance(v, bool)}
        if label and terms:
            out.append({"label": label, "terms": list(terms), "weights": {k.lower(): int(v) for k, v in terms.items()}})
    return out[:MAX_CAT_TOTAL]


def _clean_words(value, what: str, *, maxn: int, maxlen: int = 80, minlen: int = 2) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProfileError(f"{what}: serve un elenco")
    out, seen = [], set()
    for v in value:
        if not isinstance(v, str):
            raise ProfileError(f"{what}: ogni voce deve essere un testo")
        v = _clean_text(v)
        if not v:
            continue
        if len(v) < minlen or len(v) > maxlen:
            raise ProfileError(f"{what}: ogni voce deve avere da {minlen} a {maxlen} caratteri")
        if v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    if len(out) > maxn:
        raise ProfileError(f"{what}: massimo {maxn} voci")
    return out


_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _clean_text(v: str) -> str:
    """Testo su una riga, senza caratteri di controllo (es. NUL) e con gli spazi ripuliti."""
    return " ".join(_CTRL.sub(" ", v).split())


def validate_profile(data, cfg: dict | None = None) -> Profile:
    """Controlla un profilo ricevuto dall'esterno e ritorna un Profile pulito, oppure solleva ProfileError."""
    if not isinstance(data, dict):
        raise ProfileError("il profilo deve essere un oggetto JSON")
    name = data.get("name")
    if not isinstance(name, str) or not _clean_text(name):
        raise ProfileError("serve un nome per il profilo")
    name = _clean_text(name)
    if len(name) > 80:
        raise ProfileError("il nome può avere al massimo 80 caratteri")
    preset = data.get("preset", "custom")
    if not isinstance(preset, str) or preset not in PRESETS:
        raise ProfileError("tipo di profilo sconosciuto")
    titles = _clean_words(data.get("titles"), "titoli", maxn=20, minlen=1)
    if preset == "custom" and not titles:
        raise ProfileError("scrivi almeno un lavoro che cerchi (esempio: infermiere)")
    include = data.get("include") or {}
    if not isinstance(include, dict):
        raise ProfileError("parole chiave extra: serve un elenco parola e peso")
    inc: dict[str, int] = {}
    for k, v in include.items():
        if not isinstance(k, str) or not _clean_text(k) or len(k) > 60:
            raise ProfileError("parole chiave extra: testo non valido")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 1 <= v <= 15:
            raise ProfileError("parole chiave extra: il peso deve essere un numero da 1 a 15")
        inc[_clean_text(k).lower()] = int(v)
    if len(inc) > 60:
        raise ProfileError("parole chiave extra: massimo 60")
    exclude = _clean_words(data.get("exclude"), "parole da escludere", maxn=60, maxlen=60, minlen=1)
    seniority = data.get("seniority", "any")
    if not isinstance(seniority, str) or seniority not in SENIORITY:
        raise ProfileError("livello non valido (any, junior, mid o senior)")
    contracts = data.get("contracts") or []
    if not isinstance(contracts, list) or any(not isinstance(c, str) or c not in CONTRACTS for c in contracts):
        raise ProfileError("tipo di contratto non valido")
    countries = data.get("countries", [DEFAULT_COUNTRY])
    if not isinstance(countries, list) or not countries:
        raise ProfileError("scegli almeno un paese")
    if any(not isinstance(c, str) for c in countries):
        raise ProfileError("paese non valido")
    countries = [c.lower() for c in countries]
    bad = [c for c in countries if c not in COUNTRIES]
    if bad:
        raise ProfileError(f"paese sconosciuto: {bad[0]}")
    countries = list(dict.fromkeys(countries))
    loc = data.get("location") or {}
    if not isinstance(loc, dict):
        raise ProfileError("luogo non valido")
    city = loc.get("city") or ""
    if not isinstance(city, str) or len(city) > 80:
        raise ProfileError("città non valida")
    radius = loc.get("radius_km", 100)
    if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not 1 <= radius <= 3000:
        raise ProfileError("il raggio deve essere tra 1 e 3000 km")
    for key in ("active", "remote", "internships"):
        if key in data and not isinstance(data[key], bool):
            raise ProfileError(f"{key}: serve vero o falso")
    categories = clean_categories(data.get("categories"), preset, cfg)
    return Profile(name=name, preset=preset, active=data.get("active", True), titles=titles, include=inc,
                   exclude=exclude, seniority=seniority, contracts=list(contracts), countries=countries,
                   location={"city": _clean_text(city), "radius_km": int(radius)},
                   remote=data.get("remote", True), internships=data.get("internships", True), categories=categories)


# ----------------------------------------------------------------- regole ----
@dataclass
class Rules:
    """Regole di punteggio gia' pronte per un profilo (si costruiscono una volta per scansione)."""
    groups: list[tuple[str, dict[str, int]]]
    extra: dict[str, int]
    blacklist: list[str]
    adjust: dict[str, int]          # penalita' e bonus sul titolo (positivi = bonus)
    flex: bool                      # riconosce anche singolare/plurale e genere (infermiere/infermiera/infermieri)
    cyber: bool                     # categoria PURPLE se RED e BLUE sono alti, come prima
    internship_bonus: bool
    cats: list[tuple[str, dict[str, int]]] = field(default_factory=list)  # categorie personali che NON sono gruppi di punteggio (bonus piccolo)
    label_groups: bool = True       # i gruppi di punteggio decidono anche l'etichetta (false = solo le categorie personali)


def significant_words(title: str, lang_hint: str | None = None) -> list[str]:
    words = re.findall(r"[^\W_]+", title.lower())
    stop = ALL_STOP if lang_hint is None else STOPWORDS.get(lang_hint, set()) | STOPWORDS["en"]
    return [w for w in words if len(w) >= 3 and w not in stop]


def title_groups(titles: list[str]) -> list[tuple[str, dict[str, int]]]:
    """Per profili custom: ogni titolo diventa un gruppo (frase intera + parole significative)."""
    used: set[str] = set()
    out = []
    for t in titles:
        phrase = " ".join(t.lower().split())
        terms = {phrase: TITLE_PHRASE_WEIGHT}
        for w in significant_words(phrase):
            if w != phrase and w not in used:
                terms[w] = GENERIC_WORD_WEIGHT if w in GENERIC_WORDS else TITLE_WORD_WEIGHT
        used.update(terms)
        out.append((unicodedata.normalize("NFKC", phrase).upper()[:24], terms))  # stessa normalizzazione delle etichette e del filtro ?cat=
    return out


def level_tables(profile: Profile, preset: dict, cfg: dict | None) -> dict[str, int]:
    """Penalita'/bonus sul titolo in base al livello cercato. Positivo = bonus."""
    cyber = profile.preset == "cybersecurity"
    pen, bon = dict(preset["level_penalties"]), dict(preset["level_bonus"])
    if cyber and cfg and cfg.get("penalties"):
        pen = dict(cfg["penalties"].get("title_terms", pen))
        bon = dict(cfg.get("bonus", {}).get("title_terms", bon))
    sen = profile.seniority
    if sen == "any":
        # senza preferenza esplicita la cybersecurity mantiene la sua taratura storica (dal config); gli altri nulla
        return {**bon, **pen} if cyber else {}
    if sen == "junior":
        return {**bon, **pen}
    leads = {k: v for k, v in _SENIOR_PEN.items() if k not in ("senior", "sr.")}
    if sen == "mid":
        return {**leads, "junior": -10, "entry": -8, "trainee": -10, "intern": -10, "graduate": -8}
    return {"senior": 10, "sr.": 10, "lead": 8, "principal": 8, "manager": 6, "head of": 6, "staff": 6,
            "junior": -15, "entry": -15, "trainee": -15, "intern": -15, "graduate": -12}  # senior


def build_rules(profile, cfg: dict | None = None) -> Rules:
    p = as_profile(profile)
    preset = PRESETS.get(p.preset, PRESETS["custom"])
    cyber = p.preset == "cybersecurity"
    groups: list[tuple[str, dict[str, int]]] = []
    blacklist = list(preset["blacklist"])
    if cyber and cfg and cfg.get("keywords"):
        groups = [(c["label"], dict(c["terms"])) for c in cfg["keywords"].values()]
        blacklist = list(cfg.get("penalties", {}).get("blacklist", blacklist))
    elif p.preset == "custom":
        groups = title_groups(p.titles)
    else:
        groups = [(g["label"], dict(g["terms"])) for g in preset["groups"]]
        if p.titles:
            groups += title_groups(p.titles)  # i titoli scelti dall'utente si aggiungono al preset
    if cyber and p.titles:
        groups += title_groups(p.titles)
    cats: list[tuple[str, dict[str, int]]] = []
    label_groups = True
    if p.categories:
        own = own_labels(p.preset, cfg) if p.preset != "custom" else set()
        # pesate E del tipo di profilo = gruppi di punteggio; una categoria "nota" aggiunta da un altro tipo (es. BLUE a un profilo di sviluppo) e' una categoria dell'utente
        weighted = [c for c in p.categories if c.get("weights") and c["label"].upper() in own]
        if p.preset == "custom":
            cats = [(c["label"], cat_terms(c)) for c in p.categories]
            label_groups = False   # i titoli danno il punteggio, le categorie scelte dall'utente danno l'etichetta
        else:
            if weighted:  # categorie copiate dal preset: SONO i gruppi di punteggio (stessi termini e pesi, punteggi invariati)
                groups = [(c["label"], cat_terms(c)) for c in weighted]
                if p.titles:
                    groups += title_groups(p.titles)
            cats = [(c["label"], cat_terms(c)) for c in p.categories if c not in weighted]
            label_groups = bool(weighted)
    adjust = level_tables(p, preset, cfg)
    if p.internships:
        from .scoring import DEFAULT_BONUS

        adjust = {**DEFAULT_BONUS, **adjust}
    return Rules(groups=groups, extra=dict(p.include), blacklist=blacklist + list(p.exclude), adjust=adjust,
                 flex=not cyber, cyber=cyber, internship_bonus=p.internships, cats=cats, label_groups=label_groups)


def keywords_of(profile, cfg: dict | None = None) -> list[dict]:
    """Elenco piatto {term, weight, group} per l'anteprima."""
    r = build_rules(profile, cfg)
    out = [{"term": t, "weight": w, "group": g} for g, terms in r.groups for t, w in terms.items()]
    out += [{"term": t, "weight": w, "group": label} for label, terms in r.cats for t, w in terms.items()]
    out += [{"term": t, "weight": w, "group": "EXTRA"} for t, w in r.extra.items()]
    return out


# ------------------------------------------------------------------ query ----
@dataclass(frozen=True)
class Query:
    q: str
    country: str
    where: str = ""
    radius_km: int | None = None
    pages: tuple = (1, 2)


def country_langs(country: str, preset_key: str, titles: bool = False) -> list[str]:
    """Lingue da usare per le ricerche in un paese: quelle del paese che il preset conosce, altrimenti inglese."""
    have = PRESETS.get(preset_key, PRESETS["custom"])["queries"]
    if preset_key == "custom":  # i titoli sono scritti dall'utente: conta solo la lingua del paese (per "stage"/"internship")
        have = {l: True for l in INTERN_PREFIX}
    langs = [l for l in COUNTRIES.get(country, {}).get("languages", []) if have.get(l)]
    return langs[:1] if preset_key == "custom" else (langs[:2] or ["en"])


def preset_queries(preset_key: str, lang: str, cfg: dict | None = None) -> list[str]:
    preset = PRESETS.get(preset_key, PRESETS["custom"])
    if preset_key == "cybersecurity" and lang == "it" and cfg:
        q = (cfg.get("sources", {}).get("adzuna", {}) or {}).get("queries")
        if q:
            return list(q)  # le ricerche scelte dall'utente in config.toml restano valide
    return list(preset["queries"].get(lang) or preset["queries"].get("en") or [])


def internship_queries(profile: Profile, lang: str, cfg: dict | None, base: list[str]) -> list[str]:
    preset = PRESETS.get(profile.preset, PRESETS["custom"])
    if profile.preset == "cybersecurity" and cfg:
        from .sources.base import DEFAULT_INTERNSHIP_QUERIES

        custom = (cfg.get("sources", {}).get("adzuna", {}) or {}).get("internship_queries")
        if custom and lang == "it":
            return list(custom)
        if lang == "it" and not preset.get("internship_queries"):
            return list(DEFAULT_INTERNSHIP_QUERIES[:1])
    given = (preset.get("internship_queries") or {}).get(lang)
    if given:
        return list(given)
    prefix = INTERN_PREFIX.get(lang, "internship")
    return [f"{prefix} {q}" for q in base[:2]]


def _city_country(city: str, countries: list[str]) -> str:
    """In quale dei paesi del profilo si trova la citta' (se non si capisce, nel primo)."""
    from . import geo

    for c in countries:
        hit = geo.lookup(city, country=c)
        if hit and hit.get("country", "").lower() == c:
            return c
    return countries[0]


def profile_queries(profile, cfg: dict | None = None) -> list[Query]:
    """Le ricerche di UN profilo (le fonti ricevono poi l'unione senza doppioni, vedi `merge_queries`)."""
    p = as_profile(profile)
    cfg = cfg or {}
    out: dict[tuple, Query] = {}

    def add(q: str, country: str, where: str, radius: int | None, pages: tuple) -> None:
        key = (q.lower().strip(), country, where.lower(), radius)
        if not key[0]:
            return
        old = out.get(key)
        if old is None or len(pages) > len(old.pages):
            out[key] = Query(q.strip(), country, where, radius, pages)

    home_country = _city_country(p.city, p.countries) if p.city else None
    for country in p.countries:
        for lang in country_langs(country, p.preset):
            base = preset_queries(p.preset, lang, cfg) if p.preset != "custom" else []
            for t in p.titles:
                if t.lower() not in [b.lower() for b in base]:
                    base.append(t)
            intern = internship_queries(p, lang, cfg, base) if (p.internships and base) else []
            if p.preset == "custom" and p.titles and p.internships:
                intern = [f"{INTERN_PREFIX.get(lang, 'internship')} {t}" for t in p.titles[:2]]
            # con una citta' si cerca nel suo raggio (nel paese della citta'); senza citta' in tutto il paese
            passes = [(p.city, p.radius_km)] if (country == home_country and p.city) else [("", None)]
            for where, radius in passes:
                for q in base:
                    add(q, country, where, radius, (1, 2))
                for q in intern:
                    add(q, country, where, radius, (1,))
    return list(out.values())


def merge_queries(profiles: list, cfg: dict | None = None) -> list[Query]:
    """Unione delle ricerche di piu' profili, senza duplicati (stessa q+paese+luogo = una sola richiesta)."""
    merged: dict[tuple, Query] = {}
    for p in profiles:
        for q in profile_queries(p, cfg):
            key = (q.q.lower(), q.country, q.where.lower(), q.radius_km)
            old = merged.get(key)
            if old is None or len(q.pages) > len(old.pages):
                merged[key] = q
    return list(merged.values())


def estimate_requests(profiles: list, cfg: dict) -> dict[str, int]:
    """Quante richieste farebbe ogni fonte attiva con questi profili (serve all'anteprima)."""
    profs = [as_profile(p) for p in profiles]
    qs = merge_queries(profs, cfg)
    out: dict[str, int] = {}
    srcs = cfg.get("sources", {})
    from .sources.boards import jooble_hosts

    for name, scfg in srcs.items():
        if not isinstance(scfg, dict) or not scfg.get("enabled"):
            continue
        if name == "adzuna":
            out[name] = sum(len(q.pages) for q in qs if COUNTRIES.get(q.country, {}).get("adzuna"))
        elif name == "jooble":
            hosts = jooble_hosts(scfg)
            out[name] = sum(1 for q in qs if q.country in hosts)
        elif name == "arbeitnow":
            out[name] = 3 if any("de" in p.countries for p in profs) else 0
        elif name == "remoteok":
            out[name] = 1 if any(p.remote for p in profs) else 0
        elif name == "remotive":
            out[name] = min(len({q.q.lower() for q in qs if q.country}), 6) if any(p.remote for p in profs) else 0
        elif name == "greenhouse":
            out[name] = len(scfg.get("boards", []))
        elif name == "lever":
            out[name] = len(scfg.get("companies", []))
        else:
            out[name] = 1
    return out


# -------------------------------------------------------------- archivio ----
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileStore:
    """Lettura e scrittura dei profili nel database."""

    def __init__(self, db):
        self.db = db
        self.conn = db.conn

    def _row_to_profile(self, r) -> Profile:
        data = json.loads(r["data"] or "{}")
        p = as_profile({**data, "name": r["name"], "active": bool(r["active"])})
        p.id, p.created, p.updated = r["id"], r["created"], r["updated"]
        return p

    def list(self, only_active: bool = False) -> list[Profile]:
        sql = "SELECT * FROM profiles" + (" WHERE active=1" if only_active else "") + " ORDER BY id"
        return [self._row_to_profile(r) for r in self.conn.execute(sql)]

    def active(self) -> list[Profile]:
        return self.list(only_active=True)

    def get(self, key) -> Profile | None:
        """Per id (numero o testo numerico) oppure per nome (senza distinguere maiuscole)."""
        if isinstance(key, Profile):
            key = key.id
        r = None
        if isinstance(key, bool):
            return None
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            n = int(key)
            if 0 <= n < 2**62:  # id enormi non esistono (e SQLite non li accetta)
                r = self.conn.execute("SELECT * FROM profiles WHERE id=?", (n,)).fetchone()
        if r is None and isinstance(key, str):
            r = self.conn.execute("SELECT * FROM profiles WHERE name=? COLLATE NOCASE", (key.strip(),)).fetchone()
        return self._row_to_profile(r) if r else None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]

    def job_count(self, profile_id: int) -> int:
        """Annunci del profilo che si vedono in elenco (non scartati, non duplicati nascosti, non chiusi)."""
        from .db import DUP_HIDDEN

        return self.conn.execute(
            "SELECT COUNT(*) FROM job_profiles jp JOIN jobs ON jobs.uid=jp.job_uid WHERE jp.profile_id=? "
            f"AND jobs.status!='discarded' AND jobs.avail!='closed' AND jobs.{DUP_HIDDEN}", (profile_id,)).fetchone()[0]

    def _name_taken(self, name: str, except_id: int | None = None) -> bool:
        r = self.conn.execute("SELECT id FROM profiles WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        return bool(r and r["id"] != except_id)

    def add(self, data, cfg: dict | None = None) -> Profile:
        """Crea un profilo. Se e' di un preset e non dice niente sulle categorie, ci si copiano quelle del preset (modificabili)."""
        p = data if isinstance(data, Profile) else validate_profile(data, cfg)
        if isinstance(data, Profile):
            p = validate_profile(data.to_dict(), cfg)
        if not p.categories and not (isinstance(data, dict) and "categories" in data):
            p.categories = preset_categories(p.preset, cfg)
        if self._name_taken(p.name):
            raise ProfileError("esiste già un profilo con questo nome")
        now = now_iso()
        try:
            cur = self.conn.execute(
                "INSERT INTO profiles (name, active, data, created, updated) VALUES (?,?,?,?,?)",
                (p.name, int(p.active), json.dumps(p.to_dict(), ensure_ascii=False), now, now))
        except sqlite3.IntegrityError:  # due richieste insieme con lo stesso nome
            self.conn.rollback()
            raise ProfileError("esiste già un profilo con questo nome") from None
        self.conn.commit()
        return self.get(cur.lastrowid)

    def update(self, profile_id: int, data, cfg: dict | None = None) -> Profile:
        old = self.get(profile_id)
        if old is None:
            raise KeyError(profile_id)
        p = validate_profile(data.to_dict() if isinstance(data, Profile) else data, cfg)
        if p.preset != old.preset:
            # cambio di tipo: le categorie del tipo vecchio (pesate) non restano; si parte da quelle del tipo nuovo, come alla creazione
            p.categories = [c for c in p.categories if not c.get("weights")] + preset_categories(p.preset, cfg)
        if self._name_taken(p.name, old.id):
            raise ProfileError("esiste già un profilo con questo nome")
        try:
            self.conn.execute("UPDATE profiles SET name=?, active=?, data=?, updated=? WHERE id=?",
                              (p.name, int(p.active), json.dumps(p.to_dict(), ensure_ascii=False), now_iso(), old.id))
        except sqlite3.IntegrityError:
            self.conn.rollback()
            raise ProfileError("esiste già un profilo con questo nome") from None
        self.conn.commit()
        return self.get(old.id)

    def raw_row(self, profile_id: int):
        """La riga del profilo com'e' nel database (per rimetterla a posto se un ricalcolo fallisce)."""
        r = self.conn.execute("SELECT name, active, data, updated FROM profiles WHERE id=?", (profile_id,)).fetchone()
        return tuple(r) if r else None

    def restore_raw(self, profile_id: int, row) -> None:
        if row is not None:
            self.conn.execute("UPDATE profiles SET name=?, active=?, data=?, updated=? WHERE id=?", (*row, profile_id))
            self.conn.commit()

    def remove_raw(self, profile_id: int) -> None:
        """Toglie un profilo appena creato senza i controlli di delete (usata se il primo ricalcolo fallisce)."""
        self.conn.execute("DELETE FROM job_profiles WHERE profile_id=?", (profile_id,))
        self.conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        self.conn.commit()

    def set_active(self, profile_id: int, active: bool) -> Profile:
        p = self.get(profile_id)
        if p is None:
            raise KeyError(profile_id)
        return self.update(p.id, replace(p, active=active).to_dict())

    def delete(self, profile_id: int) -> None:
        if self.get(profile_id) is None:
            raise KeyError(profile_id)
        if self.count() <= 1:
            raise ProfileError("non si può eliminare l'ultimo profilo")
        self.conn.execute("DELETE FROM job_profiles WHERE profile_id=?", (profile_id,))
        self.conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        self.conn.commit()
        self.db.drop_orphans()
        self.db.refresh_best()


def default_cyber_profile(cfg: dict | None) -> dict:
    """Il profilo Cybersecurity creato dalla migrazione, ricavato dal config esistente."""
    cfg = cfg or {}
    az = (cfg.get("sources", {}) or {}).get("adzuna", {}) or {}
    city = az.get("home", "") or ""
    radius = az.get("radius_km", 100) or 100
    return {
        "name": "Cybersecurity", "preset": "cybersecurity", "active": True, "titles": [], "include": {},
        "exclude": [], "seniority": "any", "contracts": [], "countries": [DEFAULT_COUNTRY],
        "location": {"city": city, "radius_km": int(radius)},
        "remote": bool((cfg.get("location", {}) or {}).get("allow_remote", True)),
        "internships": bool((cfg.get("search", {}) or {}).get("internships", True)),
    }
