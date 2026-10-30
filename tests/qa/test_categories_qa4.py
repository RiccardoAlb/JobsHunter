"""Fase 6, quarto giro del TESTER: nuova regola dei limiti per le categorie pesate dei gruppi noti (B83 in poi)."""
from __future__ import annotations

import copy
import time

import pytest

from conftest import t as tlimit
from jobshunter import profiles as prof
from jobshunter import settings
from jobshunter.models import Job
from jobshunter.scoring import score_job
from qa.qa_helpers import call, mkprofile, profile_body

SW = ["BACKEND", "FRONTEND", "SOFTWARE", "MOBILE", "DEVOPS"]


def mk(preset, cats, name):
    return call(None if False else CLIENT[0], "post", "/api/profiles", profile_body(name=name, preset=preset, titles=["abc"] if preset == "custom" else [], categories=cats))


CLIENT = [None]


@pytest.fixture(autouse=True)
def _c(client):
    CLIENT[0] = client


def cat(label, n, w=5, length=8):
    terms = [("t%03d" % i + "x" * length)[:length + 4] for i in range(n)]
    return {"label": label, "terms": terms, "weights": {terms[0]: w}}


def test_la_modifica_del_test_21_in_41_e_legittima_e_i_21_restano_vietati_dove_serve():
    # il 21 resta vietato per profili custom e per etichette fuori dai gruppi del tipo (limite 20)
    for preset, label in (("custom", "BACKEND"), ("software_dev", "BLUE"), ("data", "BACKEND"), ("software_dev", "MIA")):
        with pytest.raises(prof.ProfileError):
            prof.validate_profile({"name": "x", "preset": preset, "titles": ["abc"], "categories": [cat(label, 21)]}, settings.load_config())
    # gruppo noto del proprio tipo: fino a max(40, originale + 20)
    cfg = settings.load_config()
    prof.validate_profile({"name": "x", "preset": "software_dev", "categories": [cat("BACKEND", 40)]}, cfg)
    with pytest.raises(prof.ProfileError):
        prof.validate_profile({"name": "x", "preset": "software_dev", "categories": [cat("BACKEND", 41)]}, cfg)


@pytest.mark.parametrize("preset,label,n,ok", [
    ("software_dev", "BACKEND", 200, False), ("software_dev", "BACKEND", 41, False), ("software_dev", "BACKEND", 40, True),
    ("cybersecurity", "BLUE", 200, False), ("cybersecurity", "BLUE", 41, False), ("cybersecurity", "BLUE", 39, True),
    ("software_dev", "BLUE", 30, False), ("data", "BACKEND", 25, False), ("custom", "BACKEND", 21, False), ("custom", "BLUE", 21, False),
    ("custom", "BLUE", 20, True), ("software_dev", "NUOVA", 21, False), ("cybersecurity", "NUOVA", 21, False)])
def test_limiti_parole_nuova_regola(preset, label, n, ok):
    cfg = settings.load_config()
    body = {"name": "x", "preset": preset, "titles": ["abc"] if preset == "custom" else [], "categories": [cat(label, n)]}
    if ok:
        prof.validate_profile(body, cfg)
    else:
        with pytest.raises(prof.ProfileError):
            prof.validate_profile(body, cfg)


@pytest.mark.parametrize("preset", ["software_dev", "cybersecurity", "data", "admin_office"])
@pytest.mark.parametrize("w", [13, 20, 1000, "5", 5.5 + 1e9, float("inf"), True])
def test_pesi_oltre_12_mai_per_gruppi_noti(preset, w):
    label = prof.preset_categories(preset, settings.load_config())[0]["label"]
    c = cat(label, 10, w=w)
    if w == 5.5 + 1e9 or w in (13, 20, 1000, "5", True) or w == float("inf"):
        with pytest.raises(prof.ProfileError):
            prof.validate_profile({"name": "x", "preset": preset, "categories": [c]}, settings.load_config())


def test_senza_config_almeno_100_ma_pesi_e_etichette_restano_stretti():
    c100 = cat("BACKEND", 100)
    prof.validate_profile({"name": "x", "preset": "software_dev", "categories": [c100]})
    with pytest.raises(prof.ProfileError):
        prof.validate_profile({"name": "x", "preset": "software_dev", "categories": [cat("BACKEND", 101)]})
    with pytest.raises(prof.ProfileError):
        prof.validate_profile({"name": "x", "preset": "cybersecurity", "categories": [cat("BLUE", 100, w=13)]})
    for lab in ("<b>BLUE", 'BLUE"', "BLUE\\", "＜BLUE＞"):
        with pytest.raises(prof.ProfileError):
            prof.validate_profile({"name": "x", "preset": "cybersecurity", "categories": [cat(lab, 3)]})
    with pytest.raises(prof.ProfileError):
        prof.validate_profile({"name": "x", "preset": "cybersecurity", "categories": [{**cat("BLUE", 3), "terms": ["a" * 81, "bb"]}]})


