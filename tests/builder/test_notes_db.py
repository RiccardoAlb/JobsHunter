"""Fase 10, blocco note: database, modello di lettera, nomi di file e formato Markdown (home temporanea, nessuna rete)."""
from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from jobshunter import notes as N
from jobshunter import settings
from jobshunter.db import DB

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def db(home):
    cfg = settings.load_config(create_if_missing=True)
    return DB(settings.resolve_path(cfg["general"]["db_path"]))


def add_job(db, uid="job1", title="Analista SOC", company="Acme Srl", **extra):
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, score, category, matched, first_seen) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (uid, "adzuna", title, company, "Milano", "https://example.org/" + uid, "descrizione", 50, "BLUE", "", "2026-01-01T00:00:00+00:00"))
    for k, v in extra.items():
        db.conn.execute(f"UPDATE jobs SET {k}=? WHERE uid=?", (v, uid))
    db.conn.commit()
    return uid


# ------------------------------------------------------------------ migrazione ----
def test_migrazione_da_db_vecchio_senza_perdere_nulla(tmp_path):
    p = tmp_path / "vecchio.db"
    con = sqlite3.connect(p)
    con.executescript("CREATE TABLE jobs (uid TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT, url TEXT, description TEXT, posted_at TEXT, remote INTEGER,"
                      " score INTEGER, category TEXT, matched TEXT, status TEXT DEFAULT 'new', notified INTEGER DEFAULT 0, first_seen TEXT);"
                      "INSERT INTO jobs (uid, title, company) VALUES ('a1', 'Vecchio', 'Acme');"
                      "CREATE TABLE applications (id INTEGER PRIMARY KEY AUTOINCREMENT, job_uid TEXT, company TEXT NOT NULL, role TEXT NOT NULL, notes TEXT DEFAULT '');"
                      "INSERT INTO applications (job_uid, company, role, notes) VALUES ('a1', 'Acme', 'Dev', 'il mio campo note');")
    con.commit()
    con.close()
    d = DB(p)
    assert d.conn.execute("SELECT name FROM sqlite_master WHERE name='notes'").fetchone()
    assert {r[1] for r in d.conn.execute("PRAGMA index_list(notes)")} >= {"idx_notes_job", "idx_notes_app"}
    assert d.conn.execute("SELECT title FROM jobs WHERE uid='a1'").fetchone()[0] == "Vecchio"
    assert d.conn.execute("SELECT notes FROM applications").fetchone()[0] == "il mio campo note"  # il vecchio campo Note della candidatura non cambia
    assert d.add_note(title="x") == 1
    DB(p)  # seconda apertura senza errori


# ---------------------------------------------------------------------- CRUD ----
def test_crud_e_campi(db):
    nid = db.add_note(kind="note", title="  Appunto \n con a capo ", body="testo\r\nsu due righe")
    r = db.get_note(nid)
    assert (r["kind"], r["title"], r["body"]) == ("note", "Appunto con a capo", "testo\nsu due righe")
    assert r["job_uid"] is None and r["app_id"] is None and r["created"] and r["created"] == r["updated"] and r["created"].endswith("+00:00")
    before = r["updated"]
    r2 = db.update_note(nid, body="nuovo")
    assert r2["body"] == "nuovo" and r2["title"] == "Appunto con a capo" and r2["updated"] >= before
    assert db.update_note(nid, title="Altro")["title"] == "Altro"
    assert db.update_note(999) is None
    assert db.update_note(nid)["title"] == "Altro"  # nessun campo: non cambia nulla
    assert db.delete_note(nid) is True and db.get_note(nid) is None and db.delete_note(nid) is False


def test_limiti_mai_troncare_in_silenzio(db):
    db.add_note(title="t" * 200, body="b" * 100_000)
    with pytest.raises(N.NoteError, match="titolo troppo lungo"):
        db.add_note(title="t" * 201)
    with pytest.raises(N.NoteError, match="testo troppo lungo"):
        db.add_note(body="b" * 100_001)
    nid = db.add_note(title="ok")
    with pytest.raises(N.NoteError):
        db.update_note(nid, body="b" * 100_001)
    assert db.get_note(nid)["body"] == ""  # l'aggiornamento rifiutato non ha cambiato nulla
    for bad in ("altro", "", None):
        with pytest.raises(N.NoteError, match="tipo di nota"):
            db.add_note(kind=bad)
    with pytest.raises(N.NoteError):
        db.add_note(title=5)
    assert db.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 2


