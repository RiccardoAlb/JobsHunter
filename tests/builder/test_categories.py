"""Categorie personali per profilo (fase 6): validazione, punteggio, regressione sui preset, API, CLI, guida, report.

Home temporanea e nessuna rete (guardia di cvguard). Compatibile con Python 3.11 e Linux."""
import copy
import csv
import json
from pathlib import Path

import pytest

from cvguard import _cv_guardia  # noqa: F401  (autouse: home temporanea, niente rete)
from jobshunter import onboarding, report, settings
from jobshunter import profiles as prof
from jobshunter.db import DB
from jobshunter.models import Job
from jobshunter.rescore import rescore
from jobshunter.scoring import CAT_BONUS_BODY, CAT_BONUS_TITLE, score_job

H = {"Host": "127.0.0.1:8765"}
LONG = " Offriamo un ambiente dinamico e un percorso di crescita nel team, con formazione continua e sede a Roma."


def job(title, desc="", n=1, location="Roma"):
    return Job(source="fake", title=title, company="Acme %d" % n, location=location, url="https://example.org/j%d" % n,
               description=desc + LONG, country="it")


def custom(titles, categories=None, **kw):
    d = {"name": "Prova", "preset": "custom", "titles": titles}
    if categories is not None:
        d["categories"] = categories
    d.update(kw)
    return prof.validate_profile(d)


# ----------------------------------------------------------------- validazione ----
def test_etichetta_normalizzata_in_maiuscolo():
    p = custom(["cuoco"], [{"label": " cuoco  di sala ", "terms": ["cuoco"]}])
    assert p.categories[0]["label"] == "CUOCO DI SALA"


@pytest.mark.parametrize("label", ["", "   ", "ALTRO", "altro", "A" * 17, "CUOCO!", "<script>", "=CMD", "A_B", "x|y", "a\nb;c", "'; DROP--"])
def test_etichette_non_valide(label):
    with pytest.raises(prof.ProfileError) as e:
        custom(["cuoco"], [{"label": label, "terms": ["cuoco"]}])
    assert str(e.value).startswith("categorie")


@pytest.mark.parametrize("label", ["CUOCO", "A", "A" * 16, "PASTICCERIA", "SALA-BAR", "SALA 2", "CAFFÈ", "ÀLA CARTE", "1 LIVELLO"])
def test_etichette_valide(label):
    assert custom(["cuoco"], [{"label": label, "terms": ["cuoco"]}]).categories[0]["label"] == label.upper()


def test_etichette_duplicate_anche_con_maiuscole_diverse():
    with pytest.raises(prof.ProfileError) as e:
        custom(["x"], [{"label": "cuoco", "terms": ["cuoco"]}, {"label": "CUOCO", "terms": ["chef"]}])
    assert "ripetuta" in str(e.value)


def test_massimo_12_categorie():
    cats = [{"label": "C%d" % i, "terms": ["parola%d" % i]} for i in range(12)]
    assert len(custom(["x"], cats).categories) == 12
    with pytest.raises(prof.ProfileError):
        custom(["x"], cats + [{"label": "C13", "terms": ["tredici"]}])


@pytest.mark.parametrize("terms", [[], [""], ["a"], ["x" * 41], [5], {"a": 1}, None, [" ", "\t"]])
def test_parole_non_valide(terms):
    with pytest.raises(prof.ProfileError) as e:
        custom(["x"], [{"label": "CUOCO", "terms": terms}])
    assert str(e.value).startswith("categorie")


def test_parole_limiti_e_duplicati():
    twenty = ["parola%02d" % i for i in range(20)]
    assert len(custom(["x"], [{"label": "A", "terms": twenty}]).categories[0]["terms"]) == 20
    with pytest.raises(prof.ProfileError):
        custom(["x"], [{"label": "A", "terms": twenty + ["ventunesima"]}])
    dup = custom(["x"], [{"label": "A", "terms": ["Cuoco", "cuoco", "CUOCO", "chef"]}]).categories[0]["terms"]
    assert dup == ["Cuoco", "chef"]
    assert custom(["x"], [{"label": "A", "terms": ["xx", "x" * 40]}]).categories


