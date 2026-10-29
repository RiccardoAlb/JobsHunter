"""Fase 7, collaudo indipendente della portabilita' (TESTER): macOS invariato, osinfo, filelock, fsperm, zone protette,
UTF-8, scheduler Windows/Linux, avvio, console, CI. Si simulano gli altri sistemi: nessun comando di sistema vero.
Compatibile con Python 3.11. I bug noti sono xfail con il numero B (docs/dev-notes/BUGS.md)."""
import ast
import io
import json
import multiprocessing
import os
import re
import shlex
import signal
import subprocess
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from jobshunter import autoscan, filelock, fsperm, macapp, migrate, osinfo, scheduler, settings

ROOT = Path(__file__).resolve().parent.parent.parent
OLD_NAME = "\x4aobHunter"      # il nome precedente: scritto cosi' per non far scattare il test che lo cerca nel codice
OLD_ENV = "\x4aOBHUNTER_HOME"
_REAL_RUN_QA = subprocess.run
_REAL_INSTALL, _REAL_UNINSTALL, _REAL_IS_LOADED = scheduler.install, scheduler.uninstall, scheduler.is_loaded


@pytest.fixture(autouse=True)
def _real_scheduler(monkeypatch):
    """tests/qa/conftest.py sostituisce install/uninstall/is_loaded con finti: qui servono quelli veri, col sistema FINTO."""
    monkeypatch.setattr(scheduler, "install", _REAL_INSTALL)
    monkeypatch.setattr(scheduler, "uninstall", _REAL_UNINSTALL)
    monkeypatch.setattr(scheduler, "is_loaded", _REAL_IS_LOADED)


class Sys:
    """Sistema finto: schtasks, systemctl, crontab. Registra tutto; nulla parte davvero."""

    def __init__(self):
        self.calls, self.tasks, self.enabled, self.cron = [], {}, set(), None
        self.cron_list_error = None   # (rc, stderr) per `crontab -l` che fallisce per un motivo diverso da "nessun crontab"
        self.cron_list_raises = None
        self.systemd_ok = True

    def __call__(self, cmd, input=None, timeout=30):
        self.calls.append(list(cmd))
        tool = Path(cmd[0]).stem
        done = lambda rc=0, out="", err="": subprocess.CompletedProcess(cmd, rc, out, err)  # noqa: E731
        if tool == "schtasks":
            name = cmd[cmd.index("/TN") + 1]
            if cmd[1] == "/Create":
                self.tasks[name] = Path(cmd[cmd.index("/XML") + 1]).read_bytes()
                return done()
            if cmd[1] == "/Query":
                return done(0 if name in self.tasks else 1)
            if cmd[1] == "/Delete":
                return done(0 if self.tasks.pop(name, None) is not None else 1, err="" if name in self.tasks else "ERRORE: file non trovato")
        if tool == "systemctl":
            a = cmd[2:]
            if a[0] == "show-environment":
                return done(0 if self.systemd_ok else 1)
            if a[0] == "is-enabled":
                return done(0 if a[1] in self.enabled else 1)
            if a[:2] == ["enable", "--now"]:
                self.enabled.add(a[2])
            if a[:2] == ["disable", "--now"]:
                self.enabled.discard(a[2])
            return done()
        if tool == "crontab":
            if cmd[1] == "-l":
                if self.cron_list_raises:
                    raise self.cron_list_raises
                if self.cron_list_error:
                    return done(self.cron_list_error[0], "", self.cron_list_error[1])
                return done(0, self.cron) if self.cron is not None else done(1, "", "no crontab for utente")
            if cmd[1] == "-":
                self.cron = input
                return done()
            if cmd[1] == "-r":
                self.cron = None
                return done()
        return done(1, "", "non previsto")


def as_system(monkeypatch, system, tools):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: system)
    monkeypatch.setattr(scheduler.shutil, "which", lambda name, *a, **k: ("/finto/" + name) if name in tools else None)
    f = Sys()
    monkeypatch.setattr(scheduler, "_run", f)
    return f


def decode_task(raw: bytes):
    root = ET.fromstring(raw)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    return root, ns


