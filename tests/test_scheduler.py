"""Pianificazione: orari, contenuto del LaunchAgent, prossimo avvio."""
import plistlib
from datetime import datetime

import pytest

from jobshunter import scheduler


def test_parse_times():
    assert scheduler.parse_times("09:00, 18:30") == [(9, 0), (18, 30)]
    assert scheduler.parse_times("18:30 9:05") == [(9, 5), (18, 30)]  # ordina e accetta l'ora senza zero
    assert scheduler.parse_times("09:00, 09:00") == [(9, 0)]


@pytest.mark.parametrize("bad", ["", "9", "25:00", "09:60", "aa:bb", "09:00, 10:00, 11:00, 12:00, 13:00"])
def test_parse_times_rifiuta_formati_sbagliati(bad):
    with pytest.raises(ValueError):
        scheduler.parse_times(bad)


def test_plist_giornaliero():
    d = scheduler.build_plist("daily", [(9, 0), (18, 30)], 6)
    assert d["StartCalendarInterval"] == [{"Hour": 9, "Minute": 0}, {"Hour": 18, "Minute": 30}]
    assert "StartInterval" not in d and d["RunAtLoad"] is False
    assert d["Label"] == scheduler.LABEL and "JOBSHUNTER_HOME" in d["EnvironmentVariables"]
    plistlib.loads(plistlib.dumps(d))  # e' un plist valido


def test_plist_ogni_n_ore():
    d = scheduler.build_plist("every", [(9, 0)], 6)
    assert d["StartInterval"] == 6 * 3600 and "StartCalendarInterval" not in d


def test_prossimo_avvio():
    now = datetime(2026, 10, 28, 10, 0)
    assert scheduler.next_run("daily", [(9, 0), (18, 30)], 6, now) == datetime(2026, 10, 28, 18, 30)
    assert scheduler.next_run("daily", [(9, 0)], 6, now) == datetime(2026, 10, 29, 9, 0)  # oggi e' gia' passata
    assert scheduler.next_run("every", [(9, 0)], 6, now) is None


def test_impostazioni_di_default(cfg):
    cur = scheduler.current_settings(cfg)
    assert cur["enabled"] is False and cur["times"] == "09:00" and cur["hours"] == 6


def test_impostazioni_sporche_tornano_ai_valori_sicuri():
    cur = scheduler.current_settings({"schedule": {"enabled": True, "kind": "boh", "times": "xx", "hours": 7}})
    assert cur["kind"] == "daily" and cur["times"] == "09:00" and cur["hours"] == 6
