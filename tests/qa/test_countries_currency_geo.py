"""SPEC 3: piu' paesi (COUNTRIES, query per lingua, fonti per paese), valuta e filtro RAL, geo con paese."""
import re

import pytest

from qa.qa_helpers import call, edit_config, profile_body

pytestmark = pytest.mark.phase2

REQUIRED = ["it", "gb", "de", "fr", "es", "nl", "at", "ch", "be", "pl", "us", "ca", "au", "br", "in", "mx", "nz", "sg", "za"]
CURRENCY = {"it": "EUR", "gb": "GBP", "de": "EUR", "fr": "EUR", "es": "EUR", "nl": "EUR", "at": "EUR", "ch": "CHF", "be": "EUR",
            "pl": "PLN", "us": "USD", "ca": "CAD", "au": "AUD", "br": "BRL", "in": "INR", "mx": "MXN", "nz": "NZD", "sg": "SGD", "za": "ZAR"}
NAME_IT = {"it": "Italia", "gb": "Regno Unito", "de": "Germania", "fr": "Francia", "es": "Spagna", "us": "Stati Uniti", "ch": "Svizzera"}
LANG = {"it": "it", "de": "de", "fr": "fr", "es": "es", "gb": "en", "us": "en"}


def test_countries_python():
    from jobshunter.profiles import COUNTRIES

    for c in REQUIRED:
        assert c in COUNTRIES, f"manca il paese {c}"
        e = COUNTRIES[c]
        assert e["name"].strip() and re.fullmatch(r"[A-Z]{3}", e["currency"])
        assert e["languages"] and all(isinstance(x, str) for x in e["languages"])
        assert isinstance(e["adzuna"], bool)
        assert not any(d in e["name"] for d in ("—", "–"))
    for c, cur in CURRENCY.items():
        assert COUNTRIES[c]["currency"] == cur, f"{c}: valuta attesa {cur}"
    for c, n in NAME_IT.items():
        assert COUNTRIES[c]["name"] == n, f"{c}: nome in italiano atteso '{n}'"
    assert COUNTRIES["it"]["languages"][0] == "it" and COUNTRIES["de"]["languages"][0] == "de"


def test_api_countries(client):
    st, d = call(client, "get", "/api/countries")
    assert st == 200 and isinstance(d, list)
    by = {c["code"]: c for c in d}
    assert set(REQUIRED) <= set(by)
    assert len(by) == len(d), "codici duplicati"
    for c in REQUIRED:
        e = by[c]
        assert set(e) >= {"code", "name", "currency", "languages", "adzuna"}
    assert d[0]["code"] == "it" or by["it"], "l'Italia e' il paese di default"


# ------------------------------------------------------------ query per paese e lingua ----
def preview(client, **over):
    st, d = call(client, "post", "/api/profiles/preview", profile_body(name="P", **over))
    assert st == 200, d
    return d


def preset_queries(client, key):
    from jobshunter.profiles import PRESETS

    return {lang: [q.lower() for q in lst] for lang, lst in PRESETS[key]["queries"].items()}


def test_query_per_lingua_del_paese(client):
    d = preview(client, preset="software_dev", countries=["it", "de", "fr", "gb"], internships=False)
    pq = preset_queries(client, "software_dev")
    for q in d["queries"]:
        lang = LANG[q["country"]]
        lang = lang if lang in pq else "en"
        assert q["q"].lower() in pq[lang], f"{q['country']}: '{q['q']}' non e' una query in lingua '{lang}' del preset"
    assert {q["country"] for q in d["queries"]} == {"it", "de", "fr", "gb"}


def test_lingua_assente_nel_preset_ripiega_sull_inglese(client):
    """Paesi baltici/olandesi non hanno una lista di query propria: si usa l'inglese."""
    d = preview(client, preset="software_dev", countries=["nl"], internships=False)
    pq = preset_queries(client, "software_dev")
    assert d["queries"] and all(q["q"].lower() in pq["en"] for q in d["queries"])


def test_titoli_liberi_valgono_per_ogni_paese(client):
    d = preview(client, preset="software_dev", titles=["sviluppatore cobol"], countries=["it", "gb"], internships=False)
    for c in ("it", "gb"):
        assert "sviluppatore cobol" in {q["q"].lower() for q in d["queries"] if q["country"] == c}


def test_nessuna_query_duplicata_nel_profilo(client):
    d = preview(client, preset="cybersecurity", titles=["soc analyst", "SOC Analyst", "penetration tester"], countries=["it", "gb"])
    keys = [(q["q"].lower(), q["country"], q.get("where", "")) for q in d["queries"]]
    assert len(keys) == len(set(keys)), "query duplicate (stessa q+country+where)"


