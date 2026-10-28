"""Dal file del CV al testo, tutto in locale: PDF (pypdf), DOCX (zipfile + XML della libreria standard), TXT e MD.

Regole di sicurezza:
- si guarda l'estensione E il contenuto (i primi byte): un .pdf che non e' un PDF, o un .txt che e' un archivio, si rifiuta;
- limiti: 5 MB, 40 pagine, e per i DOCX un tetto all'espansione (contro le "zip bomb");
- il nome scelto dal client serve solo per l'estensione, non viene mai usato come percorso;
- nessun messaggio d'errore contiene pezzi del documento (le eccezioni delle librerie si scartano).
"""
from __future__ import annotations

import io
import re
import zipfile

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 40
MAX_CHARS = 200_000          # tetto al testo tenuto
MIN_WORDS = 20               # sotto questa soglia il CV e' vuoto o una scansione
EXTENSIONS = (".pdf", ".docx", ".txt", ".md")

DOCX_MAX_MEMBER = 25 * 1024 * 1024   # un file dentro il DOCX non puo' espandersi oltre questo
DOCX_MAX_RATIO = 150                 # rapporto massimo decompresso / compresso
DOCX_MAX_ENTRIES = 3000


class CvError(Exception):
    """Errore da mostrare all'utente: il testo e' gia' in italiano e non contiene mai parti del CV."""


def _clean(text: str) -> str:
    text = text.encode("utf-8", "ignore").decode("utf-8")  # niente surrogati isolati (non si possono scrivere su disco)
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text)                      # spazi multipli
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)  # caratteri di controllo
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_CHARS]


