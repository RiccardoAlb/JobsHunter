"""Portabilita' (fase 7): percorsi per sistema, blocco di file, permessi, zone protette, apertura di cartelle, avvio.

Si simulano gli altri sistemi (piattaforma, variabili d'ambiente, PureWindowsPath): nessun test tocca il sistema vero.
Compatibile con Python 3.11 e con macOS, Linux e Windows."""
import multiprocessing
import re
import os
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from cvguard import _cv_guardia  # noqa: F401  (autouse: home temporanea, niente rete)
from jobshunter import filelock, fsperm, macapp, migrate, osinfo, settings

ROOT = Path(__file__).resolve().parent.parent.parent


# ------------------------------------------------------------------ osinfo ----
def test_costanti_coerenti_con_il_sistema_in_uso():
    assert (osinfo.IS_MAC, osinfo.IS_WINDOWS, osinfo.IS_LINUX).count(True) <= 1
    assert osinfo.current() in ("mac", "windows", "linux")
    assert osinfo.current("darwin") == "mac" and osinfo.current("win32") == "windows" and osinfo.current("cygwin") == "windows"
    assert osinfo.current("linux") == "linux" and osinfo.current("freebsd13") == "linux"


def test_macos_invariato():
    h = PurePosixPath("/Users/utente")
    assert osinfo.data_dir(platform="darwin", home=h) == PurePosixPath("/Users/utente/Library/Application Support/JobsHunter")
    assert osinfo.log_dir(platform="darwin", home=h) == PurePosixPath("/Users/utente/Library/Logs/JobsHunter")


def test_windows_con_variabili_d_ambiente_e_spazi_e_accenti():
    h = PureWindowsPath("C:/Users/utente bée")
    env = {"APPDATA": "C:\\Users\\utente bée\\AppData\\Roaming", "LOCALAPPDATA": "D:\\Dati locali\\Ann"}
    assert osinfo.data_dir(platform="win32", env=env, home=h) == PureWindowsPath("C:/Users/utente bée/AppData/Roaming/JobsHunter")
    assert osinfo.log_dir(platform="win32", env=env, home=h) == PureWindowsPath("D:/Dati locali/Ann/JobsHunter/Logs")


def test_windows_senza_variabili_ripiega_sulla_home():
    h = PureWindowsPath("C:/Users/x")
    assert osinfo.data_dir(platform="win32", env={}, home=h) == PureWindowsPath("C:/Users/x/AppData/Roaming/JobsHunter")
    assert osinfo.log_dir(platform="win32", env={}, home=h) == PureWindowsPath("C:/Users/x/AppData/Local/JobsHunter/Logs")


def test_linux_xdg_e_predefiniti():
    h = PurePosixPath("/home/utente")
    assert osinfo.data_dir(platform="linux", env={}, home=h) == PurePosixPath("/home/utente/.local/share/jobshunter")
    assert osinfo.log_dir(platform="linux", env={}, home=h) == PurePosixPath("/home/utente/.local/state/jobshunter")
    env = {"XDG_DATA_HOME": "/dati/xdg", "XDG_STATE_HOME": "/stato"}
    assert osinfo.data_dir(platform="linux", env=env, home=h) == PurePosixPath("/dati/xdg/jobshunter")
    assert osinfo.log_dir(platform="linux", env=env, home=h) == PurePosixPath("/stato/jobshunter")
    rel = {"XDG_DATA_HOME": "relativo"}  # le specifiche XDG vogliono percorsi assoluti: uno relativo si ignora
    assert osinfo.data_dir(platform="linux", env=rel, home=h) == PurePosixPath("/home/utente/.local/share/jobshunter")


def test_cartella_report_predefinita():
    assert osinfo.default_report_dir(platform="win32", home=PureWindowsPath("C:/Users/x")) == PureWindowsPath("C:/Users/x/Documents/JobsHunter")
    assert osinfo.default_report_dir(platform="linux", home=PurePosixPath("/home/x")) == PurePosixPath("/home/x/Documents/JobsHunter")


def test_jobshunter_home_ha_la_precedenza(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "mia"))
    assert settings.home() == tmp_path / "mia"


def test_migrazione_del_vecchio_nome_solo_su_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(migrate.osinfo, "data_dir", lambda name="JobsHunter", **k: tmp_path / "dati" / name)
    d, outcome = migrate.migrate_app_data()
    assert d == tmp_path / "dati" / "JobsHunter" and outcome == "fresh"
    (d).mkdir(parents=True)
    (d / "config.toml").write_text("x", encoding="utf-8")
    assert migrate.migrate_app_data()[1] == "new"


def test_support_dir_con_home_esplicita_resta_quella_di_macos(tmp_path):
    assert migrate.support_dir(home=tmp_path) == tmp_path / "Library" / "Application Support" / "JobsHunter"
    assert migrate.log_dir(home=tmp_path) == tmp_path / "Library" / "Logs" / "JobsHunter"


def test_nessun_percorso_di_macos_nei_default_del_codice():
    for f in ("osinfo.py", "filelock.py", "fsperm.py"):
        src = (ROOT / "jobshunter" / f).read_text(encoding="utf-8")
        assert "/Users/" not in src


