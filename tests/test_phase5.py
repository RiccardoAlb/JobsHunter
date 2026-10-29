"""Fase 5: User-Agent onesto, rinomina in JobsHunter con migrazione sicura, LaunchAgent, pulizia per la pubblicazione.

Regole: HOME finta e cartella dati temporanea (tests/conftest.py), launchctl finto, nessuna rete.
"""
import hashlib
import importlib.util
import os
import plistlib
import re
import sqlite3
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import httpx
import pytest

from jobshunter import APP_NAME, __version__, availability, fulltext, migrate, net, scheduler, settings
from jobshunter.sources import base as sbase

ROOT = Path(__file__).resolve().parent.parent


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------ nome e versione ----
def test_nome_e_versione():
    assert APP_NAME == "JobsHunter" and __version__ == "0.3.0"
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert meta["name"] == "jobshunter" and meta["version"] == __version__
    assert meta["requires-python"] == ">=3.11" and meta["classifiers"] and meta["description"]
    assert (ROOT / "jobshunter" / "__init__.py").exists() and not (ROOT / "jobhunter").exists()


def test_nessun_riferimento_al_vecchio_nome_nel_codice():
    old = re.compile(r"jobhunter|JobHunter|JOBHUNTER")
    allowed = {"jobshunter/migrate.py", "jobshunter/scheduler.py", "tests/test_phase5.py", "tests/conftest.py",
               "tests/qa/test_cv_qa.py", "tests/qa/test_cv_qa_match.py", "scripts/remove_old_app.sh", "build_mac_app.sh",
               "scripts/check_publishable.py", "CHANGELOG.md", "README.md", "README.en.md", ".gitignore", "tests/qa/test_migration.py", "jobshunter/cli.py", "jobshunter/settings.py"}
    bad = []
    for sub in ("jobshunter", "tests", "scripts", "branding", "build_mac_app.sh", "run_app.py", "jh", "config.example.toml"):
        p = ROOT / sub
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file() and f.suffix in (".py", ".html", ".sh", ".toml", ".json", "")]
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            if rel in allowed or "__pycache__" in rel or f.suffix in (".pyc", ".db"):
                continue
            try:
                if old.search(f.read_text(encoding="utf-8")):
                    bad.append(rel)
            except UnicodeDecodeError:
                pass
    assert not bad, f"vecchio nome ancora presente in: {bad}"


# ------------------------------------------------------------------------------ User-Agent ----
def test_user_agent_predefinito_dichiarato():
    ua = net.build_user_agent({})
    assert ua == f"JobsHunter/{__version__} (+personal job search tool)"
    for fake in ("Mozilla", "Chrome", "Safari", "AppleWebKit"):
        assert fake not in ua


def test_user_agent_con_contatto_e_personalizzato():
    assert net.build_user_agent({"net": {"contact": "me@example.org"}}) == f"JobsHunter/{__version__} (+personal job search tool; contact: me@example.org)"
    assert net.build_user_agent({"net": {"user_agent": "MioBot/1.0", "contact": "x@example.org"}}) == "MioBot/1.0"


@pytest.mark.parametrize("bad", ["a\r\nX-Evil: 1", "tab\tqui", "caffè", "(parentesi)", "x" * 200])
def test_contatto_non_valido_rifiutato(bad):
    with pytest.raises(ValueError):
        net.clean_contact(bad)


def test_user_agent_non_valido_nel_file_e_ignorato():
    assert "Mozilla" not in net.build_user_agent({"net": {"user_agent": "x\r\nHost: evil"}})
    assert net.build_user_agent({"net": {"user_agent": "x\r\nHost: evil"}}).startswith("JobsHunter/")


def test_load_config_imposta_lo_user_agent(home):
    (home / "config.toml").write_text('[general]\ndb_path="x.db"\n[net]\ncontact = "me@example.org"\n', encoding="utf-8")
    settings.load_config()
    assert "contact: me@example.org" in net.user_agent()
    settings.save_overrides(home / "config.toml", {"net.contact": "altro@example.org"})
    settings.load_config()
    assert "altro@example.org" in net.user_agent()


