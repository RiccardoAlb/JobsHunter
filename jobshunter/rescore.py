"""Rivaluta gli annunci GIA' salvati per uno o piu' profili (dopo aver creato o modificato un profilo).

Usa il testo salvato (descrizione fino a 5.000 caratteri): non fa nessuna richiesta di rete."""
from __future__ import annotations

import copy

from .db import DB
from .geo import distance_km
from .models import Job
from .profiles import Profile, ProfileStore, build_rules
from .scoring import fold, location_ok, score_job


def _job_from_row(r) -> Job:
    from .sources.base import parse_dt

    return Job(source=r["source"], title=r["title"], company=r["company"], location=r["location"] or "", url=r["url"] or "",
               description=r["description"] or "", posted_at=parse_dt(r["posted_at"]), remote=bool(r["remote"]),
               salary=r["salary"] or "", near_home=False, country=r["country"] or "")


def rescore(db: DB, cfg: dict, profile_ids: list[int] | None = None) -> int:
    """Ricalcola `job_profiles` per i profili indicati (None = tutti). Ritorna quanti annunci risultano pertinenti."""
    store = ProfileStore(db)
    profiles: list[Profile] = [p for p in (store.get(i) for i in profile_ids) if p] if profile_ids is not None else store.list()
    if not profiles:
        return 0
    try:
        min_score = cfg["general"]["min_score"]
        hits = 0
        rows = db.conn.execute("SELECT uid, source, title, company, location, url, description, posted_at, remote, salary, country, "
                               "lat, lon, geo FROM jobs").fetchall()
        for p in profiles:
            rules = build_rules(p, cfg)
            center = None
            if p.city:
                from .geo import lookup

                hit = lookup(p.city, p.countries[0] if p.countries else None)
                center = (hit["lat"], hit["lon"]) if hit else None
            db.conn.execute("DELETE FROM job_profiles WHERE profile_id=?", (p.id,))
            for r in rows:
                job = _job_from_row(r)
                if center and r["geo"] == 1 and r["lat"] is not None and distance_km(*center, r["lat"], r["lon"]) <= p.radius_km:
                    job.near_where = {fold(p.city)}
                if not location_ok(job, cfg, p):
                    continue
                sc = score_job(copy.copy(job), cfg, p, rules)
                if sc and sc.score >= min_score:
                    db.set_job_profile(r["uid"], p.id, sc.score, sc.category, sc.matched)
                    hits += 1
        db.refresh_best(commit=False)  # nella stessa transazione: o cambia tutto (job_profiles e punteggi migliori) o niente
        db.conn.commit()
    except BaseException:
        db.conn.rollback()  # niente transazione rimasta aperta: altrimenti il database resta bloccato per tutti
        raise
    return hits
