"""Il CV dell'utente: archiviazione locale e profilo ricavato (competenze, anni di esperienza, lingue).

Dal CV si tiene SOLO il testo estratto, in `<cartella dati>/cv.json` con permessi 600 (mai il file originale). Il testo non esce da
questo modulo verso log, API, report o messaggi d'errore: chi lo mostra usa `summary()`, che contiene solo dati derivati.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import settings, skills
from .cvfile import CvError, count_words

CV_FILENAME = "cv.json"
CV_FORMAT = 1
MAX_MANUAL = 80
CVMATCH_VERSION = 3  # aumentalo se cambiano le regole che producono il profilo o il punteggio


def path() -> Path:
    return settings.home() / CV_FILENAME


# ------------------------------------------------------------------ archivio ----
def load() -> dict | None:
    """Il documento salvato, oppure None se non c'e' o non e' leggibile."""
    try:
        doc = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("text"), str) or not doc["text"].strip():
        return None
    doc["skills_manual"] = [s for s in doc.get("skills_manual", []) if isinstance(s, str)][:MAX_MANUAL]
    doc["skills_removed"] = [s for s in doc.get("skills_removed", []) if isinstance(s, str)][:MAX_MANUAL * 4]
    return doc


def _write(doc: dict) -> None:
    """Scrittura atomica con permessi 600 fin dalla creazione. Il nome temporaneo e' casuale (mai legato al CV)."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".cv-{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        _wipe(p)  # il file che si sta per sostituire: i suoi blocchi non devono restare con il vecchio CV
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _wipe(p: Path) -> None:
    """Sovrascrive con zeri il contenuto di un file esistente (se c'e'); mai un errore."""
    try:
        size = p.stat().st_size
        with open(p, "r+b") as f:
            f.write(b"\x00" * size)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass


def save_text(text: str, source: str) -> dict:
    """Salva (o sostituisce) il CV. Le competenze aggiunte o tolte a mano riguardavano il CV precedente: si azzerano."""
    doc = {"format": CV_FORMAT, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source,
           "words": count_words(text), "text": text, "skills_manual": [], "skills_removed": []}
    _write(doc)
    return doc


def delete() -> bool:
    """Cancella davvero il CV: il contenuto del file viene prima sovrascritto, poi il file e' rimosso."""
    p = path()
    existed = p.exists()
    _wipe(p)
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    for tmp in p.parent.glob(".cv-*.tmp"):
        try:
            tmp.unlink()
        except OSError:
            pass
    return existed


# ------------------------------------------------------------- anni e lingue ----
_MONTHS = {"gen": 1, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "may": 5, "giu": 6, "jun": 6, "lug": 7, "jul": 7,
           "ago": 8, "aug": 8, "set": 9, "sep": 9, "ott": 10, "oct": 10, "nov": 11, "dic": 12, "dec": 12}
_MON = r"(?:(\d{1,2})\s*[/.\-]\s*|(gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic|jan|may|jun|jul|aug|sep|oct|dec)[a-z]*\.?\s+)?"
_SEP = r"\s*(?:-|–|—|\bto\b|\ba\b|\bal\b|\bfino a\b|\bfino al\b|/)\s*"
_NOW = r"(presente|oggi|attuale|attualmente|present|current|now|in corso|ad oggi|tuttora|tutt oggi|to date)"
_RANGE = re.compile(rf"(?<![\d/])" + _MON + r"((?:19|20)\d{2})" + _SEP + rf"(?:" + _MON + r"((?:19|20)\d{2})|" + _NOW + r")(?!\d)", re.I)
_EDU_HEAD = re.compile(r"^(?:istruzione|formazione|educazione|education|studi|titoli di studio|corsi|certificazioni|certifications|formazione e istruzione|istruzione e formazione|corsi e certificazioni|academic)\b")
_EXP_HEAD = re.compile(r"^(?:esperienz[ae]|work experience|professional experience|experience|employment|work history|carriera|career|lavoro|progetti|projects)\b")
_OTHER_HEAD = re.compile(r"^(?:competenze|skills|lingue|languages|contatti|contact|profilo|profile|sommario|summary|interessi|interests|hobby|dati personali|personal|riferimenti|references|certificazioni)\b")
_EDU_LINE = re.compile(r"\b(?:laurea|laureato|laureata|diploma|degree|bachelor|master (?:in|di|degree|universitario|of)|liceo|tesi|thesis|dottorato|phd|maturita|itis|its academy|corso di studi|"
                       r"universita|university|istituto|scuola|school|college)\b")
