#!/usr/bin/env python3
"""Screenshot della GUI per la documentazione, da un server di prova con dati FINTI (scripts/demo_server.py).

Uso:  python3 scripts/take_screenshots.py [--port 8851] [--browser "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
Richiede un browser basato su Chromium e il pacchetto `websockets` (solo per questo script, non e' una dipendenza del progetto).
Avvia un browser PROPRIO (profilo temporaneo) e lo chiude alla fine; non tocca altri processi.
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


class Page:
    def __init__(self, ws_url: str):
        self.ws = connect(ws_url, max_size=64 * 1024 * 1024)
        self.n = 0

    def call(self, method: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def js(self, code: str):
        return self.call("Runtime.evaluate", expression=code, awaitPromise=True, returnByValue=True).get("result", {}).get("value")

    def shot(self, name: str) -> None:
        data = self.call("Page.captureScreenshot", format="png")["data"]
        (OUT / name).write_bytes(base64.b64decode(data))
        print("scritto", name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8851)
    ap.add_argument("--debug-port", type=int, default=9341)
    ap.add_argument("--browser", default="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{a.port}/"
    prof = tempfile.mkdtemp(prefix="jh-shot-")
    proc = subprocess.Popen([a.browser, "--headless=new", f"--remote-debugging-port={a.debug_port}", f"--user-data-dir={prof}",
                             "--window-size=1440,900", "--hide-scrollbars", "--force-device-scale-factor=1", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{a.debug_port}/json"))
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise SystemExit("browser non raggiungibile")
        p = Page(page["webSocketDebuggerUrl"])
        p.call("Page.enable")
        p.call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)

        def load(theme="dark"):
            p.call("Page.navigate", url=base)
            time.sleep(1.5)
            p.js(f'localStorage.setItem("jh-theme", "{theme}"); document.documentElement.dataset.theme = "{theme}"; 1')
            p.call("Page.navigate", url=base)
            time.sleep(2.5)

        def tab(name, wait=1.8):
            p.js(f'document.querySelector(\'.tab[data-v="{name}"]\').click(); 1')
            time.sleep(wait)

        load("dark")
        time.sleep(3)  # il confronto col CV si calcola in background
        p.js("location.reload(); 1")
        time.sleep(3)
        p.shot("01-lista.png")
        p.js('document.querySelector("tr.row").click(); 1')
        time.sleep(2.5)
        p.shot("02-scheda-affinita-cv.png")
        p.js("closeDrawer(); 1")
        tab("apps")
        p.shot("03-candidature.png")
        tab("dups")
        p.shot("04-duplicati.png")
        tab("search")
        p.shot("05-ricerca.png")
        tab("settings", 2.5)
        p.js('document.getElementById("about").scrollIntoView(); 1')
        p.js(r'''document.querySelectorAll(".sfoot div").forEach(d => { d.childNodes.forEach(n => { if (n.nodeType === 3) n.textContent = n.textContent.replace(/\/[^ ]*(jobshunter-demo-[^\/ ]*)/g, "~/Library/Application Support/JobsHunter"); }); }); 1''')
        time.sleep(0.6)
        p.shot("06-impostazioni-informazioni.png")
        p.js('openOnboarding(true); 1')
        time.sleep(1.5)
        p.shot("07-guida-primo-avvio.png")
        load("light")
        time.sleep(2)
        p.shot("08-tema-chiaro.png")
        p.ws.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
