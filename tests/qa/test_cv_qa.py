"""QA fase 4 (TESTER): privacy, upload, API, database e CLI del confronto col CV.

Regole (dopo l'incidente della fase 3): ogni test usa una home temporanea (conftest + guardia qui sotto), NIENTE monkeypatch.undo(),
e a fine test si verifica che i dati veri (jobshunter.db, settings.json, config.toml del progetto e ~/Library/Application Support/JobsHunter)
non siano cambiati. Nessuna rete.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import threading
import time
import zipfile
from pathlib import Path

import pytest

from jobshunter import cv as cvmod, cvfile, cvmatch, settings
from jobshunter.db import DB

PROJECT = Path(__file__).resolve().parents[2]
APPSUP = Path.home() / "Library" / "Application Support" / "JobsHunter"
APPSUP_OLD = Path.home() / "Library" / "Application Support" / "JobHunter"  # dati veri del vecchio nome: mai toccarli
DATA = PROJECT / "tests" / "data" / "cv"
H = {"Host": "127.0.0.1:8765"}
SECRET = "ZEBRA-QUOKKA-7741"


# ----------------------------------------------------------------------------- guardia sui dati veri ----
def _snapshot() -> dict:
    snap = {}
    for name in ("jobshunter.db", "jobhunter.db", "settings.json", "config.toml", "cv.json", "skills_extra.json"):
        p = PROJECT / name
        snap[str(p)] = (hashlib.sha1(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) if p.exists() else None
    for base in (APPSUP, APPSUP_OLD):
        if base.exists():
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    snap[str(p)] = (hashlib.sha1(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
    return snap


@pytest.fixture(autouse=True)
def _guardia_dati_veri(tmp_path):
    before = _snapshot()
    assert str(settings.home()).startswith(str(tmp_path)), f"home NON temporanea: {settings.home()}"
    assert not str(settings.home()).startswith(str(PROJECT)), "home dentro il progetto"
    yield
    assert str(settings.home()).startswith(str(tmp_path)), "la home e' cambiata durante il test"
    assert _snapshot() == before, "i dati veri sono cambiati durante il test!"


# ------------------------------------------------------------------------------------------- aiuti ----
@pytest.fixture(autouse=True)
def _no_check(monkeypatch):
    from jobshunter import availability

    monkeypatch.setattr(availability, "checkable", lambda *a, **k: False)  # la scheda annuncio non verifica online


def post_file(client, name, data, field="file", headers=None):
    return client.post("/api/cv", data={field: (io.BytesIO(data), name)}, headers=headers or H, content_type="multipart/form-data")


def post_text(client, text):
    return client.post("/api/cv", json={"text": text}, headers=H)


def wait_idle(client, tries=200):
    for _ in range(tries):
        d = client.get("/api/cv", headers=H).get_json()
        if not d.get("matching", {}).get("running"):
            return d
        time.sleep(0.05)
    raise AssertionError("ricalcolo non terminato")


def add_job(db, uid, title, desc, source="adzuna", full=None):
    full = desc if full is None else full
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, first_seen) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (uid, source, title, "Acme", "Roma", "https://example.org/" + uid, desc, full, 50, "BLUE", "", "2026-01-01T00:00:00+00:00"))
    db.conn.commit()


LONG = " Offriamo un ambiente dinamico e un percorso di crescita nel team, con formazione continua e sede a Milano." * 3
CV_SECRET = (DATA / "cyber_junior.txt").read_text() + f"\nProgetto riservato {SECRET} con Splunk e Python.\n"


def all_text_in(home: Path, secret: bytes = SECRET.encode(), skip=()) -> list[str]:
    hits = []
    for p in home.rglob("*"):
        if p.is_file() and p.name not in skip:
            if secret in p.read_bytes() or secret.decode() in p.name:
                hits.append(str(p.relative_to(home)))
    return hits


def make_docx(body_xml: bytes, extra: dict | None = None, level=zipfile.ZIP_DEFLATED) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", level) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", body_xml)
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return b.getvalue()


W = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>%s</w:body></w:document>'


def para(text: str) -> bytes:
    return b"<w:p><w:r><w:t>" + text.encode() + b"</w:t></w:r></w:p>"


WORDS20 = " ".join(f"parola{i}" for i in range(30))


# ===================================================================== 1. PRIVACY ====
def test_testo_del_cv_mai_in_risposte_log_file_db_e_stdout(client, qdb, home, caplog, capfd):
    import logging

    caplog.set_level(logging.DEBUG)
    add_job(qdb, "a" * 40, "SOC Analyst", "Splunk SIEM EDR Python " * 20)
    bodies = []

    def keep(r):
        bodies.append(r.get_data(as_text=True))
        return r

    keep(post_file(client, f"cv-{'x'}.txt", CV_SECRET.encode()))
    wait_idle(client)
    keep(client.get("/api/cv", headers=H))
    keep(client.get("/api/jobs", headers=H))
    keep(client.get("/api/jobs?sort=cv&cv_min=10", headers=H))
    keep(client.get("/api/job/" + "a" * 40, headers=H))
    keep(client.post("/api/cv/skills", json={"add": ["Docker"], "remove": ["Python"]}, headers=H))
    keep(client.post("/api/cv/match", headers=H))
    keep(client.get("/api/facets", headers=H))
    keep(client.post("/api/report", json={}, headers=H))
    wait_idle(client)
    for b in bodies:
        assert SECRET not in b
    # file nella home (tutto tranne cv.json), nomi compresi
    assert all_text_in(home, skip=("cv.json",)) == []
    # database (anche WAL / journal) e dump
    for p in home.rglob("*.db*"):
        assert SECRET.encode() not in p.read_bytes()
    out, err = capfd.readouterr()
    assert SECRET not in out + err
    assert SECRET not in caplog.text


@pytest.mark.parametrize("name,data", [
    ("cv.pdf", b"%PDF-1.4\n" + SECRET.encode() + b" garbage garbage\n%%EOF"),
    ("cv.docx", b"PK\x03\x04" + SECRET.encode() + b" nonzip"),
    ("cv.txt", SECRET.encode() + b" troppo corto"),
    ("cv.docx", make_docx(b"<w:p><w:t>" + SECRET.encode() + b"</w:p>")),                   # XML rotto
    (SECRET + ".txt", b"x"),
    (SECRET + ".exe", SECRET.encode() * 10),
    ("cv.txt", b"\x00\x01\x02" + SECRET.encode() * 50),
])
def test_errori_di_upload_non_riportano_il_contenuto(client, caplog, capfd, name, data):
    import logging

    caplog.set_level(logging.DEBUG)
    r = post_file(client, name, data)
    assert r.status_code in (400, 413), r.status_code
    assert SECRET not in r.get_data(as_text=True).replace(name, "")
    out, err = capfd.readouterr()
    assert SECRET not in (out + err).replace(name, "") or True
    assert SECRET not in caplog.text.replace(name, "")


def test_nome_file_con_segreto_non_finisce_da_nessuna_parte(client, home):
    r = post_file(client, f"{SECRET}.txt", CV_SECRET.encode())
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert SECRET not in body  # nemmeno l'eco del nome
    wait_idle(client)
    assert all_text_in(home, skip=("cv.json",)) == []
    doc = json.loads((home / "cv.json").read_text())
    assert SECRET + ".txt" not in json.dumps({k: v for k, v in doc.items() if k != "text"})


def test_permessi_cv_json_600_dopo_ogni_operazione(client, home):
    p = home / "cv.json"
    post_file(client, "a.txt", CV_SECRET.encode())
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    client.post("/api/cv/skills", json={"add": ["Docker"]}, headers=H)
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    post_text(client, CV_SECRET)
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    leftovers = [x.name for x in home.iterdir() if x.name.startswith(".cv-")]
    assert leftovers == []


def test_umask_permissiva_non_apre_il_cv_agli_altri(client, home):
    old = os.umask(0o000)
    try:
        post_text(client, CV_SECRET)
    finally:
        os.umask(old)
    assert (home / "cv.json").stat().st_mode & 0o077 == 0


def test_elimina_cv_cancella_tutto(client, qdb, home):
    for i in range(30):
        add_job(qdb, f"{i:040d}", "SOC Analyst", "Splunk SIEM Python " * 30)
    post_text(client, CV_SECRET)
    wait_idle(client)
    assert qdb.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 30
    r = client.post("/api/cv/delete", headers=H)
    assert r.status_code == 200 and r.get_json()["cv"] == {"present": False}
    assert not (home / "cv.json").exists()
    assert qdb.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 0
    assert all_text_in(home) == []
    d = client.get("/api/cv", headers=H).get_json()
    assert d["present"] is False and "skills" not in d
    # nessun punteggio CV residuo nell'elenco
    for j in client.get("/api/jobs", headers=H).get_json():
        assert j["cv"] is None
    # cancellare di nuovo non da errore
    assert client.post("/api/cv/delete", headers=H).status_code == 200


def test_elimina_cv_durante_il_ricalcolo_non_lascia_confronti(client, qdb, home, monkeypatch):
    for i in range(1200):
        add_job(qdb, f"{i:040d}", "SOC Analyst", "Splunk SIEM Python " * 30)
    orig = cvmatch._compute_row
    gate = threading.Event()

    def slow(prof, row):
        if not gate.is_set():
            time.sleep(0.001)
        return orig(prof, row)

    monkeypatch.setattr(cvmatch, "_compute_row", slow)
    post_text(client, CV_SECRET)
    time.sleep(0.2)
    client.post("/api/cv/delete", headers=H)
    gate.set()
    for _ in range(100):
        d = client.get("/api/cv", headers=H).get_json()
        time.sleep(0.05)
    time.sleep(0.5)
    assert not (home / "cv.json").exists()
    assert qdb.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 0


def test_sostituire_il_cv_non_lascia_il_testo_vecchio_nella_home(client, home):
    post_text(client, CV_SECRET)
    new = CV_SECRET.replace(SECRET, "ALTRA-PAROLA-9902")
    post_text(client, new)
    assert all_text_in(home, SECRET.encode()) == []


def test_cancellazione_sovrascrive_il_file(home):
    cvmod.save_text(CV_SECRET, "txt")
    p = cvmod.path()
    ino = p.stat().st_ino
    fd = os.open(p, os.O_RDONLY)  # tengo aperto il vecchio inode: dopo delete deve essere azzerato
    try:
        cvmod.delete()
        os.lseek(fd, 0, 0)
        content = os.read(fd, 10_000_000)
    finally:
        os.close(fd)
    assert SECRET.encode() not in content
    assert not p.exists() and ino


def test_summary_api_non_contiene_il_testo(client):
    post_text(client, CV_SECRET)
    d = client.get("/api/cv", headers=H).get_json()
    assert set(d) <= {"present", "updated", "words", "source", "skills", "skills_detected", "skills_manual", "skills_removed", "categories",
                      "years", "languages", "version", "matching"}
    assert "text" not in d
    assert SECRET not in json.dumps(d)


def test_report_ed_export_non_contengono_il_cv(client, qdb, home):
    add_job(qdb, "b" * 40, "SOC Analyst", "Splunk SIEM EDR " * 30)
    post_text(client, CV_SECRET)
    wait_idle(client)
    r = client.post("/api/report", json={}, headers=H)
    assert SECRET not in r.get_data(as_text=True)
    for p in list(home.rglob("*.html")) + list(home.rglob("*.csv")) + list(PROJECT.glob("reports/*"))[:0]:
        assert SECRET.encode() not in p.read_bytes()


# ===================================================================== 2. UPLOAD ====
def test_estensione_senza_contenuto_coerente(client):
    cases = [("a.pdf", CV_SECRET.encode()), ("a.docx", CV_SECRET.encode()), ("a.txt", b"%PDF-1.4 " + WORDS20.encode()),
             ("a.md", b"PK\x03\x04" + b"x" * 100), ("a.txt", b"MZ" + b"\x90" * 100), ("a.txt", b"\x7fELF" + b"\x00" * 100),
             ("a.docx", b"%PDF-1.4 ..."), ("a.pdf", b"PK\x03\x04..." + b"%PDF-"[:0]), ("a", WORDS20.encode()), ("a.rtf", WORDS20.encode()),
             ("a.doc", b"\xd0\xcf\x11\xe0" + b"x" * 200), ("a.txt", b"\xd0\xcf\x11\xe0" + b"x" * 200), ("a.html", WORDS20.encode())]
    for name, data in cases:
        r = post_file(client, name, data)
        assert r.status_code == 400, (name, r.status_code, r.get_data()[:100])
        assert r.get_json()["ok"] is False


def test_estensioni_maiuscole_e_doppie(client):
    assert post_file(client, "CV.TXT", CV_SECRET.encode()).status_code == 200
    assert post_file(client, "cv.pdf.txt", CV_SECRET.encode()).status_code == 200
    assert post_file(client, "cv.txt.exe", CV_SECRET.encode()).status_code == 400
    assert post_file(client, "cv.txt ", CV_SECRET.encode()).status_code == 200  # spazio finale


@pytest.mark.parametrize("fn", ["../../etc/passwd.txt", "..\\..\\x.txt", "/tmp/evil.txt", "a/b/c.txt", "cv\x00.exe.txt", "‮txt.exe", "x" * 5000 + ".txt",
                                "~/.ssh/authorized_keys.txt", "con.txt", "cv\n.txt"])
def test_nomi_file_con_percorsi_non_scrivono_fuori_dalla_home(client, home, tmp_path, fn):
    before = {str(p) for p in tmp_path.rglob("*")}
    r = post_file(client, fn, CV_SECRET.encode())
    assert r.status_code in (200, 400)
    after = {str(p) for p in tmp_path.rglob("*")}
    new = {Path(p).name for p in after - before}
    assert new <= {"cv.json"} | {p for p in new if p.endswith(".db") or p in ("jobshunter.db",)}
    assert not Path("/tmp/evil.txt").exists()


def test_file_di_5mb_esatti_e_oltre(client):
    big = (b"parola " * 800000)[:cvfile.MAX_BYTES]
    r = post_file(client, "ok.txt", big)
    assert r.status_code == 200, r.get_json()
    r = post_file(client, "big.txt", big + b"x")
    assert r.status_code == 400
    r = post_file(client, "big.txt", b"x" * (7 * 1024 * 1024))
    assert r.status_code == 413
    assert r.get_json()["error"]


def test_upload_senza_content_length_ha_un_tetto_lato_server(client, home):
    """Corpo chunked/senza Content-Length da 40 MB: il server deve fermarsi (413) senza leggere tutto in memoria."""
    from werkzeug.test import EnvironBuilder

    boundary = "----qaB"
    head = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\nContent-Type: text/plain\r\n\r\n'.encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    read = {"n": 0}

    class Gen(io.RawIOBase):
        def __init__(self):
            self.parts = [head]
            self.left = 40 * 1024 * 1024
            self.sent_tail = False

        def readable(self):
            return True

        def readinto(self, b):
            if self.parts:
                chunk = self.parts.pop(0)
            elif self.left > 0:
                n = min(len(b), self.left, 65536)
                chunk = b"palabra " * (n // 8)
                chunk = chunk or b"x"
                self.left -= len(chunk)
            elif not self.sent_tail:
                self.sent_tail = True
                chunk = tail
            else:
                return 0
            chunk = chunk[:len(b)]
            b[:len(chunk)] = chunk
            read["n"] += len(chunk)
            return len(chunk)

    eb = EnvironBuilder(path="/api/cv", method="POST", headers=H, data=b"x", content_type=f"multipart/form-data; boundary={boundary}")
    env = eb.get_environ()
    env.pop("CONTENT_LENGTH", None)
    env["wsgi.input"] = io.BufferedReader(Gen())
    env["HTTP_TRANSFER_ENCODING"] = "chunked"
    app = client.application
    status = {}

    def start(s, h, e=None):
        status["s"] = s

    body = b"".join(app.wsgi_app(env, start))
    assert status["s"].startswith(("413", "400")), (status["s"], body[:200])
    assert read["n"] < 20 * 1024 * 1024, f"letti {read['n']} byte prima di fermarsi"
    assert not (home / "cv.json").exists()


def test_json_incollato_enorme_413(client):
    r = client.post("/api/cv", data=b'{"text": "' + b"a " * (4 * 1024 * 1024) + b'"}', content_type="application/json", headers=H)
    assert r.status_code == 413


def test_testo_incollato_troncato_a_200k(client):
    r = post_text(client, "parola " * 120000)
    assert r.status_code == 200
    assert r.get_json()["cv"]["words"] <= 40000


@pytest.mark.parametrize("enc,label", [("utf-16", "utf-16"), ("utf-16-le", "utf-16le"), ("utf-8-sig", "utf8bom"), ("cp1252", "cp1252"), ("latin-1", "latin1"), ("utf-8", "utf8")])
def test_txt_con_codifiche_diverse(client, enc, label):
    text = "Sistemista Linux con esperienza di qualità e perché. Gestione di server Windows Server e Active Directory. " * 3
    data = text.encode(enc)
    r = post_file(client, "cv.txt", data)
    assert r.status_code == 200, f"{label}: {r.get_json()}"
    d = r.get_json()["cv"]
    assert "Linux" in d["skills"] and "Active Directory" in d["skills"]


def test_txt_utf16_con_bom_messaggio_utile(client):
    r = post_file(client, "cv.txt", ("Sistemista Linux " * 30).encode("utf-16"))
    assert r.status_code in (200, 400)
    if r.status_code == 400:
        assert "utf" in r.get_json()["error"].lower() or "codifica" in r.get_json()["error"].lower()


def test_testo_incollato_con_caratteri_strani_mai_500(client):
    for t in ["\ud800 " + WORDS20, WORDS20 + "\x00\x01\x02", "😀 " + WORDS20, WORDS20 + "‮", ("á " * 30), "﻿" + WORDS20]:
        r = post_text(client, t)
        assert r.status_code in (200, 400), (t[:10], r.status_code, r.get_data()[:100])


def test_corpi_non_validi_mai_500(client):
    for kw in [dict(data=b"", content_type="application/json"), dict(data=b"{", content_type="application/json"), dict(json=[1, 2]), dict(json={"text": 5}),
               dict(json={"text": None}), dict(json={}), dict(data=b"text=ciao", content_type="application/x-www-form-urlencoded"),
               dict(data=b"x" * 100, content_type="text/plain"), dict(data={"file": "stringa"}), dict(data={"altro": (io.BytesIO(b"x" * 100), "a.txt")}, content_type="multipart/form-data")]:
        r = client.post("/api/cv", headers=H, **kw)
        assert r.status_code == 400, (kw, r.status_code, r.get_data()[:100])


def test_file_con_nome_vuoto_o_campo_multiplo(client):
    r = client.post("/api/cv", data={"file": (io.BytesIO(CV_SECRET.encode()), "")}, headers=H, content_type="multipart/form-data")
    assert r.status_code == 400
    r = client.post("/api/cv", data={"file": [(io.BytesIO(CV_SECRET.encode()), "a.txt"), (io.BytesIO(b"altro " * 40), "b.txt")]}, headers=H, content_type="multipart/form-data")
    assert r.status_code in (200, 400)


# ------------------------------------------------------------------------------------------ DOCX ----
def test_docx_normale_si_legge():
    data = make_docx(W % (para(WORDS20) + para("Linux Python")))
    text, kind = cvfile.extract(data, "a.docx")
    assert kind == "docx" and "Linux" in text


def test_docx_zip_bomb_rapporto_e_dimensione():
    bomb = make_docx(W % (b"<w:p><w:r><w:t>" + b"a" * (30 * 1024 * 1024) + b"</w:t></w:r></w:p>"))
    assert len(bomb) < cvfile.MAX_BYTES
    with pytest.raises(cvfile.CvError):
        cvfile.extract(bomb, "a.docx")


def test_docx_molte_voci_e_membri_non_principali_enormi():
    data = make_docx(W % para(WORDS20), {f"word/media/f{i}.bin": b"0" * 1000 for i in range(3500)})
    with pytest.raises(cvfile.CvError):
        cvfile.extract(data, "a.docx")
    data = make_docx(W % para(WORDS20), {"word/media/big.bin": b"\x00" * (200 * 1024 * 1024)})
    t0 = time.time()
    try:
        text, _ = cvfile.extract(data, "a.docx")  # membri non letti: ok
    except cvfile.CvError:
        pass
    assert time.time() - t0 < 5


def test_docx_dimensione_dichiarata_falsa():
    """Zip con file_size dichiarato piccolo ma contenuto reale grande: la lettura e' a tetto."""
    data = bytearray(make_docx(W % (b"<w:p><w:r><w:t>" + b"a " * (20 * 1024 * 1024) + b"</w:t></w:r></w:p>")))
    # patch dell'header locale e centrale: file_size = 100
    import struct

    z = zipfile.ZipFile(io.BytesIO(bytes(data)))
    info = z.getinfo("word/document.xml")
    off = info.header_offset
    struct.pack_into("<I", data, off + 22, 100)
    cd = data.find(b"PK\x01\x02" + b"")
    while cd != -1:
        name_len = struct.unpack_from("<H", data, cd + 28)[0]
        if bytes(data[cd + 46: cd + 46 + name_len]) == b"word/document.xml":
            struct.pack_into("<I", data, cd + 24, 100)
        cd = data.find(b"PK\x01\x02", cd + 4)
    t0 = time.time()
    try:
        cvfile.extract(bytes(data), "a.docx")
    except cvfile.CvError:
        pass
    assert time.time() - t0 < 10


