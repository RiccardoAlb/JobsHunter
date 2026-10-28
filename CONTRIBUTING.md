# Contribuire / Contributing

Grazie dell'interesse! / Thanks for your interest!

**IT.** Il progetto e' uno strumento personale e locale per cercare lavoro. Le proposte sono benvenute, in italiano o in inglese.

1. Apri prima una *issue* per le modifiche grandi (nuova fonte, nuovo tipo di profilo, cambi alla sicurezza).
2. Ambiente: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest`.
3. Prima di aprire una pull request: `.venv/bin/python -m pytest -q` e `python scripts/check_publishable.py` devono passare.
4. Regole dei test: **mai dati veri** (ogni test lavora in una cartella dati temporanea e con una HOME finta, lo garantisce `tests/conftest.py`)
   e **nessuna rete reale** (il collaudo la vieta). Per le fonti usa `httpx.MockTransport` o la fonte finta.
5. Se aggiungi una funzione, aggiungi il test. Se tocchi i duplicati, rimisura con `tests/qa/measure_dedupe.py`.
6. Niente chiavi, email o percorsi personali in codice, esempi, test o screenshot.
7. Le fonti si usano nel rispetto dei loro termini: niente aggiramento di protezioni anti-bot, niente User-Agent che fingono di essere un browser.

**EN.** This is a personal, local-first job-search tool. Contributions are welcome in Italian or English.
Open an issue first for big changes. Set up a venv, run `python -m pytest -q` and `python scripts/check_publishable.py` before opening a PR.
Tests must never touch real data and must never use the network (see `tests/conftest.py`). Never commit keys, emails, personal paths or personal screenshots.
Respect the terms of the services the tool talks to: no anti-bot bypassing, no browser-impersonating User-Agent.