def test_pagine_normali_e_stage(client):
    d = preview(client, preset="software_dev", countries=["it"], internships=True)
    pages = {tuple(q["pages"]) for q in d["queries"]}
    assert pages <= {(1, 2), (1,)} and (1, 2) in pages and (1,) in pages, pages
    d2 = preview(client, preset="software_dev", countries=["it"], internships=False)
    assert {tuple(q["pages"]) for q in d2["queries"]} == {(1, 2)}


def test_stage_non_aumentano_senza_internships(client):
    a = preview(client, preset="software_dev", internships=True)
    b = preview(client, preset="software_dev", internships=False)
    assert len(a["queries"]) > len(b["queries"])


def test_sede_e_raggio_nelle_query(client):
    d = preview(client, preset="software_dev", location={"city": "Palermo", "radius_km": 80}, internships=False)
    assert all(q["where"].lower() == "palermo" for q in d["queries"]), d["queries"][:2]
    d2 = preview(client, preset="software_dev", location={"city": "", "radius_km": 80}, internships=False)
    assert all(not q["where"] for q in d2["queries"]), "citta' vuota = tutto il paese"


# ------------------------------------------------------------ richieste stimate per fonte ----
@pytest.fixture
def fonti_attive(client, home, qcfg):
    """Adzuna e Jooble 'accese' con chiavi finte (nessuna richiesta parte: l'anteprima non fa rete), host Jooble per it e gb."""
    def f(t):
        t = t.replace('[sources.adzuna]\nenabled = false\napp_id = ""\napp_key = ""', '[sources.adzuna]\nenabled = true\napp_id = "x"\napp_key = "y"')
        t = t.replace('[sources.jooble]\nenabled = false', '[sources.jooble]\nenabled = true').replace('api_key = ""', 'api_key = "k"')
        t = re.sub(r"(\[sources\.(arbeitnow|remoteok|remotive)\]\nenabled = )false", r"\1true", t)
        return t + '\n[sources.jooble.hosts]\nit = "it.jooble.org"\ngb = "uk.jooble.org"\n'

    edit_config(home, f)
    from jobshunter.gui.app import create_app

    return create_app(None, 8765).test_client()


def req(client, **over):
    st, d = call(client, "post", "/api/profiles/preview", profile_body(name="R", **over))
    assert st == 200, d
    return d["requests"]


def test_adzuna_una_chiave_per_tutti_i_paesi_richieste_proporzionali(fonti_attive):
    r1 = req(fonti_attive, preset="software_dev", countries=["it"], internships=False)
    r3 = req(fonti_attive, preset="software_dev", countries=["it", "de", "fr"], internships=False)
    assert r1.get("adzuna", 0) > 0 and r3["adzuna"] >= 2 * r1["adzuna"]


def test_jooble_solo_paesi_con_host(fonti_attive):
    r_it = req(fonti_attive, preset="software_dev", countries=["it"], internships=False)
    r_mix = req(fonti_attive, preset="software_dev", countries=["it", "de"], internships=False)  # de senza host: saltato
    assert r_it.get("jooble", 0) > 0
    assert r_mix.get("jooble") == r_it.get("jooble"), "paesi senza host Jooble vanno saltati"
    r_gb = req(fonti_attive, preset="software_dev", countries=["gb"], internships=False)
    assert r_gb.get("jooble", 0) > 0
    r_de = req(fonti_attive, preset="software_dev", countries=["de"], internships=False)
    assert r_de.get("jooble", 0) == 0


def test_arbeitnow_solo_con_la_germania(fonti_attive):
    assert req(fonti_attive, preset="software_dev", countries=["it"]).get("arbeitnow", 0) == 0
    assert req(fonti_attive, preset="software_dev", countries=["it", "de"]).get("arbeitnow", 0) > 0


def test_fonti_remote_solo_se_remoto(fonti_attive):
    on = req(fonti_attive, preset="software_dev", remote=True)
    off = req(fonti_attive, preset="software_dev", remote=False)
    assert on.get("remoteok", 0) + on.get("remotive", 0) > 0
    assert off.get("remoteok", 0) == 0 and off.get("remotive", 0) == 0


def test_richieste_sono_numeri_interi_non_negativi(fonti_attive):
    for v in req(fonti_attive, preset="cybersecurity", countries=["it", "gb", "us"]).values():
        assert isinstance(v, int) and v >= 0