def test_parole_come_testo_unico():
    c = custom(["x"], [{"label": "A", "terms": "cuoco, chef; aiuto cuoco"}]).categories[0]
    assert c["terms"] == ["cuoco", "chef", "aiuto cuoco"]


def test_categorie_non_lista_o_voci_strane():
    for bad in ("cuoco", {"label": "A"}, [1], ["A"], [{"terms": ["x"]}], [{"label": 5, "terms": ["x"]}]):
        with pytest.raises(prof.ProfileError):
            custom(["x"], bad)


def test_pesi_validi_e_non_validi():
    c = custom(["x"], [{"label": "A", "terms": ["alfa", "beta"], "weights": {"alfa": 9, "gamma": 3}}]).categories[0]
    assert c["weights"] == {"alfa": 9}  # i pesi di parole non presenti si scartano
    for w in ({"alfa": 0}, {"alfa": 21}, {"alfa": "x"}, {"alfa": True}, ["a"]):
        with pytest.raises(prof.ProfileError):
            custom(["x"], [{"label": "A", "terms": ["alfa"], "weights": w}])


def test_controllo_caratteri_nelle_parole():
    c = custom(["x"], [{"label": "A", "terms": ["a\x00b\x07c", "bello\ncosi"]}]).categories[0]
    assert all("\x00" not in t and "\n" not in t for t in c["terms"])


# -------------------------------------------------------- lettura e salvataggio ----
def test_profilo_vecchio_senza_categorie_si_legge_e_non_scrive_la_chiave():
    p = prof.as_profile({"name": "Vecchio", "preset": "cybersecurity"})
    assert p.categories == [] and "categories" not in p.to_dict()
    assert prof.validate_profile({"name": "Vecchio", "preset": "cybersecurity"}).categories == []


def test_lettura_tollerante_di_dati_rovinati():
    p = prof.as_profile({"name": "X", "categories": [{"label": "A"}, 5, {"label": "B", "terms": ["ok"]}, {"label": "C", "terms": []}]})
    assert [c["label"] for c in p.categories] == ["B"]
    assert prof.as_profile({"name": "X", "categories": "boh"}).categories == []


def test_salvataggio_e_rilettura(db):
    store = prof.ProfileStore(db)
    p = store.add({"name": "Cucina", "preset": "custom", "titles": ["cuoco"], "categories": [{"label": "cuoco", "terms": ["cuoco", "chef"]}]})
    assert store.get(p.id).categories == [{"label": "CUOCO", "terms": ["cuoco", "chef"]}]
    raw = json.loads(db.conn.execute("SELECT data FROM profiles WHERE id=?", (p.id,)).fetchone()["data"])
    assert raw["categories"][0]["label"] == "CUOCO"


def test_aggiornamento_senza_chiave_azzera_le_categorie(db):
    store = prof.ProfileStore(db)
    p = store.add({"name": "Cucina", "preset": "custom", "titles": ["cuoco"], "categories": [{"label": "A", "terms": ["cuoco"]}]})
    q = store.update(p.id, {"name": "Cucina", "preset": "custom", "titles": ["cuoco"]})
    assert q.categories == []


# ------------------------------------------------------------ preset e copia ----
def test_creazione_da_preset_copia_le_categorie(db):
    store = prof.ProfileStore(db)
    p = store.add({"name": "Dev", "preset": "software_dev"})
    assert [c["label"] for c in p.categories] == [g["label"] for g in prof.PRESETS["software_dev"]["groups"]]
    assert all(c.get("weights") for c in p.categories)


def test_creazione_da_preset_con_categorie_esplicite_vuote_non_copia(db):
    p = prof.ProfileStore(db).add({"name": "Dev", "preset": "software_dev", "categories": []})
    assert p.categories == []


def test_custom_non_copia_niente(db):
    assert prof.ProfileStore(db).add({"name": "C", "preset": "custom", "titles": ["cuoco"]}).categories == []


