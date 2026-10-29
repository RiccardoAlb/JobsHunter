"""Fixture comuni: cartella dati temporanea, configurazione con una fonte finta, database."""
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # i test girano anche senza installare il pacchetto

from jobshunter import settings  # noqa: E402
from jobshunter.db import DB  # noqa: E402
from jobshunter.models import Job  # noqa: E402
from jobshunter.sources import REGISTRY  # noqa: E402
from jobshunter.sources.base import Source  # noqa: E402


class FakeSource(Source):
    """Fonte di prova: restituisce gli annunci messi in FakeSource.jobs, senza rete."""

    name = "fake"
    jobs: list[Job] = []

    def fetch(self) -> list[Job]:
        self.check()
        return list(FakeSource.jobs)


def make_job(title="SOC Analyst", company="Acme Security", location="Roma", n=1, desc="Triage SIEM EDR eventi di sicurezza") -> Job:
    return Job(source="fake", title=title, company=company, location=location, url=f"https://example.org/job/{n}", description=desc)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def cfg(home):
    c = settings.load_config(create_if_missing=True)
    c["sources"] = {"fake": {"enabled": True}}  # solo la fonte finta: nessuna richiesta di rete
    c.setdefault("availability", {})["auto_check_after_scan"] = 0
    REGISTRY["fake"] = FakeSource
    FakeSource.jobs = []
    yield c
    REGISTRY.pop("fake", None)


@pytest.fixture
def db(cfg):
    return DB(settings.resolve_path(cfg["general"]["db_path"]))


