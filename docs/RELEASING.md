# Come fare una release

Il workflow `.github/workflows/release.yml` costruisce i pacchetti da un tag `vX.Y.Z` e prepara una **bozza** di release.
**Non pubblica mai da solo**: l'ultimo passo, la pubblicazione, lo fai tu dopo aver scaricato e provato i file.

## Passi

1. **Aggiorna la versione** (un solo numero, che deve coincidere con il tag):
   - `jobshunter/__init__.py` (`__version__`) e `pyproject.toml` (`version`);
   - `CHANGELOG.md`: titolo `## [X.Y.Z] - AAAA-MM-GG` con le novita' (diventano le note della release);
   - `README.md` e `README.en.md`: riga "Versione X.Y.Z" in alto e l'esempio di User-Agent.
   I test `tests/builder/test_phase9.py` controllano che siano tutti uguali.
2. **Controlla in locale**: suite dei test, `python scripts/check_publishable.py`, e se vuoi un pacchetto di prova
   `packaging/build_mac.sh --out /una/cartella` (macOS), `packaging\\build_windows.ps1` (Windows): tutti lanciano anche il test di fumo.
3. **Crea il tag e mandalo su GitHub**: `git tag vX.Y.Z` e `git push origin vX.Y.Z`. In alternativa, dalla scheda Actions, **Release**, **Run workflow** (la casella "bozza" e' attiva di default).
4. **Aspetta il workflow.** Quattro job costruiscono (macOS arm64, Windows x64, Linux amd64 e Linux arm64), ognuno prova il pacchetto con `--smoke`; poi il job `bozza` crea la release in **bozza** con i pacchetti, `SHA256SUMS.txt` e le note prese dal CHANGELOG.
5. **Controlla la bozza** (scheda Releases, visibile solo a te): ci sono tutti i file? i nomi e le dimensioni sono quelli attesi? Le note sono giuste?
6. **Scarica e prova** almeno un pacchetto per sistema che puoi: apri l'app, controlla la versione in Impostazioni, fai una ricerca con dati finti o con le tue chiavi. Verifica l'hash (`shasum -a 256` su macOS e Linux, `Get-FileHash` su Windows) con `SHA256SUMS.txt`.
7. **Pubblica la bozza** (Edit, **Publish release**): questo passo lo fai solo tu. Il workflow non lo fa e non ha il permesso di farlo oltre a creare la bozza.

## Cose da sapere

- I pacchetti sono **non firmati e non notarizzati**: il README spiega gli avvisi di macOS e di Windows SmartScreen.
- Se per quel tag esiste gia' una release, il workflow si ferma senza toccarla: cancella la bozza vecchia e rilancia.
- **Linux:** `packaging/build_linux.sh` costruisce `jobshunter_<versione>_<amd64|arm64>.deb` con `dpkg-deb` (cartella PyInstaller in `/opt/jobshunter`, collegamento `/usr/bin/jobshunter`, voce di menu e icona, `Depends: libc6 (>= 2.35)`) e, su x86_64, la AppImage. Il test di fumo del .deb (`packaging/smoke_deb.sh`) lo installa con apt, lancia `jobshunter --smoke`, controlla i file e lo toglie con `apt remove`: si lancia solo in CI o a mano con `--yes` su una macchina usa e getta. L'arm64 gira sul runner `ubuntu-22.04-arm` (gratuito per le repo pubbliche); se non fosse disponibile, togli quella voce dalla matrice e scrivi "non fornito" nel README.
- **AppImage:** si costruisce solo se in `packaging/appimagetool.txt` c'e' anche l'hash SHA256 di appimagetool: scarica il file indicato in `url`, calcola `shasum -a 256 <file>` e scrivi il risultato dopo `sha256=`; senza hash la release Linux ha solo i `.deb` (lo script lo dice).
- **Installer di Windows:** si costruisce se Inno Setup e' disponibile (il workflow lo installa con `choco`, versione fissa; se l'installazione fallisce la release contiene solo lo zip).
- **Azioni di terze parti:** sono bloccate a una versione precisa (`@vX.Y.Z`); per aggiornarle cambia il numero a mano e rileggi le note di quella versione.
- Il workflow usa solo `GITHUB_TOKEN` con `contents: write` nel solo job `bozza`; non ci sono altri segreti e non gira sui fork.
- Per provare un pacchetto a mano senza GitHub: `JobsHunter --smoke` (macOS: `JobsHunter.app/Contents/MacOS/JobsHunter --smoke`; Linux: `jobshunter --smoke` dopo aver installato il .deb, o `JobsHunter-<versione>-Linux-x86_64.AppImage --appimage-extract-and-run --smoke`; Windows: `JobsHunter.exe --smoke --smoke-log risultato.txt`, perche' senza console non stampa).
