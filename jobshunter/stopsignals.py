"""Arresto ordinato su SIGINT/SIGTERM (e SIGBREAK su Windows), anche se SIGINT era IGNORATO all'avvio.

Un processo lanciato da un servizio, da una CI o da `nohup` puo' ereditare SIGINT ignorato: in quel caso Python non installa il suo
handler e Ctrl+C / `kill -INT` non fermano mai l'attesa. Qui gli handler sono installati in modo esplicito (solo nel thread
principale, dove `signal.signal` e' permesso) e portano a un evento: chi aspetta esce con codice 0.
"""
from __future__ import annotations

import signal
import threading
from collections.abc import Callable

STOP = threading.Event()


def install(on_stop: Callable[[], None] | None = None) -> threading.Event:
    """Installa gli handler e ritorna l'evento che si accende alla richiesta di arresto. Mai eccezioni (thread secondario: non fa nulla)."""
    STOP.clear()

    def handler(signum, frame):  # noqa: ARG001
        STOP.set()
        if on_stop is not None:
            try:
                on_stop()
            except Exception:  # noqa: BLE001
                pass

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):  # non e' il thread principale, o segnale non gestibile su questo sistema
            pass
    return STOP


def wait(event: threading.Event | None = None) -> None:
    """Attesa interrompibile (mai una chiamata bloccante senza timeout: i segnali devono poter arrivare)."""
    ev = event or STOP
    while not ev.wait(0.5):
        pass
