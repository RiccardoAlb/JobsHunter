"""Fase 6, terzo giro del TESTER: aggiramenti nuovi, ?cat= ostile, refresh_best che solleva, deadlock su server vero (B81 in poi)."""
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
from qa.qa_helpers import H, call, mkprofile, profile_body
from qa.test_categories_qa import ROOT, addjob
from qa.test_categories_qa2 import get, post

PRESETS = [k for k in prof.PRESETS if k != "custom"]


def _variants(base):
    v = {}
    for name, fn in {
        "peso13": lambda c: c["weights"].__setitem__(list(c["weights"])[0], 13),
        "peso1000": lambda c: c["weights"].__setitem__(list(c["weights"])[0], 1000),
        "peso_str": lambda c: c.update(weights={k: "5" for k in c["weights"]}),
        "peso_lista": lambda c: c.update(weights=[1]),
        "peso_nan": lambda c: c["weights"].__setitem__(list(c["weights"])[0], float("inf")),
        "41termini": lambda c: c.update(terms=[f"t{i} x" for i in range(41)], weights={"t0 x": 5}),  # B81: un gruppo del tipo si puo' allargare fino a max(40, parole + 20)
        "150termini": lambda c: c.update(terms=[f"t{i} x" for i in range(150)], weights={f"t{i} x": 12 for i in range(150)}),
        "parola81": lambda c: c.update(terms=c["terms"] + ["y" * 81], weights=c["weights"]),
        "label<>": lambda c: c.update(label="<b>" + c["label"][:5]),
        "label_virgolette": lambda c: c.update(label=c["label"] + '"\''),
        "label_backslash": lambda c: c.update(label=c["label"][:5] + "\\"),
        "label_altro_larga": lambda c: c.update(label="ＡＬＴＲＯ"),
        "label_nfkc_tag": lambda c: c.update(label="＜img＞"),
    }.items():
        c = copy.deepcopy(base)
        fn(c)
        v[name] = c
    return v


@pytest.mark.parametrize("preset", PRESETS + ["custom"])
def test_nessun_aggiramento_dei_limiti(client, preset):
    cfg = settings.load_config()
    pc = prof.preset_categories(preset, cfg) or [{"label": "BACKEND", "terms": [f"aa{i} x" for i in range(10)], "weights": {"aa0 x": 5}}]
    for name, v in _variants(pc[0]).items():
        if preset == "custom" and name == "peso13":
            continue  # nei profili personalizzati i pesi vanno da 1 a 20 (spec)
        body = profile_body(name=f"{preset}-{name}", preset=preset, titles=["abc"] if preset == "custom" else [], categories=[v])
        st, d = call(client, "post", "/api/profiles", body)
        assert st == 400, (preset, name, [(c["label"], len(c["terms"]), max(c.get("weights", {"": 0}).values())) for c in d["profile"]["categories"]])
        assert d["error"].startswith("categorie") or "tipo" in d["error"]


def test_preset_sconosciuto_e_tipo_non_stringa(client):
    for preset in ("nope", "", None, 5, ["cybersecurity"]):
        st, d = call(client, "post", "/api/profiles", profile_body(name="x", preset=preset, categories=[{"label": "A", "terms": ["xx"], "weights": {"xx": 5}}]))
        assert st == 400


@pytest.mark.parametrize("preset", PRESETS)
def test_copie_legittime_si_risalvano_identiche_e_pesi_alti_solo_li(client, preset):
    cfg = settings.load_config()
    cats = prof.preset_categories(preset, cfg)
    p = mkprofile(client, name="P", preset=preset)
    assert p["categories"] == [{**c, "weights": {k.lower(): v for k, v in c["weights"].items()}} for c in cats] or p["categories"] == cats
    st, d = call(client, "post", f"/api/profiles/{p['id']}", p)
    assert st == 200 and d["profile"]["categories"] == p["categories"]
    again = call(client, "post", f"/api/profiles/{p['id']}", {**d["profile"], "categories": list(reversed(d["profile"]["categories"]))})
    assert again[0] == 200
    # i pesi alti (oltre 12) non esistono in nessuna categoria dei preset veri
    assert max(w for c in p["categories"] for w in c["weights"].values()) <= prof.TRUSTED_MAX_WEIGHT


def test_B81_categoria_del_config_con_piu_di_20_parole_modificabile(home):
    cfg = copy.deepcopy(settings.load_config(create_if_missing=True))
    cfg["keywords"]["blue"]["terms"].update({f"extra term {i}": 4 for i in range(12)})
    cats = prof.preset_categories("cybersecurity", cfg)
    assert len(prof.clean_categories(cats, "cybersecurity", cfg)) == 4
    c = copy.deepcopy(cats)
    t = c[0]["terms"].pop()
    c[0]["weights"].pop(t.lower())
    prof.clean_categories(c, "cybersecurity", cfg)


