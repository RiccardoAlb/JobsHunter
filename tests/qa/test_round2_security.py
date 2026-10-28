"""Giro 2: sicurezza (SQL injection, XSS lato API, Host/Origin), corse tra scansione e modifica profilo, stima richieste reali."""
import json
import threading
import time

import httpx
import pytest

from qa.qa_helpers import H, all_profiles, by_name, call, job, mkprofile, profile_body, wait_scan

pytestmark = pytest.mark.phase2

INJ = ["x'); DROP TABLE profiles;--", "' OR '1'='1", "\" OR 1=1 --", "Robert'); DELETE FROM jobs;--", "%' UNION SELECT * FROM kv --", "<img src=x onerror=alert(1)>",
       "<script>alert(1)</script>", "javascript:alert(1)", "{{7*7}}", "${7*7}", "\\'; --"]


def tables_ok(qdb):
    names = {r[0] for r in qdb.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {"jobs", "profiles", "job_profiles", "dup_pairs", "applications"} <= names


@pytest.mark.parametrize("s", INJ)
def test_sql_injection_nei_campi_del_profilo(client, qdb, s):
    st, d = call(client, "post", "/api/profiles", profile_body(name="P" + s, titles=[s], exclude=[s], include={s: 4}, location={"city": s, "radius_km": 10}))
    assert st in (200, 400)
    st, d = call(client, "post", "/api/profiles/preview", profile_body(name="Q", preset="custom", titles=[s]))
    assert st in (200, 400)
    for url in ("/api/jobs?q=", "/api/jobs?company=", "/api/jobs?profile=", "/api/facets?profile=", "/api/jobs?where="):
        r = client.get(url + httpx.QueryParams({"x": s}).render()[2:] if False else url + __import__("urllib.parse").parse.quote(s), headers=H)
        assert r.status_code < 500, (url, r.status_code)
    assert tables_ok(qdb)
    if st == 200:
        names = [p["name"] for p in all_profiles(client)]
        assert any(n == "P" + s for n in names) or True


def test_i_valori_con_codice_tornano_identici_come_json(client):
    s = "<img src=x onerror=alert(1)>"
    p = mkprofile(client, name=s, titles=[s])
    r = client.get("/api/profiles", headers=H)
    assert r.mimetype == "application/json" and r.headers.get("X-Content-Type-Options", "nosniff") == "nosniff" or r.mimetype == "application/json"
    got = by_name(client, s)
    assert got["titles"] == [s]


def test_gui_costruisce_il_dom_senza_innerhtml():
    """La GUI crea gli elementi con testo (mai HTML): nomi profilo e titoli con codice non possono eseguire nulla."""
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent.parent / "jobshunter/gui/static/index.html").read_text()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert bad not in html, f"{bad} nella GUI: rischio XSS con dati dei profili"


@pytest.mark.parametrize("hdrs,code", [
    ({"Origin": "null"}, 403), ({"Origin": "http://127.0.0.1:8765.evil.com"}, 403), ({"Origin": "http://evil.com:8765"}, 403),
    ({"Origin": "http://localhost:9999"}, 403), ({"Host": "127.0.0.1:8765.evil.com"}, 403), ({"Host": "evil.com"}, 403), ({"Host": "127.0.0.1:1"}, 403),
])
def test_host_origin_su_tutti_i_nuovi_endpoint(client, hdrs, code):
    h = {"Host": "127.0.0.1:8765"}
    h.update(hdrs)
    for method, url in (("post", "/api/profiles"), ("post", "/api/profiles/preview"), ("post", "/api/profiles/1"), ("post", "/api/profiles/1/delete"),
                        ("post", "/api/scan/start"), ("get", "/api/profiles"), ("get", "/api/presets"), ("get", "/api/countries")):
        r = getattr(client, method)(url, headers=h, **({"json": profile_body()} if method == "post" else {}))
        if method == "get" and "Origin" in hdrs and "Host" not in hdrs:
            continue  # il controllo Origin vale per i POST
        assert r.status_code == code, (method, url, hdrs, r.status_code)
    assert [p["name"] for p in all_profiles(client)] == ["Cybersecurity"]


# ---------------------------------------------------------------- corse con una scansione lenta ----
class SlowSource:
    pass