# ---------------------------------------------------------------- filelock ----
def test_un_solo_import_di_fcntl_e_msvcrt():
    bad = []
    for p in (ROOT / "jobshunter").rglob("*.py"):
        if p.name == "filelock.py":
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(("import fcntl", "import msvcrt", "from fcntl", "from msvcrt")):
                bad.append(str(p))
    assert not bad, bad


def test_blocco_esclusivo_non_bloccante(tmp_path):
    a, b = filelock.FileLock(tmp_path / "x.lock"), filelock.FileLock(tmp_path / "x.lock")
    assert a.acquire(blocking=False) is True and a.held
    assert b.acquire(blocking=False) is False and not b.held
    a.release()
    assert not a.held
    assert b.acquire(blocking=False) is True
    b.release()
    b.release()  # rilasciare due volte non da' errore


def test_blocco_con_attesa_tra_thread(tmp_path):
    first = filelock.FileLock(tmp_path / "w.lock")
    assert first.acquire()
    got = []

    def second():
        with filelock.FileLock(tmp_path / "w.lock"):
            got.append(time.time())

    t0 = time.time()
    th = threading.Thread(target=second)
    th.start()
    time.sleep(0.4)
    assert not got  # ancora in attesa
    first.release()
    th.join(10)
    assert got and got[0] - t0 >= 0.35


def _hold(path, ready, release):
    from jobshunter.filelock import FileLock

    lk = FileLock(path)
    assert lk.acquire(blocking=False)
    ready.set()
    release.wait(20)
    lk.release()


def test_blocco_tra_due_processi(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    p = ctx.Process(target=_hold, args=(str(tmp_path / "p.lock"), ready, release))
    p.start()
    try:
        assert ready.wait(30)
        me = filelock.FileLock(tmp_path / "p.lock")
        assert me.acquire(blocking=False) is False  # lo tiene l'altro processo
        release.set()
        p.join(20)
        assert me.acquire(blocking=False) is True  # il blocco cade quando l'altro lo rilascia
        me.release()
    finally:
        release.set()
        if p.is_alive():
            p.join(5)
            if p.is_alive():
                p.kill()


def test_scan_lock_usa_il_blocco_portabile(home):
    from jobshunter.autoscan import ScanLock

    a, b = ScanLock(), ScanLock()
    assert a.acquire() is True and b.acquire() is False
    a.release()
    assert b.acquire() is True
    b.release()


def test_blocco_in_cartella_non_scrivibile_non_solleva(tmp_path):
    f = tmp_path / "file"
    f.write_text("x", encoding="utf-8")
    with filelock.FileLock(f / "sotto.lock") as lk:  # il genitore e' un file: niente blocco, nessun errore
        assert not lk.held


# ------------------------------------------------------------------ fsperm ----
@pytest.mark.skipif(sys.platform.startswith("win"), reason="i permessi POSIX non esistono su Windows (li copre il test di icacls)")
def test_secure_file_e_dir_posix(tmp_path):
    f = tmp_path / "a.db"
    f.write_text("x", encoding="utf-8")
    d = tmp_path / "cartella"
    d.mkdir()
    assert fsperm.secure_file(f) is True and (f.stat().st_mode & 0o777) == 0o600
    assert fsperm.secure_dir(d) is True and (d.stat().st_mode & 0o777) == 0o700


def test_secure_non_solleva_mai(tmp_path):
    assert fsperm.secure_file(tmp_path / "non_esiste") is False
    assert fsperm.secure_dir(tmp_path / "neppure") is False
    assert fsperm.secure_file(None) is False


def test_windows_usa_icacls_prima_concede_poi_toglie_l_ereditarieta(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: None)  # su un Windows vero whoami partirebbe davvero
    monkeypatch.setattr(fsperm.subprocess, "run", fake_run)
    monkeypatch.setenv("USERNAME", "utente")
    monkeypatch.setenv("USERDOMAIN", "PC")
    f = tmp_path / "x.db"
    f.write_text("x", encoding="utf-8")
    assert fsperm.secure_file(f) is True
    assert calls[0][0] == "icacls" and calls[0][2] == "/grant:r" and calls[0][3] == "PC\\utente:F"
    assert calls[1][2] == "/inheritance:r"
    calls.clear()
    assert fsperm.secure_dir(tmp_path) is True and calls[0][3] == "PC\\utente:(OI)(CI)F"


def test_windows_icacls_che_fallisce_non_toglie_l_accesso_e_non_solleva(monkeypatch, tmp_path, caplog):
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 5, "", "accesso negato")

    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: None)  # su un Windows vero whoami partirebbe davvero
    monkeypatch.setattr(fsperm.subprocess, "run", fake_run)
    monkeypatch.setattr(fsperm, "_warned", [False])
    monkeypatch.setenv("USERNAME", "utente")
    (tmp_path / "x").write_text("x", encoding="utf-8")
    (tmp_path / "y").write_text("y", encoding="utf-8")
    assert fsperm.secure_file(tmp_path / "x") is False
    assert len(calls) == 1 and calls[0][2] == "/grant:r"  # la concessione e' fallita: l'ereditarieta' non si tocca
    fsperm.secure_file(tmp_path / "y")
    assert sum("icacls" in r.getMessage() for r in caplog.records) <= 1  # l'avviso si scrive una volta sola