def test_preset_categories_per_ogni_preset():
    for key in prof.PRESETS:
        cats = prof.preset_categories(key)
        assert (key == "custom") == (cats == [])
        for c in cats:
            assert prof.clean_categories([c])  # le categorie dei preset superano la validazione


def test_cyber_copia_le_parole_del_config_se_cambiate(db, cfg):
    c2 = copy.deepcopy(cfg)
    c2["keywords"] = {"x": {"label": "BLUE", "terms": {"unicaparola": 7}}}
    p = prof.ProfileStore(db).add({"name": "Cy", "preset": "cybersecurity"}, c2)
    assert p.categories == [{"label": "BLUE", "terms": ["unicaparola"], "weights": {"unicaparola": 7}}]


# ------------------------------------------------- regressione: punteggi invariati ----
SAMPLES = [
    ("SOC Analyst", "SIEM Splunk incident response"), ("Penetration Tester", "pentest OSCP vulnerability assessment"),
    ("Sistemista Linux", "Windows Server Active Directory VMware backup"), ("Security Engineer", "cybersecurity information security"),
    ("Junior SOC Analyst", "Wazuh EDR threat hunting"), ("Senior Pentester Red Team", "red team offensive security"),
    ("Help Desk Specialist", "assistenza tecnica ticket service desk"), ("Backend Developer Python", "Django REST API PostgreSQL docker"),
    ("Frontend Engineer React", "TypeScript CSS"), ("Data Analyst", "SQL Power BI dashboard"), ("Data Engineer", "ETL Spark Airflow"),
    ("Impiegato amministrativo", "contabilita fatturazione segreteria"), ("Account Executive vendite", "CRM lead generation marketing"),
    ("Cuoco", "cucina ristorante"), ("Infermiere", "reparto ospedale"), ("Magazziniere carrellista", "magazzino muletto"),
    ("Stage Cybersecurity", "SOC SIEM"), ("Purple Team Engineer", "red team blue team siem pentest"),
]


def results(profile, cfg):
    out = []
    for i, (t, d) in enumerate(SAMPLES):
        r = score_job(job(t, d, i), cfg, profile)
        out.append(None if r is None else (r.score, r.category, tuple(r.matched)))
    return out


@pytest.mark.parametrize("preset", [k for k in prof.PRESETS if k != "custom"])
@pytest.mark.parametrize("seniority", ["any", "junior"])
@pytest.mark.parametrize("titles", [[], ["tecnico informatico"]])
def test_regressione_preset_con_categorie_copiate_stessi_punteggi(cfg, preset, seniority, titles):
    base = prof.validate_profile({"name": "P", "preset": preset, "seniority": seniority, "titles": titles})
    copied = prof.validate_profile({"name": "P", "preset": preset, "seniority": seniority, "titles": titles,
                                    "categories": prof.preset_categories(preset, cfg)})
    assert copied.categories and base.categories == []
    assert results(copied, cfg) == results(base, cfg)


def test_regressione_cyber_con_config_modificato(cfg):
    c2 = copy.deepcopy(cfg)
    c2["keywords"] = {"a": {"label": "BLUE", "terms": {"siem": 9, "soc": 5}}, "b": {"label": "RED", "terms": {"pentest": 12}}}
    base = prof.validate_profile({"name": "P", "preset": "cybersecurity"})
    copied = prof.validate_profile({"name": "P", "preset": "cybersecurity", "categories": prof.preset_categories("cybersecurity", c2)})
    assert results(copied, c2) == results(base, c2)


def test_regressione_profilo_senza_categorie_dei_preset_noti_non_cambia(cfg):
    """Un profilo salvato prima della fase 6 deve dare gli stessi punteggi e le stesse categorie di sempre (BLUE/RED/SYSADM/SEC/PURPLE)."""
    p = prof.as_profile({"name": "Cyber", "preset": "cybersecurity"})
    cats = {r[1] for r in results(p, cfg) if r}
    assert {"BLUE", "RED", "SYSADM", "SEC"} <= cats
    purple = score_job(job("Purple Team Engineer", "red team blue team siem pentest incident response soc analyst", 99), cfg, p)
    assert purple is not None and purple.category == "PURPLE"


