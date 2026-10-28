"""Logica di scan condivisa da CLI e GUI, con stop manuale e tetto massimo di durata."""
from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from . import availability, net
from .db import DB
from .dedupe import find_duplicates
from .profiles import ProfileStore, build_rules, merge_queries
from .scoring import location_ok, score_job
from .sources import REGISTRY
from .sources.base import Cancelled

Event = Callable[[str, dict], None]


@dataclass
class ScanResult:
    read: int = 0
    kept: int = 0
    new: int = 0
    dups_new: int = 0
    closed_found: int = 0
    check_blocked: bool = False
    cancelled: bool = False
    reason: str = ""
    errors: list[tuple[str, str]] = field(default_factory=list)


def source_wanted(name: str, profiles: list) -> bool:
    """Alcune fonti hanno senso solo per certi profili: Arbeitnow per la Germania, RemoteOK/Remotive per il remoto."""
    if name == "arbeitnow":
        return any("de" in p.countries for p in profiles)
    if name in ("remoteok", "remotive"):
        return any(p.remote for p in profiles)
    if name in ("greenhouse", "lever"):  # pagine carriere di aziende di cybersecurity: solo per chi cerca in quell'ambito
        return any(p.preset == "cybersecurity" for p in profiles)
    return True


def run_scan(cfg: dict, db: DB, *, cancel: threading.Event | None = None,
             on_event: Event | None = None, profile_ids: list[int] | None = None) -> ScanResult:
    """Esegue lo scan di tutte le fonti attive per i profili indicati (`None` = tutti i profili attivi).

    Ogni annuncio letto e' valutato per OGNI profilo interessato e salvato una sola volta; per ciascun profilo
    si registra il suo punteggio (`job_profiles`). Eventi emessi: queued(name), start(name), done(name, read, kept,
    new), error(name, msg), cancelled(reason). Si ferma allo stop o allo scadere di general.max_scan_seconds."""
    cancel = cancel or threading.Event()
    emit = on_event or (lambda kind, data: None)
    max_s = cfg["general"].get("max_scan_seconds", 300)
    deadline = time.monotonic() + max_s
    res = ScanResult()

    store = ProfileStore(db)
    if store.count() == 0:  # DB senza profili: si crea quello predefinito (cybersecurity dal config)
        db._migrate_profiles(cfg)
    if profile_ids is None:
        profiles = store.active()
    else:
        profiles = [p for p in (store.get(i) for i in profile_ids) if p is not None]
    rules = {p.id: build_rules(p, cfg) for p in profiles}
    queries = merge_queries(profiles, cfg)
    min_score = cfg["general"]["min_score"]

    active = [(n, cls) for n, cls in REGISTRY.items()
              if cfg["sources"].get(n, {}).get("enabled") and source_wanted(n, profiles)]
    for name, _ in active:
        emit("queued", {"name": name})

    for name, cls in active:
        if cancel.is_set() or time.monotonic() > deadline:
            res.cancelled = True
            res.reason = "fermato dall'utente" if cancel.is_set() else f"tempo massimo ({max_s}s)"
            break
        emit("start", {"name": name})
        scfg = dict(cfg["sources"][name])
        scfg["_internships"] = any(p.internships for p in profiles)
        src = cls(scfg)
        src.cancel, src.deadline = cancel, deadline
        try:
            jobs = src.fetch_queries(queries)
        except Cancelled as e:
            res.cancelled, res.reason = True, str(e)
            break
        except Exception as e:  # una fonte rotta non deve fermare le altre
            res.errors.append((name, net.redact(e)[:100]))
            emit("error", {"name": name, "msg": net.redact(e)[:100]})
            continue
        kept, new, touched = 0, 0, []
        for job in jobs:
            best, per_profile = None, []
            for p in profiles:
                if not location_ok(job, cfg, p):
                    continue
                scored = score_job(copy.copy(job), cfg, p, rules[p.id])
                if scored and scored.score >= min_score:
                    per_profile.append((p.id, scored))
                    if best is None or scored.score > best.score:
                        best = scored
            if best is None:
                continue
            kept += 1
            new += db.upsert(best)
            for pid, sc in per_profile:
                db.set_job_profile(best.uid, pid, sc.score, sc.category, sc.matched)
            touched.append(best.uid)
        db.drop_orphans()  # un profilo eliminato durante la scansione non deve lasciare righe
        db.refresh_best(touched)
        db.commit()
        res.read += len(jobs)
        res.kept += kept
        res.new += new
        emit("done", {"name": name, "read": len(jobs), "kept": kept, "new": new})

    db.backfill_geo()
    db.backfill_meta()
    res.dups_new = find_duplicates(db, cfg)
    if res.dups_new:
        emit("dups", {"new": res.dups_new})
    # verifica a campione dei migliori annunci: cosi' quelli chiusi si scoprono prima di leggerli
    n_auto = int(cfg.get("availability", {}).get("auto_check_after_scan", 20))
    if n_auto > 0 and not cancel.is_set():
        emit("checking", {"n": n_auto})
        chk = availability.run_check(db, cfg, limit=n_auto, cancel=cancel)
        res.closed_found, res.check_blocked = chk["closed"], chk["blocked"]
        emit("checked", chk)
    if res.cancelled:
        emit("cancelled", {"reason": res.reason})
    return res