def test_windows_icacls_assente_non_solleva(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("icacls")

    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: None)  # su un Windows vero whoami partirebbe davvero
    monkeypatch.setattr(fsperm.subprocess, "run", boom)
    monkeypatch.setenv("USERNAME", "utente")
    assert fsperm.secure_file(tmp_path / "x") is False


def test_i_dati_veri_restano_protetti_su_posix(home):
    if sys.platform.startswith("win"):
        pytest.skip("permessi POSIX")
    cfg = settings.load_config(create_if_missing=True)
    assert (Path(cfg["_config_path"]).stat().st_mode & 0o777) == 0o600
    settings.save_overrides(Path(cfg["_config_path"]), {"general.min_score": 20})
    assert (settings.overrides_path(Path(cfg["_config_path"])).stat().st_mode & 0o777) == 0o600


# ------------------------------------------------- zone protette dei report ----
WENV = {"SystemRoot": "C:\\Windows", "ProgramFiles": "C:\\Program Files", "ProgramFiles(x86)": "C:\\Program Files (x86)", "ProgramData": "C:\\ProgramData",
        "APPDATA": "C:\\Users\\utente bée\\AppData\\Roaming", "LOCALAPPDATA": "C:\\Users\\utente bée\\AppData\\Local", "SystemDrive": "C:"}
WHOME = PureWindowsPath("C:\\Users\\utente bée")
WTEMP = ["C:\\Users\\utente bée\\AppData\\Local\\Temp"]


@pytest.mark.parametrize("path", [
    "C:\\Windows", "c:\\WINDOWS\\System32", "C:\\Program Files\\App", "C:\\Program Files (x86)\\Qualcosa", "c:\\programdata\\x", "C:\\", "D:\\", "\\\\server\\condivisione\\report",
    "C:\\Users\\utente bée\\AppData\\Roaming\\JobsHunter", "C:\\Users\\utente bée\\AppData\\Local\\Programs", "C:\\Users\\utente bée\\.ssh", "C:\\Users\\utente bée\\.ssh\\keys",
    "c:\\users\\utente bée\\.GNUPG", "C:\\Users\\utente bée\\.aws"])
def test_windows_zone_protette(path):
    assert settings._win_protected(PureWindowsPath(path), WHOME, WENV, WTEMP) is True


@pytest.mark.parametrize("path", [
    "C:\\Users\\utente bée\\Documents\\Report JH", "D:\\Lavori\\Résumé", "C:\\jh\\reports", "E:\\Obsidian\\Vault\\JobsHunter", "C:\\Users\\utente bée\\Desktop",
    "C:\\Users\\utente bée\\AppData\\Local\\Temp\\pytest-1\\x", "C:\\Dati"])
def test_windows_cartelle_ammesse(path):
    assert settings._win_protected(PureWindowsPath(path), WHOME, WENV, WTEMP) is False


def test_windows_prefisso_esteso_e_rete():
    assert settings._strip_win_prefix("\\\\?\\C:\\Windows") == "C:\\Windows"
    assert settings._strip_win_prefix("\\\\?\\UNC\\srv\\share") == "\\\\srv\\share"
    assert settings._win_protected(PureWindowsPath(settings._strip_win_prefix("\\\\?\\UNC\\srv\\share\\x")), WHOME, WENV, WTEMP) is True


@pytest.mark.parametrize("path", ["/etc", "/etc/ssh", "/usr/local", "/bin", "/sbin", "/var/lib", "/sys", "/proc", "/boot", "/dev", "/root/x", "/opt/app", "/"])
def test_linux_zone_protette(path):
    assert settings._posix_protected(path, "/home/utente", "linux") is True


@pytest.mark.parametrize("path", ["/home/utente/Documents/report", "/home/utente", "/tmp/pytest-1/x", "/mnt/dati/report", "/media/utente/usb/report", "/srv"])
def test_linux_cartelle_ammesse(path):
    assert settings._posix_protected(path, "/home/utente", "linux") is False


def test_linux_zone_sensibili_della_home():
    for sub in (".ssh", ".gnupg", ".aws", ".config"):
        assert settings._posix_protected("/home/utente/" + sub + "/x", "/home/utente", "linux") is True


def test_linux_home_di_root_ammessa_ma_non_le_sue_chiavi():
    assert settings._posix_protected("/root/report", "/root", "linux") is False
    assert settings._posix_protected("/root/.ssh", "/root", "linux") is True
    assert settings._posix_protected("/root/report", "/home/utente", "linux") is True


def test_macos_senza_distinguere_maiuscole():
    assert settings._posix_protected("/SYSTEM/x", "/Users/utente", "mac") is True
    assert settings._posix_protected("/users/utente/library/launchagents/x", "/Users/utente", "mac") is True
    assert settings._posix_protected("/Users/utente/Documents/x", "/Users/utente", "mac") is False
    assert settings._posix_protected("/private/tmp/x", "/Users/utente", "mac") is False
    assert settings._posix_protected("/Volumes/Dati/x", "/Users/utente", "mac") is False
    assert settings._posix_protected("/Applications/x", "/Users/utente", "mac") is True