def test_testo_con_apostrofi_percento_emoji_e_unicode_resta_identico(db):
    body = "L'azienda {azienda} 100% ok \U0001F600 \u00e8 \"x\" ; DROP TABLE notes; --\n\ttab"
    nid = db.add_note(title="it's 50% \U0001F600", body=body)
    assert db.get_note(nid)["body"] == body and db.get_note(nid)["title"] == "it's 50% \U0001F600"


# ------------------------------------------------------------------- ricerca ----
def test_ricerca_senza_maiuscole_e_con_caratteri_speciali(db):
    db.add_note(title="Colloquio con l'Azienda", body="Chiamare il 100% dei contatti", company="Città", role="Dev_Ops")
    db.add_note(title="Altro", body="niente", company="Beta", role="DevXOps")
    db.add_note(title="Perche' si", body="\u00c8 IMPORTANTE", company="", role="")
    q = lambda t: [r["title"] for r in db.list_notes(q=t)]
    assert q("colloquio") == ["Colloquio con l'Azienda"] and q("COLLOQUIO") == ["Colloquio con l'Azienda"]
    assert q("l'azienda") == ["Colloquio con l'Azienda"]  # apostrofo
    assert q("100%") == ["Colloquio con l'Azienda"] and q("%") == ["Colloquio con l'Azienda"]  # % e' un carattere, non un jolly
    assert q("dev_ops") == ["Colloquio con l'Azienda"] and q("_") == ["Colloquio con l'Azienda"]  # _ non e' un jolly
    assert q("\u00e8 importante") == ["Perche' si"] and q("\u00c8 importante") == ["Perche' si"]  # accenti e maiuscole non ASCII
    assert q("beta") == ["Altro"] and q("devxops") == ["Altro"]  # azienda e ruolo
    assert q("\\") == [] and q("zzz") == [] and len(db.list_notes(q="   ")) == 3 and len(db.list_notes(q="")) == 3


def test_filtri_ordine_e_conteggi(db):
    job = add_job(db)
    a = db.add_note(kind="note", title="generale")
    b = db.add_note(kind="letter", title="lettera", job_uid=job)
    c = db.add_note(kind="note", title="dell'annuncio", job_uid=job)
    db.update_note(a, body="ritoccata per ultima")
    assert [r["id"] for r in db.list_notes()] == [a, c, b]  # prima la modificata piu' di recente
    assert [r["id"] for r in db.list_notes(general=True)] == [a]
    assert {r["id"] for r in db.list_notes(job_uid=job)} == {b, c}
    assert [r["id"] for r in db.list_notes(kind="letter")] == [b] and len(db.list_notes(kind="boh")) == 3
    assert db.note_counts() == {"total": 3, "letters": 1, "notes": 2, "general": 1}
    assert db.note_counts_by("job") == {job: 2}


# --------------------------------------------------- le note seguono la candidatura ----
def test_le_note_dell_annuncio_seguono_la_candidatura_creata_da_add_application(db):
    job = add_job(db)
    other = add_job(db, "job2", "Altro")
    n1 = db.add_note(title="uno", job_uid=job)
    n2 = db.add_note(kind="letter", title="due", job_uid=job)
    n3 = db.add_note(title="di un altro annuncio", job_uid=other)
    n4 = db.add_note(title="generale")
    aid = db.add_application(company="Acme Srl", role="Analista SOC", job_uid=job)
    assert [db.get_note(n)["app_id"] for n in (n1, n2)] == [aid, aid]
    assert db.get_note(n3)["app_id"] is None and db.get_note(n4)["app_id"] is None
    assert db.get_note(n1)["job_uid"] == job
    assert db.list_applications()[0]["note_count"] == 2


def test_le_note_seguono_ensure_application_cioe_segna_candidato(db):
    job = add_job(db)
    n = db.add_note(title="prima di candidarmi", job_uid=job)
    db.set_status(job, "applied")
    app_id = db.conn.execute("SELECT id FROM applications WHERE job_uid=?", (job,)).fetchone()[0]
    assert db.get_note(n)["app_id"] == app_id
    assert db.ensure_application(job) is None  # una sola candidatura per annuncio: le note non si ricollegano di nuovo