_EDU_STRONG = re.compile(r"\b(?:laurea|laureato|laureata|diploma|degree|bachelor|master (?:in|di|degree|universitario|of)|liceo|tesi|thesis|dottorato|phd|maturita|corso di studi)\b")
_DASHES = re.compile("[\u2010-\u2015\u2212\ufe58\ufe63\uff0d]")
_EXPLICIT = [
    re.compile(r"(\d{1,2})\s*\+?\s*(?:anni|anno|years|year|yrs)\s+(?:di\s+|of\s+)?(?:comprovata\s+|solida\s+|significativa\s+|professional\s+|working\s+|work\s+)?(?:esperienza|experience)"),
    re.compile(r"(?:esperienza|experience)\s+(?:di|of|pari a|ventennale|decennale)?\s*(?:oltre|piu di|circa|over|more than)?\s*(\d{1,2})\s*\+?\s*(?:anni|years)"),
]


def _to_year(y: str, m_num: str | None, m_name: str | None, default_month: int) -> float:
    month = default_month
    if m_num and 1 <= int(m_num) <= 12:
        month = int(m_num)
    elif m_name and m_name[:3].lower() in _MONTHS:
        month = _MONTHS[m_name[:3].lower()]
    return int(y) + (month - 1) / 12


def _today_year() -> float:
    t = date.today()
    return t.year + (t.month - 1) / 12


_WORK_CUE = re.compile(r"\b(?:presso|at|srl|spa|s\.r\.l|s\.p\.a|ltd|inc|gmbh|llc|snc|azienda|company|cooperativa|societa)\b|@")


def estimate_years(text: str) -> float | None:
    return estimate_years_ex(text)[0]


def estimate_years_ex(text: str) -> tuple[float | None, bool]:
    """(anni di esperienza lavorativa al mezzo anno o None, sicuro?).

    Conta solo gli intervalli di date che sembrano lavoro: nella sezione "Esperienza", oppure con indizi (presso, srl, spa, ltd...) o con il
    mese a entrambi i capi ("FEB. 2023 - MARZ. 2026"). Gli intervalli di studio (laurea, istituto, universita', corsi, certificazioni) non contano.
    Nei PDF a due colonne i titoli di sezione finiscono mescolati: se un intervallo non si capisce si scarta (si sottostima) e il risultato e'
    marcato "non sicuro", cosi' non viene usato per penalizzare il livello. Le frasi "N anni di esperienza" valgono come minimo."""
    text = _DASHES.sub("-", text or "")  # Word scrive "2019 \u2013 2021": il fold toglierebbe il trattino
    low = skills.fold(text)
    explicit = []
    for rx in _EXPLICIT:
        explicit += [int(m.group(1)) for m in rx.finditer(low) if 0 < int(m.group(1)) <= 50]
    section = ""
    spans: list[tuple[float, float]] = []
    dropped = False
    now = _today_year()
    for line in text.splitlines():
        flat = skills.fold(line).strip()
        if not flat:
            continue
        if len(flat) <= 45:
            head = flat.strip(":- |")
            if _EDU_HEAD.match(head):
                section = "edu"
            elif _EXP_HEAD.match(head):
                section = "exp"
            elif _OTHER_HEAD.match(head):
                section = "other"
        found = list(_RANGE.finditer(flat))
        if not found:
            continue
        if _EDU_STRONG.search(flat):
            continue
        work_cue = bool(_WORK_CUE.search(flat))
        if not work_cue and _EDU_LINE.search(flat):
            continue
        for m in found:
            m1n, m1s, y1, m2n, m2s, y2, nowtok = m.groups()
            both_months = bool(m1n or m1s) and bool(m2n or m2s or nowtok)
            if not (work_cue or both_months or section == "exp"):
                if section == "":
                    dropped = True  # intervallo senza indizi e senza sezione: non si sa se e' lavoro
                continue
            start = _to_year(y1, m1n, m1s, 1)
            end = now if nowtok else _to_year(y2, m2n, m2s, 1)
            if end < start or end - start > 45 or start > now + 0.5:
                continue
            spans.append((start, min(end, now)))
    union = 0.0
    last_end = None
    for s_, e_ in sorted(spans):
        if last_end is None or s_ > last_end:
            union += e_ - s_
            last_end = e_
        elif e_ > last_end:
            union += e_ - last_end
            last_end = e_
    if not spans and not explicit:
        return None, not dropped
    best = max([union] + explicit)
    return round(min(best, 50) * 2) / 2, not dropped


