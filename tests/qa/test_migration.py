"""SPEC 2.4 e criterio 2: un DB creato con lo schema di FASE 1 si apre, crea il profilo Cybersecurity e non perde nulla."""
import json
import re
import sqlite3
from pathlib import Path

import pytest

from qa.qa_helpers import all_profiles, by_name, call, edit_config

pytestmark = pytest.mark.phase2
DATA = Path(__file__).resolve().parent.parent / "data"

LEGACY_SCHEMA = """
CREATE TABLE jobs (uid TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT, url TEXT, description TEXT,
  posted_at TEXT, remote INTEGER, score INTEGER, category TEXT, matched TEXT, status TEXT DEFAULT 'new', notified INTEGER DEFAULT 0,
  first_seen TEXT, salary TEXT DEFAULT '', near_home INTEGER DEFAULT 0, full_text TEXT DEFAULT '', lat REAL, lon REAL,
  geo INTEGER DEFAULT 0, city TEXT DEFAULT '', work_mode TEXT DEFAULT 'unknown', sal_min INTEGER, sal_max INTEGER,
  meta INTEGER DEFAULT 0, company_key TEXT DEFAULT '', contract TEXT DEFAULT 'unknown', avail TEXT DEFAULT 'unknown',
  avail_checked TEXT, valid_until TEXT, avail_note TEXT DEFAULT '');
CREATE INDEX idx_score ON jobs(score DESC);
CREATE TABLE dup_pairs (id INTEGER PRIMARY KEY AUTOINCREMENT, uid_a TEXT NOT NULL, uid_b TEXT NOT NULL, pct INTEGER, keep_uid TEXT,
  hidden_uid TEXT, status TEXT DEFAULT 'pending', auto INTEGER DEFAULT 0, created TEXT, decided_at TEXT, UNIQUE(uid_a, uid_b));
CREATE TABLE applications (id INTEGER PRIMARY KEY AUTOINCREMENT, job_uid TEXT, company TEXT NOT NULL, role TEXT NOT NULL,
  location TEXT DEFAULT '', url TEXT DEFAULT '', applied_at TEXT, stage TEXT DEFAULT 'sent', outcome TEXT DEFAULT 'active',
  contact TEXT DEFAULT '', notes TEXT DEFAULT '', follow_up TEXT, created TEXT, updated TEXT);
CREATE TABLE app_events (id INTEGER PRIMARY KEY AUTOINCREMENT, app_id INTEGER NOT NULL, kind TEXT, value TEXT, at TEXT, note TEXT DEFAULT '');
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE scan_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT, finished TEXT, kind TEXT, read INTEGER DEFAULT 0,
  kept INTEGER DEFAULT 0, new INTEGER DEFAULT 0, closed INTEGER DEFAULT 0, dups INTEGER DEFAULT 0, cancelled INTEGER DEFAULT 0,
  blocked INTEGER DEFAULT 0, errors TEXT DEFAULT '', notified INTEGER DEFAULT 0);
"""