def test_candidatura_manuale_senza_annuncio_non_prende_note(db):
    job = add_job(db)
    n = db.add_note(title="x", job_uid=job)
    db.add_application(company="Altra", role="Ruolo")
    assert db.get_note(n)["app_id"] is None


def test_nota_creata_dentro_la_candidatura_prende_annuncio_azienda_e_ruolo(db):
    job = add_job(db)
    aid = db.add_application(company="Acme Srl", role="Analista SOC", job_uid=job)
    n = db.get_note(db.add_note(title="dentro", app_id=aid))
    assert (n["app_id"], n["job_uid"], n["company"], n["role"]) == (aid, job, "Acme Srl", "Analista SOC")
    manual = db.add_application(company="Manuale SpA", role="Tester")
    m = db.get_note(db.add_note(title="m", app_id=manual))
    assert (m["app_id"], m["job_uid"], m["company"], m["role"]) == (manual, None, "Manuale SpA", "Tester")
    with pytest.raises(LookupError):
        db.add_note(title="x", app_id=9999)


def test_nota_nuova_per_un_annuncio_gia_candidato_si_lega_alla_candidatura(db):
    job = add_job(db)
    aid = db.add_application(company="Acme Srl", role="Analista SOC", job_uid=job)
    assert db.get_note(db.add_note(title="dopo", job_uid=job))["app_id"] == aid


def test_azienda_e_ruolo_dall_annuncio_e_copiati_alla_creazione(db):
    job = add_job(db, title="Dev", company="Beta SpA")
    n = db.add_note(title="x", job_uid=job)
    assert (db.get_note(n)["company"], db.get_note(n)["role"]) == ("Beta SpA", "Dev")
    db.conn.execute("UPDATE jobs SET company='Cambiata' WHERE uid=?", (job,))
    assert db.get_note(n)["company"] == "Beta SpA"  # e' una copia: il contesto non cambia dopo


def test_cancellare_la_candidatura_non_cancella_le_note(db):
    job = add_job(db)
    n = db.add_note(title="resta", job_uid=job)
    aid = db.add_application(company="Acme Srl", role="Analista SOC", job_uid=job)
    inside = db.add_note(title="dentro", app_id=aid)
    assert db.delete_application(aid) is True
    for nid in (n, inside):
        r = db.get_note(nid)
        assert r is not None and r["app_id"] is None and r["job_uid"] == job and r["company"] == "Acme Srl" and r["role"] == "Analista SOC"


# ----------------------------------------------- nessuna pulizia tocca le note ----
def test_annuncio_chiuso_o_rimosso_la_nota_resta_con_il_contesto(db):
    job = add_job(db)
    n = db.add_note(title="x", job_uid=job)
    assert db.job_is_open(job) is True
    db.set_avail(job, "closed", None, "chiuso dalla fonte")
    assert db.job_is_open(job) is False and db.get_note(n)["company"] == "Acme Srl"
    db.conn.execute("DELETE FROM jobs WHERE uid=?", (job,))  # anche se l'annuncio sparisce
    db.conn.commit()
    r = db.get_note(n)
    assert r["job_uid"] == job and r["company"] == "Acme Srl" and r["role"] == "Analista SOC" and db.job_is_open(job) is False
    assert db.job_is_open(None) is None and db.job_is_open("non-esiste") is False


def test_le_pulizie_e_i_ricalcoli_non_toccano_le_note(db):
    from jobshunter.rescore import rescore

    job = add_job(db)
    n = db.add_note(title="x", job_uid=job)
    g = db.add_note(title="generale")
    db.drop_orphans()
    rescore(db, settings.load_config())
    db.snapshot("prova")
    assert {r["id"] for r in db.list_notes()} == {n, g}


def test_nel_codice_le_note_si_cancellano_solo_con_delete_note():
    hits = []
    for p in (ROOT / "jobshunter").rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"DELETE\s+FROM\s+notes", line, re.I):
                hits.append((p.name, i))
            if re.search(r"DROP\s+TABLE|DELETE\s+FROM\s+jobs\b", line, re.I):
                hits.append((p.name, i, "annunci/tabelle"))
    assert hits == [("db.py", hits[0][1])], hits  # una sola cancellazione di note: delete_note
    src = (ROOT / "jobshunter" / "db.py").read_text(encoding="utf-8")
    body = src[src.index("def delete_note"):src.index("def note_counts")]
    assert "DELETE FROM notes WHERE id=?" in body


