"""API di novita', cronologia e pianificazione."""
import json

import pytest

from jobshunter import scheduler
from jobshunter.gui.app import create_app
from conftest import FakeSource, make_job

H = {"Host": "127.0.0.1:8765"}


@pytest.fixture
def client(cfg, home, monkeypatch):
    monkeypatch.setattr(scheduler, "install", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "uninstall", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "is_loaded", lambda: False)
    return create_app(None, 8765).test_client()


def jget(r):
    return json.loads(r.data)


def test_prima_visita_senza_novita_poi_si_azzerano(client, db, cfg):
    from jobshunter.autoscan import run_auto

    assert jget(client.get("/api/news", headers=H))["new"] == 0  # primo accesso: nessun "passato"
    FakeSource.jobs = [make_job(n=1), make_job("Pentester", "Beta", n=2)]
    run_auto(cfg, db, notify=False)
    assert jget(client.get("/api/news", headers=H))["new"] == 2
    assert client.post("/api/news/ack", headers=H).status_code == 200
    assert jget(client.get("/api/news", headers=H))["new"] == 0


def test_cronologia_scansioni(client, db, cfg):
    from jobshunter.autoscan import run_auto

    FakeSource.jobs = [make_job()]
    run_auto(cfg, db, kind="manuale", notify=False)
    scans = jget(client.get("/api/scans", headers=H))
    assert len(scans) == 1 and scans[0]["kind"] == "manuale" and scans[0]["new"] == 1


def test_attiva_e_salva_la_pianificazione(client):
    r = client.post("/api/schedule", headers=H, json={"enabled": True, "kind": "daily", "times": "08:30, 18:00", "notify": True})
    d = jget(r)
    assert r.status_code == 200 and d["ok"] and d["times"] == "08:30, 18:00" and d["enabled"]
    assert jget(client.get("/api/schedule", headers=H))["times"] == "08:30, 18:00"  # salvato davvero


@pytest.mark.parametrize("body", [{"enabled": True, "times": "99:99"}, {"enabled": True, "kind": "every", "hours": 7}, {"times": "ciao"}])
def test_pianificazione_rifiuta_valori_non_validi(client, body):
    assert client.post("/api/schedule", headers=H, json=body).status_code == 400


def test_origine_esterna_rifiutata(client):
    assert client.post("/api/schedule", headers={**H, "Origin": "http://evil.com"}, json={"enabled": True}).status_code == 403
