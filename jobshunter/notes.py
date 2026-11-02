"""Blocco note e lettere di presentazione: modello, segnaposto, formato Markdown e nomi di file sicuri (fase 10).

Le note sono DATI PERSONALI (come il CV e le candidature): stanno solo nel database locale e nei file che l'utente esporta.
Tutto il testo mostrato all'utente (messaggi d'errore compresi) sta in costanti qui sotto, cosi' si traduce dopo senza caccia al testo.
Nessuna dipendenza esterna.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path

KINDS = ("note", "letter")
MAX_TITLE = 200
MAX_BODY = 100_000
MAX_TEMPLATE = 20_000
TEMPLATE_KEY = "notes.letter_template"  # chiave in settings.json (le impostazioni, non il browser)
EXPORT_SUBDIR = "Note"  # dentro la cartella dei report: un file .md per nota
MAX_FILENAME = 80
MAX_FILENAME_BYTES = 200  # in byte UTF-8 (resta posto per il suffisso -N e per .md dentro i 255 di ext4)

# ---- messaggi (costanti di modulo: in futuro si traducono da qui) ----
MSG_KIND = "tipo di nota non valido (valori ammessi: note, letter)"
MSG_TITLE_TOO_LONG = f"titolo troppo lungo (massimo {MAX_TITLE:,} caratteri)".replace(",", ".")
MSG_BODY_TOO_LONG = f"testo troppo lungo (massimo {MAX_BODY:,} caratteri): accorcialo o dividilo in due note".replace(",", ".")
MSG_TEMPLATE_TOO_LONG = f"modello troppo lungo (massimo {MAX_TEMPLATE:,} caratteri)".replace(",", ".")
MSG_NOT_TEXT = "titolo e testo devono essere testo"
MSG_NOTE_NOT_FOUND = "nota non trovata"
MSG_JOB_NOT_FOUND = "annuncio non trovato"
MSG_APP_NOT_FOUND = "candidatura non trovata"
MSG_BAD_ID = "identificativo non valido"
MSG_NO_NOTES = "nessuna nota da esportare"
MSG_NEED_JSON = "serve un oggetto JSON"
MSG_EXPORT_FAILED = "non sono riuscito a scrivere il file: controlla la cartella dei report"
MSG_BAD_TEXT = "il testo contiene caratteri non validi (non è Unicode corretto): copialo di nuovo oppure togli i caratteri strani"
MSG_LINK_MISMATCH = "l'annuncio e la candidatura indicati non sono collegati tra loro: scegline uno solo"
MSG_NOTE_FOLDER_OUTSIDE = "la sottocartella Note non sta dentro la cartella dei report (è un collegamento verso un'altra cartella): toglila o scegli un'altra cartella dei report"

DEFAULT_TEMPLATE = """{data}

Spett.le {azienda}

Oggetto: candidatura per la posizione di {ruolo}

Buongiorno,

scrivo per candidarmi alla posizione di {ruolo} presso {azienda} ({sede}), che ho trovato qui: {link}

[Racconta in due o tre frasi perché questo ruolo fa per te e cosa porti.]

[Aggiungi un esempio concreto di quello che hai fatto e che c'entra con l'annuncio.]

Resto a disposizione per un colloquio e ringrazio per l'attenzione.

Cordiali saluti,
[Il tuo nome]
"""

# segnaposto accettati (italiani e inglesi) e il dato a cui corrispondono
PLACEHOLDERS = {
    "azienda": "company", "company": "company",
    "ruolo": "role", "role": "role",
    "sede": "location", "location": "location",
    "data": "date", "date": "date",
    "link": "url", "url": "url",
}
_PLACEHOLDER = re.compile(r"\{(" + "|".join(sorted(PLACEHOLDERS, key=len, reverse=True)) + r")\}")


class NoteError(ValueError):
    """Dato non valido: il messaggio e' in italiano e si mostra cosi' com'e'."""


_SURROGATES = re.compile("[\ud800-\udfff]")


def _no_surrogates(text: str) -> str:
    """Un JSON valido puo' contenere un surrogato spaiato (`\\ud800`): non si scrive in UTF-8, quindi si rifiuta con un messaggio chiaro."""
    if _SURROGATES.search(text):
        raise NoteError(MSG_BAD_TEXT)
    return text