def test_il_backup_contiene_le_note(db):
    job = add_job(db)
    n = db.add_note(kind="letter", title="in backup", body="testo", job_uid=job)
    copia = db.snapshot("note")
    assert copia
    r = DB(copia).get_note(n)
    assert r["title"] == "in backup" and r["body"] == "testo" and r["job_uid"] == job


# ------------------------------------------------------------ modello di lettera ----
DATA = {"company": "Acme Srl", "role": "Analista SOC", "location": "Milano", "url": "https://example.org/a?b=1&c=2"}
TODAY = date(2026, 11, 1)


@pytest.mark.parametrize("name,expected", [
    ("azienda", "Acme Srl"), ("company", "Acme Srl"), ("ruolo", "Analista SOC"), ("role", "Analista SOC"),
    ("sede", "Milano"), ("location", "Milano"), ("data", "01/11/2026"), ("date", "01/11/2026"),
    ("link", "https://example.org/a?b=1&c=2"), ("url", "https://example.org/a?b=1&c=2"),
])
def test_segnaposto_italiani_e_inglesi(name, expected):
    assert N.render_template("[{" + name + "}]", DATA, TODAY) == f"[{expected}]"


def test_segnaposto_sconosciuti_maiuscoli_o_incompleti_restano_come_sono():
    t = "{altro} {Azienda} {AZIENDA} {azienda {ruolo} { azienda} {{azienda}} {}"
    out = N.render_template(t, DATA, TODAY)
    assert out == "{altro} {Azienda} {AZIENDA} {azienda Analista SOC { azienda} {Acme Srl} {}"


def test_valori_speciali_si_inseriscono_senza_interpretarli():
    data = {"company": "A{b}c %s %(x)d {ruolo} \U0001F600", "role": "R\\n {data}", "location": "{link}", "url": "%"}
    out = N.render_template("{azienda}|{ruolo}|{sede}|{link}", data, TODAY)
    assert out == "A{b}c %s %(x)d {ruolo} \U0001F600|R\\n {data}|{link}|%"  # niente doppia sostituzione, niente str.format
    assert N.render_template("100% {azienda} {0} {x!r}", DATA, TODAY) == "100% Acme Srl {0} {x!r}"


def test_dati_mancanti_il_segnaposto_resta_visibile():
    assert N.render_template("{azienda}, {ruolo}, {sede}, {link}", {"company": "Acme"}, TODAY) == "Acme, {ruolo}, {sede}, {link}"
    assert N.render_template("{azienda}", {"company": "  "}, TODAY) == "{azienda}"
    assert N.render_template("{data}", {}, TODAY) == "01/11/2026"
    assert N.render_template("", DATA) == ""
    assert re.fullmatch(r"\d\d/\d\d/\d{4}", N.render_template("{data}", {}))


def test_modello_predefinito_e_titolo_della_lettera():
    out = N.render_template(N.DEFAULT_TEMPLATE, DATA, TODAY)
    assert "Acme Srl" in out and "Analista SOC" in out and "01/11/2026" in out and "https://example.org/a?b=1&c=2" in out
    assert "{azienda}" not in out and "—" not in N.DEFAULT_TEMPLATE and "–" not in N.DEFAULT_TEMPLATE
    assert N.letter_title("Acme", "Dev") == "Lettera per Acme, Dev" and N.letter_title("Acme", "") == "Lettera per Acme"
    assert N.letter_title("", "Dev") == "Lettera per Dev" and N.letter_title("", " ") == "Lettera di presentazione"
    assert len(N.DEFAULT_TEMPLATE) < N.MAX_TEMPLATE