# ------------------------------------------------------------ valuta e RAL ----
def insert_job(db, uid, title, company, salary, location="Roma"):
    db.conn.execute("INSERT INTO jobs (uid,source,title,company,location,url,description,score,status,salary,first_seen,remote) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,0)", (uid, "fake", title, company, location, "https://example.org/" + uid,
                                                          "desc", 50, "new", salary, "2026-01-01T00:00:00+00:00"))
    db.conn.commit()


@pytest.mark.parametrize("salary,cur,lo,hi", [
    ("40.000 - 50.000 EUR", "EUR", 40000, 50000),
    ("26.500 € - 31.000 €", "EUR", 26500, 31000),
    ("£40,000 - £50,000", "GBP", 40000, 50000),
    ("GBP 35,000 per year", "GBP", 35000, 35000),
    ("$90,000 - $110,000", "USD", 90000, 110000),
    ("USD 120000", "USD", 120000, 120000),
    ("CHF 95,000 - 110,000", "CHF", 95000, 110000),
    ("PLN 120,000 - 150,000", "PLN", 120000, 150000),
])
def test_valuta_riconosciuta_e_salvata(qdb, salary, cur, lo, hi):
    insert_job(qdb, "j1", "Titolo", "Azienda", salary)
    qdb.backfill_meta()
    r = qdb.conn.execute("SELECT sal_currency, sal_min, sal_max FROM jobs WHERE uid='j1'").fetchone()
    assert r["sal_currency"] == cur, f"{salary!r}: valuta {r['sal_currency']!r}"
    assert (r["sal_min"], r["sal_max"]) == (lo, hi)


def test_senza_stipendio_nessuna_valuta(qdb):
    insert_job(qdb, "j1", "Titolo", "Azienda", "")
    qdb.backfill_meta()
    r = qdb.conn.execute("SELECT sal_currency, sal_min FROM jobs WHERE uid='j1'").fetchone()
    assert r["sal_min"] is None and not r["sal_currency"]


def test_colonne_nuove_presenti(qdb):
    cols = {r["name"] for r in qdb.conn.execute("PRAGMA table_info(jobs)")}
    assert {"sal_currency", "country"} <= cols
    tabs = {r[0] for r in qdb.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"profiles", "job_profiles"} <= tabs


def test_filtro_ral_vale_solo_per_la_valuta_del_profilo(client, qdb):
    insert_job(qdb, "eur_alto", "A", "Alfa", "40.000 - 45.000 EUR")
    insert_job(qdb, "eur_basso", "B", "Beta", "20.000 - 22.000 EUR")
    insert_job(qdb, "gbp_alto", "C", "Gamma", "£50,000 - £60,000")
    insert_job(qdb, "senza", "D", "Delta", "")

    def uids(q):
        st, d = call(client, "get", "/api/jobs?" + q)
        assert st == 200
        return {j["uid"] for j in d}

    strict = uids("ral_min=30000&ral_unk=0")
    assert strict == {"eur_alto"}, "la sterlina conta come RAL sconosciuta, quindi fuori con ral_unk=0"
    lenient = uids("ral_min=30000&ral_unk=1")
    assert lenient == {"eur_alto", "gbp_alto", "senza"}


# ------------------------------------------------------------ geo con paese ----
def test_geo_locate_senza_paese_come_oggi():
    from jobshunter import geo

    p = geo.locate("Milano, Provincia di Milano")
    assert p and abs(p[0] - 45.46) < 0.2 and abs(p[1] - 9.19) < 0.2
    assert geo.locate("Nowheresville Qwerty") is None


def test_geo_locate_con_paese_preferisce_quel_paese():
    from jobshunter import geo

    uk = geo.locate("Birmingham", country="gb")
    us = geo.locate("Birmingham", country="us")
    assert uk and us and uk != us
    assert abs(uk[0] - 52.48) < 0.5 and abs(us[0] - 33.52) < 0.5 and us[1] < -80
    lon_ca = geo.locate("London", country="ca")
    lon_gb = geo.locate("London", country="gb")
    assert lon_ca and lon_gb and lon_ca[1] < -70 and abs(lon_gb[1]) < 2


def test_geo_locate_paese_maiuscolo_o_minuscolo():
    from jobshunter import geo

    assert geo.locate("Birmingham", country="US") == geo.locate("Birmingham", country="us")


def test_geo_locate_paese_ignoto_non_esplode():
    from jobshunter import geo

    geo.locate("Roma", country="xx")  # nessuna eccezione; il risultato puo' essere il ripiego sul default
    assert geo.locate("Birmingham", country="") == geo.locate("Birmingham")
