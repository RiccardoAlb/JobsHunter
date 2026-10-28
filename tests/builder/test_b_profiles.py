"""Profili: validazione, archivio, migrazione, regole di punteggio, query."""
import json

import pytest

from conftest import make_job
from jobshunter import profiles as prof
from jobshunter.db import DB
from jobshunter.models import Job
from jobshunter.scoring import location_ok, score_job


def body(**over):
    b = {"name": "Prova", "preset": "software_dev", "titles": [], "countries": ["it"]}
    b.update(over)
    return b


def test_validazione_rifiuta_i_casi_sporchi():
    for bad in (body(name=""), body(name=None), body(preset="x"), body(preset=["a"]), body(countries=[]),
                body(countries=["xx"]), body(seniority="boss"), body(contracts=["foo"]),
                body(location={"city": "", "radius_km": 0}), body(location={"city": "", "radius_km": None}),
                body(include={"a": 99}), body(preset="custom"), "testo", None):
        with pytest.raises(prof.ProfileError):
            prof.validate_profile(bad)


def test_validazione_pulisce_i_caratteri_di_controllo():
    p = prof.validate_profile(body(name="a\x00b\n  c"))
    assert p.name == "a b c"


def test_migrazione_crea_cybersecurity_e_associa_gli_annunci(cfg, tmp_path):
    path = tmp_path / "vecchio.db"
    import sqlite3

    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE jobs (uid TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT, url TEXT,"
                      " description TEXT, posted_at TEXT, remote INTEGER, score INTEGER, category TEXT, matched TEXT,"
                      " status TEXT DEFAULT 'new', notified INTEGER DEFAULT 0, first_seen TEXT);"
                      "INSERT INTO jobs (uid,source,title,company,location,url,score,category,matched) VALUES"
                      " ('a1','adzuna','SOC Analyst','Acme','Roma','u',42,'BLUE','siem,soc');")
    con.commit()
    con.close()
    db = DB(path, cfg)
    store = prof.ProfileStore(db)
    [p] = store.list()
    assert p.name == "Cybersecurity" and p.preset == "cybersecurity" and p.countries == ["it"]
    row = db.conn.execute("SELECT score, category, matched FROM job_profiles WHERE job_uid='a1' AND profile_id=?", (p.id,)).fetchone()
    assert tuple(row) == (42, "BLUE", "siem,soc")
    DB(path, cfg)  # seconda apertura: nessun duplicato
    assert len(prof.ProfileStore(DB(path, cfg)).list()) == 1


def test_non_si_elimina_l_ultimo_profilo(db):
    store = prof.ProfileStore(db)
    with pytest.raises(prof.ProfileError):
        store.delete(store.list()[0].id)
    p = store.add(body())
    store.delete(p.id)
    assert [x.name for x in store.list()] == ["Cybersecurity"]


def test_profilo_di_default_vale_come_prima(cfg, db):
    """Il profilo Cybersecurity creato dalla migrazione da' gli stessi punteggi dell'algoritmo storico."""
    [p] = prof.ProfileStore(db).list()
    cases = [make_job("SOC Analyst", desc="SIEM EDR"), make_job("Junior Pentester", location="Palermo", desc="Burp Metasploit"),
             make_job("Senior Sistemista Linux", desc="Active Directory vmware"), make_job("Stage Cyber Security"),
             make_job("Account Executive", desc="security"), make_job("Cuoco")]
    for j in cases:
        a = score_job(Job(**{**j.__dict__}), cfg)
        b = score_job(Job(**{**j.__dict__}), cfg, p)
        assert (a is None) == (b is None)
        if a:
            assert (a.score, a.category, a.matched) == (b.score, b.category, b.matched), j.title


def test_custom_ricava_le_regole_dai_titoli():
    r = prof.build_rules(prof.validate_profile(body(preset="custom", titles=["magazziniere carrellista", "infermiere"])))
    terms = {t: w for _, g in r.groups for t, w in g.items()}
    assert terms["magazziniere carrellista"] == 12 and terms["magazziniere"] == 5 and terms["infermiere"] == 12
    assert r.flex


def test_riconosce_femminile_e_plurale(cfg):
    p = prof.validate_profile(body(preset="custom", titles=["infermiere"]))
    for t in ("Infermiera professionale", "Infermieri di sala", "INFERMIERE"):
        assert score_job(make_job(t, desc="turni"), cfg, p) is not None, t
    assert score_job(make_job("Infermieristica magazzino"), cfg, p) is None