def test_make_letter_dal_modello_dell_utente_e_ripristino(db, home):
    cfg = settings.load_config()
    job = add_job(db)
    nid = N.make_letter(cfg, db, job_uid=job)
    r = db.get_note(nid)
    assert r["kind"] == "letter" and r["title"] == "Lettera per Acme Srl, Analista SOC" and "Acme Srl" in r["body"] and "Milano" in r["body"]
    cfg_file = Path(cfg["_config_path"])
    settings.save_overrides(cfg_file, {N.TEMPLATE_KEY: "Per {company}: {role} ({date})"})
    cfg = settings.load_config()
    assert N.get_template(cfg) == "Per {company}: {role} ({date})"
    assert db.get_note(N.make_letter(cfg, db, job_uid=job))["body"].startswith("Per Acme Srl: Analista SOC (")
    settings.save_overrides(cfg_file, {}, [N.TEMPLATE_KEY])
    assert N.get_template(settings.load_config()) == N.DEFAULT_TEMPLATE
    settings.save_overrides(cfg_file, {N.TEMPLATE_KEY: "   "})
    assert N.get_template(settings.load_config()) == N.DEFAULT_TEMPLATE  # un modello vuoto vale il predefinito
    assert (cfg_file.with_name("settings.json")).exists()
    with pytest.raises(N.NoteError):
        N.clean_template("x" * 20_001)
    assert N.clean_template("a\r\nb") == "a\nb"


def test_lettera_da_candidatura_usa_i_dati_della_candidatura(db, home):
    cfg = settings.load_config()
    aid = db.add_application(company="Manuale SpA", role="Tester", location="Roma", url="https://example.org/m")
    r = db.get_note(N.make_letter(cfg, db, app_id=aid))
    assert r["app_id"] == aid and "Manuale SpA" in r["body"] and "Roma" in r["body"] and r["title"] == "Lettera per Manuale SpA, Tester"


# ------------------------------------------------------------------ nomi di file ----
@pytest.mark.parametrize("title,expected", [
    ("Lettera per Acme, Dev", "Lettera per Acme, Dev"),
    ("../../etc/passwd", "etc-passwd"),
    ("a/b\\c:d*e?f\"g<h>i|j", "a-b-c-d-e-f-g-h-i-j"),
    ("riga1\nriga2\t\x00x", "riga1 riga2 x"),
    ("CON", "_CON"), ("nul", "_nul"), ("COM1", "_COM1"), ("lpt9.txt", "_lpt9.txt"), ("Console", "Console"),
    ("  ..nome..  ", "nome"), ("fine con punto.", "fine con punto"),
    ("", "nota"), ("///", "nota"), ("...", "nota"), (None, "nota"),
    ("\u00e8\u00e0 \U0001F600 ok", "\u00e8\u00e0 \U0001F600 ok"),
])
def test_nome_file_ripulito(title, expected):
    assert N.safe_filename(title) == expected


def test_nome_file_lunghezza_massima_e_mai_percorsi():
    n = N.safe_filename("x" * 500)
    assert len(n) == N.MAX_FILENAME
    for hostile in ("../../x", "a/../b", "..\\..\\x", "/etc/passwd", "C:\\Windows\\x", "~/x", ".hidden", "..", "."):
        out = N.safe_filename(hostile)
        assert not set(out) & set('/\\:*?"<>|\x00') and ".." not in out and not out.startswith(".") and out


def test_scrittura_senza_mai_sovrascrivere(tmp_path):
    f = tmp_path / "Note"
    p1 = N.write_unique(f, "lettera", "uno")
    p2 = N.write_unique(f, "lettera", "due")
    p3 = N.write_unique(f, "lettera", "tre")
    assert [p.name for p in (p1, p2, p3)] == ["lettera.md", "lettera-2.md", "lettera-3.md"]
    assert [p.read_text(encoding="utf-8") for p in (p1, p2, p3)] == ["uno", "due", "tre"]
    (f / "altro.md").write_text("di un altro", encoding="utf-8")
    N.write_unique(f, "altro", "x")
    assert (f / "altro.md").read_text(encoding="utf-8") == "di un altro"  # un file di altri non si tocca


# -------------------------------------------------------------- formato Markdown ----
def test_formato_del_file_markdown():
    note = {"kind": "letter", "title": "Lettera per Acme, Dev", "body": "Gentile team,\n\ntesto.", "company": "Acme", "role": "Dev", "app_id": 3,
            "created": "2026-11-01T10:00:00+00:00", "updated": "2026-11-02T08:30:00+00:00"}
    md = N.to_markdown(note, url="https://example.org/x", applied_at="2026-11-01")
    assert md == ("---\ntitolo: Lettera per Acme, Dev\ntipo: lettera\nazienda: Acme\nruolo: Dev\nannuncio: https://example.org/x\n"
                  "candidatura: inviata il 01/11/2026\ncreata: 2026-11-01\naggiornata: 2026-11-02\n---\n\nGentile team,\n\ntesto.")
    plain = N.to_markdown({"kind": "note", "title": "Appunto", "body": "x\n", "created": "2026-11-01T10:00:00+00:00", "updated": "2026-11-01T10:00:00+00:00"})
    assert plain == "---\ntitolo: Appunto\ntipo: nota\ncreata: 2026-11-01\naggiornata: 2026-11-01\n---\n\nx\n"  # senza azienda, annuncio e candidatura
    assert N.to_markdown({"kind": "note", "title": "", "body": "", "created": "", "updated": ""}).startswith("---\ntitolo: senza titolo\n")