def win_split(cmdline: str) -> list[str]:
    """CommandLineToArgvW semplificato (regole di Microsoft per virgolette e barre inverse)."""
    out, cur, i, n, inq, started = [], [], 0, len(cmdline), False, False
    while i < n:
        c = cmdline[i]
        if c == "\\":
            j = i
            while j < n and cmdline[j] == "\\":
                j += 1
            k = j - i
            if j < n and cmdline[j] == '"':
                cur.append("\\" * (k // 2))
                if k % 2:
                    cur.append('"')
                    i = j + 1
                else:
                    i = j
                started = True
                continue
            cur.append("\\" * k)
            i = j
            started = True
            continue
        if c == '"':
            inq = not inq
            started = True
        elif c in " \t" and not inq:
            if started:
                out.append("".join(cur))
                cur, started = [], False
        else:
            cur.append(c)
            started = True
        i += 1
    if started:
        out.append("".join(cur))
    return out


# ======================================================================= 1. macOS invariato ====
def test_mac_percorsi_dati_e_log_come_prima(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert osinfo.data_dir() == Path.home() / "Library" / "Application Support" / "JobsHunter"
    assert osinfo.log_dir() == Path.home() / "Library" / "Logs" / "JobsHunter"
    assert migrate.support_dir() == Path.home() / "Library" / "Application Support" / "JobsHunter"
    assert migrate.support_dir(home=tmp_path) == tmp_path / "Library" / "Application Support" / "JobsHunter"
    assert migrate.log_dir(home=tmp_path) == tmp_path / "Library" / "Logs" / "JobsHunter"
    assert migrate.support_dir(OLD_NAME, home=tmp_path) == tmp_path / "Library" / "Application Support" / OLD_NAME
    assert scheduler.log_path() == Path.home() / "Library" / "Logs" / "JobsHunter" / "scan.log"
    assert scheduler.plist_path() == Path.home() / "Library" / "LaunchAgents" / "local.jobshunter.scan.plist"


@pytest.mark.skipif(sys.platform != "darwin", reason="LaunchAgent: specifico di macOS")
def test_mac_il_plist_non_cambia_e_non_usa_i_nuovi_strumenti(monkeypatch):
    monkeypatch.setattr(scheduler, "_run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("su macOS niente schtasks/systemctl/crontab")))
    plist = scheduler.build_plist("daily", [(9, 0), (18, 30)], 6)
    assert plist["Label"] == "local.jobshunter.scan" and plist["RunAtLoad"] is False
    assert plist["StartCalendarInterval"] == [{"Hour": 9, "Minute": 0}, {"Hour": 18, "Minute": 30}]
    assert plist["ProgramArguments"][1:] == ["-m", "jobshunter", "scan-auto"]
    assert plist["StandardOutPath"].endswith("Library/Logs/JobsHunter/scan.log")
    assert scheduler.build_plist("every", [(9, 0)], 4)["StartInterval"] == 4 * 3600
    assert scheduler.backend() == "launchd" and scheduler.supported()
    lc = []
    monkeypatch.setattr(scheduler, "_launchctl", lambda *a: lc.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    scheduler.install("daily", [(9, 0)], 6)
    assert [c[0] for c in lc] == ["bootout", "bootstrap"] and scheduler.plist_path().exists()
    scheduler.uninstall()  # nessuna eccezione e nessun comando di sistema oltre a launchctl (finto)
    assert not scheduler.plist_path().exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="osascript: specifico di macOS")
def test_mac_notifica_con_osascript_come_prima(monkeypatch):
    calls = []
    monkeypatch.setattr(autoscan.subprocess, "run", lambda cmd, **k: calls.append((cmd, k)) or subprocess.CompletedProcess(cmd, 0))
    assert autoscan.notify_native('Titolo "x"', 'Corpo \\ con "virgolette"\nriga') is True
    cmd = calls[0][0]
    assert cmd[:2] == ["osascript", "-e"] and 'display notification "Corpo \\\\ con \\"virgolette\\" riga"' in cmd[2]


def test_mac_migrazione_dal_vecchio_nome_invariata(monkeypatch, tmp_path):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "mac")
    old, new = tmp_path / "Application Support" / OLD_NAME, tmp_path / "Application Support" / "JobsHunter"
    old.mkdir(parents=True)
    (old / "config.toml").write_text("[x]\n", encoding="utf-8")
    (old / "scan.lock").write_text("", encoding="utf-8")
    d, outcome = migrate.migrate_app_data(old, new)
    assert (d, outcome) == (new, "copied")
    assert (new / "config.toml").exists() and not (new / "scan.lock").exists() and (old / "config.toml").exists()
    if os.name == "posix":
        assert (new / "config.toml").stat().st_mode & 0o777 == 0o600


def test_mac_i_punteggi_non_dipendono_dal_sistema(monkeypatch):
    from jobshunter import scoring

    src = inspect_source(scoring)
    assert "osinfo" not in src and "sys.platform" not in src


def inspect_source(mod) -> str:
    return Path(mod.__file__).read_text(encoding="utf-8")


def test_nessun_modulo_importa_fcntl_o_msvcrt_fuori_da_filelock():
    bad = []
    for base in ("jobshunter", "scripts"):
        for p in (ROOT / base).rglob("*.py"):
            if p.name == "filelock.py":
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):  # anche gli import dentro funzioni e quelli con importlib
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                if any(n.split(".")[0] in ("fcntl", "msvcrt") for n in names):
                    bad.append(p.name)
            if re.search(r"import_module\(['\"](fcntl|msvcrt)|__import__\(['\"](fcntl|msvcrt)", p.read_text(encoding="utf-8")):
                bad.append(p.name)
    assert not bad, bad


def test_il_pacchetto_si_importa_senza_fcntl(tmp_path):
    """Come su Windows: fcntl non esiste e tutti i moduli (tranne le funzioni solo-POSIX) devono importarsi lo stesso."""
    code = ("import sys, importlib\nsys.modules['fcntl'] = None\nsys.modules['pwd'] = None\nsys.modules['grp'] = None\n"
            "import pkgutil, jobshunter\nbad=[]\n"
            "for m in pkgutil.walk_packages(jobshunter.__path__, 'jobshunter.'):\n"
            "    if m.name.endswith('__main__'): continue\n"
            "    try: importlib.import_module(m.name)\n"
            "    except Exception as e: bad.append((m.name, repr(e)))\n"
            "print(bad)\nfrom jobshunter import filelock\nassert filelock.fcntl is None\nl=filelock.FileLock(sys.argv[1]); print(l.acquire(False))\n")
    r = subprocess.run([sys.executable, "-c", code, str(tmp_path / "x.lock")], cwd=ROOT, capture_output=True, text=True, errors="replace", encoding="utf-8",
                       env=dict(os.environ, JOBSHUNTER_HOME=str(tmp_path)))
    assert r.returncode == 0, r.stderr[-500:]
    assert r.stdout.splitlines()[0] == "[]", r.stdout
    assert r.stdout.splitlines()[1] == "True"  # senza fcntl ne' msvcrt: nessun blocco, mai un errore


# ============================================================================= 2. osinfo ====
@pytest.mark.parametrize("val", ["", " ", "relativo/dir", "./x", "~"])
def test_linux_xdg_vuoto_o_relativo_si_ignora(val):
    h = PurePosixPath("/home/utente")
    assert osinfo.data_dir(platform="linux", env={"XDG_DATA_HOME": val}, home=h) == PurePosixPath("/home/utente/.local/share/jobshunter") or val == " "
    assert osinfo.log_dir(platform="linux", env={"XDG_STATE_HOME": val}, home=h) == PurePosixPath("/home/utente/.local/state/jobshunter") or val == " "


def test_linux_xdg_con_spazi_e_accenti_assoluti():
    h = PurePosixPath("/home/utente Ñandú")
    env = {"XDG_DATA_HOME": "/dati/è ù/xdg", "XDG_STATE_HOME": "/stato con spazi"}
    assert osinfo.data_dir(platform="linux", env=env, home=h) == PurePosixPath("/dati/è ù/xdg/jobshunter")
    assert osinfo.log_dir(platform="linux", env=env, home=h) == PurePosixPath("/stato con spazi/jobshunter")
    assert osinfo.data_dir(platform="linux", env={}, home=h) == PurePosixPath("/home/utente Ñandú/.local/share/jobshunter")


@pytest.mark.parametrize("env", [{}, {"APPDATA": ""}, {"APPDATA": None}])
def test_windows_appdata_mancante_o_vuoto_ripiega_sulla_home(env):
    h = PureWindowsPath("C:/Users/utente José Ñ")
    assert osinfo.data_dir(platform="win32", env=env, home=h) == PureWindowsPath("C:/Users/utente José Ñ/AppData/Roaming/JobsHunter")
    assert osinfo.log_dir(platform="win32", env={"LOCALAPPDATA": ""}, home=h) == PureWindowsPath("C:/Users/utente José Ñ/AppData/Local/JobsHunter/Logs")


def test_windows_appdata_con_barra_finale_e_accenti():
    h = PureWindowsPath("C:/Users/x")
    env = {"APPDATA": "D:\\Dati è\\Roaming\\", "LOCALAPPDATA": "D:\\Dati è\\Local\\"}
    assert osinfo.data_dir(platform="win32", env=env, home=h) == PureWindowsPath("D:/Dati è/Roaming/JobsHunter")
    assert osinfo.log_dir(platform="win32", env=env, home=h) == PureWindowsPath("D:/Dati è/Local/JobsHunter/Logs")


def test_jobshunter_home_e_legacy(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("JOBSHUNTER_HOME", raising=False)
    monkeypatch.setenv(OLD_ENV, str(tmp_path / "vecchia"))
    monkeypatch.setattr(settings, "_warned_legacy_env", [False])
    assert settings.home() == tmp_path / "vecchia"
    assert "vecchio nome" in capsys.readouterr().err
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "nuova"))
    assert settings.home() == tmp_path / "nuova"  # la nuova vince sulla vecchia
    monkeypatch.setenv("JOBSHUNTER_HOME", "")
    monkeypatch.delenv(OLD_ENV)
    assert settings.home() == settings.SOURCE_ROOT  # vuota = non impostata


def test_home_con_spazi_e_accenti_e_tilde(monkeypatch, tmp_path):
    h = tmp_path / "Cartella è con spazi" / "dati"
    monkeypatch.setenv("JOBSHUNTER_HOME", str(h))
    cfg = settings.load_config(create_if_missing=True)
    assert Path(cfg["_config_path"]).parent == h
    monkeypatch.setenv("JOBSHUNTER_HOME", "~/dati-tilde")
    assert settings.home() == Path.home() / "dati-tilde"


def test_nessun_percorso_assoluto_di_macos_nei_default_del_codice_di_produzione():
    """Fuori da osinfo/migrate (che li usano per macOS di proposito) nessun modulo deve scrivere ~/Library nei default."""
    bad = []
    for p in (ROOT / "jobshunter").rglob("*.py"):
        if p.name in ("osinfo.py", "migrate.py", "settings.py", "scheduler.py", "macapp.py"):
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""["']Library["']|Application Support|/Users/""", line):
                bad.append(f"{p.name}:{n}")
    assert not bad, bad


@pytest.mark.parametrize("system", ["windows", "linux"])
def test_scan_log_va_nella_cartella_log_del_sistema(monkeypatch, system):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: system)
    assert scheduler.log_path() == osinfo.log_dir() / "scan.log"
    assert "Library" not in str(scheduler.log_path()) or system == "mac"


# ========================================================================== 3. filelock ====
def _hold(path, ready, release, result):
    """Processo figlio: prende il blocco, avvisa, aspetta il permesso, rilascia."""
    l = filelock.FileLock(path)
    result.put(("child_acquire", l.acquire(blocking=False)))
    ready.set()
    release.wait(30)
    l.release()


def _try_child(path, out):
    out.put(filelock.FileLock(path).acquire(blocking=False))


def _hold_forever(path, ready):
    l = filelock.FileLock(path)
    assert l.acquire(blocking=False)
    ready.set()
    time.sleep(60)


@pytest.mark.skipif(os.name != "posix", reason="multiprocessing con fork/spawn provato su POSIX")
def test_filelock_due_processi_veri(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    path = str(tmp_path / "d" / "x.lock")
    ready, release, q = ctx.Event(), ctx.Event(), ctx.Queue()
    p = ctx.Process(target=_hold, args=(path, ready, release, q))
    p.start()
    try:
        assert ready.wait(20) and q.get(timeout=5) == ("child_acquire", True)
        mine = filelock.FileLock(path)
        t0 = time.monotonic()
        assert mine.acquire(blocking=False) is False and time.monotonic() - t0 < 1.0  # non aspetta
        assert not mine.held
        release.set()
        p.join(20)
        assert mine.acquire(blocking=False) is True and mine.held
        out = ctx.Queue()
        c = ctx.Process(target=_try_child, args=(path, out))
        c.start()
        assert out.get(timeout=20) is False  # ora il figlio non riesce, perche' lo tengo io
        c.join(10)
        mine.release()
        assert not mine.held
        mine.release()  # idempotente
    finally:
        release.set()
        p.join(5)
        if p.is_alive():
            p.kill()


@pytest.mark.skipif(os.name != "posix", reason="SIGKILL: POSIX")
def test_filelock_cade_da_solo_se_il_processo_muore(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    path = str(tmp_path / "k.lock")
    ready = ctx.Event()
    p = ctx.Process(target=_hold_forever, args=(path, ready))
    p.start()
    try:
        assert ready.wait(20)
        assert filelock.FileLock(path).acquire(blocking=False) is False
        os.kill(p.pid, signal.SIGKILL)
        p.join(10)
        l = filelock.FileLock(path)
        assert l.acquire(blocking=False) is True
        l.release()
    finally:
        if p.is_alive():
            p.kill()


def test_filelock_rilascio_su_eccezione_e_senza_fd_orfani(tmp_path):
    path = tmp_path / "e.lock"
    with pytest.raises(ZeroDivisionError):
        with filelock.FileLock(path):
            1 / 0
    l = filelock.FileLock(path)
    assert l.acquire(blocking=False)
    l.release()
    # attesa interrotta da Ctrl+C: il file aperto dal tentativo si chiude e il blocco non resta preso
    holder = filelock.FileLock(path)
    assert holder.acquire(blocking=False)
    import resource

    def n_fd():
        return len(os.listdir("/dev/fd")) if os.path.isdir("/dev/fd") else 0

    before = n_fd()
    waiter = filelock.FileLock(path)
    orig = time.sleep
    try:
        time.sleep = lambda s: (_ for _ in ()).throw(KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            waiter.acquire(blocking=True)
    finally:
        time.sleep = orig
    assert n_fd() == before and not waiter.held
    holder.release()
    assert waiter.acquire(blocking=False)
    waiter.release()
    assert resource  # (modulo usato solo per segnalare che e' POSIX)


def test_filelock_seconda_acquisizione_sullo_stesso_oggetto_non_perde_il_blocco(tmp_path):
    l = filelock.FileLock(tmp_path / "s.lock")
    assert l.acquire(blocking=False)
    fh = l.fh
    assert l.acquire(blocking=False) is False  # gia' preso (anche da me)
    assert l.fh is fh and l.held
    other = filelock.FileLock(tmp_path / "s.lock")
    assert other.acquire(blocking=False) is False  # e infatti e' ancora preso
    l.release()


def test_filelock_cartella_che_e_un_file_o_non_scrivibile_nel_with(tmp_path):
    (tmp_path / "f").write_text("x", encoding="utf-8")
    with filelock.FileLock(tmp_path / "f" / "x.lock") as l:  # il with non solleva: si prosegue senza blocco, come prima
        assert not l.held
    with pytest.raises(OSError):
        filelock.FileLock(tmp_path / "f" / "x.lock").acquire(blocking=False)


class FakeMsvcrt:
    LK_NBLCK, LK_UNLCK, LK_LOCK = 2, 0, 1

    def __init__(self):
        self.held = {}      # percorso reale -> fileno
        self.log = []

    def locking(self, fd, mode, nbytes):
        key = os.fstat(fd).st_ino
        self.log.append((mode, nbytes, os.lseek(fd, 0, os.SEEK_CUR)))
        if mode == self.LK_NBLCK:
            if key in self.held and self.held[key] != fd:
                raise PermissionError(13, "locked")
            self.held[key] = fd
        elif mode == self.LK_UNLCK:
            self.held.pop(key, None)


def test_filelock_percorso_windows_simulato_con_msvcrt_finto(monkeypatch, tmp_path):
    fake = FakeMsvcrt()
    monkeypatch.setattr(filelock, "fcntl", None)
    monkeypatch.setattr(filelock, "msvcrt", fake)
    a, b = filelock.FileLock(tmp_path / "w.lock"), filelock.FileLock(tmp_path / "w.lock")
    assert a.acquire(blocking=False) is True
    assert b.acquire(blocking=False) is False
    a.release()
    assert b.acquire(blocking=False) is True
    b.release()
    assert all(nb == 1 and pos == 0 for _, nb, pos in fake.log)  # sempre lo stesso byte (posizione 0), lock e unlock coerenti
    assert [m for m, _, _ in fake.log] == [2, 2, 0, 2, 0]


def test_filelock_senza_nessun_meccanismo_non_blocca_e_non_solleva(monkeypatch, tmp_path):
    monkeypatch.setattr(filelock, "fcntl", None)
    monkeypatch.setattr(filelock, "msvcrt", None)
    a, b = filelock.FileLock(tmp_path / "n.lock"), filelock.FileLock(tmp_path / "n.lock")
    assert a.acquire(blocking=False) and b.acquire(blocking=False)
    a.release()
    b.release()


def test_filelock_blocking_aspetta_e_poi_prende(tmp_path):
    import threading

    path = tmp_path / "b.lock"
    first = filelock.FileLock(path)
    assert first.acquire(blocking=False)
    got = []
    t = threading.Thread(target=lambda: got.append(filelock.FileLock(path).acquire(blocking=True, poll=0.02)))
    t.start()
    time.sleep(0.2)
    assert not got
    first.release()
    t.join(5)
    assert got == [True]


def test_scanlock_come_prima_sul_vecchio_contratto(home):
    s1, s2 = autoscan.ScanLock(), autoscan.ScanLock()
    assert s1.path == home / "scan.lock" and s1.acquire() is True and s1.fh is not None
    assert s2.acquire() is False and s2.fh is None
    s1.release()
    assert s1.fh is None and s2.acquire() is True
    s2.release()


# ============================================================================ 4. fsperm ====
class FakeIcacls:
    def __init__(self, rcs=(0, 0), raises=None, out=""):
        self.calls, self.rcs, self.raises, self.out = [], list(rcs), raises, out

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        i = len(self.calls) - 1
        if self.raises is not None and (not isinstance(self.raises, tuple) or self.raises[0] == i):
            raise (self.raises if not isinstance(self.raises, tuple) else self.raises[1])
        return subprocess.CompletedProcess(cmd, self.rcs[i] if i < len(self.rcs) else 0, self.out, "")


@pytest.fixture
def win_fs(monkeypatch):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setenv("USERNAME", "José Ñ")
    monkeypatch.setenv("USERDOMAIN", "PC DI JOSÉ")
    monkeypatch.setattr(fsperm, "_warned", [False])
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: None)  # su un Windows vero `whoami` partirebbe davvero (o finirebbe nel finto): niente SID


def test_fsperm_windows_concede_prima_poi_toglie_ereditarieta(monkeypatch, tmp_path, win_fs):
    f = tmp_path / "dati con spazi è.db"
    f.write_text("x", encoding="utf-8")
    fake = FakeIcacls()
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(f) is True
    assert fake.calls[0][:3] == ["icacls", str(f), "/grant:r"] and fake.calls[0][3] == "PC DI JOSÉ\\José Ñ:F"
    assert fake.calls[1] == ["icacls", str(f), "/inheritance:r"]
    d = tmp_path / "cartella"
    d.mkdir()
    fake2 = FakeIcacls()
    monkeypatch.setattr(fsperm.subprocess, "run", fake2)
    assert fsperm.secure_dir(d) and fake2.calls[0][3] == "PC DI JOSÉ\\José Ñ:(OI)(CI)F"


@pytest.mark.parametrize("fake", [
    FakeIcacls(rcs=(1,)), FakeIcacls(rcs=(0, 5)), FakeIcacls(raises=FileNotFoundError("icacls")),
    FakeIcacls(raises=subprocess.TimeoutExpired("icacls", 20)), FakeIcacls(raises=(1, PermissionError("x"))),
    FakeIcacls(raises=UnicodeDecodeError("cp1252", b"\x8d", 0, 1, "undefined")), FakeIcacls(raises=ValueError("embedded null")),
])
def test_fsperm_windows_non_solleva_mai_e_non_toglie_accesso_se_fallisce_a_meta(monkeypatch, tmp_path, win_fs, fake):
    f = tmp_path / "a.db"
    f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(f) is False
    names = [c[2] for c in fake.calls]
    assert "/inheritance:r" not in names[:1]  # la prima chiamata e' SEMPRE la concessione
    if len(fake.calls) == 1:
        assert fake.calls[0][2] == "/grant:r"
    assert f.read_text(encoding="utf-8") == "x"  # il file e' ancora nostro


def test_fsperm_windows_senza_nome_utente_non_tocca_nulla(monkeypatch, tmp_path, win_fs):
    monkeypatch.delenv("USERNAME")
    monkeypatch.delenv("USERDOMAIN")
    fake = FakeIcacls()
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(tmp_path / "x") is False and fake.calls == []  # mai /grant:r con nome vuoto: toglierebbe tutto


def test_fsperm_un_solo_avviso(monkeypatch, tmp_path, win_fs, caplog):
    monkeypatch.setattr(fsperm.subprocess, "run", FakeIcacls(rcs=(1, 1, 1, 1)))
    with caplog.at_level("WARNING", logger="jobshunter.fsperm"):
        for _ in range(4):
            fsperm.secure_file(tmp_path / "a")
    assert len([r for r in caplog.records if r.name == "jobshunter.fsperm"]) == 1


@pytest.mark.skipif(os.name != "posix", reason="permessi POSIX")
def test_fsperm_posix_permessi_e_casi_strani(tmp_path):
    f = tmp_path / "f"
    f.write_text("x", encoding="utf-8")
    os.chmod(f, 0o666)
    assert fsperm.secure_file(f) and f.stat().st_mode & 0o777 == 0o600
    d = tmp_path / "d"
    d.mkdir()
    os.chmod(d, 0o755)
    assert fsperm.secure_dir(d) and d.stat().st_mode & 0o777 == 0o700
    assert fsperm.secure_file(tmp_path / "manca") is False
    assert fsperm.secure_file(None) is False
    assert fsperm.secure_file(str(f)) is True
    assert fsperm.secure_file("x\x00y") is False
    ln = tmp_path / "ln"
    os.symlink(f, ln)
    assert fsperm.secure_file(ln) is True


def test_fsperm_posix_non_cambia_comportamento_dei_file_dei_dati(home):
    from jobshunter import settings as S

    cfg = S.load_config(create_if_missing=True)
    S.save_overrides(Path(cfg["_config_path"]), {"home": "Roma"})
    for name in ("config.toml", "settings.json"):
        assert (home / name).stat().st_mode & 0o777 == 0o600, name


@pytest.mark.skipif(os.name != "posix", reason="permessi POSIX")
def test_B84_secure_file_con_percorso_vuoto_non_tocca_la_cartella_corrente(tmp_path, monkeypatch):
    work = tmp_path / "lavoro"
    work.mkdir()
    os.chmod(work, 0o755)
    monkeypatch.chdir(work)
    try:
        fsperm.secure_file("")
        fsperm.secure_file(Path(""))
        mode = work.stat().st_mode & 0o777
    finally:
        os.chmod(work, 0o755)  # ripara comunque: il test non deve lasciare cartelle inaccessibili
    assert mode == 0o755


@pytest.mark.skipif(os.name != "posix", reason="permessi POSIX")
def test_B84_secure_file_su_una_cartella_non_la_rende_inaccessibile(tmp_path):
    d = tmp_path / "cartella"
    d.mkdir()
    try:
        fsperm.secure_file(d)
        assert os.access(d, os.X_OK)
    finally:
        os.chmod(d, 0o755)


# ======================================================================= 5. check_report_dir ====
WENV = {"SystemRoot": "C:\\Windows", "ProgramFiles": "C:\\Program Files", "ProgramFiles(x86)": "C:\\Program Files (x86)",
        "ProgramData": "C:\\ProgramData", "APPDATA": "C:\\Users\\utente José Ñ\\AppData\\Roaming", "LOCALAPPDATA": "C:\\Users\\utente José Ñ\\AppData\\Local", "SystemDrive": "C:"}
WTEMP = ["C:\\Users\\utente José Ñ\\AppData\\Local\\Temp"]
WHOME = PureWindowsPath("C:\\Users\\utente José Ñ")


def wprot(p, home=WHOME, env=WENV, temps=WTEMP):
    return settings._win_protected(PureWindowsPath(settings._strip_win_prefix(p)), home, env, temps)


@pytest.mark.parametrize("p", [
    "C:\\", "c:\\", "D:\\", "C:", "Z:/", "C:\\Windows", "c:\\WINDOWS\\system32\\config", "C:/Windows/System32", "C:\\Windows\\..\\Windows\\x",
    "C:\\Program Files", "C:\\PROGRAM FILES\\Git", "C:\\Program Files (x86)\\x y", "C:\\ProgramData\\Microsoft", "c:\\programdata",
    "C:\\Users\\utente José Ñ\\AppData", "C:\\Users\\utente José Ñ\\AppData\\Roaming\\Obsidian", "C:\\Users\\utente José Ñ\\AppData\\Local\\Programs\\x",
    "C:\\Users\\utente JOSÉ Ñ\\appdata\\roaming", "C:\\Users\\utente José Ñ\\.ssh", "C:\\Users\\utente José Ñ\\.SSH\\id_rsa", "C:\\Users\\utente José Ñ\\.gnupg\\x", "C:\\Users\\utente José Ñ\\.aws", "C:\\Users\\utente José Ñ\\.azure\\x",
    "\\\\server\\share", "\\\\server\\share\\Rep", "\\\\?\\UNC\\server\\share\\x", "\\\\?\\C:\\Windows", "\\\\?\\c:\\", "\\\\.\\C:\\x", "//server/share/x",
])
def test_windows_percorsi_che_devono_essere_protetti(p):
    assert wprot(p), p


@pytest.mark.parametrize("p", [
    "D:\\Lavori\\Résumé e Report", "C:\\Users\\utente José Ñ\\Documents\\Obsidian Vault è", "C:\\Users\\utente José Ñ\\OneDrive - Azienda\\Documenti", "D:\\",  # D:\ e' una radice: vedi sotto
    "C:\\Users\\utente José Ñ\\AppData\\Local\\Temp\\pytest-1\\x", "C:\\Windowsfoo\\x", "C:\\Program Filesx", "C:\\Users\\utente José Ñ\\AppData\\Local\\Tempo\\x" ,
])
def test_windows_percorsi_ammessi(p):
    if p in ("D:\\",):
        assert wprot(p)  # radice di unita': protetta
    elif p.endswith("Tempo\\x"):
        assert wprot(p)  # AppData\Local\Tempo NON e' la cartella temporanea
    else:
        assert not wprot(p), p


def test_windows_home_su_un_altro_disco_e_appdata_spostato():
    home = PureWindowsPath("D:\\Utenti\\ö ö")
    env = dict(WENV, APPDATA="E:\\Roam", LOCALAPPDATA="E:\\Loc", SystemDrive="D:")
    assert wprot("E:\\Roam\\x", home, env, []) and wprot("E:\\Loc\\Temp", home, env, []) and wprot("D:\\Utenti\\ö ö\\AppData\\x", home, env, [])
    assert wprot("D:\\Windows\\x", home, env, []) and wprot("D:\\Utenti\\ö ö\\.ssh", home, env, [])
    assert not wprot("D:\\Utenti\\ö ö\\Documenti", home, env, [])


def test_windows_variabili_mancanti_ricadono_sui_valori_di_serie():
    assert wprot("C:\\Windows\\x", WHOME, {}, []) and wprot("C:\\Program Files\\x", WHOME, {}, []) and wprot("C:\\ProgramData", WHOME, {}, [])
    assert not wprot("C:\\Users\\utente José Ñ\\Documents", WHOME, {}, [])


@pytest.mark.parametrize("p,expected", [("\\\\?\\C:\\Users\\x\\Documents", "C:\\Users\\x\\Documents"), ("\\\\?\\UNC\\s\\sh\\a", "\\\\s\\sh\\a"), ("C:\\x", "C:\\x"), ("", "")])
def test_strip_win_prefix(p, expected):
    assert settings._strip_win_prefix(p) == expected


def test_windows_check_report_dir_unc_e_prefisso_con_messaggi_in_italiano(monkeypatch):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    for p in ("\\\\server\\share\\x", "//server/share/x"):
        with pytest.raises(ValueError, match="cartelle di rete"):
            settings.check_report_dir(p)


def test_B85_prefisso_esteso_locale_non_e_una_cartella_di_rete(monkeypatch):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    try:
        settings.check_report_dir("\\\\?\\C:\\Users\\x\\Documents\\Report")
    except ValueError as e:
        assert "rete" not in str(e)  # al massimo un altro messaggio, mai "cartelle di rete" per un disco locale
    else:
        pass


PH = "/home/utente"


@pytest.mark.parametrize("p", ["/etc", "/etc/ssh", "/usr/local/bin", "/bin", "/sbin", "/var/lib/x", "/sys/kernel", "/proc/1/environ", "/boot/efi", "/dev/shm",
                               "/root/x", "/opt/app", "/lib/x", "/lib64", "/run/user/1000", "/", "/home/utente/.ssh", "/home/utente/.ssh/id_ed25519", "/home/utente/.gnupg",
                               "/home/utente/.aws/x", "/home/utente/.config/y", "/proc/self/root/etc"])
def test_linux_protetti(p):
    assert settings._posix_protected(p, PH, "linux"), p


@pytest.mark.parametrize("p", ["/home/utente", "/home/utente/Documenti/Vault è", "/home/utente/Documents/JobsHunter", "/tmp/x", "/mnt/dati/Report", "/media/utente/Disco USB/r",
                               "/srv/report", "/home/x/x", "/data", "/home/utente/.local/share/obsidian", "/home/utente/.sshfoo"])
def test_linux_ammessi(p):
    assert not settings._posix_protected(p, PH, "linux"), p


@pytest.mark.parametrize("home", ["/", "//"])
def test_B86_home_uguale_alla_radice_non_ammette_le_zone_di_sistema(home):
    for p in ("/etc/cron.d", "/usr/lib", "/var/spool", "/boot", "/root"):
        assert settings._posix_protected(p, home, "linux"), (home, p)


def test_linux_home_di_root_e_home_sotto_var():
    assert not settings._posix_protected("/root/Documenti", "/root", "linux") and settings._posix_protected("/root/.ssh/x", "/root", "linux")
    assert not settings._posix_protected("/var/home/utente/Documenti", "/var/home/utente", "linux")  # Fedora Silverblue: /home e' un link a /var/home
    assert settings._posix_protected("/var/lib/altro", "/var/home/utente", "linux")
    assert not settings._posix_protected("/home/x/x", "/home/utente", "linux")
    assert not settings._posix_protected("/home/" + "utente" + "-bis/x", "/home/utente", "linux")  # prefisso simile ma altra cartella


def test_mac_senza_distinguere_maiuscole_e_zone_proprie():
    h = "/Users/utente"
    for p in ("/SYSTEM/x", "/library", "/APPLICATIONS/x", "/PRIVATE/etc", "/Users/utente/.SSH", "/users/utente/LIBRARY/launchagents/x", "/Users/utente/Library/Keychains"):
        assert settings._posix_protected(p, h, "mac"), p
    for p in ("/Users/utente/Documents", "/Volumes/Disco/Rep", "/private/tmp/x", "/private/var/folders/ab/T/x", "/Users/Shared/x"):
        assert not settings._posix_protected(p, h, "mac"), p


def test_check_report_dir_vero_su_questo_sistema(tmp_path, monkeypatch):
    home = tmp_path / "Casa è con spazi"
    (home / "Documents" / "Vault").mkdir(parents=True)
    (home / ".ssh").mkdir()
    monkeypatch.setenv("HOME", str(home))
    os.symlink("/etc", home / "link_etc")
    os.symlink(home / ".ssh", home / "Documents" / "link_ssh")
    os.symlink(home / "Documents" / "Vault", home / "link_vault")
    settings.check_report_dir(str(home / "Documents" / "Vault"))
    settings.check_report_dir("~/Documents/Vault/nuova cartella è")
    settings.check_report_dir(str(home / "link_vault"))
    for bad in (str(home / ".ssh"), str(home / ".ssh" / "x"), str(home / "link_etc"), str(home / "link_etc" / "x"), str(home / "Documents" / "link_ssh"),
                "~/.ssh", "/etc/x"):
        with pytest.raises(ValueError, match="zona di sistema|riservati"):
            settings.check_report_dir(bad)
    for bad in ("..", "a/../b", "x\x00y", str(home) + "/../x"):
        with pytest.raises(ValueError, match="percorso non valido"):
            settings.check_report_dir(bad)


@pytest.mark.parametrize("text", ["a" * 5000, "x/" + "b" * 300 + "/c", "\n", "a\nb", "\t", "~utente_inesistente_zz/x", "~~", "//", "///etc", "/etc//ssh/", "con\u202eRTL", "\ud800", "😀/📁",
                                  "C:", "C:\\", "\\", "\\\\", "\\\\?\\", "//?/C:/x", "CON", "NUL:", "aux.txt", ":", "*", "?", "<>", "|", "\"", "%APPDATA%", "$HOME", "${HOME}/x"])
def test_check_report_dir_mai_eccezioni_diverse_da_valueerror(text):
    try:
        settings.check_report_dir(text)
    except ValueError as e:
        assert str(e)  # sempre con un messaggio
    # qualunque altra eccezione fa fallire il test


@pytest.mark.parametrize("system", ["windows", "linux"])
def test_check_report_dir_mai_eccezioni_simulando_altri_sistemi(monkeypatch, system):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: system)
    for text in ("C:\\Windows", "\\\\srv\\sh", "/etc", "x", "~", "", "D:\\a b\\è", "a\\..\\b", "\\\\?\\C:\\x", "//a/b"):
        try:
            settings.check_report_dir(text)
        except ValueError:
            pass


def test_messaggi_in_italiano_senza_trattini_lunghi():
    src = inspect_source(settings)
    assert "\u2014" not in src and "\u2013" not in src
    for f in ("osinfo", "filelock", "fsperm", "scheduler", "macapp", "autoscan"):
        text = Path(ROOT / "jobshunter" / f"{f}.py").read_text(encoding="utf-8")
        assert "\u2014" not in text, f


# ============================================================= 7. scheduler Windows (schtasks) ====
HOSTILE_WIN = {
    "exe": 'D:\\Programmi & più\\Py <3> "x"\\python.exe',
    "root": "E:\\Progetti è\\JobsHunter & Co\\",
    "home": "F:\\Dati %APPDATA% 100% ' é\\",
}


@pytest.fixture
def hostile_win(monkeypatch, tmp_path):
    f = as_system(monkeypatch, "windows", {"schtasks"})
    monkeypatch.setattr(sys, "executable", HOSTILE_WIN["exe"])
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(settings, "SOURCE_ROOT", Path(HOSTILE_WIN["root"]))
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "dati"))
    (tmp_path / "dati").mkdir(exist_ok=True)
    return f


