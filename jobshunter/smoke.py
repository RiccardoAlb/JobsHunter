"""Test di fumo del programma impacchettato: `JobsHunter --smoke`.

Avvia il server locale su una porta libera con una cartella dati TEMPORANEA, controlla che la pagina e le API rispondano e che
i file inclusi nel pacchetto (config di esempio, pagina, dati delle citta', PDF, crittografia) ci siano. Nessuna rete, nessuna finestra.
Esce con codice 0 se tutto va bene; stampa la versione. `--smoke-log FILE` scrive lo stesso resoconto su un file (utile su Windows,
dove l'eseguibile senza console non ha un'uscita da leggere).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path


def _get(port: int, path: str, timeout: float = 20.0) -> tuple[int, bytes]:
    from . import net

    os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")  # la richiesta resta sul computer, mai attraverso un proxy
    with net.client(timeout=timeout) as c:  # solo 127.0.0.1: tutte le richieste passano da net.py
        r = c.get(f"http://127.0.0.1:{port}{path}")
        return r.status_code, r.content


def run(log_path: str | None = None) -> int:
    from . import APP_NAME, __version__

    lines: list[str] = []

    def say(msg: str) -> None:
        lines.append(msg)
        try:
            print(msg, flush=True)
        except Exception:  # noqa: BLE001 - senza console (Windows, --windowed) stdout puo' non esserci
            pass

    ok = True

    def check(name: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        say(f"{'OK  ' if good else 'FAIL'} {name}" + (f" ({detail})" if detail else ""))

    import logging

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    tmp = Path(tempfile.mkdtemp(prefix="jobshunter-smoke-"))
    old_home = os.environ.get("JOBSHUNTER_HOME")
    os.environ["JOBSHUNTER_HOME"] = str(tmp)
    say(f"{APP_NAME} {__version__} (test di fumo)")
    try:
        from . import settings

        check("config di esempio nel pacchetto", (settings.bundled_root() / "config.example.toml").is_file())
        check("pagina nel pacchetto", (Path(__file__).resolve().parent / "gui" / "static" / "index.html").is_file())
        try:
            from . import geo

            hit = geo.lookup("Roma")
            check("dati delle citta'", bool(hit), "Roma")
        except Exception as e:  # noqa: BLE001
            check("dati delle citta'", False, type(e).__name__)
        for mod in ("pypdf", "cryptography"):
            try:
                __import__(mod)
                check(f"modulo {mod}", True)
            except Exception as e:  # noqa: BLE001
                check(f"modulo {mod}", False, type(e).__name__)

        from werkzeug.serving import make_server

        from .gui.app import create_app

        from .macapp import _free_port

        port = _free_port()
        app = create_app(None, port)
        server = make_server("127.0.0.1", port, app, threaded=True)
        th = threading.Thread(target=server.serve_forever, daemon=True)
        th.start()
        try:
            st, body = _get(port, "/")
            check("pagina principale", st == 200 and b"<html" in body.lower())
            st, body = _get(port, "/api/stats")
            check("API /api/stats", st == 200 and "by_cat" in json.loads(body))
            st, body = _get(port, "/api/jobs")
            check("API /api/jobs", st == 200 and isinstance(json.loads(body), list))
            st, body = _get(port, "/api/settings")
            check("versione nell'app", st == 200 and json.loads(body).get("version") == __version__, __version__)
            check("config creato al primo avvio", (tmp / "config.toml").is_file())
        finally:
            server.shutdown()
            server.server_close()
        # il pacchetto non deve scrivere accanto a se stesso: tutto e' finito nella cartella temporanea
        check("dati nella cartella temporanea", any(tmp.iterdir()))
    except Exception as e:  # noqa: BLE001
        check("avvio del server", False, f"{type(e).__name__}: {e}")
    finally:
        if old_home is None:
            os.environ.pop("JOBSHUNTER_HOME", None)
        else:
            os.environ["JOBSHUNTER_HOME"] = old_home
        shutil.rmtree(tmp, ignore_errors=True)
    say("RISULTATO: " + ("tutto bene" if ok else "FALLITO"))
    if log_path:
        try:
            Path(log_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    log = None
    if "--smoke-log" in argv:
        i = argv.index("--smoke-log")
        log = argv[i + 1] if i + 1 < len(argv) else None
    return run(log)
