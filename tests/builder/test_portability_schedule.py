"""Pianificazione su Windows (schtasks) e Linux (systemd --user, cron) con comandi FINTI: nessun comando di sistema parte davvero.

Compatibile con Python 3.11 e con macOS, Linux e Windows."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from cvguard import _cv_guardia  # noqa: F401  (autouse: home temporanea, niente rete)
from jobshunter import autoscan, onboarding, osinfo, scheduler, settings

H = {"Host": "127.0.0.1:8765"}


class FakeSystem:
    """Simula schtasks, systemctl e crontab. Registra ogni comando."""

    def __init__(self):
        self.calls = []
        self.tasks = {}          # nome -> byte dell'XML
        self.enabled = set()
        self.cron = None         # testo del crontab (None = nessun crontab)
        self.systemd_ok = True
        self.fail = set()        # es. {"schtasks /Create"}

    def __call__(self, cmd, input=None, timeout=30):
        self.calls.append(list(cmd))
        tool = Path(cmd[0]).stem
        key = f"{tool} {cmd[1] if len(cmd) > 1 else ''}"

        def done(rc=0, out="", err=""):
            return subprocess.CompletedProcess(cmd, rc, out, err)

        if key in self.fail:
            return done(1, "", "errore finto")
        if tool == "schtasks":
            name = cmd[cmd.index("/TN") + 1]
            if cmd[1] == "/Create":
                self.tasks[name] = Path(cmd[cmd.index("/XML") + 1]).read_bytes()
                return done()
            if cmd[1] == "/Query":
                return done(0 if name in self.tasks else 1)
            if cmd[1] == "/Delete":
                return done(0 if self.tasks.pop(name, None) is not None else 1)
        if tool == "systemctl":
            args = cmd[2:]
            if f"systemctl {args[0]}" in self.fail:
                return done(1, "", "errore finto")
            if args[0] == "show-environment":
                return done(0 if self.systemd_ok else 1)
            if args[0] == "is-enabled":
                return done(0 if args[1] in self.enabled else 1)
            if args[:2] == ["enable", "--now"]:
                self.enabled.add(args[2])
            if args[:2] == ["disable", "--now"]:
                self.enabled.discard(args[2])
            return done()
        if tool == "crontab":
            if cmd[1] == "-l":
                return done(0, self.cron) if self.cron is not None else done(1, "", "no crontab")
            if cmd[1] == "-":
                self.cron = input
                return done()
            if cmd[1] == "-r":
                self.cron = None
                return done()
        return done(1, "", "comando non previsto")


@pytest.fixture
def fake(monkeypatch):
    f = FakeSystem()
    monkeypatch.setattr(scheduler, "_run", f)
    return f


def as_system(monkeypatch, system, tools):
    monkeypatch.setattr(osinfo, "current", lambda platform=None: system)
    monkeypatch.setattr(scheduler.shutil, "which", lambda name, *a, **k: ("/finto/" + name) if name in tools else None)


@pytest.fixture
def windows(monkeypatch, fake):
    as_system(monkeypatch, "windows", {"schtasks"})
    return fake


@pytest.fixture
def linux_systemd(monkeypatch, fake, tmp_path):
    as_system(monkeypatch, "linux", {"systemctl", "crontab"})
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return fake


@pytest.fixture
def linux_cron(monkeypatch, fake, tmp_path):
    as_system(monkeypatch, "linux", {"crontab"})
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return fake


def xml_of(raw: bytes) -> str:
    assert raw[:2] in (b"\xff\xfe", b"\xfe\xff")  # UTF-16 con BOM, come vuole l'Utilita' di pianificazione
    return raw.decode("utf-16")


# ------------------------------------------------------------------ rilevamento ----
def test_backend_per_sistema(monkeypatch, fake):
    as_system(monkeypatch, "windows", {"schtasks"})
    assert scheduler.backend() == "schtasks" and scheduler.supported() and "Windows" in scheduler.method_label()
    as_system(monkeypatch, "windows", set())
    assert scheduler.backend() == "" and not scheduler.supported() and "schtasks" in scheduler.unsupported_reason()
    as_system(monkeypatch, "linux", {"systemctl", "crontab"})
    assert scheduler.backend() == "systemd"
    fake.systemd_ok = False  # systemd c'e' ma l'utente non ha il suo gestore (es. contenitore, SSH senza sessione)
    assert scheduler.backend() == "cron"
    as_system(monkeypatch, "linux", {"systemctl"})
    assert scheduler.backend() == ""
    as_system(monkeypatch, "linux", set())
    assert scheduler.backend() == "" and "cron" in scheduler.unsupported_reason()
    as_system(monkeypatch, "mac", set())
    assert scheduler.backend() == "launchd"


def test_run_rifiuta_comandi_non_ammessi():
    with pytest.raises(RuntimeError):
        scheduler._REAL_RUN(["rm", "-rf", "/"])
    with pytest.raises(RuntimeError):
        scheduler._REAL_RUN([])


def test_sotto_pytest_senza_finto_il_sistema_non_si_tocca(monkeypatch, tmp_path):
    as_system(monkeypatch, "linux", {"crontab"})
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    with pytest.raises(RuntimeError) as e:
        scheduler.install("daily", [(9, 0)], 6)
    assert "test" in str(e.value)
    with pytest.raises(RuntimeError):
        scheduler.uninstall()
    assert not (tmp_path / "xdg").exists()


# --------------------------------------------------------------------- Windows ----
def test_windows_installa_attivita_giornaliera_con_due_orari(windows):
    scheduler.install("daily", [(9, 0), (18, 30)], 6)
    create = [c for c in windows.calls if c[:2] == ["schtasks", "/Create"]]
    assert len(create) == 1 and create[0][2:4] == ["/TN", "JobsHunter scan"] and "/F" in create[0]
    xml = xml_of(windows.tasks["JobsHunter scan"])
    assert xml.count("<CalendarTrigger>") == 2 and "T09:00:00" in xml and "T18:30:00" in xml
    assert "InteractiveToken" in xml and "LeastPrivilege" in xml and "<StartWhenAvailable>true" in xml and "IgnoreNew" in xml
    assert "scan-auto" in xml and "--home" in xml and "jobshunter" in xml
    assert not (settings.home() / "schedule_task.xml").exists()  # il file temporaneo non resta
    state = json.loads((settings.home() / "schedule_state.json").read_text(encoding="utf-8"))
    assert state["backend"] == "schtasks" and state["times"] == [[9, 0], [18, 30]]


@pytest.mark.parametrize("hours,expect", [(1, "PT1H"), (6, "PT6H"), (12, "PT12H")])
def test_windows_ogni_n_ore(windows, hours, expect):
    scheduler.install("every", [(9, 0)], hours)
    xml = xml_of(windows.tasks["JobsHunter scan"])
    assert expect in xml and "<Duration>P1D</Duration>" in xml and xml.count("<CalendarTrigger>") == 1


def test_windows_ogni_24_ore_e_una_volta_al_giorno(windows):
    scheduler.install("every", [(9, 0)], 24)
    xml = xml_of(windows.tasks["JobsHunter scan"])
    assert "Repetition" not in xml and "T09:00:00" in xml


def test_windows_percorsi_con_spazi_e_accenti_nel_xml(windows, monkeypatch, tmp_path):
    home = tmp_path / "Dati di Résumé & Co"
    monkeypatch.setenv("JOBSHUNTER_HOME", str(home))
    scheduler.install("daily", [(9, 0)], 6)
    xml = xml_of(windows.tasks["JobsHunter scan"])
    assert "Résumé &amp; Co" in xml  # escape XML corretto
    assert "&amp;" in xml and "& Co" not in xml.replace("&amp; Co", "")


def test_windows_errore_della_utilita_e_messaggio_italiano(windows):
    windows.fail.add("schtasks /Create")
    with pytest.raises(RuntimeError) as e:
        scheduler.install("daily", [(9, 0)], 6)
    assert "Utilita' di pianificazione" in str(e.value)
    assert not (settings.home() / "schedule_task.xml").exists()
    assert not (settings.home() / "schedule_state.json").exists()


def test_windows_is_loaded_e_uninstall_senza_orfani(windows):
    assert scheduler.is_loaded() is False
    scheduler.install("daily", [(9, 0)], 6)
    assert scheduler.is_loaded() is True
    scheduler.uninstall()
    assert scheduler.is_loaded() is False and windows.tasks == {}
    assert not (settings.home() / "schedule_state.json").exists()
    scheduler.uninstall()  # una seconda volta non da' errore


def test_windows_reinstallare_sostituisce(windows):
    scheduler.install("daily", [(9, 0)], 6)
    scheduler.install("daily", [(7, 15)], 6)
    assert list(windows.tasks) == ["JobsHunter scan"] and "T07:15:00" in xml_of(windows.tasks["JobsHunter scan"])


def test_windows_usa_pythonw_se_c_e(windows, monkeypatch, tmp_path):
    fake_py = tmp_path / "Python 3" / "python.exe"
    fake_py.parent.mkdir()
    fake_py.write_text("", encoding="utf-8")
    (fake_py.parent / "pythonw.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(scheduler.sys, "executable", str(fake_py))
    cmd = scheduler._task_command()
    assert cmd[0].endswith("pythonw.exe") and "--log-file" in cmd and cmd[-2] == "--log-file"


# ----------------------------------------------------------------------- systemd ----
def test_systemd_installa_timer_e_servizio(linux_systemd, tmp_path):
    scheduler.install("daily", [(9, 0), (18, 30)], 6)
    d = tmp_path / "xdg" / "systemd" / "user"
    timer = (d / "jobshunter-scan.timer").read_text(encoding="utf-8")
    service = (d / "jobshunter-scan.service").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 09:00:00" in timer and "OnCalendar=*-*-* 18:30:00" in timer and "Persistent=true" in timer and "WantedBy=timers.target" in timer
    assert "Type=oneshot" in service and "ExecStart=" in service and "scan-auto" in service and "JOBSHUNTER_HOME=" in service
    cmds = [c[2:] for c in linux_systemd.calls if c[0] == "systemctl" and c[1] == "--user"]
    assert ["daemon-reload"] in cmds and ["enable", "--now", "jobshunter-scan.timer"] in cmds
    assert scheduler.is_loaded() is True


@pytest.mark.parametrize("hours,expect", [(1, "00/1:00:00"), (6, "00/6:00:00"), (12, "00/12:00:00"), (24, "09:00:00")])
def test_systemd_ogni_n_ore(linux_systemd, tmp_path, hours, expect):
    scheduler.install("every", [(9, 0)], hours)
    assert expect in (tmp_path / "xdg" / "systemd" / "user" / "jobshunter-scan.timer").read_text(encoding="utf-8")


def test_systemd_percorso_con_spazi_e_percento_tra_virgolette(linux_systemd, monkeypatch, tmp_path):
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "Dati 100% miei"))
    scheduler.install("daily", [(9, 0)], 6)
    service = (tmp_path / "xdg" / "systemd" / "user" / "jobshunter-scan.service").read_text(encoding="utf-8")
    assert 'Environment="JOBSHUNTER_HOME=' in service and "Dati 100%% miei" in service


def test_systemd_uninstall_pulito(linux_systemd, tmp_path):
    scheduler.install("daily", [(9, 0)], 6)
    scheduler.uninstall()
    d = tmp_path / "xdg" / "systemd" / "user"
    assert not (d / "jobshunter-scan.timer").exists() and not (d / "jobshunter-scan.service").exists()
    assert scheduler.is_loaded() is False
    assert ["systemctl", "--user", "disable", "--now", "jobshunter-scan.timer"] in linux_systemd.calls
    scheduler.uninstall()


def test_systemd_errore_e_messaggio_italiano(linux_systemd):
    linux_systemd.fail.add("systemctl enable")
    with pytest.raises(RuntimeError):
        scheduler.install("daily", [(9, 0)], 6)


# --------------------------------------------------------------------------- cron ----
def test_cron_installa_e_conserva_le_righe_dell_utente(linux_cron):
    linux_cron.cron = "# le mie cose\n0 3 * * * /usr/bin/backup\n"
    scheduler.install("daily", [(9, 0), (18, 30)], 6)
    lines = linux_cron.cron.splitlines()
    assert lines[:2] == ["# le mie cose", "0 3 * * * /usr/bin/backup"]
    mine = [x for x in lines if "# JobsHunter" in x]
    assert len(mine) == 2 and mine[0].startswith("0 9 * * * ") and mine[1].startswith("30 18 * * * ")
    assert all("scan-auto" in x and "JOBSHUNTER_HOME=" in x and ">> " in x for x in mine)
    assert scheduler.is_loaded() is True


def test_cron_reinstallare_non_duplica(linux_cron):
    scheduler.install("daily", [(9, 0)], 6)
    scheduler.install("daily", [(7, 0)], 6)
    marked = [x for x in linux_cron.cron.splitlines() if "# JobsHunter" in x]
    assert len(marked) == 1 and marked[0].startswith("0 7 * * * ")


@pytest.mark.parametrize("hours,spec", [(1, "0 */1 * * *"), (6, "0 */6 * * *"), (24, "0 9 * * *")])
def test_cron_ogni_n_ore(linux_cron, hours, spec):
    scheduler.install("every", [(9, 0)], hours)
    assert linux_cron.cron.splitlines()[0].startswith(spec + " ")


def test_cron_escape_del_percento_e_virgolette(linux_cron, monkeypatch, tmp_path):
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "Dati 100% miei"))
    scheduler.install("daily", [(9, 0)], 6)
    line = linux_cron.cron.splitlines()[0]
    assert "100\\% miei" in line and not re.search(r"(?<!\\)%", line)
    assert "'" in line  # percorso con spazi tra apici


def test_cron_uninstall_toglie_solo_le_nostre_righe(linux_cron):
    linux_cron.cron = "0 3 * * * /usr/bin/backup\n"
    scheduler.install("daily", [(9, 0)], 6)
    scheduler.uninstall()
    assert linux_cron.cron == "0 3 * * * /usr/bin/backup\n"
    assert scheduler.is_loaded() is False


def test_cron_uninstall_con_solo_le_nostre_righe_toglie_il_crontab(linux_cron):
    scheduler.install("daily", [(9, 0)], 6)
    scheduler.uninstall()
    assert linux_cron.cron is None  # nessun crontab vuoto rimasto


def test_cron_uninstall_senza_crontab_non_da_errore(linux_cron):
    scheduler.uninstall()
    assert linux_cron.cron is None


def test_cron_errore_di_salvataggio(linux_cron):
    linux_cron.fail.add("crontab -")
    with pytest.raises(RuntimeError) as e:
        scheduler.install("daily", [(9, 0)], 6)
    assert "cron" in str(e.value)


def test_linux_da_cron_a_systemd_non_lascia_due_pianificazioni(monkeypatch, fake, tmp_path):
    as_system(monkeypatch, "linux", {"crontab"})
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    scheduler.install("daily", [(9, 0)], 6)
    assert "# JobsHunter" in fake.cron
    as_system(monkeypatch, "linux", {"systemctl", "crontab"})
    scheduler.install("daily", [(9, 0)], 6)
    assert fake.cron is None and scheduler.is_loaded()
    scheduler.uninstall()
    assert not scheduler.is_loaded()


# --------------------------------------------------------- stato e ensure_current ----
def cfg_on(**over):
    s = {"enabled": True, "kind": "daily", "times": "09:00", "hours": 6, "notify": True}
    s.update(over)
    return {"schedule": s}


def test_ensure_current_riscrive_se_manca_o_cambia(windows, monkeypatch, tmp_path):
    assert scheduler.ensure_current(cfg_on()) is True and "JobsHunter scan" in windows.tasks
    assert scheduler.ensure_current(cfg_on()) is False  # tutto allineato: niente da fare
    windows.tasks.clear()
    assert scheduler.ensure_current(cfg_on()) is True   # l'attivita' e' sparita
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "altra"))
    assert scheduler.ensure_current(cfg_on()) is True   # cartella dei dati cambiata
    assert scheduler.ensure_current(cfg_on(times="07:00")) is True


def test_ensure_current_spenta_o_non_supportata_non_fa_niente(monkeypatch, fake):
    as_system(monkeypatch, "windows", {"schtasks"})
    assert scheduler.ensure_current(cfg_on(enabled=False)) is False and fake.calls == []
    as_system(monkeypatch, "windows", set())
    assert scheduler.ensure_current(cfg_on()) is False


def test_ensure_current_non_solleva_mai(monkeypatch, windows):
    windows.fail.add("schtasks /Create")
    assert scheduler.ensure_current(cfg_on()) is False


# ----------------------------------------------------------- stato, API e guida ----
def test_status_per_sistema(windows, linux_cron):
    st = scheduler.status(cfg_on())
    assert st["supported"] and st["platform"] == "linux" and st["method"] == "cron" and st["reason"] == ""


def test_status_non_supportato_ha_il_motivo(monkeypatch, fake):
    as_system(monkeypatch, "windows", set())
    st = scheduler.status(cfg_on())
    assert st["supported"] is False and "schtasks" in st["reason"] and st["method"] == ""


@pytest.fixture
def client(home):
    from jobshunter.gui.app import create_app

    return create_app(None, 8765).test_client()


def test_api_pianificazione_su_windows_finto(client, windows):
    r = client.post("/api/schedule", headers=H, json={"enabled": True, "kind": "daily", "times": "08:30", "notify": True})
    d = r.get_json()
    assert r.status_code == 200 and d["ok"] and d["method"].startswith("Utilita'") and "JobsHunter scan" in windows.tasks
    r = client.post("/api/schedule", headers=H, json={"enabled": False})
    assert r.status_code == 200 and windows.tasks == {}


def test_api_pianificazione_non_supportata_da_400_in_italiano(client, monkeypatch, fake):
    as_system(monkeypatch, "linux", set())
    r = client.post("/api/schedule", headers=H, json={"enabled": True, "kind": "daily", "times": "08:30"})
    assert r.status_code == 400 and "cron" in r.get_json()["error"]


def test_guida_sa_se_si_puo_pianificare(client, windows, monkeypatch):
    assert client.get("/api/onboarding", headers=H).get_json()["can_schedule"] is True
    as_system(monkeypatch, "windows", set())
    assert client.get("/api/onboarding", headers=H).get_json()["can_schedule"] is False


def test_guida_attiva_la_pianificazione_su_linux_finto(client, linux_cron):
    base = {"country": "it", "home": "", "radius_km": 100, "keys": {}, "report_dir": "",
            "profile": {"preset": "custom", "titles": ["cuoco"]}, "schedule": {"enabled": True, "kind": "daily", "times": "08:30", "notify": False}}
    r = client.post("/api/onboarding/complete", headers=H, json=base)
    assert r.status_code == 200 and "# JobsHunter" in linux_cron.cron


def test_guida_non_attiva_se_non_supportata_e_lo_dice(client, monkeypatch, fake):
    as_system(monkeypatch, "windows", set())
    base = {"country": "it", "home": "", "radius_km": 100, "keys": {}, "report_dir": "",
            "profile": {"preset": "custom", "titles": ["cuoco"]}, "schedule": {"enabled": True, "kind": "daily", "times": "08:30", "notify": False}}
    r = client.post("/api/onboarding/complete", headers=H, json=base)
    assert r.status_code == 200 and any("non e' disponibile" in n for n in r.get_json()["notes"])


def test_cli_schedule_status_e_off_su_windows_finto(windows):
    from click.testing import CliRunner

    from jobshunter.cli import main

    settings.load_config(create_if_missing=True)
    r = CliRunner()
    out = r.invoke(main, ["schedule", "on", "--at", "09:00"])
    assert out.exit_code == 0 and "JobsHunter scan" in windows.tasks
    assert "Utilita'" in r.invoke(main, ["schedule", "status"]).output
    assert r.invoke(main, ["schedule", "off"]).exit_code == 0 and windows.tasks == {}


def test_cli_schedule_status_non_supportato(monkeypatch, fake):
    from click.testing import CliRunner

    from jobshunter.cli import main

    settings.load_config(create_if_missing=True)
    as_system(monkeypatch, "linux", set())
    out = CliRunner().invoke(main, ["schedule", "status"])
    assert out.exit_code == 0 and "cron" in out.output


def test_cli_home_e_log_file(tmp_path, windows):
    from click.testing import CliRunner

    from jobshunter.cli import main

    out = CliRunner().invoke(main, ["--home", str(tmp_path / "x"), "schedule", "status"])
    assert out.exit_code == 0 and (tmp_path / "x" / "config.toml").exists()


# ------------------------------------------------------------------ notifiche ----
def test_notifica_windows_con_powershell_finto(monkeypatch):
    seen = {}

    def fake_run(cmd, **k):
        seen.update(cmd=cmd, env=k.get("env"))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    as_system(monkeypatch, "windows", {"powershell"})
    monkeypatch.setattr(autoscan.subprocess, "run", fake_run)
    assert autoscan.notify_native('Titolo "con" virgolette', "Corpo con 'apici' e accènti") is True
    assert seen["cmd"][0] == "powershell" and "-NoProfile" in seen["cmd"] and "-NonInteractive" in seen["cmd"]
    assert seen["env"]["JH_TITLE"] == 'Titolo "con" virgolette' and seen["env"]["JH_BODY"].startswith("Corpo")  # il testo viaggia nell'ambiente, non nel comando
    assert "virgolette" not in " ".join(seen["cmd"])
    assert "ToastNotificationManager" in " ".join(seen["cmd"])


def test_notifica_windows_senza_powershell_o_con_errore(monkeypatch):
    as_system(monkeypatch, "windows", set())
    assert autoscan.notify_native("t", "b") is False
    as_system(monkeypatch, "windows", {"powershell"})
    monkeypatch.setattr(autoscan.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, b"", b"err"))
    assert autoscan.notify_native("t", "b") is False

    def boom(*a, **k):
        raise FileNotFoundError("powershell")

    monkeypatch.setattr(autoscan.subprocess, "run", boom)
    assert autoscan.notify_native("t", "b") is False


def test_notifica_linux_notify_send_se_presente(monkeypatch):
    calls = []
    as_system(monkeypatch, "linux", {"notify-send"})
    monkeypatch.setattr(autoscan.subprocess, "run", lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, b"", b""))
    assert autoscan.notify_native("-t strano", "corpo") is True
    assert calls[0][:3] == ["notify-send", "--app-name", "JobsHunter"] and "--" in calls[0]  # "--": un titolo che inizia con "-" non e' un'opzione
    as_system(monkeypatch, "linux", set())
    assert autoscan.notify_native("t", "b") is False


def test_notifica_sotto_pytest_non_parte_davvero_fuori_da_macos(monkeypatch):
    as_system(monkeypatch, "linux", {"notify-send"})
    assert autoscan.notify_native("t", "b") is False


def test_notifica_macos_invariata(monkeypatch):
    calls = []
    as_system(monkeypatch, "mac", set())
    monkeypatch.setattr(autoscan.subprocess, "run", lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    assert autoscan.notify_native('a "b"', "c") is True and calls[0][:2] == ["osascript", "-e"]


# ---------------------------------------------------- correzioni dopo il collaudo ----
def test_cron_lettura_fallita_non_riscrive_il_crontab(linux_cron):
    linux_cron.cron = "0 3 * * * /usr/bin/backup\n"
    real = linux_cron.__call__

    def broken(cmd, input=None, timeout=30):
        if cmd[:2] == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 1, "", "crontab: permission denied")
        return real(cmd, input, timeout)

    scheduler._run = broken
    try:
        with pytest.raises(RuntimeError) as e:
            scheduler.install("daily", [(9, 0)], 6)
        assert "crontab" in str(e.value)
    finally:
        scheduler._run = real
    assert linux_cron.cron == "0 3 * * * /usr/bin/backup\n"


def test_cron_solo_nessun_crontab_vale_come_vuoto(linux_cron):
    linux_cron.cron = None
    scheduler.install("daily", [(9, 0)], 6)
    assert "# JobsHunter" in linux_cron.cron


def test_cron_riconosce_solo_le_proprie_righe(linux_cron):
    mine = "0 4 * * * /usr/bin/rsync -a ~/jobs /backup # JobsHunter backup mio"
    other = "0 5 * * * x # JobsHunterX"
    linux_cron.cron = f"{mine}\n{other}\n"
    scheduler.install("daily", [(9, 0)], 6)
    scheduler.uninstall()
    assert linux_cron.cron == f"{mine}\n{other}\n"


def test_systemd_dollaro_raddoppiato_solo_in_exec_start(linux_systemd, monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler.sys, "executable", "/home/utente/$HOME/bin/python3")
    service, _ = scheduler._systemd_files("daily", [(9, 0)], 6)
    exec_line = [l for l in service.splitlines() if l.startswith("ExecStart=")][0]
    assert "$$HOME" in exec_line and "$HOME" not in exec_line.replace("$$HOME", "")


def test_run_decodifica_con_sostituzione(monkeypatch):
    seen = {}

    def fake(cmd, **k):
        seen.update(k)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(scheduler.subprocess, "run", fake)
    scheduler._REAL_RUN(["schtasks", "/Query"])
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"


def test_notifica_con_nul_non_solleva(monkeypatch):
    seen = {}
    as_system(monkeypatch, "windows", {"powershell"})
    monkeypatch.setattr(autoscan.subprocess, "run", lambda cmd, **k: seen.update(env=k["env"]) or subprocess.CompletedProcess(cmd, 0, b"", b""))
    assert autoscan.notify_native("Tito\x00lo", "Cor\x00po") is True
    assert "\x00" not in seen["env"]["JH_TITLE"] and "\x00" not in seen["env"]["JH_BODY"]


def test_cli_schedule_on_non_supportato_non_salva_niente(monkeypatch, home):
    from click.testing import CliRunner

    from jobshunter.cli import main

    settings.load_config(create_if_missing=True)
    as_system(monkeypatch, "linux", set())
    r = CliRunner().invoke(main, ["schedule", "on"])
    assert r.exit_code == 1 and "cron" in r.output and not isinstance(r.exception, RuntimeError)
    ov = settings.load_overrides(settings.default_config_path())
    assert ov.get("schedule.enabled") is not True


def test_cli_schedule_on_che_fallisce_riporta_enabled_false(windows, monkeypatch, home):
    from click.testing import CliRunner

    from jobshunter.cli import main

    settings.load_config(create_if_missing=True)
    windows.fail.add("schtasks /Create")
    r = CliRunner().invoke(main, ["schedule", "on"])
    assert r.exit_code == 1 and "Non sono riuscito" in r.output
    assert settings.load_overrides(settings.default_config_path()).get("schedule.enabled") is False