def make_legacy_db(path: Path) -> dict:
    """DB di fase 1 con gli annunci d'oro (punteggi calcolati dal codice di fase 1), candidature, duplicati decisi e impostazioni."""
    from jobshunter.models import Job

    gold = [g for g in json.loads((DATA / "score_golden.json").read_text(encoding="utf-8")) if g["expected"] and g["expected"]["score"] >= 15]
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    uids, rows = [], {}
    statuses = ["new", "seen", "applied", "discarded", "new"]
    for i, g in enumerate(gold):
        j = Job(source="adzuna", title=g["title"], company=g["company"], location=g["location"], url=f"https://example.org/{i}")
        e = g["expected"]
        con.execute("INSERT INTO jobs (uid,source,title,company,location,url,description,remote,score,category,matched,status,first_seen,near_home) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (j.uid, "adzuna", g["title"], g["company"], g["location"], j.url, g["description"], int(g["remote"]),
                     e["score"], e["category"], ",".join(e["matched"]), statuses[i % 5], "2026-05-01T10:00:00+00:00", int(e["near_home"])))
        uids.append(j.uid)
        rows[j.uid] = (e["score"], e["category"], ",".join(e["matched"]), statuses[i % 5])
    con.execute("INSERT INTO dup_pairs (uid_a,uid_b,pct,keep_uid,hidden_uid,status,created) VALUES (?,?,?,?,?,?,?)",
                (uids[0], uids[1], 88, uids[0], uids[1], "confirmed", "2026-05-02"))
    con.execute("INSERT INTO dup_pairs (uid_a,uid_b,pct,keep_uid,hidden_uid,status,created) VALUES (?,?,?,?,?,?,?)",
                (uids[2], uids[3], 80, uids[2], uids[3], "rejected", "2026-05-02"))
    con.execute("INSERT INTO applications (job_uid,company,role,applied_at,stage,outcome,notes,created,updated) VALUES (?,?,?,?,?,?,?,?,?)",
                (uids[0], "Acme", "SOC Analyst", "2026-05-03", "hr", "active", "nota importante", "2026-05-03", "2026-05-04"))
    con.execute("INSERT INTO app_events (app_id,kind,value,at) VALUES (1,'created','sent','2026-05-03')")
    con.execute("INSERT INTO kv VALUES ('news_seen','2026-05-01T00:00:00+00:00')")
    con.execute("INSERT INTO scan_runs (started,finished,kind,read,kept,new) VALUES ('2026-05-01','2026-05-01','auto',100,40,12)")
    con.commit()
    con.close()
    return {"uids": uids, "rows": rows}


@pytest.fixture
def legacy(qcfg, home):
    from jobshunter import settings

    path = settings.resolve_path(qcfg["general"]["db_path"])
    if path.exists():
        path.unlink()
    return {"path": path, **make_legacy_db(path)}


