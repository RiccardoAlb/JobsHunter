"""Valutazione dei duplicati sul set etichettato tests/data/dedupe_cases.json (uso comune a test e a misure manuali)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "dedupe_cases.json"
HOLDOUT = DATA.with_name("dedupe_holdout.json")
DB_COLS = ("source", "title", "company", "location", "url", "description", "posted_at", "remote",
           "score", "status", "salary", "full_text")


def load_cases(holdout: bool = False, blind: bool = False, blind2: bool = False, blind3: bool = False) -> list[dict]:
    f = DATA.with_name("dedupe_blind3.json") if blind3 else DATA.with_name("dedupe_blind2.json") if blind2 else DATA.with_name("dedupe_blind.json") if blind else (HOLDOUT if holdout else DATA)
    return json.loads(f.read_text(encoding="utf-8"))


def as_row(d: dict) -> sqlite3.Row:
    """Una riga tipo sqlite3.Row (accesso per nome), cosi' similarity la tratta come una riga di DB."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    cols = list(d)
    con.execute(f"CREATE TABLE t ({','.join(cols)})")
    con.execute(f"INSERT INTO t VALUES ({','.join('?' * len(cols))})", [d[c] for c in cols])
    return con.execute("SELECT * FROM t").fetchone()


def metrics(cases: list[dict], predicted: dict[str, bool]) -> dict:
    tp = sum(1 for c in cases if c["label"] == "dup" and predicted[c["id"]])
    fn = [c for c in cases if c["label"] == "dup" and not predicted[c["id"]]]
    fp = [c for c in cases if c["label"] == "nodup" and predicted[c["id"]]]
    prec = tp / (tp + len(fp)) if tp + len(fp) else 1.0
    rec = tp / (tp + len(fn)) if tp + len(fn) else 1.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec}


def phase1():
    """La copia fedele della somiglianza di fase 1 (tests/data/phase1_reference.py)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("phase1_reference", DATA.parent / "phase1_reference.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def predict_similarity(cases, min_percent=75, impl=None) -> dict[str, bool]:
    if impl is None:
        from jobshunter import dedupe as impl

    out = {}
    for c in cases:
        pct = impl.similarity(as_row(c["a"]), as_row(c["b"]))
        c["_pct"] = pct
        out[c["id"]] = pct is not None and pct >= min_percent
    return out


def insert_case(db, c: dict) -> tuple[str, str]:
    ua, ub = f"{c['id']}a".ljust(16, "0"), f"{c['id']}b".ljust(16, "0")
    for uid, side in ((ua, "a"), (ub, "b")):
        r = c[side]
        db.conn.execute(
            f"INSERT INTO jobs (uid,{','.join(DB_COLS)},first_seen) VALUES (?,{','.join('?' * len(DB_COLS))},?)",
            [uid, *[r[k] for k in DB_COLS], "2026-01-01T00:00:00+00:00"])
    db.conn.commit()
    return ua, ub


def predict_find_duplicates(cases, cfg, tmp_dir: Path) -> dict[str, bool]:
    """Un DB temporaneo per caso (cosi' i casi non si influenzano); True se find_duplicates propone la coppia."""
    from jobshunter import dedupe
    from jobshunter.db import DB

    out = {}
    for c in cases:
        db = DB(tmp_dir / f"{c['id']}.db")
        ua, ub = insert_case(db, c)
        db.backfill_meta()  # company_key & co., come dopo una vera scansione
        dedupe.find_duplicates(db, cfg)
        hit = db.conn.execute("SELECT 1 FROM dup_pairs WHERE (uid_a=? AND uid_b=?) OR (uid_a=? AND uid_b=?)",
                              (ua, ub, ub, ua)).fetchone()
        out[c["id"]] = hit is not None
        db.conn.close()
    return out