def test_check_report_dir_reale_resta_in_italiano(tmp_path):
    settings.check_report_dir(str(tmp_path / "ok"))
    with pytest.raises(ValueError) as e:
        settings.check_report_dir("../fuori")
    assert "percorso non valido" in str(e.value)
    with pytest.raises(ValueError):
        settings.check_report_dir("a\x00b")
    sys_dir = "C:\\Windows" if sys.platform.startswith("win") else "/etc"
    with pytest.raises(ValueError) as e:
        settings.check_report_dir(sys_dir)
    assert "zona di sistema" in str(e.value)


def test_check_report_dir_windows_simulato_rifiuta_unc(monkeypatch):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    with pytest.raises(ValueError) as e:
        settings.check_report_dir("\\\\server\\share\\report")
    assert "rete" in str(e.value)


# ------------------------------------------------------- config con percorsi ----
def test_config_toml_con_percorsi_windows_in_stringa_letterale(home):
    (home / "config.toml").write_text((ROOT / "config.example.toml").read_text(encoding="utf-8")
                                       .replace('dir = "reports"', "dir = 'D:\\Lavori\\Résumé e Report'"), encoding="utf-8")
    cfg = settings.load_config()
    assert cfg["report"]["dir"] == "D:\\Lavori\\Résumé e Report"


def test_impostazioni_con_percorso_windows_si_salvano_e_rileggono(home):
    cfg = settings.load_config(create_if_missing=True)
    p = Path(cfg["_config_path"])
    settings.save_overrides(p, {"report.dir": "D:\\Lavori\\Résumé e Report"})
    assert settings.load_config()["report"]["dir"] == "D:\\Lavori\\Résumé e Report"
    raw = settings.overrides_path(p).read_text(encoding="utf-8")
    assert "Résumé" in raw  # UTF-8 su disco, qualunque sia la codifica predefinita del sistema


def test_config_e_json_si_leggono_sempre_in_utf8(home, monkeypatch):
    import locale

    monkeypatch.setattr(locale, "getpreferredencoding", lambda *a, **k: "cp1252")
    cfg = settings.load_config(create_if_missing=True)
    settings.save_overrides(Path(cfg["_config_path"]), {"home": "Forlì"})
    assert settings.load_config()["sources"]["adzuna"]["home"] == "Forlì"


def encoding_violations(root) -> list[str]:
    """Chiamate che aprono file di TESTO senza codifica esplicita, trovate leggendo l'albero sintattico (non il testo delle righe):
    `open`, `io.open`, `Path(...).open`, `os.fdopen`, `read_text`, `write_text`, `logging.FileHandler`, anche su piu' righe;
    una parola "encoding" in un commento non conta. I file in modalita' binaria sono esclusi."""
    import ast

    out = []
    files = list((Path(root) / "jobshunter").rglob("*.py")) + list((Path(root) / "scripts").glob("*.py")) + [Path(root) / "run_app.py"]
    for p in files:
        if not p.is_file():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            owner = f.value if isinstance(f, ast.Attribute) else None
            # posizione dell'argomento "mode" e di "encoding" per ogni tipo di chiamata
            if name == "open" and owner is None:
                mode_pos, enc_pos = 1, 3
            elif name == "open" and isinstance(owner, ast.Name) and owner.id == "io":
                mode_pos, enc_pos = 1, 3
            elif name == "open" and isinstance(owner, ast.Call) and getattr(owner.func, "id", getattr(owner.func, "attr", "")) in ("Path", "PurePath"):
                mode_pos, enc_pos = 0, 2
            elif name == "fdopen":
                mode_pos, enc_pos = 1, 3
            elif name == "read_text":
                mode_pos, enc_pos = None, 0
            elif name == "write_text":
                mode_pos, enc_pos = None, 1
            elif name == "FileHandler":
                mode_pos, enc_pos = 1, 2
            else:
                continue
            mode = None
            if mode_pos is not None:
                if len(node.args) > mode_pos and isinstance(node.args[mode_pos], ast.Constant):
                    mode = node.args[mode_pos].value
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = kw.value.value
            if isinstance(mode, str) and "b" in mode:
                continue
            has_enc = len(node.args) > enc_pos or any(kw.arg == "encoding" for kw in node.keywords)
            if not has_enc:
                out.append(f"{p.name}:{node.lineno}")
    return out


def test_nessuna_lettura_o_scrittura_di_testo_senza_codifica():
    assert not encoding_violations(ROOT), encoding_violations(ROOT)


# ------------------------------------------------------------- apertura cartelle ----
def test_open_path_per_sistema(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(macapp.subprocess, "Popen", lambda cmd, **k: calls.append(cmd))  # lancio staccato (B94)
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "mac")
    assert macapp.open_path(tmp_path) is True and calls[-1] == ["open", str(tmp_path)]
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "linux")
    assert macapp.open_path(tmp_path) is True and calls[-1] == ["xdg-open", str(tmp_path)]
    started = []
    monkeypatch.setattr(macapp.os, "startfile", lambda p: started.append(p), raising=False)
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    assert macapp.open_path(tmp_path) is True and started == [str(tmp_path)]


def test_open_path_non_solleva_mai(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(macapp.subprocess, "Popen", boom)
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "linux")
    assert macapp.open_path(tmp_path) is False


