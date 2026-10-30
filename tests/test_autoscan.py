"""Scansione automatica: blocco, cronologia, notifiche, novita'."""
from jobshunter import autoscan
from jobshunter.autoscan import ScanLock, run_auto
from conftest import FakeSource, make_job


def test_registra_la_scansione_e_notifica(cfg, db, monkeypatch):
    sent = []
    monkeypatch.setattr(autoscan, "notify_native", lambda title, body: sent.append((title, body)) or True)
    FakeSource.jobs = [make_job(n=1), make_job("Junior SOC Analyst", "Beta Srl", n=2)]
    res, info = run_auto(cfg, db, kind="auto")
    assert res.new == 2 and not info["skipped"] and info["notified"]
    run = db.recent_scans(1)[0]
    assert (run["kind"], run["new"], run["notified"]) == ("auto", 2, 1)
    title, body = sent[0]
    assert "2 nuovi annunci" in title and "SOC Analyst" in body


def test_senza_novita_nessuna_notifica(cfg, db, monkeypatch):
    sent = []
    monkeypatch.setattr(autoscan, "notify_native", lambda *a: sent.append(a) or True)
    FakeSource.jobs = [make_job()]
    run_auto(cfg, db)
    assert len(sent) == 1
    run_auto(cfg, db)  # stessi annunci: nulla di nuovo
    assert len(sent) == 1 and db.recent_scans(1)[0]["new"] == 0


def test_scansione_manuale_non_notifica(cfg, db, monkeypatch):
    sent = []
    monkeypatch.setattr(autoscan, "notify_native", lambda *a: sent.append(a) or True)
    FakeSource.jobs = [make_job()]
    run_auto(cfg, db, kind="manuale", notify=False)
    assert not sent and db.recent_scans(1)[0]["kind"] == "manuale"


def test_notifiche_disattivabili(cfg, db, monkeypatch):
    sent = []
    monkeypatch.setattr(autoscan, "notify_native", lambda *a: sent.append(a) or True)
    cfg["schedule"] = {"notify": False}
    FakeSource.jobs = [make_job()]
    run_auto(cfg, db)
    assert not sent


def test_il_blocco_impedisce_due_scansioni_insieme(cfg, db):
    FakeSource.jobs = [make_job()]
    lock = ScanLock()
    assert lock.acquire()
    try:
        res, info = run_auto(cfg, db)
        assert res is None and info["skipped"] and "in corso" in info["message"]
        assert db.recent_scans(1) == []  # niente scansione, niente riga in cronologia
    finally:
        lock.release()
    res, info = run_auto(cfg, db)
    assert res is not None and res.new == 1


def test_novita_dall_ultimo_accesso(cfg, db):
    from datetime import datetime, timezone

    from datetime import timedelta

    before = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()  # Windows: l'orologio ha ~15 ms di risoluzione, senza margine il primo annuncio puo' avere lo stesso istante
    FakeSource.jobs = [make_job(n=1), make_job("Pentester", "Beta", n=2)]
    run_auto(cfg, db, notify=False)
    assert db.news_since(before)["new"] == 2
    db.kv_set("last_ack", datetime.now(timezone.utc).isoformat())
    assert db.news_since(db.kv_get("last_ack")) == {"new": 0, "closed": 0, "dups": 0}


def test_messaggio_con_i_migliori_per_primi(cfg, db, monkeypatch):
    sent = []
    monkeypatch.setattr(autoscan, "notify_native", lambda t, b: sent.append((t, b)) or True)
    FakeSource.jobs = [make_job("Sistemista", "Gamma", n=1), make_job("Junior SOC Analyst", "Beta", n=2)]
    run_auto(cfg, db)
    assert sent[0][1].startswith("Junior SOC Analyst")  # punteggio piu' alto per primo