_LEVEL_WORDS = [
    (re.compile(r"\b(?:madrelingua|mother tongue|native|bilingue|bilingual)\b"), "madrelingua"),
    (re.compile(r"\b(a1|a2|b1|b2|c1|c2)\b"), None),
    (re.compile(r"\b(?:fluente|fluent|ottimo|ottima|avanzato|avanzata|advanced|professional|professionale|proficient|eccellente|excellent)\b"), "avanzato"),
    (re.compile(r"\b(?:buono|buona|good|intermedio|intermedia|intermediate|upper intermediate|discreto|discreta|medio)\b"), "intermedio"),
    (re.compile(r"\b(?:scolastico|scolastica|base|basic|elementary|elementare|beginner|principiante|sufficiente|basilare)\b"), "base"),
]


def _level_in(words: list[str]) -> str | None:
    window = " ".join(words)
    best = None  # vince il livello scritto piu' vicino alla lingua
    for rx, label in _LEVEL_WORDS:
        m = rx.search(window)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), m.group(1).upper() if label is None else label)
    return best[1] if best else None


def detect_languages(text: str) -> list[dict]:
    """Lingue citate nel CV con il livello se indicato vicino: [{lang, level}]. L'italiano solo se ha un livello (e' gia' la lingua del CV)."""
    toks = skills.tokenize(text or "")
    words = [t for t, _ in toks]
    every = {w for names in skills.LANG_WORDS.values() for w in names}
    found: dict[str, str | None] = {}
    for lang, names in skills.LANG_WORDS.items():
        for i, w in enumerate(words):
            if w not in names:
                continue
            after = []
            for x in words[i + 1: i + 6]:
                if x in every:
                    break  # il livello dopo un'altra lingua riguarda quella
                after.append(x)
            level = _level_in(after)
            if level is None:  # "madrelingua italiano", "ottimo inglese": livello subito prima
                before = []
                for x in reversed(words[max(0, i - 2): i]):
                    if x in every:
                        break
                    before.insert(0, x)
                level = _level_in(before)
            if lang == "Italiano" and level is None:
                continue
            if lang not in found or (found[lang] is None and level):
                found[lang] = level
    return [{"lang": k, "level": v} for k, v in sorted(found.items(), key=lambda kv: (kv[0] != "Italiano", kv[0]))]


