# Changelog

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).

## [0.4.0] - in preparazione

Portabilita' (fase 7): macOS, Windows e Linux. Il numero di versione nel codice resta quello attuale finche' non si pubblica.

### Aggiunto
- `jobshunter/osinfo.py` (sistema e cartelle dati/log per sistema, `JOBSHUNTER_HOME` invariato), `filelock.py` (blocco di file con fcntl o msvcrt: nessun `import fcntl` fuori da li'), `fsperm.py` (permessi riservati: chmod su POSIX, `icacls` su Windows, mai eccezioni).
- `jh.bat` per Windows, `requirements-gui.txt` (pywebview per Windows e Linux); `./jh app` ripiega sul browser se pywebview manca o la finestra non parte.
- Zone protette per la cartella dei report anche su Windows (Windows, Program Files, ProgramData, AppData, radice di unita', cartelle di rete) e Linux (/etc, /usr, /var, /root...), senza distinguere maiuscole su Windows e macOS.
- Scansione automatica anche su Windows (Utilita' di pianificazione) e Linux (timer `systemd --user`, altrimenti cron); notifiche di Windows (PowerShell) e Linux (`notify-send`). Opzioni `--home` e `scan-auto --log-file`.
- CI su `windows-latest`.

### Corretto (dopo il collaudo)
- cron: mai riscritto se non si riesce a leggere; rimosse solo le righe proprie. `scan-auto --log-file` registra gli errori. Home Linux uguale a `/` non ammette tutto. `secure_file`/`secure_dir` solo su file e cartelle veri.
  `schedule on` senza strumenti non salva niente. Gestore dei file lanciato staccato. Codifica esplicita per i comandi di sistema. `config.toml` con backslash: messaggio chiaro. Prefisso `\\?\` locale, `$` in systemd, notifiche con NUL, metadati del pacchetto, nessun `osascript` vero nei test.

### Corretto (prima suite su Windows)
- Su Windows `os.replace` e la lettura di config e CV riprovano se il file e' aperto per un attimo (`fsutil`); `cv.json` con un blocco tra thread; `cv.delete()` non fallisce se il file e' aperto; percorsi XDG simulati. I test specifici di macOS o POSIX sono saltati con motivo (`tests/conftest.py`); i test leggono e scrivono in UTF-8; `JOBSHUNTER_TEST_TIME_FACTOR` per le macchine lente.

### Corretto (icacls su Windows)
- `fsperm`: l'utente si indica per SID (con ripiego su DOMINIO\\utente e sul solo nome se icacls risponde 1332), l'ereditarieta' si toglie solo dopo una concessione riuscita e si controlla di poter ancora aprire il file (altrimenti `/reset`). Prima, fuori dominio, la protezione non veniva mai applicata.

### Corretto (secondo giro, fase 7)
- `cv.delete()` non dice di aver cancellato se il CV si legge ancora (errore chiaro in GUI e CLI); il temporaneo del salvataggio nasce sotto il blocco. Comandi esterni su Windows senza finestra nera (`proc.py`). Riga cron con bus D-Bus e `DISPLAY` per `notify-send`. Meno test saltati fuori da macOS.

### Cambiato
- Apri cartelle e link con il programma del sistema (Finder, Esplora risorse, `xdg-open`); testi dell'interfaccia senza "Mac" dove valgono per tutti.
- Tutti i file di testo si leggono e scrivono in UTF-8 (Windows usa altrimenti una codifica a 8 bit); la console non da' errori con i simboli.
- Il messaggio "solo macOS" della scansione automatica e' ora per sistema e per strumento mancante.

Non ancora provato su una macchina Windows o Linux vera: vedi `docs/phase7_status.md`.

## [0.3.0] - 2026-10-28

Categorie personali per profilo (fase 6). Il numero di versione nel codice resta 0.2.0 finche' non si pubblica.

### Aggiunto
- Ogni profilo puo' avere le sue **categorie** (nome + parole che la riconoscono): editor nella scheda Ricerca, filtri nella lista (solo quelle con annunci), colore neutro per quelle dell'utente,
  campo facoltativo "Categorie" nella guida di primo avvio (nessun passo nuovo), `./jh profiles add --category` e `./jh profiles categories`.
- I preset copiano le loro categorie nel nuovo profilo come categorie modificabili ("Ripristina quelle del preset").
- Copia di sicurezza del database in `backups/` (ultime tre) prima di ricalcolare le categorie.

### Corretto (dopo il collaudo)
- Ricalcolo atomico: se fallisce il database non resta bloccato e il profilo torna com'era; salvataggi dei profili serializzati. Cambio di tipo che sostituisce le categorie, categorie di altri tipi solo come bonus,
  unione delle categorie con "Profilo: tutti", filtri con simboli nel nome, normalizzazione Unicode delle etichette, backup con nome unico, report in ordine stabile.

- Categorie "copiate da un preset" accettate senza limiti solo se identiche a quelle del server, altrimenti limiti stretti; filtro `?cat=` normalizzato e mai "tutto l'elenco" per nomi non validi; ricalcolo e punteggi migliori nella stessa transazione; guida e profili con lo stesso blocco.

- Categorie di un gruppo del tipo di profilo modificabili anche se grandi (fino a 40 parole o parole + 20); etichette ricavate dai titoli normalizzate NFKC.

### Cambiato
- Un profilo personalizzato con categorie usa quelle per l'etichetta degli annunci (`ALTRO` se nessuna combacia); una categoria dell'utente puo' dare al massimo +4 punti (titolo) o +2 (testo)
  e mai fa entrare un annuncio da sola. I punteggi e le categorie dei profili esistenti e dei preset non cambiano (test di regressione).

## [0.2.0] - 2026-10-28

Rifinitura per la pubblicazione.

### Cambiato
- **Nuovo nome: JobsHunter** (era JobHunter): pacchetto Python `jobshunter`, app `JobsHunter.app`, identificativo `local.jobshunter.app`,
  LaunchAgent `local.jobshunter.scan`, cartella dati `~/Library/Application Support/JobsHunter`, log in `~/Library/Logs/JobsHunter`, variabile `JOBSHUNTER_HOME`.
- **Migrazione sicura**: al primo avvio i dati della vecchia cartella `JobHunter` vengono COPIATI (mai spostati) nella nuova, con verifica di integrita' del database;
  se esistono entrambe si usa la nuova; il vecchio LaunchAgent viene tolto e, se la scansione automatica era attiva, ne viene installato uno nuovo (senza doppioni).
- **User-Agent onesto**: tutte le richieste si presentano come `JobsHunter/<versione> (+personal job search tool; contact: ...)`, non piu' come un browser.
  Contatto e User-Agent sono configurabili (`[net]` in `config.toml`, Impostazioni > Avanzate, rete). Se un sito rifiuta (403, 429) non si insiste e l'annuncio resta "non verificato".
- La configurazione di esempio e' neutra (nessuna citta' di casa predefinita). Greenhouse e Lever (aziende cyber) sono interrogate solo dai profili cybersecurity.

### Aggiunto
- Informazioni e attribuzioni in Impostazioni (Adzuna, Jooble, GeoNames CC BY 4.0), sezione Avvertenze nel README, `THIRD_PARTY_NOTICES.md`.
- `README.en.md`, screenshot in `docs/screenshots/`, `scripts/check_publishable.py`, CI di GitHub, `CONTRIBUTING.md`, `SECURITY.md`.

### Aggiunto (dopo il collaudo)
- Comandi `./jh gui` e `./jh app`; extra `mac` (pywebview); `JOBHUNTER_HOME` ancora accettata con avviso; migrazione con blocco tra processi.

### Sicurezza
- Chiavi mai nei messaggi di errore, richieste chunked rifiutate, report senza immagini esterne, nessun redirect verso reti private.
- Controlli `Origin`/`Sec-Fetch-Site` su ogni richiesta che modifica dati, limite di 256 KB sui corpi JSON, intestazioni di sicurezza (CSP, nosniff, no-referrer, no framing),
  database creato con permessi 600, `config.toml` creato con permessi 600, esportazione CSV protetta dalle formule, log di httpx silenziati per non scrivere chiavi.

## [0.1.0]

Versione privata: raccolta da piu' fonti, profili di ricerca e paesi, duplicati, verifica annunci aperti, candidature, scansione automatica, guida di primo avvio, confronto locale con il CV, app per Mac.

### Test su Windows vero (terza esecuzione)
- I tre test icacls del builder sostituiscono `fsperm._whoami_output` (su Windows `whoami` partiva davvero); `test_ld_ensure_current_con_scansione_attiva...` controlla `0o644` solo fuori da Windows; `test_cv_delete_errore_vero_non_si_nasconde_su_posix` ha lo skipif su Windows. Nessuna modifica al codice di produzione.
- Copia pulita (senza config.toml, database, settings.json): `test_jh_app_ripiega_sul_browser_con_messaggio_chiaro` usava il config.toml del progetto; ora il figlio ha una cartella dati con config copiato da `config.example.toml`. Nella copia pulita la suite passa intera (2632 passati, 3 saltati per assenza di .venv/.git).
- **Primo avvio:** se manca `config.toml` e c'e' `config.example.toml`, tutti i comandi (`gui`, `app`, `scan`, `list`, `cv`, `scan-auto`...) lo creano da soli (UTF-8, scrittura atomica, permessi sicuri, blocco tra processi, mai sopra un file esistente) e scrivono una riga: "Creato config.toml dal file di esempio: lo trovi in <percorso>". Un `--config` indicato a mano e inesistente resta un errore. Se manca anche l'esempio l'errore dice di riscaricarlo dal repository. Nei README il passo `cp config.example.toml config.toml` e' facoltativo. Nuovo `tests/builder/test_first_run.py`.

### Prima CI su GitHub (macOS, Ubuntu, Windows)
- **jh.bat in CRLF:** nuovo `.gitattributes` (`*.bat`/`*.cmd` `eol=crlf`, `jh` e `*.sh` `eol=lf`, binari `binary`), cosi' Git non normalizza `jh.bat` a LF su un clone fresco. `jh` e gli script `.sh` restano eseguibili (100755).
- **Motore locale (`jh app`):** se `_wait_port` scade, `app.log` riporta porta, attesa, stato del thread e l'eventuale eccezione (prima invisibile); l'attesa e' regolabile con `JOBSHUNTER_ENGINE_TIMEOUT` (predefinito 20 s). Il test `jh app` aspetta fino a 90 s e, se manca la porta, mostra stderr completo e le ultime 40 righe di `app.log`.
- **CI:** `JOBSHUNTER_TEST_TIME_FACTOR` nel workflow (3 Windows, 2 macOS, 1 Ubuntu) per i test di prestazioni (`t()` e' usato da `test_dedupe_blind` e `test_prestazioni_5000_annunci`).
- **Test:** ogni lettura dell'output di sottoprocessi usa `encoding="utf-8", errors="replace"` (il test delle SKIP_RULES imposta anche `PYTHONIOENCODING=utf-8`); la condizione Windows dell'asserzione `0o644` e' ora `os.name == "nt"` perche' la fixture `ld` simula `sys.platform = "darwin"`.

### Arresto ordinato (CI 49abf22)
- **Difetto vero:** un processo con SIGINT ignorato all'avvio (CI, `nohup`, servizi) o fermato con SIGTERM non usciva mai dall'attesa di `./jh app` (ripiego sul browser) e `./jh gui`. Nuovo `jobshunter/stopsignals.py`: handler espliciti per SIGINT, SIGTERM e (Windows) SIGBREAK, installati nel thread principale, che accendono un evento; l'attesa e' interrompibile (`Event.wait(0.5)`). `app` (browser di ripiego e finestra nativa, chiusa con `destroy()`) e `gui` (server werkzeug fermato con `shutdown()`) escono con codice 0 e senza traceback.
- **Test:** `test_jh_app_si_ferma_in_modo_ordinato_con_i_segnali` (nowebview, startfails, finestra finta x SIGINT/SIGTERM x SIGINT normale/ignorato) e `test_jh_gui_si_ferma_in_modo_ordinato_con_i_segnali`; nel test esistente dopo `kill()` c'e' `wait()` e il messaggio "il processo non ha risposto a SIGINT".

### CI su repo pubblica (c1df44c)
- **Ubuntu:** i test che avviano `jh app`/`jh gui` con una HOME propria passano al figlio un ambiente completo (`child_home_env`: HOME, USERPROFILE, APPDATA, LOCALAPPDATA, XDG_DATA_HOME, XDG_STATE_HOME, XDG_CONFIG_HOME dentro la cartella del test), perche' su Linux il log sta in `$XDG_STATE_HOME` e la guardia globale di conftest lo puntava altrove. Riprodotto sul Mac con `sys.platform = "linux"` nel figlio: 12 test rossi con XDG fuori dalla home, 12 verdi con il fix. Stesso ambiente anche per `scan-auto` e il test delle console non UTF-8.
- **Windows 3.11:** `test_limiter_riapre_dopo_l_intervallo` usa un orologio finto (`time.monotonic`) invece di `sleep(0.06)`.
