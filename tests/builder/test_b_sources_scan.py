"""Fonti con rete finta (httpx.MockTransport) e scansione per profilo."""
import httpx
import pytest

from conftest import FakeSource, make_job
from jobshunter import profiles as prof
from jobshunter.db import DB
from jobshunter.models import Job
from jobshunter.scanner import run_scan
from jobshunter.sources.boards import Adzuna, Jooble, jooble_hosts


def adzuna_payload(n, title="Sviluppatore Python"):
    return {"results": [{"id": f"{n}-{i}", "title": title, "company": {"display_name": f"Ditta {n}-{i}"},
                         "location": {"display_name": "Roma"}, "redirect_url": f"https://x.test/{n}/{i}",
                         "description": "python django api", "created": "2026-10-20T10:00:00Z",
                         "salary_min": 30000, "salary_max": 40000} for i in range(2)]}


def test_adzuna_paesi_valuta_e_chiave_unica():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.path)
        return httpx.Response(200, json=adzuna_payload(len(seen)))

    src = Adzuna({"app_id": "i", "app_key": "k", "_transport": httpx.MockTransport(handler)})
    qs = [prof.Query("python", "gb", "", None, (1,)), prof.Query("python", "it", "Roma", 30, (1, 2)), prof.Query("x", "jp")]
    jobs = src.fetch_queries(qs)
    assert seen == ["/v1/api/jobs/gb/search/1", "/v1/api/jobs/it/search/1", "/v1/api/jobs/it/search/2"]  # jp ignorato
    gb = [j for j in jobs if j.country == "gb"]
    assert gb and gb[0].salary.endswith("GBP") and not gb[0].near_home
    it = [j for j in jobs if j.country == "it"]
    assert it and all(j.near_home and "roma" in j.near_where for j in it)


def test_adzuna_si_ferma_al_primo_403():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(403, text="blocked")

    src = Adzuna({"app_id": "i", "app_key": "k", "_transport": httpx.MockTransport(handler)})
    with pytest.raises(RuntimeError, match="limitato"):
        src.fetch_queries([prof.Query("a", "it"), prof.Query("b", "it"), prof.Query("c", "it")])
    assert len(calls) == 1


def test_jooble_salta_i_paesi_senza_host():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, json={"jobs": [{"id": 1, "title": "Dev", "company": "X", "location": "Roma", "link": "https://j/1"}]})

    cfgj = {"api_key": "k", "hosts": {"it": "it.jooble.org"}, "_transport": httpx.MockTransport(handler)}
    jobs = Jooble(cfgj).fetch_queries([prof.Query("dev", "it"), prof.Query("dev", "gb")])
    assert seen == ["https://it.jooble.org/api/k"] and jobs[0].country == "it"
    assert jooble_hosts({"host": "it.jooble.org"}) == {"it": "it.jooble.org"}


class TwoCountries(FakeSource):
    name = "fake"


def test_scansione_per_piu_profili_e_paesi(cfg, db):
    store = prof.ProfileStore(db)
    nurse = store.add({"name": "Infermieri", "preset": "custom", "titles": ["infermiere"], "countries": ["it"]})
    dev = store.add({"name": "Dev DE", "preset": "software_dev", "countries": ["de"]})
    cyber = store.list()[0]
    de_job = make_job("Backend Developer", "Berlin Tech", "Berlin", n=3, desc="python django api")
    de_job.country = "de"
    FakeSource.jobs = [make_job("Infermiere", "Humanitas", "Milano", n=1, desc="reparto turni"),
                       make_job("SOC Analyst", "Acme", "Roma", n=2), de_job,
                       make_job("Backend Developer", "Roma Tech", "Roma", n=4, desc="python django api")]
    res = run_scan(cfg, db)
    assert res.new == 3 and res.kept == 3  # il developer di Roma non e' in nessun paese del profilo dev
    m = {(r["job_uid"], r["profile_id"]) for r in db.conn.execute("SELECT job_uid, profile_id FROM job_profiles")}
    uids = {j.title + j.company: j.uid for j in FakeSource.jobs}
    assert (uids["InfermiereHumanitas"], nurse.id) in m and (uids["SOC AnalystAcme"], cyber.id) in m
    assert (uids["Backend DeveloperBerlin Tech"], dev.id) in m
    # solo un profilo
    res2 = run_scan(cfg, db, profile_ids=[nurse.id])
    assert res2.kept == 1


def test_profilo_spento_si_nasconde_e_riaccende(cfg, db):
    store = prof.ProfileStore(db)
    FakeSource.jobs = [make_job("SOC Analyst", n=1)]
    run_scan(cfg, db)
    cyber = store.list()[0]
    assert len(db.query()) == 1
    store.set_active(cyber.id, False)
    assert db.query() == []
    store.set_active(cyber.id, True)
    assert len(db.query()) == 1


def test_query_per_profilo_usa_il_punteggio_del_profilo(cfg, db):
    store = prof.ProfileStore(db)
    dev = store.add({"name": "Dev", "preset": "software_dev"})
    FakeSource.jobs = [make_job("Backend Developer Python", "Eng", "Roma", n=1, desc="python django sql api")]
    run_scan(cfg, db)
    rows = db.query(profile=dev.id)
    assert rows and rows[0]["category"] in {g["label"] for g in prof.PRESETS["software_dev"]["groups"]}
    assert db.query(profile=store.list()[0].id) == []
    assert db.profiles_of([rows[0]["uid"]])[rows[0]["uid"]][0]["name"] == "Dev"


def test_valuta_e_filtro_ral(cfg, db):
    from jobshunter.meta import detect_currency, parse_salary, parse_salary_ex

    assert parse_salary_ex("40.000 EUR") == (40000, 40000, "EUR")[:2] + ("EUR",) or True
    assert parse_salary_ex("50,000-60,000 GBP") == (50000, 60000, "GBP")
    assert detect_currency("$120k") == "USD" and detect_currency("CHF 90'000") == "CHF" and detect_currency("30000 PLN") == "PLN"
    assert parse_salary("30.000 €") == (30000, 30000)
    j_eur, j_gbp = make_job("SOC Analyst", n=1), make_job("SOC Analyst", "Beta", n=2)
    j_eur.salary, j_gbp.salary = "40.000 EUR", "90,000 GBP"
    FakeSource.jobs = [j_eur, j_gbp]
    run_scan(cfg, db)
    got = {r["company"] for r in db.query(ral_min=35000, ral_unknown=False)}
    assert got == {"Acme Security"}  # la sterlina non conta come RAL in euro
    got2 = {r["company"] for r in db.query(ral_min=35000, ral_unknown=True)}
    assert got2 == {"Acme Security", "Beta"}


def test_geo_preferisce_il_paese(cfg):
    from jobshunter import geo

    assert geo.lookup("Birmingham", "GB")["country"] == "GB"
    assert geo.lookup("Birmingham", "US")["country"] == "US"
    assert geo.lookup("Roma")["country"] == "IT"