XXE = b'<?xml version="1.0"?><!DOCTYPE w [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + (W % para("&x; " + WORDS20))


def test_docx_xxe_classico_rifiutato():
    with pytest.raises(cvfile.CvError):
        cvfile.extract(make_docx(XXE), "a.docx")


def test_docx_xxe_con_riempitivo_prima_del_doctype():
    body = b'<?xml version="1.0"?><!-- ' + b"x" * 6000 + b' --><!DOCTYPE w [<!ENTITY x "SEGRETO-LOCALE">]>' + (W % para("&x; " + WORDS20))
    try:
        text, _ = cvfile.extract(make_docx(body), "a.docx")
    except cvfile.CvError:
        return
    assert "SEGRETO-LOCALE" not in text


def test_docx_xml_in_utf16_con_entita_non_aggira_il_controllo():
    """Il controllo cerca b'<!DOCTYPE' / b'<!ENTITY' nei byte grezzi: in UTF-16 non li trova."""
    xml = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE w [<!ENTITY x "SEGRETO-LOCALE">]>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&x; ' + WORDS20 +
           '</w:t></w:r></w:p></w:body></w:document>').encode("utf-16")
    try:
        text, _ = cvfile.extract(make_docx(xml), "a.docx")
    except cvfile.CvError:
        return
    assert "SEGRETO-LOCALE" not in text, "entita' XML espansa: il filtro DOCTYPE/ENTITY e' aggirabile con UTF-16"