# --------------------------------------------------------------- profilo ----
@dataclass
class CvProfile:
    detected: dict[str, int] = field(default_factory=dict)   # competenze trovate nel testo
    manual: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    years: float | None = None
    years_certain: bool = True
    languages: list[dict] = field(default_factory=list)
    words: int = 0
    updated: str = ""
    source: str = ""

    @property
    def skills(self) -> set[str]:
        """Competenze valide per il confronto (senza le lingue, che hanno un trattamento a parte)."""
        s = (set(self.detected) | set(self.manual)) - set(self.removed)
        return {x for x in s if not skills.is_language(x)}

    @property
    def lang_names(self) -> set[str]:
        return {d["lang"] for d in self.languages}

    @property
    def version(self) -> str:
        """Impronta del CV *elaborato*: cambia solo se cambia cio' che conta per il confronto. Non contiene il testo."""
        raw = json.dumps([CVMATCH_VERSION, skills.vocab_signature(), sorted(self.skills), self.years, self.years_certain,
                          sorted(self.lang_names)], sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()[:16]


def build_profile(doc: dict) -> CvProfile:
    text = doc.get("text", "")
    found = {k: v for k, v in skills.find_skills(text).items() if not skills.is_language(k)}
    years, certain = estimate_years_ex(text)
    return CvProfile(detected=found, manual=list(doc.get("skills_manual", [])), removed=list(doc.get("skills_removed", [])),
                     years=years, years_certain=certain, languages=detect_languages(text), words=int(doc.get("words") or count_words(text)),
                     updated=doc.get("updated", ""), source=doc.get("source", ""))


_cache: dict = {"key": None, "prof": None}


def current() -> CvProfile | None:
    """Il profilo del CV salvato, oppure None. Si riusa finche' il file e il vocabolario non cambiano."""
    p = path()
    try:
        st = p.stat()
    except OSError:
        _cache.update(key=None, prof=None)
        return None
    key = (str(p), st.st_mtime_ns, st.st_size, skills.vocab_signature())
    if _cache["key"] == key and _cache["prof"] is not None:
        return _cache["prof"]
    doc = load()
    prof = build_profile(doc) if doc else None
    _cache.update(key=key, prof=prof)
    return prof


def summary(prof: CvProfile | None) -> dict:
    """Cio' che l'API puo' dire del CV: nessun testo, solo dati derivati."""
    if prof is None:
        return {"present": False}
    return {
        "present": True, "updated": prof.updated, "words": prof.words, "source": prof.source,
        "skills": sorted(prof.skills, key=lambda n: (skills.category_of(n), n.lower())),
        "skills_detected": sorted(n for n in prof.detected),
        "skills_manual": sorted(prof.manual), "skills_removed": sorted(prof.removed),
        "categories": {n: skills.category_of(n) for n in prof.skills},
        "years": prof.years if prof.years_certain else None, "languages": prof.languages, "version": prof.version,
    }


# -------------------------------------------------- competenze: aggiungi/togli ----
def clean_skill_name(raw) -> str:
    if not isinstance(raw, str):
        raise CvError("Nome della competenza non valido.")
    name = re.sub(r"[\x00-\x1f\x7f]", " ", raw).strip()
    name = re.sub(r"\s+", " ", name)
    if not name or len(name) > 60:
        raise CvError("Scrivi il nome di una competenza (al massimo 60 caratteri).")
    return name


def change_skills(add=(), remove=(), restore=()) -> dict:
    """Aggiunge competenze a mano, toglie quelle sbagliate, ripristina quelle tolte. Ritorna il documento aggiornato."""
    doc = load()
    if doc is None:
        raise CvError("Non hai ancora caricato un CV.")
    detected = set(skills.find_skills(doc["text"]))
    manual, removed = list(doc["skills_manual"]), list(doc["skills_removed"])
    for raw in add:
        name = clean_skill_name(raw)
        canon = skills.resolve_name(name)
        if canon is None:
            raise CvError("Questa competenza non e' nel vocabolario. Puoi insegnarmela scrivendola nel file skills_extra.json della cartella dei dati.")
        if skills.is_language(canon):
            raise CvError("Le lingue si riconoscono dal testo del CV: scrivi per esempio \"Inglese B2\" nel testo.")
        if canon in removed:
            removed.remove(canon)
        if canon not in detected and canon not in manual:
            if len(manual) >= MAX_MANUAL:
                raise CvError("Troppe competenze aggiunte a mano.")
            manual.append(canon)
    for raw in remove:
        name = clean_skill_name(raw)
        canon = skills.resolve_name(name) or name
        if canon in manual:
            manual.remove(canon)
        elif canon in detected and canon not in removed:
            removed.append(canon)
    for raw in restore:
        name = clean_skill_name(raw)
        canon = skills.resolve_name(name) or name
        if canon in removed:
            removed.remove(canon)
    doc["skills_manual"], doc["skills_removed"] = manual, removed
    _write(doc)
    return doc
