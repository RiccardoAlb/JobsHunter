"""Fase 9: pacchetti scaricabili. Controlli statici su release.yml e sugli script, pianificazione da pacchetto (sys.frozen simulato),
test di fumo `--smoke` e coerenza di versione. Nessuna rete; PyInstaller non serve (i pacchetti veri li prova la CI di rilascio)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import t
from jobshunter import __version__, osinfo, scheduler, settings
from test_portability_schedule import as_system, fake, linux_cron, linux_systemd, windows, xml_of  # noqa: F401  (fixture e aiuti condivisi)

ROOT = Path(__file__).resolve().parent.parent.parent
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
SPEC = (ROOT / "packaging" / "JobsHunter.spec").read_text(encoding="utf-8")


def child_home_env(home: Path) -> dict:
    return {"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "AppData" / "Roaming"), "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "XDG_DATA_HOME": str(home / ".local" / "share"), "XDG_STATE_HOME": str(home / ".local" / "state"), "XDG_CONFIG_HOME": str(home / ".config")}


# ------------------------------------------------------------------ release.yml ----
def test_release_trigger_tag_e_avvio_manuale_con_casella_bozza():
    assert re.search(r'push:\s*\n\s*tags:\s*\n\s*- "v\*\.\*\.\*"', RELEASE)
    assert "workflow_dispatch:" in RELEASE
    m = re.search(r"bozza:\n(.*?)\n\njobs:", RELEASE, re.S) or re.search(r"bozza:\n(.*?)\npermissions:", RELEASE, re.S)
    assert m and "type: boolean" in m.group(1) and "default: true" in m.group(1)
    assert "pull_request" not in RELEASE.split("jobs:")[0]  # nessun trigger da pull request


def test_release_permessi_minimi_e_scrittura_solo_nel_job_della_bozza():
    assert re.search(r"^permissions:\n  contents: read\n", RELEASE, re.M)
    assert RELEASE.count("contents: write") == 1
    i = RELEASE.index("contents: write")
    assert RELEASE.rindex("\n  bozza:", 0, i) > RELEASE.rindex("\n  build:", 0, i)  # sta dentro il job `bozza`, non in `build`
    assert "id-token" not in RELEASE and "packages: write" not in RELEASE


def test_release_matrice_python_fisso_e_cache():
    for runner in ("macos-14", "windows-latest", "ubuntu-22.04", "ubuntu-22.04-arm"):
        assert f"os: {runner}" in RELEASE
    ids = re.findall(r"^\s+id: (\S+)$", RELEASE, re.M)
    assert ids == ["macos", "windows", "linux-amd64", "linux-arm64"] and "pacchetto-${{ matrix.id }}" in RELEASE  # nomi di artefatto distinti
    assert RELEASE.count('python-version: "3.13"') == 2 and "cache: pip" in RELEASE
    assert "latest" not in RELEASE.replace("windows-latest", "")  # nessun "latest" ambiguo oltre a windows-latest


def test_release_azioni_bloccate_a_una_versione_precisa():
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", RELEASE, re.M)
    assert uses
    for u in uses:
        assert re.fullmatch(r"[\w./-]+@(v\d+\.\d+\.\d+|[0-9a-f]{40})", u), u
    assert not re.search(r"@(main|master|v\d+)\s*$", RELEASE, re.M)


def test_release_nessun_rischio_di_iniezione_ne_scarichi_pericolosi():
    assert "pull_request_target" not in RELEASE
    assert not re.search(r"(curl|wget)[^\n|]*\|\s*(ba|z)?sh", RELEASE)
    # nessuna espressione ${{ }} dentro i comandi di shell: i valori arrivano da `env:`
    in_run, run_indent = False, 0
    for line in RELEASE.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if in_run and stripped and indent <= run_indent:
            in_run = False
        if re.match(r"^\s*(- )?run:", line):
            in_run, run_indent = True, indent
            if "${{" in line:
                pytest.fail(f"espressione dentro un run: {line}")
            continue
        if in_run and "${{" in line:
            pytest.fail(f"espressione dentro un run: {line}")
    for secret in re.findall(r"secrets\.(\w+)", RELEASE):
        assert secret == "GITHUB_TOKEN"


def test_release_non_gira_sui_fork_e_ha_il_passo_di_fumo():
    assert RELEASE.count("github.event.repository.fork == false") == 2
    assert RELEASE.lower().count("test di fumo") >= 4  # macOS, Windows, .deb e AppImage
    assert "build_mac.sh" in RELEASE and "build_windows.ps1" in RELEASE and "build_linux.sh" in RELEASE


def test_release_crea_solo_una_bozza_e_non_pubblica_mai():
    assert "gh release create" in RELEASE and "--draft" in RELEASE
    for bad in ("gh release edit", "--draft=false", "--latest", "publish", "prerelease: false", "softprops", "release-action"):
        assert bad not in RELEASE, bad
    assert "SHA256SUMS.txt" in RELEASE and "release_notes.py" in RELEASE
    assert "Il workflow NON pubblica mai" in RELEASE


def test_release_il_tag_deve_coincidere_con_la_versione():
    assert 'if [ "$TAG" != "v$VER" ]' in RELEASE and "TAG: ${{ github.ref_name }}" in RELEASE


def test_ci_yml_non_e_stato_toccato_dalla_fase_9():
    assert CI.startswith("name: CI") and "release" not in CI.lower()
    assert "build_mac" not in CI and "pyinstaller" not in CI.lower()


# ------------------------------------------------------------ script e specifica ----
SCRIPTS = ["build_mac.sh", "smoke.sh", "build_linux.sh", "smoke_deb.sh"]


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_sh_sicuri_e_leggibili(name):
    s = (ROOT / "packaging" / name).read_text(encoding="utf-8")
    assert s.startswith("#!/bin/sh") and "set -e" in s
    for target in (x.rstrip("'") for x in re.findall(r"rm -rf (\S+)", s)):
        assert re.fullmatch(r'"\$\{[A-Z]+:\?\}"', target), f"rm -rf senza protezione: {target}"  # mai `rm -rf "$VAR"` che puo' espandersi a vuoto
    for target in re.findall(r"rm -f (\S+)", s):
        assert ":?" in target, target
    assert "curl | sh" not in s
    assert ("sudo" in s) == (name == "smoke_deb.sh")  # sudo solo dove si installa un pacchetto, e li' solo in CI o con --yes
    assert "\r" not in s


def test_script_windows_ascii_e_con_fumo():
    for name in ("build_windows.ps1", "smoke_windows.ps1"):
        raw = (ROOT / "packaging" / name).read_bytes()
        raw.decode("ascii")  # Windows PowerShell 5.1 legge i file senza BOM in ANSI: solo ASCII
    s = (ROOT / "packaging" / "build_windows.ps1").read_text(encoding="ascii")
    assert "$ErrorActionPreference = \"Stop\"" in s and "smoke_windows.ps1" in s and "JobsHunter.spec" in s
    assert "ZipFile]::CreateFromDirectory" in s and "-Setup.exe" in s and "iscc" in s.lower()
    sm = (ROOT / "packaging" / "smoke_windows.ps1").read_text(encoding="ascii")
    assert "--smoke" in sm and "--smoke-log" in sm and "exit 1" in sm


def test_script_mac_usa_la_stessa_specifica_della_ci():
    s = (ROOT / "packaging" / "build_mac.sh").read_text(encoding="utf-8")
    assert "packaging/JobsHunter.spec" in s and "smoke.sh" in s and "--no-smoke" in s and "--out" in s


def test_spec_include_il_necessario_e_niente_di_personale():
    datas = re.search(r"datas = \[(.*?)\n\]", SPEC, re.S).group(1)
    for needle in ("config.example.toml", "jobshunter\" / \"gui\" / \"static", "cities15000.json", "countries.json"):
        assert needle in datas, needle
    assert len(re.findall(r"^\s*\(str\(", datas, re.M)) == 4  # solo questi quattro: nient'altro viene copiato
    for bad in ("config.toml\"", ".db", "settings.json", "cv.json", "reports", "tests", "dev-notes", ".env", "docs"):
        assert bad not in datas, bad
    assert 'hiddenimports = ["pypdf", "cryptography"]' in SPEC and "collect_submodules(\"pypdf\")" in SPEC
    assert "run_app.py" in SPEC and "console=IS_LINUX" in SPEC and "upx=False" in SPEC
    assert "excludes.append(\"webview\")" in SPEC and "IS_LINUX" in SPEC  # su Linux la finestra nativa e' del sistema
    for mod in ("tkinter", "matplotlib", "numpy", "pytest"):
        assert f'"{mod}"' in SPEC
    assert "bundle_identifier=\"local.jobshunter.app\"" in SPEC and "CFBundleShortVersionString" in SPEC


def test_spec_non_e_python_rotto():
    import ast

    ast.parse(SPEC, feature_version=(3, 11))


def test_icone_e_file_di_versione_di_windows():
    assert (ROOT / "branding" / "JobsHunter.icns").stat().st_size > 1000
    assert (ROOT / "branding" / "JobsHunter.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert (ROOT / "branding" / "JobsHunter.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import versioninfo
    finally:
        sys.path.pop(0)
    assert versioninfo.parse("0.4.0") == (0, 4, 0, 0)
    txt = versioninfo.render("0.4.0")
    assert "filevers=(0, 4, 0, 0)" in txt and "'FileVersion', '0.4.0'" in txt and "JobsHunter.exe" in txt
    assert not re.search(r"@|/Users/|\\Users\\", txt)  # niente indirizzi o percorsi personali
    import ast

    ast.parse(txt.split("\n", 1)[1], feature_version=(3, 11))


def test_inno_setup_per_utente_senza_amministratore():
    iss = (ROOT / "packaging" / "JobsHunter.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss and "{localappdata}" in iss and "{autoprograms}" in iss
    assert "UninstallDisplayIcon" in iss and "AppVersion" in iss
    assert "{userappdata}" not in iss.split("[Files]")[1].split("[Icons]")[0]  # i dati dell'utente non fanno parte dell'installazione


def test_il_vecchio_script_mac_non_e_stato_cambiato_nel_comportamento():
    s = (ROOT / "build_mac_app.sh").read_text(encoding="utf-8")
    assert "$HOME/Applications" in s and "codesign" in s


# ------------------------------------------------------------------- versione ----
def test_versione_coerente_ovunque():
    import tomllib

    assert __version__ == "0.4.0"
    assert tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] == __version__
    first = re.search(r"^## \[([^\]]+)\] - (\S+)", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    assert first.group(1) == __version__ and re.fullmatch(r"\d{4}-\d{2}-\d{2}", first.group(2))
    assert f"Versione {__version__}" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Version {__version__}" in (ROOT / "README.en.md").read_text(encoding="utf-8")
    assert f"JobsHunter/{__version__} (+" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_note_della_release_dal_changelog():
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import release_notes
    finally:
        sys.path.pop(0)
    text = "# C\n\n## [1.2.0] - 2026-01-01\n\nNovita'.\n\n### Aggiunto\n- cosa\n\n## [1.1.0] - 2025-01-01\n\nVecchio.\n"
    assert release_notes.section(text, "1.2.0").startswith("Novita'.") and "Vecchio" not in release_notes.section(text, "1.2.0")
    assert release_notes.section(text, "9.9.9") == ""
    assert release_notes.section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), __version__)  # la versione corrente ha le sue note
    r = subprocess.run([sys.executable, str(ROOT / "packaging" / "release_notes.py"), __version__], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0 and r.stdout.strip()
    assert subprocess.run([sys.executable, str(ROOT / "packaging" / "release_notes.py"), "0.0.1"], capture_output=True).returncode == 1
    assert subprocess.run([sys.executable, str(ROOT / "packaging" / "release_notes.py"), "x; rm"], capture_output=True).returncode == 2


# --------------------------------------------------------------------- --smoke ----
def test_run_app_gestisce_smoke_prima_di_tutto():
    src = (ROOT / "run_app.py").read_text(encoding="utf-8")
    assert src.index('"--smoke"') < src.index('"--scan-once"') and "smoke_main(sys.argv)" in src


def test_smoke_come_sottoprocesso(tmp_path):
    home = tmp_path / "Casa con spazi è"
    home.mkdir()
    data = home / "dati"
    data.mkdir()
    log = tmp_path / "smoke.log"
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env.update(child_home_env(home), JOBSHUNTER_HOME=str(data), PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "run_app.py"), "--smoke", "--smoke-log", str(log)], cwd=tmp_path, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=t(120))
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    assert f"JobsHunter {__version__}" in r.stdout and "RISULTATO: tutto bene" in r.stdout and "FAIL" not in r.stdout
    assert log.read_text(encoding="utf-8").strip().endswith("RISULTATO: tutto bene")
    assert list(data.iterdir()) == []  # la prova usa una cartella temporanea sua: i dati indicati non si toccano


def test_smoke_in_processo_ripristina_l_ambiente(monkeypatch, tmp_path, capsys):
    from jobshunter import smoke

    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path))
    log = tmp_path / "s.log"
    assert smoke.main(["x", "--smoke-log", str(log)]) == 0
    assert os.environ["JOBSHUNTER_HOME"] == str(tmp_path)
    assert "RISULTATO: tutto bene" in log.read_text(encoding="utf-8") and "versione nell'app" in capsys.readouterr().out


def test_smoke_fallisce_con_codice_diverso_da_zero_se_manca_un_pezzo(monkeypatch, tmp_path):
    from jobshunter import smoke

    monkeypatch.setattr(settings, "bundled_root", lambda: tmp_path / "vuota")  # senza config.example.toml
    log = tmp_path / "s.log"
    assert smoke.main(["x", "--smoke-log", str(log)]) == 1
    assert "FAIL config di esempio nel pacchetto" in log.read_text(encoding="utf-8")


# ---------------------------------------------------- pianificazione da pacchetto ----
def frozen(monkeypatch, exe):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", exe)


def test_macos_da_pacchetto_launchagent_con_scan_once_e_spazi(monkeypatch):
    exe = "/Applications/Job Hunter prova/JobsHunter.app/Contents/MacOS/JobsHunter"
    frozen(monkeypatch, exe)
    d = scheduler.build_plist("daily", [(9, 0)], 6)
    assert d["ProgramArguments"] == [exe, "--scan-once"]
    assert "PYTHONPATH" not in d["EnvironmentVariables"] and "JOBSHUNTER_HOME" in d["EnvironmentVariables"]
    assert "-m" not in d["ProgramArguments"] and "jobshunter" not in " ".join(d["ProgramArguments"][1:])


def test_windows_da_pacchetto_attivita_con_eseguibile_e_scan_once(windows, monkeypatch):
    exe = r"C:\Program Files\JobsHunter\JobsHunter.exe"
    frozen(monkeypatch, exe)
    scheduler.install("daily", [(9, 0), (18, 0)], 6)
    xml = xml_of(windows.tasks["JobsHunter scan"])
    assert f"<Command>{exe}</Command>" in xml and "<Arguments>--scan-once</Arguments>" in xml
    assert "pythonw" not in xml and "-m jobshunter" not in xml and "--home" not in xml
    assert f"<WorkingDirectory>{Path(exe).parent}</WorkingDirectory>" in xml  # la cartella dell'eseguibile, che esiste di sicuro


def test_windows_da_pacchetto_percorso_con_accenti_e_e_commerciale(windows, monkeypatch):
    exe = r"C:\Users\utente\App & Più\JobsHunter.exe"
    frozen(monkeypatch, exe)
    scheduler.install("daily", [(9, 0)], 6)
    xml = xml_of(windows.tasks["JobsHunter scan"])
    assert "App &amp; Più" in xml and "--scan-once" in xml


def test_linux_da_pacchetto_systemd_con_spazi(linux_systemd, monkeypatch):
    exe = "/opt/Mio Programma/JobsHunter/JobsHunter"
    frozen(monkeypatch, exe)
    scheduler.install("daily", [(9, 0)], 6)
    service = next(p for p in (Path(os.environ["XDG_CONFIG_HOME"]) / "systemd" / "user").glob("*.service")).read_text(encoding="utf-8")
    assert f'ExecStart="{exe}" "--scan-once"' in service
    assert "PYTHONPATH" not in service and "JOBSHUNTER_HOME" in service and "-m" not in service.split("ExecStart=")[1].split("\n")[0]


def test_linux_da_pacchetto_cron_con_spazi(linux_cron, monkeypatch):
    exe = "/opt/Mio Programma/JobsHunter/JobsHunter"
    frozen(monkeypatch, exe)
    scheduler.install("daily", [(9, 0)], 6)
    line = [l for l in linux_cron.cron.splitlines() if "--scan-once" in l][0]
    assert "'/opt/Mio Programma/JobsHunter/JobsHunter' --scan-once" in line and "PYTHONPATH" not in line and "-m jobshunter" not in line


def test_da_sviluppo_non_cambia_nulla(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    cmd = scheduler.command()
    assert cmd[-3:] == ["-m", "jobshunter", "scan-auto"] or cmd[1:] == ["-m", "jobshunter", "scan-auto"]
    assert "PYTHONPATH" in scheduler.build_plist("daily", [(9, 0)], 6)["EnvironmentVariables"]


@pytest.mark.parametrize("system", ["mac", "windows", "linux"])
def test_da_pacchetto_senza_cartella_dati_non_si_scrive_accanto_al_programma(monkeypatch, system, tmp_path):
    """Un programma impacchettato non ha JOBSHUNTER_HOME impostata: i dati vanno nella cartella dell'utente, mai nel pacchetto."""
    monkeypatch.delenv("JOBSHUNTER_HOME", raising=False)
    monkeypatch.delenv("JOB" + "HUNTER_HOME", raising=False)  # la variabile del vecchio nome vale ancora come ripiego
    monkeypatch.setattr(osinfo, "current", lambda platform=None: system)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    frozen(monkeypatch, str(tmp_path / "Programmi" / "JobsHunter" / "JobsHunter"))
    h = settings.home()
    assert h == osinfo.data_dir() and h != settings.SOURCE_ROOT
    assert "Programmi" not in str(h)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert settings.home() == settings.SOURCE_ROOT  # da sviluppo resta la cartella del progetto


