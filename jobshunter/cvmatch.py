"""Affinita' tra il CV e un annuncio: punteggio 0-100 SPIEGATO, deterministico, senza modelli e senza rete.

Come si calcola (ogni passo finisce nella spiegazione che l'utente legge):
1. Dall'annuncio si ricavano le competenze richieste (vocabolario di `skills.py`). Pesano di piu' quelle nel titolo (x3) e quelle
   ripetute nel testo (fino a +1,5). Le competenze generali e trasversali (Excel, lavoro di squadra...) pesano il 40%.
2. Copertura = peso delle competenze richieste che sono nel CV / peso di tutte le richieste. E' la base del punteggio (0-100).
3. Penalita' lieve per le competenze chiave mancanti (nel titolo o ripetute): fino a -12.
4. Livello: anni di esperienza del CV contro il livello dell'annuncio (stage/junior/medio/senior, o "N anni" scritti nel testo).
   Meno esperienza del richiesto: fino a -25. Molta piu' esperienza del richiesto per uno stage o un junior: -6/-8.
5. Lingua: lingua straniera richiesta e non presente nel CV: -10 (al massimo -15).
6. Prudenza: con poche competenze riconosciute il punteggio ha un tetto (1 competenza: 52, 2: 64, 3: 76, 4: 88); se il testo e' solo
   un'anteprima (annunci Jooble, testo sotto i 300 caratteri, snippet non ancora scaricati) il tetto e' 60 e il punteggio si riduce del 15%.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import skills
from .cv import CvProfile
from .meta import detect_contract

PREVIEW_MIN_CHARS = 300
PREVIEW_CAP = 60
CAP_BY_COUNT = {0: 30, 1: 52, 2: 64, 3: 76, 4: 88}
GENERIC_FACTOR = 0.4
LEVEL_YEARS = {"stage": 0, "junior": 0, "medio": 3, "senior": 5, "lead": 7}
LEVEL_LABEL = {"stage": "stage o tirocinio", "junior": "junior", "medio": "intermedio", "senior": "senior", "lead": "ruolo di responsabilita'"}

_JUNIOR = re.compile(r"\b(?:junior|jr|entry[- ]level|neolaureat\w*|neodiplomat\w*|graduate|trainee|primo impiego|apprendist\w*)\b")
_MID = re.compile(r"\b(?:mid|middle|mid[- ]level|intermedio|semi[- ]?senior|ssr)\b")
_SENIOR = re.compile(r"\b(?:senior|sr|esperto|expert|specialist senior)\b")
_LEAD = re.compile(r"\b(?:lead|principal|manager|head|director|architect|staff|responsabile|capo|direttore|coordinatore|supervisor|team leader)\b")
_YEARS = [
    re.compile(r"(\d{1,2})\s*(?:-|a|to)\s*\d{1,2}\s*\+?\s*(?:anni|years|yrs)\s+(?:di\s+|of\s+)?(?:comprovata\s+|solida\s+|pregressa\s+)?(?:esperienza|experience)"),
    re.compile(r"(\d{1,2})\s*\+?\s*(?:anni|anno|years|year|yrs)\s+(?:di\s+|of\s+)?(?:comprovata\s+|solida\s+|pregressa\s+|significativa\s+|hands on\s+|professional\s+|working\s+)?(?:esperienza|experience)"),
    re.compile(r"(?:esperienza|experience)\s+(?:di\s+|of\s+|pari a\s+|minima di\s+)?(?:almeno|minimo|oltre|piu di|at least|minimum|over|more than)?\s*(\d{1,2})\s*\+?\s*(?:anni|anno|years)"),
    re.compile(r"(?:almeno|minimo|min|at least|minimum)\s*(\d{1,2})\s*(?:anni|years|yrs)"),
]
_LANG_CTX = {"richiesto", "richiesta", "richiesti", "required", "fluent", "fluente", "conoscenza", "conoscenze", "knowledge", "ottima", "ottimo",
             "buona", "buono", "madrelingua", "native", "livello", "level", "proficiency", "parlato", "scritto", "spoken", "written", "avanzato",
             "advanced", "intermedio", "essential", "indispensabile", "must", "necessaria", "necessario", "lingua", "language", "languages",
             "lingue", "a2", "b1", "b2", "c1", "c2", "fluency", "comunicare", "communicate", "speak", "parlare", "business", "professional"}
_LANG_OPT = {"gradita", "gradito", "preferibile", "preferred", "plus", "nice", "valutabile", "apprezzata", "apprezzato", "preferenziale", "titolo preferenziale"}


@dataclass
class JobSkills:
    weights: dict[str, float]     # competenze (non lingue) con il loro peso
    in_title: set[str]
    languages: dict[str, bool]    # lingua straniera richiesta -> True se richiesta, False se solo gradita
    level: str | None
    years: int | None             # anni richiesti scritti nel testo


def analyze_job(title: str, text: str) -> JobSkills:
    t_found = skills.find_skills(title)
    b_found = skills.find_skills(text)
    weights: dict[str, float] = {}
    for name in set(t_found) | set(b_found):
        if skills.is_language(name):
            continue
        w = 1.0
        if name in t_found:
            w += 2.0
        w += min(max(b_found.get(name, 0) - 1, 0), 3) * 0.5
        if skills.is_generic(name):
            w *= GENERIC_FACTOR
        weights[name] = w
    in_title = {n for n in t_found if not skills.is_language(n)}
    langs = _job_languages(f"{title}\n{text}")
    level, years = detect_level(title, text)
    return JobSkills(weights, in_title, langs, level, years)


def _job_languages(text: str) -> dict[str, bool]:
    toks = skills.tokenize(text)
    words = [t for t, _ in toks]
    out: dict[str, bool] = {}
    for lang, names in skills.LANG_WORDS.items():
        if lang == "Italiano":
            continue
        for i, w in enumerate(words):
            if w not in names:
                continue
            window = set(words[max(0, i - 6): i + 7])
            if window & _LANG_OPT:
                out.setdefault(lang, False)
            elif window & _LANG_CTX:
                out[lang] = True
    return out


_COMPANY = re.compile(r"\b(?:azienda|societa|gruppo|siamo|vanta\w*|company|our|we|nostr[aeio]|fondat\w*|leader|storia|team di)\b")
_REQUEST = re.compile(r"\b(?:richiest\w*|requisit\w*|candidat\w*|necessari\w*|almeno|minim\w*|required|minimum|you|tu|cerchiamo|ricerchiamo)\b")


def _about_company(body: str, pos: int) -> bool:
    """La frase parla dell'azienda ("vanta 25 anni di esperienza") e non chiede niente al candidato?"""
    start = max(body.rfind(c, 0, pos) for c in ".;:!?\n")
    before = body[start + 1:pos]
    return bool(_COMPANY.search(before)) and not _REQUEST.search(before)


