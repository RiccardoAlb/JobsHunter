"""Correzioni dopo il collaudo della fase 6 (B63-B77): atomicita' del ricalcolo, tipi di profilo, unione delle categorie, limiti.

Home temporanea e nessuna rete (guardia di cvguard). Compatibile con Python 3.11 e Linux."""
import copy
import json
import threading
from pathlib import Path

import pytest

from cvguard import _cv_guardia  # noqa: F401  (autouse: home temporanea, niente rete)
from jobshunter import onboarding, rescore as R, settings
from jobshunter import profiles as prof
from jobshunter.db import DB
from jobshunter.models import Job
from jobshunter.scoring import score_job

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


def add_job(db, uid, title, desc):
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, status, first_seen, country, avail, avail_checked) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (uid, "fake", title, "Acme " + uid, "Roma", "https://example.org/" + uid, desc + LONG, "", 0, "", "", "new",
                                                               "2026-01-01T00:00:00+00:00", "it", "open", "2099-01-01T00:00:00+00:00"))
    db.conn.commit()


def post(client, url, data):
    return client.post(url, json=data, headers=H)


def body(**over):
    b = {"name": "Cucina", "preset": "custom", "titles": ["cuoco"], "countries": ["it"], "location": {"city": "", "radius_km": 100}, "remote": True,
         "internships": True, "active": True}
    b.update(over)
    return b


# ------------------------------------------------------------------ B63 ----
def odd_cfg(cfg):
    c = copy.deepcopy(cfg)
    c["keywords"] = {"a": {"label": "SEC/OPS", "terms": dict({"secops": 25, "x": 3, "a" * 60: 4}, **{"termine %d" % i: 3 for i in range(80)})},
                     "b": {"label": "BLUE", "terms": {"siem": 9, "soc": 5}}}
    return c


def job(title, desc):
    return Job(source="f", title=title, company="c", location="Roma", url="u", description=desc + LONG)


def test_b63_config_insolito_si_copia_senza_perdere_niente_e_si_risalva(cfg):
    c = odd_cfg(cfg)
    cats = prof.preset_categories("cybersecurity", c)
    assert cats[0]["label"] == "SEC/OPS" and len(cats[0]["terms"]) == 83 and cats[0]["weights"]["secops"] == 25
    again = prof.validate_profile(prof.Profile(name="x", preset="cybersecurity", categories=cats).to_dict(), c)  # il server confronta col config: identica = accettata
    assert [x["label"] for x in again.categories] == ["SEC/OPS", "BLUE"] and again.categories[0]["terms"] == cats[0]["terms"]
    base = prof.validate_profile({"name": "x", "preset": "cybersecurity"})
    for t, d in (("SOC secops", "termine 4 siem"), ("Analyst", "x secops termine 7"), ("Junior SIEM", "soc")):
        a, b = score_job(job(t, d), c, base), score_job(job(t, d), c, again)
        assert (a is None) == (b is None) and (a is None or (a.score, a.category) == (b.score, b.category))


def test_b63_salvataggio_via_api_con_config_insolito(client, dbx):
    c = odd_cfg(settings.load_config())
    store = prof.ProfileStore(dbx)
    p = store.add({"name": "Cy", "preset": "cybersecurity"}, c)
    again = store.update(p.id, p.to_dict(), c)
    assert again.categories == p.categories


# ----------------------------------------------------------- B64 / B65 / B66 ----
def test_b64_b65_normalizzazione_unicode():
    import unicodedata

    nfd = unicodedata.normalize("NFD", "città")
    assert prof.clean_categories([{"label": nfd, "terms": ["cuoco"]}])[0]["label"] == "CITTÀ"
    with pytest.raises(prof.ProfileError) as e:
        prof.clean_categories([{"label": "ＡＬＴＲＯ", "terms": ["cuoco"]}])
    assert "riservato" in str(e.value)
    t = prof.clean_categories([{"label": "A", "terms": [unicodedata.normalize("NFD", "caffè")]}])[0]["terms"][0]
    assert t == unicodedata.normalize("NFC", "caffè")
    with pytest.raises(prof.ProfileError):
        prof.clean_categories([{"label": nfd, "terms": ["x1"]}, {"label": "CITTÀ", "terms": ["x2"]}])