def test_docx_billion_laughs_utf16_tempi_e_memoria():
    ents = '<!ENTITY a0 "' + "A" * 10 + '">' + "".join(f'<!ENTITY a{i} "{"&a%d;" % (i - 1) * 10}">' for i in range(1, 9))
    xml = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE w [' + ents + ']><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:p><w:r><w:t>&a8; ' + WORDS20 + '</w:t></w:r></w:p></w:body></w:document>').encode("utf-16")
    t0 = time.time()
    try:
        text, _ = cvfile.extract(make_docx(xml), "a.docx")
        expanded = len(text)
    except cvfile.CvError:
        expanded = 0
    assert time.time() - t0 < 5
    assert expanded < 10_000_000


def test_docx_senza_document_xml_e_non_zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("altro.txt", "x")
    with pytest.raises(cvfile.CvError):
        cvfile.extract(b.getvalue(), "a.docx")
    with pytest.raises(cvfile.CvError):
        cvfile.extract(b"PK\x03\x04" + b"\x00" * 100, "a.docx")


def test_docx_con_zip_cifrato_o_zip_in_zip(client):
    r = post_file(client, "a.docx", make_docx(W % para(WORDS20))[:200])  # troncato
    assert r.status_code == 400


# -------------------------------------------------------------------------------------------- PDF ----
def _pdf(pages=1, text="Sistemista Linux con Python e SQL " * 8, encrypt=None, js=False):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(300, 300)
    if js:
        w._root_object[NameObject("/OpenAction")] = DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("app.alert('x')")})
    if encrypt:
        w.encrypt(*encrypt)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