def test_valori_del_blocco_iniziale_su_una_riga_senza_trattini_tripli():
    note = {"kind": "note", "title": "a\nb\r\n---\nc", "body": "---\ncorpo con --- dentro\n", "company": "Ac\nme\u2028---", "role": "R\x00\x1fR",
            "created": "2026-11-01T10:00:00+00:00", "updated": "2026-11-01T10:00:00+00:00"}
    md = N.to_markdown(note, url="https://x.org/a\nb")
    head = md.split("\n---\n", 1)[0]
    assert head.count("\n---") == 0 and head.startswith("---\n")  # nel blocco iniziale nessun "---" nei valori: l'unico di chiusura e' quello che segue
    for line in md.split("\n---\n", 1)[0].splitlines()[1:]:
        assert re.match(r"^[a-z]+: ", line), line
    assert "titolo: a b - c" in md and "azienda: Ac me -" in md and "annuncio: https://x.org/a b" in md
    assert md.endswith("\n---\n\n---\ncorpo con --- dentro\n")  # il testo della nota resta com'e', anche con "---" dentro


def test_ogni_nota_ha_il_proprio_contenuto_nel_database_e_nessun_dato_nei_file_del_progetto():
    sys_path = str(ROOT / "scripts")
    import sys

    sys.path.insert(0, sys_path)
    try:
        import check_publishable as cp
    finally:
        sys.path.pop(0)
    files = [rel for _p, rel in cp.iter_files(ROOT)]
    assert not [f for f in files if "/Note/" in f or f.startswith("Note/") or re.search(r"(^|/)nota?s?[-_ ]", f, re.I)]
    assert not (ROOT / "reports" / "Note").exists() or (ROOT / "reports" / "Note").is_dir()  # i test usano cartelle temporanee, mai quella vera
    assert not [p for p in ROOT.glob("*.md") if p.name not in ("README.md", "README.en.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md")]


def test_B125_la_ricerca_degli_annunci_ignora_le_maiuscole_anche_con_gli_accenti(db):
    add_job(db, "j1", title="Responsabile Qualità", company="ÈTICA Srl")
    assert [r["uid"] for r in db.query(search="qualità")] == ["j1"] and [r["uid"] for r in db.query(search="QUALITÀ")] == ["j1"]
    assert [r["uid"] for r in db.query(search="etica")] == []  # senza accento non e' la stessa parola
    assert [r["uid"] for r in db.query(search="è")] == ["j1"] and [r["uid"] for r in db.query(search="Soc")] == []


# ------------------------------------------------ correzioni B126-B134 (giro del tester) ----
def test_B126_surrogati_rifiutati_con_messaggio_chiaro_e_nessun_temporaneo(db, home):
    for bad in ("\ud800", "a\udfffb"):
        for fn in (N.clean_title, N.clean_body, N.clean_template):
            with pytest.raises(N.NoteError, match="caratteri non validi"):
                fn(bad)
    with pytest.raises(N.NoteError):
        db.add_note(title="\ud800")
    cfg = settings.load_config()
    cfg_file = Path(cfg["_config_path"])
    with pytest.raises(UnicodeEncodeError):
        settings.save_overrides(cfg_file, {N.TEMPLATE_KEY: "a \ud800"})  # anche se un valore cattivo arrivasse fin qui, il temporaneo non resta
    assert not list(cfg_file.parent.glob("settings.json.*.tmp"))


def test_B127_B134_nome_file_in_byte_e_senza_punti_di_fila():
    assert len((N.safe_filename("😀" * 300)).encode("utf-8")) <= N.MAX_FILENAME_BYTES
    assert len((N.safe_filename("日" * 300)).encode("utf-8")) <= N.MAX_FILENAME_BYTES and N.safe_filename("日" * 300) == "日" * 66  # taglio su un confine di carattere
    for t in ("a...b", "x....y", "..a..", "a" + "." * 50 + "b"):
        assert ".." not in N.safe_filename(t)