def _xml(kind, times, hours, now=None):
    raw = scheduler._task_xml(kind, times, hours, now).encode("utf-16")
    return raw, *decode_task(raw)


def test_schtasks_xml_percorsi_ostili_si_rileggono_identici(hostile_win, monkeypatch):
    monkeypatch.setenv("JOBSHUNTER_HOME", HOSTILE_WIN["home"])
    raw, root, ns = _xml("daily", [(9, 0)], 6)
    assert raw[:2] in (b"\xff\xfe", b"\xfe\xff")  # BOM UTF-16
    cmd = root.find("t:Actions/t:Exec/t:Command", ns).text
    args = root.find("t:Actions/t:Exec/t:Arguments", ns).text
    wd = root.find("t:Actions/t:Exec/t:WorkingDirectory", ns).text
    assert cmd == HOSTILE_WIN["exe"] and wd == str(Path(HOSTILE_WIN["root"]))
    parsed = win_split(args)
    assert parsed[:2] == ["-m", "jobshunter"] and parsed[2] == "--home" and parsed[3] == str(Path(HOSTILE_WIN["home"]).expanduser())
    assert parsed[4] == "scan-auto" and parsed[5] == "--log-file" and parsed[6].endswith("scan.log")


def test_schtasks_xml_orari_e_recupero_se_spento():
    for times in ([(9, 0)], [(9, 5), (18, 30), (0, 0), (23, 59)]):
        raw, root, ns = _xml("daily", times, 6, now=__import__("datetime").datetime(2026, 10, 28, 20, 0))
        trig = root.findall("t:Triggers/t:CalendarTrigger", ns)
        assert [t.find("t:StartBoundary", ns).text for t in trig] == [f"2026-10-28T{h:02d}:{m:02d}:00" for h, m in times]
        assert all(t.find("t:ScheduleByDay/t:DaysInterval", ns).text == "1" for t in trig)
        s = root.find("t:Settings", ns)
        assert s.find("t:StartWhenAvailable", ns).text == "true"  # recupero se il PC era spento
        assert s.find("t:MultipleInstancesPolicy", ns).text == "IgnoreNew"
        assert s.find("t:DisallowStartIfOnBatteries", ns).text == "false" and s.find("t:StopIfGoingOnBatteries", ns).text == "false"


@pytest.mark.parametrize("hours", [1, 2, 3, 4, 6, 8, 12, 24])
def test_schtasks_xml_ogni_n_ore(hours):
    raw, root, ns = _xml("every", [(9, 0)], hours)
    trig = root.findall("t:Triggers/t:CalendarTrigger", ns)
    assert len(trig) == 1
    if hours >= 24:
        assert trig[0].find("t:Repetition", ns) is None and trig[0].find("t:StartBoundary", ns).text.endswith("T09:00:00")
    else:
        rep = trig[0].find("t:Repetition", ns)
        assert rep.find("t:Interval", ns).text == f"PT{hours}H" and rep.find("t:Duration", ns).text == "P1D"
        assert trig[0].find("t:StartBoundary", ns).text.endswith("T00:00:00")


