"""Guardie per i test del confronto col CV (solo i file test_cv*.py): home temporanea e nessuna rete."""
import socket

import pytest


@pytest.fixture(autouse=True)
def _cv_guardia(tmp_path, monkeypatch):
    home = tmp_path / "jh_home"
    home.mkdir()
    monkeypatch.setenv("JOBSHUNTER_HOME", str(home))

    def no_net(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(address, tuple) and host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"RETE VIETATA nei test del CV: {address!r}")
        return real(self, address, *a, **k)

    real = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", no_net)
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: (_ for _ in ()).throw(AssertionError(f"DNS vietato: {host!r}")) if host not in (None, "127.0.0.1", "::1", "localhost") else _real_gai(host, *a, **k))
    from jobshunter import settings

    assert str(settings.home()).startswith(str(tmp_path)), "la home non e' temporanea"
    yield


_real_gai = socket.getaddrinfo
