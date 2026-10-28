"""API, CLI e privacy del confronto col CV (home temporanea, nessuna rete)."""
import io
import json
import logging
import time
from pathlib import Path

import pytest

from cvguard import _cv_guardia  # noqa: F401  (autouse: home temporanea, niente rete)
from jobshunter import cv, cvmatch, settings
from jobshunter.db import DB

DATA = Path(__file__).parent.parent / "data" / "cv"
H = {"Host": "127.0.0.1:8765"}
SECRET = "ZEBRA-QUOKKA-7741"   # parola inventata messa nei CV di prova per cercarla ovunque


@pytest.fixture
def client(home):
    from jobshunter.gui.app import create_app

    return create_app(None, 8765).test_client()


@pytest.fixture(autouse=True)
def _no_check(monkeypatch):
    from jobshunter import availability

    monkeypatch.setattr(availability, "checkable", lambda *a, **k: False)  # la scheda annuncio non verifica online


@pytest.fixture
def dbx(client, home):
    c = settings.load_config()
    return DB(settings.resolve_path(c["general"]["db_path"]))


def post_file(client, name, data=None, field="file"):
    data = (DATA / name).read_bytes() if data is None else data
    return client.post("/api/cv", data={field: (io.BytesIO(data), name)}, headers=H, content_type="multipart/form-data")


def wait_idle(client, tries=100):
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


def test_senza_cv(client):
    d = client.get("/api/cv", headers=H).get_json()
    assert d == {"present": False, "matching": {"running": False, "done": 0, "total": 0}}


def test_carica_pdf_docx_txt_md(client):
    for name in ("sviluppatore.pdf", "sistemista.docx", "cyber_junior.txt", "infermiere.md"):
        r = post_file(client, name)
        assert r.status_code == 200 and r.get_json()["ok"], name
        d = r.get_json()["cv"]
        assert d["present"] and d["words"] > 30 and d["skills"]
        assert set(d) >= {"present", "updated", "words", "skills", "years", "languages"}
    assert "Python" not in cv.current().skills  # l'ultimo caricato (infermiere) ha sostituito i precedenti


def test_incolla_testo(client):
    r = client.post("/api/cv", json={"text": "Esperienza con Python, SQL, Linux e Docker per anni. " * 5}, headers=H)
    assert r.status_code == 200 and "Python" in r.get_json()["cv"]["skills"]
    assert r.get_json()["cv"]["source"] == "incollato"


@pytest.mark.parametrize("payload", [{"text": "poche parole"}, {"text": 5}, {}, [1], {"altro": "x"}])
def test_incolla_non_valido(client, payload):
    r = client.post("/api/cv", json=payload, headers=H)
    assert r.status_code == 400 and r.get_json()["ok"] is False
    assert not cv.path().exists()


def test_errori_chiari_in_italiano(client):
    r = post_file(client, "scansione_senza_testo.pdf")
    assert r.status_code == 400 and "scansione" in r.get_json()["error"]
    r = post_file(client, "finto.pdf", b"non sono un pdf " * 30)
    assert r.status_code == 400 and "PDF" in r.get_json()["error"]
    r = post_file(client, "cv.exe", b"MZ" + b"x" * 500)
    assert r.status_code == 400
    r = post_file(client, "cv.txt", b"%PDF-1.4 " + b"x" * 500)
    assert r.status_code == 400
    r = client.post("/api/cv", data={"altro": "x"}, headers=H, content_type="multipart/form-data")
    assert r.status_code == 400
    assert not cv.path().exists()


def test_file_troppo_grande(client):
    r = post_file(client, "grande.txt", b"parola " * 1_100_000)
    assert r.status_code in (400, 413)
    assert "5 MB" in r.get_json().get("error", "")
    assert not cv.path().exists()


