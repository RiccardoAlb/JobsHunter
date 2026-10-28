"""Procedura guidata di primo avvio: logica (la GUI la usa tramite gli endpoint /api/onboarding).

Tutto passa dalla validazione che esiste già (profili, impostazioni, pianificazione): qui si mettono insieme i pezzi,
si controlla ogni campo lato server e si applica il risultato in un colpo solo.
"""
from __future__ import annotations

import copy
import logging
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import geo as geomod
from . import profiles as prof
from . import net, scheduler, settings

# httpx scrive l'indirizzo completo delle richieste (con la chiave) nei log di livello INFO: qui non deve succedere
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

KV_DONE = "onboarding_done"
KV_PROFILE = "onboarding_profile_id"
MAX_TITLES = 8
TEST_INTERVAL = 5.0  # secondi tra due prove della chiave
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
KEY_OK = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
JOOBLE_HOST_OK = re.compile(r"^(?:[a-z0-9-]+\.)*jooble\.org$")  # la chiave viaggia solo verso Jooble, mai altrove
PERSONAL_KEYS = {"home", "radius_km", "report.dir", "notify.topic"}
FREE_SOURCES = ("arbeitnow", "remoteok", "remotive")


class OnboardingError(ValueError):
    """Dato non valido: il messaggio è in italiano e va mostrato così com'è. `field` dice quale campo."""

    def __init__(self, message: str, field: str = ""):
        super().__init__(message)
        self.field = field


# ------------------------------------------------------------------ stato ----
def untouched_default(store: prof.ProfileStore) -> prof.Profile | None:
    """Il profilo Cybersecurity creato in automatico alla prima apertura e mai modificato dall'utente."""
    ps = store.list()
    if len(ps) == 1:
        p = ps[0]
        if p.name == "Cybersecurity" and p.preset == "cybersecurity" and p.created == p.updated:
            return p
    return None


def _count(db, sql: str) -> int:
    return db.conn.execute(sql).fetchone()[0]


def has_keys(cfg: dict) -> bool:
    src = cfg.get("sources", {})
    return bool(src.get("adzuna", {}).get("app_key") or src.get("jooble", {}).get("api_key"))


def state(cfg: dict, db) -> dict:
    """Serve alla GUI per decidere se mostrare la guida. Un utente con dati, chiavi o profili suoi non la vede da sola."""
    store = prof.ProfileStore(db)
    done = db.kv_get(KV_DONE) == "1"
    keys = has_keys(cfg)
    data = bool(_count(db, "SELECT COUNT(*) FROM jobs") or _count(db, "SELECT COUNT(*) FROM applications")
                or _count(db, "SELECT COUNT(*) FROM scan_runs"))
    ov = settings.load_overrides(Path(cfg["_config_path"])) if cfg.get("_config_path") else {}
    # impostazioni "personali" (casa, report, notifiche, pianificazione, fonti): soglie e simili non contano
    has_settings = any(k in PERSONAL_KEYS or k.startswith(("schedule.", "sources.")) for k in ov)
    has_profiles = store.count() > 1 or (store.count() == 1 and untouched_default(store) is None)
    needed = not done and not (keys or data or has_profiles or has_settings)
    pid = db.kv_get(KV_PROFILE)
    mine = store.get(int(pid)) if pid and pid.isdigit() else None
    az, jo = cfg.get("sources", {}).get("adzuna", {}), cfg.get("sources", {}).get("jooble", {})
    sch = scheduler.current_settings(cfg)
    return {
        "needed": needed, "done": done, "has_keys": keys, "has_data": data, "has_profiles": has_profiles, "has_settings": has_settings,
        "step_hint": "welcome" if needed else ("rerun" if done else "none"),
        "suggested_report_dir": str(Path.home() / "Documents" / "JobsHunter"),
        "can_schedule": sys.platform == "darwin",
        "prefill": {
            "home": az.get("home", "") or "", "radius_km": int(az.get("radius_km", 100) or 100),
            "has_adzuna": bool(az.get("app_key")), "has_jooble": bool(jo.get("api_key")),
            "jooble_host": jo.get("host", "") or "",
            "report_dir": cfg.get("report", {}).get("dir", "reports"),
            "schedule": {k: sch[k] for k in ("enabled", "kind", "times", "hours", "notify")},
            "profile": mine.to_dict() if mine else None,
        },
    }


