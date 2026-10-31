"""Apertura dei link esterni dall'app (B124): comando del sistema per macOS, Windows e Linux, ripiego su webbrowser, solo http/https.
Nessun browser e nessun comando veri: subprocess, os.startfile e webbrowser sono finti."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from jobshunter import macapp, osinfo

ROOT = Path(__file__).resolve().parent.parent.parent
URL = "https://example.org/annuncio?id=1&q=a b;c|d$(x)`y`&n=è#frag"


class FakeProc:
    def __init__(self, rc=0, hang=False):
        self.rc, self.hang, self.returncode = rc, hang, rc

    def wait(self, timeout=None):
        if self.hang:
            raise subprocess.TimeoutExpired("cmd", timeout)
        return self.rc


@pytest.fixture
def rec(monkeypatch):
    """Registra le chiamate a Popen, a os.startfile e a webbrowser.open; per sistema: rec.system = 'mac' | 'windows' | 'linux'."""
    class R:
        popen: list = []
        startfile: list = []
        web: list = []
        proc = FakeProc()
        web_result = True
        popen_error = None

    r = R()
    r.popen, r.startfile, r.web = [], [], []

    def fake_popen(cmd, **kw):
        r.popen.append((cmd, kw))
        if r.popen_error:
            raise r.popen_error
        return r.proc

    monkeypatch.setattr(macapp.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(macapp.os, "startfile", lambda u: r.startfile.append(u), raising=False)
    monkeypatch.setattr(macapp.webbrowser, "open", lambda u, *a, **k: r.web.append(u) or r.web_result)

    def system(name):
        monkeypatch.setattr(osinfo, "current", lambda platform=None: name)

    r.system = system
    return r


def test_macos_usa_open_con_l_indirizzo_come_argomento(rec):
    rec.system("mac")
    assert macapp.open_url(URL) is True
    (cmd, kw), = rec.popen
    assert cmd == ["open", URL] and isinstance(cmd, list)  # niente shell: spazi e caratteri speciali restano un solo argomento
    assert kw.get("shell") is None and kw["start_new_session"] is True and kw["stdin"] == subprocess.DEVNULL
    assert rec.web == [] and rec.startfile == []  # webbrowser non si tocca se il comando funziona


def test_linux_usa_xdg_open(rec):
    rec.system("linux")
    assert macapp.open_url(URL) is True
    assert rec.popen[0][0] == ["xdg-open", URL] and rec.web == []


def test_windows_usa_startfile(rec):
    rec.system("windows")
    assert macapp.open_url(URL) is True
    assert rec.startfile == [URL] and rec.popen == [] and rec.web == []


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "javascript:alert(1)", "ftp://x", "data:text/html,x", "", None, 5, "HTTP://x.org", "//x.org", "x.org", "-a Safari", " https://x.org", "open -a Terminal"])
@pytest.mark.parametrize("system", ["mac", "windows", "linux"])
def test_schemi_non_http_rifiutati_senza_toccare_nulla(rec, system, bad):
    rec.system(system)
    assert macapp.open_url(bad) is False
    assert rec.popen == [] and rec.startfile == [] and rec.web == []


@pytest.mark.parametrize("system", ["mac", "linux"])
def test_ripiego_su_webbrowser_se_il_comando_manca(rec, system):
    rec.system(system)
    rec.popen_error = FileNotFoundError("open")
    assert macapp.open_url(URL) is True
    assert rec.web == [URL]


@pytest.mark.parametrize("system", ["mac", "linux"])
def test_ripiego_su_webbrowser_se_il_comando_risponde_con_errore(rec, system):
    rec.system(system)
    rec.proc = FakeProc(rc=1)
    assert macapp.open_url(URL) is True
    assert rec.web == [URL]


def test_comando_che_resta_in_attesa_si_considera_riuscito(rec):
    rec.system("linux")
    rec.proc = FakeProc(hang=True)
    assert macapp.open_url(URL) is True and rec.web == []


def test_windows_senza_startfile_ripiega(rec, monkeypatch):
    rec.system("windows")
    monkeypatch.setattr(macapp.os, "startfile", lambda u: (_ for _ in ()).throw(OSError("niente")), raising=False)
    assert macapp.open_url(URL) is True and rec.web == [URL]


def test_tutto_fallito_avvisa_nel_registro_e_ritorna_false(rec, caplog):
    rec.system("mac")
    rec.popen_error = PermissionError("negato")
    rec.web_result = False
    with caplog.at_level(logging.WARNING):
        assert macapp.open_url(URL) is False
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "nessun metodo ha funzionato" in msgs and "PermissionError" in msgs
    import webbrowser

    rec.web_result = True
    rec.popen_error = None
    assert macapp.open_url(URL) is True


def test_webbrowser_che_solleva_non_propaga(rec, monkeypatch):
    import webbrowser

    rec.system("linux")
    rec.popen_error = FileNotFoundError("xdg-open")
    monkeypatch.setattr(macapp.webbrowser, "open", lambda u, *a, **k: (_ for _ in ()).throw(webbrowser.Error("nessun browser")))
    assert macapp.open_url(URL) is False


def test_bridge_open_external_usa_open_url(monkeypatch):
    seen = []
    monkeypatch.setattr(macapp, "open_url", lambda u: seen.append(u) or True)
    assert macapp.Bridge().open_external("https://example.org/x") is True and seen == ["https://example.org/x"]
    monkeypatch.undo()
    assert macapp.Bridge().open_external("javascript:alert(1)") is False


def test_pagina_ogni_link_esterno_passa_dal_ponte_e_se_fallisce_lo_dice():
    html = (ROOT / "jobshunter" / "gui" / "static" / "index.html").read_text(encoding="utf-8")
    i = html.index('document.addEventListener("click", (e) => {\n  const a = e.target.closest')
    block = html[i:i + 700]
    assert 'a[target=_blank]' in block and "native().open_external(href)" in block and "Non riesco ad aprire il browser" in block
    assert block.count("Non riesco ad aprire il browser") == 2  # sia se risponde false sia se la chiamata fallisce
    # tutti i link che aprono una nuova scheda sono a[target=_blank]: li prende questo gestore, in fase di cattura
    assert "}, true);" in block
    assert "—" not in block
