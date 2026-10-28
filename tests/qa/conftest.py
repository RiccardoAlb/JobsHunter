"""Configurazione dei test del TESTER: marker, isolamento dai dati veri, nessuna rete esterna.

Le regole di sicurezza della fase 2 (spec punto 0) sono applicate qui a tutti i test di tests/qa:
- JOBSHUNTER_HOME punta sempre a una cartella temporanea;
- ogni connessione di rete diversa da 127.0.0.1 / ::1 fallisce subito (nessuna richiesta ad Adzuna, Jooble, ...);
- nessun LaunchAgent reale viene toccato.
"""
import socket

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: test lenti (prestazioni, 5.000 annunci); escludili con -m 'not slow'")
    config.addinivalue_line("markers", "phase2: scritto contro la SPEC della fase 2, fallisce finche' BUILDER non consegna")


@pytest.fixture(autouse=True)
def _qa_sicurezza(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "jh_home"))
    (tmp_path / "jh_home").mkdir()
    real_connect = socket.socket.connect

    def only_local(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address, *a, **k)
        if not isinstance(address, tuple):  # socket unix
            return real_connect(self, address, *a, **k)
        raise AssertionError(f"RETE VIETATA nei test: connessione a {address!r}")

    monkeypatch.setattr(socket.socket, "connect", only_local)
    monkeypatch.setattr(socket, "getaddrinfo", _guard_dns(socket.getaddrinfo))
    try:
        from jobshunter import scheduler

        monkeypatch.setattr(scheduler, "install", lambda *a, **k: None)
        monkeypatch.setattr(scheduler, "uninstall", lambda *a, **k: None)
        monkeypatch.setattr(scheduler, "is_loaded", lambda: False)
    except Exception:
        pass
    yield


def _guard_dns(real):
    def guard(host, *a, **k):
        if host not in (None, "127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"RETE VIETATA nei test: DNS per {host!r}")
        return real(host, *a, **k)

    return guard


# ---------------------------------------------------------------- fixture comuni per i test della fase 2 ----
import re



from qa.qa_helpers import edit_config  # noqa: E402


@pytest.fixture
def qcfg(cfg, home):
    """Configurazione con SOLO la fonte finta attiva (nessuna fonte vera, nemmeno spenta per sbaglio), riletta da config.toml."""
    from jobshunter import settings

    def f(text):
        text = re.sub(r"enabled\s*=\s*true", "enabled = false", text)
        text = re.sub(r"auto_check_after_scan\s*=\s*\d+", "auto_check_after_scan = 0", text)
        return text + "\n[sources.fake]\nenabled = true\n"

    edit_config(home, f)
    c = settings.load_config()
    return c


@pytest.fixture
def client(qcfg, home):
    from jobshunter.gui.app import create_app

    return create_app(None, 8765).test_client()


@pytest.fixture
def qdb(qcfg):
    from jobshunter import settings
    from jobshunter.db import DB

    return DB(settings.resolve_path(qcfg["general"]["db_path"]))


@pytest.fixture
def fake_jobs():
    """Imposta gli annunci restituiti dalla fonte finta: fake_jobs([Job, ...])."""
    from jobshunter.sources import REGISTRY

    def setter(jobs):
        REGISTRY["fake"].jobs = list(jobs)

    return setter