def test_open_url_solo_http_https(monkeypatch):
    opened = []
    monkeypatch.setattr(macapp.webbrowser, "open", lambda u: opened.append(u) or True)
    assert macapp.open_url("https://example.org") is True and macapp.open_url("http://127.0.0.1:8765/") is True
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://x", "", None, 5):
        assert macapp.open_url(bad) is False
    assert opened == ["https://example.org", "http://127.0.0.1:8765/"]


def test_bridge_apre_le_cartelle_con_open_path(monkeypatch, home):
    got = []
    monkeypatch.setattr(macapp, "open_path", lambda p: got.append(Path(p)) or True)
    b = macapp.Bridge()
    assert b.open_folder("data") is True and got[-1] == settings.home()
    assert b.open_folder("reports") is True
    assert b.open_folder("altro") is False


def test_app_senza_pywebview_ripiega_sul_browser(monkeypatch, home):
    import builtins

    real_import = builtins.__import__

    def no_webview(name, *a, **k):
        if name == "webview":
            raise ImportError("niente pywebview")
        return real_import(name, *a, **k)

    seen = {}
    monkeypatch.setattr(macapp, "_start_engine", lambda: 4321)
    monkeypatch.setattr(macapp, "_browser_fallback", lambda port, why: seen.update(port=port, why=why))
    monkeypatch.setattr(builtins, "__import__", no_webview)
    macapp.main()
    monkeypatch.setattr(builtins, "__import__", real_import)
    assert seen["port"] == 4321 and "pywebview" in seen["why"] and "requirements-gui.txt" in seen["why"]


# --------------------------------------------------------------------- avvio ----
def test_jh_bat_e_jh_equivalenti():
    bat = (ROOT / "jh.bat").read_bytes().decode("utf-8")
    assert "\r\n" in bat and ".venv\\Scripts\\python.exe" in bat and "-m jobshunter %*" in bat and "%~dp0" in bat
    sh = (ROOT / "jh").read_text(encoding="utf-8")
    assert "-m jobshunter" in sh and ".venv/bin/python" in sh


def test_requisiti_gui_e_comuni():
    assert "pywebview" in (ROOT / "requirements-gui.txt").read_text(encoding="utf-8")
    common = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "pywebview" not in common and "flask" in common
    assert (ROOT / "requirements-mac.txt").exists()


