# Changelog

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).

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