# --------------------------------------------------------- prova chiave ----
class Limiter:
    """Al massimo una prova ogni `interval` secondi (per non farsi bloccare da Adzuna)."""

    def __init__(self, interval: float = TEST_INTERVAL):
        self.interval, self._last, self._lock = interval, -1e9, threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if now - self._last < self.interval:
                return False
            self._last = now
            return True


def make_client() -> httpx.Client:
    """Client HTTP per la prova (i test lo sostituiscono: nessuna rete vera nei test)."""
    return net.client(timeout=10, follow_redirects=False)


def _result(ok: bool, status: str, message: str, **extra) -> dict:
    return {"ok": ok, "status": status, "message": message, **extra}


def test_adzuna(app_id, app_key, country, limiter: Limiter) -> dict:
    """UNA sola richiesta (1 risultato). Le chiavi non vengono mai scritte nei log né restituite."""
    app_id = app_id.strip() if isinstance(app_id, str) else ""
    app_key = app_key.strip() if isinstance(app_key, str) else ""
    if not app_id or not app_key:
        return _result(False, "empty_fields", "Inserisci sia l'Application ID sia l'Application Key.")
    if not KEY_OK.match(app_id) or not KEY_OK.match(app_key):
        return _result(False, "invalid", "Le chiavi contengono caratteri strani: copiale di nuovo dalla pagina di Adzuna, senza spazi.")
    country = (country if isinstance(country, str) else "it").lower()
    if country not in prof.COUNTRIES or not prof.COUNTRIES[country]["adzuna"]:
        country = "it"
    if not limiter.allow():
        return _result(False, "blocked", "Attendi qualche secondo prima di riprovare.", wait=True)
    try:
        with make_client() as c:
            r = c.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                      params={"app_id": app_id, "app_key": app_key, "results_per_page": 1, "what": "lavoro"})
    except Exception:  # qualsiasi errore del client (rete, indirizzo, flusso): mai un 500, mai dettagli con la chiave
        return _result(False, "network", "Non riesco a collegarmi a Adzuna. Controlla la connessione a internet e riprova.")
    code = r.status_code
    if code == 200:
        try:
            ok_body = isinstance(r.json(), dict)
        except Exception:
            ok_body = False
        if ok_body:
            return _result(True, "ok", "La chiave funziona.")
        return _result(False, "network", "Ho ricevuto una risposta inattesa: potrebbe essere una rete Wi-Fi che chiede l'accesso o un filtro. Riprova da un'altra rete.")
    if code in (403, 429):
        return _result(False, "blocked", "Adzuna sta limitando le richieste. Riprova tra qualche minuto: la chiave potrebbe essere buona.")
    if code >= 500 or code in (408,) or 300 <= code < 400 or code == 404:
        return _result(False, "network", "Non riesco a verificare la chiave in questo momento (risposta inattesa). Riprova tra poco.")
    return _result(False, "invalid", "Adzuna non riconosce questa chiave. Controlla di aver copiato bene ID e Key.")


# --------------------------------------------------------------- piano ----
@dataclass
class Plan:
    profile: prof.Profile
    overrides: dict
    country: str
    schedule: dict | None = None
    notes: list[str] = field(default_factory=list)


def _int(value, default, lo, hi, what, fld):
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise OnboardingError(f"{what}: numero non valido", fld)
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        raise OnboardingError(f"{what}: numero non valido", fld) from None
    if not lo <= n <= hi:
        raise OnboardingError(f"{what}: deve essere tra {lo} e {hi}", fld)
    return n


