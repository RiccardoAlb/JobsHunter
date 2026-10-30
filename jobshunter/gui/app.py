"""GUI locale (Flask) per JobsHunter. Ascolta solo su 127.0.0.1."""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .. import availability, net
from ..db import DB, DUP_HIDDEN, NOT_HIDDEN, PROFILE_ACTIVE, OUTCOMES, STAGES
from ..dedupe import find_duplicates
from .. import geo as geomod
from .. import __version__, settings
from ..report import build_report
from .. import APP_NAME, autoscan, onboarding, scheduler
from .. import profiles as prof
from .. import cv as cvmod, cvfile, cvmatch
from ..rescore import rescore

STATIC = Path(__file__).resolve().parent / "static"
STATUSES = {"new", "seen", "applied", "discarded"}
CATEGORIES = {"RED", "BLUE", "PURPLE", "SYSADM", "SEC"}
MAX_JSON_BYTES = 256 * 1024
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
CATEGORY_OK = re.compile(r"^[^\x00-\x1f\x7f]{1,60}$")  # qualsiasi nome senza caratteri di controllo: il valore va nel SQL solo come parametro  # le categorie dei profili non cyber sono nomi di gruppo (es. BACKEND)


def norm_cat(value) -> str:
    """Nome di categoria dal filtro, normalizzato come le etichette salvate (NFKC e maiuscolo)."""
    import unicodedata

    return unicodedata.normalize("NFKC", str(value or "")).upper()