def test_primo_avvio_da_pacchetto_crea_il_config_dall_esempio_incluso(monkeypatch, tmp_path):
    """Il pacchetto contiene config.example.toml (bundled_root = _MEIPASS): al primo avvio nasce config.toml nella cartella dati."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.example.toml").write_text((ROOT / "config.example.toml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(settings, "bundled_root", lambda: Path(getattr(sys, "_MEIPASS")))
    data = tmp_path / "Dati utente è"
    monkeypatch.setenv("JOBSHUNTER_HOME", str(data))
    cfg = settings.load_config(create_if_missing=settings.auto_create())
    assert (data / "config.toml").is_file() and cfg["_config_path"] == str(data / "config.toml")
    assert list(bundle.iterdir()) == [bundle / "config.example.toml"]  # niente scritto dentro il pacchetto


# ---------------------------------------------------------------- documentazione ----
def test_readme_sezione_scarica_in_italiano_e_inglese():
    it = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    for text, words in ((it, ("## Scarica", "Apri comunque", "Ulteriori informazioni", "Get-FileHash", "SHA256SUMS", "non notarizzat", "non ancora provato")),
                        (en, ("## Download", "Open Anyway", "More info", "Get-FileHash", "SHA256SUMS", "not notarized", "not yet tried"))):
        for w in words:
            assert w in text, w
    assert "—" not in it and "—" not in en


def test_releasing_md_ha_i_passi_e_lascia_la_pubblicazione_all_utente():
    r = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
    for w in ("pyproject.toml", "CHANGELOG.md", "git tag", "bozza", "SHA256SUMS", "pubblica"):
        assert w in r, w
    assert "—" not in r


def test_gitignore_non_nasconde_la_specifica_e_check_publishable_capisce_le_riammissioni():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import check_publishable as cp
    finally:
        sys.path.pop(0)
    rules = cp._gitignore_rules(ROOT)
    assert cp._ignored("run_app.spec", False, rules) is True  # le specifiche generate da PyInstaller restano ignorate
    assert cp._ignored("packaging/JobsHunter.spec", False, rules) is False  # quella del progetto e' tracciata
    assert cp._ignored("dist-release", True, rules) is True
    assert cp._ignored("x/a.spec", False, ["*.spec", "!x/a.spec"]) is False
    assert cp._ignored("config.toml", False, rules) is True


def test_bridge_non_espone_attributi_pubblici_che_non_siano_funzioni():
    """pywebview esamina ricorsivamente gli attributi pubblici di js_api: `window` (la finestra) su Windows va in ricorsione infinita
    (window.native...Bounds.Empty.Empty...) e blocca l'app. Gli attributi di stato devono essere privati (trattino basso)."""
    from jobshunter import macapp

    b = macapp.Bridge()
    pubblici = [n for n in vars(b) if not n.startswith("_")]
    assert pubblici == [], pubblici
    for n in dir(b):
        if not n.startswith("_"):
            assert callable(getattr(b, n)), n