def test_accenti_ignorati(cfg):
    p = prof.validate_profile(body(preset="custom", titles=["contabile"]))
    assert score_job(make_job("Contabilità", desc="x"), cfg, p) is None  # parola diversa
    p2 = prof.validate_profile(body(preset="custom", titles=["contabilita"]))
    assert score_job(make_job("Addetto Contabilità"), cfg, p2) is not None


def test_exclude_contratti_e_livello(cfg):
    p = prof.validate_profile(body(preset="software_dev", exclude=["php"], seniority="senior"))
    assert score_job(make_job("Sviluppatore PHP", desc="php"), cfg, p) is None
    j = score_job(make_job("Senior Backend Developer", desc="python django"), cfg, p)
    k = score_job(make_job("Junior Backend Developer", desc="python django"), cfg, p)
    assert j.score > k.score
    pc = prof.validate_profile(body(preset="software_dev", contracts=["internship"]))
    assert score_job(make_job("Backend Developer", desc="python"), cfg, pc) is None
    assert score_job(make_job("Stage Backend Developer", desc="python"), cfg, pc) is not None


def test_location_ok_per_paese_e_remoto(cfg):
    de = prof.validate_profile(body(countries=["de"], remote=True))
    it = prof.validate_profile(body(countries=["it"], remote=False))
    j = make_job(location="Berlin")
    j.country = "de"
    assert location_ok(j, cfg, de) and not location_ok(j, cfg, it)
    r = make_job(location="Remote")
    r.remote = True
    assert location_ok(r, cfg, de) and not location_ok(r, cfg, it)  # it: remote=False
    usa = make_job(location="Remote - USA")
    usa.remote = True
    assert not location_ok(usa, cfg, de)
    assert location_ok(make_job(location="Firenze"), cfg, prof.validate_profile(body()))  # citta' italiana da fonte globale


def test_query_senza_duplicati_e_pagine(cfg):
    a = prof.validate_profile(body(name="A", preset="custom", titles=["elettricista"], location={"city": "Bari", "radius_km": 40}))
    b = prof.validate_profile(body(name="B", preset="custom", titles=["elettricista"], location={"city": "Bari", "radius_km": 40}))
    qs = prof.merge_queries([a, b], cfg)
    keys = [(q.q.lower(), q.country, q.where.lower(), q.radius_km) for q in qs]
    assert len(keys) == len(set(keys))
    main = [q for q in qs if q.q == "elettricista"]
    assert main and all(q.where == "Bari" and q.radius_km == 40 and q.pages == (1, 2) for q in main)
    assert any(q.pages == (1,) for q in qs)  # stage


def test_lingue_per_paese(cfg):
    p = prof.validate_profile(body(preset="software_dev", countries=["de", "gb"], internships=False))
    by = {}
    for q in prof.profile_queries(p, cfg):
        by.setdefault(q.country, set()).add(q.q)
    assert "softwareentwickler" in by["de"] and "software developer" in by["gb"]
    assert "software developer" not in by["de"]


def test_stime_richieste(cfg):
    cfg["sources"]["adzuna"] = {"enabled": True}
    cfg["sources"]["jooble"] = {"enabled": True, "hosts": {"it": "it.jooble.org"}}
    p = prof.validate_profile(body(preset="software_dev", countries=["it", "gb"], internships=False))
    est = prof.estimate_requests([p], cfg)
    n = len(prof.profile_queries(p, cfg))
    assert est["adzuna"] == 2 * n
    assert est["jooble"] == sum(1 for q in prof.profile_queries(p, cfg) if q.country == "it")


def test_custom_parola_generica_non_basta_da_sola(cfg):
    p = prof.validate_profile(body(preset="custom", titles=["software engineer backend"]))
    ok = lambda t: (score_job(make_job(t, desc=""), cfg, p) or Job("", "", "", "", "")).score >= cfg["general"]["min_score"]
    assert ok("Backend Developer") and ok("Software Engineer Backend")
    assert not ok("Mechanical Engineer") and not ok("Civil Engineer") and not ok("Software Tester")
    assert score_job(make_job("Infermiere"), cfg, prof.validate_profile(body(preset="custom", titles=["infermiere"])))


def test_regione_italiana_con_paese_ignoto(cfg):
    p = prof.validate_profile(body())
    for reg in ("Lombardia", "Lazio", "Veneto", "Toscana", "Emilia-Romagna"):
        assert location_ok(make_job(location=reg), cfg, p), reg
    assert not location_ok(make_job(location="Bavaria"), cfg, p)