def detect_level(title: str, text: str) -> tuple[str | None, int | None]:
    """(livello, anni richiesti scritti nel testo). Livello: stage | junior | medio | senior | lead | None."""
    head, body = skills.fold(title), skills.fold(text)
    years = None
    found = []
    for rx in _YEARS:
        for m in rx.finditer(body):
            if 0 < int(m.group(1)) <= 30 and not _about_company(body, m.start()):
                found.append(int(m.group(1)))
    if found:
        years = min(found)
    level = None
    if detect_contract(title, "") == "internship" or detect_contract(title, text[:600]) == "internship":
        level = "stage"
    elif _LEAD.search(head):
        level = "lead"
    elif _SENIOR.search(head):
        level = "senior"
    elif _MID.search(head):
        level = "medio"
    elif _JUNIOR.search(head):
        level = "junior"
    elif years is not None:
        level = "junior" if years <= 2 else "medio" if years <= 4 else "senior"
    return level, years


def is_preview(source: str, text: str, full_text: str) -> bool:
    """Testo troppo scarno per un confronto completo: Jooble, snippet di Adzuna non ancora scaricati, o meno di 300 caratteri."""
    src = (source or "").lower()
    if src.startswith("jooble"):
        return True
    if src.startswith("adzuna") and not (full_text or "").strip():
        return True
    return len((text or "").strip()) < PREVIEW_MIN_CHARS


def _clamp(x: float) -> int:
    return int(max(0, min(100, round(x))))


