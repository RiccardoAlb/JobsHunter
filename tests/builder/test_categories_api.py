"""Categorie personali: API, CLI, guida di primo avvio, report ed export (home temporanea, nessuna rete)."""
import csv
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from cvguard import _cv_guardia  # noqa: F401  (autouse: home temporanea, niente rete)
from jobshunter import onboarding, report, settings
from jobshunter import profiles as prof
from jobshunter.db import DB

H = {"Host": "127.0.0.1:8765"}
LONG = " Offriamo un ambiente dinamico e un percorso di crescita nel team, con formazione continua e sede a Roma."
HTML = (Path(__file__).parent.parent.parent / "jobshunter" / "gui" / "static" / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def client(home):
    from jobshunter.gui.app import create_app

    return create_app(None, 8765).test_client()


@pytest.fixture
def dbx(client):
    c = settings.load_config()
    return DB(settings.resolve_path(c["general"]["db_path"]))


def add_job(db, uid, title, desc, status="new"):
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, status, first_seen, country, avail, avail_checked) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (uid, "fake", title, "Acme " + uid, "Roma", "https://example.org/" + uid, desc + LONG, "", 0, "", "", status,
                                                               "2026-01-01T00:00:00+00:00", "it", "open", "2099-01-01T00:00:00+00:00"))
    db.conn.commit()


def body(**over):
    b = {"name": "Cucina", "preset": "custom", "titles": ["cuoco", "pasticcere"], "countries": ["it"], "location": {"city": "", "radius_km": 100},
         "remote": True, "internships": True, "active": True}
    b.update(over)
    return b


def post(client, url, data):
    return client.post(url, json=data, headers=H)


# -------------------------------------------------------------------------- API ----
def test_presets_espongono_le_categorie(client):
    presets = {p["key"]: p for p in client.get("/api/presets", headers=H).get_json()}
    assert [c["label"] for c in presets["cybersecurity"]["categories"]] == ["BLUE", "RED", "SYSADM", "SEC"]
    assert presets["custom"]["categories"] == []
    assert presets["software_dev"]["categories"][0]["weights"]


def test_creazione_custom_con_categorie(client):
    r = post(client, "/api/profiles", body(categories=[{"label": "cuoco", "terms": ["cuoco", "chef"]}]))
    assert r.status_code == 200
    assert r.get_json()["profile"]["categories"] == [{"label": "CUOCO", "terms": ["cuoco", "chef"]}]


def test_creazione_da_preset_copia_le_categorie(client):
    p = post(client, "/api/profiles", body(name="Dev", preset="software_dev", titles=[])).get_json()["profile"]
    assert [c["label"] for c in p["categories"]][:2] == ["BACKEND", "FRONTEND"]


def test_profilo_senza_categorie_ha_lista_vuota_nell_api(client):
    p = post(client, "/api/profiles", body()).get_json()["profile"]
    assert p["categories"] == []
    assert all("categories" in x for x in client.get("/api/profiles", headers=H).get_json())


def test_errori_di_validazione_in_italiano(client):
    cases = [([{"label": "ALTRO", "terms": ["x1"]}], "riservato"), ([{"label": "A", "terms": []}], "almeno una parola"),
             ([{"label": "A" * 20, "terms": ["xx"]}], "troppo lungo"), ([{"label": "A", "terms": ["xx"]}, {"label": "a", "terms": ["yy"]}], "ripetuta"),
             ([{"label": "A!", "terms": ["xx"]}], "lettere, numeri"), ("boh", "serve un elenco")]
    for cats, frag in cases:
        r = post(client, "/api/profiles", body(categories=cats))
        assert r.status_code == 400, cats
        err = r.get_json()["error"]
        assert err.startswith("categorie") and frag in err, err


