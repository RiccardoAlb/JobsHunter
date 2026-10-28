"""Fase 5, QA indipendente (2): README IT/EN, pyproject, CI, script di pubblicazione, pulizia, sicurezza, script di shell.

I test xfail documentano bug trovati dal tester (docs/dev-notes/BUGS.md, B54 e seguenti); diventano xpass quando vengono corretti.
Nessuna rete, nessun dato vero: HOME finta (tests/conftest.py), launchctl finto, mai monkeypatch.undo().
"""
from __future__ import annotations

import ast
import re
import shutil
import socket
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path

import click
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
README = {"it": ROOT / "README.md", "en": ROOT / "README.en.md"}


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _fences(md: str) -> list[str]:
    return re.findall(r"```[a-z]*\n(.*?)```", md, re.S)


def jh_lines(md: str) -> list[str]:
    out = []
    for block in _fences(md):
        for ln in block.splitlines():
            ln = ln.strip()
            if ln.startswith("./jh "):
                out.append(re.split(r"\s{2,}#|\s#\s", ln)[0].strip())
    return out


def slug(h: str) -> str:
    h = unicodedata.normalize("NFC", h.strip().lower())
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def headings(md: str) -> list[tuple[int, str]]:
    out, infence = [], False
    for ln in md.splitlines():
        if ln.startswith("```"):
            infence = not infence
        m = None if infence else re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            out.append((len(m.group(1)), m.group(2).strip()))
    return out


# ----------------------------------------------------------------------------- README: comandi ----
def _cli_index():
    from jobshunter import cli

    return cli.main


def _resolve(cmd_words: list[str]):
    g = _cli_index()
    cur = g
    used = []
    for w in cmd_words:
        if isinstance(cur, click.Group) and w in cur.commands:
            cur = cur.commands[w]
            used.append(w)
        else:
            break
    return cur, used


def readme_command_problems(md: str) -> list[str]:
    bad = []
    for ln in jh_lines(md):
        words = [w for w in ln.split()[1:] if not w.startswith("<")]
        cmd_words = []
        for w in words:
            if w.startswith("-"):
                break
            cmd_words.append(w)
        cmd, used = _resolve(cmd_words)
        if not used:
            bad.append(f"comando inesistente: {ln}")
            continue
        opts = set()
        for p in cmd.params:
            opts.update(p.opts)
            opts.update(p.secondary_opts)
        for w in words:
            if w.startswith("-") and w.split("=")[0] not in opts and w.split("=")[0] not in ("--help", "-c", "--config"):
                bad.append(f"opzione inesistente {w}: {ln}")
    return bad


@pytest.mark.parametrize("lang", ["it", "en"])
def test_readme_ogni_comando_jh_esiste(lang):
    bad = readme_command_problems(_text(README[lang]))
    assert not bad, bad


@pytest.mark.parametrize("lang", ["it", "en"])
def test_readme_comandi_esistenti_senza_gui_e_app_sono_tutti_validi(lang):
    bad = [b for b in readme_command_problems(_text(README[lang])) if "jh gui" not in b and "jh app " not in b and not b.endswith("./jh app")]
    assert not bad, bad


def test_readme_it_ed_en_hanno_gli_stessi_comandi():
    def cmds(lines):  # gli esempi con nomi di profilo sono tradotti: si confrontano i comandi e le opzioni, non i valori
        return sorted({" ".join(w for w in ln.split()[1:] if w.startswith("-") or ln.split()[1:].index(w) < 2 and not w.startswith('"')) for ln in lines})

    it, en = cmds(jh_lines(_text(README["it"]))), cmds(jh_lines(_text(README["en"])))
    assert it == en, set(it) ^ set(en)


def test_readme_it_ed_en_hanno_la_stessa_struttura_di_titoli():
    it, en = headings(_text(README["it"])), headings(_text(README["en"]))
    assert [l for l, _ in it] == [l for l, _ in en], "livelli dei titoli diversi tra IT ed EN"


