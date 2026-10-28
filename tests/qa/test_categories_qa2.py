"""Fase 6, secondo giro del TESTER: regressioni introdotte dalle correzioni B63-B77 (nuovi bug da B78)."""
from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request

import pytest

from jobshunter import profiles as prof
from jobshunter import settings
from jobshunter.models import Job
from jobshunter.scoring import score_job
from qa.qa_helpers import H, call, mkprofile, profile_body
from qa.test_categories_qa import ROOT, _SERVER_FAIL, addjob, cats_err, T


def post(client, pid, body):
    return client.post(f"/api/profiles/{pid}", json=body, headers=H)


def get(client, url):
    return client.get(url, headers=H).get_json()


# ------------------------------------------------------------------ regressione dei punteggi (PURPLE obbligatorio) ----
def test_purple_obbligatorio_cybersecurity_con_e_senza_categorie(home):
    cfg = settings.load_config(create_if_missing=True)
    j = lambda: Job(source="f", title="Penetration tester e SOC analyst", company="c", location="Roma", url="u",
                    description="pentest red team exploit oscp siem splunk wazuh incident response blue team edr dfir")
    old = score_job(j(), cfg, prof.Profile(name="x", preset="cybersecurity"))
    new = score_job(j(), cfg, prof.Profile(name="x", preset="cybersecurity", categories=prof.preset_categories("cybersecurity", cfg)))
    assert old.category == "PURPLE" and new.category == "PURPLE" and old.score == new.score and old.matched == new.matched
    # anche dopo un giro per validazione e salvataggio
    saved = prof.validate_profile(prof.Profile(name="x", preset="cybersecurity", categories=prof.preset_categories("cybersecurity", cfg)).to_dict())
    again = score_job(j(), cfg, saved)
    assert again.category == "PURPLE" and again.score == old.score


@pytest.mark.parametrize("preset", [k for k in prof.PRESETS if k != "custom"])
def test_preset_salvato_e_riletto_stesso_punteggio(preset, home):
    cfg = settings.load_config(create_if_missing=True)
    p0 = prof.Profile(name="x", preset=preset)
    p1 = prof.validate_profile(prof.Profile(name="x", preset=preset, categories=prof.preset_categories(preset, cfg)).to_dict())
    terms = [t for g in prof.PRESETS[preset]["groups"] for t in g["terms"]]
    for i in range(0, len(terms), 2):
        job = Job(source="f", title=f"{terms[i]} {terms[(i + 1) % len(terms)]}", company="c", location="Roma", url="u", description=" ".join(terms[i:i + 6]))
        a, b = score_job(copy.copy(job), cfg, p0), score_job(copy.copy(job), cfg, p1)
        assert (a and (a.score, a.category, a.matched)) == (b and (b.score, b.category, b.matched))


# ------------------------------------------------------------------ B63/B66: i limiti larghi non si aggirano ----
@pytest.mark.parametrize("preset,label", [("cybersecurity", "<b>x</b> zzz"), ("cybersecurity", "NOME INVENTATO"), ("software_dev", "BACKEND")])
def test_B78_utente_non_aggira_i_limiti_con_weights_e_tipo_di_profilo(client, preset, label):
    terms = [f"parola{i} x" for i in range(150)]
    body = profile_body(name="Furbo", preset=preset, categories=[{"label": label, "terms": terms, "weights": {t: 1000 for t in terms}}])
    st, d = call(client, "post", "/api/profiles", body)
    assert st == 400, [(c["label"], len(c["terms"]), max(c["weights"].values())) for c in d["profile"]["categories"]]


def test_B78_peso_enorme_non_fa_punteggi_assurdi(client, qdb):
    body = profile_body(name="Furbo", preset="software_dev", categories=[{"label": "BACKEND", "terms": ["zzfoo"], "weights": {"zzfoo": 1000}}])
    st, d = call(client, "post", "/api/profiles", body)
    cfg = settings.load_config()
    r = score_job(Job(source="f", title="zzfoo dev", company="c", location="Roma", url="u", description="x"), cfg, prof.ProfileStore(qdb).get(d["profile"]["id"]) if st == 200 else prof.Profile(name="x"))
    assert st == 400 or (r and r.score <= 100), r and r.score


def test_limiti_larghi_solo_per_categorie_davvero_copiate(client):
    terms = [f"parola{i} x" for i in range(30)]
    for preset in ("custom", "data", "admin_office"):  # 'BACKEND' non e' un gruppo di questi tipi
        body = profile_body(name="F" + preset, preset=preset, titles=["abc"] if preset == "custom" else [], categories=[{"label": "BACKEND", "terms": terms, "weights": {terms[0]: 5}}])
        st, d = call(client, "post", "/api/profiles", body)
        assert st == 400, (preset, d)
    # senza weights nessuno ha limiti larghi, nemmeno cybersecurity
    st, d = call(client, "post", "/api/profiles", profile_body(name="C1", preset="cybersecurity", categories=[{"label": "BLUE", "terms": terms}]))
    assert st == 400


