"""JobsHunter come app con finestra nativa: motore locale + pywebview (WKWebView su macOS, WebView2 su Windows, GTK/Qt su Linux).

I dati stanno nella cartella dell'app del sistema (vedi `osinfo`): su macOS `~/Library/Application Support/JobsHunter`.
Se pywebview manca o la finestra non si apre, si ripiega sul browser predefinito con lo stesso motore locale.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import APP_NAME, migrate, osinfo

APP_DIR = migrate.support_dir()
LOG_DIR = migrate.log_dir()


def open_path(path) -> bool:
    """Apre una cartella o un file con il programma del sistema (Finder, Esplora risorse, gestore file). True se ha provato, mai eccezioni."""
    target = str(path)
    try:
        if osinfo.is_windows():
            os.startfile(target)  # type: ignore[attr-defined]  # solo Windows
        else:
            # lanciato e lasciato andare (sessione propria): il gestore dei file puo' restare aperto quanto vuole, nessun timeout lo uccide
            cmd = ["open", target] if osinfo.is_mac() else ["xdg-open", target]
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except (OSError, subprocess.SubprocessError, AttributeError):
        return False


def open_url(url: str) -> bool:
    """Apre un indirizzo http/https nel browser predefinito."""
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        try:
            return bool(webbrowser.open(url))
        except webbrowser.Error:
            return False
    return False


class Bridge:
    """Funzioni native richiamabili dalla pagina (window.pywebview.api.*)."""

    def __init__(self) -> None:
        self.window = None

    def open_external(self, url: str) -> bool:
        """Apre un link nel browser predefinito (solo http/https)."""
        return open_url(url)

    def choose_folder(self) -> str | None:
        import webview

        res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return res[0] if res else None

    def open_folder(self, kind: str) -> bool:
        """Apre nel gestore file del sistema la cartella dati o quella dei report."""
        from . import settings

        if kind == "data":
            path = settings.home()
        elif kind == "reports":
            cfg = settings.load_config(create_if_missing=True)
            path = settings.resolve_path(cfg.get("report", {}).get("dir", "reports"))
            path.mkdir(parents=True, exist_ok=True)
        else:
            return False
        return open_path(path)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, timeout: float = 20.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _start_engine() -> int:
    """Prepara cartelle e log, avvia il motore locale in un thread e ritorna la porta."""
    data_dir, outcome = migrate.migrate_app_data()  # copia (mai sposta) i dati del vecchio nome (solo macOS)
    os.environ.setdefault("JOBSHUNTER_HOME", str(data_dir))
    from . import settings

    settings.home().mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_DIR / "app.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.info("dati: %s (%s)", data_dir, outcome)

    from .gui.app import create_app

    try:  # se la scansione automatica e' attiva, la pianificazione deve puntare a questa app
        from . import scheduler

        if scheduler.ensure_current(settings.load_config(create_if_missing=True)):
            logging.info("pianificazione della scansione automatica riallineata")
    except Exception:
        logging.exception("impossibile verificare la scansione automatica")

    port = _free_port()
    flask_app = create_app(None, port)
    failure: list[BaseException] = []

    def serve() -> None:
        try:
            flask_app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)
        except BaseException as e:  # noqa: BLE001 - un'eccezione nel thread sarebbe invisibile: la si scrive nel log
            failure.append(e)
            logging.exception("il motore locale si e' fermato con un errore")

    th = threading.Thread(target=serve, daemon=True, name="motore-locale")
    th.start()
    try:
        timeout = float(os.environ.get("JOBSHUNTER_ENGINE_TIMEOUT", "20"))
    except ValueError:
        timeout = 20.0
    if not _wait_port(port, timeout):
        logging.error("il motore locale non si e' avviato (porta %s, attesa %.0f s, thread %s, errore: %s)", port, timeout,
                      "vivo" if th.is_alive() else "terminato", repr(failure[0]) if failure else "nessuno")
        raise SystemExit(f"JobsHunter: il motore locale non si e' avviato (vedi {LOG_DIR / 'app.log'})")
    logging.info("motore locale su porta %s, dati in %s", port, settings.home())
    return port


def _browser_fallback(port: int, why: str) -> None:
    """Niente finestra nativa: il motore resta acceso e la pagina si apre nel browser predefinito (Ctrl+C per chiudere)."""
    logging.info("finestra nativa non disponibile (%s): uso il browser", why)
    print(f"{APP_NAME}: {why}. Apro la pagina nel browser: http://127.0.0.1:{port}/  (Ctrl+C per chiudere)", file=sys.stderr)
    open_url(f"http://127.0.0.1:{port}/")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def main() -> None:
    port = _start_engine()
    from . import settings

    try:
        import webview
    except ImportError:
        _browser_fallback(port, "manca pywebview (installalo con: pip install -r requirements-gui.txt)")
        return

    bridge = Bridge()
    try:
        bridge.window = webview.create_window(
            APP_NAME, f"http://127.0.0.1:{port}/", js_api=bridge,
            width=1320, height=860, min_size=(960, 620), background_color="#0b0b0c",
        )
        # private_mode=False: serve a ricordare tema e raggio scelti (localStorage) tra un avvio e l'altro
        webview.start(private_mode=False, storage_path=str(settings.home() / "webview"))
    except Exception as e:  # noqa: BLE001 - qualunque problema della finestra (WebView2/GTK mancanti...): si ripiega sul browser
        logging.exception("la finestra nativa non si e' aperta")
        _browser_fallback(port, f"la finestra nativa non si e' aperta ({type(e).__name__})")