def test_python_m_jobshunter_parte(tmp_path):
    env = dict(os.environ, JOBSHUNTER_HOME=str(tmp_path / "h"), PYTHONPATH=str(ROOT), PYTHONIOENCODING="cp1252")
    r = subprocess.run([sys.executable, "-m", "jobshunter", "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(tmp_path), timeout=60)
    assert r.returncode == 0 and "JobsHunter" in r.stdout


def test_ensure_utf8_streams_non_solleva():
    osinfo.ensure_utf8_streams()


# ---------------------------------------------------- correzioni dopo il collaudo ----
def test_secure_rifiuta_vuoto_punto_cartelle_e_inesistenti(tmp_path, monkeypatch):
    work = tmp_path / "lavoro"
    work.mkdir()
    monkeypatch.chdir(work)
    before = work.stat().st_mode
    for bad in ("", ".", Path(""), Path("."), "   ", None):
        assert fsperm.secure_file(bad) is False and fsperm.secure_dir(bad) is False
    assert work.stat().st_mode == before
    assert fsperm.secure_file(work) is False  # una cartella non e' un file: niente 600
    assert work.stat().st_mode == before
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    assert fsperm.secure_dir(f) is False and fsperm.secure_file(tmp_path / "manca") is False and fsperm.secure_dir(tmp_path / "manca") is False


def test_linux_home_radice_o_di_sistema_non_ammette_tutto():
    for home in ("/", "//", "/usr", "/etc/x", "/boot"):
        for p in ("/etc/cron.d", "/usr/lib", "/var/spool", "/root"):
            assert settings._posix_protected(p, home, "linux") is True, (home, p)
    assert settings._posix_protected("/var/lib/db/x", "/var/lib/db", "linux") is False  # utente di servizio con home propria


def test_prefisso_esteso_locale_non_e_di_rete(monkeypatch, tmp_path):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(settings, "_win_protected", lambda *a, **k: False)
    try:
        settings.check_report_dir("\\\\?\\C:\\Users\\x\\Documents\\Report")
    except ValueError as e:
        assert "rete" not in str(e)
    with pytest.raises(ValueError) as e:
        settings.check_report_dir("\\\\?\\UNC\\srv\\share\\x")
    assert "rete" in str(e.value)


def test_config_toml_con_backslash_da_messaggio_italiano(home):
    (home / "config.toml").write_text('[report]\ndir = "D:\\Lavori\\Report"\n', encoding="utf-8")
    with pytest.raises(settings.ConfigError) as e:
        settings.load_config()
    msg = str(e.value)
    assert "config.toml" in msg and "apici singoli" in msg and "'D:" in msg
    from click.testing import CliRunner

    from jobshunter.cli import main

    r = CliRunner().invoke(main, ["list"])
    assert r.exit_code == 1 and "apici singoli" in r.output


def test_open_path_staccato_senza_timeout(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(macapp.subprocess, "Popen", lambda cmd, **k: seen.update(cmd=cmd, k=k))
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "linux")
    assert macapp.open_path(tmp_path) is True
    assert seen["k"].get("start_new_session") is True and "timeout" not in seen["k"]


def test_pyproject_dice_tre_sistemi():
    import tomllib

    p = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "Operating System :: Microsoft :: Windows" in p["classifiers"] and "windows" in p["keywords"]


def test_il_controllo_dell_encoding_vede_le_violazioni_vere(tmp_path):
    import shutil

    cases = {
        "Path.open": 'from pathlib import Path\ndef f(p):\n    return Path(p).open("w")\n',
        "io.open": 'import io\ndef f(p):\n    return io.open(p, "w")\n',
        "multiriga": 'from pathlib import Path\ndef f(p, d):\n    Path(p).write_text(\n        d\n    )\n',
        "commento": 'from pathlib import Path\ndef f(p):\n    return Path(p).read_text()  # TODO encoding\n',
        "fdopen": 'import os\ndef f(fd):\n    return os.fdopen(fd, "w")\n',
        "FileHandler": 'import logging\ndef f(p):\n    return logging.FileHandler(p)\n',
        "open": 'def f(p):\n    return open(p)\n',
    }
    for name, code in cases.items():
        root = tmp_path / name.replace(".", "_")
        shutil.copytree(ROOT / "jobshunter", root / "jobshunter", ignore=shutil.ignore_patterns("__pycache__"))
        (root / "jobshunter" / "zz_violazione.py").write_text(code.replace("\\\n", "\n"), encoding="utf-8")
        assert encoding_violations(root), name
    good = tmp_path / "ok"
    shutil.copytree(ROOT / "jobshunter", good / "jobshunter", ignore=shutil.ignore_patterns("__pycache__"))
    (good / "jobshunter" / "zz_ok.py").write_text('import io\ndef f(p):\n    a = io.open(p, "wb")\n    return open(p, "r", encoding="utf-8")\n', encoding="utf-8")
    assert not encoding_violations(good)


# ------------------------------------------- correzioni dopo la prima suite su Windows vero ----
def test_fsutil_riprova_solo_su_windows(monkeypatch, tmp_path):
    from jobshunter import fsutil

    calls = []

    def flaky(*a):
        calls.append(a)
        if len(calls) < 3:
            raise PermissionError("file aperto da un altro processo")
        return "ok"

    monkeypatch.setattr(fsutil.time, "sleep", lambda s: None)
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    assert fsutil.retry(flaky, 1) == "ok" and len(calls) == 3
    calls.clear()
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "linux")
    with pytest.raises(PermissionError):
        fsutil.retry(flaky, 1)  # fuori da Windows nessun nuovo tentativo: comportamento identico a prima
    assert len(calls) == 1


def test_fsutil_windows_si_arrende_dopo_i_tentativi(monkeypatch):
    from jobshunter import fsutil

    monkeypatch.setattr(fsutil.time, "sleep", lambda s: None)
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")

    def always(*a):
        raise PermissionError("bloccato")

    with pytest.raises(PermissionError):
        fsutil.retry(always, tries=3)


def test_fsutil_replace_e_read_text(tmp_path):
    from jobshunter import fsutil

    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("nuovo è", encoding="utf-8")
    b.write_text("vecchio", encoding="utf-8")
    fsutil.replace(a, b)
    assert fsutil.read_text(b) == "nuovo è" and not a.exists()


def test_cv_delete_su_windows_con_file_che_non_si_cancella(monkeypatch, home):
    from jobshunter import cv, fsutil

    cv.save_text("Python SQL Linux Docker Git " * 10, "txt")
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsutil.time, "sleep", lambda s: None)
    monkeypatch.setattr(fsutil, "unlink", lambda *a, **k: (_ for _ in ()).throw(PermissionError("aperto")))
    assert cv.delete() is True  # il contenuto e' azzerato: non e' piu' un CV valido, nessuna eccezione
    assert cv.load() is None


def test_cv_scritture_concorrenti_non_si_pestano(home):
    import threading

    from jobshunter import cv

    errors = []

    def go(i):
        try:
            for _ in range(10):
                cv.save_text(f"Python SQL Linux {i} " * 20, "txt")
                assert cv.load() is not None
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    ts = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    assert not errors, errors[:2]
    assert not list(home.glob(".cv-*.tmp"))


def test_osinfo_linux_simulato_da_windows_usa_percorsi_posix_assoluti():
    h = PurePosixPath("/home/utente")
    assert osinfo.data_dir(platform="linux", env={"XDG_DATA_HOME": "/dati/xdg"}, home=h) == PurePosixPath("/dati/xdg/jobshunter")
    assert osinfo.log_dir(platform="linux", env={"XDG_STATE_HOME": "/stato"}, home=h) == PurePosixPath("/stato/jobshunter")


# ----------------------------------- icacls: utente per SID (bug trovato sul Windows 11 vero) ----
SID = "S-1-5-21-1111111111-2222222222-3333333333-500"