def match(prof: CvProfile, title: str, text: str, source: str = "", full_text: str = "") -> dict:
    """{score, base, explain} per un annuncio. `text` e' il testo piu' completo disponibile."""
    job = analyze_job(title, text)
    base = "anteprima" if is_preview(source, text, full_text) else "completo"
    cv_skills = prof.skills
    notes: list[str] = []

    total = sum(job.weights.values())
    common = sorted((n for n in job.weights if n in cv_skills), key=lambda n: (-job.weights[n], n.lower()))
    missing = sorted((n for n in job.weights if n not in cv_skills), key=lambda n: (-job.weights[n], n.lower()))
    covered = sum(job.weights[n] for n in common)
    coverage = covered / total if total else 0.0

    nongen = [n for n in job.weights if not skills.is_generic(n)]
    key_missing = [n for n in missing if not skills.is_generic(n) and (n in job.in_title or job.weights[n] >= 1.5)]
    penalty = min(12.0, 3.0 * len(key_missing))
    score = 100.0 * coverage - (penalty if total else 0)

    # livello
    cv_years = prof.years if prof.years_certain else None  # anni incerti: mai usati per penalizzare (ne' per premiare)
    lvl = {"richiesto": job.level, "etichetta": LEVEL_LABEL.get(job.level, ""), "anni_richiesti": None, "anni_cv": cv_years, "esito": "sconosciuto"}
    req = job.years if job.years is not None else LEVEL_YEARS.get(job.level)
    lvl["anni_richiesti"] = req
    adj_level = 0.0
    if req is not None and cv_years is not None:
        delta = cv_years - req
        if delta < 0:
            adj_level = -min(25.0, 7.0 * (-delta))
            lvl["esito"] = "sotto"
            notes.append(f"L'annuncio chiede circa {req} {'anno' if req == 1 else 'anni'} di esperienza, nel CV ne risultano circa {_fmt(cv_years)}.")
        elif (job.level == "stage" and delta >= 3) or (job.level == "junior" and delta >= 6):
            adj_level = -8.0 if job.level == "stage" else -6.0
            lvl["esito"] = "sopra"
            notes.append("Hai molta piu' esperienza di quella richiesta per questo livello.")
        else:
            lvl["esito"] = "in_linea"
    elif req is not None and cv_years is None:
        notes.append("Non sono sicuro degli anni di esperienza nel CV, quindi non confronto il livello (nessuna penalita')." if not prof.years_certain
                     else "Non riesco a stimare i tuoi anni di esperienza dal CV, quindi non confronto il livello.")
    if total:
        score += adj_level

    # lingue
    langs_req = [lang for lang, must in sorted(job.languages.items()) if must]
    langs_opt = [lang for lang, must in sorted(job.languages.items()) if not must]
    langs_missing = [l for l in langs_req if l not in prof.lang_names]
    lang_common = [l for l in langs_req if l in prof.lang_names]
    if total and langs_missing:
        score -= min(15.0, 10.0 * len(langs_missing))
        notes.append("Richiede " + ", ".join(l.lower() for l in langs_missing) + ": non lo trovo nel CV.")
    if langs_opt:
        notes.append("Gradita: " + ", ".join(l.lower() for l in langs_opt) + ".")

    # prudenza
    n = len(nongen)
    if not total:
        notes.append("Non riconosco competenze in questo annuncio: il punteggio e' solo indicativo.")
        score = 0.0
    if not cv_skills:
        notes.append("Nel CV non ho riconosciuto competenze: aggiungile a mano dalle Impostazioni.")
    cap = CAP_BY_COUNT.get(n, 100)
    if total and n < 5 and n > 0:
        notes.append("Nell'annuncio ci sono poche competenze riconoscibili: il punteggio e' prudente.")
    if base == "anteprima":
        score = score * 0.85
        cap = min(cap, PREVIEW_CAP)
        notes.insert(0, "Basato su anteprima: l'annuncio ha poco testo (o e' solo un riassunto), quindi il punteggio e' prudente.")
    final = _clamp(min(score, cap)) if total else 0
    confidence = "alta" if base == "completo" and n >= 4 else "media" if (base == "completo" and n >= 2) or (base == "anteprima" and n >= 3) else "bassa"

    explain = {
        "in_comune": common[:15], "mancanti": missing[:12], "livello": lvl, "base": base, "confidenza": confidence,
        "lingue": {"richieste": langs_req, "in_comune": lang_common, "mancanti": langs_missing, "gradite": langs_opt},
        "note": notes, "competenze_annuncio": len(job.weights), "titolo": sorted(job.in_title & set(job.weights)),
        "n_in_comune": len(common), "n_mancanti": len(missing),
    }
    return {"score": final, "base": base, "explain": explain}


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x).replace(".", ",")