def today_it(today: date | None = None) -> str:
    return (today or date.today()).strftime("%d/%m/%Y")


def render_template(template: str, data: dict, today: date | None = None) -> str:
    """Riempie i segnaposto con una sostituzione SEMPLICE in un solo passaggio (niente str.format, niente % e niente interpretazione del testo
    dell'utente: i valori con `{}`, `%` o emoji restano com'e'). Un segnaposto sconosciuto o senza dato resta visibile, mai un errore."""
    values = {"company": data.get("company"), "role": data.get("role"), "location": data.get("location"), "url": data.get("url"), "date": today_it(today)}

    def one(m: re.Match) -> str:
        v = values.get(PLACEHOLDERS[m.group(1)])
        return m.group(0) if v is None or str(v).strip() == "" else str(v)

    return _PLACEHOLDER.sub(one, template)


LETTER_PREFIX = "Lettera per "
MAX_LETTER_TITLE = 70  # caratteri totali del titolo generato (un ruolo lungo non deve fare un titolo lunghissimo)
ELLIPSIS = "\u2026"


def shorten(text: str, limit: int) -> str:
    """Accorcia `text` a `limit` caratteri (compreso il segno di continuazione) sull'ULTIMA PAROLA INTERA e aggiunge "…".
    Se la prima parola da sola e' piu' lunga del limite taglia comunque, duro. Senza punteggiatura o spazi finali prima del segno."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 1:
        return ELLIPSIS[:limit]
    cut = text[: limit - 1]
    if text[limit - 1] != " " and " " in cut:  # il taglio cadrebbe dentro una parola: si torna all'ultimo spazio
        cut = cut.rsplit(" ", 1)[0]
    cut = cut.rstrip(" ,.;:-&/_")
    return (cut or text[: limit - 1]) + ELLIPSIS


def letter_title(company: str, role: str, max_len: int = MAX_LETTER_TITLE) -> str:
    """`Lettera per <azienda>, <ruolo>` in al massimo `max_len` caratteri: se supera, il ruolo si accorcia sull'ultima parola intera con "…";
    se l'azienda da sola e' troppo lunga si accorcia l'azienda (e il ruolo non c'e' piu' posto per mostrarlo). Se manca un dato si usa quello che c'e'."""
    c, r = re.sub(r"\s+", " ", company or "").strip(), re.sub(r"\s+", " ", role or "").strip()
    room = max_len - len(LETTER_PREFIX)
    if not c and not r:
        return "Lettera di presentazione"
    if not r or not c:
        return LETTER_PREFIX + shorten(c or r, room)
    if len(c) + 2 + len(r) <= room:
        return f"{LETTER_PREFIX}{c}, {r}"
    role_room = room - len(c) - 2
    if role_room >= 6:  # un ruolo con meno di qualche carattere non dice niente: meglio solo l'azienda
        return f"{LETTER_PREFIX}{c}, {shorten(r, role_room)}"
    return LETTER_PREFIX + shorten(c, room)


def clean_title(title) -> str:
    if not isinstance(title, str):
        raise NoteError(MSG_NOT_TEXT)
    t = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]+", " ", _no_surrogates(title))).strip()  # un titolo sta su una riga
    if len(t) > MAX_TITLE:
        raise NoteError(MSG_TITLE_TOO_LONG)
    return t


def clean_body(body) -> str:
    if not isinstance(body, str):
        raise NoteError(MSG_NOT_TEXT)
    b = _no_surrogates(body).replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    if len(b) > MAX_BODY:
        raise NoteError(MSG_BODY_TOO_LONG)  # mai troncare in silenzio
    return b


def clean_template(template) -> str:
    if not isinstance(template, str):
        raise NoteError(MSG_NOT_TEXT)
    t = _no_surrogates(template).replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    if len(t) > MAX_TEMPLATE:
        raise NoteError(MSG_TEMPLATE_TOO_LONG)
    return t


def get_template(cfg: dict) -> str:
    """Il modello dell'utente se c'e' (e non e' vuoto), altrimenti quello predefinito."""
    t = (cfg.get("notes") or {}).get("letter_template") if isinstance(cfg.get("notes"), dict) else None
    return t if isinstance(t, str) and t.strip() else DEFAULT_TEMPLATE


# ---------------------------------------------------------------- file Markdown ----
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_filename(title: str, fallback: str = "nota") -> str:
    """Nome di file (senza estensione) ricavato dal titolo: niente `/`, `\\`, `..`, caratteri di controllo o vietati da Windows,
    niente nomi riservati di Windows (CON, NUL, COM1...), niente punti o spazi finali, lunghezza limitata. Mai vuoto."""
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(title or ""))
    s = re.sub(r'[\\/:*?"<>|]', "-", s)
    s = re.sub(r"\.{2,}", ".", s)  # mai due punti di fila, anche con tre o piu'
    s = re.sub(r"\s+", " ", s).strip(" .-_")
    if len(s) > MAX_FILENAME or len(s.encode("utf-8", "ignore")) > MAX_FILENAME_BYTES:
        n = min(len(s), MAX_FILENAME)
        while len(s[:n].encode("utf-8", "ignore")) > MAX_FILENAME_BYTES:  # su ext4 un nome puo' avere 255 byte: si taglia su un confine di carattere
            n -= 1
        cut = s[:n]
        if s[n:n + 1] != " " and " " in cut:  # niente parole a meta': si torna all'ultima parola intera
            cut = cut.rsplit(" ", 1)[0]
        s = cut  # se la prima parola da sola e' troppo lunga resta il taglio duro
    s = s.rstrip(" .-_&,;:")  # niente spazi, punti, trattini o segni appesi in fondo
    if s.split(".")[0].upper() in _WIN_RESERVED:
        s = "_" + s
    return s or fallback


def unique_path(folder: Path, stem: str, suffix: str = ".md") -> Path:
    """Percorso libero dentro `folder`: se `stem.md` esiste (di chiunque) si aggiunge -2, -3... Non sovrascrive mai."""
    p = folder / f"{stem}{suffix}"
    n = 2
    while p.exists():
        p = folder / f"{stem}-{n}{suffix}"
        n += 1
    return p


def one_line(value) -> str:
    """Un valore per il blocco iniziale: su una riga, senza a capo e senza `---`."""
    s = re.sub(r"[\x00-\x1f\x7f  ]+", " ", str(value or ""))
    s = re.sub(r"-{3,}", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def _day(iso: str | None) -> str:
    return (iso or "")[:10]


def _it_day(iso: str | None) -> str:
    d = _day(iso)
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return d


def to_markdown(note: dict, *, url: str = "", applied_at: str | None = None) -> str:
    """Il file di una nota: blocco iniziale (titolo, tipo, azienda, ruolo, annuncio, candidatura, date) e poi il testo cosi' com'e'."""
    lines = ["---", f"titolo: {one_line(note.get('title')) or 'senza titolo'}", f"tipo: {'lettera' if note.get('kind') == 'letter' else 'nota'}"]
    if one_line(note.get("company")):
        lines.append(f"azienda: {one_line(note['company'])}")
    if one_line(note.get("role")):
        lines.append(f"ruolo: {one_line(note['role'])}")
    if one_line(url):
        lines.append(f"annuncio: {one_line(url)}")
    if note.get("app_id"):
        lines.append("candidatura: " + (f"inviata il {_it_day(applied_at)}" if applied_at else "collegata"))
    lines += [f"creata: {_day(note.get('created'))}", f"aggiornata: {_day(note.get('updated'))}", "---", "", ""]
    body = note.get("body") or ""
    return "\n".join(lines) + body  # il testo e' esattamente quello della nota: nessun a capo aggiunto