class IcaclsScript:
    """icacls finto: `rcs` e' un dizionario {indice del /grant: codice}; tutto il resto riesce. Registra i comandi."""

    def __init__(self, grant_rcs=(), inherit_rc=0, out=b"\x8dERRORE localizzato cp850\n"):
        self.calls, self.grant_rcs, self.inherit_rc, self.out = [], list(grant_rcs), inherit_rc, out
        self.n_grants = 0

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        assert "text" not in kw and "encoding" not in kw, "l'output di icacls e' OEM: non va decodificato come testo"
        if cmd[2] == "/grant:r":
            rc = self.grant_rcs[self.n_grants] if self.n_grants < len(self.grant_rcs) else 0
            self.n_grants += 1
        elif cmd[2] == "/inheritance:r":
            rc = self.inherit_rc
        else:
            rc = 0
        return subprocess.CompletedProcess(cmd, rc, self.out, b"")


@pytest.fixture
def winuser(monkeypatch, tmp_path):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setenv("USERNAME", "administrator")
    monkeypatch.setenv("USERDOMAIN", "WORKGROUP")
    monkeypatch.setattr(fsperm, "_warned", [False])
    f = tmp_path / "dati.db"
    f.write_text("x", encoding="utf-8")
    return f


def grants(fake):
    return [c[3] for c in fake.calls if c[2] == "/grant:r"]


def test_icacls_usa_il_sid_con_l_asterisco(monkeypatch, winuser):
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: '"laptop-x\\administrator","' + SID + '"\r\n')
    fake = IcaclsScript()
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(winuser) is True
    assert grants(fake) == ["*" + SID + ":F"]
    assert [c[2] for c in fake.calls] == ["/grant:r", "/inheritance:r"]


def test_icacls_cartella_con_sid(monkeypatch, winuser, tmp_path):
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: f'"x\\y","{SID}"')
    fake = IcaclsScript()
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_dir(tmp_path) is True and grants(fake) == ["*" + SID + ":(OI)(CI)F"]


def test_icacls_whoami_che_fallisce_ripiega_su_dominio_e_utente(monkeypatch, winuser):
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: None)
    fake = IcaclsScript()
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(winuser) is True and grants(fake) == ["WORKGROUP\\administrator:F"]


@pytest.mark.parametrize("out", ["", "ERRORE: strumento non trovato", '"x\\y","non-un-sid"', "\"x\\y\"\r\n"])
def test_icacls_whoami_con_output_strano_non_da_un_sid(monkeypatch, winuser, out):
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: out)
    assert fsperm._user_sid() is None


def test_icacls_sid_non_mappato_poi_il_nome_semplice_funziona(monkeypatch, winuser):
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: f'"x\\y","{SID}"')
    fake = IcaclsScript(grant_rcs=[1332, 1332, 0])  # SID e DOMINIO\\utente non si risolvono, il solo nome si'
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(winuser) is True
    assert grants(fake) == ["*" + SID + ":F", "WORKGROUP\\administrator:F", "administrator:F"]
    assert fake.calls[-1][2] == "/inheritance:r"


def test_icacls_dominio_utente_non_mappato_poi_il_nome_semplice(monkeypatch, winuser):
    """Il caso del PC fuori dominio: WORKGROUP\\administrator da' 1332, `administrator` funziona."""
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: None)
    fake = IcaclsScript(grant_rcs=[1332, 0])
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(winuser) is True and grants(fake) == ["WORKGROUP\\administrator:F", "administrator:F"]


def test_icacls_tutte_le_concessioni_falliscono_non_si_toglie_l_ereditarieta(monkeypatch, winuser, caplog):
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: f'"x\\y","{SID}"')
    fake = IcaclsScript(grant_rcs=[1332, 1332, 1332])
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(winuser) is False
    assert all(c[2] == "/grant:r" for c in fake.calls) and len(fake.calls) == 3  # nessun /inheritance:r
    assert winuser.read_text(encoding="utf-8") == "x"


def test_icacls_altro_errore_non_prova_altri_nomi(monkeypatch, winuser):
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: f'"x\\y","{SID}"')
    fake = IcaclsScript(grant_rcs=[5])  # accesso negato: inutile insistere
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(winuser) is False and len(fake.calls) == 1


def test_icacls_file_illeggibile_dopo_l_ereditarieta_viene_ripristinato(monkeypatch, winuser):
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: f'"x\\y","{SID}"')
    monkeypatch.setattr(fsperm, "_accessible", lambda p, is_dir: False)
    fake = IcaclsScript()
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(winuser) is False
    assert [c[2] for c in fake.calls] == ["/grant:r", "/inheritance:r", "/reset"]


def test_icacls_ereditarieta_fallita_non_controlla_ne_ripristina(monkeypatch, winuser):
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: None)
    fake = IcaclsScript(inherit_rc=5)
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(winuser) is False and [c[2] for c in fake.calls] == ["/grant:r", "/inheritance:r"]


def test_icacls_senza_nome_ne_sid_non_tocca_niente(monkeypatch, winuser):
    monkeypatch.delenv("USERNAME")
    monkeypatch.delenv("USERDOMAIN")
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: None)
    fake = IcaclsScript()
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(winuser) is False and fake.calls == []


def test_icacls_solo_nome_utente_senza_dominio(monkeypatch, winuser):
    monkeypatch.delenv("USERDOMAIN")
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: None)
    fake = IcaclsScript()
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(winuser) is True and grants(fake) == ["administrator:F"]