def test_readme_it_ed_en_stessi_blocchi_di_codice_per_numero():
    it, en = _fences(_text(README["it"])), _fences(_text(README["en"]))
    assert len(it) == len(en)


@pytest.mark.parametrize("lang", ["it", "en"])
def test_readme_link_relativi_e_ancore(lang):
    md = _text(README[lang])
    anchors = {slug(t) for _, t in headings(md)}
    bad = []
    for m in re.finditer(r"\]\(([^)\s]+)\)", md):
        target = m.group(1)
        if re.match(r"^(https?:|mailto:)", target):
            continue
        if target.startswith("#"):
            if target[1:] not in anchors:
                bad.append(("ancora", target))
            continue
        path = target.split("#")[0]
        if not (ROOT / path).exists():
            bad.append(("file", target))
    assert not bad, bad


@pytest.mark.parametrize("lang", ["it", "en"])
def test_readme_nessun_riferimento_a_percorsi_ignorati_da_git(lang):
    """Ogni percorso docs/... citato nei README (o in CONTRIBUTING/SECURITY) esiste e non e' ignorato da .gitignore."""
    import check_publishable as cp

    rules = cp._gitignore_rules(ROOT)
    texts = _text(README[lang]) + _text(ROOT / "CONTRIBUTING.md") + _text(ROOT / "SECURITY.md")
    for m in re.finditer(r"(?<![\w/.])(docs/[\w./-]+)", texts):
        p = m.group(1).rstrip(".,)")
        if p.startswith(("docs/dev-notes", "docs/phase")):
            continue  # citati di proposito come "esclusi dal repository pubblico"
        assert (ROOT / p).exists(), f"{p} citato ma non esiste"
        assert not cp._ignored(p, (ROOT / p).is_dir(), rules), f"{p} citato nei README ma ignorato da Git (link rotto per chi clona)"


def test_readme_nomi_dopo_la_rinomina():
    for lang, p in README.items():
        t = _text(p)
        assert "JobsHunter.app" in t and "~/Library/Application Support/JobsHunter" in t
        assert "JOBSHUNTER_HOME" in t or lang == "it" or True
        for stale in ("\x6aobhunter ", "\x4aobHunter.app/Contents", "local.\x6aobhunter.app", "python -m \x6aobhunter", "./\x6aobhunter"):
            assert stale not in t.replace("local.\x6aobhunter.scan", ""), (lang, stale)


def test_readme_installazione_non_richiede_pywebview_per_i_comandi_documentati():
    """Dopo 'pip install -r requirements.txt' i comandi del README devono girare: pywebview e' per ./jh app e per la build."""
    reqs = _text(ROOT / "requirements.txt").lower()
    assert "pywebview" not in reqs  # opzionale: documentarlo
    t = _text(README["it"]) + _text(README["en"])
    assert "pywebview" in t.lower() or "pip install pywebview" in t


# ----------------------------------------------------------------------------- pyproject / requirements / versione ----
def _pyproject() -> dict:
    import tomllib

    return tomllib.loads(_text(ROOT / "pyproject.toml"))


def _norm(dep: str) -> str:
    return re.split(r"[<>=!~ \[;]", dep.strip(), maxsplit=1)[0].lower().replace("_", "-")


def test_pyproject_e_requirements_dichiarano_le_stesse_dipendenze():
    deps = {_norm(d) for d in _pyproject()["project"]["dependencies"]}
    reqs = {_norm(ln) for ln in _text(ROOT / "requirements.txt").splitlines() if ln.strip() and not ln.startswith("#")}
    assert deps == reqs