def test_categorie_copiate_cyber_continuano_a_dare_purple(cfg):
    p = prof.validate_profile({"name": "P", "preset": "cybersecurity", "categories": prof.preset_categories("cybersecurity", cfg)})
    r = score_job(job("Purple Team Engineer", "red team blue team siem pentest incident response soc analyst", 99), cfg, p)
    assert r is not None and r.category == "PURPLE"


# ------------------------------------------------- punteggio con categorie ----
def test_custom_senza_categorie_e_come_prima(cfg):
    p = custom(["cuoco"])
    r = score_job(job("Cuoco", "cucina"), cfg, p)
    assert r.category == "CUOCO"  # il titolo e' il gruppo, come oggi


def test_custom_con_categorie_decidono_l_etichetta(cfg):
    p = custom(["cuoco", "pasticcere"], [{"label": "CUCINA", "terms": ["cuoco", "chef"]}, {"label": "DOLCI", "terms": ["pasticcere", "pasticceria"]}])
    assert score_job(job("Cuoco di sala", "chef"), cfg, p).category == "CUCINA"
    assert score_job(job("Pasticcere", "pasticceria artigianale", 2), cfg, p).category == "DOLCI"


def test_custom_nessuna_categoria_riconosciuta_e_altro(cfg):
    p = custom(["cuoco"], [{"label": "DOLCI", "terms": ["pasticcere"]}])
    r = score_job(job("Cuoco", "cucina"), cfg, p)
    assert r is not None and r.category == "ALTRO"


def test_bonus_titolo_e_testo_e_massimo(cfg):
    base = score_job(job("Cuoco", "cucina", 1), cfg, custom(["cuoco"])).score
    in_title = score_job(job("Cuoco", "cucina", 1), cfg, custom(["cuoco"], [{"label": "A", "terms": ["cuoco"]}])).score
    in_body = score_job(job("Cuoco", "cucina", 1), cfg, custom(["cuoco"], [{"label": "A", "terms": ["cucina"]}])).score
    many = score_job(job("Cuoco", "cucina", 1), cfg, custom(["cuoco"], [{"label": "A", "terms": ["cuoco"]}, {"label": "B", "terms": ["cucina"]}, {"label": "C", "terms": ["cuoco", "cucina"]}])).score
    assert in_title - base == CAT_BONUS_TITLE and in_body - base == CAT_BONUS_BODY
    assert many - base == CAT_BONUS_TITLE  # mai la somma: il bonus massimo e' uno solo


def test_categoria_da_sola_non_fa_entrare_un_annuncio(cfg):
    p = custom(["cuoco"], [{"label": "A", "terms": ["magazziniere"]}])
    assert score_job(job("Magazziniere", "magazzino"), cfg, p) is None


def test_categorie_non_cambiano_il_punteggio_oltre_il_bonus(cfg):
    for t, d in SAMPLES:
        a = score_job(job(t, d), cfg, custom(["cuoco", "infermiere", "magazziniere"]))
        b = score_job(job(t, d), cfg, custom(["cuoco", "infermiere", "magazziniere"], [{"label": "X", "terms": ["cuoco", "infermiere", "ospedale", "cucina"]}]))
        assert (a is None) == (b is None)
        if a:
            assert 0 <= b.score - a.score <= CAT_BONUS_TITLE


def test_preset_piu_categoria_dell_utente(cfg):
    cats = prof.preset_categories("software_dev") + [{"label": "MIO", "terms": ["fintech"]}]
    p = prof.validate_profile({"name": "D", "preset": "software_dev", "categories": cats})
    base = prof.validate_profile({"name": "D", "preset": "software_dev"})
    a = score_job(job("Backend Developer", "python fintech", 1), cfg, p)
    b = score_job(job("Backend Developer", "python fintech", 1), cfg, base)
    assert a.score - b.score == CAT_BONUS_BODY
    assert a.category in {"BACKEND", "MIO"}