@pytest.fixture(autouse=True)
def _guardia_globale(tmp_path_factory, monkeypatch):
    """Per OGNI test: HOME finta (mai ~/Library/Application Support, ~/Library/LaunchAgents o dati veri), cartella dati
    temporanea, launchctl finto e User-Agent riportato al valore predefinito. Nessun test tocca la macchina vera."""
    from jobshunter import net, scheduler

    fake_home = tmp_path_factory.mktemp("fakehome")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows: Path.home() legge questa, non HOME
    monkeypatch.setenv("APPDATA", str(fake_home / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(fake_home / "AppData" / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(fake_home / ".local" / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(fake_home / ".local" / "state"))
    for var in ("HOMEDRIVE", "HOMEPATH"):
        monkeypatch.delenv(var, raising=False)
    for var in ("JOBSHUNTER_HOME", "JOBHUNTER_HOME"):
        monkeypatch.setenv(var, str(fake_home / "dati_test"))
    LAUNCHCTL_CALLS.clear()

    def fake_launchctl(*args):
        LAUNCHCTL_CALLS.append(args)
        return subprocess.CompletedProcess(["launchctl", *args], 1, "", "finto")

    monkeypatch.setattr(scheduler, "_launchctl", fake_launchctl)
    net.configure({})
    monkeypatch.setenv("PUBLISH_FORBIDDEN_WORDS", "/users/ricc" + "ardo,ricc" + "ardo.alban" + "ese,alban" + "ese14")  # percorsi ed email dell'autore: il nome nel file LICENSE e' voluto
    real_connect = socket.socket.connect

    def only_local(self, address, *a, **k):  # nessuna rete vera in nessun test
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"RETE VIETATA nei test: connessione a {address!r}")
        return real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", only_local)
    # configurazione "di prova" (con una citta' di casa e home_names): il config.example.toml vero e' neutro e si prova a parte
    monkeypatch.setattr(settings, "bundled_root", lambda: ROOT / "tests" / "data" / "fixture_root")
    assert Path.home() == fake_home
    yield
    net.configure({})
    assert not (REAL_HOME / "Library" / "LaunchAgents" / "local.jobshunter.scan.plist").exists() or REAL_PLIST_EXISTED


import subprocess  # noqa: E402

REAL_HOME = Path.home()
REAL_PLIST_EXISTED = (REAL_HOME / "Library" / "LaunchAgents" / "local.jobshunter.scan.plist").exists()
LAUNCHCTL_CALLS: list = []


# ======================================================================== Windows: test che non si applicano ====
# Alcuni test controllano cose che esistono solo su macOS/POSIX (permessi chmod, LaunchAgent, moduli `resource`/`SIGALRM`, script `sh`,
# percorsi /etc o ~/Library). Su Windows sono saltati con un MOTIVO scritto qui: mai xfail generici e mai asserzioni indebolite.
# Il comportamento di Windows ha i suoi test (tests/builder/test_portability*.py, tests/qa/test_portability_qa.py).
# Helper per i test nuovi: `@needs_posix_perms`, `@mac_only`, `@posix_only`.
IS_WINDOWS = sys.platform.startswith("win")
TIME_FACTOR = float(__import__("os").environ.get("JOBSHUNTER_TEST_TIME_FACTOR", "1") or 1)  # macchine lente: es. 4 su un PC Windows


def t(seconds: float) -> float:
    """Limite di tempo di un test di prestazioni, moltiplicato per JOBSHUNTER_TEST_TIME_FACTOR (predefinito 1: invariato)."""
    return seconds * TIME_FACTOR


needs_posix_perms = pytest.mark.skipif(IS_WINDOWS, reason="permessi POSIX (chmod/st_mode/umask): su Windows la protezione e' icacls (provata in test_portability)")
mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="specifico di macOS (LaunchAgent, ~/Library, migrazione del vecchio nome, script .sh)")
posix_only = pytest.mark.skipif(IS_WINDOWS, reason="usa strumenti POSIX (resource, SIGALRM, sh, symlink, /etc)")

_P = "permessi POSIX (chmod/st_mode/umask): su Windows la protezione e' icacls (provata in test_portability)"
_M = "specifico di macOS (LaunchAgent, ~/Library, migrazione del vecchio nome JobHunter, script .sh)"
_X = "usa strumenti solo POSIX (modulo resource, signal.SIGALRM, sh, symlink senza privilegi, percorsi /etc)"
_Z = "controlla zone di sistema POSIX/macOS (/etc, /System, ~/Library): le zone di Windows e Linux sono provate in test_portability (check_report_dir)"
# (espressione sul nodeid, motivo, dove si salta): "win" = solo su Windows, "notmac" = su qualunque sistema che non sia macOS
SKIP_RULES = [
    (r"test_cv_qa\.py::test_cancellazione_sovrascrive_il_file", "usa un descrittore aperto sul vecchio file mentre lo cancella: Windows non cancella i file aperti (cv.delete azzera comunque il contenuto)", "win"),
    (r"test_cv_qa\.py::test_pdf_flate_bomb_tempo_e_memoria_limitati", "usa il modulo `resource`, che non esiste su Windows", "win"),
    (r"test_phase5_qa\.py::test_mig_percorsi_con_caratteri_speciali_degli_uri_sqlite\[\?\]", "il carattere ? non e' ammesso nei nomi di file di Windows", "win"),
    (r"test_phase5_qa\.py::test_mig_percorsi_assoluti_", "il test scrive a mano un config.toml con percorsi tra virgolette doppie: su Windows le barre inverse non sono TOML valido", "win"),
    (r"test_phase5_qa\.py::test_ld_plist_nuovo_ha_variabile_e_percorsi_giusti", _M, "notmac"),
    (r"test_phase5_qa\.py::test_ld_remove_legacy_se_il_plist_e_un_symlink_non_tocca_il_bersaglio", "usa os.symlink, che su Windows richiede privilegi", "win"),
    (r"test_phase5_qa\.py::test_mig_corsa_reale_due_processi", "i processi figli chiamano migrate_app_data() con i percorsi predefiniti e il test confronta con quelli di macOS (~/Library): altrove la migrazione del vecchio nome non esiste (il blocco di file tra due processi veri e' provato da test_blocco_tra_due_processi)", "notmac"),
    (r"test_phase5_qa2\.py::test_remove_old_app_", "prova lo script scripts/remove_old_app.sh con le cartelle di macOS (JobHunter.app, Library)", "notmac"),
    (r"test_phase5\.py::(test_etichette_e_percorsi|test_percorsi_predefiniti_stanno_nella_home_finta|test_macapp_usa_le_cartelle_nuove|test_scan_once_migra_prima_di_creare_la_config)", _M, "notmac"),
    (r"test_onboarding\.py::test_cartella_report_zone_di_sistema\[(/etc|/usr/local|/var/log|~/Library/LaunchAgents)-False\]", _Z, "win"),
    (r"test_onboarding\.py::test_cartella_report_zone_di_sistema\[(/System/Library|/Applications/X)-False\]", _Z, "notmac"),
    (r"test_onboarding_qa\.py::test_report_dir_in_zone_di_sistema\[/etc\]", _Z, "win"),
    (r"test_onboarding_qa\.py::test_report_dir_in_zone_di_sistema\[(/System/Library|/Library/LaunchDaemons)\]", _Z, "notmac"),
    (r"test_phase5_security\.py::test_cartella_report_non_puo_essere_di_sistema", _Z, "notmac"),
    (r"test_dedupe_perf\.py::(test_5000_annunci_in_meno_di_10_secondi_con_richiamo_alto|test_crescita_non_quadratica)", "usa signal.SIGALRM, che non esiste su Windows", "win"),
    (r"test_portability_qa\.py::(test_filelock_rilascio_su_eccezione_e_senza_fd_orfani|test_jh_sh_percorsi_con_spazi_e_link|test_check_report_dir_vero_su_questo_sistema)", _X, "win"),
    (r"test_portability_qa\.py::test_fsperm_posix_non_cambia_comportamento_dei_file_dei_dati", _P, "win"),
]


def pytest_collection_modifyitems(config, items):
    import re

    for item in items:
        for pattern, reason, where in SKIP_RULES:
            if re.search(pattern, item.nodeid):
                if where == "win" and IS_WINDOWS or where == "notmac" and sys.platform != "darwin":
                    system = "Windows" if IS_WINDOWS else sys.platform
                    item.add_marker(pytest.mark.skip(reason=f"{system}: {reason}"))
                break