def test_B129_il_testo_esportato_e_esattamente_quello_della_nota():
    md = N.to_markdown({"kind": "note", "title": "t", "body": "ultima riga", "created": "2026-11-01", "updated": "2026-11-01"})
    assert md.endswith("---\n\nultima riga") and N.to_markdown({"kind": "note", "title": "t", "body": "a\n\n", "created": "", "updated": ""}).endswith("\n\na\n\n")


def test_B130_annuncio_e_candidatura_incoerenti_rifiutati(db):
    add_job(db, "A")
    add_job(db, "B", company="Beta")
    appb = db.add_application(company="Beta", role="RB", job_uid="B")
    with pytest.raises(N.NoteError, match="non sono collegati"):
        db.add_note(title="x", job_uid="A", app_id=appb)
    assert db.get_note(db.add_note(title="ok", job_uid="B", app_id=appb))["job_uid"] == "B"  # coerenti: va bene
    manual = db.add_application(company="Manuale", role="R")
    assert db.get_note(db.add_note(title="m", job_uid="A", app_id=manual))["app_id"] == manual  # candidatura senza annuncio: nessun conflitto


def test_B131_le_note_del_duplicato_nascosto_si_trovano_dal_tenuto_e_contano(db):
    add_job(db, "keep")
    add_job(db, "hid")
    nk = db.add_note(title="sul tenuto", job_uid="keep")
    nh = db.add_note(title="sul nascosto", job_uid="hid")
    db.upsert_dup("keep", "hid", 90, "keep", "hid")
    pid = db.list_dups("pending")[0]["id"]
    assert [r["id"] for r in db.list_notes(job_uid="keep")] == [nk]  # coppia ancora da decidere: nessun legame
    db.set_dup_status(pid, "confirmed")
    assert {r["id"] for r in db.list_notes(job_uid="keep")} == {nk, nh}
    assert db.get_note(nh)["job_uid"] == "hid"  # non si sposta: un annullo non perde nulla
    assert db.note_counts_by("job")["keep"] == 2
    db.set_status("keep", "applied")
    assert db.list_applications()[0]["note_count"] == 1 + 1  # anche quella del nascosto
    app_id = db.list_applications()[0]["id"]
    assert {r["id"] for r in db.list_notes(app_id=app_id)} == {nk, nh}
    db.set_dup_status(pid, "rejected")
    assert [r["id"] for r in db.list_notes(job_uid="keep")] == [nk] and db.note_counts_by("job").get("keep") == 1


# ---------------------------------------------- titolo della lettera e nome file accorciati ----
LONG_ROLE = "Junior Sistemista IT - Infrastrutture, Sicurezza & Assistenza"


def test_titolo_lettera_breve_resta_com_e():
    assert N.letter_title("Pharmaservice", "Sistemista") == "Lettera per Pharmaservice, Sistemista"
    t = "Lettera per " + "A" * 10 + ", " + "r" * 46  # esattamente 70 caratteri
    assert len(t) == 70 and N.letter_title("A" * 10, "r" * 46) == t


def test_titolo_lettera_con_ruolo_lungo_si_accorcia_sull_ultima_parola_intera():
    t = N.letter_title("Pharmaservice", LONG_ROLE)
    assert t == "Lettera per Pharmaservice, Junior Sistemista IT - Infrastrutture…"
    assert len(t) <= 70 and t.endswith("…") and "Sicurezza" not in t and "Infrastrutture…" in t
    assert not t.endswith(",…") and " …" not in t  # niente segni appesi prima dei puntini


def test_titolo_lettera_con_azienda_lunga_e_ruolo_che_non_ci_sta():
    c = "Societa' Italiana Servizi Informatici Integrati e Consulenza Aziendale SpA"
    t = N.letter_title(c, LONG_ROLE)
    assert t.startswith("Lettera per Societa'") and len(t) <= 70 and t.endswith("…") and LONG_ROLE.split()[0] not in t  # il ruolo non c'e' piu' posto per mostrarlo
    t2 = N.letter_title("Azienda Media Srl " + "x" * 30, "Dev")
    assert len(t2) <= 70
    assert N.letter_title(c, "") == N.letter_title(c, None) and N.letter_title(c, "").endswith("…") and len(N.letter_title(c, "")) <= 70