def test_parole_80_caratteri_si_ma_81_no():
    prof.validate_profile({"name": "x", "preset": "software_dev", "categories": [{"label": "BACKEND", "terms": ["q" * 80, "bb"], "weights": {"bb": 5}}]}, settings.load_config())
    with pytest.raises(prof.ProfileError):
        prof.validate_profile({"name": "x", "preset": "software_dev", "categories": [{"label": "BACKEND", "terms": ["q" * 81, "bb"], "weights": {"bb": 5}}]}, settings.load_config())


# ---- B81 e B82 ----
def test_B81_blue_di_serie_piu_due_parole_e_togliere_una(client):
    p = mkprofile(client, name="Cy", preset="cybersecurity")
    cats = copy.deepcopy(p["categories"])
    cats[0]["terms"] += ["zzuno", "zzdue"]
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**p, "categories": cats})
    assert st == 200 and len(d["profile"]["categories"][0]["terms"]) == len(p["categories"][0]["terms"]) + 2
    cats2 = copy.deepcopy(d["profile"]["categories"])
    cats2[0]["terms"].pop(0)
    assert call(client, "post", f"/api/profiles/{p['id']}", {**d["profile"], "categories": cats2})[0] == 200


def test_B81_config_con_gruppo_grande_modificabile(home):
    cfg = copy.deepcopy(settings.load_config(create_if_missing=True))
    cfg["keywords"]["blue"]["terms"].update({f"extra term {i}": 4 for i in range(12)})
    cats = prof.preset_categories("cybersecurity", cfg)
    c = copy.deepcopy(cats)
    t = c[0]["terms"].pop()
    c[0]["weights"].pop(t.lower())
    assert len(prof.clean_categories(c, "cybersecurity", cfg)) == 4
    c[0]["terms"] += [f"nuova {i}" for i in range(20)]
    prof.clean_categories(c, "cybersecurity", cfg)
    c[0]["terms"] += [f"altra {i}" for i in range(5)]
    with pytest.raises(prof.ProfileError):
        prof.clean_categories(c, "cybersecurity", cfg)


# ---- amplificazione e lentezza ----
@pytest.mark.xfail(reason="B83: la stessa parola in tutti i gruppi del tipo (BACKEND, FRONTEND, SOFTWARE, MOBILE, DEVOPS, ciascuno con peso 12) si somma: una parola nel titolo vale 180 punti, cioe' un peso effettivo di 60 (limite dichiarato: 12)")
def test_B83_una_parola_non_pesa_oltre_12_sommando_i_gruppi(client, qdb):
    cats = [{"label": l, "terms": ["zzfoo"], "weights": {"zzfoo": 12}} for l in SW]
    st, d = call(client, "post", "/api/profiles", profile_body(name="amp", preset="software_dev", categories=cats))
    r = score_job(Job(source="f", title="zzfoo", company="c", location="Roma", url="u", description="x"), settings.load_config(), prof.ProfileStore(qdb).get(d["profile"]["id"]) if st == 200 else prof.Profile(name="x"))
    assert st == 400 or r is None or r.score <= 12 * 3 + 4, r and r.score


def test_categorie_al_massimo_dei_limiti_senza_rallentamenti(home):
    cfg = settings.load_config(create_if_missing=True)
    mkt = lambda k, n, l: [("w%02d%s" % (i, k)).ljust(l, "y") for i in range(n)]
    cats = [{"label": lab, "terms": mkt(lab[:3], 40, 80), "weights": {t: 12 for t in mkt(lab[:3], 40, 80)}} for lab in SW]
    cats += [{"label": f"U{i}", "terms": mkt(f"u{i}", 20, 40)} for i in range(7)]
    p = prof.validate_profile({"name": "x", "preset": "software_dev", "categories": cats}, cfg)
    bodies = [("developer yyyyyyyy backend aaaa " * 200)[:5000], (("w00BAC" + "y" * 74 + " ") * 80)[:5000], "y" * 5000, " ".join(["backend"] * 700)[:5000]]
    t0 = time.time()
    for _ in range(100):
        for b in bodies:
            score_job(Job(source="f", title="backend developer", company="c", location="Roma", url="u", description=b), cfg, p)
    assert time.time() - t0 < tlimit(25), "troppo lento"