def _taken(folder: Path) -> set[str]:
    """Nomi gia' presenti nella cartella, senza distinguere le maiuscole: il vault dei report puo' finire su macOS o Windows."""
    try:
        return {n.lower() for n in os.listdir(folder)}
    except OSError:
        return set()


def write_unique(folder: Path, stem: str, text: str) -> Path:
    """Scrive `text` in `folder/stem.md` (UTF-8, a capo `\n`) senza MAI sovrascrivere: se il nome c'e' gia' (anche solo per le maiuscole) prova -2, -3... (creazione esclusiva)."""
    folder.mkdir(parents=True, exist_ok=True)
    taken = _taken(folder)
    n = 1
    while True:
        name = f"{stem}.md" if n == 1 else f"{stem}-{n}.md"
        if name.lower() in taken:
            n += 1
            continue
        p = folder / name
        try:
            with open(p, "x", encoding="utf-8", newline="\n") as f:
                f.write(text)
            return p
        except FileExistsError:
            taken = _taken(folder)
            n += 1


# ---------------------------------------------- legami con annunci e candidature, esportazione ----
def source_data(db, job_uid: str | None, app_id: int | None) -> dict:
    """Azienda, ruolo, sede e indirizzo dell'annuncio o della candidatura (la candidatura vale piu' dell'annuncio), per riempire il modello."""
    data: dict = {}
    if job_uid:
        j = db.conn.execute("SELECT title, company, location, url FROM jobs WHERE uid=?", (job_uid,)).fetchone()
        if j:
            data = {"company": j["company"], "role": j["title"], "location": j["location"], "url": j["url"]}
    if app_id is not None:
        a = db.conn.execute("SELECT company, role, location, url FROM applications WHERE id=?", (app_id,)).fetchone()
        if a:
            data = {k: (a[k] or data.get(k)) for k in ("company", "role", "location", "url")}
    return data