def to_int(value, default: int = 0, lo: int | None = None, hi: int | None = None) -> int:
    """Numero da input esterno: se non è un numero valido si usa il valore di riserva (mai un errore 500)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def create_app(config_path: str | None = None, port: int = 8765) -> Flask:
    cfg = settings.load_config(config_path, create_if_missing=settings.auto_create(config_path))
    cfg_file = Path(cfg["_config_path"])

    def db_file() -> Path:
        return settings.resolve_path(cfg["general"]["db_path"])

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = cvfile.MAX_BYTES + 1024 * 1024  # il CV puo' pesare 5 MB; tutto il resto e' molto piu' piccolo
    lock = threading.Lock()
    state = {"running": False, "cancel": None, "sources": {}, "order": [], "summary": None,
             "message": "", "started": None, "finished": None}
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    net_block = {"until": 0.0}  # dopo un blocco del sito (403/429) si evita di insistere per qualche minuto

    def open_db() -> DB:
        return DB(db_file())

    @app.before_request
    def guard():
        # difesa da richieste cross-site verso il server locale
        if request.host not in allowed_hosts:
            abort(403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):  # POST, DELETE, PUT, PATCH: tutto cio' che modifica qualcosa
            origin = request.headers.get("Origin")
            if origin and urlparse(origin).netloc not in allowed_hosts:
                abort(403)
            if request.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                abort(403)  # il browser dichiara che la richiesta arriva da un altro sito (anche un'altra porta di localhost)
            if "chunked" in request.headers.get("Transfer-Encoding", "").lower():
                abort(413)  # senza Content-Length il limite non si puo' controllare prima di leggere: il browser non li usa
            if request.path != "/api/cv":
                request.max_content_length = MAX_JSON_BYTES  # solo il CV puo' essere grande; il resto e' JSON piccolo

    @app.errorhandler(RecursionError)
    def too_deep(e):
        return jsonify(error="richiesta non valida"), 400

    @app.errorhandler(HTTPException)
    def json_errors(e):
        """Gli errori delle API sono JSON {error} in italiano; le altre pagine restano com'erano."""
        if request.path.startswith("/api/"):
            msg = {400: "richiesta non valida", 403: "accesso negato", 404: "non trovato", 405: "metodo non consentito",
                   413: "file troppo grande (il limite e' 5 MB)", 422: "dati non validi"}.get(e.code, e.name)
            detail = e.description if isinstance(e.description, str) and e.code in (400, 422) else msg
            return jsonify(error=detail), e.code
        return e

    @app.after_request
    def no_cache(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = CSP
        if request.path.startswith("/assets/") or request.path == "/favicon.ico":
            resp.headers["Cache-Control"] = "public, max-age=3600"
        else:
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(STATIC, "favicon.ico")

    @app.get("/assets/<path:name>")
    def assets(name):
        if not name.lower().endswith((".png", ".ico", ".svg")):
            abort(404)
        return send_from_directory(STATIC, name)

    def geo_arg(src):
        """Legge city/km/unk da query string o JSON. Ritorna (tupla per il filtro, etichetta) oppure (None, '')."""
        city = src.get("city") or ""
        city = city.strip() if isinstance(city, str) else ""
        if not city:
            return None, ""
        hit = geomod.lookup(city)
        if not hit:
            abort(422, description="citta' non trovata")
        km = to_int(src.get("km"), 100, 1, 3000)
        unk = str(src.get("unk", "1")) in ("1", "true", "True")
        return (hit["lat"], hit["lon"], km, unk), f"{city.title()} {km}km"

    MODE_VALUES = ("remote", "hybrid", "onsite", "unknown")
    CONTRACT_VALUES = ("internship", "apprenticeship", "fixed", "permanent", "other", "unknown")

    def flt_args(src) -> dict:
        """Filtri azienda, citta', modalita' e RAL da query string (GET) o JSON (POST)."""
        many = src.getlist if hasattr(src, "getlist") else (lambda k: list(src.get(k) or []))
        out = {}
        company = (src.get("company") or "").strip()
        if company:
            out["company"] = company[:100]
        cities = [("" if c == "~generica" else str(c).strip()[:80]) for c in many("where")]
        if cities:
            out["cities"] = cities[:40]
        modes = [m for m in many("mode") if m in MODE_VALUES]
        if modes:
            out["modes"] = modes
        contracts = [c for c in many("contract") if c in CONTRACT_VALUES]
        if contracts:
            out["contracts"] = contracts
        ral = to_int(src.get("ral_min"), 0, 0, 1_000_000)
        if ral:
            out["ral_min"] = ral
            out["ral_unknown"] = str(src.get("ral_unk", "1")) in ("1", "true", "True")
        return out

    def profile_arg(src):
        """Parametro `profile`: 'all' (o assente) oppure l'id di un profilo esistente. Ritorna None per 'tutti'."""
        raw = src.get("profile")
        if raw in (None, "", "all"):
            return None
        pid = to_int(raw, -1)
        if pid < 0 or ProfilesDB().get(pid) is None:
            abort(400, description="profilo sconosciuto")
        return pid

    def ProfilesDB():
        return prof.ProfileStore(open_db())

    @app.get("/api/facets")
    def facets():
        g = request.args.get("group")
        return jsonify(open_db().facets(g if g in ("main", "jooble") else None, profile=profile_arg(request.args)))

    @app.get("/api/geo/suggest")
    def geo_suggest():
        return jsonify(geomod.suggest(request.args.get("q", "")))

    @app.get("/api/geo/resolve")
    def geo_resolve():
        hit = geomod.lookup(request.args.get("q", ""))
        return jsonify(ok=bool(hit), **(hit or {}))

    def job_dict(r, full: bool = False, profiles: list | None = None) -> dict:
        d = {k: r[k] for k in ("uid", "title", "company", "location", "url", "score", "category",
                               "status", "salary", "source", "posted_at")}
        d["country"] = r["country"] or ""
        d["profiles"] = profiles if profiles is not None else open_db().profiles_of([r["uid"]]).get(r["uid"], [])
        d["adzuna"] = (r["source"] or "").startswith("adzuna")  # va mostrata l'attribuzione "Jobs by Adzuna"
        d["near"] = bool(r["near_home"])
        d["km"] = r["km"] if "km" in r.keys() else None
        d["mode"] = r["work_mode"]
        d["contract"] = r["contract"]
        d["avail"], d["avail_checked"] = r["avail"], r["avail_checked"]
        d["valid_until"], d["avail_note"] = r["valid_until"], r["avail_note"]
        d["matched"] = [m for m in (r["matched"] or "").split(",") if m]
        d["cv"], d["cv_base"] = None, None  # affinita' col CV: la riempie chi ha il CV (vedi cv_scores)
        d["id"] = r["uid"][:6]
        d["saved_at"] = r["saved_at"]
        d["saved"] = bool(r["saved_at"])
        if full:
            d["text"] = r["full_text"] or r["description"] or ""
            d["has_full"] = bool(r["full_text"])
        return d

    @app.get("/api/jobs")
    def jobs():
        a = request.args
        cat = norm_cat(a.get("cat", ""))
        if cat and not CATEGORY_OK.match(cat):
            return jsonify([])  # un nome che non puo' esistere non trova niente (mai "tutto l'elenco")
        db = open_db()
        cprof = cv_profile()
        cv_ver = cprof.version if cprof else None
        if cprof:
            cv_kick(cprof, only_if_stale=True)
        rows = db.query(
            cv_min=to_int(a.get("cv_min"), 0, 0, 100) if cprof else 0, cv_version=cv_ver, order_cv=bool(cprof and a.get("sort") == "cv"),
            category=cat if CATEGORY_OK.match(cat) else None,
            min_score=to_int(a.get("min"), 0, 0, 1000),
            status=a.get("status") if a.get("status") in STATUSES else None,
            limit=to_int(a.get("limit"), 200, 1, 500),
            profile=profile_arg(a),
            country=(a.get("country") or None) if (a.get("country") or "").lower() in prof.COUNTRIES else None,
            search=a.get("q") or None,
            near_only=a.get("near") == "1",
            only_new=a.get("new") == "1",
            group=a.get("group") if a.get("group") in ("main", "jooble") else None,
            geo=geo_arg(a)[0],
            include_closed=a.get("closed") == "1",
            saved=a.get("saved") == "1",
            **flt_args(a),
        )
        pmap = db.profiles_of([r["uid"] for r in rows])
        out = [job_dict(r, profiles=pmap.get(r["uid"], [])) for r in rows]
        if cprof:
            sc = cvmatch.scores_for(db, [j["uid"] for j in out], cv_ver)
            for j in out:
                if j["uid"] in sc:
                    j["cv"], j["cv_base"] = sc[j["uid"]]
        return jsonify(out)

    @app.get("/api/job/<uid>")
    def job(uid):
        db = open_db()
        r = db.get(uid)
        if not r:
            abort(404)
        blocked = False
        hours = cfg.get("availability", {}).get("recheck_hours", 24)
        due = (not r["full_text"] or availability.is_stale(r["avail_checked"], hours)) and r["avail"] != "closed"
        if due and availability.checkable(r["source"], r["url"], cfg) and time.time() >= net_block["until"]:
            with net.client(timeout=20, follow_redirects=True) as c:
                res = availability.check(c, r["url"], r["source"])
            if res.blocked:  # il sito limita: non si cambia nulla e si evita di insistere per un po'
                blocked = True
                net_block["until"] = time.time() + 600
            else:
                availability.apply(db, r, res)
                r = db.get(uid)
        out = job_dict(r, full=True)
        out["check_blocked"] = blocked or time.time() < net_block["until"]
        cprof = cv_profile()
        if cprof:
            m = cvmatch.for_job(db, cprof, r["uid"])
            if m:
                out["cv"], out["cv_base"] = m["score"], m["base"]
                out["cv_explain"] = m["explain"]
        return jsonify(out)

    @app.post("/api/job/<uid>/check")
    def job_check(uid):
        """Riverifica un annuncio (anche se chiuso o controllato da poco)."""
        db = open_db()
        r = db.get(uid)
        if not r:
            abort(404)
        if not availability.checkable(r["source"], r["url"], cfg):
            return jsonify(ok=False, error="questa fonte non permette di verificare l'annuncio")
        if time.time() < net_block["until"]:
            return jsonify(ok=False, blocked=True, error="il sito ha limitato le richieste: riprova tra qualche minuto")
        with net.client(timeout=20, follow_redirects=True) as c:
            res = availability.check(c, r["url"], r["source"])
        if res.blocked:
            net_block["until"] = time.time() + 600
            return jsonify(ok=False, blocked=True, error=res.note)
        availability.apply(db, r, res)
        out = job_dict(db.get(uid), full=True)
        out["check_blocked"] = False
        return jsonify(ok=True, job=out)

    @app.post("/api/job/<uid>/status")
    def set_status(uid):
        status = (request.get_json(silent=True) or {}).get("status")
        if status not in STATUSES:
            abort(400)
        body = request.get_json(silent=True) or {}
        db = open_db()
        r = db.get(uid)
        if not r:
            abort(404)
        if status == "discarded" and r["saved_at"]:
            # uno scarto non deve far sparire in silenzio un annuncio salvato: serve una conferma esplicita (unsave=true)
            if body.get("unsave") is not True:
                return jsonify(ok=False, saved=True, error="L'annuncio e' salvato: scartandolo si toglie dai Salvati."), 409
            db.unsave_job(r["uid"])
        db.set_status(r["uid"], status)
        return jsonify(ok=True)

    @app.post("/api/jobs/<uid>/save")
    def job_save(uid):
        """Salva l'annuncio per ritrovarlo nella vista Salvati (idempotente)."""
        db = open_db()
        r = db.conn.execute("SELECT uid, saved_at FROM jobs WHERE uid=?", (uid,)).fetchone()  # uid esatto: una modifica non deve mai colpire "il primo che inizia cosi'"
        if not r:
            abort(404)
        db.save_job(r["uid"])
        return jsonify(ok=True, uid=r["uid"], saved=True, saved_at=db.conn.execute("SELECT saved_at FROM jobs WHERE uid=?", (r["uid"],)).fetchone()[0])

    @app.post("/api/jobs/<uid>/unsave")
    def job_unsave(uid):
        db = open_db()
        r = db.conn.execute("SELECT uid, saved_at FROM jobs WHERE uid=?", (uid,)).fetchone()  # uid esatto: una modifica non deve mai colpire "il primo che inizia cosi'"
        if not r:
            abort(404)
        db.unsave_job(r["uid"])
        return jsonify(ok=True, uid=r["uid"], saved=False, saved_at=None)

    @app.get("/api/stats")
    def stats():
        db = open_db()
        pid = profile_arg(request.args)
        by_cat = {r["category"]: r["n"] for r in db.stats(pid)}
        all_cats = db.category_union() if pid is None else dict(by_cat)  # per i chip del filtro: con "tutti" le categorie di tutti i profili
        src, sargs = db._from(pid)  # tutti i conteggi riguardano il profilo scelto (o tutti i profili attivi)
        if sargs:
            src = src.replace("jp.profile_id=?", f"jp.profile_id={int(sargs[0])}")
        hidden = NOT_HIDDEN
        one = lambda extra: db.conn.execute(f"SELECT COUNT(*) {src} WHERE {extra} AND {hidden}").fetchone()[0]
        total_new = one("status='new' AND source NOT LIKE 'jooble%'")
        near = one("near_home=1 AND status!='discarded'")
        jooble_near_new = one("source LIKE 'jooble%' AND near_home=1 AND status='new'")
        jooble = one("source LIKE 'jooble%' AND status!='discarded'")
        closed = db.conn.execute(f"SELECT COUNT(*) {src} WHERE avail='closed' AND status!='discarded' AND {DUP_HIDDEN} AND {PROFILE_ACTIVE}").fetchone()[0]
        dc = db.dup_counts()
        return jsonify(by_cat=by_cat, all_cats=all_cats, new=total_new, near=near, total=max(0, sum(by_cat.values()) - jooble),
                       dups_pending=dc.get("pending", 0), dup_counts=dc, jooble=jooble, jooble_near_new=jooble_near_new,
                       app_counts=db.app_counts(), needs_setup=needs_setup(), closed=closed, saved=db.saved_count(pid))

    # ---- novita' dall'ultimo accesso, cronologia, scansione automatica ----
    def now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    @app.get("/api/news")
    def news():
        db = open_db()
        ack = db.kv_get("last_ack")
        if not ack:  # primo accesso: non ci sono "novita'" rispetto a un passato che non esiste
            ack = now_iso()
            db.kv_set("last_ack", ack)
        return jsonify({**db.news_since(ack), "since": ack})

    @app.post("/api/news/ack")
    def news_ack():
        open_db().kv_set("last_ack", now_iso())
        return jsonify(ok=True)

    @app.get("/api/scans")
    def scans():
        return jsonify([dict(r) for r in open_db().recent_scans(8)])

    def schedule_payload():
        st = scheduler.status(cfg)
        last = open_db().recent_scans(1)
        st["last"] = dict(last[0]) if last else None
        return st

    @app.get("/api/schedule")
    def schedule_get():
        return jsonify(schedule_payload())

    @app.post("/api/schedule")
    def schedule_set():
        if not scheduler.supported():
            abort(400, description=scheduler.unsupported_reason())
        b = request.get_json(silent=True) or {}
        try:
            req = scheduler.parse_request(b)
        except ValueError as e:
            abort(400, description=str(e))
        kind, times, hours, enabled = req["kind"], req["times"], req["hours"], req["enabled"]
        settings.save_overrides(cfg_file, {
            "schedule.enabled": enabled, "schedule.kind": kind, "schedule.times": scheduler.format_times(times),
            "schedule.hours": hours, "schedule.notify": bool(b.get("notify", True))})
        fresh = settings.load_config(cfg_file)
        cfg.clear()
        cfg.update(fresh)
        try:
            scheduler.install(kind, times, hours) if enabled else scheduler.uninstall()
        except RuntimeError as e:
            return jsonify(ok=False, error=str(e)), 500
        return jsonify(ok=True, **schedule_payload())

    @app.post("/api/notify/test")
    def notify_test():
        return jsonify(ok=autoscan.notify_native(f"{APP_NAME}: prova", "Le notifiche funzionano."))

    # ---- impostazioni ----
    def needs_setup() -> bool:
        src = cfg.get("sources", {})
        has_adzuna = bool(src.get("adzuna", {}).get("app_key"))
        has_jooble = bool(src.get("jooble", {}).get("api_key"))
        return not (has_adzuna or has_jooble)

    @app.get("/api/settings")
    def settings_get():
        return jsonify(
            fields=settings.describe(cfg), version=__version__, user_agent=net.user_agent(), in_app=bool(os.environ.get("JOBSHUNTER_HOME")),
            needs_setup=needs_setup(),
            paths={"home": str(settings.home()), "db": str(db_file()), "config": str(cfg_file),
                   "reports": str(settings.resolve_path(cfg.get("report", {}).get("dir", "reports")))})

    @app.post("/api/settings")
    def settings_save():
        if state["running"]:
            return jsonify(ok=False, error="scan in corso: fermalo prima di cambiare le impostazioni"), 409
        b = request.get_json(silent=True) or {}
        try:
            clean = settings.clean_values(b.get("values") or {})  # segreto vuoto = invariato
        except ValueError as e:
            abort(400, description=str(e))
        if clean.get("home") and not geomod.lookup(clean["home"]):
            abort(422, description="città non trovata")
        settings.save_overrides(cfg_file, clean, [k for k in (b.get("clear") or []) if k in settings.SECRET_KEYS])
        fresh = settings.load_config(cfg_file)
        cfg.clear()
        cfg.update(fresh)
        return jsonify(ok=True)

    @app.post("/api/settings/test/<name>")
    def settings_test(name):
        """Verifica la chiave con UNA richiesta (per Jooble ne consuma una delle 500)."""
        try:
            with net.client(timeout=15) as c:
                if name == "adzuna":
                    a = cfg.get("sources", {}).get("adzuna", {})
                    if not (a.get("app_id") and a.get("app_key")):
                        return jsonify(ok=False, detail="inserisci e salva Application ID e Key")
                    r = c.get(f"https://api.adzuna.com/v1/api/jobs/{a.get('country', 'it')}/search/1",
                              params={"app_id": a["app_id"], "app_key": a["app_key"], "results_per_page": 1, "what": "it"})
                elif name == "jooble":
                    j = cfg.get("sources", {}).get("jooble", {})
                    if not j.get("api_key"):
                        return jsonify(ok=False, detail="inserisci e salva la chiave Jooble")
                    r = c.post(f"https://{j.get('host', 'jooble.org')}/api/{j['api_key']}", json={"keywords": "it", "location": "Roma"})
                else:
                    abort(404)
        except httpx.HTTPError as e:
            return jsonify(ok=False, detail=f"errore di rete: {type(e).__name__}")
        ok = r.status_code == 200
        return jsonify(ok=ok, detail="chiave valida" if ok else f"risposta {r.status_code}: controlla chiave e host")

    # ---- procedura guidata di primo avvio ----
    onb_limiter = onboarding.Limiter()

    def onb_body() -> dict:
        b = request.get_json(silent=True)
        if not isinstance(b, dict):
            abort(400, description="serve un oggetto JSON")
        return b

    @app.get("/api/onboarding")
    def onboarding_state():
        return jsonify(onboarding.state(cfg, open_db()))

    @app.post("/api/onboarding/test-adzuna")
    def onboarding_test_adzuna():
        b = onb_body()
        return jsonify(onboarding.test_adzuna(b.get("app_id"), b.get("app_key"), b.get("country"), onb_limiter))

    @app.post("/api/onboarding/estimate")
    def onboarding_estimate():
        """Anteprima della prima scansione con le scelte fatte: controlla tutto ma non salva niente."""
        try:
            plan = onboarding.prepare(onb_body(), cfg, ProfilesDB())
        except onboarding.OnboardingError as e:
            return jsonify(ok=False, error=str(e), field=e.field), 400
        return jsonify(ok=True, **onboarding.estimate(plan, cfg))

    @app.post("/api/onboarding/complete")
    def onboarding_complete():
        b = onb_body()
        with lock:
            if state["running"]:
                return jsonify(ok=False, error="una scansione è in corso: aspetta che finisca o fermala"), 409
        db = open_db()
        with onboarding.COMPLETE_LOCK, prof.PROFILE_LOCK:  # prima la conclusione della guida, poi i profili (sempre in quest'ordine: niente deadlock)
            try:
                plan = onboarding.prepare(b, cfg, prof.ProfileStore(db))
            except onboarding.OnboardingError as e:
                return jsonify(ok=False, error=str(e), field=e.field), 400
            was_scheduled = bool(cfg.get("schedule", {}).get("enabled"))
            try:
                pid = onboarding.apply(plan, cfg_file, db, cfg, rescore)
            except prof.ProfileError as e:
                return jsonify(ok=False, error=str(e), field="profile"), 400
            except Exception:  # tutto e' stato rimesso com'era: si risponde in italiano, senza dettagli tecnici
                app.logger.exception("guida di primo avvio: salvataggio non riuscito")
                return jsonify(ok=False, error="Non sono riuscito a salvare le scelte e non ho cambiato niente. Riprova tra un attimo."), 500
        notes = list(plan.notes)
        sch = plan.schedule
        if sch is not None and (sch["enabled"] or was_scheduled):
            try:
                scheduler.install(sch["kind"], sch["times"], sch["hours"]) if sch["enabled"] else scheduler.uninstall()
            except RuntimeError:
                settings.save_overrides(cfg_file, {"schedule.enabled": False})
                fresh = settings.load_config(cfg_file)
                cfg.clear()
                cfg.update(fresh)
                notes.append("Non sono riuscito ad attivare la scansione automatica: puoi riprovare dalle Impostazioni.")
        db.kv_set(onboarding.KV_DONE, "1")
        return jsonify(ok=True, profile_id=pid, notes=notes)

    @app.post("/api/tutorial/seen")
    def tutorial_seen():
        """Ricorda (nelle impostazioni, non nel browser) che il tutorial e' stato visto o saltato; seen=false lo riarma."""
        b = request.get_json(silent=True)
        seen = True if not isinstance(b, dict) else b.get("seen", True)
        if not isinstance(seen, bool):
            abort(400, description="seen deve essere true o false")
        open_db().kv_set(onboarding.KV_TUTORIAL, "1" if seen else "0")
        return jsonify(ok=True, tutorial_seen=seen)

    @app.post("/api/onboarding/skip")
    def onboarding_skip():
        open_db().kv_set(onboarding.KV_DONE, "1")
        return jsonify(ok=True)

    # ---- profili di ricerca ----
    def profile_json(p: prof.Profile, store: prof.ProfileStore) -> dict:
        d = p.to_dict(meta=True)
        d.setdefault("categories", [])
        d["job_count"] = store.job_count(p.id)
        return d

    def body_profile() -> dict:
        b = request.get_json(silent=True)
        if not isinstance(b, dict):
            abort(400, description="serve un profilo in formato JSON")
        return b

    def bad(msg: str, code: int = 400):
        return jsonify(ok=False, error=msg), code

    @app.get("/api/presets")
    def presets_list():
        out = []
        for key, p in prof.PRESETS.items():
            groups = [{"label": g["label"], "terms": dict(g["terms"])} for g in p["groups"]]
            if key == "cybersecurity" and cfg.get("keywords"):
                groups = [{"label": c["label"], "terms": dict(c["terms"])} for c in cfg["keywords"].values()]
            out.append({"key": key, "label": p["label"], "description": p["description"],
                        "default_titles": list(p["default_titles"]), "groups": groups,
                        "categories": prof.preset_categories(key, cfg)})
        return jsonify(out)

    @app.get("/api/countries")
    def countries_list():
        return jsonify([{"code": c, "name": v["name"], "currency": v["currency"], "languages": list(v["languages"]),
                         "adzuna": v["adzuna"]} for c, v in prof.COUNTRIES.items()])

    @app.get("/api/profiles")
    def profiles_list():
        store = ProfilesDB()
        return jsonify([profile_json(p, store) for p in store.list()])

    recalc_failed = "Non sono riuscito a ricalcolare gli annunci: il profilo e' rimasto com'era. Riprova tra un attimo."

    @app.post("/api/profiles")
    def profiles_create():
        body = body_profile()
        with prof.PROFILE_LOCK:
            store = ProfilesDB()
            try:
                p = store.add(body, cfg)
            except prof.ProfileError as e:
                return bad(str(e))
            try:
                rescore(store.db, cfg, [p.id])
            except Exception as e:  # il ricalcolo ha rimesso a posto il database (rollback): si toglie anche il profilo appena creato
                app.logger.error("ricalcolo del nuovo profilo non riuscito (%s)", type(e).__name__)
                store.remove_raw(p.id)
                return jsonify(ok=False, error=recalc_failed), 500
            return jsonify(ok=True, profile=profile_json(store.get(p.id), store))

    @app.post("/api/profiles/preview")
    def profiles_preview():
        try:
            p = prof.validate_profile(body_profile(), cfg)
        except prof.ProfileError as e:
            return bad(str(e))
        qs = prof.profile_queries(p, cfg)
        notes = []
        req = prof.estimate_requests([p], cfg)
        srcs = cfg.get("sources", {})
        if not srcs.get("adzuna", {}).get("enabled"):
            notes.append("Adzuna non è attivo: metti le chiavi nelle Impostazioni per cercare in questi paesi.")
        for c in p.countries:
            if not prof.COUNTRIES[c]["adzuna"]:
                notes.append(f"{prof.COUNTRIES[c]['name']}: Adzuna non copre questo paese.")
        if req.get("adzuna", 0) > 60:
            notes.append("Sono molte richieste ad Adzuna: se il sito le limita, riduci i paesi o i titoli.")
        if p.city and not geomod.lookup(p.city, p.countries[0]):
            notes.append(f"Non trovo la città {p.city}: la ricerca coprirà tutto il paese.")
        return jsonify(queries=[{"q": q.q, "country": q.country, "where": q.where, "radius_km": q.radius_km,
                                 "pages": list(q.pages)} for q in qs],
                       keywords=prof.keywords_of(p, cfg), requests=req, notes=notes)

    @app.post("/api/profiles/<int:pid>")
    def profiles_update(pid):
        body = body_profile()
        with prof.PROFILE_LOCK:  # salvataggio e ricalcolo sono un blocco solo: due salvataggi insieme non si mescolano
            store = ProfilesDB()
            old = store.get(pid)  # riletto DENTRO il blocco
            if old is None:
                abort(404)
            saved_row = store.raw_row(pid)
            try:
                new = store.update(pid, body, cfg)
            except prof.ProfileError as e:
                return bad(str(e))
            a, b = old.to_dict(), new.to_dict()
            a.pop("active"), b.pop("active")
            if a != b:  # cambiano le regole: si rivalutano gli annunci già salvati
                if old.categories != new.categories:
                    store.db.snapshot()  # copia di sicurezza prima di ricalcolare le categorie
                try:
                    rescore(store.db, cfg, [pid])
                except Exception as e:  # rollback gia' fatto dal ricalcolo: si rimette anche il profilo com'era, cosi' riprovare ricalcola davvero
                    app.logger.error("ricalcolo del profilo non riuscito (%s)", type(e).__name__)
                    store.restore_raw(pid, saved_row)
                    return jsonify(ok=False, error=recalc_failed), 500
            else:
                store.db.refresh_best()
            return jsonify(ok=True, profile=profile_json(store.get(pid), store))

    @app.post("/api/profiles/<int:pid>/delete")
    def profiles_delete(pid):
        with prof.PROFILE_LOCK:
            store = ProfilesDB()
            if store.get(pid) is None:
                abort(404)
            try:
                store.delete(pid)
            except prof.ProfileError as e:
                return bad(str(e))
        return jsonify(ok=True)

    # ---- il tuo CV: caricamento, competenze, confronto con gli annunci (tutto in locale) ----
    cvm = {"running": False, "done": 0, "total": 0, "cancel": None, "again": False}

    def cv_profile():
        return cvmod.current()

    def cv_worker(cprof, cancel):
        db = open_db()

        def on_progress(i, n):
            with lock:
                cvm.update(done=i, total=n)

        try:
            cvmatch.recompute(db, cprof, progress=on_progress, cancel=cancel)
            if cvmod.current() is None:  # il CV e' stato eliminato mentre si calcolava: non deve restare niente
                cvmatch.clear(db)
        except Exception as e:  # il thread non deve morire in silenzio, ma niente dettagli (potrebbero contenere testo)
            app.logger.error("confronto col CV non riuscito (%s)", type(e).__name__)
        finally:
            with lock:
                again = cvm["again"] and not cancel.is_set()
                cvm.update(running=False, again=False)
            if again:
                cv_kick(cvmod.current())

    def cv_kick(cprof, only_if_stale: bool = False) -> bool:
        """Avvia (se serve e se non sta gia' girando) il ricalcolo in background. Con un CV cambiato nel frattempo lo ripete."""
        if cprof is None:
            return False
        if only_if_stale and not cvmatch.stale_count(open_db(), cprof.version):
            return False
        with lock:
            if cvm["running"]:
                cvm["again"] = True
                return False
            cancel = threading.Event()
            cvm.update(running=True, done=0, total=0, cancel=cancel, again=False)
        threading.Thread(target=cv_worker, args=(cprof, cancel), daemon=True).start()
        return True

    def cv_state(cprof) -> dict:
        out = cvmod.summary(cprof)
        with lock:
            run = {"running": cvm["running"], "done": cvm["done"], "total": cvm["total"]}
        if cprof is not None:
            run["pending"] = cvmatch.stale_count(open_db(), cprof.version)
        out["matching"] = run
        return out

    def cv_fail(e: cvfile.CvError):
        return jsonify(ok=False, error=str(e)), 400

    @app.get("/api/cv")
    def cv_get():
        cprof = cv_profile()
        if cprof:
            cv_kick(cprof, only_if_stale=True)
        return jsonify(cv_state(cprof))

    @app.get("/api/cv/vocab")
    def cv_vocab():
        """Nomi delle competenze note (per i suggerimenti mentre si scrive): solo il vocabolario, niente del CV."""
        from .. import skills as skmod

        return jsonify([n for n in skmod.all_skill_names() if not skmod.is_language(n)])

    @app.post("/api/cv")
    def cv_upload():
        """Carica il CV: un file (multipart, campo `file`) oppure testo incollato (JSON {text}). Si salva solo il testo estratto."""
        try:
            if request.files:
                f = request.files.get("file")
                if f is None:
                    raise cvfile.CvError("Scegli un file da caricare.")
                data = f.stream.read(cvfile.MAX_BYTES + 1)
                text, source = cvfile.extract(data, f.filename or "")
            else:
                b = request.get_json(silent=True)
                if not isinstance(b, dict) or not isinstance(b.get("text"), str):
                    raise cvfile.CvError("Scegli un file oppure incolla il testo del CV.")
                text, source = cvfile.check_text(b["text"]), "incollato"
            cvmod.save_text(text, source)
        except cvfile.CvError as e:
            return cv_fail(e)
        except HTTPException:
            raise
        except Exception as e:  # mai dettagli: potrebbero contenere pezzi del documento
            app.logger.error("caricamento del CV non riuscito (%s)", type(e).__name__)
            return jsonify(ok=False, error="Non sono riuscito a leggere il file. Riprova, oppure incolla il testo del CV."), 500
        cprof = cv_profile()
        cv_kick(cprof)
        return jsonify(ok=True, cv=cv_state(cprof))

    @app.post("/api/cv/skills")
    def cv_skills():
        b = request.get_json(silent=True)
        if not isinstance(b, dict):
            abort(400, description="serve un oggetto JSON")
        lists = {}
        for k in ("add", "remove", "restore"):
            v = b.get(k) or []
            if not isinstance(v, list) or len(v) > 40:
                abort(400, description="elenco di competenze non valido")
            lists[k] = v
        try:
            cvmod.change_skills(**lists)
        except cvfile.CvError as e:
            return cv_fail(e)
        cprof = cv_profile()
        cv_kick(cprof)
        return jsonify(ok=True, cv=cv_state(cprof))

    @app.post("/api/cv/delete")
    def cv_delete():
        with lock:
            if cvm["cancel"] is not None:
                cvm["cancel"].set()
        try:
            cvmod.delete()
        except cvmod.CvDeleteError as e:  # Windows: file aperto da un altro programma e non azzerabile
            return jsonify(ok=False, error=str(e)), 409
        cvmatch.clear(open_db())
        return jsonify(ok=True, cv={"present": False})

    @app.post("/api/cv/match")
    def cv_match_start():
        """Ricalcolo su richiesta (di norma parte da solo)."""
        cprof = cv_profile()
        if cprof is None:
            return jsonify(ok=False, error="Non hai ancora caricato un CV."), 400
        cv_kick(cprof)
        return jsonify(ok=True, cv=cv_state(cprof))

    # ---- candidature ----
    DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def clean(b: dict, key: str, maxlen: int = 300):
        v = b.get(key)
        return None if v is None else str(v).strip()[:maxlen]

    def clean_day(b: dict, key: str):
        v = clean(b, key)
        if v in (None, ""):
            return None if v is None else ""
        if not DAY.match(v):
            abort(400, description=f"data non valida: {key}")
        return v

    @app.get("/api/apps")
    def apps_list():
        st = request.args.get("outcome", "active")
        return jsonify(open_db().list_applications(st if st in ("active", "closed", "all") else "active"))

    @app.post("/api/apps")
    def apps_create():
        b = request.get_json(silent=True) or {}
        company, role = clean(b, "company"), clean(b, "role")
        if not company or not role:
            abort(400, description="azienda e ruolo sono obbligatori")
        new_id = open_db().add_application(
            company=company, role=role, location=clean(b, "location") or "", url=clean(b, "url") or "",
            applied_at=clean_day(b, "applied_at") or None, notes=clean(b, "notes", 5000) or "",
            contact=clean(b, "contact") or "", follow_up=clean_day(b, "follow_up") or None)
        return jsonify(ok=True, id=new_id)

    @app.post("/api/apps/<int:app_id>")
    def apps_update(app_id):
        b = request.get_json(silent=True) or {}
        db = open_db()
        at = clean_day(b, "at") or None
        if "stage" in b and (b["stage"] not in STAGES or not db.set_app_stage(app_id, b["stage"], at, clean(b, "note") or "")):
            abort(400)
        if "outcome" in b and (b["outcome"] not in OUTCOMES or not db.set_app_outcome(app_id, b["outcome"], at, clean(b, "note") or "")):
            abort(400)
        fields = {}
        for k in ("company", "role", "location", "url", "contact"):
            if k in b:
                fields[k] = clean(b, k) or ""
        if "notes" in b:
            fields["notes"] = clean(b, "notes", 5000) or ""
        for k in ("applied_at", "follow_up"):
            if k in b:
                fields[k] = clean_day(b, k) or None
        if fields and not db.update_application(app_id, **fields):
            abort(404)
        return jsonify(ok=True)

    @app.post("/api/apps/<int:app_id>/delete")
    def apps_delete(app_id):
        if not open_db().delete_application(app_id):
            abort(404)
        return jsonify(ok=True)

    # ---- duplicati: l'app propone, l'utente decide ----
    def side(r, k: str) -> dict:
        return {"uid": r[f"uid_{k}"], "title": r[f"{k}_title"], "company": r[f"{k}_company"],
                "location": r[f"{k}_location"], "url": r[f"{k}_url"], "source": r[f"{k}_source"],
                "salary": r[f"{k}_salary"], "score": r[f"{k}_score"], "status": r[f"{k}_status"],
                "category": r[f"{k}_category"], "posted_at": r[f"{k}_posted"], "keep": r["keep_uid"] == r[f"uid_{k}"]}

    @app.get("/api/dups")
    def dups():
        st = request.args.get("status", "pending")
        if st not in ("pending", "confirmed", "rejected"):
            abort(400)
        rows = open_db().list_dups(st)
        return jsonify([{"id": r["id"], "pct": r["pct"], "status": r["status"], "auto": bool(r["auto"]),
                         "decided_at": r["decided_at"], "a": side(r, "a"), "b": side(r, "b")} for r in rows])

    @app.post("/api/dups/<int:pair_id>")
    def dup_decide(pair_id):
        b = request.get_json(silent=True) or {}
        if b.get("status") not in ("pending", "confirmed", "rejected"):
            abort(400)
        if not open_db().set_dup_status(pair_id, b["status"], swap=bool(b.get("swap"))):
            abort(404)
        return jsonify(ok=True)

    @app.post("/api/dups/rescan")
    def dup_rescan():
        return jsonify(ok=True, new=find_duplicates(open_db(), cfg))

    # ---- verifica in blocco (in background, con stop) ----
    chk = {"running": False, "cancel": None, "done": 0, "total": 0, "open": 0, "closed": 0, "unknown": 0,
           "blocked": False}

    def check_worker(cancel: threading.Event, uids: list[str]):
        db = open_db()

        def on_progress(i, n, row, res):
            with lock:
                chk.update(done=i, total=n)
                chk[res.state] += 1

        try:
            out = availability.run_check(db, cfg, uids=uids, limit=60, cancel=cancel, on_progress=on_progress)
            with lock:
                chk["total"], chk["blocked"] = out["total"], out["blocked"]
                if out["blocked"]:
                    net_block["until"] = time.time() + 600
        finally:
            with lock:
                chk["running"] = False

    @app.post("/api/check/start")
    def check_start():
        b = request.get_json(silent=True) or {}
        uids = [str(u) for u in (b.get("uids") or [])][:80]
        with lock:
            if state["running"] or chk["running"]:
                return jsonify(ok=False, error="scan o verifica gia' in corso"), 409
            if time.time() < net_block["until"]:
                return jsonify(ok=False, blocked=True, error="il sito ha limitato le richieste: riprova tra qualche minuto")
            cancel = threading.Event()
            chk.update(running=True, cancel=cancel, done=0, total=0, open=0, closed=0, unknown=0, blocked=False)
        threading.Thread(target=check_worker, args=(cancel, uids), daemon=True).start()
        return jsonify(ok=True)

    @app.post("/api/check/stop")
    def check_stop():
        with lock:
            if chk["running"] and chk["cancel"]:
                chk["cancel"].set()
        return jsonify(ok=True)

    @app.get("/api/check/status")
    def check_status():
        with lock:
            return jsonify({k: v for k, v in chk.items() if k != "cancel"})

    # ---- scan in background con stop ----
    def scan_worker(cancel: threading.Event, profile_ids: list[int] | None = None):
        db = open_db()  # connessione propria del thread

        def on_event(kind, d):
            with lock:
                s = state["sources"]
                name = d.get("name")
                if kind == "queued":
                    s[name] = {"status": "queued"}
                    state["order"].append(name)
                elif kind == "start":
                    s[name] = {"status": "running"}
                elif kind == "error":
                    s[name] = {"status": "error", "msg": d["msg"]}
                elif kind == "done":
                    s[name] = {"status": "done", "read": d["read"], "kept": d["kept"], "new": d["new"]}
                elif kind == "cancelled":
                    state["message"] = d["reason"]
                elif kind == "checking":
                    state["message"] = "verifico che i migliori annunci siano ancora aperti..."

        try:
            res, info = autoscan.run_auto(cfg, db, kind="manuale", cancel=cancel, on_event=on_event, notify=False,
                                       profile_ids=profile_ids)
            if res is None:  # una scansione automatica e' gia' in corso: non se ne avvia una seconda
                with lock:
                    state["message"] = info["message"]
                    state["summary"] = {"read": 0, "kept": 0, "new": 0, "cancelled": True, "reason": info["message"],
                                        "dups_new": 0, "closed_found": 0, "check_blocked": False}
                return
            cv_kick(cv_profile(), only_if_stale=True)  # i nuovi annunci si confrontano col CV, in background
            with lock:
                state["summary"] = {"read": res.read, "kept": res.kept, "new": res.new,
                                    "cancelled": res.cancelled, "reason": res.reason, "dups_new": res.dups_new,
                                    "closed_found": res.closed_found, "check_blocked": res.check_blocked}
        except Exception as e:  # il thread non deve morire in silenzio
            with lock:
                state["message"] = f"errore: {e}"
        finally:
            with lock:
                for name, v in state["sources"].items():
                    if v["status"] in ("queued", "running"):
                        v["status"] = "stopped"
                state["running"] = False
                state["finished"] = time.time()

    @app.post("/api/scan/start")
    def scan_start():
        body = request.get_json(silent=True) if request.data else {}
        if body is None or not isinstance(body, dict):
            abort(400, description="serve un oggetto JSON")
        pids = None
        if body.get("profile_ids") is not None:
            raw = body["profile_ids"]
            if not isinstance(raw, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in raw):
                abort(400, description="profile_ids deve essere un elenco di numeri")
            store = ProfilesDB()
            if any(store.get(i) is None for i in raw):
                abort(400, description="profilo sconosciuto")
            pids = list(raw)
        with lock:
            if state["running"] or chk["running"]:
                return jsonify(ok=False, error="scan o verifica gia' in corso"), 409
            cancel = threading.Event()
            state.update(running=True, cancel=cancel, sources={}, order=[], summary=None,
                         message="", started=time.time(), finished=None)
        threading.Thread(target=scan_worker, args=(cancel, pids), daemon=True).start()
        return jsonify(ok=True)

    @app.post("/api/scan/stop")
    def scan_stop():
        with lock:
            if state["running"] and state["cancel"]:
                state["cancel"].set()
                state["message"] = "interruzione in corso..."
        return jsonify(ok=True)

    @app.get("/api/status")
    def status():
        with lock:
            return jsonify(
                running=state["running"], sources=state["sources"], order=state["order"],
                summary=state["summary"], message=state["message"],
                elapsed=(time.time() - state["started"]) if state["running"] and state["started"] else None,
                max_seconds=cfg["general"].get("max_scan_seconds", 300),
            )

    @app.post("/api/report")
    def report():
        b = request.get_json(silent=True) or {}
        if not isinstance(b, dict):
            abort(400, description="serve un oggetto JSON")
        cat = norm_cat(b.get("cat") or "")
        if cat and not CATEGORY_OK.match(cat):
            return jsonify(ok=False, error="nessun annuncio con questi filtri"), 404
        geo, geo_label = geo_arg(b)
        result = build_report(
            cfg, open_db(),
            category=cat if CATEGORY_OK.match(cat) else None,
            min_score=to_int(b.get("min"), 30, 0, 1000), limit=to_int(b.get("limit"), 20, 1, 100),
            near=bool(b.get("near")), only_new=bool(b.get("new")),
            group=b.get("group") if b.get("group") in ("main", "jooble") else None,
            geo=geo, geo_label=geo_label, filters=flt_args(b),
        )
        if not result:
            return jsonify(ok=False, error="nessun annuncio con questi filtri"), 404
        path, n, full, closed, blocked = result
        if path is None:
            return jsonify(ok=False, error=f"tutti gli annunci ({closed}) risultano chiusi"), 404
        return jsonify(ok=True, path=str(path), name=path.name, n=n, full=full, closed=closed, blocked=blocked)

    return app


def serve(config_path: str | None = None, port: int = 8765, open_browser: bool = True) -> None:
    import webbrowser

    app = create_app(config_path, port)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    from werkzeug.serving import make_server

    from .. import stopsignals

    server = make_server("127.0.0.1", port, app, threaded=True)
    print(f" * Server su http://127.0.0.1:{port}/ (Ctrl+C per chiudere)", flush=True)
    stopsignals.install()
    th = threading.Thread(target=server.serve_forever, name="gui-server", daemon=True)
    th.start()
    try:
        stopsignals.wait()
    except KeyboardInterrupt:
        pass
    server.shutdown()  # uscita ordinata, codice 0
    server.server_close()