def test_b66_weights_non_alzano_il_limite_di_20_parole_ne_con_tipo_di_profilo_se_il_nome_non_e_del_tipo():
    many = ["parola%d" % i for i in range(30)]
    with pytest.raises(prof.ProfileError) as e:
        prof.clean_categories([{"label": "A", "terms": many, "weights": {"parola0": 3}}])
    assert "massimo 20" in str(e.value)
    with pytest.raises(prof.ProfileError):
        prof.validate_profile({"name": "x", "preset": "software_dev", "categories": [{"label": "MIA", "terms": many, "weights": {"parola0": 3}}]})
    with pytest.raises(prof.ProfileError):
        prof.validate_profile({"name": "x", "preset": "custom", "titles": ["x1"], "categories": [{"label": "BACKEND", "terms": many, "weights": {"parola0": 3}}]})


# ------------------------------------------------------------ B77 / B68 / B76 ----
def boom_after(n, real):
    state = {"c": 0}

    def f(*a, **k):
        state["c"] += 1
        if state["c"] > n:
            raise RuntimeError("boom")
        return real(*a, **k)

    return f


def test_b77_rescore_fallito_non_lascia_transazione_aperta(dbx, cfg, monkeypatch):
    store = prof.ProfileStore(dbx)
    p = store.add({"name": "C", "preset": "custom", "titles": ["cuoco"]})
    for i in range(8):
        add_job(dbx, "%08d" % i, "Cuoco %d" % i, "cucina")
    R.rescore(dbx, cfg, [p.id])
    before = dbx.conn.execute("SELECT COUNT(*) FROM job_profiles").fetchone()[0]
    monkeypatch.setattr(R, "score_job", boom_after(3, R.score_job))
    with pytest.raises(RuntimeError):
        R.rescore(dbx, cfg, [p.id])
    assert dbx.conn.in_transaction is False
    assert dbx.conn.execute("SELECT COUNT(*) FROM job_profiles").fetchone()[0] == before  # il DELETE e' stato annullato


def test_b68_ricalcolo_fallito_rimette_il_profilo_e_riprovare_funziona(client, dbx, monkeypatch):
    pid = post(client, "/api/profiles", body(titles=["cuoco", "pasticcere"], categories=[{"label": "OLD", "terms": ["cuoco", "pasticcere"]}])).get_json()["profile"]["id"]
    for i in range(10):
        add_job(dbx, "%08d" % i, ("Cuoco " if i % 2 else "Pasticcere ") + str(i), "cucina dolci")
    R.rescore(dbx, settings.load_config(), [pid])
    new = body(titles=["cuoco", "pasticcere"], categories=[{"label": "NEW", "terms": ["cuoco", "pasticcere"]}])
    real = R.score_job
    monkeypatch.setattr(R, "score_job", boom_after(4, real))
    r = post(client, "/api/profiles/%d" % pid, new)
    assert r.status_code == 500 and "rimasto com'era" in r.get_json()["error"]
    saved = [c["label"] for c in prof.ProfileStore(dbx).get(pid).categories]
    assert saved == ["OLD"]
    assert {x[0] for x in dbx.conn.execute("SELECT DISTINCT category FROM job_profiles WHERE profile_id=?", (pid,))} == {"OLD"}
    monkeypatch.setattr(R, "score_job", real)
    assert post(client, "/api/profiles/%d" % pid, new).status_code == 200  # lo stesso corpo ricalcola davvero
    assert {x[0] for x in dbx.conn.execute("SELECT DISTINCT category FROM job_profiles WHERE profile_id=?", (pid,))} == {"NEW"}


def test_creazione_con_ricalcolo_fallito_non_lascia_il_profilo(client, dbx, monkeypatch):
    add_job(dbx, "aaaaaaaa", "Cuoco", "cucina")
    monkeypatch.setattr(R, "score_job", boom_after(0, R.score_job))
    r = post(client, "/api/profiles", body(name="Nuovo"))
    assert r.status_code == 500
    assert prof.ProfileStore(dbx).get("Nuovo") is None