def test_aggiornamento_ricalcola_categorie_e_filtra(client, dbx, home):
    pid = post(client, "/api/profiles", body()).get_json()["profile"]["id"]
    add_job(dbx, "aaaaaaaa", "Cuoco", "cucina", status="applied")
    add_job(dbx, "bbbbbbbb", "Pasticcere", "dolci")
    dbx.ensure_application("aaaaaaaa")
    r = post(client, "/api/profiles/%d" % pid, body(categories=[{"label": "CUCINA", "terms": ["cuoco"]}, {"label": "DOLCI", "terms": ["pasticcere"]}]))
    assert r.status_code == 200
    jobs = {j["id"]: j for j in client.get("/api/jobs?group=all&profile=%d" % pid, headers=H).get_json()}
    assert jobs["aaaaaa"]["category"] == "CUCINA" and jobs["bbbbbb"]["category"] == "DOLCI"
    assert jobs["aaaaaa"]["status"] == "applied"
    only = client.get("/api/jobs?group=all&cat=dolci", headers=H).get_json()
    assert [j["id"] for j in only] == ["bbbbbb"]
    assert client.get("/api/stats?profile=%d" % pid, headers=H).get_json()["by_cat"] == {"CUCINA": 1, "DOLCI": 1}
    assert dbx.conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
    assert list((home / "backups").glob("jobshunter-prima-del-ricalcolo-*.db"))   # copia di sicurezza prima del ricalcolo


def test_nessun_backup_se_le_categorie_non_cambiano(client, home):
    pid = post(client, "/api/profiles", body(categories=[{"label": "A", "terms": ["cuoco"]}])).get_json()["profile"]["id"]
    post(client, "/api/profiles/%d" % pid, body(categories=[{"label": "A", "terms": ["cuoco"]}], remote=False))
    assert not (home / "backups").exists() or not list((home / "backups").glob("*prima-del-ricalcolo*"))


def test_filtro_con_etichetta_accentata(client, dbx):
    pid = post(client, "/api/profiles", body(titles=["barista"], categories=[{"label": "caffè", "terms": ["barista"]}])).get_json()["profile"]["id"]
    add_job(dbx, "cccccccc", "Barista", "bar")
    post(client, "/api/profiles/%d" % pid, body(titles=["barista"], categories=[{"label": "caffè", "terms": ["barista"]}, {"label": "bar", "terms": ["bar"]}]))
    got = client.get("/api/jobs?group=all&cat=CAFFÈ", headers=H).get_json()
    assert [j["category"] for j in got] == ["CAFFÈ"]


def test_filtri_con_valori_strani_non_danno_500(client):
    for c in ("%3Cscript%3E", "x" * 100, "A%00B", "'; DROP TABLE jobs;--"):
        assert client.get("/api/jobs?group=all&cat=" + c, headers=H).status_code == 200


def test_anteprima_con_categorie(client):
    r = post(client, "/api/profiles/preview", body(categories=[{"label": "CUOCO", "terms": ["chef"]}]))
    assert r.status_code == 200 and {"term": "chef", "weight": 5, "group": "CUOCO"} in r.get_json()["keywords"]


# -------------------------------------------------------------- report ed export ----
def test_report_raggruppa_per_categoria_personale(client, dbx):
    pid = post(client, "/api/profiles", body(categories=[{"label": "CUCINA", "terms": ["cuoco"]}, {"label": "DOLCI", "terms": ["pasticcere"]}])).get_json()["profile"]["id"]
    add_job(dbx, "aaaaaaaa", "Cuoco", "cucina")
    add_job(dbx, "bbbbbbbb", "Pasticcere", "dolci")
    from jobshunter.rescore import rescore

    rescore(dbx, settings.load_config(), [pid])
    rows = dbx.query(min_score=0, limit=10)
    md = report.render(rows, title="Prova")
    assert "# " in md and "CUCINA (1)" in md and "DOLCI (1)" in md