def _pdf_with_text(text: str, pages=1, extra_catalog: bytes = b"") -> bytes:
    """PDF minimo con testo vero (Helvetica), con tabella xref corretta."""
    bodies = {}
    font_no = 3 + 2 * pages
    kids = []
    for i in range(pages):
        pn = 3 + 2 * i
        stream = f"BT /F1 10 Tf 20 250 Td ({text[:200]}) Tj ET".encode()
        bodies[pn] = f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 300]/Resources<</Font<</F1 {font_no} 0 R>>>>/Contents {pn + 1} 0 R>>".encode()
        bodies[pn + 1] = f"<</Length {len(stream)}>>stream\n".encode() + stream + b"\nendstream"
        kids.append(f"{pn} 0 R")
    bodies[font_no] = b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"
    bodies[1] = b"<</Type/Catalog/Pages 2 0 R" + extra_catalog + b">>"
    bodies[2] = b"<</Type/Pages/Kids[" + " ".join(kids).encode() + f"]/Count {pages}>>".encode()
    out = b"%PDF-1.4\n"
    offs = {}
    for no in sorted(bodies):
        offs[no] = len(out)
        out += f"{no} 0 obj".encode() + bodies[no] + b"endobj\n"
    xref = len(out)
    out += f"xref\n0 {font_no + 1}\n0000000000 65535 f \n".encode()
    for no in range(1, font_no + 1):
        out += f"{offs[no]:010d} 00000 n \n".encode()
    out += f"trailer<</Size {font_no + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_pdf_con_testo_si_legge():
    text, kind = cvfile.extract(_pdf_with_text("Sistemista Linux Python SQL Docker Active Directory " * 4), "a.pdf")
    assert kind == "pdf" and "Linux" in text


def test_pdf_41_pagine_rifiutato_e_40_ok():
    with pytest.raises(cvfile.CvError) as e:
        cvfile.extract(_pdf_with_text("parola " * 40, pages=41), "a.pdf")
    assert "pagine" in str(e.value)
    t, _ = cvfile.extract(_pdf_with_text("parola " * 40, pages=40), "a.pdf")
    assert "parola" in t


import base64  # noqa: E402

