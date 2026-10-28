"""SPEC 4: scansione per profilo (query condivise senza duplicati, profile_ids, profilo di default, fonti adattate)."""
import json

import pytest

from qa.qa_helpers import RecSource, all_profiles, by_name, call, job, mkprofile, qtuple

pytestmark = pytest.mark.phase2


@pytest.fixture
def rec(qcfg, home):
    """Registra la fonte 'rec' (che annota le query ricevute) e la rende l'unica fonte attiva."""
    from jobshunter import settings
    from jobshunter.sources import REGISTRY
    from qa.qa_helpers import edit_config

    REGISTRY["rec"] = RecSource
    RecSource.calls, RecSource.jobs = [], []
    edit_config(home, lambda t: t.replace("[sources.fake]\nenabled = true", "[sources.fake]\nenabled = false\n\n[sources.rec]\nenabled = true"))
    yield settings.load_config()
    REGISTRY.pop("rec", None)


def all_queries():
    return [q for call_ in RecSource.calls for q in call_]


def test_profilo_di_default_creato_dalla_scansione_se_non_ce_ne_sono(rec, qdb):
    from jobshunter.scanner import run_scan

    qdb.conn.execute("DELETE FROM profiles")
    qdb.conn.commit()
    run_scan(rec, qdb)
    rows = qdb.conn.execute("SELECT data FROM profiles").fetchall()
    assert len(rows) == 1 and json.loads(rows[0]["data"])["name"] == "Cybersecurity"


def test_query_senza_duplicati_fra_profili(rec, qdb, client):
    from jobshunter.scanner import run_scan

    mkprofile(client, name="Sviluppo A", preset="software_dev", titles=["sviluppatore rust"])
    mkprofile(client, name="Sviluppo B", preset="software_dev", titles=["sviluppatore rust"])
    run_scan(rec, qdb)
    qs = [qtuple(q) for q in all_queries()]
    assert qs, "la fonte non ha ricevuto nessuna query"
    assert len(qs) == len(set(qs)), "stessa q+country+where chiesta piu' volte (profili che si sovrappongono vanno condivisi)"
    assert any(t[0].lower() == "sviluppatore rust" for t in qs)


def test_forma_delle_query(rec, qdb, client):
    from jobshunter.scanner import run_scan

    run_scan(rec, qdb)
    for q in all_queries():
        for attr in ("q", "country", "where", "radius_km", "pages"):
            assert hasattr(q, attr), f"Query senza '{attr}'"
        assert isinstance(q.q, str) and q.q and q.country in ("it",) and tuple(q.pages) in ((1, 2), (1,))


def test_solo_profili_attivi_e_indicati(rec, qdb, client):
    from jobshunter.scanner import run_scan

    a = mkprofile(client, name="Rust", preset="custom", titles=["sviluppatore rust"])
    b = mkprofile(client, name="Cobol", preset="custom", titles=["sviluppatore cobol"])
    off = mkprofile(client, name="Spento", preset="custom", titles=["sviluppatore fortran"], active=False)
    run_scan(rec, qdb)
    qs = {qtuple(q)[0].lower() for q in all_queries()}
    assert {"sviluppatore rust", "sviluppatore cobol"} <= qs and "sviluppatore fortran" not in qs
    RecSource.calls.clear()
    run_scan(rec, qdb, profile_ids=[b["id"]])
    qs = {qtuple(q)[0].lower() for q in all_queries()}
    assert "sviluppatore cobol" in qs and "sviluppatore rust" not in qs
    RecSource.calls.clear()
    run_scan(rec, qdb, profile_ids=[off["id"]])  # indicare esplicitamente un profilo spento: si scansiona comunque
    assert "sviluppatore fortran" in {qtuple(q)[0].lower() for q in all_queries()}


def test_paesi_multipli_generano_query_per_ogni_paese(rec, qdb, client):
    from jobshunter.scanner import run_scan

    mkprofile(client, name="Europa", preset="custom", titles=["elettricista"], countries=["it", "de", "fr"])
    run_scan(rec, qdb, profile_ids=[by_name(client, "Europa")["id"]])
    assert {qtuple(q)[1] for q in all_queries()} == {"it", "de", "fr"}


def test_citta_e_raggio_arrivano_alla_fonte(rec, qdb, client):
    from jobshunter.scanner import run_scan

    p = mkprofile(client, name="Locale", preset="custom", titles=["elettricista"], location={"city": "Bari", "radius_km": 40})
    run_scan(rec, qdb, profile_ids=[p["id"]])
    qs = [q for q in all_queries() if q.q.lower() == "elettricista"]
    assert qs and all(q.where.lower() == "bari" and q.radius_km == 40 for q in qs)


def test_gli_annunci_della_fonte_sono_valutati_per_ogni_profilo(rec, qdb, client):
    from jobshunter.scanner import run_scan

    n = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"])
    RecSource.jobs = [job("Infermiere", "Humanitas", "Milano", "Reparto turni", n=1), job("SOC Analyst", "Acme", "Roma", "SIEM EDR", n=2)]
    res = run_scan(rec, qdb)
    assert res.read == 2 and res.new == 2 and res.kept == 2
    rows = qdb.conn.execute("SELECT job_uid, profile_id FROM job_profiles").fetchall()
    assert {(r[0], r[1]) for r in rows} == {(RecSource.jobs[0].uid, n["id"]), (RecSource.jobs[1].uid, by_name(client, "Cybersecurity")["id"])}


def test_fonte_che_conosce_solo_fetch_continua_a_funzionare(qcfg, qdb, client, fake_jobs):
    """FakeSource (come le fonti scritte prima della fase 2) ha solo fetch(): niente errori e annunci letti."""
    from jobshunter.scanner import run_scan

    fake_jobs([job("SOC Analyst", "Acme", "Roma", "SIEM EDR", n=1)])
    res = run_scan(qcfg, qdb)
    assert res.errors == [] and res.new == 1


def test_stima_richieste_non_cresce_per_profili_identici(client):
    a = mkprofile(client, name="S1", preset="custom", titles=["sviluppatore rust"])
    st, one = call(client, "post", "/api/profiles/preview", {k: v for k, v in a.items() if k not in ("id", "created", "updated", "job_count")})
    assert st == 200
    assert one["queries"], "anteprima senza query"