# ------------------------------------------------------------------- Linux (.deb, AppImage) ----
def _deb_files():
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import deb_files
    finally:
        sys.path.pop(0)
    return deb_files


def test_release_linux_deb_amd64_arm64_e_appimage_con_fumo_e_somme():
    assert "ubuntu-22.04-arm" in RELEASE
    assert "sh packaging/smoke_deb.sh dist-release/jobshunter_*.deb" in RELEASE  # installa, --smoke, apt remove
    assert "--appimage-extract-and-run" in RELEASE
    assert "sha256sum JobsHunter-* jobshunter_*" in RELEASE  # anche i .deb (nome da Debian) entrano in SHA256SUMS.txt
    assert "if: matrix.sistema == 'linux'" in RELEASE
    assert "gh release create" in RELEASE and "--draft" in RELEASE  # sempre e solo bozza


def test_build_linux_sh_deb_e_appimage_senza_curl_pipe_sh():
    sh = (ROOT / "packaging" / "build_linux.sh").read_text(encoding="utf-8")
    for needle in ("dpkg-deb --root-owner-group", "dpkg --print-architecture", "jobshunter_${VER}_${DEB_ARCH}.deb", "deb_files.py",
                   "packaging/JobsHunter.spec", "--appimage-extract-and-run", "sha256sum -c", "[0-9a-f]{64}", "--no-smoke", "--no-appimage", "--out"):
        assert needle in sh, needle
    assert not re.search(r"\|\s*(ba|z)?sh\b", sh.replace("#!/bin/sh", "")) and "sudo" not in sh
    assert '"$MACHINE" = "x86_64"' in sh  # AppImage solo x86_64
    deb = (ROOT / "packaging" / "smoke_deb.sh").read_text(encoding="utf-8")
    for needle in ("apt-get install -y", "jobshunter --smoke", "apt-get remove -y jobshunter", 'CI:-}" != "true"', "--yes", "hicolor"):
        assert needle in deb, needle
    cfg = (ROOT / "packaging" / "appimagetool.txt").read_text(encoding="utf-8")
    assert re.search(r"^url=https://github\.com/AppImage/appimagetool/releases/download/\d+\.\d+\.\d+/", cfg, re.M)
    m = re.search(r"^sha256=(.*)$", cfg, re.M)
    assert m and (m.group(1) == "" or re.fullmatch(r"[0-9a-f]{64}", m.group(1)))  # vuoto (AppImage saltata) o un hash vero, mai inventato