def test_preset_copiato_si_risalva_con_config_strano(client):
    cats = prof.preset_categories("cybersecurity", settings.load_config())
    p = mkprofile(client, name="Cy", preset="cybersecurity")
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**p, "categories": cats})
    assert st == 200


# ------------------------------------------------------------------ B64/B65: NFKC/NFC ----
def test_nfkc_etichette_e_parole(home):
    assert prof.clean_categories([{"label": unicodedata.normalize("NFD", "città"), "terms": T}])[0]["label"] == "CITTÀ"
    cats_err([{"label": "ＡＬＴＲＯ", "terms": T}])
    assert "ripetuta" in cats_err([{"label": "è", "terms": T}, {"label": unicodedata.normalize("NFD", "È"), "terms": T}])
    assert prof.clean_categories([{"label": "ﬁsica", "terms": T}])[0]["label"] == "FISICA"
    assert prof.clean_categories([{"label": "a", "terms": [unicodedata.normalize("NFD", "caffè")]}])[0]["terms"] == [unicodedata.normalize("NFC", "caffè")]
    for bad in ("㎏ ", "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰", " x", "x‮y", "a​b"):
        try:
            got = prof.clean_categories([{"label": bad, "terms": T}])
        except prof.ProfileError:
            continue
        lab = got[0]["label"]
        assert lab == lab.upper() and all(ord(ch) >= 32 and ch not in " ‮​" for ch in lab), repr(lab)


def test_B80_cat_filtro_con_nfd_nell_url(client, qdb):
    p = mkprofile(client, name="Bar", preset="custom", titles=["barista"], categories=[{"label": "caffè", "terms": ["barista"]}])
    addjob(qdb, "aaaaaaaa", "Barista", "bar")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [p["id"]])
    nfd = unicodedata.normalize("NFD", "CAFFÈ")
    assert len(get(client, "/api/jobs?group=all&cat=" + nfd)) == 1  # il filtro deve normalizzare come le etichette


# ------------------------------------------------------------------ B72/B73/all_cats, SQL e nomi ostili ----
def test_filtro_cat_ostile_non_tocca_il_db_e_non_restituisce_tutto(client, qdb):
    p = mkprofile(client, name="Dev", preset="custom", titles=["C++ developer"])
    addjob(qdb, "aaaaaaaa", "C++ developer", "c++")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [p["id"]])
    assert len(get(client, "/api/jobs?group=all&cat=C%2B%2B DEVELOPER")) == 1
    for q in ("%27%20OR%201%3D1--", "%25", "_", "%27%3B%20DROP%20TABLE%20jobs%3B--", "%22", "%5C", "%3Cimg%20onerror%3D1%3E"):
        assert get(client, "/api/jobs?group=all&cat=" + q) == [], q
    assert qdb.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_B79_cat_troppo_lunga_o_con_controlli_da_lista_vuota(client, qdb):
    p = mkprofile(client, name="Dev", preset="custom", titles=["analista"])
    addjob(qdb, "aaaaaaaa", "Analista", "x")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [p["id"]])
    assert get(client, "/api/jobs?group=all&cat=" + "A" * 100) == []
    assert get(client, "/api/jobs?group=all&cat=A%00B") == []


def test_stats_all_cats_unione_attivi_e_scartati(client, qdb):
    a = mkprofile(client, name="A", preset="custom", titles=["analista"], categories=[{"label": "ALFA", "terms": ["analista"]}])
    b = mkprofile(client, name="B", preset="custom", titles=["analista"], categories=[{"label": "BETA", "terms": ["analista", "turni"]}])
    addjob(qdb, "aaaaaaaa", "Analista", "turni")
    addjob(qdb, "bbbbbbbb", "Analista senior", "x", status="discarded")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [a["id"], b["id"]])
    s = get(client, "/api/stats")
    assert s["all_cats"] == {"ALFA": 1, "BETA": 1} and s["by_cat"] in ({"ALFA": 1}, {"BETA": 1})
    assert len(get(client, "/api/jobs?group=all&cat=ALFA")) == 1 and len(get(client, "/api/jobs?group=all&cat=BETA")) == 1
    assert get(client, f"/api/stats?profile={b['id']}")["all_cats"] == get(client, f"/api/stats?profile={b['id']}")["by_cat"] == {"BETA": 1}
    post(client, b["id"], {**profile_body(name="B", preset="custom", titles=["analista"]), "active": False, "categories": [{"label": "BETA", "terms": ["analista", "turni"]}]})
    assert get(client, "/api/stats")["all_cats"] == {"ALFA": 1}
    assert get(client, "/api/jobs?group=all&cat=BETA") == []  # profilo spento: niente chip e niente annunci
    s = get(client, "/api/stats?profile=999999") if False else None