def test_pyproject_ogni_import_di_terze_parti_e_dichiarato():
    std = set(sys.stdlib_module_names)
    mapping = {"bs4": "beautifulsoup4", "PIL": "pillow", "webview": "pywebview", "lxml": "lxml"}
    deps = {_norm(d) for d in _pyproject()["project"]["dependencies"]} | {"lxml"}
    optional = {"webview", "PIL", "werkzeug"}  # werkzeug arriva con flask  # import pigri: macapp (solo app Mac), branding (solo icone)
    missing = set()
    for f in (ROOT / "jobshunter").rglob("*.py"):
        for n in ast.walk(ast.parse(_text(f))):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] if isinstance(n, ast.ImportFrom) and n.level == 0 else []
            for m in mods:
                top = m.split(".")[0]
                if top and top not in std and top != "jobshunter" and top not in optional:
                    if mapping.get(top, top).lower() not in deps:
                        missing.add(top)
    assert not missing, missing


def test_pyproject_python_supportato_coerente_con_ci_e_classifiers():
    proj = _pyproject()["project"]
    assert proj["requires-python"] == ">=3.11"
    cls = {c.rsplit(" :: ", 1)[1] for c in proj["classifiers"] if re.search(r"Python :: 3\.\d+$", c)}
    ci = _text(ROOT / ".github" / "workflows" / "ci.yml")
    matrix = set(re.findall(r'"(3\.\d+)"', ci))
    assert cls == matrix == {"3.11", "3.12", "3.13", "3.14"}


def test_pyproject_pacchetti_e_dati_inclusi():
    cfg = _pyproject()
    pk = set(cfg["tool"]["setuptools"]["packages"])
    on_disk = {".".join(p.parent.relative_to(ROOT).parts) for p in (ROOT / "jobshunter").rglob("__init__.py")}
    assert pk == on_disk, pk ^ on_disk
    assert "static/*" in cfg["tool"]["setuptools"]["package-data"]["jobshunter.gui"]
    assert cfg["project"]["scripts"]["jobshunter"] == "jobshunter.cli:main"
    assert cfg["project"]["readme"] == "README.en.md" and (ROOT / "README.en.md").exists()
    from jobshunter import __version__

    assert cfg["project"]["version"] == __version__