def test_deb_control_e_desktop():
    d = _deb_files()
    c = d.control("0.4.0", "arm64", 123456)
    lines = dict(l.split(": ", 1) for l in c.splitlines() if l and not l.startswith(" "))
    assert lines["Package"] == "jobshunter" and lines["Version"] == "0.4.0" and lines["Architecture"] == "arm64"
    assert lines["Depends"] == "libc6 (>= 2.35)" and lines["Installed-Size"] == "123456" and lines["Section"] == "utils"
    assert "@" in lines["Maintainer"] and lines["Maintainer"].endswith(".invalid>")  # nessun indirizzo vero
    assert c.endswith("\n") and "\nDescription: " in c and not re.search(r"[^\x00-\x7f]", c)
    assert all(l.startswith(" ") for l in c.split("Description:", 1)[1].splitlines()[1:])  # righe di continuazione con spazio iniziale
    for bad in ("1.0", "0.4", "v0.4.0", ""):
        with pytest.raises(ValueError):
            d.control(bad, "amd64", 1)
    with pytest.raises(ValueError):
        d.control("0.4.0", "i386", 1)
    desk = d.desktop()
    kv = dict(l.split("=", 1) for l in desk.splitlines() if "=" in l and not l.startswith("["))
    assert desk.startswith("[Desktop Entry]\n") and kv["Type"] == "Application" and kv["Exec"] == "jobshunter" and kv["Icon"] == "jobshunter"
    assert kv["Terminal"] == "false" and kv["Categories"].endswith(";") and kv["Name"] == "JobsHunter"


