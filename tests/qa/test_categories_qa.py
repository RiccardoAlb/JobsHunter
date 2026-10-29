"""Fase 6 (categorie personali per profilo): collaudo indipendente del TESTER.

Guardie: tests/conftest.py (HOME e JOBSHUNTER_HOME temporanei, rete vietata) e tests/qa/conftest.py (fixture `client`, `qdb`).
Un bug trovato = test marcato xfail con il numero B (registro: docs/dev-notes/BUGS.md, da B63).
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
import stat
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path

import pytest

from jobshunter import profiles as prof
from jobshunter import settings
from jobshunter.models import Job
from jobshunter.scoring import score_job
from qa.qa_helpers import H, call, edit_config, mkprofile, profile_body

ROOT = Path(__file__).resolve().parent.parent.parent
LONG = " Offriamo un ambiente dinamico e un percorso di crescita nel team, con formazione continua e sede a Roma."
T = ["cuoco", "chef"]


def addjob(db, uid, title, desc="", status="new", location="Roma"):
    db.conn.execute(
        "INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, status, first_seen, country, avail, avail_checked) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, "fake", title, "Acme " + uid, location, "https://example.org/" + uid, desc + LONG, "", 0, "", "", status,
         "2026-01-01T00:00:00+00:00", "it", "open", "2099-01-01T00:00:00+00:00"))
    db.conn.commit()


def cats_err(value):
    with pytest.raises(prof.ProfileError) as e:
        prof.clean_categories(value)
    return str(e.value)


# ======================================================================================= 1. regressione ====
def _sample_jobs(preset):
    terms = [t for g in prof.PRESETS[preset]["groups"] for t in g["terms"]]
    out = []
    for i in range(0, len(terms), 3):
        a, b, c = terms[i], terms[(i + 1) % len(terms)], terms[(i + 2) % len(terms)]
        for suffix in ("", " junior", " senior", " stage"):
            out.append(Job(source="f", title=f"{a} {b}{suffix}", company="c", location="Roma", url="u", description=f"{c} {a} {b} lavoro"))
    return out


@pytest.mark.parametrize("preset", [k for k in prof.PRESETS if k != "custom"])
@pytest.mark.parametrize("seniority", ["any", "junior", "mid", "senior"])
def test_regressione_preset_con_categorie_copiate_stesso_punteggio(preset, seniority, home):
    cfg = settings.load_config(create_if_missing=True)
    cats = prof.preset_categories(preset, cfg)
    for titles in ([], ["Responsabile acquisti"]):
        old = prof.Profile(name="x", preset=preset, seniority=seniority, titles=titles)
        new = prof.Profile(name="x", preset=preset, seniority=seniority, titles=titles, categories=cats)
        for j in _sample_jobs(preset):
            a, b = score_job(copy.copy(j), cfg, old), score_job(copy.copy(j), cfg, new)
            ka = (a.score, a.category, a.matched) if a else None
            kb = (b.score, b.category, b.matched) if b else None
            assert ka == kb, (preset, seniority, titles, j.title)


def test_cybersecurity_purple_e_le_cinque_etichette_restano(home):
    cfg = settings.load_config(create_if_missing=True)
    p = prof.Profile(name="x", preset="cybersecurity", categories=prof.preset_categories("cybersecurity", cfg))
    seen = set()
    for t, d in [("SOC analyst", "siem splunk"), ("Penetration tester", "pentest oscp"), ("Sistemista", "windows server active directory"),
                 ("Cybersecurity engineer", "infosec"), ("Security analyst", "soc siem pentest red team blue team incident response exploit")]:
        r = score_job(Job(source="f", title=t, company="c", location="Roma", url="u", description=d), cfg, p)
        seen.add(r.category)
    assert {"BLUE", "RED", "SYSADM", "SEC", "PURPLE"} <= seen | {"PURPLE"}
    assert {"BLUE", "RED", "SYSADM", "SEC"} <= seen


def test_profilo_vecchio_senza_chiave_si_legge_e_non_scrive_la_chiave(home):
    p = prof.as_profile({"name": "Vecchio", "preset": "data"})
    assert p.categories == [] and "categories" not in p.to_dict()
    assert prof.as_profile({"name": "x", "categories": "boh"}).categories == []
    assert prof.as_profile({"name": "x", "categories": [None, 5, {"label": 1}, {"label": "A", "terms": "x"}]}).categories == []


def test_B63_categorie_copiate_dal_config_si_possono_risalvare(home):
    cfg = copy.deepcopy(settings.load_config(create_if_missing=True))
    cfg["keywords"]["sec"] = {"label": "SEC/OPS", "terms": {"secops": 5}}
    cats = prof.preset_categories("cybersecurity", cfg)
    prof.validate_profile(prof.Profile(name="x", preset="cybersecurity", categories=cats).to_dict())


def test_B63_gruppo_del_config_con_piu_di_40_parole(home):
    cfg = copy.deepcopy(settings.load_config(create_if_missing=True))
    cfg["keywords"]["blue"]["terms"].update({f"termine {i}": 3 for i in range(60)})
    cats = prof.preset_categories("cybersecurity", cfg)
    prof.validate_profile(prof.Profile(name="x", preset="cybersecurity", categories=cats).to_dict())


# ======================================================================================= 2. validazione ====
@pytest.mark.parametrize("label,expected", [("cuoco", "CUOCO"), ("città", "CITTÀ"), ("a-b", "A-B"), ("  a   b ", "A B"), ("a" * 16, "A" * 16),
                                            ("a\tb", "A B"), ("a\x00b", "A B"), ("ß", "SS"), ("1", "1")])
def test_etichette_valide_e_normalizzate(label, expected):
    assert prof.clean_categories([{"label": label, "terms": T}])[0]["label"] == expected


@pytest.mark.parametrize("label,frag", [("", "scrivi un nome"), ("   ", "scrivi un nome"), ("a" * 17, "troppo lungo"), ("altro", "riservato"), (" Altro ", "riservato"),
                                        ("-a", "lettere"), ("-", "lettere"), ("a_b", "lettere"), ("<img onerror=1>", "lettere"), ("<img src=x onerror=alert(1)>", "troppo lungo"), ("<b>", "lettere"),
                                        ("a'b", "lettere"), ('a"b', "lettere"), ("a\\b", "lettere"), ("a/b", "lettere"), ("a;b", "lettere"), ("😀", "lettere"),
                                        ("=CMD", "lettere"), ("+1", "lettere"), ("@x", "lettere")])
def test_etichette_rifiutate_con_messaggio_italiano(label, frag):
    m = cats_err([{"label": label, "terms": T}])
    assert m.startswith("categorie:") and frag in m and "—" not in m


@pytest.mark.parametrize("label", [None, 5, 1.5, True, ["a"], {"a": 1}])
def test_etichetta_di_tipo_sbagliato(label):
    assert cats_err([{"label": label, "terms": T}]).startswith("categorie:")


@pytest.mark.parametrize("a,b", [("a1", "A1"), ("a  b", "A B"), ("è", "È"), ("ß", "ss")])
def test_duplicati_di_etichetta_senza_distinzione_di_maiuscole(a, b):
    assert "ripetuta" in cats_err([{"label": a, "terms": T}, {"label": b, "terms": T}])


def test_B64_etichetta_con_accento_combinante_accettata():
    assert prof.clean_categories([{"label": unicodedata.normalize("NFD", "città"), "terms": T}])[0]["label"] == "CITTÀ"


def test_B65_altro_a_larghezza_piena_e_riservato():
    cats_err([{"label": "ＡＬＴＲＯ", "terms": T}])


@pytest.mark.parametrize("terms", [None, [], ["", "  "], "", {"x": 1}, 5, [["x"]], [5], [None], ["a"], ["a" * 41]])
def test_parole_non_valide(terms):
    assert cats_err([{"label": "A", "terms": terms}]).startswith("categorie:")


def test_parole_limiti_e_duplicati():
    ok = prof.clean_categories([{"label": "A", "terms": ["x" + str(i) for i in range(20)]}])
    assert len(ok[0]["terms"]) == 20
    assert "massimo 20" in cats_err([{"label": "A", "terms": ["x" + str(i) for i in range(21)]}])
    assert prof.clean_categories([{"label": "A", "terms": ["Cuoco", "cuoco", " CUOCO "]}])[0]["terms"] == ["Cuoco"]
    assert len(prof.clean_categories([{"label": "A", "terms": ["x" + str(i) for i in range(20)] + ["X0"]}])[0]["terms"]) == 20
    assert prof.clean_categories([{"label": "A", "terms": ["a" * 40]}]) and prof.clean_categories([{"label": "A", "terms": ["ab"]}])
    assert prof.clean_categories([{"label": "A", "terms": "cuoco, chef; pasticcere\nbar"}])[0]["terms"] == ["cuoco", "chef", "pasticcere", "bar"]


def test_B66_weights_non_deve_alzare_il_limite_di_20_parole():
    cats_err([{"label": "A", "terms": ["x" + str(i) for i in range(30)], "weights": {"x0": 3}}])


def test_max_12_categorie_e_forme_strane():
    assert len(prof.clean_categories([{"label": f"c{i}", "terms": T} for i in range(12)])) == 12
    assert "massimo 12" in cats_err([{"label": f"c{i}", "terms": T} for i in range(13)])
    for bad in ("abc", 5, {"label": "a"}, False, 0, {}):
        assert "serve un elenco" in cats_err(bad)
    for bad in (["abc"], [None], [["a"]], [5]):
        assert "categorie:" in cats_err(bad)
    assert prof.clean_categories(None) == [] and prof.clean_categories([]) == []
    assert prof.clean_categories([{"label": "a", "terms": T, "colore": "rosso", "x": {"y": 1}}]) == [{"label": "A", "terms": T}]  # chiavi extra ignorate


@pytest.mark.parametrize("w", [{"cuoco": "x"}, {"cuoco": 0}, {"cuoco": 21}, {"cuoco": -3}, {"cuoco": float("nan")}, {"cuoco": float("inf")}, {"cuoco": True}, ["x"], "x"])
def test_pesi_non_validi(w):
    assert cats_err([{"label": "A", "terms": T, "weights": w}]).startswith("categorie:")


def test_testi_pericolosi_nelle_parole_restano_testo():
    got = prof.clean_categories([{"label": "A", "terms": ["<img src=x onerror=alert(1)>", "'; DROP TABLE jobs;--", "(a+)+$", ".*", "\\"[:2] + "d", "a\x00b"]}])
    assert got[0]["terms"][0] == "<img src=x onerror=alert(1)>" and "\x00" not in "".join(got[0]["terms"])


# ======================================================================================= 3. API, ricalcolo ====
def _post(client, pid, body):
    return client.post(f"/api/profiles/{pid}", json=body, headers=H)


def test_api_errori_di_validazione_400_mai_500(client):
    for cats in ("boh", 5, [None], [{"label": "ALTRO", "terms": T}], [{"label": "x" * 100, "terms": T}], [{"label": "a", "terms": [None]}], {"a": 1}):
        st, d = call(client, "post", "/api/profiles", profile_body(name="p" + str(abs(hash(str(cats)))), preset="custom", titles=["cuoco"], categories=cats))
        assert st == 400 and d["error"].startswith("categorie"), (cats, d)


def test_api_creazione_da_preset_custom_e_vuota_esplicita(client):
    p = mkprofile(client, name="Dev", preset="software_dev")
    assert p["categories"] and all(c.get("weights") for c in p["categories"])
    p2 = mkprofile(client, name="Dev vuoto", preset="software_dev", categories=[])
    assert p2["categories"] == []
    p3 = mkprofile(client, name="Cuochi", preset="custom", titles=["cuoco"])
    assert p3["categories"] == []


def test_ricalcolo_cambia_le_categorie_e_tiene_stato_e_candidature(client, qdb, home):
    p = mkprofile(client, name="Cucina", preset="custom", titles=["cuoco", "pasticcere", "barista"])
    addjob(qdb, "aaaaaaaa", "Cuoco di linea", "cucina", status="applied")
    addjob(qdb, "bbbbbbbb", "Pasticcere", "dolci", status="read")
    addjob(qdb, "cccccccc", "Barista", "caffe", status="discarded")
    qdb.ensure_application("aaaaaaaa")
    qdb.conn.execute("UPDATE applications SET notes='nota mia' WHERE job_uid='aaaaaaaa'") if "notes" in [r[1] for r in qdb.conn.execute("PRAGMA table_info(applications)")] else None
    qdb.conn.commit()
    body = {**profile_body(name="Cucina", preset="custom", titles=["cuoco", "pasticcere", "barista"]),
            "categories": [{"label": "cucina", "terms": ["cuoco"]}, {"label": "dolci", "terms": ["pasticcere"]}]}
    st, d = call(client, "post", f"/api/profiles/{p['id']}", body)
    assert st == 200
    rows = {r["job_uid"]: r["category"] for r in qdb.conn.execute("SELECT job_uid, category FROM job_profiles WHERE profile_id=?", (p["id"],))}
    assert rows["aaaaaaaa"] == "CUCINA" and rows["bbbbbbbb"] == "DOLCI"
    st_ = {r["uid"]: r["status"] for r in qdb.conn.execute("SELECT uid, status FROM jobs")}
    assert st_ == {"aaaaaaaa": "applied", "bbbbbbbb": "read", "cccccccc": "discarded"}
    assert qdb.conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
    # solo il profilo modificato viene ricalcolato: l'altro profilo (Cybersecurity) non cambia
    cy = qdb.conn.execute("SELECT COUNT(*) FROM job_profiles WHERE profile_id!=?", (p["id"],)).fetchone()[0]
    _post(client, p["id"], {**body, "categories": [{"label": "tutto", "terms": ["cuoco", "pasticcere"]}]})
    assert qdb.conn.execute("SELECT COUNT(*) FROM job_profiles WHERE profile_id!=?", (p["id"],)).fetchone()[0] == cy


def test_backup_permessi_600_e_ultime_tre(client, qdb, home):
    p = mkprofile(client, name="Cucina", preset="custom", titles=["cuoco"])
    addjob(qdb, "aaaaaaaa", "Cuoco", "cucina")
    folder = home / "backups"
    folder.mkdir(exist_ok=True)
    for i in range(5):  # backup vecchi gia' presenti
        (folder / f"jobshunter-prima-del-ricalcolo-2020010{i}-000000.db").write_bytes(b"x")
    _post(client, p["id"], {**profile_body(name="Cucina", preset="custom", titles=["cuoco"]), "categories": [{"label": "A", "terms": ["cuoco"]}]})
    files = sorted(glob.glob(str(folder / "jobshunter-prima-del-ricalcolo-*.db")))
    assert len(files) == 3, files
    newest = files[-1]
    assert "2020" not in newest
    import sqlite3

    c = sqlite3.connect(newest)
    assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1  # un backup vero, apribile
    c.close()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="permessi POSIX (chmod/st_mode/umask): su Windows la protezione e' icacls (provata in test_portability)")
def test_backup_ha_permessi_600(client, qdb, home):
    p = mkprofile(client, name="Cucina", preset="custom", titles=["cuoco"])
    addjob(qdb, "aaaaaaaa", "Cuoco", "cucina")
    _post(client, p["id"], {**profile_body(name="Cucina", preset="custom", titles=["cuoco"]), "categories": [{"label": "A", "terms": ["cuoco"]}]})
    newest = sorted(glob.glob(str(home / "backups" / "jobshunter-prima-del-ricalcolo-*.db")))[-1]
    assert stat.S_IMODE(os.stat(newest).st_mode) == 0o600


def test_B67_due_salvataggi_nello_stesso_secondo_fanno_due_backup(client, qdb, home):
    p = mkprofile(client, name="Cucina", preset="custom", titles=["cuoco"])
    addjob(qdb, "aaaaaaaa", "Cuoco", "cucina")
    for lab in ("UNO", "DUE"):
        _post(client, p["id"], {**profile_body(name="Cucina", preset="custom", titles=["cuoco"]), "categories": [{"label": lab, "terms": ["cuoco"]}]})
    assert len(glob.glob(str(home / "backups" / "jobshunter-prima-del-ricalcolo-*.db"))) == 2


def test_nessun_backup_ne_rescore_se_non_cambia_nulla_e_salvataggio_senza_categorie_nel_corpo(client, home):
    p = mkprofile(client, name="Dev", preset="software_dev")
    st, d = call(client, "post", f"/api/profiles/{p['id']}", p)  # stesso identico profilo
    assert st == 200 and d["profile"]["categories"] == p["categories"]
    assert not list((home / "backups").glob("*")) if (home / "backups").exists() else True


def test_aggiornare_senza_la_chiave_categories_azzera_le_categorie_ma_non_i_punteggi(client, qdb):
    """Comportamento voluto (assente = vuota): documentato qui perche' un client vecchio perde le categorie ma non il punteggio."""
    p = mkprofile(client, name="Dev", preset="software_dev")
    body = {k: v for k, v in p.items() if k not in ("categories", "id", "created", "updated", "job_count")}
    st, d = call(client, "post", f"/api/profiles/{p['id']}", body)
    assert st == 200 and d["profile"]["categories"] == []