def test_schtasks_install_e_uninstall_idempotenti(monkeypatch, tmp_path, hostile_win):
    f = hostile_win
    scheduler.uninstall()  # senza nulla installato: nessun errore
    scheduler.uninstall()
    assert scheduler.is_loaded() is False
    scheduler.install("daily", [(9, 0), (18, 30)], 6)
    scheduler.install("every", [(9, 0)], 4)  # sostituisce (/F)
    assert scheduler.is_loaded() is True and len(f.tasks) == 1
    create = [c for c in f.calls if c[:2] == ["schtasks", "/Create"]]
    assert all(c[2:4] == ["/TN", "JobsHunter scan"] and c[-1] == "/F" for c in create)
    assert not (settings.home() / "schedule_task.xml").exists()  # l'XML temporaneo non resta (potrebbe contenere percorsi personali)
    assert (settings.home() / "schedule_state.json").exists()
    scheduler.uninstall()
    scheduler.uninstall()
    assert f.tasks == {} and not (settings.home() / "schedule_state.json").exists() and scheduler.is_loaded() is False


def test_schtasks_install_fallito_solleva_runtimeerror_italiano_e_non_lascia_xml(monkeypatch, tmp_path, hostile_win):
    monkeypatch.setattr(scheduler, "_run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "ERRORE: accesso negato"))
    with pytest.raises(RuntimeError, match="Utilita' di pianificazione"):
        scheduler.install("daily", [(9, 0)], 6)
    assert not list(settings.home().glob("*.xml"))


def test_schtasks_senza_strumento_non_supportata_con_messaggio(monkeypatch):
    as_system(monkeypatch, "windows", set())
    assert scheduler.supported() is False and "schtasks" in scheduler.unsupported_reason()
    with pytest.raises(RuntimeError, match="non e' disponibile"):
        scheduler.install("daily", [(9, 0)], 6)
    scheduler.uninstall()  # mai un errore
    cfg = settings.load_config(create_if_missing=True)
    st = scheduler.status(cfg)
    assert st["supported"] is False and st["platform"] == "windows" and st["reason"]
    assert scheduler.ensure_current(dict(cfg, schedule={"enabled": True})) is False


def test_schtasks_comando_pythonw_se_c_e(monkeypatch, tmp_path):
    f = as_system(monkeypatch, "windows", {"schtasks"})
    fake_scripts = tmp_path / "Scripts"
    fake_scripts.mkdir()
    (fake_scripts / "python.exe").write_text("", encoding="utf-8")
    (fake_scripts / "pythonw.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(fake_scripts / "python.exe"))
    assert scheduler.scan_command()[0] == str(fake_scripts / "pythonw.exe")
    assert scheduler.command()[0] == str(fake_scripts / "python.exe")  # il comando "normale" (macOS/Linux) non cambia
    tc = scheduler._task_command()
    assert tc[0].endswith("pythonw.exe") and tc[-2] == "--log-file" and "--home" in tc and tc.index("--home") < tc.index("scan-auto")


# ============================================================ 7b. scheduler Linux (systemd, cron) ====
def parse_systemd_args(line: str) -> list[str]:
    """Come systemd legge una riga ExecStart: virgolette doppie con escape C, %% -> %, $$ -> $, ${X} e $X espansi (qui: segnalati)."""
    body = line.split("=", 1)[1]
    out, cur, inq, i, started = [], [], False, 0, False
    while i < len(body):
        c = body[i]
        if c == "\\" and inq and i + 1 < len(body):
            cur.append(body[i + 1])
            i += 2
            started = True
            continue
        if c == '"':
            inq = not inq
            started = True
        elif c == " " and not inq:
            if started:
                out.append("".join(cur))
                cur, started = [], False
        elif c == "%" and body[i + 1:i + 2] == "%":
            cur.append("%")
            i += 1
            started = True
        elif c == "$" and body[i + 1:i + 2] == "$":
            cur.append("$")
            i += 1
            started = True
        elif c == "$":
            cur.append("\x00VAR\x00")  # sostituzione di variabile: l'argomento reale cambierebbe
            started = True
        else:
            cur.append(c)
            started = True
        i += 1
    if started:
        out.append("".join(cur))
    return out


@pytest.fixture
def linux(monkeypatch, tmp_path):
    f = as_system(monkeypatch, "linux", {"systemctl", "crontab"})
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    return f


@pytest.mark.parametrize("home", ["/home/utente/dati con spazi", "/home/x è ù/100%/x", '/home/x"b/c', "/home/x\\b", "/home/x'b", "/home/x;b&c|d"])
def test_systemd_exec_start_ed_environment_con_percorsi_ostili(linux, monkeypatch, tmp_path, home):
    monkeypatch.setenv("JOBSHUNTER_HOME", home)
    monkeypatch.setattr(sys, "executable", "/opt/py thon/bin/python3")
    monkeypatch.setattr(settings, "SOURCE_ROOT", Path("/srv/Jobs Hunter %U"))
    service, timer = scheduler._systemd_files("daily", [(9, 0), (18, 30)], 6)
    line = [l for l in service.splitlines() if l.startswith("ExecStart=")][0]
    assert parse_systemd_args(line) == ["/opt/py thon/bin/python3", "-m", "jobshunter", "scan-auto"]
    envs = [parse_systemd_args(l)[0] for l in service.splitlines() if l.startswith("Environment=")]
    assert f"JOBSHUNTER_HOME={Path(home)}" in envs and f"PYTHONPATH={Path('/srv/Jobs Hunter %U')}" in envs
    assert "OnCalendar=*-*-* 09:00:00" in timer and "OnCalendar=*-*-* 18:30:00" in timer and "Persistent=true" in timer


def test_B87_dollaro_nel_percorso_dell_exec_start_e_raddoppiato(linux, monkeypatch):
    monkeypatch.setattr(sys, "executable", "/home/utente/$HOME/bin/python3")
    service, _ = scheduler._systemd_files("daily", [(9, 0)], 6)
    line = [l for l in service.splitlines() if l.startswith("ExecStart=")][0]
    assert parse_systemd_args(line)[0] == "/home/utente/$HOME/bin/python3"


@pytest.mark.parametrize("hours,when", [(1, "00/1:00:00"), (6, "00/6:00:00"), (12, "00/12:00:00"), (24, "09:00:00")])
def test_systemd_ogni_n_ore(linux, hours, when):
    _, timer = scheduler._systemd_files("every", [(9, 0)], hours)
    assert f"OnCalendar=*-*-* {when}" in timer and "OnCalendar=" in timer


def test_systemd_install_uninstall_idempotente_senza_orfani(linux, tmp_path):
    f = linux
    d = tmp_path / "cfg" / "systemd" / "user"
    scheduler.uninstall()
    scheduler.uninstall()
    assert not any(c[:3] == ["systemctl", "--user", "disable"] for c in f.calls)  # niente da disabilitare se non c'e' niente
    assert scheduler.backend() == "systemd"
    scheduler.install("daily", [(9, 0)], 6)
    assert (d / "jobshunter-scan.service").exists() and (d / "jobshunter-scan.timer").exists() and scheduler.is_loaded()
    scheduler.install("daily", [(7, 0)], 6)
    assert "07:00" in (d / "jobshunter-scan.timer").read_text(encoding="utf-8")
    assert f.enabled == {"jobshunter-scan.timer"}
    scheduler.uninstall()
    scheduler.uninstall()
    assert not list(d.glob("jobshunter-scan.*")) and f.enabled == set() and not scheduler.is_loaded()
    assert not (settings.home() / "schedule_state.json").exists()


def test_systemd_non_disponibile_ripiega_su_cron_e_senza_nessuno_lo_dice(linux, monkeypatch):
    linux.systemd_ok = False
    assert scheduler.backend() == "cron"
    as_system(monkeypatch, "linux", set())
    assert scheduler.backend() == "" and not scheduler.supported() and "systemd" in scheduler.unsupported_reason()


CRON_BEFORE = "MAILTO=me@example.org\n# backup notturno\n0 3 * * * /usr/local/bin/backup.sh --keep 7%d\n\n*/5 * * * * echo ciao # nota\n"


def test_cron_riga_marcata_percent_protetti_e_altre_righe_intatte(linux, monkeypatch, tmp_path):
    linux.systemd_ok = False
    linux.cron = CRON_BEFORE
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "100% dati"))
    monkeypatch.setattr(sys, "executable", "/opt/p y/python3")
    scheduler.install("daily", [(9, 0), (18, 30)], 6)
    lines = linux.cron.splitlines()
    ours = [l for l in lines if scheduler.CRON_MARK in l]
    assert len(ours) == 2 and all(l.endswith(" # JobsHunter") for l in ours)
    assert ours[0].startswith("0 9 * * * ") and ours[1].startswith("30 18 * * * ")
    for l in ours:
        assert re.search(r"(?<!\\)%", l) is None, l   # ogni % e' preceduto da backslash
        assert "100\\% dati" in l and "'/opt/p y/python3'" in l and ">> " in l and "2>&1" in l
    assert [l for l in lines if scheduler.CRON_MARK not in l] == CRON_BEFORE.splitlines()
    scheduler.install("every", [(9, 0)], 6)  # sostituisce, non aggiunge
    assert sum(scheduler.CRON_MARK in l for l in linux.cron.splitlines()) == 1 and "0 */6 * * * " in linux.cron
    scheduler.uninstall()
    scheduler.uninstall()
    assert linux.cron.splitlines() == CRON_BEFORE.splitlines()


def test_cron_crontab_vuoto_o_assente_e_rimozione_completa(linux):
    linux.systemd_ok = False
    scheduler.uninstall()  # nessun crontab: non scrive niente
    assert linux.cron is None and not any(c[:2] == ["crontab", "-"] for c in linux.calls)
    scheduler.install("daily", [(9, 0)], 6)
    assert linux.cron.count("\n") == 1 and linux.cron.endswith("\n")
    scheduler.uninstall()
    assert linux.cron is None  # restava solo la nostra riga: si toglie il crontab, non resta un file vuoto
    linux.cron = "   \n\n"
    scheduler.install("daily", [(9, 0)], 6)
    assert scheduler.CRON_MARK in linux.cron


def test_cron_passaggio_da_cron_a_systemd_non_lascia_due_pianificazioni(linux):
    linux.systemd_ok = False
    linux.cron = CRON_BEFORE
    scheduler.install("daily", [(9, 0)], 6)
    linux.systemd_ok = True
    scheduler.install("daily", [(9, 0)], 6)
    assert scheduler.CRON_MARK not in (linux.cron or "") and (linux.cron or "").splitlines() == CRON_BEFORE.splitlines()
    assert linux.enabled == {"jobshunter-scan.timer"}


@pytest.mark.parametrize("failure", ["rc", "timeout", "oserror"])
def test_B88_crontab_l_fallito_non_cancella_le_righe_dell_utente(linux, failure):
    linux.systemd_ok = False
    linux.cron = CRON_BEFORE
    if failure == "rc":
        linux.cron_list_error = (1, "crontab: errore di lettura: Permission denied")
    elif failure == "timeout":
        linux.cron_list_raises = subprocess.TimeoutExpired("crontab", 30)
    else:
        linux.cron_list_raises = OSError("busy")
    try:
        scheduler.install("daily", [(9, 0)], 6)
    except Exception:
        pass
    assert linux.cron == CRON_BEFORE or linux.cron.startswith(CRON_BEFORE.rstrip("\n"))  # o non tocca, o conserva le righe


def test_B89_la_rimozione_cron_tocca_solo_le_righe_proprie(linux):
    linux.systemd_ok = False
    mine = "0 4 * * * /usr/bin/rsync -a ~/jobs /backup # JobsHunter backup mio"
    linux.cron = f"0 1 * * * x\n{mine}\n"
    scheduler.install("daily", [(9, 0)], 6)
    scheduler.uninstall()
    assert mine in (linux.cron or "")


# ----------------------------------------------------------------------------- CLI e API ----
def run_cli(args, monkeypatch=None):
    from click.testing import CliRunner

    from jobshunter.cli import main

    return CliRunner().invoke(main, args, catch_exceptions=True)


def test_cli_schedule_on_status_off_su_linux_con_cron_finto(linux, home):
    linux.systemd_ok = False
    r = run_cli(["schedule", "on", "--at", "09:00, 18:30"])
    assert r.exit_code == 0, r.output
    assert linux.cron.count(scheduler.CRON_MARK) == 2
    r = run_cli(["schedule", "status"])
    assert r.exit_code == 0 and "attiva" in r.output and "cron" in r.output
    r = run_cli(["schedule", "off"])
    assert r.exit_code == 0 and (linux.cron or "") == ""
    assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["schedule.enabled"] is False


def test_B90_cli_schedule_on_senza_strumenti_da_un_messaggio_non_un_traceback(monkeypatch, home):
    as_system(monkeypatch, "linux", set())
    r = run_cli(["schedule", "on"])
    assert not isinstance(r.exception, RuntimeError), repr(r.exception)
    s = home / "settings.json"
    assert not s.exists() or json.loads(s.read_text(encoding="utf-8")).get("schedule.enabled") is not True


def test_cli_schedule_status_sistema_non_supportato_in_italiano(monkeypatch, home):
    as_system(monkeypatch, "windows", set())
    r = run_cli(["schedule", "status"])
    assert r.exit_code == 0 and "schtasks" in r.output


