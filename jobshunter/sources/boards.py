"""Fonti basate su API JSON pubbliche (nessuna chiave richiesta)."""
from __future__ import annotations

from .. import net
from ..models import Job, strip_html
from .base import Source, client, parse_dt  # noqa: F401  (client resta importabile da qui per i test)


class Arbeitnow(Source):
    name = "arbeitnow"

    def fetch(self) -> list[Job]:
        jobs = []
        with self.http() as c:
            for page in (1, 2, 3):
                self.check()
                r = c.get("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
                net.ensure_ok(r)
                for j in r.json().get("data", []):
                    jobs.append(Job(
                        source=self.name, title=j["title"], company=j["company_name"],
                        location=j.get("location", ""), url=j["url"],
                        description=strip_html(j.get("description", "")),
                        posted_at=parse_dt(j.get("created_at")), remote=bool(j.get("remote")),
                        country="de",
                    ))
        return jobs


class RemoteOK(Source):
    name = "remoteok"

    def fetch(self) -> list[Job]:
        with self.http() as c:
            r = c.get("https://remoteok.com/api")
            net.ensure_ok(r)
        return [
            Job(
                source=self.name, title=j["position"], company=j.get("company", ""),
                location=j.get("location") or "Remote", url=j["url"],
                description=strip_html(j.get("description", "")) + " " + " ".join(j.get("tags", [])),
                posted_at=parse_dt(j.get("date")), remote=True,
            )
            for j in r.json() if isinstance(j, dict) and j.get("position")
        ]


class Remotive(Source):
    name = "remotive"

    def fetch(self) -> list[Job]:
        return self._search(self.cfg.get("queries", ["security"]))

    def fetch_queries(self, queries: list) -> list[Job]:
        """Cerca le parole dei profili (al massimo 6 ricerche diverse): è una fonte solo di lavoro da remoto."""
        words: list[str] = []
        for q in queries:
            if q.q.lower() not in words:
                words.append(q.q.lower())
        return self._search(words[:6])

    def _search(self, terms: list[str]) -> list[Job]:
        jobs, seen = [], set()
        with self.http() as c:
            for q in terms:
                self.check()
                r = c.get("https://remotive.com/api/remote-jobs", params={"search": q})
                net.ensure_ok(r)
                for j in r.json().get("jobs", []):
                    if j["id"] in seen:
                        continue
                    seen.add(j["id"])
                    jobs.append(Job(
                        source=self.name, title=j["title"], company=j["company_name"],
                        location=j.get("candidate_required_location", "Remote"), url=j["url"],
                        description=strip_html(j.get("description", "")),
                        posted_at=parse_dt(j.get("publication_date")), remote=True,
                    ))
        return jobs


class Greenhouse(Source):
    name = "greenhouse"

    def fetch(self) -> list[Job]:
        jobs = []
        with self.http() as c:
            for board in self.cfg.get("boards", []):
                self.check()
                r = c.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
                if r.status_code != 200:
                    continue
                for j in r.json().get("jobs", []):
                    loc = (j.get("location") or {}).get("name", "")
                    jobs.append(Job(
                        source=f"gh:{board}", title=j["title"], company=board.capitalize(),
                        location=loc, url=j["absolute_url"], posted_at=parse_dt(j.get("updated_at")),
                        remote="remote" in loc.lower(),
                    ))
        return jobs


class Lever(Source):
    name = "lever"

    def fetch(self) -> list[Job]:
        jobs = []
        with self.http() as c:
            for comp in self.cfg.get("companies", []):
                self.check()
                r = c.get(f"https://api.lever.co/v0/postings/{comp}", params={"mode": "json"})
                if r.status_code != 200:
                    continue
                for j in r.json():
                    cats = j.get("categories", {})
                    loc = cats.get("location", "") or ""
                    jobs.append(Job(
                        source=f"lever:{comp}", title=j["text"], company=comp.capitalize(),
                        location=loc, url=j["hostedUrl"],
                        description=j.get("descriptionPlain", ""),
                        posted_at=parse_dt(j.get("createdAt")),
                        remote="remote" in loc.lower() or j.get("workplaceType") == "remote",
                    ))
        return jobs


def _legacy_queries(cfg: dict, country: str, default: list[str], source: "Source") -> list:
    """Le ricerche storiche di una sola fonte (config.toml): citta' di casa piu' tutto il paese."""
    from ..profiles import Query

    home, radius = cfg.get("home", ""), cfg.get("radius_km", 100)
    passes = ([(home, radius)] if home else []) + [("", None)]
    out = []
    for where, dist in passes:
        for q, pages in source.queries_with_pages(default, (1, 2)):
            out.append(Query(q, country, where, dist, tuple(pages)))
    return out


class Adzuna(Source):
    """Adzuna, per tutti i paesi che offre. Chiave gratuita su https://developer.adzuna.com (o env ADZUNA_APP_ID / ADZUNA_APP_KEY).

    La stessa chiave vale per ogni paese (`/jobs/{paese}/search/{pagina}`). Per ogni ricerca con una citta' si
    legge nel raggio indicato e quegli annunci risultano "vicini"; le ricerche senza citta' coprono tutto il paese.
    Al primo rifiuto del sito (403 o 429) la fonte si ferma: insistere peggiora il blocco."""
    name = "adzuna"

    def fetch(self) -> list[Job]:
        country = self.cfg.get("country", "it")
        return self.fetch_queries(_legacy_queries(self.cfg, country, ["cyber security"], self))

    def fetch_queries(self, queries: list) -> list[Job]:
        import os

        from ..profiles import COUNTRIES

        app_id = self.cfg.get("app_id") or os.environ.get("ADZUNA_APP_ID")
        app_key = self.cfg.get("app_key") or os.environ.get("ADZUNA_APP_KEY")
        if not (app_id and app_key):
            raise RuntimeError("chiavi Adzuna mancanti (config o env)")
        jobs: dict[tuple, Job] = {}
        with self.http() as c:
            for q in queries:
                info = COUNTRIES.get(q.country)
                if not info or not info.get("adzuna"):
                    continue
                for page in q.pages:
                    self.check()
                    self.pause()
                    params = {"app_id": app_id, "app_key": app_key, "what": q.q,
                              "results_per_page": 50, "max_days_old": 30, "sort_by": "date"}
                    if q.where:
                        params.update(where=q.where, distance=q.radius_km or 100)
                    r = c.get(f"https://api.adzuna.com/v1/api/jobs/{q.country}/search/{page}", params=params)
                    if r.status_code in (403, 429):
                        raise RuntimeError("Adzuna ha limitato le richieste (HTTP %d): riprova più tardi, senza insistere" % r.status_code)
                    net.ensure_ok(r)
                    near = bool(q.where)
                    for j in r.json().get("results", []):
                        key = (q.country, j["id"])
                        if key in jobs:
                            jobs[key].near_home |= near
                            if near:
                                jobs[key].near_where.add(q.where.lower())
                            continue
                        lo, hi = j.get("salary_min"), j.get("salary_max")
                        salary, cur = "", info["currency"]
                        if lo and lo >= 1000:  # valori anomali dell'API vengono ignorati
                            salary = f"{lo:,.0f}-{hi:,.0f} {cur}" if hi and hi > lo else f"{lo:,.0f} {cur}"
                        jobs[key] = Job(
                            source=self.name, title=j["title"],
                            company=(j.get("company") or {}).get("display_name", ""),
                            location=(j.get("location") or {}).get("display_name", ""),
                            url=j["redirect_url"], description=strip_html(j.get("description", "")),
                            posted_at=parse_dt(j.get("created")), salary=salary, near_home=near,
                            country=q.country, near_where={q.where.lower()} if near else set(),
                        )
        return list(jobs.values())


def jooble_hosts(cfg: dict) -> dict[str, str]:
    """Mappa paese -> host Jooble. La chiave Jooble vale solo per il proprio host, quindi i paesi senza host sono saltati.

    Si usa `hosts` (es. {"it": "it.jooble.org"}). Anche il singolo `host` vale, per il paese indicato dal suo prefisso
    (uk = gb; "jooble.org" senza prefisso = us), così l'host scelto nella guida non viene ignorato se esiste `hosts`;
    per lo stesso paese vince `hosts`."""
    hosts = {str(k).lower(): str(v) for k, v in (cfg.get("hosts") or {}).items() if v}
    host = cfg.get("host")
    if host or not hosts:
        host = str(host or "it.jooble.org")
        prefix = host.split(".")[0].lower()
        country = {"uk": "gb", "jooble": "us"}.get(prefix, prefix if len(prefix) == 2 else "it")
        hosts.setdefault(country, host)
    return hosts


class Jooble(Source):
    """Aggregatore con API gratuita. Chiave: https://jooble.org/api/about (o env JOOBLE_API_KEY)."""
    name = "jooble"

    @staticmethod
    def to_job(j: dict, near: bool, country: str = "") -> Job:
        return Job(
            source="jooble" + (f":{j['source']}" if j.get("source") else ""),
            title=strip_html(j.get("title", "")), company=j.get("company", ""),
            location=j.get("location", ""), url=j.get("link", ""),
            description=strip_html(j.get("snippet", "")),
            posted_at=parse_dt(j.get("updated")), salary=(j.get("salary") or "").strip(),
            near_home=near, country=country,
        )

    def fetch(self) -> list[Job]:
        hosts = jooble_hosts(self.cfg)
        country = next(iter(hosts))
        return self.fetch_queries(_legacy_queries(self.cfg, country, ["cyber security"], self))

    def fetch_queries(self, queries: list) -> list[Job]:
        import os

        from ..profiles import COUNTRIES

        key = self.cfg.get("api_key") or os.environ.get("JOOBLE_API_KEY")
        if not key:
            raise RuntimeError("chiave Jooble mancante (config o env JOOBLE_API_KEY)")
        hosts = jooble_hosts(self.cfg)
        jobs: dict[str, Job] = {}
        with self.http() as c:
            for q in queries:
                host = hosts.get(q.country)
                if not host:
                    continue  # nessun host Jooble per questo paese
                self.check()
                self.pause()
                where = q.where or COUNTRIES.get(q.country, {}).get("local", "")
                body = {"keywords": q.q, "location": where, "page": 1}
                if q.where and q.radius_km:
                    body["radius"] = str(q.radius_km)
                r = c.post(f"https://{host}/api/{key}", json=body)
                if r.status_code in (403, 429):
                    raise RuntimeError("Jooble ha limitato le richieste (HTTP %d): riprova più tardi" % r.status_code)
                net.ensure_ok(r)
                near = bool(q.where)
                for j in r.json().get("jobs", []):
                    job = self.to_job(j, near, q.country)
                    if not job.url:
                        continue
                    key_ = f"{q.country}:{j.get('id') or job.url}"
                    if key_ in jobs:
                        jobs[key_].near_home |= near
                        if near:
                            jobs[key_].near_where.add(q.where.lower())
                    else:
                        if near:
                            job.near_where.add(q.where.lower())
                        jobs[key_] = job
        return list(jobs.values())


REGISTRY = {s.name: s for s in (Arbeitnow, RemoteOK, Remotive, Greenhouse, Lever, Adzuna, Jooble)}