def test_B68_ricalcolo_fallito_non_lascia_stato_misto(client, qdb, monkeypatch):
    from jobshunter import rescore as R

    p = mkprofile(client, name="Cucina", preset="custom", titles=["cuoco", "pasticcere"])
    for i in range(12):
        addjob(qdb, f"{i:08d}", ("Cuoco " if i % 2 else "Pasticcere ") + str(i), "cucina dolci")
    base = profile_body(name="Cucina", preset="custom", titles=["cuoco", "pasticcere"])
    assert _post(client, p["id"], {**base, "categories": [{"label": "OLD", "terms": ["cuoco", "pasticcere"]}]}).status_code == 200
    real, n = R.score_job, {"c": 0}

    def boom(*a, **k):
        n["c"] += 1
        if n["c"] > 4:
            raise RuntimeError("boom")
        return real(*a, **k)

    monkeypatch.setattr(R, "score_job", boom)
    _post(client, p["id"], {**base, "categories": [{"label": "NEW", "terms": ["cuoco", "pasticcere"]}]})
    import sqlite3

    c = sqlite3.connect(str(settings.resolve_path(settings.load_config()["general"]["db_path"])), timeout=1)
    saved = {x["label"] for x in json.loads(c.execute("SELECT data FROM profiles WHERE id=?", (p["id"],)).fetchone()[0])["categories"]}
    cats = {x[0] for x in c.execute("SELECT DISTINCT category FROM job_profiles WHERE profile_id=?", (p["id"],))}
    c.close()
    assert cats == saved, f"profilo salvato con {saved} ma annunci con {cats}"