def count_words(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def check_text(text: str, scanned_hint: bool = False) -> str:
    """Pulisce il testo e verifica che ci sia abbastanza materiale."""
    text = _clean(text)
    if count_words(text) < MIN_WORDS:
        if scanned_hint:
            raise CvError("Questo PDF non contiene testo selezionabile (sembra una scansione, cioe' un'immagine). "
                          "JobsHunter non legge le immagini: usa un PDF con testo, oppure incolla qui il testo del CV.")
        raise CvError(f"Il testo e' troppo corto: servono almeno {MIN_WORDS} parole per riconoscere le competenze.")
    return text


def extension_of(filename: str) -> str:
    name = (filename or "").strip().lower()
    for ext in EXTENSIONS:
        if name.endswith(ext):
            return ext
    return ""


def extract(data: bytes, filename: str) -> tuple[str, str]:
    """(testo, tipo) dove tipo e' pdf | docx | txt | md. Alza CvError con un messaggio italiano."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise CvError("Il file e' vuoto.")
    if len(data) > MAX_BYTES:
        raise CvError("Il file e' troppo grande: il limite e' 5 MB.")
    ext = extension_of(filename)
    if not ext:
        raise CvError("Formato non supportato: usa un file .pdf, .docx, .txt o .md (oppure incolla il testo).")
    head = bytes(data[:1024])
    is_pdf = b"%PDF-" in head
    is_zip = head.startswith(b"PK\x03\x04")
    if ext == ".pdf":
        if not is_pdf:
            raise CvError("Il file non e' un vero PDF (il contenuto non corrisponde all'estensione).")
        return _from_pdf(bytes(data)), "pdf"
    if ext == ".docx":
        if not is_zip:
            raise CvError("Il file non e' un vero DOCX (il contenuto non corrisponde all'estensione).")
        return _from_docx(bytes(data)), "docx"
    # testo semplice
    if is_pdf or is_zip or head.startswith(b"\xd0\xcf\x11\xe0") or head.startswith(b"MZ") or head.startswith(b"\x7fELF"):
        raise CvError("Il contenuto del file non e' testo semplice: l'estensione non corrisponde.")
    return _from_text(bytes(data)), ext[1:]


def _from_text(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):  # Blocco note / TextEdit "Unicode"
        try:
            return check_text(data.decode("utf-16"))
        except UnicodeError:
            raise CvError("Non riesco a leggere questo file di testo: salvalo come UTF-8 e riprova.") from None
    head = data[:4096]
    if b"\x00" in head and len(head) >= 8:  # UTF-16 senza BOM: i byte a zero stanno tutti su posizioni dispari (LE) o pari (BE)
        odd, even = head[1::2].count(0), head[0::2].count(0)
        half = len(head) // 2
        enc = "utf-16-le" if odd > half * 0.3 and even < half * 0.05 else "utf-16-be" if even > half * 0.3 and odd < half * 0.05 else None
        if enc:
            try:
                return check_text(data.decode(enc))
            except UnicodeError:
                pass
    if b"\x00" in head:
        raise CvError("Il file di testo usa una codifica che non so leggere (forse UTF-16 senza BOM o UTF-32): salvalo come UTF-8 e riprova.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
    weird = sum(1 for ch in text[:20000] if ord(ch) < 32 and ch not in "\n\r\t")
    if weird > 20:
        raise CvError("Il file non sembra un testo semplice.")
    return check_text(text)


# ------------------------------------------------------------------ PDF ----
def _from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise CvError("Manca il componente per leggere i PDF (pypdf). Incolla il testo del CV, oppure usa un file .docx o .txt.") from None
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            ok = 0
            try:
                ok = reader.decrypt("")
            except Exception:
                ok = 0
            if not ok:
                raise CvError("Il PDF e' protetto da password: salvane una copia senza protezione e riprova (oppure incolla il testo del CV).")
        n = len(reader.pages)
        if n > MAX_PAGES:
            raise CvError(f"Il PDF ha troppe pagine ({n}): il limite e' {MAX_PAGES}. Un CV di solito ne ha 1 o 2.")
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")  # una pagina illeggibile non blocca le altre
    except CvError:
        raise
    except RecursionError:
        raise CvError("Il PDF e' danneggiato o troppo complesso: non riesco a leggerlo.") from None
    except Exception:  # file corrotto: il messaggio della libreria potrebbe contenere pezzi del file, si scarta
        raise CvError("Il PDF e' danneggiato e non riesco a leggerlo. Prova a riesportarlo, oppure incolla il testo.") from None
    return check_text("\n".join(parts), scanned_hint=True)


# ----------------------------------------------------------------- DOCX ----
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.file_size > DOCX_MAX_MEMBER:
        raise CvError("Il documento e' troppo grande una volta aperto: non lo leggo per sicurezza.")
    if info.compress_size and info.file_size / max(info.compress_size, 1) > DOCX_MAX_RATIO:
        raise CvError("Il documento ha una compressione sospetta: non lo leggo per sicurezza.")
    with zf.open(info) as f:
        out = f.read(DOCX_MAX_MEMBER + 1)  # lettura a tetto: le dimensioni dichiarate possono mentire
    if len(out) > DOCX_MAX_MEMBER:
        raise CvError("Il documento e' troppo grande una volta aperto: non lo leggo per sicurezza.")
    return out


def _from_docx(data: bytes) -> str:
    import xml.etree.ElementTree as ET

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        raise CvError("Il DOCX e' danneggiato e non riesco ad aprirlo.") from None
    try:
        infos = zf.infolist()
        if len(infos) > DOCX_MAX_ENTRIES:
            raise CvError("Il documento contiene troppi file: non lo leggo per sicurezza.")
        if sum(i.file_size for i in infos) > 8 * DOCX_MAX_MEMBER:
            raise CvError("Il documento e' troppo grande una volta aperto: non lo leggo per sicurezza.")
        names = {i.filename: i for i in infos}
        main = names.get("word/document.xml")
        if main is None:
            raise CvError("Il DOCX non e' un documento Word valido (manca il testo principale).")
        order = [main] + [names[n] for n in sorted(names) if re.fullmatch(r"word/(?:header|footer)\d*\.xml", n)]
        parts = []
        for info in order:
            raw = _read_member(zf, info)
            if raw[:4] in (b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00") or b"\x00" in raw[:200] \
                    or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise CvError("Il documento contiene elementi non ammessi: non lo leggo per sicurezza.")
            parts.append(_xml_text(raw, ET))
    except CvError:
        raise
    except Exception:
        raise CvError("Il DOCX e' danneggiato e non riesco a leggerlo.") from None
    finally:
        zf.close()
    return check_text("\n".join(parts))


def _xml_text(raw: bytes, ET) -> str:
    out: list[str] = []
    try:
        for _event, elem in ET.iterparse(io.BytesIO(raw), events=("end",)):
            tag = elem.tag
            if tag == _W + "t":
                out.append(elem.text or "")
            elif tag == _W + "tab":
                out.append("\t")
            elif tag in (_W + "br", _W + "cr"):
                out.append("\n")
            elif tag == _W + "p":
                out.append("\n")
            if tag in (_W + "p", _W + "r"):
                elem.clear()
    except ET.ParseError:
        raise CvError("Il DOCX e' danneggiato e non riesco a leggerlo.") from None
    return "".join(out)
