"""CSP della pagina (B124, causa vera): stretta nel browser, con 'unsafe-eval' SOLO dentro la finestra nativa (pywebview crea il ponte con new Function)."""
from __future__ import annotations

import os
import re
import sys
import types

import pytest

from jobshunter import macapp
from jobshunter.gui import app as guiapp

H = {"Host": "127.0.0.1:8765"}
STRICT = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
          "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


@pytest.fixture
def client(home, monkeypatch):
    monkeypatch.delenv("JOBSHUNTER_NATIVE_WINDOW", raising=False)
    return guiapp.create_app(None, 8765).test_client()


def directives(csp: str) -> dict:
    return {d.split()[0]: d.split()[1:] for d in csp.split("; ") if d}


ROUTES = ["/", "/api/stats", "/api/jobs", "/api/settings", "/assets/favicon-32.png", "/favicon.ico", "/api/non-esiste", "/api/job/nonesiste"]


@pytest.mark.parametrize("path", ROUTES)
def test_csp_stretta_di_default_su_tutte_le_rotte_anche_errori_e_assets(client, path):
    r = client.get(path, headers=H)
    assert r.headers["Content-Security-Policy"] == STRICT
    assert "unsafe-eval" not in r.headers["Content-Security-Policy"]


def test_csp_stretta_anche_su_403_e_405(client):
    assert client.get("/", headers={"Host": "evil.example"}).headers["Content-Security-Policy"] == STRICT
    r = client.get("/api/onboarding/complete", headers=H)  # solo POST
    assert r.status_code == 405 and r.headers["Content-Security-Policy"] == STRICT


def test_csp_costante_invariata():
    assert guiapp.CSP == STRICT


def test_csp_nativa_e_la_stretta_piu_solo_unsafe_eval(client, monkeypatch):
    monkeypatch.setenv("JOBSHUNTER_NATIVE_WINDOW", "1")
    for path in ROUTES:
        csp = client.get(path, headers=H).headers["Content-Security-Policy"]
        assert csp == guiapp.CSP_NATIVE
    strict, native = directives(STRICT), directives(guiapp.CSP_NATIVE)
    assert native.pop("script-src") == ["'self'", "'unsafe-inline'", "'unsafe-eval'"]
    assert strict.pop("script-src") == ["'self'", "'unsafe-inline'"]
    assert native == strict  # nessun altro valore cambiato
    assert "*" not in guiapp.CSP_NATIVE and "http" not in guiapp.CSP_NATIVE and guiapp.CSP_NATIVE.count("unsafe-eval") == 1
    assert guiapp.CSP_NATIVE == STRICT.replace("'unsafe-inline'; style-src", "'unsafe-inline' 'unsafe-eval'; style-src", 1)


@pytest.mark.parametrize("value", ["0", "", "true", "yes", "2", " 1"])
def test_solo_il_valore_uno_attiva_la_csp_nativa(client, monkeypatch, value):
    monkeypatch.setenv("JOBSHUNTER_NATIVE_WINDOW", value)
    assert client.get("/", headers=H).headers["Content-Security-Policy"] == STRICT


def test_la_variabile_si_legge_a_ogni_richiesta(client, monkeypatch):
    assert client.get("/", headers=H).headers["Content-Security-Policy"] == STRICT
    monkeypatch.setenv("JOBSHUNTER_NATIVE_WINDOW", "1")
    assert "unsafe-eval" in client.get("/", headers=H).headers["Content-Security-Policy"]
    monkeypatch.delenv("JOBSHUNTER_NATIVE_WINDOW")
    assert client.get("/", headers=H).headers["Content-Security-Policy"] == STRICT


# ------------------------------------------------------------------ macapp.main ----
def test_main_senza_pywebview_non_imposta_la_variabile(monkeypatch, home):
    import builtins

    real_import = builtins.__import__

    def no_webview(name, *a, **k):
        if name == "webview":
            raise ImportError("niente pywebview")
        return real_import(name, *a, **k)

    monkeypatch.delenv("JOBSHUNTER_NATIVE_WINDOW", raising=False)
    seen = {}
    monkeypatch.setattr(macapp, "_start_engine", lambda: 4321)
    monkeypatch.setattr(macapp, "_browser_fallback", lambda port, why: seen.update(env=os.environ.get("JOBSHUNTER_NATIVE_WINDOW")))
    monkeypatch.setattr(builtins, "__import__", no_webview)
    macapp.main()
    monkeypatch.setattr(builtins, "__import__", real_import)
    assert seen == {"env": None} and "JOBSHUNTER_NATIVE_WINDOW" not in os.environ


def fake_webview(monkeypatch, order, fail=False):
    m = types.ModuleType("webview")
    m.FOLDER_DIALOG = 20

    def create_window(*a, **k):
        order.append(("create_window", os.environ.get("JOBSHUNTER_NATIVE_WINDOW")))
        return object()

    def start(*a, **k):
        order.append(("start", os.environ.get("JOBSHUNTER_NATIVE_WINDOW")))
        if fail:
            raise RuntimeError("GTK mancante")

    m.create_window, m.start = create_window, start
    monkeypatch.setitem(sys.modules, "webview", m)


def test_main_imposta_la_variabile_dopo_l_import_e_prima_di_create_window(monkeypatch, home):
    monkeypatch.delenv("JOBSHUNTER_NATIVE_WINDOW", raising=False)
    order = []
    fake_webview(monkeypatch, order)
    monkeypatch.setattr(macapp, "_start_engine", lambda: 4321)
    monkeypatch.setattr(macapp.stopsignals, "install", lambda *a, **k: None)
    macapp.main()
    assert order == [("create_window", "1"), ("start", "1")]  # gia' attiva quando la finestra carica la pagina
    monkeypatch.delenv("JOBSHUNTER_NATIVE_WINDOW", raising=False)


def test_main_se_la_finestra_non_parte_torna_la_politica_stretta(monkeypatch, home):
    monkeypatch.delenv("JOBSHUNTER_NATIVE_WINDOW", raising=False)
    order, seen = [], {}
    fake_webview(monkeypatch, order, fail=True)
    monkeypatch.setattr(macapp, "_start_engine", lambda: 4321)
    monkeypatch.setattr(macapp.stopsignals, "install", lambda *a, **k: None)
    monkeypatch.setattr(macapp, "_browser_fallback", lambda port, why: seen.update(env=os.environ.get("JOBSHUNTER_NATIVE_WINDOW")))
    macapp.main()
    assert order[-1] == ("start", "1") and seen == {"env": None}  # nel browser di ripiego la CSP e' quella stretta


def test_la_variabile_si_imposta_solo_in_macapp():
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent.parent
    hits = [p.name for p in (root / "jobshunter").rglob("*.py") if "JOBSHUNTER_NATIVE_WINDOW" in p.read_text(encoding="utf-8")]
    assert sorted(hits) == ["app.py", "macapp.py"]
    src = (root / "jobshunter" / "macapp.py").read_text(encoding="utf-8")
    assert src.index("import webview") < src.index('os.environ["JOBSHUNTER_NATIVE_WINDOW"] = "1"') < src.index("create_window(")