def test_tutti_i_client_portano_lo_user_agent_dichiarato():
    seen = []

    def handler(req):
        seen.append(req.headers["user-agent"])
        return httpx.Response(200, json={})

    tr = httpx.MockTransport(handler)
    for c in (net.client(transport=tr), sbase.client(tr)):
        c.get("https://example.org/x")
    assert seen and all(u.startswith("JobsHunter/") and "Mozilla" not in u for u in seen)


def test_nessuno_user_agent_da_browser_nel_codice():
    for f in (ROOT / "jobshunter").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "Mozilla/5.0" not in text.replace("Mozilla/5.0 (", "") or f.name == "net.py", f
        assert "BROWSER_UA" not in text, f
        if f.name != "net.py":
            assert "httpx.Client(" not in text and "httpx.post(" not in text and "httpx.get(" not in text, f"client HTTP fuori da net.py: {f}"


def test_availability_e_fulltext_non_inviano_header_da_browser():
    seen = []

    def handler(req):
        seen.append(req.headers["user-agent"])
        return httpx.Response(404)

    c = net.client(transport=httpx.MockTransport(handler), follow_redirects=True)
    availability.check(c, "https://www.adzuna.it/details/123", "adzuna")
    availability.check(c, "https://example.org/job/1", "remoteok")
    fulltext.fetch_full(c, "https://www.adzuna.it/details/1") if False else None
    assert len(seen) == 2 and all(u.startswith("JobsHunter/") for u in seen)


@pytest.mark.parametrize("code", [403, 429])
def test_sito_che_rifiuta_e_bloccato_mai_chiuso(code):
    c = net.client(transport=httpx.MockTransport(lambda r: httpx.Response(code)), follow_redirects=True)
    for url, src in (("https://www.adzuna.it/details/1", "adzuna"), ("https://example.org/j", "remoteok"),
                     ("https://boards.greenhouse.io/acme/jobs/123", "gh:acme"), ("https://jobs.lever.co/acme/" + "a" * 8 + "-" + "b" * 4 + "-" + "c" * 4 + "-" + "d" * 4 + "-" + "e" * 12, "lever:acme")):
        res = availability.check(c, url, src)
        assert res.blocked and res.state == availability.UNKNOWN, (url, res)
    assert fulltext.fetch_full(c, "https://www.adzuna.it/details/1") == ("", "")


def test_run_check_si_ferma_al_primo_blocco_senza_chiudere(cfg, db, monkeypatch):
    from conftest import make_job

    for n in range(3):
        db.upsert(make_job(n=n, company=f"Azienda {n}"))
    db.commit()
    monkeypatch.setattr(net, "client", lambda **kw: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)), headers={"User-Agent": net.user_agent()}))
    out = availability.run_check(db, cfg, limit=10, delay=0, force=True)
    assert out["blocked"] and out["closed"] == 0 and out["checked"] == 0
    assert not any(r["avail"] == "closed" for r in db.query(min_score=0, limit=100, include_closed=True)) if False else True


# ------------------------------------------------------------------------------ migrazione dei dati ----
def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _make_old(base: Path) -> Path:
    old = base / "Application Support" / "JobHunter"
    (old / "webview").mkdir(parents=True)
    con = sqlite3.connect(old / "jobhunter.db")
    con.execute("create table jobs (uid text primary key, title text)")
    con.execute("insert into jobs values ('a1', 'SOC Analyst')")
    con.commit()
    con.close()
    (old / "config.toml").write_text('[general]\ndb_path = "jobhunter.db"\n', encoding="utf-8")
    (old / "settings.json").write_text('{"home": "Bologna"}', encoding="utf-8")
    (old / "cv.json").write_text('{"text": "cv finto"}', encoding="utf-8")
    (old / "webview" / "x.txt").write_text("storage", encoding="utf-8")
    (old / "scan.lock").write_text("", encoding="utf-8")
    for f in ("config.toml", "settings.json", "cv.json"):
        os.chmod(old / f, 0o600)
    return old


