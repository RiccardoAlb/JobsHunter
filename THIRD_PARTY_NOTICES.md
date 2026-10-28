# Avvisi sulle componenti di terze parti

JobsHunter usa le librerie qui sotto, ciascuna con la propria licenza. L'elenco e' generato dai metadati dei pacchetti installati
(`scripts/gen_third_party.py`, senza rete): per i testi completi delle licenze vedi il pacchetto di ciascuna libreria.
Le licenze indicate sono quelle dichiarate dai pacchetti; vanno ricontrollate prima di ogni pubblicazione.

## Librerie usate a runtime

| Pacchetto | Versione | Licenza | Sito |
|---|---|---|---|
| anyio | 4.15.1 | MIT | https://anyio.readthedocs.io/en/latest/ |
| beautifulsoup4 | 4.15.0 | MIT License | https://www.crummy.com/software/BeautifulSoup/bs4/download/ |
| blinker | 1.9.0 | MIT License | https://discord.gg/pallets |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi | 2.1.1 | MIT-0 | https://cffi.readthedocs.io/ |
| click | 8.5.0 | BSD-3-Clause | https://click.palletsprojects.com/page/changes/ |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | https://cryptography.io/en/latest/changelog/ |
| Flask | 3.1.3 | BSD-3-Clause | https://flask.palletsprojects.com/page/changes/ |
| geonamescache | 3.0.2 | MIT | https://github.com/yaph/geonamescache#readme |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx/blob/master/CHANGELOG.md |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna/blob/master/HISTORY.md |
| itsdangerous | 2.2.0 | BSD License | https://itsdangerous.palletsprojects.com/changes/ |
| Jinja2 | 3.1.6 | BSD License | https://jinja.palletsprojects.com/changes/ |
| lxml | 6.1.3 | BSD-3-Clause | https://lxml.de/ |
| markdown-it-py | 4.2.0 | MIT License | https://markdown-it-py.readthedocs.io |
| MarkupSafe | 3.0.4 | BSD-3-Clause | https://palletsprojects.com/donate |
| mdurl | 0.1.2 | MIT License | https://github.com/executablebooks/mdurl |
| pycparser | 3.12 | BSD-3-Clause | https://github.com/eliben/pycparser |
| Pygments | 2.21.0 | BSD-2-Clause | https://pygments.org |
| pypdf | 6.21.3 | BSD-3-Clause | https://github.com/py-pdf/pypdf/issues |
| rich | 15.0.0 | MIT | https://rich.readthedocs.io/en/latest/ |
| soupsieve | 2.10 | MIT | https://github.com/facelessuser/soupsieve |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions/issues |
| Werkzeug | 3.1.9 | BSD-3-Clause | https://werkzeug.palletsprojects.com/page/changes/ |

## Strumenti per costruire l'app Mac (non inclusi nel codice del progetto)

| Pacchetto | Versione | Licenza |
|---|---|---|
| altgraph | 0.17.5 | MIT |
| bottle | 0.13.4 | MIT |
| macholib | 1.16.4 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pillow | 12.3.0 | MIT-CMU |
| proxy_tools | 0.1.0 | MIT |
| pyinstaller | 6.22.3 | GNU General Public License v2 (GPLv2) |
| pyinstaller-hooks-contrib | 2026.8 | Apache Software License, GNU General Public License v2 (GPLv2) |
| pyobjc-core | 12.2.2 | MIT |
| pyobjc-framework-Cocoa | 12.2.2 | MIT |
| pyobjc-framework-Quartz | 12.2.2 | MIT |
| pyobjc-framework-Security | 12.2.2 | MIT |
| pyobjc-framework-UniformTypeIdentifiers | 12.2.2 | MIT |
| pyobjc-framework-WebKit | 12.2.2 | MIT |
| pywebview | 6.2.1 | BSD License |
| setuptools | 84.0.0 | MIT |

PyInstaller incorpora nell'app le librerie del runtime e l'interprete Python (licenza PSF). PyInstaller e' GPLv2 con eccezione
per il bootloader: le app prodotte non sono vincolate alla GPL. `certifi` (MPL-2.0) e' inclusa cosi' com'e', senza modifiche.

## Dati

- **GeoNames** (<https://www.geonames.org>): coordinate e nomi delle citta' con piu' di 15.000 abitanti, tramite il pacchetto `geonamescache`.
  Licenza **Creative Commons Attribution 4.0** (<https://creativecommons.org/licenses/by/4.0/>): serve citare GeoNames (CC BY 4.0), come fa questo file.
- **Adzuna** (<https://developer.adzuna.com>) e **Jooble** (<https://jooble.org/api/about>): annunci ricevuti tramite le loro API con chiavi personali.
  I contenuti restano dei rispettivi titolari e dei loro termini d'uso; non sono ridistribuiti da questo progetto.

Logo (`branding/logo-original.jpg`): origine e licenza da confermare a cura dell'autore prima della pubblicazione.
