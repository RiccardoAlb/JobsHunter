"""Fase 10, blocco note: rotte /api/notes* (home temporanea, nessuna rete)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from jobshunter import notes as N
from jobshunter import settings
from jobshunter.db import DB

H = {"Host": "127.0.0.1:8765"}


@pytest.fixture
def reports(tmp_path, home):
    """Cartella dei report in una cartella temporanea (mai quella vera), scritta in settings.json prima di avviare l'app."""
    cfg = settings.load_config(create_if_missing=True)
    folder = tmp_path / "Report miei è"
    settings.save_overrides(Path(cfg["_config_path"]), {"report.dir": str(folder)})
    return folder


@pytest.fixture
def client(reports):
    from jobshunter.gui.app import create_app

    return create_app(None, 8765).test_client()


@pytest.fixture
def dbx(client, home):
    cfg = settings.load_config()
    return DB(settings.resolve_path(cfg["general"]["db_path"]))


def add_job(db, uid="job1", title="Analista SOC", company="Acme Srl"):
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, score, category, matched, first_seen) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (uid, "adzuna", title, company, "Milano", "https://example.org/" + uid, "d", 50, "BLUE", "", "2026-01-01T00:00:00+00:00"))
    db.conn.commit()
    return uid


def post(client, path, body=None, headers=H):
    return client.post(path, data=json.dumps({} if body is None else body), content_type="application/json", headers=headers)


