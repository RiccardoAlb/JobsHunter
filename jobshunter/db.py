from __future__ import annotations

import os
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    uid        TEXT PRIMARY KEY,
    source     TEXT,
    title      TEXT,
    company    TEXT,
    location   TEXT,
    url        TEXT,
    description TEXT,
    posted_at  TEXT,
    remote     INTEGER,
    score      INTEGER,
    category   TEXT,
    matched    TEXT,
    status     TEXT DEFAULT 'new',   -- new | seen | applied | discarded
    notified   INTEGER DEFAULT 0,
    first_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_score ON jobs(score DESC);

CREATE TABLE IF NOT EXISTS dup_pairs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid_a      TEXT NOT NULL,
    uid_b      TEXT NOT NULL,
    pct        INTEGER,
    keep_uid   TEXT,
    hidden_uid TEXT,
    status     TEXT DEFAULT 'pending',   -- pending | confirmed | rejected
    auto       INTEGER DEFAULT 0,        -- 1 = confermato in automatico (100%), annullabile
    created    TEXT,
    decided_at TEXT,
    UNIQUE(uid_a, uid_b)
);

CREATE TABLE IF NOT EXISTS applications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uid    TEXT,                       -- annuncio di origine (vuoto se inserita a mano)
    company    TEXT NOT NULL,
    role       TEXT NOT NULL,
    location   TEXT DEFAULT '',
    url        TEXT DEFAULT '',
    applied_at TEXT,                       -- YYYY-MM-DD
    stage      TEXT DEFAULT 'sent',        -- sent | hr | tech | offer
    outcome    TEXT DEFAULT 'active',      -- active | accepted | rejected | withdrawn | no_response
    contact    TEXT DEFAULT '',
    notes      TEXT DEFAULT '',
    follow_up  TEXT,                       -- YYYY-MM-DD
    created    TEXT,
    updated    TEXT
);

