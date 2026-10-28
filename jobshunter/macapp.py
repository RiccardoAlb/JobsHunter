"""JobsHunter come app Mac: motore locale + finestra nativa (WKWebView tramite pywebview).

I dati stanno in ~/Library/Application Support/JobsHunter (database, configurazione, report).
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

from . import APP_NAME, migrate

APP_DIR = migrate.support_dir()
LOG_DIR = migrate.log_dir()


class Bridge:
    """Funzioni native richiamabili dalla pagina (window.pywebview.api.*)."""

    def __init__(self) -> None:
        self.window = None

    def open_external(self, url: str) -> bool:
        """Apre un link nel browser predefinito (solo http/https)."""
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            webbrowser.open(url)
            return True
        return False

    def choose_folder(self) -> str | None:
        import webview

        res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return res[0] if res else None

    def open_folder(self, kind: str) -> bool:
        """Apre in Finder la cartella dati o quella dei report."""
        from . import settings

        if kind == "data":
            path = settings.home()
        elif kind == "reports":
            cfg = settings.load_config(create_if_missing=True)
            path = settings.resolve_path(cfg.get("report", {}).get("dir", "reports"))
            path.mkdir(parents=True, exist_ok=True)
        else:
            return False
        subprocess.run(["open", str(path)], check=False)
        return True


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


def main() -> None:
    data_dir, outcome = migrate.migrate_app_data()  # copia (mai sposta) i dati del vecchio nome, senza la s
    os.environ.setdefault("JOBSHUNTER_HOME", str(data_dir))
    from . import settings

    settings.home().mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_DIR / "app.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.info("dati: %s (%s)", data_dir, outcome)

    import webview

    from .gui.app import create_app

    try:  # se la scansione automatica e' attiva, il LaunchAgent deve puntare a questa app
        from . import scheduler

        if scheduler.ensure_current(settings.load_config(create_if_missing=True)):
            logging.info("pianificazione della scansione automatica riallineata")
    except Exception:
        logging.exception("impossibile verificare la scansione automatica")

    port = _free_port()
    flask_app = create_app(None, port)
    threading.Thread(
        target=lambda: flask_app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False),
        daemon=True,
    ).start()
    if not _wait_port(port):
        logging.error("il motore locale non si e' avviato")
        raise SystemExit("JobsHunter: il motore locale non si e' avviato (vedi ~/Library/Logs/JobsHunter/app.log)")
    logging.info("motore locale su porta %s, dati in %s", port, settings.home())

    bridge = Bridge()
    bridge.window = webview.create_window(
        APP_NAME, f"http://127.0.0.1:{port}/", js_api=bridge,
        width=1320, height=860, min_size=(960, 620), background_color="#0b0b0c",
    )
    # private_mode=False: serve a ricordare tema e raggio scelti (localStorage) tra un avvio e l'altro
    webview.start(private_mode=False, storage_path=str(settings.home() / "webview"))