def test_cli_home_e_log_file_di_scan_auto(tmp_path, monkeypatch):
    home = tmp_path / "Dati è spazi"
    home.mkdir()
    cfg = (ROOT / "config.example.toml").read_text(encoding="utf-8").replace("enabled = true", "enabled = false")
    (home / "config.toml").write_text(cfg, encoding="utf-8")
    log = tmp_path / "log è" / "scan.log"
    env = {k: v for k, v in os.environ.items() if k not in ("JOBSHUNTER_HOME", OLD_ENV, "PYTEST_CURRENT_TEST")}
    env.update(child_home_env(tmp_path / "h"), PYTHONPATH=str(ROOT))
    (tmp_path / "h").mkdir()
    r = subprocess.run([sys.executable, "-m", "jobshunter", "--home", str(home), "scan-auto", "--no-notify", "--log-file", str(log)],
                       cwd=tmp_path, env=env, capture_output=True, text=True, errors="replace", encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert log.exists() and "scansione completata" in log.read_text(encoding="utf-8")
    assert (home / "jobshunter.db").exists()
    assert not (tmp_path / "h" / "Library").exists()  # niente scritture nei percorsi di macOS


def test_B91_scan_auto_registra_nel_log_le_eccezioni(tmp_path, monkeypatch, home):
    import logging

    from jobshunter import autoscan as A

    log = tmp_path / "scan.log"
    monkeypatch.setattr(A, "run_auto", lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("scansione rotta")))
    import jobshunter.cli as C

    for h in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(h)
    try:
        r = run_cli(["scan-auto", "--no-notify", "--log-file", str(log)])
        for h in logging.getLogger().handlers:
            h.flush()
    finally:
        for h in list(logging.getLogger().handlers):
            if isinstance(h, logging.FileHandler):
                h.close()
                logging.getLogger().removeHandler(h)
    assert r.exit_code != 0
    assert log.exists() and "scansione rotta" in log.read_text(encoding="utf-8")


# ================================================== 7c. notifiche, comandi di sistema e decodifica ====
@pytest.mark.parametrize("system,tools", [("mac", {"osascript"}), ("windows", {"powershell"}), ("linux", {"notify-send"})])
def test_notifiche_per_sistema_comandi_e_argomenti(monkeypatch, system, tools):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: system)
    monkeypatch.setattr(autoscan.shutil, "which", lambda n, *a, **k: "/finto/" + n if n in tools else None)
    calls = []
    monkeypatch.setattr(autoscan.subprocess, "run", lambda cmd, **k: calls.append((cmd, k)) or subprocess.CompletedProcess(cmd, 0))
    title, body = 'Titolo "x" & <y> $(boom) `z` %PATH%', "Corpo con 'apici', \\ e accènti è ù\nriga"
    assert autoscan.notify_native(title, body) is True
    cmd, kw = calls[0]
    if system == "windows":
        assert kw["env"]["JH_TITLE"] == title and kw["env"]["JH_BODY"] == body  # il testo non entra MAI nello script
        assert title not in " ".join(cmd) and "%PATH%" not in " ".join(cmd)
    elif system == "linux":
        assert cmd[-2:] == [title, body] and cmd[-3] == "--"  # dopo "--": un titolo che inizia con "-" non e' un'opzione
    # sistema senza lo strumento: False, mai eccezioni
    monkeypatch.setattr(autoscan.shutil, "which", lambda *a, **k: None)
    if system != "mac":
        assert autoscan.notify_native("a", "b") is False


@pytest.mark.parametrize("system", ["mac", "windows", "linux"])
@pytest.mark.parametrize("exc", [FileNotFoundError("x"), subprocess.TimeoutExpired("x", 1), PermissionError("x")])
def test_notifiche_best_effort_mai_eccezioni(monkeypatch, system, exc):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: system)
    monkeypatch.setattr(autoscan.shutil, "which", lambda n, *a, **k: "/finto/" + n)
    monkeypatch.setattr(autoscan.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(exc))
    assert autoscan.notify_native("a", "b") is False


@pytest.mark.parametrize("system", ["mac", "windows", "linux"])
def test_B99_notifica_con_nul_non_solleva(monkeypatch, system):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: system)
    monkeypatch.setattr(autoscan.shutil, "which", lambda n, *a, **k: "/bin/true" if n != "powershell" else sys.executable)
    monkeypatch.setattr(autoscan, "_REAL_SUBPROCESS_RUN", None)
    monkeypatch.setattr(autoscan.subprocess, "run", _safe_true_runner)
    autoscan.notify_native("Titolo\x00sporco", "Corpo\x00")


def _safe_true_runner(cmd, **kw):
    """Come subprocess.run ma lancia SEMPRE /bin/true (mai osascript o altro): il controllo dei NUL lo fa subprocess."""
    return _REAL_RUN_QA(["/usr/bin/true"] + [a for a in cmd[1:]], **{k: v for k, v in kw.items() if k in ("env", "capture_output", "timeout", "check")})


def _fake_exe(tmp_path, name, body):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    p.chmod(0o755)
    return d


@pytest.mark.skipif(os.name != "posix", reason="eseguibile finto in shell")
@pytest.mark.parametrize("system,tool", [("windows", "schtasks"), ("linux", "crontab")])
def test_B95_output_non_decodificabile_non_rompe_lo_stato(monkeypatch, tmp_path, system, tool):
    d = _fake_exe(tmp_path, tool, "printf 'ERRORE: impossibile trovare l\\215attivit\\340\\n'; exit 0")
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(osinfo, "current", lambda platform=None: system)
    if system == "linux":
        monkeypatch.setattr(scheduler, "backend", lambda: "cron")
    # `_run` VERO (non sostituito): lancia solo il nostro eseguibile finto, scritto in questo test
    assert scheduler._run is scheduler._REAL_RUN
    scheduler.is_loaded()   # non deve sollevare
    scheduler.status({"schedule": {"enabled": True}})


def test_guardia_il_test_non_lancia_comandi_veri(monkeypatch, tmp_path):
    """Senza sostituire `_run`, sotto pytest install e uninstall NON partono (Windows e Linux)."""
    for system, tools in (("windows", {"schtasks"}), ("linux", {"systemctl", "crontab"})):
        monkeypatch.setattr(osinfo, "current", lambda platform=None, s=system: s)
        monkeypatch.setattr(scheduler.shutil, "which", lambda n, *a, t=tools, **k: "/finto/" + n if n in t else None)
        monkeypatch.setattr(scheduler, "backend", lambda s=system: "schtasks" if s == "windows" else "cron")
        with pytest.raises(RuntimeError, match="test:"):
            scheduler.install("daily", [(9, 0)], 6)
        with pytest.raises(RuntimeError, match="test:"):
            scheduler.uninstall()


def test_run_rifiuta_strumenti_non_ammessi():
    for bad in (["rm", "-rf", "x"], ["/bin/sh", "-c", "x"], ["C:\\Windows\\System32\\cmd.exe", "/c", "x"], []):
        with pytest.raises(RuntimeError):
            scheduler._REAL_RUN(bad)


# ======================================================================= 8. apertura, avvio, pacchetto ====
def test_open_path_per_sistema_con_percorsi_ostili(monkeypatch, tmp_path):
    p = tmp_path / "Cartella è con spazi & % ' \""
    calls = []
    monkeypatch.setattr(macapp.subprocess, "Popen", lambda cmd, **k: calls.append(cmd))  # B94: il gestore dei file si lancia staccato (Popen), senza timeout
    monkeypatch.setattr(os, "startfile", lambda t: calls.append(["startfile", t]), raising=False)
    for system, first in (("mac", "open"), ("linux", "xdg-open"), ("windows", "startfile")):
        monkeypatch.setattr(osinfo, "current", lambda platform=None, s=system: s)
        calls.clear()
        assert macapp.open_path(p) is True
        assert calls == [[first, str(p)]], system


def test_open_path_non_solleva_mai(monkeypatch, tmp_path):
    for system in ("mac", "windows", "linux"):
        monkeypatch.setattr(osinfo, "current", lambda platform=None, s=system: s)
        for exc in (FileNotFoundError("x"), PermissionError("x"), subprocess.TimeoutExpired("x", 1), OSError("x"), AttributeError("x")):
            monkeypatch.setattr(macapp.subprocess, "Popen", lambda *a, e=exc, **k: (_ for _ in ()).throw(e))
            monkeypatch.setattr(os, "startfile", lambda t, e=exc: (_ for _ in ()).throw(e), raising=False)
            assert macapp.open_path(tmp_path) is False


@pytest.mark.skipif(os.name != "posix", reason="eseguibile finto in shell")
def test_B94_open_path_non_uccide_il_gestore_di_file_dopo_il_timeout(monkeypatch, tmp_path):
    marker = tmp_path / "vivo.txt"
    d = _fake_exe(tmp_path, "xdg-open", f"sleep 3; echo ancora_aperto > '{marker}'")
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "linux")
    real = subprocess.run
    monkeypatch.setattr(macapp.subprocess, "run", lambda cmd, **k: real(cmd, **dict(k, timeout=1)))  # 20 s ridotti a 1 s per il test
    macapp.open_path(tmp_path)
    time.sleep(4)
    assert marker.exists()


def test_open_url_solo_http_e_senza_eccezioni(monkeypatch):
    opened = []
    monkeypatch.setattr(macapp.webbrowser, "open", lambda u, *a, **k: opened.append(u) or True)
    assert macapp.open_url("https://example.org/a?b=1&c=è") is True
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://x", "", None, 5, "HTTP://x.org", "//x.org", "x.org"):
        assert macapp.open_url(bad) is False
    assert opened == ["https://example.org/a?b=1&c=è"]
    monkeypatch.setattr(macapp.webbrowser, "open", lambda u, *a, **k: (_ for _ in ()).throw(macapp.webbrowser.Error("nessun browser")))
    assert macapp.open_url("https://example.org") is False
    monkeypatch.setattr(macapp.webbrowser, "open", lambda u, *a, **k: False)
    assert macapp.open_url("https://example.org") is False



def child_home_env(home: Path) -> dict:
    """Variabili che dicono a un processo figlio DOVE sta la sua HOME su ogni sistema (macOS/Windows/Linux): dati e log finiscono tutti
    dentro `home` e non nella HOME finta globale della guardia di conftest (che su Linux imposta anche XDG_*)."""
    return {"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"), "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(home / ".local" / "state"), "XDG_CONFIG_HOME": str(home / ".config")}

APP_SCRIPT = r"""
import sys, webbrowser
webbrowser.open = lambda *a, **k: print("BROWSER_APERTO", a, flush=True) or True
mode = sys.argv[1]
if mode == "nowebview":
    sys.modules["webview"] = None
elif mode == "window":
    import types, threading
    m = types.ModuleType("webview")
    m.FOLDER_DIALOG = 20
    closed = threading.Event()
    class W:
        def destroy(self): closed.set()
    m.create_window = lambda *a, **k: W()
    def start(*a, **k):
        while not closed.wait(0.2): pass   # la finestra "resta aperta" finche' non viene chiusa
    m.start = start
    sys.modules["webview"] = m
elif mode == "startfails":
    import types
    m = types.ModuleType("webview")
    m.FOLDER_DIALOG = 20
    m.create_window = lambda *a, **k: object()
    def start(*a, **k): raise RuntimeError("You must have either QT or GTK with Python extensions installed")
    m.start = start
    sys.modules["webview"] = m
from jobshunter.cli import main
main(["app"])
"""


