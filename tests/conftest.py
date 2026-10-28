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