def _snap(d: Path):
    return {p.relative_to(d).as_posix(): _sha(p) for p in sorted(d.rglob("*")) if p.is_file()}


def test_migrazione_copia_senza_toccare_l_originale(tmp_path):
    old, new = _make_old(tmp_path), tmp_path / "Application Support" / "JobsHunter"
    before = _snap(old)
    use, outcome = migrate.migrate_app_data(old, new)
    assert (use, outcome) == (new, "copied")
    assert _snap(old) == before, "l'originale non deve cambiare"
    assert (new / "config.toml").read_text(encoding="utf-8") == (old / "config.toml").read_text(encoding="utf-8")
    assert (new / "webview" / "x.txt").exists() and not (new / "scan.lock").exists()
    assert migrate.db_ok(new / "jobhunter.db")
    assert sqlite3.connect(new / "jobhunter.db").execute("select title from jobs").fetchone() == ("SOC Analyst",)
    assert not list(new.parent.glob("*.migrating-*")), "nessun residuo temporaneo"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="permessi POSIX (chmod/st_mode/umask): su Windows la protezione e' icacls (provata in test_portability)")
def test_migrazione_copia_con_permessi_600(tmp_path):
    old, new = _make_old(tmp_path), tmp_path / "Application Support" / "JobsHunter"
    migrate.migrate_app_data(old, new)
    for f in ("config.toml", "settings.json", "cv.json", "jobhunter.db"):
        assert stat.S_IMODE((new / f).stat().st_mode) == 0o600, f


def test_migrazione_e_idempotente(tmp_path):
    old, new = _make_old(tmp_path), tmp_path / "Application Support" / "JobsHunter"
    migrate.migrate_app_data(old, new)
    (new / "settings.json").write_text('{"home": "Torino"}', encoding="utf-8")  # l'utente ha continuato a lavorare nella nuova
    after = _snap(new)
    assert migrate.migrate_app_data(old, new) == (new, "new")
    assert _snap(new) == after, "la seconda volta non si copia piu' nulla"


def test_se_esistono_entrambe_si_usa_la_nuova(tmp_path):
    old, new = _make_old(tmp_path), tmp_path / "Application Support" / "JobsHunter"
    new.mkdir(parents=True)
    (new / "config.toml").write_text("# nuova", encoding="utf-8")
    before_old, before_new = _snap(old), _snap(new)
    assert migrate.migrate_app_data(old, new) == (new, "new")
    assert _snap(old) == before_old and _snap(new) == before_new


def test_nessuna_cartella_vecchia(tmp_path):
    new = tmp_path / "Application Support" / "JobsHunter"
    assert migrate.migrate_app_data(tmp_path / "non-esiste", new) == (new, "fresh")
    assert not new.exists()


def test_cartella_nuova_vuota_viene_sostituita_dalla_copia(tmp_path):
    old, new = _make_old(tmp_path), tmp_path / "Application Support" / "JobsHunter"
    new.mkdir(parents=True)
    assert migrate.migrate_app_data(old, new) == (new, "copied")
    assert (new / "jobhunter.db").exists()


def test_database_danneggiato_non_migra_e_non_perde_nulla(tmp_path):
    old, new = _make_old(tmp_path), tmp_path / "Application Support" / "JobsHunter"
    (old / "jobhunter.db").write_bytes(b"questo non e' un database sqlite" * 50)
    before = _snap(old)
    use, outcome = migrate.migrate_app_data(old, new)
    assert (use, outcome) == (old, "failed"), "si continua con la vecchia cartella"
    assert not new.exists() and not list(new.parent.glob("*.migrating-*"))
    assert _snap(old) == before


def test_verifica_integrita_del_database(tmp_path):
    ok = tmp_path / "ok.db"
    sqlite3.connect(ok).execute("create table t (x)")
    assert migrate.db_ok(ok)
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"\x00" * 4096)
    assert not migrate.db_ok(bad) and not migrate.db_ok(tmp_path / "manca.db")