def _text(value, what, fld, maxlen=200) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise OnboardingError(f"{what}: serve un testo", fld)
    text = value.strip()
    if len(text) > maxlen:  # mai troncare in silenzio: sarebbe un altro valore da quello scritto
        raise OnboardingError(f"{what}: troppo lungo (massimo {maxlen} caratteri)", fld)
    if _CTRL.search(text):
        raise OnboardingError(f"{what}: contiene caratteri non validi", fld)
    return text


def auto_name(preset: str, titles: list[str]) -> str:
    if preset != "custom" and preset in prof.PRESETS:
        return prof.PRESETS[preset]["label"].split(":")[0].strip()
    name = (titles[0][:1].upper() + titles[0][1:])[:80] if titles else "La mia ricerca"
    return f"Ricerca {name}"[:80] if name.isdigit() else name  # un nome solo numerico sarebbe scambiato per un id


def _check_text(obj, depth=0) -> None:
    """Rifiuta testi che non si possono scrivere in UTF-8 (es. un surrogato isolato): romperebbero salvataggio e risposta."""
    if depth > 6:
        raise OnboardingError("richiesta non valida")
    if isinstance(obj, str):
        try:
            obj.encode("utf-8")
        except UnicodeEncodeError:
            raise OnboardingError("Il testo contiene caratteri non validi.") from None
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _check_text(k, depth + 1)
            _check_text(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _check_text(v, depth + 1)


def prepare(payload, cfg: dict, store: prof.ProfileStore) -> Plan:
    """Controlla ogni campo e prepara tutto, senza scrivere niente. Solleva OnboardingError."""
    if not isinstance(payload, dict):
        raise OnboardingError("richiesta non valida")
    _check_text(payload)
    pr = payload.get("profile")
    if not isinstance(pr, dict):
        raise OnboardingError("Scegli che lavoro cerchi.", "profile")

    # paese, città, raggio
    country = _text(payload.get("country"), "paese", "country", 10).lower() or "it"
    if country not in prof.COUNTRIES:
        raise OnboardingError("Paese sconosciuto.", "country")
    home = _text(payload.get("home"), "città", "home", 80)
    if home and not geomod.lookup(home, country):
        raise OnboardingError(f"Non trovo la città «{home}». Prova con il nome di una città più grande vicina, oppure lascia il campo vuoto.", "home")
    radius = _int(payload.get("radius_km"), 100, 1, 3000, "raggio", "radius_km")

    # profilo
    titles = pr.get("titles") or []
    if not isinstance(titles, list):
        raise OnboardingError("titoli: serve un elenco", "titles")
    if len([t for t in titles if isinstance(t, str) and t.strip()]) > MAX_TITLES:
        raise OnboardingError(f"Puoi scrivere al massimo {MAX_TITLES} lavori.", "titles")
    preset = pr.get("preset", "custom")
    name = pr.get("name")
    explicit_name = isinstance(name, str) and bool(name.strip())
    clean_titles = [t for t in titles if isinstance(t, str)]
    data = {"name": name if explicit_name else auto_name(preset if isinstance(preset, str) else "custom",
                                                       [t.strip() for t in clean_titles if t.strip()]),
            "preset": preset, "active": True, "titles": clean_titles, "countries": [country],
            "location": {"city": home, "radius_km": radius},
            "seniority": pr.get("seniority", "any"),
            "remote": pr.get("remote", True), "internships": pr.get("internships", True)}
    try:
        profile = prof.validate_profile(data)
    except prof.ProfileError as e:
        raise OnboardingError(str(e).capitalize() if str(e)[:1].islower() else str(e), "profile") from None

    # quale profilo si aggiorna: quello già creato dalla guida, oppure quello automatico mai toccato, altrimenti se ne crea uno
    pid = store.db.kv_get(KV_PROFILE)
    target = store.get(int(pid)) if pid and pid.isdigit() else None
    if target is None:
        target = untouched_default(store)
    if explicit_name and profile.name.isdigit():
        raise OnboardingError("Il nome non può essere solo un numero.", "profile")
    clash = store.get(profile.name) if not profile.name.isdigit() else None
    if clash is not None and (target is None or clash.id != target.id):
        if explicit_name:
            raise OnboardingError("Esiste già un profilo con questo nome: scegline un altro.", "profile")
        base, n = profile.name, 2
        while store.get(f"{base} {n}") is not None:
            n += 1
        profile.name = f"{base} {n}"
    profile.id = target.id if target else None

    notes: list[str] = []
    ov: dict = {"radius_km": radius, "search.internships": profile.internships, "home": home}  # casa vuota = nessuna casa

    # chiavi (facoltative)
    keys = payload.get("keys") or {}
    if not isinstance(keys, dict):
        raise OnboardingError("chiavi: formato non valido", "keys")
    az, jo = keys.get("adzuna") or {}, keys.get("jooble") or {}
    if not isinstance(az, dict) or not isinstance(jo, dict):
        raise OnboardingError("chiavi: formato non valido", "keys")
    aid, akey = _text(az.get("app_id"), "Application ID", "adzuna", 100), _text(az.get("app_key"), "Application Key", "adzuna", 100)
    if aid or akey:
        if not (aid and akey):
            raise OnboardingError("Per Adzuna servono sia l'Application ID sia l'Application Key.", "adzuna")
        if not KEY_OK.match(aid) or not KEY_OK.match(akey):
            raise OnboardingError("Le chiavi Adzuna contengono caratteri non validi: copiale di nuovo, senza spazi.", "adzuna")
        ov.update({"sources.adzuna.app_id": aid, "sources.adzuna.app_key": akey, "sources.adzuna.enabled": True})
    jhost, jkey = _text(jo.get("host"), "host Jooble", "jooble", 100).lower(), _text(jo.get("api_key"), "chiave Jooble", "jooble", 100)
    if jhost or jkey:
        if not (jhost and jkey):
            raise OnboardingError("Per Jooble servono sia l'host sia la chiave.", "jooble")
        if not JOOBLE_HOST_OK.match(jhost):
            raise OnboardingError("L'host di Jooble deve finire con jooble.org (esempio: it.jooble.org).", "jooble")
        if not KEY_OK.match(jkey):
            raise OnboardingError("La chiave Jooble contiene caratteri non validi: copiala di nuovo, senza spazi.", "jooble")
        ov.update({"sources.jooble.host": jhost, "sources.jooble.api_key": jkey, "sources.jooble.enabled": True})

    # cartella dei report (stessa pulizia di Impostazioni)
    rdir = _text(payload.get("report_dir"), "cartella dei report", "report_dir", 500)
    if rdir:
        try:
            settings.check_report_dir(rdir)
        except ValueError as e:
            raise OnboardingError(str(e), "report_dir") from None
        ov["report.dir"] = rdir

    # scansione automatica
    sched = payload.get("schedule")
    plan_sched = None
    if sched is not None:
        if not isinstance(sched, dict):
            raise OnboardingError("scansione automatica: formato non valido", "schedule")
        try:
            plan_sched = scheduler.parse_request(sched)
        except ValueError as e:
            raise OnboardingError(str(e).capitalize(), "schedule") from None
        if plan_sched["enabled"] and sys.platform != "darwin":
            plan_sched["enabled"] = False
            notes.append("La scansione automatica funziona solo su Mac: non l'ho attivata.")
        ov.update({"schedule.enabled": plan_sched["enabled"], "schedule.kind": plan_sched["kind"],
                   "schedule.times": scheduler.format_times(plan_sched["times"]), "schedule.hours": plan_sched["hours"],
                   "schedule.notify": plan_sched["notify"]})

    try:
        ov = settings.clean_values(ov)  # stessa validazione di Impostazioni
    except ValueError as e:
        raise OnboardingError(str(e)) from None
    # i segreti vuoti sono "invariati" per clean_values; qui non ce ne sono (sono già controllati sopra)
    return Plan(profile=profile, overrides=ov, country=country, schedule=plan_sched, notes=notes)


def estimate(plan: Plan, cfg: dict) -> dict:
    """Quante richieste farebbe la prima scansione con queste scelte (senza salvare niente)."""
    c = settings.apply_overrides(copy.deepcopy(cfg), plan.overrides)
    req = prof.estimate_requests([plan.profile], c)
    notes = list(plan.notes)
    srcs = c.get("sources", {})
    if not srcs.get("adzuna", {}).get("enabled"):
        notes.append("Senza la chiave Adzuna cerco solo nelle fonti gratuite: sono meno ricche, soprattutto per le città italiane.")
    elif not prof.COUNTRIES[plan.country]["adzuna"]:
        notes.append(f"{prof.COUNTRIES[plan.country]['name']}: Adzuna non copre questo paese.")
    if req.get("adzuna", 0) > 60:
        notes.append("Sono molte richieste ad Adzuna: se il sito le limita, riduci i titoli.")
    return {"requests": req, "total": sum(req.values()), "notes": notes}


def _snapshot(db, pid):
    """Copia della riga del profilo e dei suoi punteggi, per tornare indietro se un passo successivo fallisce."""
    row = db.conn.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone() if pid else None
    jp = db.conn.execute("SELECT * FROM job_profiles WHERE profile_id=?", (pid,)).fetchall() if pid else []
    return {"row": dict(row) if row else None, "jp": [dict(r) for r in jp], "kv": db.kv_get(KV_PROFILE)}


def _rollback_db(db, snap, pid) -> None:
    conn = db.conn
    conn.rollback()
    if pid is not None:
        conn.execute("DELETE FROM job_profiles WHERE profile_id=?", (pid,))
        if snap["row"] is None:
            conn.execute("DELETE FROM profiles WHERE id=?", (pid,))
        else:
            r = snap["row"]
            conn.execute("UPDATE profiles SET name=?, active=?, data=?, created=?, updated=? WHERE id=?",
                         (r["name"], r["active"], r["data"], r["created"], r["updated"], r["id"]))
            for j in snap["jp"]:
                cols = list(j)
                conn.execute(f"INSERT OR REPLACE INTO job_profiles ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                             [j[c] for c in cols])
    if snap["kv"] is None:
        conn.execute("DELETE FROM kv WHERE key=?", (KV_PROFILE,))
    else:
        conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (KV_PROFILE, snap["kv"]))
    conn.commit()
    db.refresh_best()


def apply(plan: Plan, cfg_file, db, cfg: dict, rescore_fn) -> int:
    """Scrive tutto: se qualcosa va storto impostazioni e profilo tornano come prima. Ritorna l'id del profilo."""
    store = prof.ProfileStore(db)
    snapshot = settings.load_overrides(cfg_file)
    snap = _snapshot(db, plan.profile.id)
    pid = plan.profile.id
    settings.save_overrides(cfg_file, plan.overrides)
    try:
        data = plan.profile.to_dict()
        p = store.update(plan.profile.id, data) if plan.profile.id else store.add(data)
        pid = p.id
        db.kv_set(KV_PROFILE, str(p.id))  # subito: un nuovo tentativo riconosce il profilo anche dopo un errore
        fresh = settings.load_config(cfg_file)
        cfg.clear()
        cfg.update(fresh)
        rescore_fn(db, cfg, [p.id])
    except Exception:
        settings.restore_overrides(cfg_file, snapshot)
        fresh = settings.load_config(cfg_file)
        cfg.clear()
        cfg.update(fresh)
        _rollback_db(db, snap, pid)
        raise
    return p.id
