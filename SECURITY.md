# Sicurezza / Security policy

## Come segnalare una vulnerabilita' / Reporting a vulnerability

**IT.** Non aprire una issue pubblica per un problema di sicurezza. Usa la funzione *Report a vulnerability* di GitHub
(scheda *Security* del repository, "Private vulnerability reporting") oppure scrivi al contatto indicato nel profilo del mantenitore.
Indica: versione, passi per riprodurlo, impatto. Si risponde appena possibile; e' un progetto personale, senza SLA.

**EN.** Please do not open a public issue for a security problem. Use GitHub's *Report a vulnerability* (the repository's *Security* tab,
"Private vulnerability reporting") or contact the maintainer listed on their profile. Include the version, steps to reproduce and the impact.
This is a personal project: replies are best effort, with no SLA.

## Modello di minaccia / Threat model

- La GUI ascolta **solo su 127.0.0.1**, non ha password e non va esposta su internet. Rifiuta richieste con `Host` o `Origin` diversi dal proprio
  e richieste dichiarate cross-site dal browser; il corpo delle richieste e' limitato (256 KB, 6 MB solo per il CV).
- Chiavi API, impostazioni e CV stanno in file con permessi `600` nella cartella dati; non escono mai nelle API, nei log o nei report.
- I testi degli annunci sono mostrati come testo semplice (mai HTML). Nessuna esecuzione di comandi di shell con dati dell'utente.
- Tutto resta in locale: nessuna telemetria. Le uniche richieste in uscita sono verso le fonti di annunci, ntfy.sh (se attivato) e le pagine degli annunci.

Versioni supportate / Supported versions: l'ultima / the latest release.