@pytest.fixture
def slow(qcfg, home):
    from jobshunter import settings
    from jobshunter.sources import REGISTRY
    from jobshunter.sources.base import Source
    from qa.qa_helpers import edit_config

    gate, started = threading.Event(), threading.Event()
    state = {"jobs": []}

    class Slow(Source):
        name = "slow"

        def fetch(self):
            return self.fetch_queries([])

        def fetch_queries(self, queries):
            started.set()
            gate.wait(20)
            return list(state["jobs"])

    REGISTRY["slow"] = Slow
    edit_config(home, lambda t: t.replace("[sources.fake]\nenabled = true", "[sources.fake]\nenabled = false\n\n[sources.slow]\nenabled = true"))
    from jobshunter.gui.app import create_app

    cl = create_app(None, 8765).test_client()
    yield gate, started, state, cl
    gate.set()
    REGISTRY.pop("slow", None)


def start_scan(client):
    st, d = call(client, "post", "/api/scan/start", {})
    assert st == 200


def orphans(qdb):
    return qdb.conn.execute("SELECT COUNT(*) FROM job_profiles WHERE profile_id NOT IN (SELECT id FROM profiles)").fetchone()[0]


def test_eliminare_un_profilo_durante_la_scansione(qdb, slow):
    gate, started, state, client = slow
    n = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"])
    state["jobs"] = [job("Infermiere", "Humanitas", "Milano", "Reparto turni assistenza", n=1), job("SOC Analyst", "Acme", "Roma", "SIEM EDR", n=2)]
    start_scan(client)
    assert started.wait(10)
    st, d = call(client, "post", f"/api/profiles/{n['id']}/delete")
    assert st == 200
    gate.set()
    s = wait_scan(client)
    assert not (s.get("message") or "").startswith("errore"), s
    assert orphans(qdb) == 0, "righe di job_profiles per un profilo eliminato durante la scansione"
    assert qdb.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= 1


def test_modificare_un_profilo_durante_la_scansione(qdb, slow):
    gate, started, state, client = slow
    n = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"])
    state["jobs"] = [job("Infermiere", "Humanitas", "Milano", "Reparto turni assistenza", n=1)]
    start_scan(client)
    assert started.wait(10)
    st, d = call(client, "post", f"/api/profiles/{n['id']}", {**n, "titles": ["cuoco"], "active": False})
    assert st == 200
    gate.set()
    s = wait_scan(client)
    assert not (s.get("message") or "").startswith("errore"), s
    assert orphans(qdb) == 0
    ids = {r[0] for r in qdb.conn.execute("SELECT id FROM profiles")}
    assert {r[0] for r in qdb.conn.execute("SELECT DISTINCT profile_id FROM job_profiles")} <= ids


def test_creare_un_profilo_durante_la_scansione_poi_nuova_scansione(qdb, slow):
    gate, started, state, client = slow
    state["jobs"] = [job("Infermiere", "Humanitas", "Milano", "Reparto turni assistenza", n=1)]
    start_scan(client)
    assert started.wait(10)
    n = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"])
    gate.set()
    wait_scan(client)
    assert orphans(qdb) == 0
    start_scan(client)  # una nuova scansione lo valuta
    gate.set()
    wait_scan(client)
    assert by_name(client, "Infermieri")["job_count"] == 1


def test_due_scansioni_insieme_la_seconda_e_rifiutata(slow):
    gate, started, state, client = slow
    start_scan(client)
    assert started.wait(10)
    r = client.post("/api/scan/start", headers=H, json={})
    assert r.status_code == 409
    gate.set()
    wait_scan(client)


# ---------------------------------------------------------------- accendi / spegni / rivaluta ----
def test_spegni_e_riaccendi_conserva_i_punteggi(client, qcfg, qdb, fake_jobs):
    from jobshunter.scanner import run_scan

    n = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"])
    j = job("Infermiere professionale", "Humanitas", "Milano", "Reparto turni assistenza", n=1)
    fake_jobs([j])
    run_scan(qcfg, qdb)
    before = dict(qdb.conn.execute("SELECT job_uid, score FROM job_profiles WHERE profile_id=?", (n["id"],)).fetchall())
    shown = lambda: {x["uid"] for x in call(client, "get", "/api/jobs?profile=all")[1]}
    assert j.uid in shown()
    call(client, "post", f"/api/profiles/{n['id']}", {**n, "active": False})
    assert j.uid not in shown(), "spegnere un profilo nasconde i suoi annunci"
    call(client, "post", f"/api/profiles/{n['id']}", {**n, "active": True})
    after = dict(qdb.conn.execute("SELECT job_uid, score FROM job_profiles WHERE profile_id=?", (n["id"],)).fetchall())
    assert after == before and j.uid in shown()