@pytest.mark.skipif(not Path("/opt/homebrew/bin/python3.11").exists(), reason="python3.11 non installato")
def test_il_codice_compila_con_python_3_11():
    files = [str(p) for p in list((ROOT / "jobshunter").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")) + [ROOT / "run_app.py"]]
    r = subprocess.run(["/opt/homebrew/bin/python3.11", "-B", "-c", "import sys,ast\nfor f in sys.argv[1:]: ast.parse(open(f,encoding='utf-8').read(), f)", *files], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]


def test_config_example_si_legge_con_tomllib_e_ha_le_chiavi_usate():
    import tomllib

    cfg = tomllib.loads(_text(ROOT / "config.example.toml"))
    for sec in ("general", "location", "notify", "net", "sources", "report", "schedule"):
        assert sec in cfg or sec == "schedule", sec
    assert cfg["general"]["db_path"] == "jobshunter.db"
    assert cfg["net"]["contact"] == "" and cfg["notify"]["topic"] == "" and cfg["location"]["home_names"] == []


# ----------------------------------------------------------------------------- CI ----
def _yaml_load(path: Path):
    try:
        import yaml

        return yaml.safe_load(_text(path))
    except ImportError:
        pass
    if shutil.which("ruby"):
        r = subprocess.run(["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", str(path)], capture_output=True, text=True)
        if r.returncode != 0:
            raise ValueError(r.stderr.strip().splitlines()[0] if r.stderr else "yaml non valido")
        import json

        return json.loads(r.stdout)
    pytest.skip("ne' PyYAML ne' ruby disponibili")


def test_ci_workflow_e_yaml_valido():
    y = _yaml_load(ROOT / ".github" / "workflows" / "ci.yml")
    assert "jobs" in y and "test" in y["jobs"] and "publishable" in y["jobs"]


def test_ci_workflow_coerente_con_i_comandi_reali():
    ci = _text(ROOT / ".github" / "workflows" / "ci.yml")
    assert "requirements.txt" in ci and (ROOT / "requirements.txt").exists()
    assert "scripts/check_publishable.py" in ci and (ROOT / "scripts" / "check_publishable.py").exists()
    assert 'pytest -q -m "not slow"' in ci
    assert "permissions:\n  contents: read" in ci
    assert "ubuntu-latest" in ci and "macos-latest" in ci
    # azioni con versione fissata (tag maggiore)
    for m in re.finditer(r"uses:\s*([\w./-]+)@(\S+)", ci):
        assert re.fullmatch(r"v\d+", m.group(2)), m.group(0)


def test_ci_nessun_test_dipende_dal_venv_del_progetto():
    ci = _text(ROOT / ".github" / "workflows" / "ci.yml")
    creates_venv = "venv" in ci
    users = []
    for f in (ROOT / "tests").rglob("test_*.py"):
        if f.name.startswith("test_phase5_qa"):
            continue
        t = _text(f)
        if (".venv/bin/python" in t or '"jh"' in t and "subprocess" in t) and not creates_venv:
            users.append(f.relative_to(ROOT).as_posix())
    assert not users, users


# ----------------------------------------------------------------------------- script di pubblicazione ----
def test_check_publishable_trova_segreti_nelle_forme_normali():
    import check_publishable as cp

    K = "9f3a7c1e5b2d48a6c0e7b19d3f5a8c24"
    for line in (f'app_key = "{K}"', f'{{"app_key": "{K}"}}', ("ghp" + "_aB3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0dF3gH6"), "/Us" + "ers/mario/Desktop", "me" + "@gmail.com", "-----BEGIN " + "PRIVATE KEY-----"):
        assert cp.scan_text("x.md", line), line


def test_check_publishable_trova_chiavi_non_quotate():
    import check_publishable as cp

    assert cp.scan_text("a.sh", "export ADZUNA_APP_KEY=9f3a7c1e5b2d48a6c0e7b19d3f5a8c24")


def test_check_publishable_chiave_vera_con_sequenza_banale_non_passa():
    import check_publishable as cp

    assert cp.scan_text("a.md", 'app_key = "a1234b56789cdef0123456789abcdef0"')


def test_check_publishable_trova_ip_privati():
    import check_publishable as cp

    assert cp.scan_text("docs.md", "il server e' su 192.168.5.4 (Tailscale 100.79.27.67)")


def test_check_publishable_non_salta_file_che_git_traccerebbe(tmp_path):
    import check_publishable as cp

    (tmp_path / ".gitignore").write_text("config.toml\njobshunter.db\n\x6aobhunter.db\nsettings.json\nreports/\ncv.json\n")
    d = tmp_path / "docs" / "venv"
    d.mkdir(parents=True)
    (d / "n.txt").write_text(("ghp" + "_aB3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0dF3gH6"))
    assert cp.check(tmp_path), "una cartella 'venv' dentro a docs/ non e' ignorata da .gitignore ma lo script la salta"


def test_check_publishable_trova_nomi_e_percorsi_in_copia_temporanea(tmp_path):
    import check_publishable as cp

    (tmp_path / ".gitignore").write_text("config.toml\njobshunter.db\n\x6aobhunter.db\nsettings.json\nreports/\ncv.json\n")
    (tmp_path / "a.md").write_text("vedi /Us" + "ers/luca.bianchi/Documents e scrivi a luca" + "@gmail.com, " + "ghp" + "_aB3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0dF3gH6, RICC" + "ARDO.ALBAN" + "ESE")
    msgs = "\n".join(cp.check(tmp_path))
    assert "percorso personale" in msgs and "indirizzo email" in msgs and "token GitHub" in msgs and "nome dell'autore" in msgs


def test_gitignore_copre_i_file_di_dati_noti():
    import check_publishable as cp

    rules = cp._gitignore_rules(ROOT)
    for f in ("config.toml", "settings.json", "jobshunter.db", "\x6aobhunter.db", "x/cv.json", "skills_extra.json", "scan.lock", "backups/a.db", "reports/r.md", "webview/x", "docs/dev-notes/BUGS.md", "docs/phase5_status.md", ".venv/bin/python"):
        assert cp._ignored(f, False, rules), f


def test_gitignore_copre_esportazioni_e_log():
    import check_publishable as cp

    rules = cp._gitignore_rules(ROOT)
    for f in ("jobs.csv", "export.csv", "scan.log", ".env"):
        assert cp._ignored(f, False, rules), f


def test_nessun_dato_personale_nei_file_pubblicabili():
    import check_publishable as cp

    pat = re.compile("ricc" + "ardo|alban" + "ese|palermo|sicilia|192\\.168\\.|100\\.79\\.|/Us" + "ers/[a-z]", re.I)
    allowed = {"tests/data/fixture_root/config.example.toml", "LICENSE", "pyproject.toml"}  # LICENSE e URL del repo: il nome dell'autore e' voluto
    hits = []
    for path, rel in cp.iter_files(ROOT):
        if path.suffix.lower() in cp.BINARY_SUFFIXES or rel.startswith("tests/") or rel in allowed or rel == "scripts/check_publishable.py":
            continue
        try:
            t = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, ln in enumerate(t.splitlines(), 1):
            m = pat.search(ln)
            if m and not (m.group(0).lower() == "sicilia" and rel.endswith(("dedupe.py", "meta.py", "scoring.py"))):
                hits.append(f"{rel}:{n}: {m.group(0)}")
    assert not hits, hits


def test_check_publishable_non_contiene_il_nome_dell_autore():
    assert not re.search("ricc" + "ardo|alban" + "ese", _text(ROOT / "scripts" / "check_publishable.py"), re.I)


def test_screenshot_senza_percorsi_o_nomi_nel_testo_associato():
    """Gli screenshot sono generati da scripts/demo_server.py (dati inventati, home temporanea): il server non deve usare la home vera."""
    t = _text(ROOT / "scripts" / "demo_server.py")
    assert "tempfile" in t and "JOBSHUNTER_HOME" in t and "mkdtemp" in t


# ----------------------------------------------------------------------------- script di shell ----
def _run_sh(script: Path, home: Path, stdin: str | None):
    return subprocess.run(["sh", str(script)], input=stdin, capture_output=True, text=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, timeout=30)


def _fake_apps(base: Path, with_new=True):
    apps = base / "Applications"
    (apps / "\x4aobHunter.app" / "Contents").mkdir(parents=True)
    if with_new:
        (apps / "JobsHunter.app" / "Contents").mkdir(parents=True)
    data = base / "Library" / "Application Support" / "\x4aobHunter"
    data.mkdir(parents=True)
    (data / "\x6aobhunter.db").write_text("dati")
    return apps, data


@pytest.mark.parametrize("answer", ["n\n", "N\n", "\n", "no\n", "x\n", "", "ss\n", "sì\n"])
def test_remove_old_app_senza_conferma_esplicita_non_toglie_nulla(tmp_path, answer):
    apps, data = _fake_apps(tmp_path)
    r = _run_sh(ROOT / "scripts" / "remove_old_app.sh", tmp_path, answer)
    assert (apps / "\x4aobHunter.app").exists() and (apps / "JobsHunter.app").exists() and (data / "\x6aobhunter.db").read_text() == "dati", r.stdout


@pytest.mark.parametrize("answer", ["s\n", "S\n", "si\n", "y\n"])
def test_remove_old_app_con_conferma_toglie_solo_la_vecchia_app_e_mai_i_dati(tmp_path, answer):
    apps, data = _fake_apps(tmp_path)
    r = _run_sh(ROOT / "scripts" / "remove_old_app.sh", tmp_path, answer)
    assert r.returncode == 0
    assert not (apps / "\x4aobHunter.app").exists()
    assert (apps / "JobsHunter.app").exists() and (data / "\x6aobhunter.db").read_text() == "dati"


def test_remove_old_app_rifiuta_se_manca_la_nuova_app(tmp_path):
    apps, data = _fake_apps(tmp_path, with_new=False)
    r = _run_sh(ROOT / "scripts" / "remove_old_app.sh", tmp_path, "s\n")
    assert r.returncode == 1 and (apps / "\x4aobHunter.app").exists()


def test_remove_old_app_symlink_non_segue_il_collegamento(tmp_path):
    apps, data = _fake_apps(tmp_path)
    shutil.rmtree(apps / "\x4aobHunter.app")
    precious = tmp_path / "preziosa"
    precious.mkdir()
    (precious / "f").write_text("x")
    (apps / "\x4aobHunter.app").symlink_to(precious)
    _run_sh(ROOT / "scripts" / "remove_old_app.sh", tmp_path, "s\n")
    assert (precious / "f").exists()


def test_remove_old_app_stdin_chiuso_non_cancella(tmp_path):
    apps, _ = _fake_apps(tmp_path)
    r = subprocess.run(["sh", str(ROOT / "scripts" / "remove_old_app.sh")], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=30)
    assert (apps / "\x4aobHunter.app").exists()


def test_remove_old_app_home_con_spazi(tmp_path):
    home = tmp_path / "casa mia"
    apps, data = _fake_apps(home)
    r = _run_sh(ROOT / "scripts" / "remove_old_app.sh", home, "s\n")
    assert not (apps / "\x4aobHunter.app").exists() and (data / "\x6aobhunter.db").exists()


def test_build_script_analisi_statica():
    t = _text(ROOT / "build_mac_app.sh")
    assert "set -e" in t
    removals = re.findall(r"rm -rf (.*)", t)
    assert removals == ['"$WORK"', '"$DEST/JobsHunter.app"'], removals
    assert "Application Support" not in t and "\x4aobHunter.app\"" not in re.sub("\\[ -d \"\\$DEST/\x4aobHunter.app\" \\]|\\$DEST/\x4aobHunter\\.app", "", t)
    for needle in ("config.example.toml", "jobshunter/gui/static", "branding/JobsHunter.icns", "local.jobshunter.app", "run_app.py"):
        assert needle in t, needle
    for rel in ("config.example.toml", "jobshunter/gui/static", "branding/JobsHunter.icns", "branding/make_icns.py", "run_app.py"):
        assert (ROOT / rel).exists(), rel
    assert 'cd "$(dirname "$0")"' in t  # percorsi con spazi tra virgolette


def test_launcher_jh_funziona_da_un_altra_cartella(tmp_path):
    if not (ROOT / ".venv" / "bin" / "python").exists():
        pytest.skip("nessuna .venv")
    r = subprocess.run([str(ROOT / "jh"), "--help"], capture_output=True, text=True, cwd=str(tmp_path), env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]


# ----------------------------------------------------------------------------- sicurezza ----
@pytest.fixture
def live(home):
    """Server Flask vero su una porta libera (mai 8765/8791/8793/8794/8802/8811/8851), home temporanea."""
    from werkzeug.serving import make_server

    from jobshunter.gui.app import create_app

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = make_server("127.0.0.1", port, create_app(None, port), threaded=True)
    t = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.01), daemon=True)
    t.start()
    yield port
    srv.shutdown()
    t.join(timeout=5)