def make_letter(cfg: dict, db, job_uid: str | None = None, app_id: int | None = None, title: str = "") -> int:
    """Crea una lettera dal modello (quello dell'utente o il predefinito) con i dati dell'annuncio o della candidatura. Ritorna l'id."""
    src = source_data(db, job_uid, app_id)
    if not isinstance(title, str) or not title.strip():
        title = letter_title(src.get("company"), src.get("role"))
    return db.add_note(kind="letter", title=title, body=render_template(get_template(cfg), src), job_uid=job_uid, app_id=app_id,
                       company=src.get("company") or "", role=src.get("role") or "")


def export_folder(cfg: dict) -> Path:
    """Sottocartella `Note` della cartella dei report, con gli stessi controlli (zone protette rifiutate): ValueError in italiano."""
    from . import settings

    base = settings.resolve_path(cfg.get("report", {}).get("dir", "reports"))
    settings.check_report_dir(str(base))
    folder = base / EXPORT_SUBDIR
    if folder.is_symlink() or folder.exists():
        real, real_base = folder.resolve(), base.resolve()
        if real != real_base / EXPORT_SUBDIR and real_base not in real.parents:
            raise ValueError(MSG_NOTE_FOLDER_OUTSIDE[0].upper() + MSG_NOTE_FOLDER_OUTSIDE[1:])  # un collegamento verso fuori: mai scrivere li' dentro
        settings.check_report_dir(str(real))  # e comunque non in una zona protetta
    return folder


def export_note(db, r, folder: Path) -> Path:
    """Scrive il file Markdown di una nota (riga di `notes`) in `folder` e ritorna il percorso."""
    url, applied = "", None
    if r["job_uid"]:
        j = db.conn.execute("SELECT url FROM jobs WHERE uid=?", (r["job_uid"],)).fetchone()
        url = (j["url"] if j else "") or ""
    if r["app_id"] is not None:
        a = db.conn.execute("SELECT url, applied_at FROM applications WHERE id=?", (r["app_id"],)).fetchone()
        if a:
            url, applied = url or a["url"] or "", a["applied_at"]
    stem = safe_filename(r["title"], "lettera" if r["kind"] == "letter" else "nota")
    return write_unique(folder, stem, to_markdown(dict(r), url=url, applied_at=applied))