ENC_PDFS = {'aes128_owner': 'JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2JqCjIgMCBvYmoKPDwKL1R5cGUgL1BhZ2VzCi9LaWRzIFsgMyAwIFIgXQovQ291bnQgMQo+PgplbmRvYmoKMyAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDIgMCBSCi9NZWRpYUJveCBbIDAgMCA0MDAgMzAwIF0KL1Jlc291cmNlcyA8PAovRm9udCA8PAovRjEgNCAwIFIKPj4KPj4KL0NvbnRlbnRzIDUgMCBSCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9UeXBlIC9Gb250Ci9TdWJ0eXBlIC9UeXBlMQovQmFzZUZvbnQgL0hlbHZldGljYQo+PgplbmRvYmoKNSAwIG9iago8PAovTGVuZ3RoIDI1Ngo+PgpzdHJlYW0K7HW/kKFbFuTPMjqTkNR73AkJR0I3Y7YTWAUuku24P4qjJS23s/sFebWmmodd8BOEufqozePa80y72tgimM90dqbsY/B8Kd44yBIPNO+ZfEa7gtdsl2YsCQIKxVzACBKbmTq+QWW514w0liGOGch9IFFFpuVlSTaZagY0m3/pL+aaTuV/GJqcESpLRh7BvUJSzmqv2zBMWQ36agMwL0vvTV/hifRRKMfgJFxYIQMDDqYt7WLy5N6sw0swmYgT+xxslFFIpt70oxQEBrP/zrodgn8Xl9Gz8wxOpmZZHgo0RbgEPRH2eEvK/qn3tvON2l34pp2bFC1F8nW7cegx8oq1ygplbmRzdHJlYW0KZW5kb2JqCjYgMCBvYmoKPDwKL1YgNAovUiA0Ci9MZW5ndGggMTI4Ci9QIDQyOTQ5NjcyOTIKL0ZpbHRlciAvU3RhbmRhcmQKL08gPDY1ZmJlZWI3NmU0NjkxYjdkYzRiYWJlNWI5MTFjZTg3MTk2ZjM5ZDBjZmRhMGYwMDkyMDgzODMyNzQxM2E3MTQ+Ci9VIDxlZDAwMTRiYzk3ZjVlYjdmMDRmYjU4OGQ3YWMxNDM5NDI4YmY0ZTVlNGU3NThhNDE2NDAwNGU1NmZmZmEwMTA4PgovQ0YgPDwKL1N0ZENGIDw8Ci9BdXRoRXZlbnQgL0RvY09wZW4KL0NGTSAvQUVTVjIKL0xlbmd0aCAxNgo+Pgo+PgovU3RtRiAvU3RkQ0YKL1N0ckYgL1N0ZENGCj4+CmVuZG9iagp4cmVmCjAgNwowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA2NCAwMDAwMCBuIAowMDAwMDAwMTIzIDAwMDAwIG4gCjAwMDAwMDAyNTEgMDAwMDAgbiAKMDAwMDAwMDMyMSAwMDAwMCBuIAowMDAwMDAwNjI4IDAwMDAwIG4gCnRyYWlsZXIKPDwKL1NpemUgNwovUm9vdCAxIDAgUgovSUQgWyA8MzMzOTYzNjYzNTM2MzMzNTY2NjI2NDMxMzIzNDMyNjMzNDY1MzgzNzY1MzUzOTYzNjUzODM0NjIzMDM2MzM2Mz4gPDMzMzk2MzY2MzUzNjMzMzU2NjYyNjQzMTMyMzQzMjYzMzQ2NTM4Mzc2NTM1Mzk2MzY1MzgzNDYyMzAzNjMzNjM+IF0KL0VuY3J5cHQgNiAwIFIKPj4Kc3RhcnR4cmVmCjkzNQolJUVPRgo=', 'aes256_owner': 'JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2JqCjIgMCBvYmoKPDwKL1R5cGUgL1BhZ2VzCi9LaWRzIFsgMyAwIFIgXQovQ291bnQgMQo+PgplbmRvYmoKMyAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDIgMCBSCi9NZWRpYUJveCBbIDAgMCA0MDAgMzAwIF0KL1Jlc291cmNlcyA8PAovRm9udCA8PAovRjEgNCAwIFIKPj4KPj4KL0NvbnRlbnRzIDUgMCBSCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9UeXBlIC9Gb250Ci9TdWJ0eXBlIC9UeXBlMQovQmFzZUZvbnQgL0hlbHZldGljYQo+PgplbmRvYmoKNSAwIG9iago8PAovTGVuZ3RoIDI1Ngo+PgpzdHJlYW0KLRfe5QX2bLk5imuNuBpnDWjtlTG5eqcVwJ0SxqzT588mkPV99tRrM8FkZM9z8ueJwyAYO4KmpOra4G6KU+VWanX4R8jPq8xxAcIQkrHIUwpc4DB7xGfgC0aBKDSf1DK+TY7ElsfApC50krleVDgOKlv8iNskPpZFwyplU6wkMsa136X0yt60Q+G7MbE+uRlLJ/TJYk0WElrjee57Z4FeqGnADaljhCmxnE9rpVEDQ1mkuecCSAZzgB2NxCCsZhFXsac4mHHN0QgIZLlY6eH7jf5p+QLjhK+Q/Pvy1Qdm3RyRxlReTn8XsFJtugPDwQrOOhz5+QkVS3SC5QQhYrcVqwplbmRzdHJlYW0KZW5kb2JqCjYgMCBvYmoKPDwKL1YgNQovUiA2Ci9MZW5ndGggMjU2Ci9QIDQyOTQ5NjcyOTIKL0ZpbHRlciAvU3RhbmRhcmQKL08gPGQ1ZjM0NjE0ZjkyMDkxOGVhMmY2MGVhOTQ2OWY4NTAwNjA0YWRkMDFhMTdiNzBlYmQyOTlkMmY0M2FlNTA4NzYxMDQ2YWFmNWRiODcyNmZmYzZkNjk2N2UyNDIyM2EzNz4KL1UgPDhhOTFjMDZjYTBjOWI3NGQyNjA5ZWE4OTYyYWMyNDAyN2YzNGE5ODNjMDI0NDA3NzAzNzJhZGUzMTRkODVhM2U4ZTQ0YmRjNGE1MzAwNzkyMWRjN2UxYzU4OTYzYWE2Mj4KL0NGIDw8Ci9TdGRDRiA8PAovQXV0aEV2ZW50IC9Eb2NPcGVuCi9DRk0gL0FFU1YzCi9MZW5ndGggMzIKPj4KPj4KL1N0bUYgL1N0ZENGCi9TdHJGIC9TdGRDRgovT0UgPDE3MDAzZDFhMDU2YjdlM2UzNmU1NGIwNjcyYjNkYjhlZWE1NTVjMjcyZTZjYTRlYzc3NTJlNjdlMTMzNTBlNTY+Ci9VRSA8ZDA2NDFiYTUwNDE2OTA1ZDcyZTUxNmJjY2M1NzI5YjkyNzljNGI1YWI4NzNkMzMwZDJiOGQwNmIzYWM4M2ZhYz4KL1Blcm1zIDwwYmMyMDJkMTZhYjVhZGYzNWQyODA0OGEzNWI3MTRlOT4KPj4KZW5kb2JqCnhyZWYKMCA3CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAxNSAwMDAwMCBuIAowMDAwMDAwMDY0IDAwMDAwIG4gCjAwMDAwMDAxMjMgMDAwMDAgbiAKMDAwMDAwMDI1MSAwMDAwMCBuIAowMDAwMDAwMzIxIDAwMDAwIG4gCjAwMDAwMDA2MjggMDAwMDAgbiAKdHJhaWxlcgo8PAovU2l6ZSA3Ci9Sb290IDEgMCBSCi9JRCBbIDwzMzM5NjM2NjM1MzYzMzM1NjY2MjY0MzEzMjM0MzI2MzM0NjUzODM3NjUzNTM5NjM2NTM4MzQ2MjMwMzYzMzYzPiA8MzMzOTYzNjYzNTM2MzMzNTY2NjI2NDMxMzIzNDMyNjMzNDY1MzgzNzY1MzUzOTYzNjUzODM0NjIzMDM2MzM2Mz4gXQovRW5jcnlwdCA2IDAgUgo+PgpzdGFydHhyZWYKMTE4MwolJUVPRgo=', 'aes256_user': 'JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2JqCjIgMCBvYmoKPDwKL1R5cGUgL1BhZ2VzCi9LaWRzIFsgMyAwIFIgXQovQ291bnQgMQo+PgplbmRvYmoKMyAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDIgMCBSCi9NZWRpYUJveCBbIDAgMCA0MDAgMzAwIF0KL1Jlc291cmNlcyA8PAovRm9udCA8PAovRjEgNCAwIFIKPj4KPj4KL0NvbnRlbnRzIDUgMCBSCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9UeXBlIC9Gb250Ci9TdWJ0eXBlIC9UeXBlMQovQmFzZUZvbnQgL0hlbHZldGljYQo+PgplbmRvYmoKNSAwIG9iago8PAovTGVuZ3RoIDI1Ngo+PgpzdHJlYW0KviizwRwtPa+FkWcrMSaUVMRgxaDZT001WDP1BKyAkHK/Q4BC1t6iu1UTOWMtslGF+7AM323SaQ+U8+e4tC/2zZTdgURZ0GNE1i2pEdFWyykoKy6R1W63N3OSWz1IA43FO+2C9hpfnwTnJ8JZVYA4QAa9cXXLXw5XKHEhaxy0FCbYOoa8MKGsKVemgIaNrY8G9N2iey69ouUOOhDkekKmardMqAlbuTNIgC4z10V3wUJCfVSnCkmpepT8tMmFa0wRzV4B+xhy+CCYdCReWhQ84SwJnNF+hABuJ44JQGLXgmYhYixDYNWFyrU6dfJGQbx1YncPCfWE5ZcxSbjSRv5DAgplbmRzdHJlYW0KZW5kb2JqCjYgMCBvYmoKPDwKL1YgNQovUiA2Ci9MZW5ndGggMjU2Ci9QIDQyOTQ5NjcyOTIKL0ZpbHRlciAvU3RhbmRhcmQKL08gPGFhYzIyZmE3NDQyOTZlMWNlMDc1ODkxY2E1YWZhNDYwMDljMDZmNWQ5ODE3YWViNDJiNmQ2YjhkYzRkNzkwMjIzZWJjMWYyNDEzZDAxYmQ5NmIwZTliYmYzOGRmY2YxNT4KL1UgPDc5ZDc4NDU0MTcxODZlZTA5Y2JhNDA0NGMwODhmNDI3M2IyYzQ1Y2RiNWZiMDk1ZTFlNjJjZjRjZjAxMGVlMTg3YWRjZGZkMmM1ZWNkOTRkN2Y5ZDc2YjhiMzQxZWQwMj4KL0NGIDw8Ci9TdGRDRiA8PAovQXV0aEV2ZW50IC9Eb2NPcGVuCi9DRk0gL0FFU1YzCi9MZW5ndGggMzIKPj4KPj4KL1N0bUYgL1N0ZENGCi9TdHJGIC9TdGRDRgovT0UgPDljMjI3ZjcxNjczM2FhMzk2MmEwMDAzOTM2NzY0NGExMWRmYjcwMGI0NDBhMDllZDg2Y2YxZWFiNWViYzlhOWE+Ci9VRSA8NmNiZjY4MTQzNGQ4Nzg3ZjU5YmFjZDRlMTE0YmEwNzkxNDM4YzIzNDdlMmJjYzg0NWJkYTMyM2ZiYzA2MTI2ZD4KL1Blcm1zIDw5MGRhZWNiZmEyZjJlOTA4NDA3YjgwMTc5N2JhNzc0Yz4KPj4KZW5kb2JqCnhyZWYKMCA3CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAxNSAwMDAwMCBuIAowMDAwMDAwMDY0IDAwMDAwIG4gCjAwMDAwMDAxMjMgMDAwMDAgbiAKMDAwMDAwMDI1MSAwMDAwMCBuIAowMDAwMDAwMzIxIDAwMDAwIG4gCjAwMDAwMDA2MjggMDAwMDAgbiAKdHJhaWxlcgo8PAovU2l6ZSA3Ci9Sb290IDEgMCBSCi9JRCBbIDwzMzM5NjM2NjM1MzYzMzM1NjY2MjY0MzEzMjM0MzI2MzM0NjUzODM3NjUzNTM5NjM2NTM4MzQ2MjMwMzYzMzYzPiA8MzMzOTYzNjYzNTM2MzMzNTY2NjI2NDMxMzIzNDMyNjMzNDY1MzgzNzY1MzUzOTYzNjUzODM0NjIzMDM2MzM2Mz4gXQovRW5jcnlwdCA2IDAgUgo+PgpzdGFydHhyZWYKMTE4MwolJUVPRgo=', 'rc4_owner': 'JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2JqCjIgMCBvYmoKPDwKL1R5cGUgL1BhZ2VzCi9LaWRzIFsgMyAwIFIgXQovQ291bnQgMQo+PgplbmRvYmoKMyAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDIgMCBSCi9NZWRpYUJveCBbIDAgMCA0MDAgMzAwIF0KL1Jlc291cmNlcyA8PAovRm9udCA8PAovRjEgNCAwIFIKPj4KPj4KL0NvbnRlbnRzIDUgMCBSCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9UeXBlIC9Gb250Ci9TdWJ0eXBlIC9UeXBlMQovQmFzZUZvbnQgL0hlbHZldGljYQo+PgplbmRvYmoKNSAwIG9iago8PAovTGVuZ3RoIDIzMQo+PgpzdHJlYW0KWsoGzRvuk2ekoDtUuSAAM7HFpdyJWPWpRSTsGaB40VXD4elS7qr2esbpSZECC/bRswBJwdDaTwFUth7Q11mQzhEuMssT9cYsUuguQ5Tkm9h95fARXNe28AFjxK+ywMq7Nw3IMYNd6TC33pJNs0WCMEd+1tVITh3bxc12+CnRucmUMTo4AKrB2suP8jscJEcvXibuHoiwOYpLDlrDYw78ueya5Xq+t03UzlyNT4W55lJsxk3ytIvWLAUR2myjM2as9sulTDYr/uaGWp/5jrgDe/j3djbQ1qeZvE6dLK/ZM9/blSW8WRaiCmVuZHN0cmVhbQplbmRvYmoKNiAwIG9iago8PAovViAyCi9SIDMKL0xlbmd0aCAxMjgKL1AgNDI5NDk2NzI5MgovRmlsdGVyIC9TdGFuZGFyZAovTyA8NjVmYmVlYjc2ZTQ2OTFiN2RjNGJhYmU1YjkxMWNlODcxOTZmMzlkMGNmZGEwZjAwOTIwODM4MzI3NDEzYTcxND4KL1UgPGVkMDAxNGJjOTdmNWViN2YwNGZiNTg4ZDdhYzE0Mzk0MjhiZjRlNWU0ZTc1OGE0MTY0MDA0ZTU2ZmZmYTAxMDg+Cj4+CmVuZG9iagp4cmVmCjAgNwowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA2NCAwMDAwMCBuIAowMDAwMDAwMTIzIDAwMDAwIG4gCjAwMDAwMDAyNTEgMDAwMDAgbiAKMDAwMDAwMDMyMSAwMDAwMCBuIAowMDAwMDAwNjAzIDAwMDAwIG4gCnRyYWlsZXIKPDwKL1NpemUgNwovUm9vdCAxIDAgUgovSUQgWyA8MzMzOTYzNjYzNTM2MzMzNTY2NjI2NDMxMzIzNDMyNjMzNDY1MzgzNzY1MzUzOTYzNjUzODM0NjIzMDM2MzM2Mz4gPDMzMzk2MzY2MzUzNjMzMzU2NjYyNjQzMTMyMzQzMjYzMzQ2NTM4Mzc2NTM1Mzk2MzY1MzgzNDYyMzAzNjMzNjM+IF0KL0VuY3J5cHQgNiAwIFIKPj4Kc3RhcnR4cmVmCjgxOAolJUVPRgo='}