def test_whoami_non_parte_fuori_da_windows(monkeypatch):
    monkeypatch.setattr(fsperm.sys, "platform", "darwin")
    monkeypatch.setattr(fsperm.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("non deve partire")))
    assert fsperm._whoami_output() is None and fsperm._user_sid() is None


def test_accessible_su_file_e_cartelle(tmp_path):
    f = tmp_path / "a"
    f.write_text("x", encoding="utf-8")
    assert fsperm._accessible(f, False) and fsperm._accessible(tmp_path, True)
    assert not fsperm._accessible(tmp_path / "manca", False) and not fsperm._accessible(tmp_path / "manca", True)


# ---------------------------------- secondo giro del collaudo (B103, B104, B107, B108) ----
def test_cv_delete_non_dice_di_aver_cancellato_se_il_cv_si_legge_ancora(monkeypatch, home):
    from jobshunter import cv, fsutil

    cv.save_text("Python SQL Linux Docker Git " * 10, "txt")
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(cv, "_wipe", lambda p: False)
    monkeypatch.setattr(fsutil, "unlink", lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "in uso")))
    with pytest.raises(cv.CvDeleteError) as e:
        cv.delete()
    assert "Non sono riuscito a cancellare il CV" in str(e.value) and isinstance(e.value, OSError)
    assert cv.load() is not None  # e infatti si legge ancora: nessuna bugia


def test_cv_delete_azzerato_ma_non_cancellato_e_un_successo_senza_contenuto(monkeypatch, home):
    from jobshunter import cv, fsutil

    cv.save_text("Python SQL Linux Docker Git " * 10, "txt")
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsutil, "unlink", lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "in uso")))
    assert cv.delete() is True and cv.load() is None


def test_api_cv_delete_con_errore_risponde_409_in_italiano(monkeypatch, home):
    from jobshunter import cv
    from jobshunter.gui.app import create_app

    cv.save_text("Python SQL Linux Docker Git " * 10, "txt")
    monkeypatch.setattr(cv, "delete", lambda: (_ for _ in ()).throw(cv.CvDeleteError("Non sono riuscito a cancellare il CV: file aperto.")))
    r = create_app(None, 8765).test_client().post("/api/cv/delete", headers={"Host": "127.0.0.1:8765"})
    assert r.status_code == 409 and r.get_json()["ok"] is False and "cancellare" in r.get_json()["error"]


def test_wipe_ritorna_l_esito(tmp_path):
    from jobshunter import cv

    f = tmp_path / "x"
    f.write_bytes(b"segreto")
    assert cv._wipe(f) is True and f.read_bytes() == b"\x00" * 7
    assert cv._wipe(tmp_path / "manca") is True
    assert cv._wipe(tmp_path) is False  # una cartella non si azzera


def test_proc_extra_solo_su_windows(monkeypatch):
    from jobshunter import proc

    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    assert proc.extra() == {"creationflags": 0x08000000} and proc.CREATE_NO_WINDOW == 0x08000000
    for system in ("mac", "linux"):
        monkeypatch.setattr(osinfo, "current", lambda platform=None, s=system: s)
        assert proc.extra() == {}


def test_tutti_i_comandi_su_windows_partono_senza_finestra(monkeypatch, tmp_path):
    from jobshunter import autoscan, scheduler

    seen = []
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsperm.subprocess, "run", lambda cmd, **k: seen.append((cmd[0], k.get("creationflags"))) or subprocess.CompletedProcess(cmd, 0, b"", b""))
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: None)
    monkeypatch.setenv("USERNAME", "utente")
    f = tmp_path / "x"
    f.write_text("x", encoding="utf-8")
    fsperm.secure_file(f)
    monkeypatch.setattr(fsperm, "_warned", [False])
    from jobshunter import proc

    proc.run(["whoami"])
    scheduler._REAL_RUN(["schtasks", "/Query"])
    monkeypatch.setattr(autoscan.shutil, "which", lambda n, *a, **k: "C:\\finto\\" + n)
    autoscan.notify_native("t", "b")
    assert {tool for tool, _ in seen} >= {"icacls", "whoami", "schtasks", "powershell"}
    assert all(flags == 0x08000000 for _, flags in seen), seen


def test_proc_run_su_sistema_non_windows_simulato_non_si_rompe(tmp_path):
    from jobshunter import proc

    # con Windows simulato su un POSIX vero subprocess rifiuta creationflags: si riprova senza
    import pytest as _pt

    mp = _pt.MonkeyPatch()
    mp.setattr(osinfo, "current", lambda platform=None: "windows")
    try:
        r = proc.run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True, encoding="utf-8")
    finally:
        mp.undo()
    assert r.returncode == 0 and r.stdout.strip() == "ok"


def test_cron_riga_con_bus_dbus_e_display(monkeypatch, tmp_path):
    from jobshunter import scheduler

    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "Dati 100% miei"))
    line = scheduler._cron_lines("daily", [(9, 0)], 6)[0]
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus" in line and "DISPLAY=${DISPLAY:-:0}" in line
    assert not re.search(r"(?<!\\)%", line) and "100\\% miei" in line  # il % resta protetto
    assert line.endswith(" # JobsHunter")