def test_cat_con_profilo_scelto_e_cat_tutti_coerenti_con_i_chip(client, qdb):
    a = mkprofile(client, name="A", preset="custom", titles=["analista"], categories=[{"label": "ALFA", "terms": ["analista"]}])
    addjob(qdb, "aaaaaaaa", "Analista", "x")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [a["id"]])
    for k in get(client, "/api/stats")["all_cats"]:
        assert get(client, "/api/jobs?group=all&cat=" + k), k  # ogni chip offerto da all_cats trova annunci


# ------------------------------------------------------------------ B68/B69/B76/B77: atomicita', tipo, lock ----
def test_cambio_di_tipo_gruppi_nuovi_e_categorie_utente_conservate(client, qdb):
    p = mkprofile(client, name="Dev", preset="software_dev", categories=[])
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**p, "preset": "software_dev", "categories": [{"label": "MIA", "terms": ["rust"]}]})
    p = d["profile"]
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**p, "preset": "data"})
    labels = {c["label"] for c in d["profile"]["categories"]}
    assert "MIA" in labels and not (labels & {"BACKEND", "FRONTEND", "DEVOPS"})
    groups = {k["group"] for k in prof.keywords_of(prof.ProfileStore(qdb).get(p["id"]), settings.load_config())}
    assert not groups & {"BACKEND", "FRONTEND", "DEVOPS"} and {c["label"] for c in prof.preset_categories("data")} <= groups
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**d["profile"], "preset": "custom", "titles": ["rust"]})
    assert st == 200 and [c["label"] for c in d["profile"]["categories"]] == ["MIA"]
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**d["profile"], "preset": "cybersecurity"})
    assert st == 200 and {"BLUE", "RED", "SYSADM", "SEC", "MIA"} <= {c["label"] for c in d["profile"]["categories"]}


def test_cambio_di_tipo_ricalcola_gli_annunci(client, qdb):
    p = mkprofile(client, name="Dev", preset="software_dev")
    addjob(qdb, "aaaaaaaa", "Data analyst", "sql python power bi dashboard")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [p["id"]])
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**p, "preset": "data"})
    assert st == 200
    row = qdb.conn.execute("SELECT category FROM job_profiles WHERE profile_id=?", (p["id"],)).fetchone()
    assert row and row[0] in {c["label"] for c in prof.preset_categories("data")}


def _server(tmp_path):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, HOME=str(tmp_path), JOBSHUNTER_HOME=str(tmp_path / "srv"))
    script = tmp_path / "srv.py"
    script.write_text(_SERVER_FAIL)
    proc = subprocess.Popen([sys.executable, str(script), str(ROOT), str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(tmp_path))
    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/profiles", timeout=1)
            break
        except OSError:
            time.sleep(0.2)

    def req(path, body=None, timeout=6):
        r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
        try:
            x = urllib.request.urlopen(r, timeout=timeout)
            return x.status, json.loads(x.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, None

    return proc, req


def _seed(tmp_path, n=12):
    import sqlite3

    c = sqlite3.connect(str(next((tmp_path / "srv").glob("*.db"))))
    for i in range(n):
        c.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, status, first_seen, country, avail, avail_checked) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"{i:08d}", "fake", "Cuoco %d" % i, "Acme%d" % i, "Roma", "https://example.org/%d" % i, "cucina " * 5, "", 0, "", "", "new",
                                                              "2026-01-01T00:00:00+00:00", "it", "open", "2099-01-01T00:00:00+00:00"))
    c.commit()
    c.close()