def test_preset_con_sole_categorie_dell_utente_etichetta_solo_loro(cfg):
    p = prof.validate_profile({"name": "D", "preset": "software_dev", "categories": [{"label": "MIO", "terms": ["fintech"]}]})
    assert score_job(job("Backend Developer", "python", 1), cfg, p).category == "ALTRO"
    assert score_job(job("Backend Developer", "python fintech", 2), cfg, p).category == "MIO"


def test_termini_speciali_sono_letterali_e_veloci(cfg):
    p = custom(["cuoco"], [{"label": "A", "terms": ["c++ (dev)", "a.*b", "[x", "(?:a+)+$", "\\d+"]}])
    r = score_job(job("Cuoco", "usa c++ (dev) oggi " + "a" * 5000 + "!"), cfg, p)
    assert r is not None and "c++ (dev)" in r.matched


def test_etichetta_con_html_non_passa_ma_le_parole_si_trattano_come_testo(cfg):
    p = custom(["cuoco"], [{"label": "OK", "terms": ["<script>alert(1)</script>"]}])
    assert p.categories[0]["terms"] == ["<script>alert(1)</script>"]  # e' solo testo: la pagina usa textContent


def test_keywords_of_include_le_categorie_dell_utente(cfg):
    p = custom(["cuoco"], [{"label": "A", "terms": ["chef"]}])
    assert {"term": "chef", "weight": 5, "group": "A"} in prof.keywords_of(p, cfg)


# ------------------------------------------------------------------ rescore ----
def add_job(db, uid, title, desc, status="new"):
    db.conn.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, status, first_seen, country) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (uid, "fake", title, "Acme " + uid, "Roma", "https://example.org/" + uid, desc + LONG, "", 0, "", "", status,
                                                           "2026-01-01T00:00:00+00:00", "it"))
    db.conn.commit()


def test_rescore_aggiorna_le_categorie_senza_perdere_stato_e_candidature(db, cfg):
    store = prof.ProfileStore(db)
    p = store.add({"name": "Cucina", "preset": "custom", "titles": ["cuoco", "pasticcere"]})
    add_job(db, "a" * 8, "Cuoco", "cucina", status="applied")
    add_job(db, "b" * 8, "Pasticcere", "dolci", status="seen")
    add_job(db, "c" * 8, "Cuoco unico", "cucina", status="discarded")
    db.ensure_application("a" * 8)
    rescore(db, cfg, [p.id])
    cats = lambda: {r["job_uid"]: r["category"] for r in db.conn.execute("SELECT * FROM job_profiles WHERE profile_id=?", (p.id,))}
    assert set(cats().values()) == {"CUOCO", "PASTICCERE", "CUOCO UNICO"} or len(set(cats().values())) >= 2
    store.update(p.id, {"name": "Cucina", "preset": "custom", "titles": ["cuoco", "pasticcere"],
                        "categories": [{"label": "CUCINA", "terms": ["cuoco"]}, {"label": "DOLCI", "terms": ["pasticcere"]}]})
    rescore(db, cfg, [p.id])
    assert cats() == {"a" * 8: "CUCINA", "b" * 8: "DOLCI", "c" * 8: "CUCINA"}
    st = {r["uid"]: r["status"] for r in db.conn.execute("SELECT uid, status FROM jobs")}
    assert st == {"a" * 8: "applied", "b" * 8: "seen", "c" * 8: "discarded"}
    assert db.conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
    assert {r["category"] for r in db.conn.execute("SELECT category FROM jobs")} == {"CUCINA", "DOLCI"}  # refresh_best


def test_snapshot_crea_copia_e_tiene_le_ultime_tre(db, home):
    names = []
    for i in range(5):
        db.conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('k', ?)", (str(i),))
        db.conn.commit()
        import time

        time.sleep(1.05)
        names.append(db.snapshot())
    files = sorted((home / "backups").glob("jobshunter-prima-del-ricalcolo-*.db"))
    assert len(files) == 3 and all(f.stat().st_mode & 0o777 == 0o600 for f in files)
    assert DB(files[-1]).kv_get("k") == "4"