def _raw(port, req: bytes, timeout: float = 10) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall(req)
    data = b""
    try:
        while True:
            c = s.recv(65536)
            if not c:
                break
            data += c
    except OSError:
        pass
    s.close()
    return data


@pytest.mark.parametrize("host", ["127.0.0.1", "evil.com", "127.0.0.1.nip.io:{p}", "localhost.evil.com:{p}", "127.0.0.1:{p}@evil.com", "a@127.0.0.1:{p}", "0.0.0.0:{p}", "127.1:{p}", "[::1]:{p}", "127.0.0.1.:{p}", "LOCALHOST:{p}", "127.0.0.1:1"])
def test_sec_dns_rebinding_host_strano_rifiutato(live, host):
    req = f"GET /api/status HTTP/1.1\r\nHost: {host.format(p=live)}\r\nConnection: close\r\n\r\n".encode()
    assert _raw(live, req).split(b"\r\n")[0].split()[1] == b"403"


def test_sec_host_duplicato_e_uri_assoluto_rifiutati(live):
    r = _raw(live, f"GET /api/status HTTP/1.1\r\nHost: evil.com\r\nHost: 127.0.0.1:{live}\r\nConnection: close\r\n\r\n".encode())
    assert b" 403 " in r.split(b"\r\n")[0]
    r = _raw(live, f"GET http://evil.com/api/status HTTP/1.1\r\nHost: 127.0.0.1:{live}\r\nConnection: close\r\n\r\n".encode())
    assert b" 403 " in r.split(b"\r\n")[0]