CREATE TABLE IF NOT EXISTS app_events (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id INTEGER NOT NULL,
    kind   TEXT,                           -- created | stage | outcome
    value  TEXT,
    at     TEXT,                           -- YYYY-MM-DD
    note   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS profiles (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    active  INTEGER DEFAULT 1,             -- copia di data.active, serve alle interrogazioni SQL
    data    TEXT NOT NULL,                 -- JSON del profilo (vedi profiles.py)
    created TEXT,
    updated TEXT
);

CREATE TABLE IF NOT EXISTS job_profiles (
    job_uid    TEXT NOT NULL,
    profile_id INTEGER NOT NULL,
    score      INTEGER,
    category   TEXT,
    matched    TEXT,
    PRIMARY KEY (job_uid, profile_id)
);
CREATE INDEX IF NOT EXISTS idx_jp_profile ON job_profiles(profile_id);

CREATE TABLE IF NOT EXISTS cv_match (
    uid        TEXT PRIMARY KEY,
    score      INTEGER,                    -- affinita' col CV, 0-100
    base       TEXT,                       -- completo | anteprima
    explain    TEXT,                       -- JSON della spiegazione (solo nomi di competenze, mai il testo del CV)
    cv_version TEXT,                       -- impronta del CV elaborato (non il testo)
    sig        TEXT                        -- lunghezze dei testi dell'annuncio: se cambiano si ricalcola
);
CREATE INDEX IF NOT EXISTS idx_cvm_score ON cv_match(score);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started   TEXT,
    finished  TEXT,
    kind      TEXT,                        -- auto | manuale
    read      INTEGER DEFAULT 0,
    kept      INTEGER DEFAULT 0,
    new       INTEGER DEFAULT 0,
    closed    INTEGER DEFAULT 0,           -- annunci trovati chiusi dalla verifica
    dups      INTEGER DEFAULT 0,           -- nuove coppie di possibili duplicati
    cancelled INTEGER DEFAULT 0,
    blocked   INTEGER DEFAULT 0,           -- la verifica si e' fermata perche' il sito limitava le richieste
    errors    TEXT DEFAULT '',
    notified  INTEGER DEFAULT 0
);
"""

from .meta import CONTRACTS, MODES  # noqa: E402

STAGES = ("sent", "hr", "tech", "offer")
OUTCOMES = ("active", "accepted", "rejected", "withdrawn", "no_response")
APP_FIELDS = ("company", "role", "location", "url", "applied_at", "contact", "notes", "follow_up")

DUP_HIDDEN = "uid NOT IN (SELECT hidden_uid FROM dup_pairs WHERE status='confirmed')"
# annunci di un profilo spento non si vedono (finche' non lo si riaccende); quelli senza profilo si vedono sempre
PROFILE_ACTIVE = ("(uid IN (SELECT jp.job_uid FROM job_profiles jp JOIN profiles p ON p.id=jp.profile_id WHERE p.active=1) "
                  "OR uid NOT IN (SELECT job_uid FROM job_profiles))")
# di norma si nascondono i duplicati confermati e gli annunci verificati come chiusi
NOT_HIDDEN = DUP_HIDDEN + " AND avail!='closed' AND " + PROFILE_ACTIVE


class DB:
    def __init__(self, path: str | Path, cfg: dict | None = None):
        existed = str(path) == ":memory:" or Path(path).exists()
        self.conn = sqlite3.connect(path, timeout=30)  # scansione automatica e GUI possono scrivere insieme
        if not existed:
            try:
                os.chmod(path, 0o600)  # il database contiene candidature e testi: solo per l'utente
            except OSError:
                pass
        self.conn.row_factory = sqlite3.Row
        # alla prima apertura piu' processi o richieste possono prepararsi lo schema insieme: si riprova se e' occupato
        for attempt in range(60):
            try:
                self.conn.executescript(SCHEMA)
                self._migrate()
                self._migrate_profiles(cfg)
                break
            except sqlite3.OperationalError as e:
                if attempt == 59 or not ("locked" in str(e) or "busy" in str(e)):
                    raise
                self.conn.rollback()
                time.sleep(0.1)

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        for name, ddl in (("salary", "TEXT DEFAULT ''"), ("near_home", "INTEGER DEFAULT 0"),
                          ("full_text", "TEXT DEFAULT ''"), ("lat", "REAL"), ("lon", "REAL"),
                          ("geo", "INTEGER DEFAULT 0"),  # geo: 0 da fare, 1 trovata, 2 sede generica/ignota
                          ("city", "TEXT DEFAULT ''"), ("work_mode", "TEXT DEFAULT 'unknown'"),
                          ("sal_min", "INTEGER"), ("sal_max", "INTEGER"), ("meta", "INTEGER DEFAULT 0"),
                          ("company_key", "TEXT DEFAULT ''"),
                          ("contract", "TEXT DEFAULT 'unknown'"),
                          ("avail", "TEXT DEFAULT 'unknown'"),  # open | closed | unknown
                          ("avail_checked", "TEXT"), ("valid_until", "TEXT"), ("avail_note", "TEXT DEFAULT ''"),
                          ("sal_currency", "TEXT DEFAULT ''"),  # valuta della RAL (EUR, GBP...), '' se ignota
                          ("country", "TEXT DEFAULT ''")):  # codice paese di provenienza, quando noto
            if name not in cols:
                try:
                    self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")
                except sqlite3.OperationalError as e:  # un'altra connessione l'ha appena aggiunta (prima apertura concorrente)
                    if "duplicate column" not in str(e):
                        raise
        self.conn.commit()

    def _migrate_profiles(self, cfg: dict | None = None) -> None:
        """Se non c'e' nessun profilo crea "Cybersecurity" dal config e vi associa tutti gli annunci esistenti.

        E' idempotente e a prova di corsa (GUI e scansione automatica che aprono il DB insieme): l'inserimento
        avviene solo se la tabella e' ancora vuota. I punteggi esistenti si copiano senza ricalcolarli."""
        import json

        if self.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]:
            return
        if cfg is None:
            try:
                from . import settings

                cfg = settings.load_config()
            except Exception:  # config assente o illeggibile: valgono i predefiniti del preset
                cfg = None
        from .profiles import default_cyber_profile, now_iso

        data = default_cyber_profile(cfg)
        now = now_iso()
        try:
            cur = self.conn.execute(
                "INSERT INTO profiles (name, active, data, created, updated) "
                "SELECT ?,1,?,?,? WHERE NOT EXISTS (SELECT 1 FROM profiles)",
                (data["name"], json.dumps(data, ensure_ascii=False), now, now))
        except sqlite3.IntegrityError:  # un'altra connessione l'ha appena creato: va bene cosi'
            self.conn.rollback()
            return
        if cur.rowcount:
            self.conn.execute(
                "INSERT OR IGNORE INTO job_profiles (job_uid, profile_id, score, category, matched) "
                "SELECT uid, ?, score, category, matched FROM jobs", (cur.lastrowid,))
        self.conn.commit()

    # ---- punteggi per profilo ----
    def set_job_profile(self, uid: str, profile_id: int, score: int, category: str, matched) -> None:
        m = ",".join(matched) if isinstance(matched, (list, tuple, set)) else (matched or "")
        self.conn.execute("INSERT OR REPLACE INTO job_profiles (job_uid, profile_id, score, category, matched) "
                          "VALUES (?,?,?,?,?)", (uid, profile_id, score, category, m))

    def refresh_best(self, uids: list[str] | None = None) -> int:
        """jobs.score/category/matched = valori del profilo ATTIVO col punteggio piu' alto (a parita' il primo creato).

        Gli annunci senza alcun profilo attivo restano come sono. Ritorna quanti annunci ha aggiornato."""
        sql = ("SELECT jp.job_uid, jp.score, jp.category, jp.matched FROM job_profiles jp "
               "JOIN profiles p ON p.id=jp.profile_id AND p.active=1")
        args: list = []
        if uids is not None:
            if not uids:
                return 0
            sql += f" WHERE jp.job_uid IN ({','.join('?' * len(uids))})"
            args = list(uids)
        best: dict[str, tuple] = {}
        for r in self.conn.execute(sql + " ORDER BY jp.score DESC, jp.profile_id ASC", args):
            best.setdefault(r["job_uid"], (r["score"], r["category"], r["matched"]))
        self.conn.executemany("UPDATE jobs SET score=?, category=?, matched=? WHERE uid=? "
                              "AND (score IS NOT ? OR category IS NOT ? OR matched IS NOT ?)",
                              [(*v, u, *v) for u, v in best.items()])
        self.conn.commit()
        return len(best)

    def drop_orphans(self) -> int:
        """Toglie le righe di job_profiles di profili che non esistono piu' (es. eliminati durante una scansione)."""
        n = self.conn.execute("DELETE FROM job_profiles WHERE profile_id NOT IN (SELECT id FROM profiles)").rowcount
        self.conn.commit()
        return n

    def profiles_of(self, uids: list[str]) -> dict[str, list[dict]]:
        """Per ogni annuncio i profili che lo hanno valutato: [{id, name, score}], il migliore per primo."""
        if not uids:
            return {}
        out: dict[str, list[dict]] = {}
        q = ("SELECT jp.job_uid u, p.id id, p.name name, jp.score score FROM job_profiles jp "
             f"JOIN profiles p ON p.id=jp.profile_id WHERE jp.job_uid IN ({','.join('?' * len(uids))}) "
             "ORDER BY jp.score DESC, p.id")
        for r in self.conn.execute(q, uids):
            out.setdefault(r["u"], []).append({"id": r["id"], "name": r["name"], "score": r["score"]})
        return out

    def _from(self, profile) -> tuple[str, list]:
        """Clausola FROM: tutti gli annunci, oppure quelli di UN profilo col punteggio di quel profilo."""
        if profile in (None, "", "all"):
            return "FROM jobs", []
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(jobs)") if r["name"] not in ("score", "category", "matched")]
        sel = ", ".join(f"jobs.{c}" for c in cols)
        return (f"FROM (SELECT {sel}, jp.score AS score, jp.category AS category, jp.matched AS matched FROM jobs "
                "JOIN job_profiles jp ON jp.job_uid=jobs.uid AND jp.profile_id=?) AS jobs"), [int(profile)]

    def upsert(self, job: Job) -> bool:
        """Inserisce l'annuncio. True se e' nuovo."""
        exists = self.conn.execute("SELECT 1 FROM jobs WHERE uid=?", (job.uid,)).fetchone()
        if exists:
            self.conn.execute(
                "UPDATE jobs SET score=?, category=?, matched=?, near_home=MAX(near_home, ?), "
                "salary=COALESCE(NULLIF(?, ''), salary), country=COALESCE(NULLIF(country, ''), ?) WHERE uid=?",
                (job.score, job.category, ",".join(job.matched), int(job.near_home), job.salary, job.country, job.uid),
            )
            return False
        self.conn.execute(
            "INSERT INTO jobs (uid,source,title,company,location,url,description,posted_at,"
            "remote,score,category,matched,first_seen,salary,near_home,country) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job.uid, job.source, job.title, job.company, job.location, job.url,
                job.description[:5000], job.posted_at.isoformat() if job.posted_at else None,
                int(job.remote), job.score, job.category, ",".join(job.matched),
                datetime.now(timezone.utc).isoformat(), job.salary, int(job.near_home), job.country,
            ),
        )
        return True

    def commit(self) -> None:
        self.conn.commit()

    def query(self, *, category: str | None = None, min_score: int = 0,
              status: str | None = None, limit: int = 30, search: str | None = None,
              near_only: bool = False, only_new: bool = False, group: str | None = None,
              geo: tuple | None = None, company: str | None = None, cities: list[str] | None = None,
              modes: list[str] | None = None, ral_min: int = 0, ral_unknown: bool = True,
              include_closed: bool = False, contracts: list[str] | None = None,
              profile=None, ral_currency: str = "EUR", country: str | None = None,
              cv_min: int = 0, cv_version: str | None = None, order_cv: bool = False):
        self.backfill_meta()  # dati derivati (RAL, modalita', citta') mancanti o da rivalutare
        src, src_args = self._from(profile)
        sql, args = (f"SELECT * {src} WHERE score>=? AND {DUP_HIDDEN if include_closed else NOT_HIDDEN}"), src_args + [min_score]
        if country:
            sql += " AND country=?"
            args.append(country.lower())
        if company:  # confronto sul nome normalizzato: "Exprivia" trova anche "Exprivia S.p.A."
            from .dedupe import norm_company

            sql += " AND company_key LIKE ?"
            args.append(f"%{norm_company(company)}%")
        if cities:  # "" = sede generica (Italia, Remote, una regione)
            labels, parts = [c for c in cities if c], []
            if labels:
                parts.append(f"city COLLATE NOCASE IN ({','.join('?' * len(labels))})")
                args += labels
            if "" in cities:
                parts.append("city=''")
            sql += " AND (" + " OR ".join(parts) + ")"
        if modes:
            valid = [m for m in modes if m in MODES]
            if valid:
                sql += f" AND work_mode IN ({','.join('?' * len(valid))})"
                args += valid
        if contracts:
            valid = [c for c in contracts if c in CONTRACTS]
            if valid:
                sql += f" AND contract IN ({','.join('?' * len(valid))})"
                args += valid
        if ral_min and ral_min > 0:
            # la RAL minima vale solo per importi nella valuta del profilo; gli altri contano come "RAL sconosciuta"
            sql += " AND ((sal_max >= ? AND (sal_currency=? OR sal_currency=''))"
            args += [int(ral_min), ral_currency]
            if ral_unknown:
                sql += " OR sal_max IS NULL OR (sal_currency!=? AND sal_currency!='')"
                args.append(ral_currency)
            sql += ")"
        if group == "jooble":
            sql += " AND source LIKE 'jooble%'"
        elif group == "main":
            sql += " AND source NOT LIKE 'jooble%'"
        if cv_min and cv_min > 0 and cv_version:  # solo annunci con un confronto aggiornato al CV attuale
            sql += " AND jobs.uid IN (SELECT uid FROM cv_match WHERE cv_version=? AND score>=?)"
            args += [cv_version, int(cv_min)]
        if near_only:
            sql += " AND near_home=1"
        if only_new:
            sql += " AND status='new'"
        if category:
            sql += " AND category=?"
            args.append(category.upper())
        if status:
            sql += " AND status=?"
            args.append(status)
        else:
            sql += " AND status!='discarded'"
        if search:
            sql += " AND (title LIKE ? OR company LIKE ?)"
            args += [f"%{search}%"] * 2
        if order_cv and cv_version:  # prima l'affinita' col CV, poi il punteggio di sempre
            sql += (" ORDER BY (SELECT score FROM cv_match m WHERE m.uid=jobs.uid AND m.cv_version=?) IS NULL,"
                    " (SELECT score FROM cv_match m WHERE m.uid=jobs.uid AND m.cv_version=?) DESC, score DESC, first_seen DESC")
            args += [cv_version, cv_version]
        else:
            sql += " ORDER BY score DESC, first_seen DESC"
        if geo is None:
            sql += " LIMIT ?"
            return self.conn.execute(sql, args + [limit]).fetchall()
        self.backfill_geo()  # prima di leggere le righe, altrimenti risultano senza coordinate
        return self._within(self.conn.execute(sql, args).fetchall(), geo)[:limit]

    def _within(self, rows, geo):
        """Filtro per raggio. geo = (lat, lon, km, includi_sede_generica). Aggiunge 'km' a ogni riga."""
        from .geo import distance_km

        lat0, lon0, radius, keep_unknown = geo
        out = []
        for r in rows:
            d = dict(r)
            if d["geo"] == 1 and d["lat"] is not None:
                d["km"] = round(distance_km(lat0, lon0, d["lat"], d["lon"]))
                if d["km"] <= radius:
                    out.append(d)
            elif keep_unknown:
                d["km"] = None
                out.append(d)
        return out

    def backfill_geo(self) -> int:
        """Calcola le coordinate degli annunci che non le hanno ancora. Ritorna quanti ne ha aggiornati."""
        todo = self.conn.execute("SELECT uid, location, country FROM jobs WHERE geo=0").fetchall()
        if not todo:
            return 0
        from .geo import locate

        for r in todo:
            pos = locate(r["location"], r["country"] or None)
            self.conn.execute("UPDATE jobs SET lat=?, lon=?, geo=? WHERE uid=?",
                              (pos[0] if pos else None, pos[1] if pos else None, 1 if pos else 2, r["uid"]))
        self.conn.commit()
        return len(todo)

    # ---- chiave/valore, cronologia scansioni, novita' ----
    def kv_get(self, key: str, default=None):
        r = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def kv_set(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, value))
        self.conn.commit()

    def add_scan_run(self, **f) -> int:
        cols = ("started", "finished", "kind", "read", "kept", "new", "closed", "dups", "cancelled", "blocked", "errors", "notified")
        cur = self.conn.execute(f"INSERT INTO scan_runs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                                [f.get(c, 0 if c not in ("started", "finished", "kind", "errors") else "") for c in cols])
        self.conn.commit()
        return cur.lastrowid

    def recent_scans(self, limit: int = 10):
        return self.conn.execute("SELECT * FROM scan_runs ORDER BY started DESC, id DESC LIMIT ?", (limit,)).fetchall()

    def new_since(self, ts: str, limit: int = 50):
        """Annunci visibili comparsi dopo `ts` (ISO UTC), i migliori per primi."""
        return self.conn.execute(
            f"SELECT * FROM jobs WHERE first_seen>=? AND status!='discarded' AND {NOT_HIDDEN} ORDER BY score DESC, first_seen DESC LIMIT ?",
            (ts, limit)).fetchall()

    def news_since(self, ts: str) -> dict:
        """Cosa e' cambiato dopo `ts`: nuovi annunci, annunci scoperti chiusi, nuovi possibili duplicati."""
        q = self.conn.execute
        new = q(f"SELECT COUNT(*) FROM jobs WHERE first_seen>? AND status!='discarded' AND {NOT_HIDDEN}", (ts,)).fetchone()[0]
        closed = q(f"SELECT COUNT(*) FROM jobs WHERE avail='closed' AND avail_checked>? AND status!='discarded' AND {DUP_HIDDEN}", (ts,)).fetchone()[0]
        dups = q("SELECT COUNT(*) FROM dup_pairs WHERE status='pending' AND created>?", (ts,)).fetchone()[0]
        return {"new": new, "closed": closed, "dups": dups}

    # ---- disponibilita' dell'annuncio ----
    def set_avail(self, uid: str, state: str, valid_until: str | None, note: str) -> None:
        self.conn.execute("UPDATE jobs SET avail=?, avail_checked=?, valid_until=COALESCE(?, valid_until), avail_note=? WHERE uid=?",
                          (state, datetime.now(timezone.utc).isoformat(), valid_until, note, uid))
        self.conn.commit()

    def to_check(self, *, hours: float = 24, limit: int = 30, uids: list[str] | None = None, force: bool = False):
        """Annunci da verificare: verificabili, non scartati, mai controllati o controllati da piu' di `hours` ore.

        Con `uids` si controllano solo quelli indicati; con `force` anche i recenti e quelli gia' chiusi."""
        from datetime import timedelta

        sql = f"SELECT * FROM jobs WHERE source NOT LIKE 'jooble%' AND url!='' AND status!='discarded' AND {DUP_HIDDEN}"
        args: list = []
        if uids is not None:
            sql += f" AND uid IN ({','.join('?' * len(uids))})" if uids else " AND 0"
            args += uids
        if not force:
            sql += " AND avail!='closed' AND (avail_checked IS NULL OR avail_checked<?)"
            args.append((datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat())
        sql += " ORDER BY score DESC, first_seen DESC LIMIT ?"
        return self.conn.execute(sql, args + [limit]).fetchall()

    def closed_count(self) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM jobs WHERE avail='closed' AND status!='discarded' AND {DUP_HIDDEN}").fetchone()[0]

    def _meta_for(self, r) -> tuple:
        from .dedupe import norm_company
        from .meta import city_of, detect_contract, detect_mode, parse_salary_ex

        text = r["full_text"] or r["description"] or ""
        sal = parse_salary_ex(r["salary"])
        mode = detect_mode(r["title"], r["location"], text, bool(r["remote"]))
        return (city_of(r["location"]), mode, sal[0] if sal else None, sal[1] if sal else None,
                norm_company(r["company"]), detect_contract(r["title"], text), sal[2] if sal else "")

    def backfill_meta(self) -> int:
        """Calcola RAL annua, modalita' di lavoro e citta' degli annunci che non li hanno (o con regole piu' vecchie)."""
        from .meta import META_VERSION

        todo = self.conn.execute("SELECT uid, title, company, location, description, full_text, salary, remote FROM jobs "
                                 "WHERE meta<?", (META_VERSION,)).fetchall()
        for r in todo:
            city, mode, lo, hi, key, contract, cur = self._meta_for(r)
            self.conn.execute("UPDATE jobs SET city=?, work_mode=?, sal_min=?, sal_max=?, company_key=?, contract=?, "
                              "sal_currency=?, meta=? WHERE uid=?",
                              (city, mode, lo, hi, key, contract, cur, META_VERSION, r["uid"]))
        if todo:
            self.conn.commit()
        return len(todo)

    def _company_facet(self, base: str) -> list[dict]:
        groups: dict[str, dict] = {}
        for r in self.conn.execute(f"SELECT company_key k, company c, COUNT(*) n {base} GROUP BY company_key, company"):
            g = groups.setdefault(r["k"], {"name": r["c"], "n": 0})
            g["n"] += r["n"]
            if len(r["c"]) < len(g["name"]):  # nome mostrato: il piu' corto del gruppo ("Exprivia" e non "Exprivia S.p.A.")
                g["name"] = r["c"]
        return sorted(groups.values(), key=lambda g: (-g["n"], g["name"].lower()))[:400]

    def facets(self, group: str | None = None, profile=None) -> dict:
        """Valori disponibili per i filtri (con quanti annunci ciascuno), sugli annunci visibili."""
        self.backfill_meta()
        src, src_args = self._from(profile)
        base = f"{src} WHERE status!='discarded' AND {NOT_HIDDEN}"
        if src_args:  # il profilo e' un parametro della sottointerrogazione: lo si incorpora (e' un intero)
            base = base.replace("jp.profile_id=?", f"jp.profile_id={int(src_args[0])}")
        if group == "jooble":
            base += " AND source LIKE 'jooble%'"
        elif group == "main":
            base += " AND source NOT LIKE 'jooble%'"
        q = self.conn.execute
        sal = q(f"SELECT COUNT(*) total, SUM(sal_max IS NOT NULL) known, MIN(sal_min) lo, MAX(sal_max) hi {base}").fetchone()
        return {
            "companies": self._company_facet(base),
            "cities": [{"name": r[0], "n": r[1]} for r in q(f"SELECT city, COUNT(*) n {base} AND city!='' GROUP BY city ORDER BY n DESC LIMIT 60")],
            "generic": q(f"SELECT COUNT(*) {base} AND city=''").fetchone()[0],
            "modes": {r[0]: r[1] for r in q(f"SELECT work_mode, COUNT(*) {base} GROUP BY work_mode")},
            "contracts": {r[0]: r[1] for r in q(f"SELECT contract, COUNT(*) {base} GROUP BY contract")},
            "countries": {r[0]: r[1] for r in q(f"SELECT country, COUNT(*) {base} AND country!='' GROUP BY country")},
            "salary": {"total": sal["total"], "known": sal["known"] or 0, "min": sal["lo"], "max": sal["hi"]},
        }

    def get(self, prefix: str):
        rows = self.conn.execute("SELECT * FROM jobs WHERE uid LIKE ?", (prefix + "%",)).fetchall()
        return rows[0] if len(rows) == 1 else None

    def set_full_text(self, uid: str, text: str, salary: str = "") -> None:
        self.conn.execute(
            "UPDATE jobs SET full_text=?, salary=COALESCE(NULLIF(?, ''), salary), meta=0 WHERE uid=?",
            (text, salary, uid),
        )
        self.conn.commit()  # meta=0: RAL e modalita' si rivalutano col testo completo

    def set_status(self, uid: str, status: str) -> None:
        self.conn.execute("UPDATE jobs SET status=? WHERE uid=?", (status, uid))
        self.conn.commit()
        if status == "applied":
            self.ensure_application(uid)

    # ---- candidature ----
    def _event(self, app_id: int, kind: str, value: str, at: str | None, note: str = "") -> None:
        self.conn.execute("INSERT INTO app_events (app_id, kind, value, at, note) VALUES (?,?,?,?,?)",
                          (app_id, kind, value, at or date.today().isoformat(), note))

    def add_application(self, *, company: str, role: str, location: str = "", url: str = "",
                        applied_at: str | None = None, notes: str = "", contact: str = "",
                        follow_up: str | None = None, job_uid: str | None = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        day = applied_at or date.today().isoformat()
        cur = self.conn.execute(
            "INSERT INTO applications (job_uid, company, role, location, url, applied_at, notes, contact, follow_up, created, updated) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (job_uid, company, role, location, url, day, notes, contact, follow_up, now, now))
        self._event(cur.lastrowid, "created", "sent", day)
        self.conn.commit()
        return cur.lastrowid

    def ensure_application(self, job_uid: str) -> int | None:
        """Crea la candidatura per un annuncio segnato 'applied', se non esiste gia'."""
        if self.conn.execute("SELECT 1 FROM applications WHERE job_uid=?", (job_uid,)).fetchone():
            return None
        j = self.conn.execute("SELECT * FROM jobs WHERE uid=?", (job_uid,)).fetchone()
        if not j:
            return None
        return self.add_application(company=j["company"], role=j["title"], location=j["location"] or "",
                                    url=j["url"] or "", job_uid=job_uid)

    def list_applications(self, outcome: str = "active"):
        sql = "SELECT * FROM applications"
        if outcome == "active":
            sql += " WHERE outcome='active'"
        elif outcome == "closed":
            sql += " WHERE outcome!='active'"
        rows = self.conn.execute(sql + " ORDER BY updated DESC, id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["events"] = [dict(e) for e in self.conn.execute(
                "SELECT kind, value, at, note FROM app_events WHERE app_id=? ORDER BY id", (r["id"],))]
            out.append(d)
        return out

    def app_counts(self) -> dict:
        r = self.conn.execute("SELECT COALESCE(SUM(outcome='active'),0) a, COALESCE(SUM(outcome!='active'),0) c FROM applications").fetchone()
        return {"active": r["a"], "closed": r["c"]}

    def _touch(self, app_id: int) -> None:
        self.conn.execute("UPDATE applications SET updated=? WHERE id=?",
                          (datetime.now(timezone.utc).isoformat(), app_id))

    def update_application(self, app_id: int, **fields) -> bool:
        if not self.conn.execute("SELECT 1 FROM applications WHERE id=?", (app_id,)).fetchone():
            return False
        for k, v in fields.items():
            if k in APP_FIELDS:
                self.conn.execute(f"UPDATE applications SET {k}=? WHERE id=?", (v, app_id))
        self._touch(app_id)
        self.conn.commit()
        return True

    def set_app_stage(self, app_id: int, stage: str, at: str | None = None, note: str = "") -> bool:
        row = self.conn.execute("SELECT stage FROM applications WHERE id=?", (app_id,)).fetchone()
        if not row or stage not in STAGES:
            return False
        if row["stage"] != stage:  # niente evento se la tappa non cambia
            self.conn.execute("UPDATE applications SET stage=? WHERE id=?", (stage, app_id))
            self._event(app_id, "stage", stage, at, note)
            self._touch(app_id)
            self.conn.commit()
        return True

    def set_app_outcome(self, app_id: int, outcome: str, at: str | None = None, note: str = "") -> bool:
        row = self.conn.execute("SELECT outcome FROM applications WHERE id=?", (app_id,)).fetchone()
        if not row or outcome not in OUTCOMES:
            return False
        if row["outcome"] != outcome:
            self.conn.execute("UPDATE applications SET outcome=? WHERE id=?", (outcome, app_id))
            self._event(app_id, "outcome", outcome, at, note)
            self._touch(app_id)
            self.conn.commit()
        return True

    def delete_application(self, app_id: int) -> bool:
        if not self.conn.execute("SELECT 1 FROM applications WHERE id=?", (app_id,)).fetchone():
            return False
        self.conn.execute("DELETE FROM app_events WHERE app_id=?", (app_id,))
        self.conn.execute("DELETE FROM applications WHERE id=?", (app_id,))
        self.conn.commit()
        return True

    def unnotified(self, min_score: int):
        return self.conn.execute(
            f"SELECT * FROM jobs WHERE notified=0 AND score>=? AND status='new' AND {NOT_HIDDEN} ORDER BY score DESC",
            (min_score,),
        ).fetchall()

    def mark_notified(self, uids: list[str]) -> None:
        self.conn.executemany("UPDATE jobs SET notified=1 WHERE uid=?", [(u,) for u in uids])
        self.conn.commit()

    # ---- duplicati ----
    def upsert_dup(self, uid_a, uid_b, pct, keep, hidden, auto=False) -> bool:
        """Salva una coppia candidata. Non tocca mai una decisione gia' presa. True se nuova."""
        a, b = sorted((uid_a, uid_b))
        row = self.conn.execute("SELECT id, status FROM dup_pairs WHERE uid_a=? AND uid_b=?", (a, b)).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        if row:
            if row["status"] == "pending":  # le coppie gia' decise non si toccano mai
                self.conn.execute("UPDATE dup_pairs SET pct=?, keep_uid=?, hidden_uid=? WHERE id=?",
                                  (pct, keep, hidden, row["id"]))
            return False
        self.conn.execute(
            "INSERT INTO dup_pairs (uid_a,uid_b,pct,keep_uid,hidden_uid,status,auto,created,decided_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (a, b, pct, keep, hidden, "confirmed" if auto else "pending", int(auto), now, now if auto else None),
        )
        return True

    def list_dups(self, status: str):
        return self.conn.execute(
            "SELECT p.*, "
            " a.title a_title, a.company a_company, a.location a_location, a.url a_url, a.source a_source, "
            " a.salary a_salary, a.score a_score, a.status a_status, a.category a_category, a.posted_at a_posted, "
            " b.title b_title, b.company b_company, b.location b_location, b.url b_url, b.source b_source, "
            " b.salary b_salary, b.score b_score, b.status b_status, b.category b_category, b.posted_at b_posted "
            "FROM dup_pairs p JOIN jobs a ON a.uid=p.uid_a JOIN jobs b ON b.uid=p.uid_b "
            "WHERE p.status=? ORDER BY p.pct DESC, p.id DESC", (status,)
        ).fetchall()

    def set_dup_status(self, pair_id: int, status: str, swap: bool = False) -> bool:
        row = self.conn.execute("SELECT * FROM dup_pairs WHERE id=?", (pair_id,)).fetchone()
        if not row:
            return False
        keep, hidden = row["keep_uid"], row["hidden_uid"]
        if swap:
            keep, hidden = hidden, keep
        decided = datetime.now(timezone.utc).isoformat() if status != "pending" else None
        self.conn.execute(
            "UPDATE dup_pairs SET status=?, keep_uid=?, hidden_uid=?, decided_at=?, auto=0 WHERE id=?",
            (status, keep, hidden, decided, pair_id),
        )
        self.conn.commit()
        return True

    def dup_counts(self) -> dict:
        rows = self.conn.execute("SELECT status, COUNT(*) n FROM dup_pairs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    def stats(self, profile=None):
        src, src_args = self._from(profile)
        return self.conn.execute(
            "SELECT category, COUNT(*) n, ROUND(AVG(score),1) avg, MAX(score) top "
            f"{src} WHERE status!='discarded' AND {NOT_HIDDEN} GROUP BY category ORDER BY n DESC", src_args
        ).fetchall()