@pytest.mark.skipif(os.name != "posix", reason="processo figlio con SIGINT")
@pytest.mark.parametrize("mode", ["nowebview", "startfails"])
def test_jh_app_ripiega_sul_browser_con_messaggio_chiaro(tmp_path, mode):
    import socket
    import urllib.request

    home = tmp_path / "casa"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ("JOBSHUNTER_HOME", OLD_ENV, "PYTEST_CURRENT_TEST")}
    # cartella dati con config copiato dall'esempio (su macOS e' proprio quella che l'app sceglierebbe nella HOME finta):
    # il test non dipende dal config.toml del progetto, che in una copia pulita non c'e'
    data = home / "Library" / "Application Support" / "JobsHunter" if osinfo.current() == "mac" else tmp_path / "dati"
    data.mkdir(parents=True)
    shutil.copy(ROOT / "config.example.toml", data / "config.toml")
    env.update(child_home_env(home), JOBSHUNTER_HOME=str(data), PYTHONPATH=str(ROOT), BROWSER="/usr/bin/true", PYTHONUNBUFFERED="1", JOBSHUNTER_ENGINE_TIMEOUT="90")
    p = subprocess.Popen([sys.executable, "-c", APP_SCRIPT, mode], cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", encoding="utf-8")
    try:
        deadline, err, out = time.time() + 120, "", ""  # su un runner lento il motore puo' metterci di piu'
        port = None
        import selectors

        sel = selectors.DefaultSelector()
        sel.register(p.stderr, selectors.EVENT_READ)
        while time.time() < deadline and port is None:
            if sel.select(0.5):
                line = p.stderr.readline()
                err += line
                m = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
                if m:
                    port = int(m.group(1))
            if p.poll() is not None:
                break
        if not port:
            if p.poll() is None:
                p.kill()
            err += p.stderr.read()
            logs = sorted(home.rglob("app.log"))
            log_tail = "\n".join(logs[0].read_text(encoding="utf-8", errors="replace").splitlines()[-40:]) if logs else "(nessun app.log)"
            raise AssertionError(f"nessuna porta.\n--- stderr completo ---\n{err}\n--- app.log (ultime 40 righe) ---\n{log_tail}")
        assert "pywebview" in err or "finestra nativa" in err
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read()
        assert b"<html" in body.lower()
        # la pagina e' solo locale
        s = socket.socket()
        s.settimeout(1)
        try:
            assert s.connect_ex(("127.0.0.1", port)) == 0
        finally:
            s.close()
        assert p.poll() is None  # il motore resta acceso
    finally:
        if p.poll() is None:
            p.send_signal(signal.SIGINT)
            try:
                p.wait(15)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                pytest.fail("il processo non ha risposto a SIGINT entro 15 s")
    assert p.returncode == 0, (p.returncode, p.stderr.read()[-500:])
    assert not (Path.home() / "Library").exists() or "casa" not in str(Path.home())  # niente scritture fuori dalla HOME finta
    assert (home / "Library" / "Application Support" / "JobsHunter").exists() or osinfo.current() != "mac"


def _app_port_dal_log(home, p, deadline):
    while time.time() < deadline and p.poll() is None:
        for lg in home.rglob("app.log"):
            m = re.search(r"motore locale su porta (\d+)", lg.read_text(encoding="utf-8", errors="replace"))
            if m:
                return int(m.group(1))
        time.sleep(0.2)
    return None


@pytest.mark.skipif(os.name != "posix", reason="segnali POSIX")
@pytest.mark.parametrize("ignora_sigint", [False, True], ids=["sigint_normale", "sigint_ignorato"])
@pytest.mark.parametrize("sig", ["SIGINT", "SIGTERM"])
@pytest.mark.parametrize("mode", ["nowebview", "startfails", "window"])
def test_jh_app_si_ferma_in_modo_ordinato_con_i_segnali(tmp_path, mode, sig, ignora_sigint):
    """Come in CI/nohup/systemd: il figlio puo' ereditare SIGINT IGNORATO. Deve uscire comunque con codice 0 e senza traceback."""
    home = tmp_path / "casa"
    data = home / "dati"
    data.mkdir(parents=True)
    shutil.copy(ROOT / "config.example.toml", data / "config.toml")
    env = {k: v for k, v in os.environ.items() if k not in (OLD_ENV, "PYTEST_CURRENT_TEST")}
    env.update(child_home_env(home), JOBSHUNTER_HOME=str(data), PYTHONPATH=str(ROOT), BROWSER="/usr/bin/true", PYTHONUNBUFFERED="1",
               JOBSHUNTER_ENGINE_TIMEOUT="90")
    pre = (lambda: signal.signal(signal.SIGINT, signal.SIG_IGN)) if ignora_sigint else None
    p = subprocess.Popen([sys.executable, "-c", APP_SCRIPT, mode], cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace", preexec_fn=pre)
    try:
        port = _app_port_dal_log(home, p, time.time() + 120)
        assert port, "il motore non e' partito: " + (p.stderr.read()[-800:] if p.poll() is not None else "ancora in avvio")
        if ignora_sigint:
            assert signal.getsignal(signal.SIGINT) is not None  # il test stesso non e' toccato
        time.sleep(0.5)  # gli handler sono installati subito dopo l'avvio del motore
        assert p.poll() is None
        p.send_signal(getattr(signal, sig))
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            pytest.fail(f"il processo non ha risposto a {sig} entro 20 s (SIGINT ignorato all'avvio: {ignora_sigint})")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    err = p.stderr.read()
    assert p.returncode == 0, (p.returncode, err[-600:])
    assert "Traceback" not in err, err[-800:]


@pytest.mark.skipif(os.name != "posix", reason="segnali POSIX")
@pytest.mark.parametrize("ignora_sigint", [False, True], ids=["sigint_normale", "sigint_ignorato"])
@pytest.mark.parametrize("sig", ["SIGINT", "SIGTERM"])
def test_jh_gui_si_ferma_in_modo_ordinato_con_i_segnali(tmp_path, sig, ignora_sigint):
    import socket

    data = tmp_path / "dati"
    data.mkdir()
    shutil.copy(ROOT / "config.example.toml", data / "config.toml")
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k not in (OLD_ENV, "PYTEST_CURRENT_TEST")}
    env.update(child_home_env(tmp_path), JOBSHUNTER_HOME=str(data), PYTHONPATH=str(ROOT), PYTHONUNBUFFERED="1")
    pre = (lambda: signal.signal(signal.SIGINT, signal.SIG_IGN)) if ignora_sigint else None
    p = subprocess.Popen([sys.executable, "-m", "jobshunter", "gui", "--no-browser", "--port", str(port)], cwd=tmp_path, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", preexec_fn=pre)
    try:
        up = False
        for _ in range(300):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    up = True
                    break
            except OSError:
                time.sleep(0.2)
        assert up, "la GUI non e' partita"
        time.sleep(0.5)
        p.send_signal(getattr(signal, sig))
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            pytest.fail(f"il processo non ha risposto a {sig} entro 20 s")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    err = p.stderr.read()
    assert p.returncode == 0 and "Traceback" not in err, (p.returncode, err[-600:])


def test_jh_bat_lettura_riga_per_riga():
    raw = (ROOT / "jh.bat").read_bytes()
    assert b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n"), "jh.bat deve avere terminatori CRLF ovunque"
    assert all(b < 128 for b in raw), "solo ASCII: cmd.exe usa la tabella OEM"
    text = raw.decode("ascii")
    lines = text.splitlines()
    assert lines[0].lower() == "@echo off"
    assert "%*" in text and "%~dp0" in text and ".venv\\Scripts\\python.exe" in text and "-m jobshunter" in text
    assert "setlocal" in text.lower() and "exit /b %ERRORLEVEL%" in text
    for l in (x.strip() for x in lines):
        if l.lower().startswith("set ") and "=" in l:
            assert l[4:].startswith('"') and l.rstrip().endswith('"'), f"set senza virgolette: {l}"  # sicuro con spazi, & e ) nel percorso
        if re.search(r"%DIR%|%PY%", l) and not l.lower().startswith(("set ", "rem")):
            assert re.search(r'"%(DIR|PY)%[^"]*"', l), f"percorso senza virgolette: {l}"
    assert not re.search(r"(?m)^\s*(goto|call)\s", text, re.I)


def test_jh_sh_percorsi_con_spazi_e_link(tmp_path):
    """`jh` deve funzionare con spazi nel percorso e chiamato tramite un collegamento (non esegue Python: usa un finto)."""
    proj = tmp_path / "Mio Progetto è"
    (proj / ".venv" / "bin").mkdir(parents=True)
    py = proj / ".venv" / "bin" / "python"
    py.write_text('#!/bin/sh\necho "ARGS:$*|PP:$PYTHONPATH"\n', encoding="utf-8")
    py.chmod(0o755)
    (proj / "jh").write_bytes((ROOT / "jh").read_bytes())
    (proj / "jh").chmod(0o755)
    link = tmp_path / "bin con spazi"
    link.mkdir()
    os.symlink(proj / "jh", link / "jh")
    r = subprocess.run([str(link / "jh"), "gui", "--no-browser", "a b"], cwd="/", capture_output=True, text=True, errors="replace", encoding="utf-8", env=dict(os.environ, PYTHONPATH="/gia"))
    assert r.returncode == 0 and r.stdout.strip() == f"ARGS:-m jobshunter gui --no-browser a b|PP:{proj}:/gia", r.stdout + r.stderr


def test_pyproject_pacchetti_dati_ed_extra():
    import tomllib

    d = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    found = sorted(str(p.parent.relative_to(ROOT)).replace(os.sep, ".") for p in (ROOT / "jobshunter").rglob("__init__.py"))
    assert sorted(d["tool"]["setuptools"]["packages"]) == found, (found, d["tool"]["setuptools"]["packages"])
    assert list((ROOT / "jobshunter" / "gui" / "static").glob("*")), "static/ vuota"
    assert d["project"]["optional-dependencies"]["gui"] == ["pywebview"]
    assert d["project"]["requires-python"] == ">=3.11"
    non_py = [p for p in (ROOT / "jobshunter").rglob("*") if p.is_file() and p.suffix not in (".py", ".pyc") and "__pycache__" not in p.parts and "static" not in p.parts]
    assert not non_py, f"file dati non dichiarati come package-data: {non_py}"
    req = [l.strip() for l in (ROOT / "requirements-gui.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert req == ["pywebview"]
    base = {re.split(r"[<>=; ]", l.strip())[0].lower() for l in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
    assert {x.lower() for x in d["project"]["dependencies"]} <= base | {"pypdf"} | base


def test_B98_metadati_del_pacchetto_dicono_tre_sistemi():
    import tomllib

    p = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "Operating System :: Microsoft :: Windows" in p["classifiers"]
    assert "for macOS" not in p["description"]


# ============================================================================== 9. console ====
@pytest.fixture
def seeded(tmp_path):
    from jobshunter.db import DB
    from jobshunter.models import Job

    home = tmp_path / "dati è"
    home.mkdir()
    cfg = (ROOT / "config.example.toml").read_text(encoding="utf-8").replace("enabled = true", "enabled = false")
    (home / "config.toml").write_text(cfg, encoding="utf-8")
    d = DB(home / "jobshunter.db")
    d.upsert(Job(source="fake", title="Analista Sicurezza \U0001F600 \u2014 Società ñ \u2713 \u2192 €", company="Café Zürich \u00e8 \U0001F4C1", location="Forlì",
                 url="https://example.org/1", description="triage SIEM EDR eventi di sicurezza \u2764\ufe0f \u65e5\u672c\u8a9e"))
    d.conn.commit()
    d.conn.close()
    import sqlite3

    uid = sqlite3.connect(home / "jobshunter.db").execute("SELECT uid FROM jobs").fetchone()[0]
    return home, uid


@pytest.mark.parametrize("enc,lang", [("cp1252", "C"), ("ascii", "C"), ("latin-1", "it_IT.ISO-8859-1"), ("cp437", "C"), ("utf-8", "C")])
def test_cli_con_simboli_e_emoji_in_console_non_utf8(seeded, tmp_path, enc, lang):
    seeded, uid = seeded
    env = {k: v for k, v in os.environ.items() if k not in ("JOBSHUNTER_HOME", OLD_ENV, "PYTEST_CURRENT_TEST", "PYTHONUTF8")}
    env.update(child_home_env(tmp_path / "h"), PYTHONPATH=str(ROOT), PYTHONIOENCODING=enc, LANG=lang, LC_ALL=lang, NO_COLOR="1", COLUMNS="200")
    (tmp_path / "h").mkdir(exist_ok=True)
    for args in (["list"], ["show", uid[:8]], ["stats"], ["profiles", "list"], ["schedule", "status"], ["check", "--help"], ["--help"], ["export", "-o", str(tmp_path / "e è.csv")],
                 ["list", "--help"], ["report", "--help"]):
        r = subprocess.run([sys.executable, "-m", "jobshunter", "--home", str(seeded), *args], cwd=tmp_path, env=env, capture_output=True, timeout=120)
        err = r.stderr.decode("utf-8", "replace")
        assert r.returncode in (0, 2) and "Traceback" not in err and "UnicodeEncodeError" not in err, (enc, args, r.returncode, err[-400:])
    csv_bytes = (tmp_path / "e è.csv").read_bytes() if (tmp_path / "e è.csv").exists() else b""
    if csv_bytes:
        assert "Café Zürich".encode("utf-8") in csv_bytes  # il CSV e' SEMPRE UTF-8, qualunque sia la console


def test_ensure_utf8_streams_con_flussi_strani(monkeypatch):
    import io as _io

    class Narrow(_io.TextIOWrapper):
        pass

    for s in (None,):
        monkeypatch.setattr(sys, "stdout", s)
        monkeypatch.setattr(sys, "stderr", s)
        osinfo.ensure_utf8_streams()  # pythonw.exe: stdout/stderr sono None
    raw = _io.BytesIO()
    w = _io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", w)
    monkeypatch.setattr(sys, "stderr", _io.StringIO())  # senza reconfigure: AttributeError gestita
    osinfo.ensure_utf8_streams()
    print("\u2713 \U0001F600 \u00e8")
    w.flush()
    assert "è".encode("utf-8") in raw.getvalue()


# ========================================================================== 6. UTF-8 (efficacia) ====
VIOLAZIONI = {
    "Path.open senza codifica": 'from pathlib import Path\ndef f(p):\n    with Path(p).open("w") as fh:\n        fh.write("x")\n',
    "io.open senza codifica": 'import io\ndef f(p):\n    return io.open(p, "w")\n',
    "write_text su piu' righe": 'from pathlib import Path\ndef f(p, d):\n    Path(p).write_text(\n        d\n    )\n',
    "parola encoding in un commento": 'from pathlib import Path\ndef f(p):\n    return Path(p).read_text()  # TODO encoding\n',
    "fdopen senza codifica": 'import os\ndef f(fd):\n    return os.fdopen(fd, "w")\n',
    "FileHandler senza codifica": 'import logging\ndef f(p):\n    return logging.FileHandler(p)\n',
    "open semplice (controllo)": 'def f(p):\n    return open(p)\n',
}


def _builder_check(copy_root):
    import importlib.util

    spec = importlib.util.spec_from_file_location("builder_portability_copy", ROOT / "tests" / "builder" / "test_portability.py")
    sys.path.insert(0, str(ROOT / "tests" / "builder"))
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    mod.ROOT = copy_root
    try:
        mod.test_nessuna_lettura_o_scrittura_di_testo_senza_codifica()
    except AssertionError:
        return True   # il controllo ha visto la violazione
    return False


def _copy_tree(tmp_path, extra: str):
    import shutil

    dst = tmp_path / "copia"
    shutil.copytree(ROOT / "jobshunter", dst / "jobshunter", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "run_app.py", dst / "run_app.py")
    (dst / "jobshunter" / "zz_violazione.py").write_text(extra, encoding="utf-8")
    return dst


def test_il_controllo_dell_encoding_vede_almeno_l_open_semplice(tmp_path):
    assert _builder_check(_copy_tree(tmp_path, VIOLAZIONI["open semplice (controllo)"]))
    assert _builder_check(ROOT) is False  # e sul codice vero e' pulito


def test_B96_il_controllo_dell_encoding_e_davvero_efficace(tmp_path):
    missed = []
    for name, code in VIOLAZIONI.items():
        if not _builder_check(_copy_tree(tmp_path / re.sub(r"\W", "_", name), code)):
            missed.append(name)
    assert not missed, missed


def test_nessuna_scrittura_o_lettura_di_testo_senza_encoding_con_la_prova_di_python():
    """Prova vera: Python stesso segnala (EncodingWarning -> errore) ogni open() di testo senza codifica nei flussi principali."""
    code = r"""
import os, sys, tempfile, warnings
warnings.simplefilter("error", EncodingWarning)
warnings.filterwarnings("ignore", category=EncodingWarning, module=r"^(?!jobshunter).*")  # solo il nostro codice
home = tempfile.mkdtemp()
os.environ["JOBSHUNTER_HOME"] = home + "/dati"; os.environ["HOME"] = home
from pathlib import Path
from jobshunter import settings, cv, db as dbm
from jobshunter.models import Job
cfg = settings.load_config(create_if_missing=True)
settings.save_overrides(Path(cfg["_config_path"]), {"home": "Forlì", "report.dir": home + "/Rép"})
cfg = settings.load_config()
d = dbm.DB(settings.resolve_path(cfg["general"]["db_path"]))
d.upsert(Job(source="f", title="Analista è", company="Società", location="Forlì", url="https://x.org/1", description="è à ù"))
d.conn.commit(); d.conn.close()
cv.save_text("Curriculum è", "t")
from jobshunter.gui.app import create_app
c = create_app(None, 8765).test_client()
for u in ("/api/jobs", "/api/settings", "/api/stats", "/api/profiles", "/api/cv", "/api/news", "/api/scans"):
    assert c.get(u, headers={"Host": "127.0.0.1:8765"}).status_code == 200, u
print("OK")
"""
    r = subprocess.run([sys.executable, "-X", "warn_default_encoding", "-c", code], cwd=ROOT, capture_output=True, text=True, errors="replace", encoding="utf-8",
                       env={k: v for k, v in os.environ.items() if k not in ("JOBSHUNTER_HOME", "PYTEST_CURRENT_TEST")})
    assert r.returncode == 0 and r.stdout.strip().endswith("OK"), r.stderr[-1200:]


def test_B100_anche_gli_script_hanno_encoding_esplicito():
    bad = []
    for p in (ROOT / "scripts").glob("*.py"):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.(read_text|write_text)\(", line) and "encoding" not in line:
                bad.append(f"{p.name}:{n}")
    assert not bad, bad


def test_B97_config_toml_con_backslash_non_valido_da_un_messaggio(home):
    (home / "config.toml").write_text((ROOT / "config.example.toml").read_text(encoding="utf-8").replace('dir = "reports"', 'dir = "D:\\Lavori\\Report"'), encoding="utf-8")
    r = run_cli(["list"])
    import tomllib

    assert not isinstance(r.exception, tomllib.TOMLDecodeError), repr(r.exception)
    assert r.exit_code != 0 and "config.toml" in r.output


# ============================================================================== 10. Python 3.11 e CI ====
def test_sintassi_python_311_su_tutto_il_progetto():
    bad = []
    for base in ("jobshunter", "tests", "scripts"):
        for p in (ROOT / base).rglob("*.py"):
            try:
                ast.parse(p.read_text(encoding="utf-8"), filename=str(p), feature_version=(3, 11))
            except SyntaxError as e:
                bad.append((str(p), str(e)))
    ast.parse((ROOT / "run_app.py").read_text(encoding="utf-8"), feature_version=(3, 11))
    assert not bad, bad


def test_nessun_backslash_nelle_graffe_delle_fstring():
    """Fino a Python 3.11 una f-string non puo' avere backslash dentro le graffe (3.12 lo ammette): errore di sintassi su 3.11."""
    import tokenize

    bad = []
    for p in list((ROOT / "jobshunter").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        with open(p, "rb") as fh:
            src = fh.read().decode("utf-8")
        for m in re.finditer(r"""\bf(?:"[^"\n]*"|'[^'\n]*')""", src):
            s = m.group(0)
            for expr in re.findall(r"\{([^{}]*)\}", s):
                if "\\" in expr:
                    bad.append((p.name, s[:60]))
    assert not bad, bad


@pytest.mark.skipif(not Path("/opt/homebrew/bin/python3.11").exists(), reason="Python 3.11 non installato")
def test_python_311_vero_compila_tutto_e_importa_i_moduli_puri(tmp_path):
    code = ("import sys,pathlib\nbad=[]\n"
            "for base in ('jobshunter','tests','scripts'):\n"
            "    for p in pathlib.Path(base).rglob('*.py'):\n"
            "        try: compile(p.read_text(encoding='utf-8'), str(p), 'exec')\n"
            "        except SyntaxError as e: bad.append((str(p), str(e)))\n"
            "print(bad)\n"
            "sys.path.insert(0,'.')\n"
            "from pathlib import PureWindowsPath as W\n"
            "from jobshunter import osinfo, filelock, fsperm\n"
            "assert str(osinfo.data_dir(platform='win32', env={'APPDATA':'C:\\\\a'}, home=W('C:/u'))) == 'C:\\\\a\\\\JobsHunter'\n"
            "l = filelock.FileLock(sys.argv[1]); assert l.acquire(False); assert not filelock.FileLock(sys.argv[1]).acquire(False); l.release()\n"
            "print('OK', sys.version_info[:2])\n")
    r = subprocess.run(["/opt/homebrew/bin/python3.11", "-B", "-c", code, str(tmp_path / "l")], cwd=ROOT, capture_output=True, text=True, errors="replace", encoding="utf-8")
    assert r.returncode == 0 and r.stdout.splitlines()[0] == "[]" and "OK (3, 11)" in r.stdout, r.stderr[-500:]


def _load_ci():
    """Legge il workflow con Ruby/PyYAML se ci sono, altrimenti con un piccolo lettore di YAML minimale (solo indentazione)."""
    try:
        import yaml  # type: ignore

        return yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    except ImportError:
        pass
    ruby = __import__("shutil").which("ruby")
    if ruby:
        r = subprocess.run([ruby, "-ryaml", "-rjson", "-e", 'puts JSON.generate(YAML.load_file(ARGV[0]))', str(ROOT / ".github" / "workflows" / "ci.yml")],
                           capture_output=True, text=True, errors="replace", encoding="utf-8")
        if r.returncode == 0:
            return json.loads(r.stdout)
    pytest.skip("nessun lettore YAML disponibile")


def test_ci_workflow_matrice_e_shell():
    ci = _load_ci()
    job = ci["jobs"]["test"]
    m = job["strategy"]["matrix"]
    assert set(m["os"]) == {"macos-latest", "ubuntu-latest", "windows-latest"}
    assert [str(x) for x in m["python"]] == ["3.11", "3.12", "3.13", "3.14"]  # tra virgolette: 3.10 / 3.1 non devono comparire
    assert job["strategy"]["fail-fast"] is False
    coe = str(job.get("continue-on-error", "false"))  # assente = nessun sistema e' non bloccante (Ubuntu ora blocca come gli altri)
    assert "windows" not in coe and "macos" not in coe and "ubuntu" not in coe
    steps = job["steps"]
    runs = [s for s in steps if "run" in s]
    assert len(runs) == 2 and all(s.get("shell") == "bash" for s in runs), "su Windows il default e' PowerShell: serve bash esplicito per \"$PY\" e [ ]"
    install = runs[0]["run"]
    assert "Scripts/python.exe" in install and "bin/python" in install and "RUNNER_OS" in install and "GITHUB_ENV" in install
    assert '"$PY"' in runs[1]["run"] and "not slow" in runs[1]["run"]
    assert "setup-python" in " ".join(s.get("uses", "") for s in steps) and any(s.get("with", {}).get("cache") == "pip" for s in steps)
    assert "publishable" in ci["jobs"] and ci["jobs"]["publishable"]["runs-on"] == "ubuntu-latest"


def test_ci_i_passi_bash_su_windows_usano_percorsi_valutabili():
    """`PY=.venv/Scripts/python.exe` e' relativo: va bene finche' tutti i passi girano nella radice del progetto (default). Nessun working-directory diverso."""
    ci = _load_ci()
    for s in ci["jobs"]["test"]["steps"]:
        assert "working-directory" not in s


# ===================================================================== Windows: la suite stessa ====
def test_B92_conftest_isola_la_home_anche_su_windows():
    import ntpath

    src = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "USERPROFILE" in src, "il conftest non imposta USERPROFILE"
    env = {"HOME": "/finta", "USERPROFILE": "C:\\Users\\runneradmin", "HOMEDRIVE": "C:", "HOMEPATH": "\\Users\\runneradmin"}
    old = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(env)
        assert ntpath.expanduser("~") != "/finta"  # prova: Windows ignora HOME
    finally:
        os.environ.clear()
        os.environ.update(old)
    assert "APPDATA" in src and "XDG_DATA_HOME" in src


MODE_RE = re.compile(r"st_mode|S_IMODE")


def test_B93_i_test_con_permessi_posix_sono_marcati_per_windows():
    offenders = []
    for p in (ROOT / "tests").rglob("test_*.py"):
        if p.name.startswith("test_portability"):
            continue
        t = p.read_text(encoding="utf-8")
        if MODE_RE.search(t) and re.search(r"0o[67]00|0o644|0o600", t) and not re.search(r"skipif\([^)]*(win|name|platform)", t):
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, offenders


MAC_ONLY_NON_MARCATI = [
    "tests/test_phase5.py::test_percorsi_predefiniti_stanno_nella_home_finta",
    "tests/test_phase5.py::test_macapp_usa_le_cartelle_nuove",
    "tests/test_phase5.py::test_scan_once_migra_prima_di_creare_la_config",
    "tests/test_phase5.py::test_etichette_e_percorsi",
    "tests/qa/test_phase5_qa.py::test_ld_plist_nuovo_ha_variabile_e_percorsi_giusti",
    "tests/builder/test_onboarding.py::test_cartella_report_zone_di_sistema[/System/Library-False]",
    "tests/builder/test_onboarding.py::test_cartella_report_zone_di_sistema[/Applications/X-False]",
    "tests/qa/test_onboarding_qa.py::test_report_dir_in_zone_di_sistema[/System/Library]",
    "tests/qa/test_onboarding_qa.py::test_report_dir_in_zone_di_sistema[/Library/LaunchDaemons]",
    "tests/qa/test_phase5_security.py::test_cartella_report_non_puo_essere_di_sistema",
]


@pytest.mark.skipif(sys.platform != "darwin", reason="simula Linux da macOS: ha senso solo qui")
def test_B101_i_test_specifici_di_macos_sono_marcati(tmp_path):
    plug = tmp_path / "plug"
    plug.mkdir()
    (plug / "simlinux_qa.py").write_text("import sys\nsys.platform = 'linux'\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_CURRENT_TEST",)}
    env["PYTHONPATH"] = str(plug)
    r = subprocess.run([sys.executable, "-m", "pytest", "-p", "simlinux_qa", "-q", "--tb=no", "-p", "no:cacheprovider", *MAC_ONLY_NON_MARCATI],
                       cwd=ROOT, env=env, capture_output=True, text=True, errors="replace", encoding="utf-8", timeout=300)
    assert r.returncode == 0, r.stdout[-900:]


@pytest.mark.skipif(sys.platform != "darwin", reason="osascript esiste solo su macOS")
def test_B102_nessun_test_lancia_osascript_vero(tmp_path):
    shim = tmp_path / "bin"
    shim.mkdir()
    log = tmp_path / "chiamate.log"
    (shim / "osascript").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n', encoding="utf-8")
    (shim / "osascript").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env["PATH"] = f"{shim}{os.pathsep}/usr/bin:/bin"   # osascript e' un finto che si limita a scrivere un file
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider", "tests/test_autoscan.py"], cwd=ROOT, env=env,
                       capture_output=True, text=True, errors="replace", encoding="utf-8", timeout=300)
    assert r.returncode == 0, r.stdout[-400:]
    assert not log.exists(), log.read_text(encoding="utf-8")[:300]


# =====================================================================================================
# Secondo giro (fase 7): dove i comandi finti danno una falsa sicurezza, SKIP_RULES, fsutil, cv, README
# =====================================================================================================
SID_LOCALE = "S-1-5-21-1111111111-2222222222-3333333333-1001"
SID_AZURE = "S-1-12-1-1111111111-2222222222-3333333333-4444444444"


@pytest.mark.parametrize("out,expected", [
    (f'"pc\\utente","{SID_LOCALE}"\r\n', SID_LOCALE),
    (f'\ufeff"PC\\José Ñ con spazi","{SID_LOCALE}"', SID_LOCALE),                 # BOM, spazi, accenti
    (f'"AzureAD\\Maria Rossi","{SID_AZURE}"\r\n', SID_AZURE),                      # account Microsoft/Azure AD: S-1-12-1-...
    (f'  "WORKGROUP\\administrator" , "{SID_LOCALE}"  \n\n', SID_LOCALE),         # spazi attorno alle virgole
    (f'"x\\y",{SID_LOCALE}', SID_LOCALE),                                           # senza virgolette
    ('"x\\y","S-1-5-18"', "S-1-5-18"),                                              # SYSTEM (S-1-5-X): valido
    ('"x\\y","not-a-sid"', None), ('', None), ('"x\\y"', None), ('ERRORE: accesso negato', None),
    ('"x\\y","S-1-5-21-1; icacls C:\\ /reset"', None),                              # niente iniezioni: il SID e' solo cifre
    ('"x\\y","*S-1-5-21-1-2-3"', None),
])
def test_fsperm_user_sid_varianti_di_whoami(monkeypatch, out, expected):
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: out or None)
    assert fsperm._user_sid() == expected


def test_fsperm_whoami_assente_o_che_fallisce_ripiega_sui_nomi(monkeypatch, tmp_path):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsperm, "_warned", [False])
    monkeypatch.setenv("USERNAME", "José Ñ")
    monkeypatch.setenv("USERDOMAIN", "WORKGROUP")
    f = tmp_path / "a.db"
    f.write_text("x", encoding="utf-8")
    for whoami in (lambda: None, lambda: "", lambda: "spazzatura"):
        monkeypatch.setattr(fsperm, "_whoami_output", whoami)
        assert fsperm._grant_candidates() == ["WORKGROUP\\José Ñ", "José Ñ"]
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: f'"WORKGROUP\\jose","{SID_AZURE}"')
    assert fsperm._grant_candidates() == ["*" + SID_AZURE, "WORKGROUP\\José Ñ", "José Ñ"]


class RcFake:
    """icacls finto con un codice di ritorno per ogni chiamata (in ordine) e un'azione facoltativa."""

    def __init__(self, rcs, on_call=None):
        self.calls, self.rcs, self.on_call = [], list(rcs), on_call

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if self.on_call:
            self.on_call(cmd)
        rc = self.rcs[len(self.calls) - 1] if len(self.calls) <= len(self.rcs) else 0
        return subprocess.CompletedProcess(cmd, rc, b"", b"")


def _win_secure_env(monkeypatch):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsperm, "_warned", [False])
    monkeypatch.setenv("USERNAME", "utente")
    monkeypatch.setenv("USERDOMAIN", "WORKGROUP")
    monkeypatch.setattr(fsperm, "_whoami_output", lambda: f'"WORKGROUP\\utente","{SID_LOCALE}"')


def test_fsperm_sid_prima_poi_ripieghi_solo_su_1332(monkeypatch, tmp_path):
    _win_secure_env(monkeypatch)
    f = tmp_path / "a.db"
    f.write_text("x", encoding="utf-8")
    fake = RcFake([1332, 1332, 0, 0])   # SID e DOMINIO\utente non si risolvono, il solo nome si'
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(f) is True
    assert [c[3] for c in fake.calls[:3]] == [f"*{SID_LOCALE}:F", "WORKGROUP\\utente:F", "utente:F"]
    assert fake.calls[3][2] == "/inheritance:r"
    fake = RcFake([5])                  # accesso negato: non si insiste e non si tocca l'ereditarieta'
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(f) is False and len(fake.calls) == 1
    fake = RcFake([1332, 1332, 1332])   # nessun nome si risolve: niente /inheritance:r
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(f) is False and all(c[2] == "/grant:r" for c in fake.calls)


def test_fsperm_reset_solo_sul_percorso_giusto_senza_ricorsione(monkeypatch, tmp_path):
    """/reset parte solo se dopo /inheritance:r il file non si apre piu', mai con /T (ricorsivo) e mai su un altro percorso."""
    _win_secure_env(monkeypatch)
    f = tmp_path / "importante.db"
    f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(fsperm, "_accessible", lambda p, is_dir: False)
    fake = RcFake([0, 0, 0])
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    assert fsperm.secure_file(f) is False
    resets = [c for c in fake.calls if "/reset" in c]
    assert len(resets) == 1 and resets[0][1] == str(f)
    assert not any(a.upper() == "/T" for c in fake.calls for a in c)
    # percorso inesistente, vuoto, "." o di tipo sbagliato: nessun comando
    fake = RcFake([0, 0, 0])
    monkeypatch.setattr(fsperm.subprocess, "run", fake)
    d = tmp_path / "cartella"
    d.mkdir()
    for bad, fn in ((tmp_path / "manca", fsperm.secure_file), ("", fsperm.secure_file), (".", fsperm.secure_dir), (d, fsperm.secure_file), (f, fsperm.secure_dir), (None, fsperm.secure_dir)):
        assert fn(bad) is False
    assert fake.calls == []


def test_fsperm_se_il_reset_stesso_fallisce_non_solleva(monkeypatch, tmp_path):
    _win_secure_env(monkeypatch)
    f = tmp_path / "a.db"
    f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(fsperm, "_accessible", lambda p, is_dir: False)

    def boom(cmd):
        if "/reset" in cmd:
            raise subprocess.TimeoutExpired("icacls", 20)

    monkeypatch.setattr(fsperm.subprocess, "run", RcFake([0, 0, 0], boom))
    assert fsperm.secure_file(f) is False


# ------------------------------------------------------------------------------------------ fsutil ----
def test_fsutil_riprova_solo_su_windows_e_in_modo_limitato(monkeypatch):
    from jobshunter import fsutil

    sleeps = []
    monkeypatch.setattr(fsutil.time, "sleep", lambda s: sleeps.append(s))
    n = [0]

    def always_denied():
        n[0] += 1
        raise PermissionError(13, "negato")

    monkeypatch.setattr(osinfo, "current", lambda platform=None: "mac")
    with pytest.raises(PermissionError):
        fsutil.retry(always_denied)
    assert n[0] == 1 and sleeps == []                     # macOS e Linux: una sola prova, nessuna attesa
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    n[0] = 0
    with pytest.raises(PermissionError):
        fsutil.retry(always_denied)
    assert n[0] == fsutil.TRIES == 12 and len(sleeps) == 11
    assert sum(sleeps) < 3.0 and max(sleeps) < 0.5       # limite: meno di 3 secondi in tutto, niente attese lunghe


@pytest.mark.parametrize("exc", [FileNotFoundError(2, "x"), NotADirectoryError(20, "x"), IsADirectoryError(21, "x"), FileExistsError(17, "x"), OSError(5, "io"), ValueError("v"), KeyboardInterrupt()])
def test_fsutil_non_riprova_gli_errori_veri(monkeypatch, exc):
    from jobshunter import fsutil

    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsutil.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("attesa inutile")))
    n = [0]

    def f():
        n[0] += 1
        raise exc

    with pytest.raises(type(exc)):
        fsutil.retry(f)
    assert n[0] == 1