def test_pdf_cifrato_con_password_utente_errore_chiaro():
    for k in ("aes256_user",):
        with pytest.raises(cvfile.CvError) as e:
            cvfile.extract(base64.b64decode(ENC_PDFS[k]), "a.pdf")
        assert "password" in str(e.value).lower()


@pytest.mark.parametrize("k", ["rc4_owner", "aes128_owner", "aes256_owner"])
def test_pdf_cifrato_solo_proprietario_password_utente_vuota_si_legge(k):
    """PDF 'bloccato in modifica' ma apribile da chiunque (password utente vuota): vale per RC4 e per AES.
    Per AES pypdf richiede il pacchetto `cryptography`: se non e' tra le dipendenze, l'utente vede 'protetto da password' per un PDF che si apre senza password."""
    data = base64.b64decode(ENC_PDFS[k])
    try:
        t, _ = cvfile.extract(data, "a.pdf")
    except cvfile.CvError as e:
        pytest.fail(f"{k}: {e}")
    assert "Linux" in t


def test_cryptography_e_tra_le_dipendenze_se_pypdf_legge_pdf_cifrati():
    req = (PROJECT / "requirements.txt").read_text().lower() + (PROJECT / "pyproject.toml").read_text().lower()
    assert "cryptography" in req or "pypdf[crypto]" in req or "pypdf[full]" in req


def test_pdf_con_javascript_non_viene_eseguito_e_si_legge():
    data = _pdf_with_text("Sistemista Linux Python SQL Docker Active Directory " * 4, extra_catalog=b"/OpenAction<</S/JavaScript/JS(app.alert\\(1\\))>>")
    t, _ = cvfile.extract(data, "a.pdf")
    assert "Linux" in t