def test_deb_postinst_e_prerm_semplici_senza_toccare_la_home():
    d = _deb_files()
    for script in (d.POSTINST, d.PRERM):
        assert script.startswith("#!/bin/sh\nset -e\n") and script.rstrip().endswith("exit 0")
        for bad in ("$HOME", "~/", "/home", "rm -", "curl", "wget", "pip", "systemctl", "crontab", "launchctl"):
            assert bad not in script, bad
    assert 'if [ "$1" = "configure" ]' in d.POSTINST and "|| true" in d.POSTINST  # le cache di sistema sono facoltative


@pytest.mark.skipif(sys.platform.startswith("win"), reason="permessi POSIX (chmod/st_mode) e collegamenti simbolici: il .deb si costruisce solo su Linux")
def test_deb_albero_costruito_da_una_cartella_finta(tmp_path):
    d = _deb_files()
    dist = tmp_path / "dist con spazi"
    (dist / "_internal").mkdir(parents=True)
    (dist / "JobsHunter").write_bytes(b"#!/bin/sh\n")
    (dist / "JobsHunter").chmod(0o755)
    (dist / "_internal" / "dato.json").write_text("{}", encoding="utf-8")
    icon = tmp_path / "icona.png"
    icon.write_bytes(b"\x89PNG\r\n\x1a\n")
    lic = tmp_path / "LICENSE"
    lic.write_text("MIT", encoding="utf-8")
    tree = tmp_path / "albero"
    d.populate(tree, dist, icon, lic, "0.4.0", "amd64")
    rel = {str(p.relative_to(tree)) for p in tree.rglob("*")}
    for needed in ("opt/jobshunter/JobsHunter", "opt/jobshunter/_internal/dato.json", "usr/bin/jobshunter", "usr/share/applications/jobshunter.desktop",
                   "usr/share/icons/hicolor/512x512/apps/jobshunter.png", "usr/share/doc/jobshunter/copyright", "DEBIAN/control", "DEBIAN/postinst", "DEBIAN/prerm"):
        assert needed.replace("/", os.sep) in rel, needed
    assert os.readlink(tree / "usr" / "bin" / "jobshunter") == "/opt/jobshunter/JobsHunter"
    # niente di personale e niente fuori dalle cartelle di sistema previste
    top = {p.name for p in tree.iterdir()}
    assert top == {"opt", "usr", "DEBIAN"}
    assert not any(n in " ".join(rel) for n in ("config.toml", ".db", "cv.json", "settings.json", "home", ".local"))
    if os.name == "posix":
        assert (tree / "opt/jobshunter/JobsHunter").stat().st_mode & 0o777 == 0o755
        assert (tree / "DEBIAN/postinst").stat().st_mode & 0o777 == 0o755 and (tree / "DEBIAN/control").stat().st_mode & 0o777 == 0o644
    assert "Installed-Size: " in (tree / "DEBIAN/control").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        d.populate(tree, dist, icon, lic, "0.4.0", "amd64")  # non sovrascrive un albero gia' pieno


def test_spec_su_linux_senza_webview_e_con_console():
    assert 'excludes.append("webview")' in SPEC and "console=IS_LINUX" in SPEC
    assert "distutils" in SPEC and '"distutils"' not in SPEC.split("excludes = [")[1].split("]")[0]  # B122: non va escluso (l'hook di setuptools vi crea un alias)


def test_bridge_usa_window_con_il_trattino_basso():
    src = (ROOT / "jobshunter" / "macapp.py").read_text(encoding="utf-8")
    assert "self._window = None" in src and "bridge._window = webview.create_window" in src  # B123: pywebview non esamina gli attributi privati
    assert "self.window" not in src and "bridge.window" not in src


def test_readme_linux_deb_e_appimage_in_entrambe_le_lingue():
    it = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    for text in (it, en):
        for w in ("jobshunter_<", "_amd64.deb", "_arm64.deb", "sudo apt install ./", "AppImage", "chmod +x", "sudo apt remove jobshunter", "--appimage-extract-and-run"):
            assert w in text, w
    assert "browser predefinito" in it and "default browser" in en
    assert "in preparazione" not in it.split("## Installazione")[0].split("## Scarica")[1] and "in preparation" not in en.split("## Installation")[0].split("## Download")[1]