def test_categoria_di_preset_default_aggiungere_una_parola_fino_a_20(client):
    p = mkprofile(client, name="Cy", preset="cybersecurity")
    cats = copy.deepcopy(p["categories"])
    cats[0]["terms"].append("zzuno")  # BLUE: 19 -> 20
    assert call(client, "post", f"/api/profiles/{p['id']}", {**p, "categories": cats})[0] == 200


# ---------------------------------------------------------------------------------------------- ?cat= ostile ----
def test_cat_lungo_controlli_nfd_nfkc(client, qdb):
    p = mkprofile(client, name="Bar", preset="custom", titles=["barista"], categories=[{"label": "caffè", "terms": ["barista"]}])
    addjob(qdb, "aaaaaaaa", "Barista", "bar")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [p["id"]])
    assert get(client, "/api/jobs?group=all&cat=" + "A" * 100) == []
    assert get(client, "/api/jobs?group=all&cat=A%00B") == [] and get(client, "/api/jobs?group=all&cat=A%0AB") == []
    assert len(get(client, "/api/jobs?group=all&cat=" + unicodedata.normalize("NFD", "CAFFÈ"))) == 1
    assert len(get(client, "/api/jobs?group=all&cat=" + "caff%C3%A8")) == 1
    for q in ("%EF%BC%A3%EF%BC%A1%EF%BC%A6%EF%BC%A6%EF%BC%A5", "%E2%80%AE", "%ED%A0%80", "%FF%FE"):
        assert client.get("/api/jobs?group=all&cat=" + q, headers=H).status_code < 500


def test_report_e_stats_con_cat_ostile_senza_scrivere_file(client, qdb, home):
    p = mkprofile(client, name="Bar", preset="custom", titles=["barista"], categories=[{"label": "caffè", "terms": ["barista"]}])
    addjob(qdb, "aaaaaaaa", "Barista", "bar")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [p["id"]])
    for cat in ("x" * 200, "A\x00B", "../../etc/passwd", "'; DROP TABLE jobs;--", "<img onerror=1>", "%", "A\nB"):
        r = client.post("/api/report", json={"cat": cat, "min": 0}, headers=H)
        assert r.status_code in (400, 404), (cat, r.status_code, r.data[:100])
    assert not list(home.rglob("*.md")), "nessun report scritto"
    assert qdb.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_B82_chip_da_titolo_nfd_filtra(client, qdb):
    title = unicodedata.normalize("NFD", "caffè")
    p = mkprofile(client, name="Bar", preset="custom", titles=[title])
    addjob(qdb, "aaaaaaaa", "Addetto caffè", "caffè")
    from jobshunter.rescore import rescore

    rescore(qdb, settings.load_config(), [p["id"]])
    cat = get(client, "/api/jobs?group=all")[0]["category"]
    from urllib.parse import quote

    assert len(get(client, "/api/jobs?group=all&cat=" + quote(cat))) == 1