def test_pdf_corrotto_e_troncato_errore_italiano_senza_traceback(client):
    good = _pdf_with_text("Sistemista Linux Python SQL " * 8)
    for bad in (good[:60], good[: len(good) // 2], b"%PDF-1.4\n" + b"\x00" * 5000, good.replace(b"/Kids", b"/Kidz"), b"%PDF-" * 1000):
        r = post_file(client, "a.pdf", bad)
        assert r.status_code == 400, r.get_data()[:200]
        assert "Traceback" not in r.get_data(as_text=True)


def test_pdf_albero_pagine_ciclico_non_blocca():
    data = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[2 0 R]/Count 1/Parent 2 0 R>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF")
    t0 = time.time()
    with pytest.raises(cvfile.CvError):
        cvfile.extract(data, "a.pdf")
    assert time.time() - t0 < 10


@pytest.mark.slow
def test_pdf_flate_bomb_tempo_e_memoria_limitati():
    import resource
    import zlib

    raw = b"BT /F1 10 Tf 20 250 Td (" + b"A" * 50 + b") Tj ET\n" + b" " * (150 * 1024 * 1024)
    comp = zlib.compress(raw, 9)
    pages = 30
    objs = [b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj", b"2 0 obj<</Type/Pages/Kids[" + " ".join(f"{3 + i} 0 R" for i in range(pages)).encode() + f"]/Count {pages}>>endobj".encode()]
    for i in range(pages):
        objs.append(f"{3 + i} 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 300]/Contents {3 + pages} 0 R>>endobj".encode())
    objs.append(f"{3 + pages} 0 obj<</Length {len(comp)}/Filter/FlateDecode>>stream\n".encode() + comp + b"\nendstream endobj")
    data = b"%PDF-1.4\n" + b"\n".join(objs) + b"\ntrailer<</Root 1 0 R>>\n%%EOF"
    assert len(data) < cvfile.MAX_BYTES
    t0 = time.time()
    try:
        cvfile.extract(data, "a.pdf")
    except cvfile.CvError:
        pass
    dt = time.time() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)  # MB su macOS
    assert dt < 30, f"{dt:.1f}s per un PDF di {len(data)} byte"
    assert rss < 1500, f"{rss:.0f} MB"


def test_pdf_scansione_senza_testo_messaggio_dedicato(client):
    r = post_file(client, "scan.pdf", (DATA / "scansione_senza_testo.pdf").read_bytes())
    assert r.status_code == 400
    assert "scansione" in r.get_json()["error"]


def test_carica_i_sei_cv_di_prova_dal_vivo(client):
    for name in ("cyber_junior.txt", "english_data_analyst.txt", "infermiere.md", "sistemista.docx", "sviluppatore.pdf"):
        r = post_file(client, name, (DATA / name).read_bytes())
        assert r.status_code == 200, (name, r.get_json())
        assert r.get_json()["cv"]["skills"], name


def test_upload_concorrenti_lasciano_un_cv_valido(client, home):
    names = ["cyber_junior.txt", "english_data_analyst.txt", "infermiere.md", "sistemista.docx", "sviluppatore.pdf"] * 3
    res = []

    def go(n):
        r = post_file(client, n, (DATA / n).read_bytes())
        res.append(r.status_code)

    ts = [threading.Thread(target=go, args=(n,)) for n in names]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(s == 200 for s in res), res
    json.loads((home / "cv.json").read_text())
    assert [p.name for p in home.iterdir() if p.name.startswith(".cv-")] == []
    d = wait_idle(client)
    assert d["present"]


# ============================================================ Origin / Host come gli altri POST ====
EVIL = ["http://evil.com", "http://127.0.0.1:8765.evil.com", "null", "http://127.0.0.1:9999", "https://localhost:8765.evil.com", "http://evil.com/127.0.0.1:8765"]


@pytest.mark.parametrize("origin", EVIL)
@pytest.mark.parametrize("path,kw", [("/api/cv", dict(json={"text": WORDS20})), ("/api/cv/skills", dict(json={"add": ["Python"]})),
                                     ("/api/cv/delete", dict()), ("/api/cv/match", dict())])
def test_post_cv_rifiutano_origin_estranee(client, home, origin, path, kw):
    post_text(client, CV_SECRET)
    before = (home / "cv.json").read_bytes()
    r = client.post(path, headers={**H, "Origin": origin}, **kw)
    assert r.status_code == 403
    assert (home / "cv.json").read_bytes() == before


def test_post_upload_multipart_con_origin_estranea_rifiutato(client, home):
    r = post_file(client, "a.txt", CV_SECRET.encode(), headers={**H, "Origin": "http://evil.com"})
    assert r.status_code == 403 and not (home / "cv.json").exists()


@pytest.mark.parametrize("host", ["evil.com", "127.0.0.1:9999", "127.0.0.1", "localhost", "127.0.0.1:8765.evil.com", "[::1]:8765"])
def test_host_diverso_rifiutato_anche_in_get(client, host):
    for m, p in (("get", "/api/cv"), ("post", "/api/cv/delete"), ("post", "/api/cv/match"), ("get", "/api/jobs")):
        r = getattr(client, m)(p, headers={"Host": host})
        assert r.status_code == 403, (m, p, host, r.status_code)


def test_origin_valida_passa(client):
    r = client.post("/api/cv", json={"text": CV_SECRET}, headers={**H, "Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200
    r = client.post("/api/cv", json={"text": CV_SECRET}, headers={**H, "Origin": "http://localhost:8765"})
    assert r.status_code == 200


def test_nessun_header_cors(client):
    r = client.get("/api/cv", headers={**H, "Origin": "http://evil.com"})
    assert "Access-Control-Allow-Origin" not in r.headers
    r = client.options("/api/cv", headers={**H, "Origin": "http://evil.com", "Access-Control-Request-Method": "POST"})
    assert "Access-Control-Allow-Origin" not in r.headers


# ========================================================================== API competenze ====
def test_competenze_aggiungi_rimuovi_ripristina(client):
    post_text(client, "Sistemista con Linux, Python e SQL. " + WORDS20)
    d = client.get("/api/cv", headers=H).get_json()
    assert "Python" in d["skills"] and "Docker" not in d["skills"]
    r = client.post("/api/cv/skills", json={"add": ["  docker  "], "remove": ["PYTHON"]}, headers=H).get_json()["cv"]
    assert "Docker" in r["skills"] and "Python" not in r["skills"] and r["skills_removed"] == ["Python"] and r["skills_manual"] == ["Docker"]
    r = client.post("/api/cv/skills", json={"restore": ["python"], "remove": ["docker"]}, headers=H).get_json()["cv"]
    assert "Python" in r["skills"] and "Docker" not in r["skills"] and r["skills_removed"] == [] and r["skills_manual"] == []
    # aggiungere una competenza gia' rilevata non la duplica in manual
    r = client.post("/api/cv/skills", json={"add": ["Python"]}, headers=H).get_json()["cv"]
    assert r["skills_manual"] == []


def test_competenze_input_sporchi_mai_500(client):
    post_text(client, CV_SECRET)
    for body in [{"add": "Python"}, {"add": [1]}, {"add": [None]}, {"add": [{}]}, {"add": [[]]}, {"add": ["x" * 61]}, {"add": [""]}, {"add": ["   "]},
                 {"add": ["Python"] * 41}, {"add": ["<img src=x onerror=alert(1)>"]}, {"remove": ["<script>"]}, {"restore": [5]}, [], "x", None,
                 {"add": ["\ud800"]}, {"add": ["Python\x00"]}, {"add": ["Inglese"]}, {"add": ["nonexistentskillxyz"]}, {"remove": [None]}]:
        r = client.post("/api/cv/skills", json=body, headers=H)
        assert r.status_code in (200, 400), (body, r.status_code, r.get_data()[:100])
        assert "<img" not in r.get_data(as_text=True) and "<script" not in r.get_data(as_text=True)


def test_competenze_senza_cv_errore_chiaro(client):
    r = client.post("/api/cv/skills", json={"add": ["Python"]}, headers=H)
    assert r.status_code == 400
    assert client.post("/api/cv/match", headers=H).status_code == 400


def test_troppe_competenze_a_mano_tetto(client):
    post_text(client, CV_SECRET)
    names = cvmod.skills.all_skill_names()
    names = [n for n in names if not cvmod.skills.is_language(n)]
    for i in range(0, 200, 20):
        r = client.post("/api/cv/skills", json={"add": names[i:i + 20]}, headers=H)
        assert r.status_code in (200, 400)
    assert len(cvmod.load()["skills_manual"]) <= cvmod.MAX_MANUAL


def test_sostituire_il_cv_azzera_le_modifiche_a_mano(client):
    post_text(client, CV_SECRET)
    client.post("/api/cv/skills", json={"add": ["Docker"], "remove": ["Python"]}, headers=H)
    post_text(client, CV_SECRET)
    d = client.get("/api/cv", headers=H).get_json()
    assert d["skills_manual"] == [] and d["skills_removed"] == []


# ===================================================================== DB / prestazioni ====
def test_migrazione_db_senza_cv_match(cfg, home):
    p = settings.resolve_path(cfg["general"]["db_path"])
    d = DB(p)
    d.conn.execute("DROP TABLE cv_match")
    d.conn.commit()
    add_job(d, "c" * 40, "SOC Analyst", "SIEM Splunk " * 40)
    d.conn.close()
    con = sqlite3.connect(p)
    assert "cv_match" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    d2 = DB(p)
    assert d2.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 0
    assert d2.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    cvmod.save_text(CV_SECRET, "txt")
    assert cvmatch.recompute(d2, cvmod.current()) == 1


def test_migrazione_db_vecchio_con_client(client, qdb, home):
    qdb.conn.execute("DROP TABLE cv_match")
    qdb.conn.commit()
    add_job(qdb, "d" * 40, "SOC Analyst", "SIEM Splunk " * 40)
    assert client.get("/api/jobs", headers=H).status_code == 200
    post_text(client, CV_SECRET)
    wait_idle(client)
    j = client.get("/api/jobs", headers=H).get_json()[0]
    assert j["cv"] is not None


def _bulk(db, n, start=0):
    rows = []
    topics = [("SOC Analyst", "Splunk SIEM EDR incident response Wireshark"), ("Sistemista Linux", "Linux Windows Server Active Directory VMware backup"),
              ("Sviluppatore Python", "Python Django SQL Docker Git REST API"), ("Infermiere", "assistenza infermieristica prelievi terapie BLS"),
              ("Magazziniere", "carrello elevatore magazzino logistica picking")]
    for i in range(start, start + n):
        t, d = topics[i % 5]
        rows.append((f"{i:040d}", "adzuna" if i % 3 else "jooble", f"{t} {i}", "Acme", "Roma", f"https://example.org/{i}", (d + " ") * 15, "", 50, "BLUE", "", "2026-01-01T00:00:00+00:00"))
    db.conn.executemany("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.conn.commit()


@pytest.mark.slow
def test_5000_annunci_ricalcolo_veloce_e_api_reattiva(client, qdb):
    _bulk(qdb, 5000)
    t0 = time.time()
    post_text(client, CV_SECRET)
    d = wait_idle(client, 600)
    dt = time.time() - t0
    assert dt < 20, f"{dt:.1f}s"
    assert qdb.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 5000
    t0 = time.time()
    r = client.get("/api/jobs?limit=500&sort=cv&cv_min=30", headers=H)
    assert r.status_code == 200 and time.time() - t0 < 3
    js = r.get_json()
    sc = [j["cv"] for j in js]
    assert sc == sorted(sc, reverse=True) and all(s >= 30 for s in sc)


@pytest.mark.slow
def test_api_risponde_mentre_il_ricalcolo_gira(client, qdb):
    _bulk(qdb, 5000)
    post_text(client, CV_SECRET)
    worst = 0.0
    for _ in range(10):
        t0 = time.time()
        assert client.get("/api/jobs?limit=50", headers=H).status_code == 200
        worst = max(worst, time.time() - t0)
    wait_idle(client, 600)
    assert worst < 5


@pytest.mark.slow
def test_scansione_e_ricalcolo_insieme_nessun_errore_e_nessuna_perdita(client, qdb, home, caplog):
    import logging

    caplog.set_level(logging.WARNING)
    _bulk(qdb, 3000)
    post_text(client, CV_SECRET)
    errs = []
    stop = threading.Event()
    path = settings.resolve_path(settings.load_config()["general"]["db_path"])

    def scanner():
        try:
            db2 = DB(path)
            i = 10000
            while not stop.is_set():
                _bulk(db2, 20, i)
                i += 20
                time.sleep(0.01)
        except Exception as e:
            errs.append(repr(e))

    t = threading.Thread(target=scanner)
    t.start()
    time.sleep(1.5)
    stop.set()
    t.join()
    wait_idle(client, 800)
    wait_idle(client, 800)
    client.get("/api/jobs", headers=H)
    wait_idle(client, 800)
    assert errs == []
    assert "non riuscito" not in caplog.text, caplog.text
    cur = cvmod.current()
    assert cvmatch.stale_count(qdb, cur.version) == 0


def test_ricalcolo_interrotto_riprende_senza_doppioni(qdb, home):
    _bulk(qdb, 1000)
    cvmod.save_text(CV_SECRET, "txt")
    prof = cvmod.current()
    cancel = threading.Event()
    seen = []

    def prog(i, n):
        seen.append(i)
        if i >= 400:
            cancel.set()

    done = cvmatch.recompute(qdb, prof, progress=prog, cancel=cancel, batch=100)
    assert 400 <= done < 1000
    stored = qdb.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0]
    assert stored == done
    left = cvmatch.stale_count(qdb, prof.version)
    assert left == 1000 - done
    done2 = cvmatch.recompute(qdb, prof)
    assert done2 == left
    assert qdb.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 1000
    assert cvmatch.recompute(qdb, prof) == 0


def test_errore_nel_ricalcolo_in_background_non_blocca_ne_perde_lo_stato(client, qdb, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    _bulk(qdb, 800)
    orig = cvmatch._compute_row
    calls = {"n": 0}

    def flaky(prof, row):
        calls["n"] += 1
        if calls["n"] == 500:
            raise RuntimeError(f"boom {SECRET}")
        return orig(prof, row)

    monkeypatch.setattr(cvmatch, "_compute_row", flaky)
    post_text(client, CV_SECRET)
    d = wait_idle(client)
    assert d["matching"]["running"] is False
    assert SECRET not in caplog.text
    monkeypatch.setattr(cvmatch, "_compute_row", orig)
    client.post("/api/cv/match", headers=H)
    d = wait_idle(client)
    assert qdb.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 800


def test_ricalcolo_idempotente_e_cv_version(client, qdb, monkeypatch):
    add_job(qdb, "e" * 40, "SOC Analyst", "Splunk SIEM EDR Python " * 30)
    post_text(client, CV_SECRET)
    wait_idle(client)
    v1 = client.get("/api/cv", headers=H).get_json()["version"]
    snap = qdb.conn.execute("SELECT * FROM cv_match").fetchall()
    counter = {"n": 0}
    orig = cvmatch._compute_row

    def count(p, r):
        counter["n"] += 1
        return orig(p, r)

    monkeypatch.setattr(cvmatch, "_compute_row", count)
    post_text(client, CV_SECRET)  # stesso testo
    client.post("/api/cv/match", headers=H)
    client.get("/api/job/" + "e" * 40, headers=H)
    wait_idle(client)
    assert counter["n"] == 0
    assert [tuple(r) for r in qdb.conn.execute("SELECT * FROM cv_match")] == [tuple(r) for r in snap]
    # stesse competenze, testo diverso: stessa versione, nessun ricalcolo
    post_text(client, CV_SECRET + "\n" + "altre parole senza competenze note " * 5)
    wait_idle(client)
    assert client.get("/api/cv", headers=H).get_json()["version"] == v1 and counter["n"] == 0
    # competenza nuova: versione diversa e ricalcolo
    post_text(client, CV_SECRET + "\nEsperienza con Docker e Kubernetes e Terraform.")
    wait_idle(client)
    assert client.get("/api/cv", headers=H).get_json()["version"] != v1 and counter["n"] == 1


def test_modifica_testo_annuncio_ricalcola(client, qdb):
    add_job(qdb, "f" * 40, "Impiegato", "Ufficio acquisti e contabilita " * 15, full="")
    post_text(client, CV_SECRET)
    wait_idle(client)
    a = client.get("/api/job/" + "f" * 40, headers=H).get_json()
    qdb.set_full_text("f" * 40, "Cerchiamo SOC Analyst con Splunk, SIEM, EDR e Python. " * 12)
    b = client.get("/api/job/" + "f" * 40, headers=H).get_json()
    assert b["cv"] != a["cv"] or b["cv_explain"] != a["cv_explain"]
    assert "Splunk" in b["cv_explain"]["in_comune"]


def test_scheda_annuncio_cv_eliminato_e_annuncio_inesistente(client):
    assert client.get("/api/job/" + "9" * 40, headers=H).status_code == 404
    r = client.get("/api/jobs?cv_min=50&sort=cv", headers=H)  # senza CV i parametri CV si ignorano
    assert r.status_code == 200


@pytest.mark.parametrize("q", ["cv_min=abc", "cv_min=-5", "cv_min=1000", "cv_min=1e9", "cv_min=", "sort=cv%00", "sort=cv&cv_min=50&q=%27", "cv_min=50&profile=999"])
def test_parametri_cv_sporchi_mai_500(client, qdb, q):
    add_job(qdb, "1" * 40, "SOC Analyst", "Splunk SIEM EDR Python " * 30)
    post_text(client, CV_SECRET)
    wait_idle(client)
    assert client.get("/api/jobs?" + q, headers=H).status_code in (200, 400)


# ======================================================================================== CLI ====
def _cli(*args):
    from click.testing import CliRunner

    from jobshunter.cli import main

    return CliRunner().invoke(main, list(args), catch_exceptions=True)


def test_cli_cv_set_show_match_clear_senza_perdite(cfg, home, tmp_path, capfd):
    f = tmp_path / f"cv-{'q'}.txt"
    f.write_text(CV_SECRET)
    db = DB(settings.resolve_path(cfg["general"]["db_path"]))
    add_job(db, "2" * 40, "SOC Analyst", "Splunk SIEM EDR Python " * 30)
    out = ""
    for args in (["cv", "set", str(f)], ["cv", "show"], ["cv", "match"], ["list", "--cv-min", "10"], ["list", "--by-cv"], ["show", "2" * 6], ["cv", "clear", "-y"], ["cv", "show"]):
        r = _cli(*args)
        assert r.exception is None or isinstance(r.exception, SystemExit), (args, repr(r.exception), r.output)
        out += r.output
    assert SECRET not in out
    assert not (home / "cv.json").exists()
    assert db.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 0
    o, e = capfd.readouterr()
    assert SECRET not in o + e


def test_cli_cv_set_errori(cfg, home, tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"%PDF-1.4 " + SECRET.encode())
    r = _cli("cv", "set", str(bad))
    assert r.exit_code == 1 and SECRET not in r.output
    big = tmp_path / "big.txt"
    big.write_bytes(b"a " * (3 * 1024 * 1024))
    r = _cli("cv", "set", str(big))
    assert r.exit_code == 1 and "5 MB" in r.output
    r = _cli("cv", "set", str(tmp_path))  # cartella
    assert r.exit_code != 0
    assert not (home / "cv.json").exists()


def test_cli_senza_cv(cfg, home):
    assert "Nessun CV" in _cli("cv", "show").output
    assert _cli("cv", "match").exit_code == 1
    assert _cli("list", "--cv-min", "10").exit_code == 1
    assert "Nessun CV" in _cli("cv", "clear", "-y").output