def test_server_vero_ricalcolo_fallito_poi_due_salvataggi_di_seguito(home, tmp_path):
    proc, req = _server(tmp_path)
    base = {"name": "Cucina", "preset": "custom", "titles": ["cuoco"]}
    try:
        st, d = req("/api/profiles", base)
        assert st == 200
        pid = d["profile"]["id"]
        _seed(tmp_path)
        assert req(f"/api/profiles/{pid}", {**base, "categories": [{"label": "UNO", "terms": ["cuoco"]}]})[0] >= 500  # fallisce alla 4a valutazione
        st, d = req(f"/api/profiles/{pid}")  # POST senza corpo: 400/415, non deve bloccarsi
        # il profilo e' rimasto com'era (nessuna categoria) e gli annunci coerenti
        st, lst = req("/api/profiles")
        assert [c["label"] for c in lst[0]["categories"]] == [], lst[0]["categories"]
        t0 = time.time()
        for lab in ("DUE", "TRE"):
            st, d = req(f"/api/profiles/{pid}", {**base, "categories": [{"label": lab, "terms": ["cuoco"]}]})
            assert st == 200, st
        assert time.time() - t0 < 5
        st, jobs = req("/api/jobs?group=all")
        assert st == 200 and {j["category"] for j in jobs} == {"TRE"}
        # la creazione che fallisce non lascia il profilo a meta': si usa un nuovo server con fallimento alla 4a valutazione
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_server_vero_creazione_con_ricalcolo_fallito_non_lascia_il_profilo(home, tmp_path):
    proc, req = _server(tmp_path)
    try:
        st, d = req("/api/profiles", {"name": "Zero", "preset": "custom", "titles": ["cuoco"]})
        assert st == 200
        _seed(tmp_path)
        st, _ = req("/api/profiles", {"name": "Due", "preset": "custom", "titles": ["cuoco"]})
        assert st >= 500
        st, lst = req("/api/profiles")
        assert st == 200 and [p["name"] for p in lst] == ["Cybersecurity", "Zero"] or [p["name"] for p in lst] == ["Zero"] or "Due" not in [p["name"] for p in lst]
        st, _ = req("/api/profiles", {"name": "Due", "preset": "custom", "titles": ["cuoco"]})  # riprovando funziona (nome non occupato)
        assert st == 200
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_lock_eliminazione_e_modifica_insieme_senza_deadlock(client, qdb):
    a = mkprofile(client, name="A", preset="custom", titles=["cuoco"])
    b = mkprofile(client, name="B", preset="custom", titles=["cuoco"])
    for i in range(60):
        addjob(qdb, f"{i:08d}", "Cuoco %d" % i, "cucina")
    out = []

    def edit(n):
        for k in range(4):
            out.append(("e", post(client, b["id"], {**profile_body(name="B", preset="custom", titles=["cuoco"]), "categories": [{"label": f"E{n}{k}", "terms": ["cuoco"]}]}).status_code))

    def rm():
        out.append(("d", client.post(f"/api/profiles/{b['id']}/delete", headers=H).status_code))

    def mk(n):
        out.append(("c", client.post("/api/profiles", json=profile_body(name=f"N{n}", preset="custom", titles=["cuoco"]), headers=H).status_code))

    ts = [threading.Thread(target=edit, args=(0,)), threading.Thread(target=edit, args=(1,)), threading.Thread(target=rm), threading.Thread(target=mk, args=(1,)), threading.Thread(target=mk, args=(2,))]
    [t.start() for t in ts]
    for t in ts:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in ts), "deadlock"
    assert all(c in (200, 400, 404) for _, c in out), out
    # stato coerente: nessuna riga di job_profiles di profili che non esistono
    assert qdb.conn.execute("SELECT COUNT(*) FROM job_profiles WHERE profile_id NOT IN (SELECT id FROM profiles)").fetchone()[0] == 0


def test_modifica_di_profilo_eliminato_e_404_non_500(client):
    p = mkprofile(client, name="A", preset="custom", titles=["cuoco"])
    mkprofile(client, name="B", preset="custom", titles=["cuoco"])
    assert client.post(f"/api/profiles/{p['id']}/delete", headers=H).status_code == 200
    assert post(client, p["id"], profile_body(name="A", preset="custom", titles=["cuoco"])).status_code == 404


# ------------------------------------------------------------------ B74/B75 ------------------------------------------------------------------
def test_guida_voci_duplicate_e_collisioni(home):
    from jobshunter import onboarding as ob

    got = ob.onboarding_categories("c++, c#, assistente alla poltrona, assistente alla vendita, Cuoco, cuoco, CUOCO", "custom")
    labels = [c["label"] for c in got]
    assert len(labels) == len(set(labels)) == 5 and sum("CUOCO" in l for l in labels) == 1
    assert [c["terms"][0] for c in got].count("c++") == 1 and "c#" in [c["terms"][0] for c in got]
    prof.clean_categories(got)  # tutte valide
    got13 = ob.onboarding_categories(", ".join(f"voce{i}" for i in range(13)), "custom")
    assert len(got13) == 13


def test_guida_via_api_collisioni_arrivano_tutte(client, qdb):
    st, d = call(client, "post", "/api/onboarding/complete", {"country": "it", "home": "", "radius_km": 100, "profile": {"preset": "custom", "titles": ["dentista"], "categories": "c++, c#, assistente alla poltrona, assistente alla vendita"}})
    assert st == 200, d
    assert len(prof.ProfileStore(qdb).get(d["profile_id"]).categories) == 4