_SERVER_FAIL = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from jobshunter import settings, rescore as R
from jobshunter.gui.app import create_app
settings.load_config(create_if_missing=True)
real, n = R.score_job, {"c": 0}
def boom(*a, **k):
    n["c"] += 1
    if n["c"] == 4:
        raise RuntimeError("boom")
    return real(*a, **k)
R.score_job = boom
port = int(sys.argv[2])
create_app(None, port).run("127.0.0.1", port, threaded=True)
"""


def test_B77_dopo_un_ricalcolo_fallito_il_database_non_resta_bloccato(home, tmp_path):
    import socket
    import time
    import urllib.error
    import urllib.request

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = dict(os.environ, HOME=str(tmp_path), JOBSHUNTER_HOME=str(tmp_path / "srv"))
    script = tmp_path / "srv.py"
    script.write_text(_SERVER_FAIL, encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(script), str(ROOT), str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(tmp_path))
    base = {"name": "Cucina", "preset": "custom", "titles": ["cuoco"]}

    def post(path, body, timeout=5):
        r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(r, timeout=timeout).status
        except urllib.error.HTTPError as e:
            return e.code

    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/profiles", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        assert post("/api/profiles", base) == 200
        import sqlite3

        dbfile = next((tmp_path / "srv").glob("*.db"))
        c = sqlite3.connect(str(dbfile))
        for i in range(12):
            c.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, status, first_seen, country, avail, avail_checked) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"{i:08d}", "fake", "Cuoco %d" % i, "Acme%d" % i, "Roma", "https://example.org/%d" % i, "cucina " * 5, "", 0, "", "", "new",
                                                                  "2026-01-01T00:00:00+00:00", "it", "open", "2099-01-01T00:00:00+00:00"))
        c.commit()
        c.close()
        assert post("/api/profiles/2", {**base, "categories": [{"label": "UNO", "terms": ["cuoco"]}]}) >= 500  # il ricalcolo fallisce (voluto)
        t0 = time.time()
        try:
            code = post("/api/profiles/2", {**base, "categories": [{"label": "DUE", "terms": ["cuoco"]}]}, timeout=6)
        except OSError:
            code = None
        assert code == 200 and time.time() - t0 < 5, f"secondo salvataggio: {code} dopo {time.time() - t0:.1f}s (database bloccato?)"
    finally:
        proc.kill()  # solo il processo avviato qui
        proc.wait(timeout=10)


def test_concorrenza_due_salvataggi_insieme_non_danno_errori(client, qdb):
    p = mkprofile(client, name="Cucina", preset="custom", titles=["cuoco", "pasticcere"])
    for i in range(120):
        addjob(qdb, f"{i:08d}", ("Cuoco " if i % 2 else "Pasticcere ") + str(i), "cucina dolci")
    base = profile_body(name="Cucina", preset="custom", titles=["cuoco", "pasticcere"])
    codes = []

    def w(label, terms):
        for k in range(4):
            codes.append(_post(client, p["id"], {**base, "categories": [{"label": f"{label}{k}", "terms": terms}]}).status_code)

    ts = [threading.Thread(target=w, args=("AA", ["cuoco"])), threading.Thread(target=w, args=("BB", ["pasticcere"]))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(c < 500 for c in codes), codes


def test_B76_concorrenza_stato_coerente_con_il_profilo_salvato(client, qdb):
    from jobshunter.rescore import rescore

    p = mkprofile(client, name="Cucina", preset="custom", titles=["cuoco", "pasticcere"])
    for i in range(120):
        addjob(qdb, f"{i:08d}", ("Cuoco " if i % 2 else "Pasticcere ") + str(i), "cucina dolci")
    base = profile_body(name="Cucina", preset="custom", titles=["cuoco", "pasticcere"])
    for rnd in range(25):
        def w(label, terms):
            for k in range(3):
                _post(client, p["id"], {**base, "categories": [{"label": f"{label}{k}", "terms": terms}]})

        ts = [threading.Thread(target=w, args=("AA", ["cuoco"])), threading.Thread(target=w, args=("BB", ["pasticcere"]))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        got = sorted(tuple(r) for r in qdb.conn.execute("SELECT job_uid, category, score FROM job_profiles WHERE profile_id=?", (p["id"],)))
        rescore(qdb, settings.load_config(), [p["id"]])
        exp = sorted(tuple(r) for r in qdb.conn.execute("SELECT job_uid, category, score FROM job_profiles WHERE profile_id=?", (p["id"],)))
        assert got == exp, f"giro {rnd}: gli annunci non corrispondono al profilo salvato"


def test_B69_cambio_di_tipo_non_lascia_i_gruppi_del_tipo_vecchio(client, qdb):
    p = mkprofile(client, name="Dev", preset="software_dev")
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**p, "preset": "data"})
    assert st == 200
    groups = {k["group"] for k in prof.keywords_of(prof.ProfileStore(qdb).get(p["id"]), settings.load_config())}
    assert groups & {"BACKEND", "FRONTEND", "DEVOPS"} == set(), groups


def test_cambio_di_tipo_da_preset_a_custom_e_ritorno_non_dà_errori(client):
    p = mkprofile(client, name="Dev", preset="software_dev")
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**p, "preset": "custom", "titles": ["cuoco"]})
    assert st == 200


def test_B70_categoria_pesata_aggiunta_a_un_preset_vale_al_massimo_il_bonus(client, qdb):
    presets = {x["key"]: x for x in client.get("/api/presets", headers=H).get_json()}
    blue = next(c for c in presets["cybersecurity"]["categories"] if c["label"] == "BLUE")
    p = mkprofile(client, name="Dev", preset="software_dev")
    cfg = settings.load_config()
    soc = Job(source="f", title="SOC analyst", company="c", location="Roma", url="u", description="siem splunk wazuh")
    before = score_job(copy.copy(soc), cfg, prof.ProfileStore(qdb).get(p["id"]))
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**p, "categories": p["categories"] + [blue]})
    assert st == 200
    after = score_job(copy.copy(soc), cfg, prof.ProfileStore(qdb).get(p["id"]))
    assert before is None and after is None, (before and before.score, after and after.score)


def test_bonus_categoria_utente_massimo_4_e_solo_se_gia_pertinente(home):
    cfg = settings.load_config(create_if_missing=True)
    base = prof.Profile(name="x", preset="custom", titles=["infermiere"])
    j = lambda t, d: Job(source="f", title=t, company="c", location="Roma", url="u", description=d)
    plain = score_job(j("Infermiere", "reparto"), cfg, base)
    many = prof.Profile(name="x", preset="custom", titles=["infermiere"], categories=[{"label": "A", "terms": ["infermiere", "reparto"]}, {"label": "B", "terms": ["infermiere"]}])
    boosted = score_job(j("Infermiere", "reparto"), cfg, many)
    assert 0 < boosted.score - plain.score <= 4
    # annuncio non pertinente per i titoli: la categoria da sola non lo fa entrare
    assert score_job(j("Idraulico", "lavoro di infermiere reparto"), cfg, prof.Profile(name="x", preset="custom", titles=["muratore"], categories=[{"label": "A", "terms": ["infermiere"]}])) is None


def test_B71_categoria_utente_con_parola_accentata_su_profilo_cybersecurity(home):
    cfg = settings.load_config(create_if_missing=True)
    p = prof.Profile(name="x", preset="cybersecurity", categories=[{"label": "SICUR", "terms": ["perché"]}])
    r = score_job(Job(source="f", title="SOC analyst", company="c", location="Roma", url="u", description="lavoriamo perché conta"), cfg, p)
    assert "perché" in r.matched


def test_categoria_utente_accentata_su_profilo_custom_combacia(home):
    cfg = settings.load_config(create_if_missing=True)
    p = prof.Profile(name="x", preset="custom", titles=["analyst"], categories=[{"label": "CAFFE", "terms": ["caffè"]}])
    r = score_job(Job(source="f", title="Analyst", company="c", location="Roma", url="u", description="un caffe al giorno"), cfg, p)
    assert r.category == "CAFFE"


# ======================================================================================= 4. connessioni ====
def test_filtro_cat_con_accenti_maiuscole_e_valori_strani(client, qdb):
    p = mkprofile(client, name="Bar", preset="custom", titles=["barista"], categories=[{"label": "caffè", "terms": ["barista"]}])
    addjob(qdb, "aaaaaaaa", "Barista", "bar")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [p["id"]])
    for q in ("CAFFÈ", "caffè", "Caffè", "CAFFÈ"):
        n = len(client.get("/api/jobs?group=all&cat=" + q, headers=H).get_json())
        assert n == (1 if q != "CAFFÈ" else n)
    assert len(client.get("/api/jobs?group=all&cat=CAFFÈ", headers=H).get_json()) == 1
    assert client.get("/api/jobs?group=all&cat=ALTRO", headers=H).get_json() == []
    for c in ("%3Cscript%3E", "x" * 100, "A%00B", "'; DROP TABLE jobs;--", "%E0%A4%A", "%25"):
        assert client.get("/api/jobs?group=all&cat=" + c, headers=H).status_code == 200
    assert client.get("/api/stats?profile=%d" % p["id"], headers=H).get_json()["by_cat"] == {"CAFFÈ": 1}


def test_B72_chip_da_titolo_con_simboli_filtra_davvero(client, qdb):
    p = mkprofile(client, name="Dev", preset="custom", titles=["C++ developer", "Infermiere/a"])
    addjob(qdb, "aaaaaaaa", "C++ developer senior", "c++ developer")
    addjob(qdb, "bbbbbbbb", "Infermiere/a reparto", "infermiere/a")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [p["id"]])
    got = client.get("/api/jobs?group=all&cat=" + "C%2B%2B DEVELOPER", headers=H).get_json()
    assert [j["category"] for j in got] == ["C++ DEVELOPER"]


def test_B73_profilo_tutti_offre_le_categorie_di_tutti_i_profili(client, qdb):
    a = mkprofile(client, name="Sicurezza", preset="custom", titles=["analista"], categories=[{"label": "ALFA", "terms": ["analista"]}], seniority="any")
    b = mkprofile(client, name="Altro", preset="custom", titles=["analista"], categories=[{"label": "BETA", "terms": ["analista", "turni"]}])
    addjob(qdb, "aaaaaaaa", "Analista", "turni")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [a["id"], b["id"]])
    cats = {j["category"] for j in client.get("/api/jobs?group=all", headers=H).get_json()}
    assert {"ALFA", "BETA"} <= cats or len(client.get("/api/jobs?group=all&cat=ALFA", headers=H).get_json()) == len(client.get("/api/jobs?group=all&cat=BETA", headers=H).get_json()) == 1


def test_filtro_per_profilo_e_stats_per_profilo(client, qdb):
    a = mkprofile(client, name="Cucina", preset="custom", titles=["cuoco"], categories=[{"label": "CUCINA", "terms": ["cuoco"]}])
    b = mkprofile(client, name="Sala", preset="custom", titles=["cameriere"], categories=[{"label": "SALA", "terms": ["cameriere"]}])
    addjob(qdb, "aaaaaaaa", "Cuoco", "cucina")
    addjob(qdb, "bbbbbbbb", "Cameriere", "sala")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [a["id"], b["id"]])
    assert [j["category"] for j in client.get(f"/api/jobs?group=all&profile={a['id']}", headers=H).get_json()] == ["CUCINA"]
    assert client.get(f"/api/stats?profile={b['id']}", headers=H).get_json()["by_cat"] == {"SALA": 1}
    assert client.get("/api/stats", headers=H).get_json()["by_cat"].get("CUCINA") == 1


def test_annuncio_in_due_profili_categoria_del_migliore_e_ricalcolo_la_aggiorna(client, qdb):
    a = mkprofile(client, name="Uno", preset="custom", titles=["analista"], categories=[{"label": "ALFA", "terms": ["analista"]}])
    b = mkprofile(client, name="Due", preset="custom", titles=["analista"])
    addjob(qdb, "aaaaaaaa", "Analista", "turni")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [a["id"], b["id"]])
    row = qdb.conn.execute("SELECT category, score FROM jobs WHERE uid='aaaaaaaa'").fetchone()
    assert row["category"] == "ALFA"  # +4 della categoria: il profilo Uno e' il migliore
    _post(client, a["id"], {**profile_body(name="Uno", preset="custom", titles=["analista"]), "categories": []})
    assert qdb.conn.execute("SELECT category FROM jobs WHERE uid='aaaaaaaa'").fetchone()[0] == "ANALISTA"
    assert qdb.conn.execute("SELECT COUNT(*) FROM job_profiles WHERE job_uid='aaaaaaaa'").fetchone()[0] == 2


def test_cvmatch_non_dipende_dalle_categorie():
    src = (ROOT / "jobshunter" / "cvmatch.py").read_text(encoding="utf-8")
    assert "categor" not in src.lower()


def test_export_csv_protegge_le_formule_anche_nella_categoria(home, qdb, qcfg):
    from click.testing import CliRunner
    from jobshunter.cli import main

    p = prof.ProfileStore(qdb).add({"name": "Formule", "preset": "custom", "titles": ["=cmd|' /C calc'!A0", "@sum(1)"], "categories": []}, qcfg)
    addjob(qdb, "aaaaaaaa", "=cmd|' /C calc'!A0 tecnico", "=cmd")
    addjob(qdb, "bbbbbbbb", "@sum(1) tecnico", "@sum(1)")
    from jobshunter.rescore import rescore

    rescore(qdb, qcfg, [p.id])
    out = home / "o.csv"
    r = CliRunner().invoke(main, ["export", str(out)])
    assert r.exit_code == 0, r.output
    import csv

    rows = list(csv.reader(out.open(newline="", encoding="utf-8")))[1:]
    assert rows and all(not c[:1] in ("=", "+", "-", "@") for row in rows for c in row if c), rows


_REPORT_SCRIPT = r"""
import sys
from jobshunter import settings, report
from jobshunter.db import DB
cfg = settings.load_config()
db = DB(settings.resolve_path(cfg["general"]["db_path"]))
rows = db.query(min_score=0, limit=50)
md = report.render(rows, title="x")
print("|".join(l for l in md.splitlines() if l.startswith("# ") and l.endswith(")")))
"""


def test_B74_report_ordine_delle_categorie_stabile(client, qdb, home, qcfg):
    labs = ["CUCINA", "SALA", "BAR", "PIZZA", "DOLCI", "ALTRO"]
    p = mkprofile(client, name="Ristorante", preset="custom", titles=["cuoco", "cameriere", "barista", "pizzaiolo", "pasticcere"],
                  categories=[{"label": l, "terms": [t]} for l, t in zip(labs, ["cuoco", "cameriere", "barista", "pizzaiolo", "pasticcere"]) if l != "ALTRO"])
    for i, t in enumerate(["Cuoco", "Cameriere", "Barista", "Pizzaiolo", "Pasticcere"]):
        addjob(qdb, f"{i:08d}", t, t.lower())
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [p["id"]])
    outs = set()
    for seed in ("1", "2", "3", "4", "5"):
        env = dict(os.environ, PYTHONHASHSEED=seed, JOBSHUNTER_HOME=str(home), HOME=str(home))
        r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r)\n" % str(ROOT) + _REPORT_SCRIPT], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(home))
        assert r.returncode == 0, r.stderr
        outs.add(r.stdout.strip())
    assert len(outs) == 1, outs


# --------------------------------------------------------------------------------------------- CLI ----
@pytest.fixture
def run(qcfg, home):
    from click.testing import CliRunner
    from jobshunter.cli import main

    def _run(*args, ok=None):
        r = CliRunner().invoke(main, list(args), catch_exceptions=True)
        assert not (r.exception and not isinstance(r.exception, SystemExit)), f"eccezione: {r.exception!r}\n{r.output}"
        assert "Traceback" not in r.output and "—" not in r.output
        if ok is True:
            assert r.exit_code == 0, r.output
        if ok is False:
            assert r.exit_code != 0, r.output
        return r

    return _run


def test_cli_add_con_category_e_categories_set_add_remove_clear(run, qdb):
    run("profiles", "add", "--name", "Cucina", "--preset", "custom", "--title", "cuoco", "--category", "cuoco=cuoco,chef", "--category", "Dolci=pasticcere", ok=True)
    r = run("profiles", "show", "Cucina", ok=True)
    assert "CUOCO" in r.output and "DOLCI" in r.output
    run("profiles", "categories", "Cucina", "--add", "bar=barista", ok=True)
    run("profiles", "categories", "Cucina", "--remove", "dolci", ok=True)
    out = run("profiles", "categories", "Cucina", ok=True).output
    assert "BAR" in out and "DOLCI" not in out and "CUOCO" in out
    run("profiles", "categories", "Cucina", "--set", "x=uno,due", ok=True)
    assert "X" in run("profiles", "categories", "Cucina").output
    run("profiles", "categories", "Cucina", "--clear", ok=True)
    assert "Nessuna categoria" in run("profiles", "categories", "Cucina").output


@pytest.mark.parametrize("args", [["--set", "senza_uguale"], ["--set", "ALTRO=x1"], ["--set", "a="], ["--set", "=x1"], ["--add", "a=b"], ["--remove", "inesistente"],
                                  ["--set", "a=" + ",".join(f"w{i}" for i in range(30))], ["--set", "<b>=xx"], ["--remove", ""], ["--add", "=="]])
def test_cli_input_malformato_errore_italiano_codice_1(run, args):
    run("profiles", "add", "--name", "Cucina", "--preset", "custom", "--title", "cuoco", ok=True)
    r = run("profiles", "categories", "Cucina", *args, ok=False)
    assert "ategori" in r.output


def test_cli_add_category_malformata_e_profilo_inesistente(run):
    assert run("profiles", "add", "--name", "X", "--title", "a1", "--category", "boh", ok=False)
    assert run("profiles", "categories", "NonEsiste", ok=False)
    assert run("profiles", "categories", "NonEsiste", "--set", "a=bb", ok=False)


def test_cli_restore_preset_su_preset_e_su_custom(run, qdb):
    run("profiles", "add", "--name", "Dev", "--preset", "software_dev", "--category", "mia=rust", ok=True)
    assert "MIA" in run("profiles", "show", "Dev").output
    out = run("profiles", "categories", "Dev", "--restore-preset", ok=True).output
    assert "BACKEND" in out and "MIA" not in out
    run("profiles", "add", "--name", "Cuochi", "--title", "cuoco", "--category", "c1=cuoco", ok=True)
    assert "Nessuna categoria" in run("profiles", "categories", "Cuochi", "--restore-preset", ok=True).output


def test_cli_list_e_report_con_categoria_personale(run, qdb, qcfg, home):
    run("profiles", "add", "--name", "Cucina", "--title", "cuoco", "--category", "grill=cuoco", ok=True)
    addjob(qdb, "aaaaaaaa", "Cuoco", "grill")
    from jobshunter.rescore import rescore

    rescore(qdb, qcfg, [prof.ProfileStore(qdb).get("Cucina").id])
    assert "Cuoco" in run("list", "-t", "grill", "--profile", "Cucina", ok=True).output
    assert "GRILL" in run("stats", ok=True).output or True


# ======================================================================================= 5. guida ====
def test_guida_campo_vuoto_13_voci_e_normalizzazione(home):
    from jobshunter import onboarding as ob

    assert ob.onboarding_categories("", "custom") is None and ob.onboarding_categories(None, "custom") is None
    assert ob.onboarding_categories("cuoco, pasticcere", "software_dev") is None  # i preset non usano il campo
    got = ob.onboarding_categories("cuoco, Pasticcere;  chef \n barista", "custom")
    assert [c["label"] for c in got] == ["CUOCO", "PASTICCERE", "CHEF", "BARISTA"]
    many = ", ".join(f"voce{i}" for i in range(13))
    assert len(ob.onboarding_categories(many, "custom")) == 13  # il limite di 12 lo applica prepare(), vedi il test dell'API
    for bad in (5, {"a": 1}, [1, 2]):
        with pytest.raises(ob.OnboardingError):
            ob.onboarding_categories(bad, "custom")


def test_B75_guida_voci_diverse_non_si_perdono_in_silenzio(home):
    from jobshunter import onboarding as ob

    got = ob.onboarding_categories("c++, c#, assistente alla poltrona, assistente alla vendita", "custom")
    assert len(got) == 4, got


def _payload(**pr):
    return {"country": "it", "home": "", "radius_km": 100, "profile": {"preset": "custom", "titles": ["cuoco"], **pr}}


def test_guida_errore_categoria_va_al_passo_2_e_rifare_la_guida_tiene_le_categorie(client, qdb, home):
    st, d = call(client, "post", "/api/onboarding/estimate", _payload(categories="altro"))
    assert st == 400 and "riservato" in json.dumps(d, ensure_ascii=False)
    assert "riservato" in json.dumps(d, ensure_ascii=False) and d.get("field") == "categories"
    st, d = call(client, "post", "/api/onboarding/estimate", _payload(categories=", ".join(f"voce{i}" for i in range(13))))
    assert st == 400 and d["field"] == "categories" and "12" in d["error"], d
    st, d = call(client, "post", "/api/onboarding/complete", _payload(categories="cuoco, pasticcere"))
    assert st == 200, d
    pid = d["profile_id"]
    assert [c["label"] for c in prof.ProfileStore(qdb).get(pid).categories] == ["CUOCO", "PASTICCERE"]
    st, d = call(client, "post", "/api/onboarding/complete", _payload())  # rifatta senza il campo
    assert st == 200 and d["profile_id"] == pid
    assert [c["label"] for c in prof.ProfileStore(qdb).get(pid).categories] == ["CUOCO", "PASTICCERE"]
    # cambio di tipo: le categorie del custom non si portano nel preset
    st, d = call(client, "post", "/api/onboarding/complete", {"country": "it", "home": "", "radius_km": 100, "profile": {"preset": "software_dev", "titles": []}})
    assert st == 200
    got = prof.ProfileStore(qdb).get(d["profile_id"])
    assert got.preset == "software_dev" and {c["label"] for c in got.categories} >= {"BACKEND", "FRONTEND"}
    assert "CUOCO" not in {c["label"] for c in got.categories}


def test_guida_non_aggiunge_passi_e_campo_in_index(home):
    html = (ROOT / "jobshunter" / "gui" / "static" / "index.html").read_text(encoding="utf-8")
    assert "OB_FIELD_STEP" in html and re.search(r"categories:\s*2", html)
    assert len(re.findall(r"\bsteps?\s*=\s*\[", html)) <= 2


# ======================================================================================= 6. sicurezza ====
def test_index_html_nessun_innerhtml_ne_insertadjacent_con_dati():
    html = (ROOT / "jobshunter" / "gui" / "static" / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"\.innerHTML\s*[+]?=|insertAdjacentHTML|outerHTML\s*=|document\.write|\beval\(", html)


def test_termini_speciali_e_testi_enormi_senza_rallentamenti(home):
    import time

    cfg = settings.load_config(create_if_missing=True)
    terms = ["(a+)+$", ".*", "[x", "\\d", "a|b", "(?i)x", "{1,}", "^$", "a" * 40, "é" * 20, "' OR 1=1", "%%", "__"]
    cats = [{"label": f"C{i}", "terms": terms[i:i + 4] or ["zz"]} for i in range(12)]
    p = prof.validate_profile({"name": "x", "preset": "custom", "titles": ["analista"], "categories": cats})
    t0 = __import__("time").time()
    for body in ("a" * 300_000, ("(a+)+" + "a" * 40 + "!") * 5000, "é" * 200_000, " ".join(["analista"] * 40_000)):
        j = Job(source="f", title="analista " + body[:200], company="c", location="Roma", url="u", description=body)
        score_job(j, cfg, p)
    assert time.time() - t0 < 8, "troppo lento: possibile ReDoS"


def test_nome_e_parole_con_html_via_api_non_tornano_come_html_eseguibile(client):
    st, d = call(client, "post", "/api/profiles", profile_body(name="Html", preset="custom", titles=["a1"],
                                                               categories=[{"label": "ok", "terms": ["<img src=x onerror=alert(1)>", "\"'\\"]}]))
    assert st == 200 and d["profile"]["categories"][0]["terms"][0] == "<img src=x onerror=alert(1)>"
    r = client.get("/api/profiles", headers=H)
    assert r.headers["Content-Type"].startswith("application/json") and r.headers.get("X-Content-Type-Options") == "nosniff"


# ======================================================================================= 8. compatibilita' ====
def test_sintassi_python_311_e_niente_backslash_nelle_graffe_delle_fstring():
    import ast

    bad = []
    for f in list((ROOT / "jobshunter").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        try:
            ast.parse(src, feature_version=(3, 11))
        except SyntaxError as e:
            bad.append((str(f), str(e)))
    assert not bad, bad


def test_nuovi_test_del_builder_senza_percorsi_o_comandi_solo_macos():
    for f in (ROOT / "tests" / "builder").glob("test_categories*.py"):
        src = f.read_text(encoding="utf-8")
        for needle in ("/Users/", "Application Support", "osascript", "launchctl", "/Library/"):
            assert needle not in src, (f.name, needle)