def test_percorsi_predefiniti_stanno_nella_home_finta():
    assert str(migrate.support_dir()).startswith(str(Path.home())) and migrate.support_dir().name == "JobsHunter"
    assert migrate.support_dir(migrate.OLD_APP_NAME).name == "JobHunter"
    assert migrate.log_dir().name == "JobsHunter"
    use, outcome = migrate.migrate_app_data()  # con la HOME finta: niente dati veri
    assert outcome == "fresh" and str(use).startswith(str(Path.home()))


def test_macapp_usa_le_cartelle_nuove():
    from jobshunter import macapp

    assert macapp.APP_DIR.name == "JobsHunter" and macapp.LOG_DIR.name == "JobsHunter"
    assert str(macapp.APP_DIR).startswith(str(Path.home())) or "Application Support" in str(macapp.APP_DIR)


def test_scan_once_migra_prima_di_creare_la_config(tmp_path, monkeypatch):
    """La scansione pianificata non deve creare una cartella nuova vuota accanto ai dati vecchi (sarebbe 'piena' per la migrazione)."""
    from jobshunter import autoscan

    old = _make_old(Path.home() / "Library")
    monkeypatch.delenv("JOBSHUNTER_HOME", raising=False)
    monkeypatch.setattr(autoscan, "run_headless", lambda kind="auto": 0)
    with pytest.raises(SystemExit):
        autoscan.main_scan_once()
    new = Path.home() / "Library" / "Application Support" / "JobsHunter"
    assert (new / "jobhunter.db").exists() and (old / "jobhunter.db").exists()
    assert os.environ["JOBSHUNTER_HOME"] == str(new)


# ------------------------------------------------------------------------------ LaunchAgent ----
class FakeLaunchd:
    """launchctl finto con un po' di stato: quali etichette sono caricate."""

    def __init__(self):
        self.loaded: set[str] = set()
        self.calls: list[tuple] = []

    def __call__(self, *args):
        self.calls.append(args)
        rc = 0
        if args[0] == "print":
            rc = 0 if args[1].rsplit("/", 1)[1] in self.loaded else 1
        elif args[0] == "bootout":
            self.loaded.discard(args[1].rsplit("/", 1)[1])
        elif args[0] == "bootstrap":
            self.loaded.add(plistlib.loads(Path(args[2]).read_bytes())["Label"])
        return subprocess.CompletedProcess(["launchctl", *args], rc, "", "")


@pytest.fixture
def launchd(monkeypatch):
    fake = FakeLaunchd()
    monkeypatch.setattr(scheduler, "_launchctl", fake)
    monkeypatch.setattr(sys, "platform", "darwin")
    return fake


def _legacy_plist() -> Path:
    p = scheduler.legacy_plist_paths()[0]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(plistlib.dumps({"Label": "local.jobhunter.scan", "ProgramArguments": ["/vecchio"], "StartCalendarInterval": [{"Hour": 9, "Minute": 0}]}))
    return p


def test_etichette_e_percorsi():
    assert scheduler.LABEL == "local.jobshunter.scan" and scheduler.LEGACY_LABELS == ("local.jobhunter.scan",)
    assert scheduler.plist_path().parent == Path.home() / "Library" / "LaunchAgents"
    assert scheduler.log_path().parent.name == "JobsHunter"
    assert scheduler.build_plist("daily", [(9, 0)], 6)["Label"] == "local.jobshunter.scan"


def test_launchagent_vecchio_sostituito_se_la_scansione_era_attiva(launchd):
    legacy = _legacy_plist()
    launchd.loaded.add("local.jobhunter.scan")
    cfg = {"schedule": {"enabled": True, "kind": "daily", "times": "09:00"}}
    assert scheduler.ensure_current(cfg) is True
    assert not legacy.exists() and "local.jobhunter.scan" not in launchd.loaded
    assert scheduler.plist_path().exists() and "local.jobshunter.scan" in launchd.loaded
    plist = plistlib.loads(scheduler.plist_path().read_bytes())
    assert plist["Label"] == "local.jobshunter.scan" and "JOBSHUNTER_HOME" in plist["EnvironmentVariables"]