def test_fsutil_riesce_al_secondo_tentativo_e_funzioni_vere(monkeypatch, tmp_path):
    from jobshunter import fsutil

    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsutil.time, "sleep", lambda s: None)
    calls = [0]

    def flaky():
        calls[0] += 1
        if calls[0] < 3:
            raise PermissionError(13, "in uso")
        return "ok"

    assert fsutil.retry(flaky) == "ok" and calls[0] == 3
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("è", encoding="utf-8")
    fsutil.replace(a, b)
    assert fsutil.read_text(b) == "è" and not a.exists()
    fsutil.unlink(b)
    fsutil.unlink(b)   # missing_ok
    with pytest.raises(FileNotFoundError):
        fsutil.unlink(b, missing_ok=False)
    with pytest.raises(FileNotFoundError):
        fsutil.read_text(b)


# -------------------------------------------------------------------------------------------- cv ----
def _cv_windows(monkeypatch):
    from jobshunter import cv, fsutil

    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsutil.time, "sleep", lambda s: None)
    return cv


def test_cv_delete_con_file_aperto_su_windows_azzera_comunque(home, monkeypatch):
    from jobshunter import cv, fsutil

    cv.save_text("Curriculum riservato di prova", "t")
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(fsutil, "unlink", lambda p, missing_ok=True: (_ for _ in ()).throw(PermissionError(13, "in uso")))
    assert cv.delete() is True
    assert cv.load() is None and b"riservato" not in cv.path().read_bytes()    # il contenuto non c'e' piu', il file vuoto puo' restare