def test_export_csv_con_categorie_nuove(home, client, dbx):
    from jobshunter.cli import main

    pid = post(client, "/api/profiles", body(categories=[{"label": "CUCINA", "terms": ["cuoco"]}])).get_json()["profile"]["id"]
    add_job(dbx, "aaaaaaaa", "Cuoco", "cucina")
    from jobshunter.rescore import rescore

    rescore(dbx, settings.load_config(), [pid])
    out = home / "x.csv"
    assert CliRunner().invoke(main, ["export", str(out)]).exit_code == 0
    assert [r["category"] for r in csv.DictReader(out.open(encoding="utf-8"))] == ["CUCINA"]


# -------------------------------------------------------------------------- CLI ----
def test_cli_profili_con_categorie(home):
    from jobshunter.cli import main

    cfg = settings.load_config(create_if_missing=True)
    db = DB(settings.resolve_path(cfg["general"]["db_path"]))
    add_job(db, "aaaaaaaa", "Cuoco", "cucina")
    add_job(db, "bbbbbbbb", "Pasticcere", "dolci")
    r = CliRunner()
    out = r.invoke(main, ["profiles", "add", "--name", "Cucina", "--title", "cuoco", "--title", "pasticcere", "--category", "cucina=cuoco,chef",
                          "--category", "dolci=pasticcere"])
    assert out.exit_code == 0, out.output
    show = r.invoke(main, ["profiles", "show", "Cucina"]).output
    assert "CUCINA" in show and "DOLCI" in show
    out = r.invoke(main, ["list", "--profile", "Cucina", "-t", "dolci", "--source", "all"])
    assert out.exit_code == 0 and "bbbbbb" in out.output and "aaaaaa" not in out.output
    assert r.invoke(main, ["profiles", "categories", "Cucina", "--add", "bevande=caffe,bar"]).exit_code == 0
    assert "BEVANDE" in r.invoke(main, ["profiles", "categories", "Cucina"]).output
    assert r.invoke(main, ["profiles", "categories", "Cucina", "--remove", "bevande"]).exit_code == 0
    bad = r.invoke(main, ["profiles", "categories", "Cucina", "--remove", "inesistente"])
    assert bad.exit_code == 1 and "non c'e'" in bad.output
    bad = r.invoke(main, ["profiles", "categories", "Cucina", "--add", "ALTRO=x1"])
    assert bad.exit_code == 1 and "riservato" in bad.output
    bad = r.invoke(main, ["profiles", "add", "--name", "Brutto", "--title", "x", "--category", "senza uguale"])
    assert bad.exit_code == 1
    assert r.invoke(main, ["profiles", "categories", "Cucina", "--clear"]).exit_code == 0
    assert "Nessuna categoria" in r.invoke(main, ["profiles", "categories", "Cucina"]).output
    assert list((home / "backups").glob("*.db"))


def test_cli_ripristina_categorie_del_preset(home):
    from jobshunter.cli import main

    settings.load_config(create_if_missing=True)
    r = CliRunner()
    assert r.invoke(main, ["profiles", "add", "--name", "Dev", "--preset", "software_dev"]).exit_code == 0
    assert r.invoke(main, ["profiles", "categories", "Dev", "--clear"]).exit_code == 0
    out = r.invoke(main, ["profiles", "categories", "Dev", "--restore-preset"])
    assert out.exit_code == 0 and "BACKEND" in out.output


# ------------------------------------------------------------ guida di primo avvio ----
def test_guida_categorie_da_testo_semplice(client, home):
    cfg = settings.load_config()
    store = prof.ProfileStore(DB(settings.resolve_path(cfg["general"]["db_path"])))
    plan = onboarding.prepare({"profile": {"preset": "custom", "titles": ["cuoco", "pasticcere"], "categories": "cuoco, Pasticcere,  cuoco ,"}, "country": "it",
                               "home": "", "radius_km": 100, "keys": {}, "report_dir": "", "schedule": None}, cfg, store)
    assert plan.profile.categories == [{"label": "CUOCO", "terms": ["cuoco"]}, {"label": "PASTICCERE", "terms": ["Pasticcere"]}]


