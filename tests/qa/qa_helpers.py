"""Funzioni di appoggio per i test del TESTER (nessuna fixture qui: stanno in conftest.py)."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

from jobshunter.models import Job
from jobshunter.sources.base import Source

H = {"Host": "127.0.0.1:8765"}


def edit_config(home: Path, fn) -> None:
    p = home / "config.toml"
    p.write_text(fn(p.read_text()))


def jget(r):
    return json.loads(r.data)


def call(client, method, url, body=None, raw=None, headers=None, ctype="application/json"):
    """Chiama l'API e ritorna (status, json|None). Verifica SEMPRE che non ci sia un errore 500."""
    h = dict(H, **(headers or {}))
    kw = {"headers": h}
    if raw is not None:
        kw.update(data=raw, content_type=ctype)
    elif body is not None:
        kw["json"] = body
    r = getattr(client, method)(url, **kw)
    assert r.status_code < 500, f"{method.upper()} {url} -> {r.status_code}: {r.data[:300]!r} (input: {body if raw is None else raw[:80]!r})"
    try:
        data = json.loads(r.data)
    except ValueError:
        data = None
    return r.status_code, data


def profile_body(name="Profilo di prova", preset="software_dev", **over) -> dict:
    b = {"name": name, "preset": preset, "active": True, "titles": [], "include": {}, "exclude": [], "seniority": "any",
         "contracts": [], "countries": ["it"], "location": {"city": "", "radius_km": 100}, "remote": True, "internships": True}
    b.update(over)
    return b


def body_with(base_name: str, override: dict) -> dict:
    """profile_body con nome di base, poi sovrascritto da `override` (che puo' contenere anche 'name' o 'preset')."""
    return {**profile_body(name=base_name), **override}


def mkprofile(client, **kw) -> dict:
    st, d = call(client, "post", "/api/profiles", profile_body(**kw))
    assert st == 200 and d and d.get("ok"), f"creazione profilo fallita: {st} {d}"
    return d["profile"]


def all_profiles(client) -> list[dict]:
    st, d = call(client, "get", "/api/profiles")
    assert st == 200 and isinstance(d, list)
    return d


def by_name(client, name) -> dict:
    return next(p for p in all_profiles(client) if p["name"] == name)


def job(title, company="Azienda Prova", location="Roma", desc="", n=None, remote=False, salary="") -> Job:
    n = n if n is not None else abs(hash((title, company, location))) % 10**8
    return Job(source="fake", title=title, company=company, location=location, url=f"https://example.org/job/{n}",
              description=desc, remote=remote, salary=salary)


def job_profiles(db_path_or_conn) -> list[sqlite3.Row]:
    conn = db_path_or_conn
    if not hasattr(conn, "execute"):
        conn = db_path_or_conn.conn
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT job_uid, profile_id, score, category, matched FROM job_profiles").fetchall()


class RecSource(Source):
    """Fonte finta che registra le query ricevute (contratto: Source.fetch_queries(queries))."""

    name = "rec"
    calls: list = []
    jobs: list = []

    def fetch(self):
        self.check()
        return list(RecSource.jobs)

    def fetch_queries(self, queries):
        self.check()
        RecSource.calls.append(list(queries))
        return list(RecSource.jobs)


def qtuple(q):
    """Una Query (dataclass) o un dict -> (q, country, where)."""
    g = (lambda k: q[k]) if isinstance(q, dict) else (lambda k: getattr(q, k))
    return (g("q"), g("country"), g("where"))


def wait_scan(client, timeout=30):
    """Aspetta la fine di una scansione avviata via API."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = json.loads(client.get("/api/status", headers=H).data)
        if not d["running"]:
            return d
        time.sleep(0.05)
    raise AssertionError("la scansione non e' finita entro il tempo")