def snapshot(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    out = {t: [tuple(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY 1")] for t in ("applications", "app_events", "kv", "scan_runs")}
    out["dups"] = [tuple(r) for r in con.execute("SELECT uid_a,uid_b,pct,keep_uid,hidden_uid,status FROM dup_pairs ORDER BY id")]
    out["jobs"] = {r["uid"]: (r["score"], r["category"], r["matched"], r["status"], r["title"], r["company"]) for r in con.execute("SELECT * FROM jobs")}
    con.close()
    return out


def test_nessun_dato_perso(legacy):
    from jobshunter.db import DB

    before = snapshot(legacy["path"])
    DB(legacy["path"]).conn.close()
    after = snapshot(legacy["path"])
    assert set(after["jobs"]) == set(before["jobs"]) and len(before["jobs"]) >= 20
    for uid, v in before["jobs"].items():
        assert after["jobs"][uid] == v, f"annuncio {uid} modificato dalla migrazione"
    for t in ("applications", "app_events", "kv", "scan_runs", "dups"):
        assert after[t] == before[t], f"tabella {t} cambiata"


def test_profilo_cybersecurity_creato_da_config(legacy, client):
    ps = all_profiles(client)
    assert [p["name"] for p in ps] == ["Cybersecurity"]
    p = ps[0]
    assert p["preset"] == "cybersecurity" and p["active"] is True and p["countries"] == ["it"]
    assert p["location"]["city"] == "Palermo" and p["location"]["radius_km"] == 150
    assert p["internships"] is True
    visibili = len(legacy["uids"]) - sum(1 for r in legacy["rows"].values() if r[3] == "discarded")
    assert visibili - 1 <= p["job_count"] <= len(legacy["uids"])  # (-1: un duplicato confermato nascosto)


def test_stessi_punteggi_per_il_profilo_di_default(legacy, client):
    from jobshunter.db import DB

    all_profiles(client)
    db = DB(legacy["path"])
    pid = by_name(client, "Cybersecurity")["id"]
    jp = {r["job_uid"]: r for r in db.conn.execute("SELECT * FROM job_profiles WHERE profile_id=?", (pid,))}
    assert set(jp) == set(legacy["uids"]), "ogni annuncio esistente va associato al profilo Cybersecurity"
    for uid, (score, cat, matched, _) in legacy["rows"].items():
        r = jp[uid]
        assert (r["score"], r["category"], r["matched"]) == (score, cat, matched), f"{uid}: punteggio cambiato (tolleranza zero)"
        j = db.conn.execute("SELECT score, category, matched FROM jobs WHERE uid=?", (uid,)).fetchone()
        assert (j["score"], j["category"], j["matched"]) == (score, cat, matched)


def test_idempotente(legacy, client):
    from jobshunter.db import DB

    all_profiles(client)
    for _ in range(3):
        DB(legacy["path"]).conn.close()
    db = DB(legacy["path"])
    assert db.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM job_profiles").fetchone()[0] == len(legacy["uids"])
    assert len(all_profiles(client)) == 1


def test_non_ricrea_un_profilo_gia_eliminato_o_rinominato(legacy, client):
    """Se l'utente ha gia' dei profili (anche rinominati) la migrazione non ne aggiunge altri."""
    p = all_profiles(client)[0]
    st, d = call(client, "post", f"/api/profiles/{p['id']}", {**p, "name": "Il mio lavoro"})
    assert st == 200
    from jobshunter.db import DB

    DB(legacy["path"]).conn.close()
    assert [x["name"] for x in all_profiles(client)] == ["Il mio lavoro"]


def test_elenco_annunci_invariato_dopo_la_migrazione(legacy, client):
    st, rows = call(client, "get", "/api/jobs?limit=500")
    got = {r["uid"] for r in rows}
    expect = {u for u, v in legacy["rows"].items() if v[3] != "discarded"}
    # i duplicati confermati (uids[0] tiene, uids[1] nascosto) restano nascosti come prima
    expect.discard(legacy["uids"][1])
    assert got == expect
    st, rows2 = call(client, "get", "/api/jobs?limit=500&profile=all")
    assert {r["uid"] for r in rows2} == got
    scores = {r["uid"]: r["score"] for r in rows}
    for uid in got:
        assert scores[uid] == legacy["rows"][uid][0]


def test_config_personalizzata_finisce_nel_profilo(qcfg, home):
    """keyword personalizzate di config.toml, citta' e raggio, stage spenti: tutto ripreso nel profilo migrato."""
    from jobshunter import settings
    from jobshunter.gui.app import create_app

    def f(t):
        t = t.replace('terms = { "soc analyst" = 12,', 'terms = { "zzparola-mia" = 9, "soc analyst" = 12,')
        t = re.sub(r"internships = true", "internships = false", t)
        t = t.replace('home = "Palermo"          # centro del raggio di ricerca\nradius_km = 150', 'home = "Catania"\nradius_km = 80')
        return t

    edit_config(home, f)
    path = settings.resolve_path(settings.load_config()["general"]["db_path"])
    make_legacy_db(path)
    cl = create_app(None, 8765).test_client()
    p = all_profiles(cl)[0]
    assert p["internships"] is False
    assert p["location"]["city"] == "Catania" and p["location"]["radius_km"] == 80
    body = {k: v for k, v in p.items() if k not in ("id", "created", "updated", "job_count")}
    st, d = call(cl, "post", "/api/profiles/preview", body)
    kw = {k["term"]: k["weight"] for k in d["keywords"]}
    assert kw.get("zzparola-mia") == 9, "la keyword personalizzata del config deve valere ancora nel profilo"
    assert kw.get("soc analyst") == 12


def test_db_nuovo_vuoto(client):
    ps = all_profiles(client)
    assert len(ps) == 1 and ps[0]["job_count"] == 0


def test_db_senza_annunci_ma_con_candidature(qcfg, home):
    from jobshunter import settings
    from jobshunter.db import DB

    path = settings.resolve_path(qcfg["general"]["db_path"])
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    con.execute("INSERT INTO applications (company, role, applied_at) VALUES ('X','Y','2026-01-01')")
    con.commit()
    con.close()
    db = DB(path)
    assert db.conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 1