def test_guida_categorie_vuote_o_su_preset_non_cambiano_niente(client, home):
    cfg = settings.load_config()
    store = prof.ProfileStore(DB(settings.resolve_path(cfg["general"]["db_path"])))
    base = {"country": "it", "home": "", "radius_km": 100, "keys": {}, "report_dir": "", "schedule": None}
    a = onboarding.prepare({**base, "profile": {"preset": "custom", "titles": ["cuoco"], "categories": ""}}, cfg, store)
    assert a.profile.categories == []
    b = onboarding.prepare({**base, "profile": {"preset": "software_dev", "titles": [], "categories": "ignorate"}}, cfg, store)
    assert b.profile.categories == prof.preset_categories("software_dev", cfg)  # il testo libero vale solo per i profili personalizzati


def test_guida_errori_categorie(client, home):
    cfg = settings.load_config()
    store = prof.ProfileStore(DB(settings.resolve_path(cfg["general"]["db_path"])))
    base = {"country": "it", "home": "", "radius_km": 100, "keys": {}, "report_dir": "", "schedule": None}
    many = ", ".join("voce%d" % i for i in range(13))
    with pytest.raises(onboarding.OnboardingError) as e:
        onboarding.prepare({**base, "profile": {"preset": "custom", "titles": ["x1"], "categories": many}}, cfg, store)
    assert e.value.field == "categories"
    with pytest.raises(onboarding.OnboardingError):
        onboarding.prepare({**base, "profile": {"preset": "custom", "titles": ["x1"], "categories": 5}}, cfg, store)


def test_guida_completa_crea_profilo_con_categorie_e_rifarla_le_conserva(client, dbx):
    base = {"country": "it", "home": "", "radius_km": 100, "keys": {}, "report_dir": "", "schedule": None}
    r = post(client, "/api/onboarding/complete", {**base, "profile": {"preset": "custom", "titles": ["cuoco"], "categories": "cuoco, chef"}})
    assert r.status_code == 200, r.get_json()
    pid = r.get_json()["profile_id"]
    assert [c["label"] for c in prof.ProfileStore(dbx).get(pid).categories] == ["CUOCO", "CHEF"]
    # rifare la guida senza toccare il campo non cancella niente; lasciarlo vuoto nemmeno
    r = post(client, "/api/onboarding/complete", {**base, "profile": {"preset": "custom", "titles": ["cuoco"], "categories": ""}})
    assert r.status_code == 200
    assert [c["label"] for c in prof.ProfileStore(dbx).get(pid).categories] == ["CUOCO", "CHEF"]


def test_guida_preset_nuovo_copia_le_categorie_del_preset(client, dbx):
    base = {"country": "it", "home": "", "radius_km": 100, "keys": {}, "report_dir": "", "schedule": None}
    r = post(client, "/api/onboarding/complete", {**base, "profile": {"preset": "software_dev", "titles": []}})
    assert r.status_code == 200, r.get_json()
    cats = prof.ProfileStore(dbx).get(r.get_json()["profile_id"]).categories
    assert cats and cats[0]["label"] == "BACKEND"


# ------------------------------------------------------------ pagina (statico) ----
def test_pagina_usa_solo_textcontent_per_le_categorie():
    start = HTML.index("/* categorie personali */")
    block = HTML[start:start + 7000]
    assert "innerHTML" not in block and "insertAdjacentHTML" not in block
    assert "Ripristina quelle del preset" in block and "Aggiungi una categoria dei tipi noti" in block
    assert "Categorie (facoltativo)" in HTML and "onbCats" in HTML
    assert "categories: 2" in HTML  # un errore sul campo riporta al passo giusto, senza passi nuovi
    assert 'const OB_STEPS = ["Benvenuto"' in HTML and 'Il tuo CV (facoltativo)", "Riepilogo e prima ricerca"]' in HTML  # nessun passo nuovo


def test_colore_neutro_per_le_categorie_dell_utente():
    assert 'presetLabels().has(c)' in HTML and '"var(--muted)"' in HTML