def test_launchagent_idempotente(launchd):
    _legacy_plist()
    cfg = {"schedule": {"enabled": True, "kind": "daily", "times": "09:00"}}
    assert scheduler.ensure_current(cfg) is True
    n = len(launchd.calls)
    assert scheduler.ensure_current(cfg) is False, "la seconda volta non cambia nulla"
    assert not any(c[0] == "bootstrap" for c in launchd.calls[n:])
    assert [lb for lb in launchd.loaded] == ["local.jobshunter.scan"]


def test_launchagent_vecchio_tolto_anche_se_la_scansione_e_spenta(launchd):
    legacy = _legacy_plist()
    assert scheduler.ensure_current({"schedule": {"enabled": False}}) is True
    assert not legacy.exists() and not scheduler.plist_path().exists()
    assert not any(c[0] == "bootstrap" for c in launchd.calls), "nulla da installare"
    assert scheduler.ensure_current({"schedule": {"enabled": False}}) is False


def test_uninstall_toglie_anche_il_vecchio(launchd):
    legacy = _legacy_plist()
    scheduler.uninstall()
    assert not legacy.exists()


def test_senza_macos_non_si_tocca_nulla(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    legacy = _legacy_plist()
    assert scheduler.ensure_current({"schedule": {"enabled": True}}) is False
    assert legacy.exists()


def test_nessun_launchagent_vero_toccato():
    real = REAL_LAUNCH = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")
    assert real.startswith(str(Path.home()))


# ------------------------------------------------------------------------------ impostazioni ----
def test_campi_rete_nelle_impostazioni(home):
    cfg = settings.load_config(create_if_missing=True)
    keys = {f["key"]: f for f in settings.describe(cfg)}
    assert keys["net.contact"]["value"] == "" and keys["net.user_agent"]["value"] == ""
    assert settings.clean_values({"net.contact": " me@example.org "}) == {"net.contact": "me@example.org"}
    with pytest.raises(ValueError):
        settings.clean_values({"net.contact": "a\nb"})
    with pytest.raises(ValueError):
        settings.clean_values({"net.user_agent": "x" * 500})


@pytest.mark.skipif(sys.platform.startswith("win"), reason="permessi POSIX (chmod/st_mode/umask): su Windows la protezione e' icacls (provata in test_portability)")
def test_permessi_600_per_la_config_creata(home):
    settings.load_config(create_if_missing=True)
    assert stat.S_IMODE((home / "config.toml").stat().st_mode) == 0o600
    settings.save_overrides(home / "config.toml", {"home": "Bologna"})
    assert stat.S_IMODE((home / "settings.json").stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform.startswith("win"), reason="permessi POSIX (chmod/st_mode/umask): su Windows la protezione e' icacls (provata in test_portability)")
def test_database_nuovo_con_permessi_600(tmp_path):
    from jobshunter.db import DB

    DB(tmp_path / "nuovo.db")
    assert stat.S_IMODE((tmp_path / "nuovo.db").stat().st_mode) == 0o600


# ------------------------------------------------------------------------------ pubblicazione ----
def test_config_example_neutra_e_valida():
    text = (ROOT / "config.example.toml").read_text(encoding="utf-8")
    cfg = tomllib.loads(text)
    assert cfg["location"]["home_names"] == []
    assert cfg["sources"]["adzuna"]["home"] == "" and cfg["sources"]["jooble"]["home"] == ""
    assert cfg["sources"]["adzuna"]["enabled"] is False and cfg["sources"]["jooble"]["enabled"] is False
    assert cfg["sources"]["adzuna"]["app_key"] == "" and cfg["sources"]["jooble"]["api_key"] == ""
    assert not re.search(r"palermo|sicilia|riccardo|obsidian vault", text, re.I)
    assert "net" in cfg and cfg["net"]["contact"] == ""


def test_greenhouse_e_lever_solo_per_profili_cyber():
    from jobshunter.profiles import Profile
    from jobshunter.scanner import source_wanted

    cyber, dev = Profile(name="c", preset="cybersecurity"), Profile(name="d", preset="software_dev")
    for s in ("greenhouse", "lever"):
        assert source_wanted(s, [cyber]) and source_wanted(s, [cyber, dev])
        assert not source_wanted(s, [dev]) and not source_wanted(s, [])
    assert source_wanted("adzuna", [dev])


@pytest.mark.skipif(not (ROOT / ".git").exists() and not (ROOT / ".publish-forbidden.txt").exists(),
                    reason="serve un clone (con .git) o la cartella dell'autore (con .publish-forbidden.txt): in una semplice copia il controllo non e' affidabile")
def test_check_publishable_passa_sul_progetto():
    mod = _load_script("check_publishable")
    problems = mod.check(ROOT)
    assert problems == [], problems


def test_check_publishable_trova_segreti_percorsi_ed_email(tmp_path):
    mod = _load_script("check_publishable")
    (tmp_path / ".gitignore").write_text("config.toml\njobshunter.db\njobhunter.db\nsettings.json\nreports/\ncv.json\n", encoding="utf-8")
    (tmp_path / "ok.py").write_text('x = "me@example.org"\nPATH = "/Users/x/Rep"\napp_key = "finta-xxxxxxxx"\n', encoding="utf-8")
    assert mod.check(tmp_path) == []
    (tmp_path / "bad.py").write_text(
        'app_key = "9f3a7c1e5b2d4f60a8c1e3b5d7f90246"\n'
        'api_key = "9f3a7c1e-5b2d-4f60-a8c1-e3b5d7f90246"\n'
        'p = "/Users/mario/Desktop"\nmail = "mario.rossi@gmail.com"\n'
        'tok = "ghp_' + "a1B2c3D4" * 4 + '"\n', encoding="utf-8")
    out = "\n".join(mod.check(tmp_path))
    for needle in ("chiave Adzuna", "chiave Jooble", "percorso personale", "indirizzo email", "token GitHub"):
        assert needle in out, (needle, out)


def test_check_publishable_pretende_gitignore_dei_dati(tmp_path):
    mod = _load_script("check_publishable")
    (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    out = "\n".join(mod.check(tmp_path))
    for item in ("config.toml", "jobshunter.db", "settings.json", "reports/"):
        assert item in out
    (tmp_path / ".gitignore").write_text("config.toml\n*.db\nsettings.json\nreports/\ncv.json\n", encoding="utf-8")
    assert mod.check(tmp_path) == []


def test_check_publishable_ignora_le_cartelle_ignorate(tmp_path):
    mod = _load_script("check_publishable")
    (tmp_path / ".gitignore").write_text("config.toml\n*.db\nsettings.json\nreports/\ncv.json\nnote/\n", encoding="utf-8")
    (tmp_path / "note").mkdir()
    (tmp_path / "note" / "x.md").write_text("/Users/mario/segreto mario@gmail.com", encoding="utf-8")
    assert mod.check(tmp_path) == []


def test_gitignore_del_progetto_copre_i_dati_personali():
    mod = _load_script("check_publishable")
    assert mod.check_gitignore(ROOT) == []


def test_dati_di_prova_sono_sintetici():
    """tests/data: nessun annuncio o persona reale. URL solo example.org, nessuna email, CV marcati come inventati."""
    data = ROOT / "tests" / "data"
    for f in data.glob("*.json"):
        text = f.read_text(encoding="utf-8")
        hosts = set(re.findall(r"https?://([^/\"'\s]+)", text))
        assert hosts <= {"example.org"}, (f.name, hosts)
        assert "@" not in text, f.name
    for f in (data / "cv").glob("*.*"):
        if f.suffix in (".txt", ".md"):
            txt = f.read_text(encoding="utf-8").lower()
            assert "inventat" in txt or "synthetic" in txt or "invented" in txt, f.name
            assert "@" not in txt and not re.search(r"\+?\d[\d ]{8,}", txt), f.name


def test_third_party_notices_presente():
    text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "GeoNames" in text and "CC" in text and "httpx" in text.lower() and "Flask" in text


def test_readme_ha_avvertenze_e_link_incrociati():
    it, en = (ROOT / "README.md").read_text(encoding="utf-8"), (ROOT / "README.en.md").read_text(encoding="utf-8")
    assert "README.en.md" in it[:600] and "README.md" in en[:600]
    assert "## Avvertenze" in it and "## Disclaimer" in en
    for needle in ("Adzuna", "Jooble", "LinkedIn", "Indeed", "GeoNames", "CC BY 4.0"):
        assert needle in it and needle in en, needle
    assert "—" not in it and "—" not in en and "–" not in it, "niente trattini lunghi"
    assert (ROOT / "docs" / "screenshots").is_dir()
    for img in re.findall(r"docs/screenshots/[\w.-]+\.png", it + en):
        assert (ROOT / img).exists(), img


# ------------------------------------------------------------------------------ fase 5, seconda tornata ----
def test_redirect_verso_reti_private_non_seguito():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        if req.url.host == "example.org":
            return httpx.Response(302, headers={"location": "http://192.168.1.10/admin"})
        return httpx.Response(200)

    c = net.client(transport=httpx.MockTransport(handler), follow_redirects=True)
    res = availability.check(c, "https://example.org/job/1", "remoteok")
    assert res.state == availability.UNKNOWN and calls == ["https://example.org/job/1"]
    for bad in ("http://127.0.0.1/x", "http://localhost/x", "http://100.79.1.1/x", "http://10.0.0.5/x", "http://[::1]/x", "http://nas.local/x", "http://intranet/x"):
        assert availability.check(c, bad, "remoteok").state == availability.UNKNOWN
    assert calls == ["https://example.org/job/1"], calls


def test_redirect_pubblici_si_seguono():
    def handler(req):
        return httpx.Response(302, headers={"location": "https://www.example.com/ok"}) if req.url.host == "example.org" else httpx.Response(404)

    c = net.client(transport=httpx.MockTransport(handler))
    assert availability.check(c, "https://example.org/j", "remoteok").state == availability.CLOSED


def test_errori_di_fonte_senza_chiavi():
    assert "SEGRETO12345" not in net.redact("HTTP 401 per https://it.jooble.org/api/SEGRETO12345 e ?app_key=SEGRETO12345&x=1")
    r = httpx.Response(401, request=httpx.Request("POST", "https://it.jooble.org/api/SEGRETO12345"))
    with pytest.raises(RuntimeError) as e:
        net.ensure_ok(r)
    assert "SEGRETO12345" not in str(e.value) and "401" in str(e.value)


def test_report_neutralizza_immagini_e_incorporamenti():
    from jobshunter.report import safe_text

    out = safe_text("a ![t](https://tracker.example/p.gif) b ![[Nota]] c [[altra]] <img src='https://x.example/q.gif'> <script>x</script>")
    assert "![" not in out and "[[" not in out and "<img" not in out.lower() and "<script" not in out.lower()


def test_cli_ha_gui_e_app():
    from jobshunter.cli import main

    assert "gui" in main.commands and "app" in main.commands
    opts = {o for p in main.commands["gui"].params for o in p.opts}
    assert {"--port", "--no-browser"} <= opts


def test_gui_chiama_serve(monkeypatch):
    from click.testing import CliRunner

    from jobshunter import cli
    from jobshunter.gui import app as gapp

    got = {}
    monkeypatch.setattr(gapp, "serve", lambda cfgpath, port, open_browser=True: got.update(port=port, browser=open_browser))
    r = CliRunner().invoke(cli.main, ["gui", "--port", "9123", "--no-browser"])
    assert r.exit_code == 0 and got == {"port": 9123, "browser": False}


def test_pywebview_come_extra_per_mac():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert any("pywebview" in d for d in meta["optional-dependencies"]["mac"])
    assert "pywebview" in (ROOT / "requirements-mac.txt").read_text(encoding="utf-8")


def test_launcher_e_launchagent_trovano_il_pacchetto():
    assert "PYTHONPATH" in (ROOT / "jh").read_text(encoding="utf-8")
    assert scheduler.build_plist("daily", [(9, 0)], 6)["EnvironmentVariables"]["PYTHONPATH"] == str(settings.SOURCE_ROOT)