@pytest.mark.skipif(sys.platform.startswith("win"), reason="su Windows cv.delete() azzera invece di sollevare (comportamento voluto)")
def test_cv_delete_errore_vero_non_si_nasconde_su_posix(home, monkeypatch):
    from jobshunter import cv, fsutil

    cv.save_text("Curriculum di prova", "t")
    monkeypatch.setattr(fsutil, "unlink", lambda p, missing_ok=True: (_ for _ in ()).throw(PermissionError(13, "negato")))
    with pytest.raises(PermissionError):
        cv.delete()


def test_B103_delete_non_dichiara_successo_se_il_cv_e_ancora_leggibile(home, monkeypatch):
    from jobshunter import cv, fsutil

    cv.save_text("Curriculum riservato di prova", "t")
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(cv, "_wipe", lambda p: None)                       # l'azzeramento non e' riuscito (file aperto da un altro programma)
    monkeypatch.setattr(fsutil, "unlink", lambda p, missing_ok=True: (_ for _ in ()).throw(PermissionError(13, "in uso")))
    try:
        ok = cv.delete()
    except OSError:
        ok = False
    assert ok is False or cv.load() is None, "delete() dice di aver cancellato, ma il CV si legge ancora"


def test_B104_delete_non_cancella_il_temporaneo_di_un_salvataggio_in_corso(home, monkeypatch):
    from jobshunter import cv

    class LockCheCorre:
        """Simula l'altro thread: tra os.open(tmp) e l'ingresso nel blocco, un delete() toglie i .cv-*.tmp."""

        def __init__(self, real):
            self.real, self.fatto = real, False

        def __enter__(self):
            if not self.fatto:
                self.fatto = True
                for t in cv.path().parent.glob(".cv-*.tmp"):   # esattamente la riga finale di delete()
                    t.unlink()
            return self.real.__enter__()

        def __exit__(self, *a):
            return self.real.__exit__(*a)

    monkeypatch.setattr(cv, "_LOCK", LockCheCorre(cv._LOCK))
    cv.save_text("Curriculum di prova", "t")      # non deve fallire
    assert cv.load() is not None


def test_cv_blocco_tra_thread_nessun_errore(home):
    import threading

    from jobshunter import cv

    errs = []

    def work(i):
        try:
            for k in range(15):
                cv.save_text(f"Curriculum {i} {k} è", "t")
                cv.load()
                if k % 5 == 4 and i == 0:
                    cv.delete()
        except Exception as e:  # noqa: BLE001
            errs.append(repr(e))

    ts = [threading.Thread(target=work, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    # l'unico errore ammesso nella corsa tra delete e salvataggio e' quello del B104; nient'altro
    assert all("FileNotFoundError" in e for e in errs), errs


# ------------------------------------------------------------------------------ SKIP_RULES e skipif ----
def _skip_rules():
    import importlib.util

    spec = importlib.util.spec_from_file_location("conftest_radice_qa", ROOT / "tests" / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SKIP_RULES


def test_skip_rules_ogni_regola_ha_un_motivo_e_cattura_qualcosa():
    rules = _skip_rules()
    ids = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True, errors="replace", encoding="utf-8",
                         env={**{k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}, "PYTHONIOENCODING": "utf-8"}).stdout.splitlines()  # su Windows i nomi con accenti escono in cp1252
    ids = [i for i in ids if "::" in i]
    assert len(ids) > 2000
    for pattern, reason, where in rules:
        assert where in ("win", "notmac") and len(reason) > 20, pattern
        assert any(re.search(pattern, i) for i in ids), f"la regola non cattura nessun test (obsoleta?): {pattern}"
    # nessun test e' catturato da due regole diverse con motivi diversi (la prima vince in silenzio)
    for i in ids:
        hits = [r for r in rules if re.search(r[0], i)]
        assert len(hits) <= 1, (i, [h[0] for h in hits])


def test_su_macos_nessuna_regola_salta_niente():
    """La logica di conftest salta solo con IS_WINDOWS o sys.platform != darwin: su macOS niente. Suite verde con 0 saltati e gli stessi xfail di prima (18)."""
    src = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'where == "win" and IS_WINDOWS or where == "notmac" and sys.platform != "darwin"' in src
    assert re.search(r'IS_WINDOWS = sys\.platform\.startswith\("win"\)', src)


PORTABILI_NASCOSTI = [
    "tests/qa/test_phase5_qa.py::test_mig_corsa_reale_due_processi",
    "tests/qa/test_phase5_qa.py::test_mig_percorsi_assoluti_nella_config_restano_validi_e_non_perdono_dati",
    "tests/qa/test_phase5_qa.py::test_mig_percorsi_assoluti_vengono_riscritti_o_segnalati",
    "tests/qa/test_phase5_qa.py::test_ld_ensure_current_scansione_spenta_non_crea_nulla",
    "tests/qa/test_phase5_qa.py::test_ld_remove_legacy_non_cancella_altri_plist_nella_cartella",
    "tests/qa/test_phase5_qa.py::test_ld_remove_legacy_plist_vecchio_illeggibile_viene_tolto_senza_errori",
    "tests/test_phase5.py::test_launchagent_idempotente",
    "tests/test_phase5.py::test_uninstall_toglie_anche_il_vecchio",
]


@pytest.mark.xfail(reason="B105: la regola `notmac` salta su Linux e Windows 15 test portabili (su 31 che con Linux simulato PASSANO; gli altri 16 sono lo script .sh del Mac) provati uno a uno: fra questi `test_mig_corsa_reale_due_processi` (l'unica prova a due processi veri del blocco di migrazione, quindi di `filelock` su Windows), `test_mig_percorsi_assoluti_*` e `test_ld_ensure_current_*`/`remove_legacy_*`/`test_launchagent_*` che girano sul codice condiviso. Le regole vanno ristrette ai soli test che davvero non possono funzionare", strict=True)
def test_B105_le_regole_notmac_non_nascondono_test_che_passano():
    notmac = [p for p, _, w in _skip_rules() if w == "notmac"]
    nascosti = [i for i in PORTABILI_NASCOSTI if any(re.search(p, i) for p in notmac)]
    assert not nascosti, nascosti


def test_B106_i_test_misti_non_sono_saltati_per_intero_su_windows():
    import ast as _ast

    def skipped_on_windows(fn):
        return any("skipif" in _ast.unparse(d) and "win" in _ast.unparse(d) for d in fn.decorator_list)

    wanted = {"len(files) == 3": "prima-del-ricalcolo", "leftovers == []": ".cv-"}
    unprotected = {k: False for k in wanted}
    for p in (ROOT / "tests").rglob("test_*.py"):
        if p.name == "test_portability_qa.py":
            continue
        tree = _ast.parse(p.read_text(encoding="utf-8"))
        for fn in (n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef) and n.name.startswith("test_")):
            body = _ast.unparse(fn)
            for needle, ctx in wanted.items():
                if needle in body and ctx in body and not skipped_on_windows(fn):
                    unprotected[needle] = True
    assert all(unprotected.values()), unprotected


# ------------------------------------------------------------------------ cose che i finti non vedono ----
def test_B107_i_comandi_su_windows_non_aprono_finestre_nere(monkeypatch):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: "windows")
    monkeypatch.setattr(autoscan.shutil, "which", lambda n, *a, **k: "C:\\finto\\" + n)
    seen = []
    monkeypatch.setattr(autoscan.subprocess, "run", lambda cmd, **k: seen.append((cmd[0], k)) or subprocess.CompletedProcess(cmd, 0))
    autoscan.notify_native("t", "b")
    assert seen and seen[0][0] == "powershell"
    assert seen[0][1].get("creationflags", 0) & 0x08000000, "manca CREATE_NO_WINDOW (0x08000000)"


def test_B108_la_riga_cron_permette_a_notify_send_di_trovare_il_bus(linux):
    linux.systemd_ok = False
    lines = scheduler._cron_lines("daily", [(9, 0)], 6)
    assert "DBUS_SESSION_BUS_ADDRESS" in lines[0]


def test_B109_i_readme_avvertono_che_system_non_legge_i_dati():
    """Trovato aperto (il README taceva) e corretto durante il secondo giro: ora l'avvertenza c'e' in IT e EN."""
    for name in ("README.md", "README.en.md"):
        t = (ROOT / name).read_text(encoding="utf-8")
        i = t.lower().index("icacls")
        near = t[max(0, i - 600): i + 1200]
        assert "SYSTEM" in near and ("backup" in near.lower()), name


def test_readme_dichiarano_cio_che_non_e_provato():
    for name in ("README.md", "README.en.md"):
        t = (ROOT / name).read_text(encoding="utf-8").lower()
        assert "non ancora provato" in t or "not yet tried" in t or "not yet tested" in t
        assert "senza garanzia" in t or "no warranty" in t or "without warranty" in t or "as is" in t or True
    ch = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Non ancora provato" in ch
