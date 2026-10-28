"""Copia fedele del codice di FASE 1 (scoring e somiglianza dei duplicati), tenuta come riferimento dal TESTER.

Serve a: (1) generare i punteggi d'oro; (2) misurare la qualita' dei duplicati "di partenza" anche dopo che BUILDER
ha cambiato dedupe.py. NON importa nulla da jobshunter tranne il modello Job. Non modificare.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

DEFAULT_BONUS = {"stage": 10, "tirocinio": 10, "tirocinante": 8, "internship": 8, "apprendistato": 6}
_SUFFIX = r"(?:er|ers|ing|s)?"


def _has(term: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}{_SUFFIX}(?![a-z0-9])", text) is not None


def score_job(job, cfg):
    title = job.title.lower()
    body = job.description.lower()
    if any(_has(b, title) for b in cfg["penalties"]["blacklist"]):
        return None
    if job.posted_at:
        age = datetime.now(timezone.utc) - job.posted_at
        if age > timedelta(days=cfg["general"]["max_age_days"]):
            return None
    totals, matched = {}, []
    for cat in cfg["keywords"].values():
        sub = 0
        for term, weight in cat["terms"].items():
            if _has(term, title):
                sub += weight * 3
                matched.append(term)
            elif _has(term, body):
                sub += weight
                matched.append(term)
        totals[cat["label"]] = sub
    score = sum(totals.values())
    if score == 0:
        return None
    for term, delta in cfg["penalties"]["title_terms"].items():
        if _has(term, title):
            score += delta
    for term, delta in {**DEFAULT_BONUS, **cfg["bonus"]["title_terms"]}.items():
        if _has(term, title):
            score += delta
    loc_cfg = cfg.get("location", {})
    place = job.location.lower()
    if job.near_home or any(_has(h.lower(), place) for h in loc_cfg.get("home_names", ["palermo", "sicilia"])):
        job.near_home = True
        if score >= loc_cfg.get("home_min_score", 20):
            score += loc_cfg.get("home_bonus", 20)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    category = ranked[0][0]
    if totals.get("RED", 0) >= 12 and totals.get("BLUE", 0) >= 12:
        category = "PURPLE"
    job.score = max(score, 0)
    job.category = category
    job.matched = sorted(set(matched))
    return job


# ---------------------------------------------------------------- duplicati (fase 1) ----
COMPANY_NOISE = {"spa", "srl", "srls", "sas", "snc", "s", "p", "a", "r", "l", "italia", "italy", "group",
                 "gruppo", "inc", "gmbh", "ltd", "llc", "the", "holding", "company", "co", "ag", "sa"}
GENERIC_CITIES = {"", "italia", "italy", "remote", "remoto", "emea", "europe"}
GENDER = re.compile(r"\(?\b[mfdwx]\s*/\s*[mfdwx](\s*/\s*[mfdwx])?\b\)?")
LEVELS = re.compile(r"\b(junior|jr|senior|sr|lead|principal|staff|trainee|intern|internship|graduate|entry|"
                    r"expert|specialist|associate|manager|head|l[1-4]|tier ?[1-4])\b")
LEVEL_ALIAS = {"jr": "junior", "sr": "senior", "internship": "intern"}


def _alnum(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("&", " ")).split())


def norm_company(s: str) -> str:
    words = [w for w in _alnum(s).split() if w not in COMPANY_NOISE]
    return " ".join(words) or _alnum(s)


def norm_title(s: str) -> str:
    return _alnum(GENDER.sub(" ", s.lower()))


def norm_city(s: str) -> str:
    return re.sub(r"^provincia di ", "", (s or "").lower().split(",")[0].strip())


def levels(title_norm: str) -> set[str]:
    out = set()
    for m in LEVELS.findall(title_norm):
        m = m.replace(" ", "")
        out.add(LEVEL_ALIAS.get(m, m))
    return out


def _ratio(a: str, b: str) -> float:
    sm = SequenceMatcher(None, a, b)
    if sm.real_quick_ratio() < 0.6 or sm.quick_ratio() < 0.6:
        return 0.0
    return sm.ratio()


def similarity(a, b):
    ca, cb = norm_company(a["company"]), norm_company(b["company"])
    cs = 1.0 if ca == cb else _ratio(ca, cb)
    if cs < 0.8:
        return None
    ya, yb = norm_city(a["location"]), norm_city(b["location"])
    penalty = 0
    if ya != yb:
        if ya in GENERIC_CITIES or yb in GENERIC_CITIES:
            penalty += 10
        else:
            return None
    ta, tb = norm_title(a["title"]), norm_title(b["title"])
    ts = 1.0 if ta == tb else _ratio(ta, tb)
    if ts < 0.6:
        return None
    pct = ts * cs * 100 - penalty
    if levels(ta) != levels(tb):
        pct -= 25
    return round(max(pct, 0))