def test_b76_salvataggi_concorrenti_lasciano_stato_coerente(client, dbx):
    pid = post(client, "/api/profiles", body(titles=["cuoco", "pasticcere"])).get_json()["profile"]["id"]
    for i in range(60):
        add_job(dbx, "%08d" % i, ("Cuoco " if i % 2 else "Pasticcere ") + str(i), "cucina dolci")
    b = body(titles=["cuoco", "pasticcere"])

    def w(label, terms):
        for k in range(3):
            post(client, "/api/profiles/%d" % pid, {**b, "categories": [{"label": "%s%d" % (label, k), "terms": terms}]})

    for _ in range(6):
        ts = [threading.Thread(target=w, args=("AA", ["cuoco"])), threading.Thread(target=w, args=("BB", ["pasticcere"]))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        got = sorted(tuple(r) for r in dbx.conn.execute("SELECT job_uid, category, score FROM job_profiles WHERE profile_id=?", (pid,)))
        R.rescore(dbx, settings.load_config(), [pid])
        assert got == sorted(tuple(r) for r in dbx.conn.execute("SELECT job_uid, category, score FROM job_profiles WHERE profile_id=?", (pid,)))


# ----------------------------------------------------------------- B69 / B70 ----
def test_b69_cambio_di_tipo_sostituisce_le_categorie_del_tipo_vecchio(client, dbx):
    p = post(client, "/api/profiles", body(name="Dev", preset="software_dev", titles=[])).get_json()["profile"]
    mia = {"label": "MIA", "terms": ["fintech"]}
    r = post(client, "/api/profiles/%d" % p["id"], {**p, "preset": "data", "categories": p["categories"] + [mia]}).get_json()["profile"]
    labels = [c["label"] for c in r["categories"]]
    assert "BACKEND" not in labels and "ANALISI" in labels and "MIA" in labels
    r = post(client, "/api/profiles/%d" % p["id"], {**r, "preset": "custom", "titles": ["cuoco"]}).get_json()["profile"]
    assert [c["label"] for c in r["categories"]] == ["MIA"]


def test_b70_categoria_nota_di_altro_tipo_vale_solo_il_bonus(client, dbx):
    presets = {x["key"]: x for x in client.get("/api/presets", headers=H).get_json()}
    blue = next(c for c in presets["cybersecurity"]["categories"] if c["label"] == "BLUE")
    p = post(client, "/api/profiles", body(name="Dev", preset="software_dev", titles=[])).get_json()["profile"]
    cfg = settings.load_config()
    soc = job("SOC analyst", "siem splunk wazuh")
    soc.description = "siem splunk wazuh"
    q = post(client, "/api/profiles/%d" % p["id"], {**p, "categories": p["categories"] + [blue]}).get_json()["profile"]
    assert score_job(copy.copy(soc), cfg, prof.ProfileStore(dbx).get(p["id"])) is None
    dev = job("Backend Developer", "python django")
    base = score_job(copy.copy(dev), cfg, prof.ProfileStore(dbx).get(p["id"]))
    assert base is not None and base.category == "BACKEND"
    assert [c["label"] for c in q["categories"]][-1] == "BLUE"


# ------------------------------------------------------------- B71 / B72 / B73 ----
def test_b71_parola_accentata_su_profilo_cybersecurity(cfg):
    p = prof.Profile(name="x", preset="cybersecurity", categories=[{"label": "SICUR", "terms": ["perché"]}])
    r = score_job(job("SOC analyst", "lavoriamo perché conta"), cfg, p)
    assert "perché" in r.matched


def test_b72_filtro_con_simboli(client, dbx):
    pid = post(client, "/api/profiles", body(name="Dev", titles=["C++ developer", "Infermiere/a"])).get_json()["profile"]["id"]
    add_job(dbx, "aaaaaaaa", "C++ developer senior", "c++ developer")
    add_job(dbx, "bbbbbbbb", "Infermiere/a reparto", "infermiere/a")
    R.rescore(dbx, settings.load_config(), [pid])
    assert [j["category"] for j in client.get("/api/jobs?group=all&cat=C%2B%2B+DEVELOPER", headers=H).get_json()] == ["C++ DEVELOPER"]
    assert len(client.get("/api/jobs?group=all&cat=INFERMIERE%2FA", headers=H).get_json()) == 1


def test_b73_unione_delle_categorie_con_profilo_tutti(client, dbx):
    a = post(client, "/api/profiles", body(name="Sic", titles=["analista"], categories=[{"label": "ALFA", "terms": ["analista"]}])).get_json()["profile"]
    b = post(client, "/api/profiles", body(name="Altro", titles=["analista"], categories=[{"label": "BETA", "terms": ["analista", "turni"]}])).get_json()["profile"]
    add_job(dbx, "aaaaaaaa", "Analista", "turni")
    R.rescore(dbx, settings.load_config(), [a["id"], b["id"]])
    for lab in ("ALFA", "BETA"):
        assert len(client.get("/api/jobs?group=all&cat=" + lab, headers=H).get_json()) == 1
    st = client.get("/api/stats", headers=H).get_json()
    assert {"ALFA", "BETA"} <= set(st["all_cats"])
    one = client.get("/api/stats?profile=%d" % a["id"], headers=H).get_json()
    assert set(one["all_cats"]) == set(one["by_cat"]) == {"ALFA"}
    assert client.get("/api/jobs?group=all&cat=BETA&profile=%d" % a["id"], headers=H).get_json() == []   # con un profilo scelto non si mischia


# ------------------------------------------------------------- B67 / B74 / B75 ----
def test_b67_backup_unici_nello_stesso_secondo(dbx, home):
    names = {dbx.snapshot() for _ in range(3)}
    assert len(names) == 3 and None not in names


def test_b74_ordine_stabile_delle_categorie_nel_report():
    from jobshunter import report

    class Row(dict):
        pass

    cats = ["ZETA", "ALFA", "MEDIO", "BLUE"]
    rows = [{"category": c, "score": 50, "title": "t" + c, "company": "c", "location": "Roma", "near_home": 0, "salary": "", "work_mode": "unknown", "contract": "unknown",
             "avail": "open", "valid_until": None, "avail_checked": "", "posted_at": "", "matched": "", "source": "fake", "uid": "u" + c + "xxxxxx", "url": "https://example.org",
             "full_text": "", "description": "d"} for c in cats]
    md = report.render(rows, title="x")
    heads = [l for l in md.splitlines() if l.startswith("# ") and l.endswith(")")]
    assert [h.split()[-2] for h in heads] == ["BLUE", "ALFA", "MEDIO", "ZETA"] or [h.split()[1] for h in heads][:1] == ["🔵"]
    assert md.index("ALFA (1)") < md.index("MEDIO (1)") < md.index("ZETA (1)")


def test_b75_voci_diverse_non_spariscono():
    got = onboarding.onboarding_categories("c++, c#, assistente alla poltrona, assistente alla vendita, c++", "custom")
    labels = [c["label"] for c in got]
    assert len(got) == 4 and len(set(labels)) == 4 and labels[0] == "C" and labels[1] == "C 2"
    assert all(len(l) <= prof.CAT_LABEL_MAX for l in labels)
    for c in got:
        prof.clean_categories([c])


# ----------------------------------------------------------------- pagina ----
def test_testo_non_confermato_si_conferma_al_salvataggio():
    assert "conferma implicita" in HTML and "catName.value.trim() || catWords.value.trim()" in HTML
    assert "all_cats" in HTML


# ------------------------------------------------------------------ B78 ----
@pytest.mark.parametrize("preset,label", [("cybersecurity", "<b>x</b> zzz"), ("cybersecurity", "NOME INVENTATO"), ("software_dev", "BACKEND")])
def test_b78_fiducia_dal_server_non_dal_corpo(client, preset, label):
    terms = ["parola%d x" % i for i in range(150)]
    r = post(client, "/api/profiles", body(name="Furbo", preset=preset, titles=[], categories=[{"label": label, "terms": terms, "weights": {t: 1000 for t in terms}}]))
    assert r.status_code == 400 and r.get_json()["error"].startswith("categorie")


def test_b78_peso_enorme_e_etichetta_con_html_rifiutati(client):
    for cat in ({"label": "BACKEND", "terms": ["zzfoo"], "weights": {"zzfoo": 1000}}, {"label": "BACKEND", "terms": ["zzfoo"], "weights": {"zzfoo": 13}},
                {"label": "<i>x</i>", "terms": ["zzfoo"], "weights": {"zzfoo": 5}}, {"label": "UN NOME", "terms": ["x%d" % i for i in range(21)], "weights": {"x0": 5}}):
        preset = "cybersecurity" if cat["label"] != "BACKEND" else "software_dev"
        assert post(client, "/api/profiles", body(name="F", preset=preset, titles=[], categories=[cat])).status_code == 400, cat


def test_b78_modifica_dentro_i_limiti_e_copia_esatta_si_accettano(client, dbx):
    presets = {x["key"]: x for x in client.get("/api/presets", headers=H).get_json()}
    cats = presets["cybersecurity"]["categories"]
    r = post(client, "/api/profiles", body(name="Cy", preset="cybersecurity", titles=[], categories=cats))
    assert r.status_code == 200 and [c["label"] for c in r.get_json()["profile"]["categories"]] == [c["label"] for c in cats]
    edited = [dict(c) for c in cats]
    edited[0] = {**edited[0], "terms": edited[0]["terms"][:-1], "weights": {k: v for k, v in edited[0]["weights"].items() if k != edited[0]["terms"][-1].lower()}}
    assert post(client, "/api/profiles/%d" % r.get_json()["profile"]["id"], body(name="Cy", preset="cybersecurity", titles=[], categories=edited)).status_code == 200
    mia = {"label": "MIA CATEGORIA", "terms": ["fintech", "banca"], "weights": {"fintech": 12, "banca": 3}}
    assert post(client, "/api/profiles", body(name="Cy2", preset="cybersecurity", titles=[], categories=[mia])).status_code == 200


def test_b78_config_insolito_via_api_con_la_copia_esatta(client, dbx):
    c = odd_cfg(settings.load_config())
    store = prof.ProfileStore(dbx)
    exact = prof.preset_categories("cybersecurity", c)
    assert prof.validate_profile({"name": "x", "preset": "cybersecurity", "categories": exact}, c).categories[0]["label"] == "SEC/OPS"
    forged = [dict(exact[0], weights={k: 1000 for k in exact[0]["weights"]})]
    with pytest.raises(prof.ProfileError):
        prof.validate_profile({"name": "x", "preset": "cybersecurity", "categories": forged}, c)
    assert store is not None


# ------------------------------------------------------------- B79 / B80 ----
def test_b79_b80_filtro_cat(client, dbx):
    import unicodedata

    pid = post(client, "/api/profiles", body(name="Bar", titles=["barista"], categories=[{"label": "caffè", "terms": ["barista"]}])).get_json()["profile"]["id"]
    add_job(dbx, "aaaaaaaa", "Barista", "bar")
    R.rescore(dbx, settings.load_config(), [pid])
    assert len(client.get("/api/jobs?group=all&cat=" + unicodedata.normalize("NFD", "CAFFÈ"), headers=H).get_json()) == 1
    assert len(client.get("/api/jobs?group=all&cat=caff%C3%A8", headers=H).get_json()) == 1
    for q in ("A" * 100, "A%00B", "A%0AB"):
        assert client.get("/api/jobs?group=all&cat=" + q, headers=H).get_json() == []
    assert client.post("/api/report", json={"cat": "A" * 100}, headers=H).status_code == 404


# ------------------------------------------------- refresh_best atomico / blocchi ----
def test_refresh_best_che_fallisce_annulla_tutto(dbx, cfg, monkeypatch):
    store = prof.ProfileStore(dbx)
    p = store.add({"name": "C", "preset": "custom", "titles": ["cuoco"], "categories": [{"label": "OLD", "terms": ["cuoco"]}]})
    add_job(dbx, "aaaaaaaa", "Cuoco", "cucina")
    R.rescore(dbx, cfg, [p.id])
    before = [tuple(r) for r in dbx.conn.execute("SELECT job_uid, category FROM job_profiles")]
    store.update(p.id, {"name": "C", "preset": "custom", "titles": ["cuoco"], "categories": [{"label": "NEW", "terms": ["cuoco"]}]})

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(DB, "refresh_best", boom)
    with pytest.raises(RuntimeError):
        R.rescore(dbx, cfg, [p.id])
    assert dbx.conn.in_transaction is False
    assert [tuple(r) for r in dbx.conn.execute("SELECT job_uid, category FROM job_profiles")] == before


def test_la_guida_prende_il_blocco_dei_profili_nell_ordine_giusto(client, dbx, monkeypatch):
    seen = {}
    real = onboarding.apply

    def spy(*a, **k):
        seen["complete"], seen["profili"] = onboarding.COMPLETE_LOCK.locked(), prof.PROFILE_LOCK.locked()
        return real(*a, **k)

    monkeypatch.setattr(onboarding, "apply", spy)
    base = {"country": "it", "home": "", "radius_km": 100, "keys": {}, "report_dir": "", "schedule": None}
    assert post(client, "/api/onboarding/complete", {**base, "profile": {"preset": "custom", "titles": ["cuoco"]}}).status_code == 200
    assert seen == {"complete": True, "profili": True}


def test_corsa_guida_e_modifica_profilo_senza_deadlock_ne_stato_misto(client, dbx):
    import time

    base = {"country": "it", "home": "", "radius_km": 100, "keys": {}, "report_dir": "", "schedule": None}
    pid = post(client, "/api/onboarding/complete", {**base, "profile": {"preset": "custom", "titles": ["cuoco"], "categories": "cuoco"}}).get_json()["profile_id"]
    for i in range(40):
        add_job(dbx, "%08d" % i, "Cuoco %d" % i, "cucina")
    R.rescore(dbx, settings.load_config(), [pid])
    codes = []

    def guida():
        for _ in range(3):
            codes.append(post(client, "/api/onboarding/complete", {**base, "profile": {"preset": "custom", "titles": ["cuoco"], "categories": "chef"}}).status_code)

    def modifica():
        for k in range(3):
            codes.append(post(client, "/api/profiles/%d" % pid, body(name="Cucina %d" % k, titles=["cuoco"], categories=[{"label": "MOD%d" % k, "terms": ["cuoco"]}])).status_code)

    ts = [threading.Thread(target=guida), threading.Thread(target=modifica)]
    t0 = time.time()
    [t.start() for t in ts]
    [t.join(timeout=60) for t in ts]
    assert not any(t.is_alive() for t in ts) and time.time() - t0 < 60  # nessun deadlock
    assert all(c < 500 for c in codes), codes
    got = sorted(tuple(r) for r in dbx.conn.execute("SELECT job_uid, category, score FROM job_profiles WHERE profile_id=?", (pid,)))
    R.rescore(dbx, settings.load_config(), [pid])
    assert got == sorted(tuple(r) for r in dbx.conn.execute("SELECT job_uid, category, score FROM job_profiles WHERE profile_id=?", (pid,)))


# ------------------------------------------------------------------ B81 / B82 ----
def test_b81_categoria_grande_modificabile_ma_senza_aggirare_gli_altri_limiti(settings_cfg=None):
    cfg = settings.load_config(create_if_missing=True) if False else None
    base = prof.preset_categories("cybersecurity")
    blue = copy.deepcopy(base[0])
    extra = ["parola extra %d" % i for i in range(21)]  # 19 + 21 = 40: il massimo per un gruppo da 19
    ok = dict(blue, terms=blue["terms"] + extra[:21], weights={**blue["weights"], **{t: 4 for t in extra[:21]}})
    assert len(prof.clean_categories([ok], "cybersecurity", {"keywords": {}})[0]["terms"]) == 40
    too = dict(blue, terms=blue["terms"] + extra + ["uno in piu"], weights={**blue["weights"], **{t: 4 for t in extra}})
    with pytest.raises(prof.ProfileError):
        prof.clean_categories([too], "cybersecurity", {"keywords": {}})
    # gli altri limiti restano: peso, etichetta, parola lunga
    heavy = dict(blue, weights={**blue["weights"], blue["terms"][0].lower(): 13})
    with pytest.raises(prof.ProfileError):
        prof.clean_categories([heavy], "cybersecurity", {"keywords": {}})
    longw = dict(blue, terms=blue["terms"] + ["x" * 81], weights={**blue["weights"], "x" * 81: 4})
    with pytest.raises(prof.ProfileError):
        prof.clean_categories([longw], "cybersecurity", {"keywords": {}})
    other = dict(blue, label="NON DEL TIPO", terms=blue["terms"] + extra[:5], weights={**blue["weights"], **{t: 4 for t in extra[:5]}})
    with pytest.raises(prof.ProfileError):
        prof.clean_categories([other], "cybersecurity", {"keywords": {}})  # fuori dai gruppi del tipo: resta il limite di 20


def test_b81_gruppo_del_config_con_30_parole_si_modifica(cfg):
    c = copy.deepcopy(cfg)
    c["keywords"]["blue"]["terms"].update({"extra %d" % i: 4 for i in range(12)})
    cats = prof.preset_categories("cybersecurity", c)
    n = len(cats[0]["terms"])
    assert n > 20
    edited = copy.deepcopy(cats)
    t = edited[0]["terms"].pop()
    edited[0]["weights"].pop(t.lower())
    assert len(prof.clean_categories(edited, "cybersecurity", c)[0]["terms"]) == n - 1
    edited[0]["terms"] += ["nuova %d" % i for i in range(20)]
    edited[0]["weights"].update({"nuova %d" % i: 4 for i in range(20)})
    assert len(prof.clean_categories(edited, "cybersecurity", c)[0]["terms"]) == n - 1 + 20


def test_b82_etichetta_da_titolo_normalizzata():
    import unicodedata

    for raw in (unicodedata.normalize("NFD", "caffè"), "ＣＡＦＦÈ"):
        label = prof.title_groups([raw])[0][0]
        assert label == unicodedata.normalize("NFKC", label).upper() == "CAFFÈ"


def test_b82_editor_normalizza_nfkc():
    assert 'normalize("NFKC").toUpperCase()' in HTML