def test_titolo_lettera_solo_ruolo_senza_spazi_o_con_emoji_o_none():
    assert N.letter_title("", LONG_ROLE).startswith("Lettera per Junior Sistemista") and len(N.letter_title("", LONG_ROLE)) <= 70
    t = N.letter_title("Acme", "x" * 400)  # una sola parola enorme: taglio duro
    assert len(t) == 70 and t.endswith("…") and t.startswith("Lettera per Acme, xxx")
    e = N.letter_title("Acme \U0001F600", "\U0001F600" * 100)
    assert len(e) <= 70 and e.endswith("…") and e.startswith("Lettera per Acme \U0001F600, \U0001F600")
    assert N.letter_title(None, None) == "Lettera di presentazione" == N.letter_title("  ", "\n")
    assert N.letter_title("Ac\nme", " Dev  Ops ") == "Lettera per Ac me, Dev Ops"  # a capo e spazi doppi ripuliti (un a capo vale uno spazio)


@pytest.mark.parametrize("c,r", [("A", "b" * 300), ("A" * 300, "b"), ("A" * 40, "b c " * 40), ("Pharmaservice", LONG_ROLE), ("", "x y " * 100), ("Èà \U0001F600", "p " * 99)])
def test_titolo_lettera_mai_oltre_70_mai_vuoto(c, r):
    t = N.letter_title(c, r)
    assert 12 < len(t) <= 70 and t.startswith("Lettera per ") and "\n" not in t and not t.endswith(" ")


def test_titolo_lettera_dal_server_per_api_e_cli(db, home):
    cfg = settings.load_config()
    job = add_job(db, title=LONG_ROLE, company="Pharmaservice")
    r = db.get_note(N.make_letter(cfg, db, job_uid=job))
    assert r["title"] == "Lettera per Pharmaservice, Junior Sistemista IT - Infrastrutture…"
    assert r["role"] == LONG_ROLE and r["company"] == "Pharmaservice"  # il contesto resta intero


@pytest.mark.parametrize("title,expected", [
    ("Lettera per Pharmaservice, " + LONG_ROLE, "Lettera per Pharmaservice, Junior Sistemista IT - Infrastrutture, Sicurezza"),
    ("parola " * 30, ("parola " * 11).strip()),
])
def test_nome_file_tagliato_sull_ultima_parola_intera(title, expected):
    out = N.safe_filename(title)
    assert out == expected and len(out) <= N.MAX_FILENAME
    assert not out.endswith(("&", " ", ".", "-", ",")) and "As" not in out.split()[-1:]  # niente "...Sicurezza & As"


def test_nome_file_parola_unica_lunghissima_taglio_duro_e_byte_utf8():
    assert N.safe_filename("x" * 400) == "x" * N.MAX_FILENAME
    out = N.safe_filename("è" * 300)  # accenti: 2 byte ciascuno, 80 caratteri = 160 byte
    assert out == "è" * 80
    emoji = N.safe_filename("\U0001F600" * 300)
    assert emoji == "\U0001F600" * 50 and len(emoji.encode("utf-8")) == 200
    frase = N.safe_filename("È la vita " * 30)
    assert len(frase) <= 80 and len(frase.encode("utf-8")) <= 200 and frase.endswith("vita") and not frase.endswith(" ")
    parole_emoji = N.safe_filename("ciao \U0001F600 " * 40)
    assert len(parole_emoji.encode("utf-8")) <= 200 and parole_emoji.split(" ")[-1] in ("ciao", "\U0001F600")  # parole intere anche con emoji


def test_nome_file_taglio_esatto_sul_limite_e_nomi_riservati():
    exact = "a" * 39 + " " + "b" * 40  # 80 caratteri esatti: non si taglia
    assert N.safe_filename(exact) == exact
    assert N.safe_filename("a" * 39 + " " + "b" * 41) == "a" * 39  # un carattere oltre: la parola che sfora cade tutta
    assert N.safe_filename("a" * 80 + " zzz") == "a" * 80  # il limite cade su uno spazio
    assert N.safe_filename("CON " + "x" * 200) == "_CON"  # la seconda parola non ci sta intera: resta la prima, che e' un nome riservato di Windows
    assert N.safe_filename("con") == "_con" and ".." not in N.safe_filename("a" * 78 + "...b")