# ---------------------------------------------------------------------------------------------- refresh_best ----
def test_refresh_best_che_solleva_lascia_profilo_e_annunci_com_erano(client, qdb, monkeypatch):
    from jobshunter.db import DB

    p = mkprofile(client, name="Cucina", preset="custom", titles=["cuoco", "pasticcere"])
    for i in range(12):
        addjob(qdb, f"{i:08d}", ("Cuoco " if i % 2 else "Pasticcere ") + str(i), "cucina dolci")
    base = profile_body(name="Cucina", preset="custom", titles=["cuoco", "pasticcere"])
    assert post(client, p["id"], {**base, "categories": [{"label": "OLD", "terms": ["cuoco", "pasticcere"]}]}).status_code == 200
    before = sorted(tuple(r) for r in qdb.conn.execute("SELECT uid, score, category FROM jobs"))
    real = DB.refresh_best
    n = {"c": 0}

    def boom(self, *a, **k):
        n["c"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(DB, "refresh_best", boom)
    r = post(client, p["id"], {**base, "categories": [{"label": "NEW", "terms": ["cuoco", "pasticcere"]}]})
    assert r.status_code >= 500 and n["c"] >= 1
    import gc
    import sqlite3

    gc.collect()
    c = sqlite3.connect(str(settings.resolve_path(settings.load_config()["general"]["db_path"])), timeout=1)
    saved = {x["label"] for x in json.loads(c.execute("SELECT data FROM profiles WHERE id=?", (p["id"],)).fetchone()[0])["categories"]}
    cats = {x[0] for x in c.execute("SELECT DISTINCT category FROM job_profiles WHERE profile_id=?", (p["id"],))}
    assert saved == cats == {"OLD"}, (saved, cats)
    assert sorted(tuple(x) for x in c.execute("SELECT uid, score, category FROM jobs")) == before
    c.execute("BEGIN IMMEDIATE")  # il database non e' bloccato
    c.rollback()
    c.close()
    monkeypatch.setattr(DB, "refresh_best", real)
    assert post(client, p["id"], {**base, "categories": [{"label": "NEW", "terms": ["cuoco", "pasticcere"]}]}).status_code == 200


# ---------------------------------------------------------------------------------------------- deadlock, server vero ----
_SERVER_OK = r"""
import sys
sys.path.insert(0, sys.argv[1])
from jobshunter import settings
from jobshunter.gui.app import create_app
settings.load_config(create_if_missing=True)
port = int(sys.argv[2])
create_app(None, port).run("127.0.0.1", port, threaded=True)
"""


def test_server_vero_richieste_parallele_guida_modifica_eliminazione_creazione(home, tmp_path):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, HOME=str(tmp_path), JOBSHUNTER_HOME=str(tmp_path / "srv"))
    script = tmp_path / "srv.py"
    script.write_text(_SERVER_OK)
    proc = subprocess.Popen([sys.executable, str(script), str(ROOT), str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(tmp_path))

    def req(path, body=None, timeout=40):
        r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
        try:
            x = urllib.request.urlopen(r, timeout=timeout)
            return x.status, json.loads(x.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, None
        except OSError:
            return "timeout", None

    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/profiles", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        st, d = req("/api/profiles", {"name": "Base", "preset": "custom", "titles": ["cuoco", "pasticcere"]})
        assert st == 200
        base_id = d["profile"]["id"]
        st, d = req("/api/profiles", {"name": "Da togliere", "preset": "custom", "titles": ["cuoco"]})
        victim = d["profile"]["id"]
        import sqlite3

        c = sqlite3.connect(str(next((tmp_path / "srv").glob("*.db"))))
        for i in range(400):
            c.execute("INSERT INTO jobs (uid, source, title, company, location, url, description, full_text, score, category, matched, status, first_seen, country, avail, avail_checked) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"{i:08d}", "fake", ("Cuoco " if i % 2 else "Pasticcere ") + str(i), "Acme%d" % i, "Roma", "https://example.org/%d" % i,
                                                                  "cucina dolci " * 10, "", 0, "", "", "new", "2026-01-01T00:00:00+00:00", "it", "open", "2099-01-01T00:00:00+00:00"))
        c.commit()
        c.close()
        results = []
        pl = {"country": "it", "home": "", "radius_km": 100}

        def run(kind, k):
            if kind == "guida":
                results.append((kind, req("/api/onboarding/complete", {**pl, "profile": {"preset": "custom", "titles": ["cuoco", "pasticcere"], "categories": "cuoco, pasticcere"}})[0]))
            elif kind == "edit":
                results.append((kind, req(f"/api/profiles/{base_id}", {"name": "Base", "preset": "custom", "titles": ["cuoco", "pasticcere"], "categories": [{"label": f"E{k}", "terms": ["cuoco"]}]})[0]))
            elif kind == "edit_victim":
                results.append((kind, req(f"/api/profiles/{victim}", {"name": "Da togliere", "preset": "custom", "titles": ["cuoco"], "categories": [{"label": f"V{k}", "terms": ["cuoco"]}]})[0]))
            elif kind == "del":
                results.append((kind, req(f"/api/profiles/{victim}/delete", {})[0]))
            elif kind == "new":
                results.append((kind, req("/api/profiles", {"name": f"Nuovo {k}", "preset": "custom", "titles": ["cuoco"], "categories": [{"label": f"N{k}", "terms": ["cuoco"]}]})[0]))
            elif kind == "jobs":
                results.append((kind, req("/api/jobs?group=all")[0]))

        plan = [("guida", 0), ("guida", 1), ("edit", 0), ("edit", 1), ("edit", 2), ("edit_victim", 0), ("del", 0), ("new", 0), ("new", 1), ("jobs", 0), ("jobs", 1), ("edit_victim", 1)]
        ts = [threading.Thread(target=run, args=a) for a in plan]
        t0 = time.time()
        [t.start() for t in ts]
        for t in ts:
            t.join(timeout=120)
        assert not any(t.is_alive() for t in ts), "deadlock"
        assert time.time() - t0 < 90
        bad = [(k, r) for k, r in results if r not in (200, 400, 404, 409)]
        assert not bad, bad
        st, lst = req("/api/profiles")
        assert st == 200
        c = sqlite3.connect(str(next((tmp_path / "srv").glob("*.db"))))
        assert c.execute("SELECT COUNT(*) FROM job_profiles WHERE profile_id NOT IN (SELECT id FROM profiles)").fetchone()[0] == 0
        c.close()
        assert req("/api/jobs?group=all", timeout=10)[0] == 200  # il server risponde ancora
    finally:
        proc.kill()
        proc.wait(timeout=10)