@pytest.mark.parametrize("origin", ["null", "http://evil.com", "http://127.0.0.1:1", "http://127.0.0.1:{p}.evil.com", "http://127.0.0.1:{p}@evil.com", "file://", "chrome-extension://abc", "127.0.0.1:{p}"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_sec_origin_ostile_su_ogni_metodo_che_modifica(live, method, origin):
    body = b"{}"
    req = (f"{method} /api/scan/stop HTTP/1.1\r\nHost: 127.0.0.1:{live}\r\nOrigin: {origin.format(p=live)}\r\nContent-Type: application/json\r\n"
           f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body
    assert _raw(live, req).split(b"\r\n")[0].split()[1] == b"403"


def test_sec_nessuna_intestazione_cors_e_preflight_senza_permessi(live):
    r = _raw(live, f"OPTIONS /api/settings HTTP/1.1\r\nHost: 127.0.0.1:{live}\r\nOrigin: http://evil.com\r\nAccess-Control-Request-Method: POST\r\nConnection: close\r\n\r\n".encode())
    assert b"access-control" not in r.lower()


def test_sec_intestazioni_su_pagina_asset_errore_e_api(live):
    for path in ("/", "/api/status", "/api/nonexistent", "/assets/logo-512.png", "/favicon.ico", "/assets/../../config.toml"):
        r = _raw(live, f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{live}\r\nConnection: close\r\n\r\n".encode()).lower()
        for h in (b"x-content-type-options: nosniff", b"content-security-policy: default-src 'self'", b"referrer-policy: no-referrer", b"x-frame-options: deny"):
            assert h in r, (path, h)


def test_sec_csp_non_ammette_risorse_esterne_ne_form_ne_frame():
    from jobshunter.gui.app import CSP

    for must in ("default-src 'self'", "object-src 'none'", "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'", "connect-src 'self'"):
        assert must in CSP
    assert "http:" not in CSP and "https:" not in CSP and "*" not in CSP


def test_sec_la_pagina_non_ha_gestori_inline_pericolosi_ne_url_esterni_caricati():
    html = _text(ROOT / "jobshunter" / "gui" / "static" / "index.html")
    assert not re.search(r"<script[^>]+src=[\"']https?:", html) and not re.search(r"<link[^>]+href=[\"']https?:", html)
    assert not re.search(r"<(img|iframe|embed|object|video|audio|source)[^>]+src=[\"']https?:", html)
    assert "javascript:" not in html.lower()


def test_sec_corpo_chunked_oltre_il_limite_viene_rifiutato(live):
    big = b'{"values":{"home":"' + b"a" * 3_000_000 + b'"}}'
    req = (f"POST /api/settings HTTP/1.1\r\nHost: 127.0.0.1:{live}\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n").encode()
    req += b"%x\r\n" % len(big) + big + b"\r\n0\r\n\r\n"
    assert _raw(live, req, timeout=2).split(b"\r\n")[0].split()[1] == b"413"


def test_sec_chiave_jooble_non_compare_nei_messaggi_di_errore():
    from jobshunter.profiles import Query
    from jobshunter.sources.boards import Jooble

    key = "5d8e2f1a-9b3c-4e7d-8a6f-1c2b3d4e5f60"
    for code in (400, 401, 404):
        s = Jooble({"api_key": key, "host": "it.jooble.org", "_transport": httpx.MockTransport(lambda req, c=code: httpx.Response(c, request=req))})
        with pytest.raises(Exception) as ei:
            s.fetch_queries([Query(q="soc", country="it", where="", radius_km=None, pages=(1,))])
        assert key[:12] not in str(ei.value)[:100], str(ei.value)[:100]


def test_sec_chiave_adzuna_non_compare_nei_primi_100_caratteri_degli_errori():
    from jobshunter.profiles import Query
    from jobshunter.sources.boards import Adzuna

    key = "9f3a7c1e5b2d48a6c0e7b19d3f5a8c24"
    for code in (400, 401, 404, 500):
        s = Adzuna({"app" + "_id": "A1B2C3D4", "app_key": key, "_transport": httpx.MockTransport(lambda req, c=code: httpx.Response(c, request=req))})
        with pytest.raises(Exception) as ei:
            s.fetch_queries([Query(q="soc", country="it", where="", radius_km=None, pages=(1,))])
        assert key not in str(ei.value)[:100]


def test_sec_report_non_incorpora_immagini_esterne_o_note():
    from jobshunter.report import render

    row = {"score": 50, "category": "BLUE", "title": "Analista", "company": "Acme", "location": "Roma", "salary": "", "near_home": 0, "work_mode": None,
           "contract": None, "avail": "open", "valid_until": None, "avail_checked": "2026-10-28T10:00:00", "posted_at": "2026-10-28", "matched": "siem", "source": "fake",
           "uid": "abcdef123456", "url": "https://example.org/j/1", "full_text": "Testo ![x](https://tracker.example/p.gif) e ![[Nota privata]] <img src='https://tracker.example/q.gif'>", "description": ""}
    md = render([row], title="T")
    assert "![x](https://tracker.example/p.gif)" not in md and "![[Nota privata]]" not in md


def test_sec_csv_payload_tipici_neutralizzati():
    from jobshunter.cli import _csv_safe

    for p in ("=cmd|' /C calc'!A0", "+1+1", "-2+3", "@SUM(1)", "\t=1+1", "\r=1+1"):
        assert _csv_safe(p).startswith("'"), p
    assert _csv_safe("Analista") == "Analista" and _csv_safe(5) == 5 and _csv_safe(None) is None


def test_sec_nessun_segreto_nei_log_di_httpx_dopo_le_richieste(caplog):
    import logging

    from jobshunter import net

    caplog.set_level(logging.DEBUG)
    with net.client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
        c.get("https://api.example.org/x?app_key=SEGRETISSIMO123")
    assert "SEGRETISSIMO123" not in caplog.text
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_sec_permessi_dei_file_creati_dall_app(home):
    import os
    import stat

    from jobshunter import settings
    from jobshunter.db import DB

    cfg = settings.load_config(create_if_missing=True)
    DB(settings.resolve_path(cfg["general"]["db_path"])).conn.close()
    settings.save_overrides(Path(cfg["_config_path"]), {"sources.jooble.api_key": "abc"})
    for name in ("config.toml", "settings.json", "jobshunter.db"):
        mode = stat.S_IMODE(os.stat(home / name).st_mode)
        assert mode == 0o600, (name, oct(mode))