def test_origin_e_host_come_gli_altri_post(client):
    body = {"text": "Python SQL Linux Docker Git " * 10}
    assert client.post("/api/cv", json=body, headers={"Host": "evil.example:8765"}).status_code == 403
    assert client.post("/api/cv", json=body, headers={**H, "Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/cv/delete", headers={**H, "Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/cv/skills", json={"add": ["Python"]}, headers={**H, "Origin": "http://evil.example"}).status_code == 403
    assert not cv.path().exists()
    assert client.post("/api/cv", json=body, headers={**H, "Origin": "http://127.0.0.1:8765"}).status_code == 200


def test_nessun_percorso_del_client_su_disco(client, home):
    post_file(client, "../../../../tmp/evil.txt", ("Python SQL Linux Docker Git " * 10).encode())
    assert not Path("/tmp/evil.txt").exists()
    assert sorted(p.name for p in home.iterdir() if p.name.startswith("cv") or p.name.startswith(".cv")) == ["cv.json"]


def test_competenze_api(client):
    client.post("/api/cv", json={"text": "Esperienza con Python e Linux per molti progetti diversi nel tempo. " * 4}, headers=H)
    r = client.post("/api/cv/skills", json={"add": ["Docker"], "remove": ["Python"]}, headers=H).get_json()
    assert r["ok"] and "Docker" in r["cv"]["skills"] and "Python" not in r["cv"]["skills"]
    assert r["cv"]["skills_manual"] == ["Docker"] and r["cv"]["skills_removed"] == ["Python"]
    r = client.post("/api/cv/skills", json={"restore": ["Python"]}, headers=H).get_json()
    assert "Python" in r["cv"]["skills"]
    assert client.post("/api/cv/skills", json={"add": ["parolainesistentexyz"]}, headers=H).status_code == 400
    assert client.post("/api/cv/skills", json={"add": "Docker"}, headers=H).status_code == 400
    assert client.post("/api/cv/skills", json={"add": ["x"] * 41}, headers=H).status_code == 400
    assert client.post("/api/cv/skills", data="no", headers=H, content_type="text/plain").status_code == 400


def test_competenze_senza_cv(client):
    r = client.post("/api/cv/skills", json={"add": ["Python"]}, headers=H)
    assert r.status_code == 400 and "CV" in r.get_json()["error"]


def test_elimina_cancella_cv_e_confronti(client, dbx, home):
    add_job(dbx, "a", "Analista", "SIEM Splunk" + LONG)
    client.post("/api/cv", json={"text": "SIEM Splunk Python Linux " * 12}, headers=H)
    wait_idle(client)
    assert dbx.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 1
    r = client.post("/api/cv/delete", headers=H).get_json()
    assert r["ok"] and r["cv"] == {"present": False}
    assert not cv.path().exists()
    assert dbx.conn.execute("SELECT COUNT(*) FROM cv_match").fetchone()[0] == 0
    assert client.get("/api/cv", headers=H).get_json()["present"] is False
    assert all(not p.name.startswith(".cv") for p in home.iterdir())
    assert client.post("/api/cv/delete", headers=H).status_code == 200  # idempotente


def test_elenco_annunci_con_affinita(client, dbx):
    add_job(dbx, "alto", "SOC Analyst", "SIEM Splunk Wazuh Python Linux" + LONG)
    add_job(dbx, "basso", "Infermiere", "triage BLSD prelievi somministrazione terapie" + LONG)
    dbx.conn.execute("UPDATE jobs SET score=95 WHERE uid='basso'")
    dbx.conn.commit()
    plain = client.get("/api/jobs?group=all", headers=H).get_json()
    assert [j["uid"] for j in plain] == ["basso", "alto"] and all(j["cv"] is None for j in plain)
    client.post("/api/cv", data={"file": (io.BytesIO((DATA / "cyber_junior.txt").read_bytes()), "c.txt")}, headers=H, content_type="multipart/form-data")
    wait_idle(client)
    jobs = client.get("/api/jobs?group=all", headers=H).get_json()
    by = {j["uid"]: j for j in jobs}
    assert by["alto"]["cv"] > 40 and by["basso"]["cv"] < 10 and by["alto"]["cv_base"] == "completo"
    assert [j["uid"] for j in jobs] == ["basso", "alto"]  # il punteggio principale non cambia
    assert [j["uid"] for j in client.get("/api/jobs?group=all&sort=cv", headers=H).get_json()] == ["alto", "basso"]
    assert [j["uid"] for j in client.get("/api/jobs?group=all&cv_min=40", headers=H).get_json()] == ["alto"]
    assert len(client.get("/api/jobs?group=all&cv_min=abc", headers=H).get_json()) == 2
    assert len(client.get("/api/jobs?group=all&cv_min=-5", headers=H).get_json()) == 2


def test_cv_min_senza_cv_ignorato(client, dbx):
    add_job(dbx, "a", "Analista", "SIEM" + LONG)
    assert len(client.get("/api/jobs?group=all&cv_min=90&sort=cv", headers=H).get_json()) == 1


def test_nuovo_annuncio_si_confronta_da_solo(client, dbx):
    client.post("/api/cv", json={"text": "SIEM Splunk Python Linux " * 12}, headers=H)
    wait_idle(client)
    add_job(dbx, "nuovo", "Analista SIEM", "Splunk SIEM Linux" + LONG)
    client.get("/api/jobs?group=all", headers=H)
    wait_idle(client)
    j = client.get("/api/jobs?group=all", headers=H).get_json()[0]
    assert j["cv"] is not None


def test_scheda_annuncio_con_spiegazione(client, dbx):
    add_job(dbx, "abcdef1234", "SOC Analyst Junior", "SIEM Splunk Wazuh Kubernetes Terraform. Inglese richiesto" + LONG)
    client.post("/api/cv", data={"file": (io.BytesIO((DATA / "cyber_junior.txt").read_bytes()), "c.txt")}, headers=H, content_type="multipart/form-data")
    wait_idle(client)
    j = client.get("/api/job/abcdef1234", headers=H).get_json()
    e = j["cv_explain"]
    assert set(e) >= {"in_comune", "mancanti", "livello", "note", "base"}
    assert {"SIEM", "Splunk"} <= set(e["in_comune"]) and {"Kubernetes", "Terraform"} <= set(e["mancanti"])
    assert j["cv"] == client.get("/api/jobs?group=all", headers=H).get_json()[0]["cv"]


def test_scheda_annuncio_anteprima_jooble(client, dbx):
    add_job(dbx, "joo1234567", "SOC Analyst", "SIEM Splunk Wazuh Python", source="jooble:it", full="")
    client.post("/api/cv", data={"file": (io.BytesIO((DATA / "cyber_junior.txt").read_bytes()), "c.txt")}, headers=H, content_type="multipart/form-data")
    wait_idle(client)
    j = client.get("/api/job/joo1234567", headers=H).get_json()
    assert j["cv_base"] == "anteprima" and j["cv_explain"]["note"][0].startswith("Basato su anteprima") and j["cv"] <= 60


def test_scheda_senza_cv_non_ha_blocco(client, dbx):
    add_job(dbx, "abcdef1234", "SOC", "SIEM" + LONG)
    j = client.get("/api/job/abcdef1234", headers=H).get_json()
    assert "cv_explain" not in j and j["cv"] is None


def test_ricalcolo_su_richiesta(client, dbx):
    assert client.post("/api/cv/match", headers=H).status_code == 400
    client.post("/api/cv", json={"text": "SIEM Splunk Python Linux " * 12}, headers=H)
    wait_idle(client)
    assert client.post("/api/cv/match", headers=H).get_json()["ok"]


# ---------------------------------------------------------------------- privacy ----
def leak_files(root, needle):
    hits = []
    for p in Path(root).rglob("*"):
        if p.is_file() and p.name != "cv.json":
            try:
                if needle.encode() in p.read_bytes():
                    hits.append(str(p))
            except OSError:
                pass
    return hits


def test_il_testo_del_cv_non_esce_da_api_log_ne_file(client, dbx, home, caplog):
    caplog.set_level(logging.DEBUG)
    cvtext = f"Analista con Python SQL Linux Docker Git. Codice riservato {SECRET}. Esperienza varia nel tempo. " * 3
    add_job(dbx, "a", "Analista", "Python SQL" + LONG)
    out = []
    r = client.post("/api/cv", json={"text": cvtext}, headers=H)
    out.append(r.get_data(as_text=True))
    wait_idle(client)
    out.append(client.get("/api/cv", headers=H).get_data(as_text=True))
    out.append(client.get("/api/jobs?group=all", headers=H).get_data(as_text=True))
    out.append(client.get("/api/job/a", headers=H).get_data(as_text=True))
    out.append(client.get("/api/settings", headers=H).get_data(as_text=True))
    out.append(client.get("/api/stats", headers=H).get_data(as_text=True))
    out.append(client.post("/api/cv/skills", json={"add": [SECRET]}, headers=H).get_data(as_text=True))
    out.append(client.post("/api/cv/skills", json={"remove": ["Python"]}, headers=H).get_data(as_text=True))
    out.append(client.post("/api/report", json={}, headers=H).get_data(as_text=True))
    # errori: file che contiene il segreto ma e' un formato falso
    for name, data in (("f.pdf", SECRET.encode() * 50), ("f.docx", b"PK\x03\x04" + SECRET.encode() * 50), ("f.txt", b"%PDF-" + SECRET.encode() * 50)):
        out.append(post_file(client, name, data).get_data(as_text=True))
    for o in out:
        assert SECRET not in o
    assert SECRET not in caplog.text
    assert SECRET not in json.dumps([dict(r) for r in dbx.conn.execute("SELECT * FROM cv_match")])
    assert SECRET not in "".join(str(tuple(r)) for r in dbx.conn.execute("SELECT * FROM kv"))
    assert leak_files(home, SECRET) == []
    assert SECRET in cv.path().read_text()  # il testo sta solo li'


def test_nessun_testo_nel_report_e_nella_esportazione(client, dbx, home):
    add_job(dbx, "a", "Analista Python", "Python SQL" + LONG)
    client.post("/api/cv", json={"text": f"Python SQL Linux {SECRET} " * 20}, headers=H)
    wait_idle(client)
    from jobshunter.report import build_report

    cfg = settings.load_config()
    res = build_report(cfg, dbx, min_score=0, limit=10)
    if res and res[0]:
        assert SECRET not in Path(res[0]).read_text()
    from click.testing import CliRunner
    from jobshunter.cli import main

    out = CliRunner().invoke(main, ["export", str(home / "x.csv")])
    assert SECRET not in out.output and SECRET not in (home / "x.csv").read_text()


def test_nomi_file_temporanei_non_legati_al_cv(home):
    cv.save_text(f"Python SQL Linux Docker Git {SECRET} " * 10, "txt")
    for p in home.iterdir():
        assert SECRET not in p.name
    assert not list(home.glob(".cv-*.tmp"))


def test_api_senza_rete_con_socket_bloccati(client, dbx, monkeypatch):
    import socket

    def boom(*a, **k):
        raise AssertionError("rete vietata")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    add_job(dbx, "a", "Analista", "SIEM Splunk" + LONG)
    assert client.post("/api/cv", json={"text": "SIEM Splunk Python Linux " * 12}, headers=H).status_code == 200
    wait_idle(client)
    assert client.get("/api/jobs?group=all", headers=H).get_json()[0]["cv"] is not None


# -------------------------------------------------------------------------- CLI ----
def test_cli_set_show_match_list_clear(home):
    from click.testing import CliRunner
    from jobshunter.cli import main

    cfg = settings.load_config(create_if_missing=True)
    db = DB(settings.resolve_path(cfg["general"]["db_path"]))
    add_job(db, "aaaaaa1111", "Analista SIEM", "SIEM Splunk Wazuh Python" + LONG)
    add_job(db, "bbbbbb2222", "Infermiere", "triage BLSD prelievi terapie" + LONG)
    db.conn.execute("UPDATE jobs SET score=99 WHERE uid LIKE 'bbbbbb%'")
    db.conn.commit()
    r = CliRunner()
    assert r.invoke(main, ["cv", "show"]).output.count("Nessun CV") == 1
    assert r.invoke(main, ["list", "--cv-min", "10"]).exit_code == 1
    out = r.invoke(main, ["cv", "set", str(DATA / "cyber_junior.txt")])
    assert out.exit_code == 0, out.output
    assert "Splunk" in out.output and "permessi" in out.output
    show = r.invoke(main, ["cv", "show"]).output
    assert "SIEM" in show and "Marco" not in show and "Acme Security" not in show
    out = r.invoke(main, ["cv", "match"])
    assert out.exit_code == 0 and "aaaaaa" in out.output
    lst = r.invoke(main, ["list", "--source", "all", "--cv-min", "40"]).output
    assert "aaaaaa" in lst and "bbbbbb" not in lst
    lst = r.invoke(main, ["list", "--source", "all", "--by-cv"]).output
    assert lst.index("aaaaaa") < lst.index("bbbbbb")
    assert r.invoke(main, ["cv", "clear", "-y"]).exit_code == 0
    assert not cv.path().exists()
    assert r.invoke(main, ["cv", "set", str(DATA / "scansione_senza_testo.pdf")]).exit_code == 1
    assert r.invoke(main, ["cv", "set", str(DATA / "sviluppatore.pdf")]).exit_code == 0


def test_cli_non_stampa_il_testo(home):
    from click.testing import CliRunner
    from jobshunter.cli import main

    f = home / "cv.txt"
    f.write_text(f"Python SQL Linux Docker Git {SECRET} lavoro " * 10)
    out = CliRunner().invoke(main, ["cv", "set", str(f)])
    assert out.exit_code == 0 and SECRET not in out.output
    assert SECRET not in CliRunner().invoke(main, ["cv", "show"]).output