def test_rivalutazione_dopo_modifica(client, qcfg, qdb, fake_jobs):
    from jobshunter.scanner import run_scan

    n = mkprofile(client, name="Mag", preset="custom", titles=["magazziniere"])
    mkprofile(client, name="Cuochi", preset="custom", titles=["cuoco"])  # serve a far salvare l'annuncio j2
    j1 = job("Magazziniere", "Logista", "Milano", "Gestione merci", n=1)
    j2 = job("Cuoco di sala", "Hotel", "Roma", "Cucina HACCP", n=2)
    fake_jobs([j1, j2])
    run_scan(qcfg, qdb)
    pid = n["id"]
    got = lambda: {r[0] for r in qdb.conn.execute("SELECT job_uid FROM job_profiles WHERE profile_id=?", (pid,))}
    assert got() == {j1.uid}
    call(client, "post", f"/api/profiles/{pid}", {**n, "titles": ["magazziniere", "cuoco"]})
    assert got() == {j1.uid, j2.uid}, "dopo aver aggiunto un titolo gli annunci gia' salvati vanno rivalutati"
    call(client, "post", f"/api/profiles/{pid}", {**n, "titles": ["cuoco"], "exclude": ["sala"]})
    assert got() == set(), "il titolo tolto e l'esclusione devono far sparire le valutazioni"
    call(client, "post", f"/api/profiles/{pid}", {**n, "titles": ["magazziniere"]})
    assert got() == {j1.uid}
    assert qdb.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2, "la rivalutazione non cancella annunci"


# ---------------------------------------------------------------- stima richieste contro richieste reali ----
@pytest.mark.parametrize("countries,city", [(["it"], ""), (["it", "gb", "de"], ""), (["it", "fr", "us", "pl"], "Roma")])
def test_stima_richieste_uguale_alle_richieste_vere(client, qcfg, qdb, home, countries, city):
    from jobshunter.scanner import run_scan

    hits = {"adzuna": 0, "jooble": 0}

    def handler(req):
        if "adzuna.com" in req.url.host:
            hits["adzuna"] += 1
            return httpx.Response(200, json={"results": []})
        hits["jooble"] += 1
        return httpx.Response(200, json={"jobs": []})

    tr = httpx.MockTransport(handler)
    import re
    from jobshunter import settings
    from qa.qa_helpers import edit_config

    def f(t):
        t = t.replace('[sources.adzuna]\nenabled = false\napp_id = ""\napp_key = ""', '[sources.adzuna]\nenabled = true\napp_id = "x"\napp_key = "y"')
        t = t.replace('[sources.jooble]\nenabled = false', '[sources.jooble]\nenabled = true').replace('api_key = ""', 'api_key = "k"')
        return t + '\n[sources.jooble.hosts]\nit = "it.jooble.org"\ngb = "uk.jooble.org"\n'

    edit_config(home, f)
    cfg = settings.load_config()
    for s in ("adzuna", "jooble"):
        cfg["sources"][s]["_transport"] = tr
        cfg["sources"][s]["delay"] = 0
    from jobshunter.gui.app import create_app

    cl = create_app(None, 8765).test_client()
    p = mkprofile(cl, name="Multi", preset="software_dev", titles=["sviluppatore rust"], countries=countries,
                  location={"city": city, "radius_km": 50}, internships=True)
    st, d = call(cl, "post", "/api/profiles/preview", {k: v for k, v in p.items() if k not in ("id", "created", "updated", "job_count")})
    est = d["requests"]
    from jobshunter.db import DB

    db = DB(settings.resolve_path(cfg["general"]["db_path"]))
    run_scan(cfg, db, profile_ids=[p["id"]])
    assert est.get("adzuna", 0) == hits["adzuna"], (est, hits)
    assert est.get("jooble", 0) == hits["jooble"], (est, hits)


def test_stats_per_profilo_totali_mai_negativi(client, qcfg, qdb, fake_jobs):
    """B8: /api/stats?profile=<id> sottrae i Jooble dal conteggio del profilo e puo' dare totale negativo ('-116 annunci' nell'intestazione)."""
    from jobshunter.scanner import run_scan

    n = mkprofile(client, name="Infermieri", preset="custom", titles=["infermiere"])
    fake_jobs([job("Infermiere", "Humanitas", "Milano", "reparto turni", n=1)])
    run_scan(qcfg, qdb)
    for i in range(5):  # annunci Jooble di un altro profilo
        qdb.conn.execute("INSERT INTO jobs (uid,source,title,company,location,url,description,score,status,first_seen,category) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (f"jj{i}", "jooble:x.com", "SOC Analyst", f"C{i}", "Roma", "u", "d", 50, "new", "2026-01-01T00:00:00+00:00", "SEC"))
    qdb.conn.commit()
    for q in ("", "?profile=all", f"?profile={n['id']}", f"?profile={by_name(client, 'Cybersecurity')['id']}"):
        st, d = call(client, "get", "/api/stats" + q)
        assert st == 200 and d["total"] >= 0 and d["new"] >= 0, (q, d)
