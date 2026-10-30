"""Fase 8, annunci salvati: database, duplicati, API e stato del tutorial (home temporanea, nessuna rete)."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from jobshunter import onboarding, settings
from jobshunter.db import DB

H = {"Host": "127.0.0.1:8765"}
ROOT = Path(__file__).resolve().parent.parent.parent
OLD_JOBS = """
CREATE TABLE jobs (uid TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT, url TEXT, description TEXT,
  posted_at TEXT, remote INTEGER, score INTEGER, category TEXT, matched TEXT, status TEXT DEFAULT 'new', notified INTEGER DEFAULT 0,
  first_seen TEXT, salary TEXT DEFAULT '', near_home INTEGER DEFAULT 0, full_text TEXT DEFAULT '');
"""


@pytest.fixture
def client(home):
    from jobshunter.gui.app import create_app

    return create_app(None, 8765).test_client()


@pytest.fixture(autouse=True)
def _no_check(monkeypatch):
    from jobshunter import availability

    monkeypatch.setattr(availability, "checkable", lambda *a, **k: False)


@pytest.fixture
def dbx(client, home):
    c = settings.load_config()
    return DB(settings.resolve_path(c["general"]["db_path"]))


def add(db, uid, title="Ruolo", company="Acme", score=50, **extra):
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, score, category, matched, first_seen) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (uid, "adzuna", title, company, "Roma", "https://example.org/" + uid, "descrizione " * 10,
                                                      score, "BLUE", "", "2026-01-01T00:00:00+00:00"))
    for k, v in extra.items():
        db.conn.execute(f"UPDATE jobs SET {k}=? WHERE uid=?", (v, uid))
    db.conn.commit()


def listing(client, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return client.get("/api/jobs?" + qs, headers=H).get_json()


# ------------------------------------------------------------------ database ----
def test_migrazione_da_db_vecchio_senza_perdere_nulla(tmp_path):
    p = tmp_path / "vecchio.db"
    con = sqlite3.connect(p)
    con.executescript(OLD_JOBS)
    con.execute("INSERT INTO jobs (uid, title, company, score, status) VALUES ('a1', 'Vecchio annuncio', 'Acme', 70, 'applied')")
    con.commit()
    con.close()
    db = DB(p)
    assert "saved_at" in {r["name"] for r in db.conn.execute("PRAGMA table_info(jobs)")}
    r = db.conn.execute("SELECT * FROM jobs WHERE uid='a1'").fetchone()
    assert (r["title"], r["score"], r["status"], r["saved_at"]) == ("Vecchio annuncio", 70, "applied", None)
    DB(p)  # una seconda apertura non da' errori (colonna gia' presente)


def test_save_unsave_idempotenti(dbx):
    add(dbx, "u1")
    assert dbx.save_job("u1") is True
    first = dbx.conn.execute("SELECT saved_at FROM jobs WHERE uid='u1'").fetchone()[0]
    assert first
    assert dbx.save_job("u1") is True
    assert dbx.conn.execute("SELECT saved_at FROM jobs WHERE uid='u1'").fetchone()[0] == first  # resta la data del primo salvataggio
    assert dbx.unsave_job("u1") is True and dbx.unsave_job("u1") is True
    assert dbx.conn.execute("SELECT saved_at FROM jobs WHERE uid='u1'").fetchone()[0] is None
    assert dbx.save_job("non-esiste") is False and dbx.unsave_job("non-esiste") is False


@pytest.mark.parametrize("status", ["new", "seen", "applied"])
def test_salvato_e_indipendente_dallo_stato(dbx, status):
    add(dbx, "u1")
    dbx.save_job("u1")
    dbx.set_status("u1", status)
    r = dbx.conn.execute("SELECT status, saved_at FROM jobs WHERE uid='u1'").fetchone()
    assert r["status"] == status and r["saved_at"]
    assert [x["uid"] for x in dbx.query(saved=True)] == ["u1"]


def test_filtro_saved_ordine_e_conteggio(dbx):
    for u, s in (("a", 10), ("b", 90), ("c", 50)):
        add(dbx, u, score=s)
    dbx.conn.execute("UPDATE jobs SET saved_at='2026-02-01T00:00:00+00:00' WHERE uid='a'")
    dbx.conn.execute("UPDATE jobs SET saved_at='2026-03-01T00:00:00+00:00' WHERE uid='c'")
    dbx.conn.commit()
    assert [r["uid"] for r in dbx.query(saved=True)] == ["c", "a"]  # il salvato per ultimo viene per primo, qualunque sia il punteggio
    assert dbx.saved_count() == 2
    assert [r["uid"] for r in dbx.query()] == ["b", "c", "a"]  # senza filtro: ordine di sempre


def test_annuncio_non_piu_online_resta_salvato(dbx):
    add(dbx, "u1")
    add(dbx, "u2")
    dbx.save_job("u1")
    dbx.set_avail("u1", "closed", None, "chiuso dalla fonte")
    assert "u1" not in [r["uid"] for r in dbx.query()]  # nella lista normale i chiusi non si vedono
    assert [r["uid"] for r in dbx.query(saved=True)] == ["u1"]  # ma il salvato resta, con la sua etichetta
    assert dbx.saved_count() == 1
    assert dbx.conn.execute("SELECT saved_at FROM jobs WHERE uid='u1'").fetchone()[0]


def test_cambio_profilo_e_rescoring_non_toccano_il_salvataggio(dbx, home):
    from jobshunter.models import Job
    from jobshunter.rescore import rescore

    job = Job(source="adzuna", title="Security Analyst", company="Acme", location="Roma", url="https://example.org/x", description="SIEM Splunk", score=10, category="BLUE")
    assert dbx.upsert(job) is True
    dbx.commit()
    dbx.save_job(job.uid)
    before = dbx.conn.execute("SELECT saved_at FROM jobs WHERE uid=?", (job.uid,)).fetchone()[0]
    job.score = 99
    assert dbx.upsert(job) is False  # nuova scansione dello stesso annuncio
    dbx.commit()
    rescore(dbx, settings.load_config())  # ricalcolo dei profili
    r = dbx.conn.execute("SELECT saved_at FROM jobs WHERE uid=?", (job.uid,)).fetchone()
    assert r["saved_at"] == before


def test_duplicato_confermato_il_tenuto_eredita_il_salvataggio_piu_vecchio(dbx):
    add(dbx, "keep")
    add(dbx, "hid")
    dbx.conn.execute("UPDATE jobs SET saved_at='2026-05-01T00:00:00+00:00' WHERE uid='keep'")
    dbx.conn.execute("UPDATE jobs SET saved_at='2026-02-01T00:00:00+00:00' WHERE uid='hid'")
    dbx.conn.commit()
    dbx.upsert_dup("keep", "hid", 80, "keep", "hid")
    pid = dbx.list_dups("pending")[0]["id"]
    assert dbx.set_dup_status(pid, "confirmed")
    sa = lambda u: dbx.conn.execute("SELECT saved_at FROM jobs WHERE uid=?", (u,)).fetchone()[0]
    assert sa("keep") == "2026-02-01T00:00:00+00:00"
    assert [r["uid"] for r in dbx.query(saved=True)] == ["keep"]  # il nascosto non compare due volte
    assert dbx.saved_count() == 1
    # annullo: nessun salvataggio e' andato perso
    assert dbx.set_dup_status(pid, "rejected")
    assert sa("hid") == "2026-02-01T00:00:00+00:00" and sa("keep")
    assert {r["uid"] for r in dbx.query(saved=True)} == {"keep", "hid"}


def test_duplicato_confermato_in_automatico_porta_il_salvataggio(dbx):
    add(dbx, "k")
    add(dbx, "h")
    dbx.save_job("h")
    dbx.upsert_dup("k", "h", 100, "k", "h", auto=True)
    assert dbx.conn.execute("SELECT saved_at FROM jobs WHERE uid='k'").fetchone()[0]
    assert [r["uid"] for r in dbx.query(saved=True)] == ["k"]


def test_nessuna_pulizia_cancella_gli_annunci():
    """Il codice non contiene nessuna cancellazione di annunci (purge/retention): un salvato non puo' sparire da li'."""
    for p in (ROOT / "jobshunter").rglob("*.py"):
        assert not re.search(r"DELETE\s+FROM\s+jobs\b", p.read_text(encoding="utf-8"), re.I), p


def test_backup_e_ripristino_mantengono_saved_at(dbx, home):
    add(dbx, "u1")
    dbx.save_job("u1")
    saved = dbx.conn.execute("SELECT saved_at FROM jobs WHERE uid='u1'").fetchone()[0]
    copia = dbx.snapshot("prova")
    assert copia
    ripristinato = DB(copia)
    assert ripristinato.conn.execute("SELECT saved_at FROM jobs WHERE uid='u1'").fetchone()[0] == saved


def test_esportazione_csv_riporta_la_data_di_salvataggio(dbx, home):
    import csv

    from click.testing import CliRunner
    from jobshunter.cli import main

    add(dbx, "u1", title="Salvato")
    add(dbx, "u2", title="Normale")
    dbx.save_job("u1")
    out = home / "e.csv"
    assert CliRunner().invoke(main, ["export", str(out)]).exit_code == 0
    rows = {r["title"]: r for r in csv.DictReader(out.open(encoding="utf-8"))}
    assert rows["Salvato"]["saved_at"] and rows["Normale"]["saved_at"] == ""


# ------------------------------------------------------------------------ API ----
def test_api_save_unsave_e_risposta_json(client, dbx):
    add(dbx, "u1")
    add(dbx, "u2")
    r = client.post("/api/jobs/u1/save", json={}, headers=H)
    assert r.status_code == 200 and r.get_json()["ok"] is True and r.get_json()["saved"] is True and r.get_json()["saved_at"]
    assert client.post("/api/jobs/u1/save", json={}, headers=H).status_code == 200  # idempotente
    jobs = {j["uid"]: j for j in listing(client)}
    assert jobs["u1"]["saved"] is True and jobs["u1"]["saved_at"] and jobs["u2"]["saved"] is False and jobs["u2"]["saved_at"] is None  # nessun effetto sugli altri
    r = client.post("/api/jobs/u1/unsave", json={}, headers=H)
    assert r.get_json() == {"ok": True, "uid": "u1", "saved": False, "saved_at": None}
    assert client.post("/api/jobs/u1/unsave", json={}, headers=H).status_code == 200


def test_api_uid_inesistente_o_prefisso_dubbio(client, dbx):
    add(dbx, "abc123")
    for path in ("save", "unsave"):
        assert client.post(f"/api/jobs/nonesiste/{path}", json={}, headers=H).status_code == 404
        assert client.post(f"/api/jobs/abc/{path}", json={}, headers=H).status_code == 404  # serve l'uid esatto: mai "il primo che inizia cosi'"
        assert client.post(f"/api/jobs/%25/{path}", json={}, headers=H).status_code == 404
    assert dbx.conn.execute("SELECT COUNT(*) FROM jobs WHERE saved_at IS NOT NULL").fetchone()[0] == 0


def test_api_protezioni_come_le_altre_rotte(client, dbx):
    add(dbx, "u1")
    assert client.post("/api/jobs/u1/save", json={}, headers={"Host": "evil.example"}).status_code == 403
    assert client.post("/api/jobs/u1/save", json={}, headers={**H, "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/jobs/u1/save", json={}, headers={**H, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/jobs/u1/save", headers=H).status_code == 405  # solo POST
    assert dbx.conn.execute("SELECT saved_at FROM jobs WHERE uid='u1'").fetchone()[0] is None


def test_api_filtro_saved_stats_e_ordine(client, dbx):
    for u in ("a", "b", "c"):
        add(dbx, u, title="Ruolo " + u)
    client.post("/api/jobs/a/save", json={}, headers=H)
    client.post("/api/jobs/c/save", json={}, headers=H)
    dbx.conn.execute("UPDATE jobs SET saved_at='2026-01-01T00:00:00+00:00' WHERE uid='a'")
    dbx.conn.commit()
    assert [j["uid"] for j in listing(client, saved=1)] == ["c", "a"]
    assert client.get("/api/stats", headers=H).get_json()["saved"] == 2
    client.post("/api/jobs/c/unsave", json={}, headers=H)
    assert [j["uid"] for j in listing(client, saved=1)] == ["a"]
    assert client.get("/api/stats", headers=H).get_json()["saved"] == 1
    assert len(listing(client)) == 3


def test_api_salvato_chiuso_si_vede_con_avail_closed(client, dbx):
    add(dbx, "u1")
    client.post("/api/jobs/u1/save", json={}, headers=H)
    dbx.set_avail("u1", "closed", None, "chiuso dalla fonte")
    r = listing(client, saved=1)
    assert len(r) == 1 and r[0]["avail"] == "closed" and r[0]["saved"] is True
    assert listing(client) == []


def test_api_scartare_un_salvato_chiede_conferma(client, dbx):
    add(dbx, "u1")
    client.post("/api/jobs/u1/save", json={}, headers=H)
    r = client.post("/api/job/u1/status", json={"status": "discarded"}, headers=H)
    assert r.status_code == 409 and r.get_json()["saved"] is True and r.get_json()["ok"] is False
    st = dbx.conn.execute("SELECT status, saved_at FROM jobs WHERE uid='u1'").fetchone()
    assert st["status"] != "discarded" and st["saved_at"]  # niente e' cambiato in silenzio
    r = client.post("/api/job/u1/status", json={"status": "discarded", "unsave": True}, headers=H)
    assert r.status_code == 200
    st = dbx.conn.execute("SELECT status, saved_at FROM jobs WHERE uid='u1'").fetchone()
    assert st["status"] == "discarded" and st["saved_at"] is None


def test_api_candidatura_dentro_un_salvato(client, dbx):
    add(dbx, "u1")
    client.post("/api/jobs/u1/save", json={}, headers=H)
    assert client.post("/api/job/u1/status", json={"status": "applied"}, headers=H).status_code == 200
    r = dbx.conn.execute("SELECT status, saved_at FROM jobs WHERE uid='u1'").fetchone()
    assert r["status"] == "applied" and r["saved_at"]
    assert client.get("/api/apps", headers=H).get_json()  # compare in Candidature


def test_api_dettaglio_annuncio_espone_saved(client, dbx):
    add(dbx, "u1")
    assert client.get("/api/job/u1", headers=H).get_json()["saved"] is False
    client.post("/api/jobs/u1/save", json={}, headers=H)
    assert client.get("/api/job/u1", headers=H).get_json()["saved"] is True


def test_nessun_dato_in_piu_verso_l_esterno():
    src = (ROOT / "jobshunter" / "gui" / "app.py").read_text(encoding="utf-8")
    i = src.index("def job_save(")
    j = src.index("def job_unsave(")
    for body in (src[i:j], src[j:j + 600]):
        assert "net.client" not in body and "httpx" not in body and "requests" not in body


# ------------------------------------------------------------- stato tutorial ----
def test_tutorial_stato_nelle_impostazioni_non_nel_browser(client, dbx):
    assert client.get("/api/onboarding", headers=H).get_json()["tutorial_seen"] is False
    assert client.post("/api/tutorial/seen", json={"seen": True}, headers=H).get_json() == {"ok": True, "tutorial_seen": True}
    assert dbx.kv_get(onboarding.KV_TUTORIAL) == "1"
    assert client.get("/api/onboarding", headers=H).get_json()["tutorial_seen"] is True
    assert client.post("/api/tutorial/seen", json={"seen": False}, headers=H).get_json()["tutorial_seen"] is False
    assert client.get("/api/onboarding", headers=H).get_json()["tutorial_seen"] is False
    assert client.post("/api/tutorial/seen", json={"seen": "si"}, headers=H).status_code == 400
    assert client.post("/api/tutorial/seen", json={}, headers={"Host": "evil.example"}).status_code == 403


# --------------------------------------------------- correzioni B111-B118 (fase 8, giro del tester) ----
def test_cli_mark_discarded_su_un_salvato_si_rifiuta_senza_unsave(dbx, home):
    from click.testing import CliRunner
    from jobshunter.cli import main

    add(dbx, "abc123")
    dbx.save_job("abc123")
    r = CliRunner().invoke(main, ["mark", "abc123", "discarded"])
    assert r.exit_code == 1 and "salvato" in r.output and "--unsave" in r.output
    row = dbx.conn.execute("SELECT status, saved_at FROM jobs WHERE uid='abc123'").fetchone()
    assert row["status"] != "discarded" and row["saved_at"]
    r = CliRunner().invoke(main, ["mark", "abc123", "discarded", "--unsave"])
    assert r.exit_code == 0
    row = dbx.conn.execute("SELECT status, saved_at FROM jobs WHERE uid='abc123'").fetchone()
    assert row["status"] == "discarded" and row["saved_at"] is None


def test_ricerca_con_underscore_e_percentuale_cerca_il_carattere_vero(client, dbx):
    add(dbx, "u1", title="Dev_Ops 100% remoto")
    add(dbx, "u2", title="Dev Ops remoto")
    assert [j["uid"] for j in listing(client, q="Dev_Ops")] == ["u1"]
    assert [j["uid"] for j in listing(client, q="100%25")] == ["u1"]


def test_vista_salvati_e_conteggio_non_dipendono_dal_profilo(client, dbx):
    add(dbx, "u1")
    dbx.save_job("u1")
    pid = client.get("/api/profiles", headers=H).get_json()[0]["id"]
    assert [j["uid"] for j in listing(client, saved=1, profile=pid)] == ["u1"]
    assert client.get(f"/api/stats?profile={pid}", headers=H).get_json()["saved"] == 1