# ---------------------------------------------------------------- database ----
SIG_SQL = "(length(coalesce(j.full_text,'')) || ':' || length(coalesce(j.description,'')))"


def _sig(row) -> str:
    return f"{len(row['full_text'] or '')}:{len(row['description'] or '')}"


def _text_of(row) -> str:
    return (row["full_text"] or row["description"] or "")


def stale_count(db, version: str) -> int:
    """Quanti annunci non hanno un confronto aggiornato (nuovi, testo cambiato o CV diverso)."""
    return db.conn.execute(
        "SELECT COUNT(*) FROM jobs j LEFT JOIN cv_match m ON m.uid=j.uid "
        f"WHERE m.uid IS NULL OR m.cv_version!=? OR m.sig!={SIG_SQL}", (version,)).fetchone()[0]


def _compute_row(prof: CvProfile, row) -> tuple:
    r = match(prof, row["title"] or "", _text_of(row), row["source"] or "", row["full_text"] or "")
    return (row["uid"], r["score"], r["base"], json.dumps(r["explain"], ensure_ascii=False), prof.version, _sig(row))


def recompute(db, prof: CvProfile, progress=None, cancel=None, batch: int = 400) -> int:
    """Ricalcola solo cio' che serve. `progress(fatti, totale)` e `cancel` (threading.Event) sono facoltativi. Ritorna quanti ne ha fatti."""
    version = prof.version
    rows = db.conn.execute(
        "SELECT j.uid, j.title, j.description, j.full_text, j.source FROM jobs j LEFT JOIN cv_match m ON m.uid=j.uid "
        f"WHERE m.uid IS NULL OR m.cv_version!=? OR m.sig!={SIG_SQL}", (version,)).fetchall()
    total = len(rows)
    done = 0
    pending = []
    for row in rows:
        if cancel is not None and cancel.is_set():
            break
        pending.append(_compute_row(prof, row))
        done += 1
        if len(pending) >= batch:
            _store(db, pending)
            pending = []
            if progress:
                progress(done, total)
    if pending:
        _store(db, pending)
    if progress:
        progress(done, total)
    return done


def _store(db, rows) -> None:
    db.conn.executemany("INSERT OR REPLACE INTO cv_match (uid, score, base, explain, cv_version, sig) VALUES (?,?,?,?,?,?)", rows)
    db.conn.commit()


def clear(db) -> None:
    db.conn.execute("DELETE FROM cv_match")
    db.conn.commit()


def for_job(db, prof: CvProfile, uid: str) -> dict | None:
    """Il confronto di UN annuncio, ricalcolato se manca o e' vecchio. {score, base, explain} oppure None se l'annuncio non esiste."""
    row = db.conn.execute("SELECT uid, title, description, full_text, source FROM jobs WHERE uid=?", (uid,)).fetchone()
    if row is None:
        return None
    m = db.conn.execute("SELECT * FROM cv_match WHERE uid=?", (uid,)).fetchone()
    if m is None or m["cv_version"] != prof.version or m["sig"] != _sig(row):
        _store(db, [_compute_row(prof, row)])
        m = db.conn.execute("SELECT * FROM cv_match WHERE uid=?", (uid,)).fetchone()
    return {"score": m["score"], "base": m["base"], "explain": json.loads(m["explain"])}


def scores_for(db, uids: list[str], version: str) -> dict[str, tuple[int, str]]:
    """{uid: (punteggio, base)} per gli annunci con un confronto aggiornato alla versione del CV."""
    out: dict[str, tuple[int, str]] = {}
    for i in range(0, len(uids), 500):
        chunk = uids[i:i + 500]
        q = f"SELECT uid, score, base FROM cv_match WHERE cv_version=? AND uid IN ({','.join('?' * len(chunk))})"
        for r in db.conn.execute(q, [version, *chunk]):
            out[r["uid"]] = (r["score"], r["base"])
    return out