def create(client, **body):
    r = post(client, "/api/notes", body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


# ---------------------------------------------------------------- crea e leggi ----
def test_crea_una_nota_201_con_tutti_i_campi(client):
    r = post(client, "/api/notes", {"kind": "note", "title": "Appunto", "body": "testo"})
    assert r.status_code == 201
    n = r.get_json()
    assert n["ok"] is True and n["id"] == 1 and n["kind"] == "note" and n["title"] == "Appunto" and n["body"] == "testo"
    assert n["job_uid"] is None and n["app_id"] is None and n["company"] == "" and n["role"] == "" and n["created"] and n["updated"]
    assert "job_open" not in n  # solo se ha un annuncio
    assert create(client)["kind"] == "note"  # senza kind: nota


def test_elenco_e_filtri(client, dbx):
    job = add_job(dbx)
    a = create(client, title="Generale uno")
    b = create(client, kind="letter", title="Lettera", job_uid=job)
    c = create(client, title="Dell'annuncio", job_uid=job, body="parola_segreta 100%")
    lst = client.get("/api/notes", headers=H).get_json()
    assert [n["id"] for n in lst] == [c["id"], b["id"], a["id"]]
    assert [n["id"] for n in client.get("/api/notes?general=1", headers=H).get_json()] == [a["id"]]
    assert {n["id"] for n in client.get(f"/api/notes?job={job}", headers=H).get_json()} == {b["id"], c["id"]}
    assert [n["id"] for n in client.get("/api/notes?kind=letter", headers=H).get_json()] == [b["id"]]
    assert [n["id"] for n in client.get("/api/notes?q=PAROLA_segreta", headers=H).get_json()] == [c["id"]]
    assert [n["id"] for n in client.get("/api/notes?q=100%25", headers=H).get_json()] == [c["id"]]
    assert client.get("/api/notes?q=%25", headers=H).get_json() and len(client.get("/api/notes?q=%25", headers=H).get_json()) == 1
    assert client.get("/api/notes?kind=boh", headers=H).status_code == 400
    assert client.get("/api/notes?app=abc", headers=H).status_code == 400  # un id non numerico e' un errore chiaro, non un 500
    assert all(n["job_open"] is True for n in client.get(f"/api/notes?job={job}", headers=H).get_json())


def test_job_open_falso_se_l_annuncio_e_chiuso_o_sparito(client, dbx):
    job = add_job(dbx)
    create(client, title="x", job_uid=job)
    dbx.set_avail(job, "closed", None, "chiuso")
    assert client.get(f"/api/notes?job={job}", headers=H).get_json()[0]["job_open"] is False
    dbx.conn.execute("DELETE FROM jobs WHERE uid=?", (job,))
    dbx.conn.commit()
    n = client.get(f"/api/notes?job={job}", headers=H).get_json()[0]
    assert n["job_open"] is False and n["company"] == "Acme Srl"  # il contesto resta


# ------------------------------------------------------------------- errori ----
def test_creazione_codici_di_errore(client, dbx):
    assert post(client, "/api/notes", {"kind": "boh"}).status_code == 400
    assert post(client, "/api/notes", {"title": "t" * 201}).status_code == 400
    r = post(client, "/api/notes", {"body": "b" * 100_001})
    assert r.status_code == 400 and r.get_json()["error"] == N.MSG_BODY_TOO_LONG and r.get_json()["ok"] is False
    assert post(client, "/api/notes", {"title": 5}).status_code == 400
    assert post(client, "/api/notes", {"title": ["x"]}).status_code == 400
    assert post(client, "/api/notes", {"job_uid": 5}).status_code == 400
    assert post(client, "/api/notes", {"app_id": "1"}).status_code == 400
    assert post(client, "/api/notes", {"app_id": True}).status_code == 400
    r = post(client, "/api/notes", {"job_uid": "non-esiste"})
    assert r.status_code == 404 and r.get_json()["error"] == N.MSG_JOB_NOT_FOUND
    r = post(client, "/api/notes", {"app_id": 77})
    assert r.status_code == 404 and r.get_json()["error"] == N.MSG_APP_NOT_FOUND
    assert post(client, "/api/notes", {"app_id": 10**30}).status_code == 404
    assert client.post("/api/notes", data="non json", content_type="application/json", headers=H).status_code == 400
    assert client.post("/api/notes", data="[1]", content_type="application/json", headers=H).status_code == 400
    assert dbx.note_counts()["total"] == 0  # nessun errore ha lasciato note a meta'


def test_testo_di_100000_caratteri_con_emoji_passa(client):
    raw = json.dumps({"title": "grande", "body": "\U0001F600" * 100_000}, ensure_ascii=False).encode("utf-8")  # come fa il browser: 4 byte per emoji
    assert len(raw) > 256 * 1024  # piu' del limite delle altre rotte
    r = client.post("/api/notes", data=raw, content_type="application/json", headers=H)
    assert r.status_code == 201 and len(r.get_json()["body"]) == 100_000


def test_corpo_enorme_rifiutato_con_413(client):
    r = client.post("/api/notes", data=json.dumps({"body": "x" * 900_000}), content_type="application/json", headers=H)
    assert r.status_code in (400, 413)


# ----------------------------------------------------------------- lettere ----
def test_lettera_senza_testo_usa_il_modello_con_i_dati_dell_annuncio(client, dbx):
    job = add_job(dbx)
    n = create(client, kind="letter", job_uid=job)
    assert n["title"] == "Lettera per Acme Srl, Analista SOC" and n["company"] == "Acme Srl" and n["role"] == "Analista SOC"
    assert "Acme Srl" in n["body"] and "Milano" in n["body"] and "https://example.org/job1" in n["body"] and "{azienda}" not in n["body"]
    own = create(client, kind="letter", job_uid=job, title="Mio titolo", body="testo mio {azienda}")
    assert own["title"] == "Mio titolo" and own["body"] == "testo mio {azienda}"  # con il testo dato non si usa il modello
    vuoto = create(client, kind="letter", job_uid=job, body="")
    assert vuoto["body"] == ""


def test_lettera_senza_annuncio_lascia_i_segnaposto_visibili(client):
    n = create(client, kind="letter")
    assert n["title"] == "Lettera di presentazione" and "{azienda}" in n["body"] and "{ruolo}" in n["body"] and "{link}" in n["body"]


def test_lettera_da_candidatura(client, dbx):
    aid = dbx.add_application(company="Manuale SpA", role="Tester", location="Roma", url="https://example.org/m")
    n = create(client, kind="letter", app_id=aid)
    assert n["app_id"] == aid and "Manuale SpA" in n["body"] and "Roma" in n["body"] and n["title"] == "Lettera per Manuale SpA, Tester"


# ------------------------------------------------ le note seguono la candidatura ----
def test_segna_candidato_porta_le_note_nella_candidatura(client, dbx):
    job = add_job(dbx)
    n = create(client, title="prima", job_uid=job)
    assert n["app_id"] is None
    assert post(client, f"/api/job/{job}/status", {"status": "applied"}).status_code == 200
    apps = client.get("/api/apps", headers=H).get_json()
    assert apps[0]["note_count"] == 1
    assert client.get(f"/api/notes?app={apps[0]['id']}", headers=H).get_json()[0]["id"] == n["id"]
    # cancellare la candidatura non cancella la nota
    assert post(client, f"/api/apps/{apps[0]['id']}/delete").status_code == 200
    after = client.get("/api/notes", headers=H).get_json()
    assert len(after) == 1 and after[0]["app_id"] is None and after[0]["job_uid"] == job


# ----------------------------------------------------------- aggiorna ed elimina ----
def test_aggiorna_e_idempotente_e_non_tocca_le_altre(client):
    a, b = create(client, title="a", body="uno"), create(client, title="b", body="due")
    r1 = post(client, f"/api/notes/{a['id']}", {"title": "A2", "body": "uno bis"})
    assert r1.status_code == 200 and r1.get_json()["title"] == "A2" and r1.get_json()["body"] == "uno bis" and r1.get_json()["updated"] >= a["updated"]
    r2 = post(client, f"/api/notes/{a['id']}", {"title": "A2", "body": "uno bis"})
    assert r2.get_json()["title"] == "A2" and r2.get_json()["body"] == "uno bis"
    assert post(client, f"/api/notes/{a['id']}", {"body": "solo testo"}).get_json()["title"] == "A2"
    other = [n for n in client.get("/api/notes", headers=H).get_json() if n["id"] == b["id"]][0]
    assert (other["title"], other["body"], other["updated"]) == ("b", "due", b["updated"])
    assert post(client, "/api/notes/999", {"title": "x"}).status_code == 404
    assert post(client, f"/api/notes/{10**30}", {"title": "x"}).status_code == 404
    r = post(client, f"/api/notes/{a['id']}", {"body": "x" * 100_001})
    assert r.status_code == 400
    assert client.get("/api/notes", headers=H).get_json()[-1]["body"] in ("uno bis", "solo testo", "due")
    assert post(client, f"/api/notes/{a['id']}", {"title": 7}).status_code == 400


def test_elimina_solo_con_la_richiesta_esplicita(client):
    a, b = create(client, title="a"), create(client, title="b")
    assert client.get(f"/api/notes/{a['id']}/delete", headers=H).status_code == 405  # mai con una GET
    assert post(client, f"/api/notes/{a['id']}/delete").get_json() == {"ok": True}
    assert [n["id"] for n in client.get("/api/notes", headers=H).get_json()] == [b["id"]]
    assert post(client, f"/api/notes/{a['id']}/delete").status_code == 404
    assert post(client, f"/api/notes/{10**30}/delete").status_code == 404


# --------------------------------------------------------------- protezioni ----
def test_protezioni_come_le_altre_rotte(client):
    n = create(client, title="x")
    paths = ["/api/notes", f"/api/notes/{n['id']}", f"/api/notes/{n['id']}/delete", "/api/notes/template", "/api/notes/export", f"/api/notes/{n['id']}/export"]
    for p in paths:
        assert post(client, p, headers={"Host": "evil.example"}).status_code == 403
        assert post(client, p, headers={**H, "Origin": "https://evil.example"}).status_code == 403
        assert post(client, p, headers={**H, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/notes", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/notes/template", headers={"Host": "evil.example"}).status_code == 403
    assert len(client.get("/api/notes", headers=H).get_json()) == 1


def test_stats_espone_il_conteggio_delle_note(client):
    assert client.get("/api/stats", headers=H).get_json()["notes"] == 0
    create(client, title="a")
    create(client, title="b", kind="letter")
    assert client.get("/api/stats", headers=H).get_json()["notes"] == 2


# ----------------------------------------------------------------- modello ----
def test_modello_predefinito_personalizzato_e_ripristino(client, reports):
    g = client.get("/api/notes/template", headers=H).get_json()
    assert g["is_default"] is True and g["template"] == N.DEFAULT_TEMPLATE and g["default"] == N.DEFAULT_TEMPLATE
    assert {"azienda", "company", "ruolo", "role", "sede", "location", "data", "date", "link", "url"} == set(g["placeholders"]) and g["max_length"] == 20_000
    r = post(client, "/api/notes/template", {"template": "Per {company} ({role}) il {date}"})
    assert r.get_json()["ok"] is True and r.get_json()["is_default"] is False
    assert client.get("/api/notes/template", headers=H).get_json()["template"] == "Per {company} ({role}) il {date}"
    # sta nelle impostazioni (settings.json), non nel browser, e sopravvive a un nuovo avvio dell'app
    cfg = settings.load_config()
    assert json.loads((Path(cfg["_config_path"]).with_name("settings.json")).read_text(encoding="utf-8"))[N.TEMPLATE_KEY] == "Per {company} ({role}) il {date}"
    from jobshunter.gui.app import create_app

    assert create_app(None, 8765).test_client().get("/api/notes/template", headers=H).get_json()["template"].startswith("Per {company}")
    n = create(client, kind="letter", title="x")
    assert n["body"] == f"Per {{company}} ({{role}}) il {N.today_it()}"  # senza annuncio: i segnaposto senza dato restano
    r = post(client, "/api/notes/template", {"template": ""})
    assert r.get_json()["is_default"] is True and client.get("/api/notes/template", headers=H).get_json()["template"] == N.DEFAULT_TEMPLATE
    assert N.TEMPLATE_KEY not in json.loads((Path(cfg["_config_path"]).with_name("settings.json")).read_text(encoding="utf-8"))  # il ripristino toglie la chiave


def test_modello_limiti_e_valori_strani(client):
    assert post(client, "/api/notes/template", {"template": "x" * 20_001}).status_code == 400
    assert post(client, "/api/notes/template", {"template": 5}).status_code == 400
    assert post(client, "/api/notes/template", {"template": "x" * 20_000}).status_code == 200
    assert client.post("/api/notes/template", data="boh", content_type="application/json", headers=H).status_code == 400
    r = post(client, "/api/notes/template", {"template": "   \n "})
    assert r.get_json()["is_default"] is True  # solo spazi = ripristino


def test_il_modello_non_e_un_campo_di_impostazioni(client):
    d = client.get("/api/settings", headers=H).get_json()
    assert N.TEMPLATE_KEY not in [f["key"] for f in d["fields"]]
    r = post(client, "/api/settings", {"values": {N.TEMPLATE_KEY: "x"}})
    assert r.status_code == 400  # per le impostazioni e' una chiave sconosciuta: si cambia solo dalle rotte delle note


# -------------------------------------------------------------- esportazione ----
def test_esporta_una_nota_nella_sottocartella_note_dei_report(client, dbx, reports):
    job = add_job(dbx)
    aid = dbx.add_application(company="Acme Srl", role="Analista SOC", job_uid=job, applied_at="2026-11-01")
    n = create(client, kind="letter", job_uid=job, title="Lettera per Acme Srl, Analista SOC", body="Gentili,\ntesto\n")
    r = post(client, f"/api/notes/{n['id']}/export")
    assert r.status_code == 200
    d = r.get_json()
    p = Path(d["path"])
    assert d["ok"] is True and d["name"] == p.name == "Lettera per Acme Srl, Analista SOC.md" and p.parent == reports / "Note" and p.is_file()
    text = p.read_text(encoding="utf-8")
    created = n["created"][:10]
    assert text == ("---\ntitolo: Lettera per Acme Srl, Analista SOC\ntipo: lettera\nazienda: Acme Srl\nruolo: Analista SOC\nannuncio: https://example.org/job1\n"
                    f"candidatura: inviata il 01/11/2026\ncreata: {created}\naggiornata: {created}\n---\n\nGentili,\ntesto\n")
    assert aid == n["app_id"]
    assert b"\r" not in p.read_bytes()


def test_esporta_non_sovrascrive_e_ripulisce_il_nome(client, reports):
    n = create(client, title="../../Brutto/nome: con*caratteri\nstrani?", body="x")
    p1 = Path(post(client, f"/api/notes/{n['id']}/export").get_json()["path"])
    p2 = Path(post(client, f"/api/notes/{n['id']}/export").get_json()["path"])
    assert p1 != p2 and p1.parent == p2.parent == reports / "Note"
    assert ".." not in p1.name and "/" not in p1.name and ":" not in p1.name and "*" not in p1.name and "\n" not in p1.name
    assert p2.name.endswith("-2.md") and p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")
    (reports / "Note" / "gia esiste.md").write_text("di un altro", encoding="utf-8")
    m = create(client, title="gia esiste", body="mio")
    p3 = Path(post(client, f"/api/notes/{m['id']}/export").get_json()["path"])
    assert p3.name == "gia esiste-2.md" and (reports / "Note" / "gia esiste.md").read_text(encoding="utf-8") == "di un altro"
    assert Path(post(client, f"/api/notes/{create(client, title='CON')['id']}/export").get_json()["path"]).name == "_CON.md"
    assert Path(post(client, f"/api/notes/{create(client, title='')['id']}/export").get_json()["path"]).name == "nota.md"


def test_esporta_newline_in_titolo_azienda_e_ruolo_ripuliti_nel_blocco_iniziale(client, dbx, reports):
    n = create(client, title="Titolo\nsu due righe", body="corpo\n---\nancora corpo")
    dbx.conn.execute("UPDATE notes SET company=?, role=? WHERE id=?", ("Ac\nme\r\n---", "Ru\x00olo", n["id"]))
    dbx.conn.commit()
    text = Path(post(client, f"/api/notes/{n['id']}/export").get_json()["path"]).read_text(encoding="utf-8")
    head = text.split("\n---\n", 1)[0]
    assert head.splitlines()[:3] == ["---", "titolo: Titolo su due righe", "tipo: nota"] and "azienda: Ac me -" in head and "ruolo: Ru olo" in head
    assert text.endswith("corpo\n---\nancora corpo")  # esattamente il testo della nota


def test_esporta_tutte_un_file_per_nota(client, reports):
    ids = [create(client, title="Stesso titolo", body=str(i))["id"] for i in range(3)] + [create(client, title="Altro", kind="letter")["id"]]
    d = post(client, "/api/notes/export").get_json()
    assert d["ok"] is True and d["count"] == 4 and Path(d["folder"]) == reports / "Note"
    names = sorted(Path(p).name for p in d["paths"])
    assert names == ["Altro.md", "Stesso titolo-2.md", "Stesso titolo-3.md", "Stesso titolo.md"]
    assert sorted(p.name for p in (reports / "Note").iterdir()) == names
    assert len(ids) == 4


def test_esporta_senza_note_404_e_nota_inesistente_404(client):
    r = post(client, "/api/notes/export")
    assert r.status_code == 404 and r.get_json()["error"] == N.MSG_NO_NOTES
    assert post(client, "/api/notes/999/export").status_code == 404
    assert post(client, f"/api/notes/{10**30}/export").status_code == 404


def test_esporta_cartella_protetta_rifiutata(home):
    cfg = settings.load_config(create_if_missing=True)
    protected = "C:\\Windows\\System32" if sys.platform.startswith("win") else "/etc"
    settings.save_overrides(Path(cfg["_config_path"]), {"report.dir": protected})  # come se l'utente avesse scelto una cartella di sistema
    from jobshunter.gui.app import create_app

    c = create_app(None, 8765).test_client()
    n = create(c, title="x")
    for path in (f"/api/notes/{n['id']}/export", "/api/notes/export"):
        r = post(c, path)
        assert r.status_code == 400 and "report" in r.get_json()["error"], r.get_json()
    assert not Path(protected, "Note").exists()
    assert len(c.get("/api/notes", headers=H).get_json()) == 1  # la nota e' al sicuro


def test_esportazione_non_lascia_file_nel_progetto(client, reports):
    root = Path(__file__).resolve().parent.parent.parent
    before = {p for p in (root / "reports").rglob("*")} if (root / "reports").exists() else set()
    n = create(client, title="x")
    post(client, f"/api/notes/{n['id']}/export")
    post(client, "/api/notes/export")
    after = {p for p in (root / "reports").rglob("*")} if (root / "reports").exists() else set()
    assert after == before  # i file vanno nella cartella temporanea, non in reports/ del progetto


def test_B126_B133_errori_400_con_ok_falso_e_surrogati(client):
    for path in ("/api/notes", "/api/notes/template", "/api/notes/1"):
        r = client.post(path, data="[]", content_type="application/json", headers=H)
        assert r.status_code == 400 and r.get_json() == {"ok": False, "error": N.MSG_NEED_JSON}
    for body in ({"title": "\ud800"}, {"body": "x\udfff"}):
        r = client.post("/api/notes", data=json.dumps(body), content_type="application/json", headers=H)
        assert r.status_code == 400 and r.get_json() == {"ok": False, "error": N.MSG_BAD_TEXT}
    r = client.post("/api/notes/template", data='{"template": "a \\ud800"}', content_type="application/json", headers=H)
    assert r.status_code == 400 and r.get_json()["error"] == N.MSG_BAD_TEXT


def test_B132_id_enormi_non_danno_mai_500(client):
    for v in ("99999999999999999999", "9" * 400, str(2**63), str(2**62 + 1)):
        r = client.get("/api/notes?app=" + v, headers=H)
        assert r.status_code == 400 and r.get_json()["ok"] is False
    assert client.get("/api/notes?job=" + "x" * 5000, headers=H).get_json() == []


def test_B130_api_annuncio_e_candidatura_incoerenti_400(client, dbx):
    add_job(dbx, "A")
    add_job(dbx, "B", company="Beta")
    appb = dbx.add_application(company="Beta", role="RB", job_uid="B")
    r = post(client, "/api/notes", {"title": "x", "job_uid": "A", "app_id": appb})
    assert r.status_code == 400 and r.get_json() == {"ok": False, "error": N.MSG_LINK_MISMATCH}


def test_B128_collegamento_note_verso_fuori_rifiutato_400(client, reports, tmp_path):
    if sys.platform.startswith("win"):
        pytest.skip("collegamenti simbolici: servono privilegi su Windows")
    n = create(client, title="x")
    reports.mkdir(parents=True, exist_ok=True)
    fuori = tmp_path / "altrove"
    fuori.mkdir()
    os.symlink(fuori, reports / "Note", target_is_directory=True)
    for path in (f"/api/notes/{n['id']}/export", "/api/notes/export"):
        r = post(client, path)
        assert r.status_code == 400 and r.get_json()["ok"] is False and "Note" in r.get_json()["error"]
    assert not list(fuori.iterdir())
