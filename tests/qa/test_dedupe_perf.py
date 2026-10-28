"""Prestazioni dei duplicati: 5.000 annunci con ~10% di varianti piantate, find_duplicates in meno di 10 secondi."""
import signal
import time

import pytest

from qa import perf_gen

LIMIT_S = 10.0
ABORT_S = 25  # oltre questo tempo il test viene interrotto (l'implementazione quadratica non finirebbe mai in tempi utili)


class _Abort(Exception):
    pass


def test_generatore_deterministico_e_ben_formato():
    r1, p1 = perf_gen.generate(500)
    r2, p2 = perf_gen.generate(500)
    assert r1 == r2 and p1 == p2
    assert len(r1) == 500 and len(p1) == 50
    assert len({r["uid"] for r in r1}) == 500


@pytest.mark.slow
@pytest.mark.phase2
def test_5000_annunci_in_meno_di_10_secondi_con_richiamo_alto(tmp_path, cfg):
    def on_alarm(*_):
        raise _Abort

    old = signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(ABORT_S)
    try:
        dt, recall, total, planted = perf_gen.run_once(tmp_path / "perf.db", 5000, cfg)
    except _Abort:
        pytest.fail(f"find_duplicates su 5000 annunci non e' finita entro {ABORT_S}s (limite spec: {LIMIT_S}s)")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    assert dt < LIMIT_S, f"find_duplicates su 5000 annunci: {dt:.1f}s (limite {LIMIT_S}s)"
    assert recall >= 0.9, f"richiamo sulle {planted} coppie piantate: {recall:.3f} (minimo 0.9); coppie trovate in tutto: {total}"


@pytest.mark.slow
@pytest.mark.phase2
def test_crescita_non_quadratica(tmp_path, cfg):
    """Raddoppiando gli annunci il tempo non deve quadruplicarsi (blocking): n=1000 -> n=2000, rapporto < 3."""
    def on_alarm(*_):
        raise _Abort

    old = signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(30)
    try:
        t1, *_ = perf_gen.run_once(tmp_path / "a.db", 1000, cfg)
        t2, *_ = perf_gen.run_once(tmp_path / "b.db", 2000, cfg)
    except _Abort:
        pytest.fail("n=1000 e n=2000 non finiti entro 30s: crescita quadratica")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    assert t2 < max(3 * t1, 0.5), f"tempi {t1:.2f}s (1000) e {t2:.2f}s (2000): crescita quasi quadratica"
