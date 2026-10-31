@echo off
rem Avvio di JobsHunter da sorgente su Windows: jh.bat gui | app | scan | list | setup | ...
rem Non dipende dalla cartella corrente. Controlla che ci sia Python 3.11 o superiore (py -3.13, -3.12, -3.11, -3, python).
rem Se manca, spiega cosa fare e CHIEDE CONFERMA prima di installare (mai installazioni silenziose, mai download ed esecuzione di file).
rem   jh.bat setup [--yes]   crea .venv se manca e installa requirements.txt (--yes = conferma di scaricare le dipendenze)
rem I pacchetti scaricabili (.exe, .app, .deb) contengono il proprio Python: questo controllo serve solo a chi usa il codice sorgente.
setlocal EnableExtensions
set "DIR=%~dp0"
set "PYTHONUTF8=1"
set "PYFOUND="

if /i "%~1"=="setup" goto setup_entry

rem 1) strada normale: .venv presente e con Python adatto
if not exist "%DIR%.venv\Scripts\python.exe" goto no_venv
"%DIR%.venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto venv_old
set "PYTHONPATH=%DIR%;%PYTHONPATH%"
"%DIR%.venv\Scripts\python.exe" -m jobshunter %*
exit /b %ERRORLEVEL%

:venv_old
echo L'ambiente .venv usa un Python piu' vecchio della 3.11. Cancella la cartella .venv e lancia jh.bat setup.
exit /b 1

rem 2) niente .venv: serve un Python adatto per crearlo
:no_venv
call :find_python
if defined PYFOUND goto have_python
call :missing_python
if errorlevel 1 exit /b 1
call :find_python
if defined PYFOUND goto have_python
echo Installato, ma non lo trovo ancora nel PATH: chiudi e riapri il terminale, poi rilancia jh.bat setup.
exit /b 1

:have_python
echo Manca l'ambiente .venv di JobsHunter. Python trovato: %PYFOUND%
set "ANS="
set /p "ANS=Vuoi prepararlo ora con jh.bat setup? [s/N] "
if /i "%ANS%"=="s" goto run_setup_then_app
if /i "%ANS%"=="si" goto run_setup_then_app
if /i "%ANS%"=="y" goto run_setup_then_app
echo Esegui jh.bat setup per prepararlo.
exit /b 1

:run_setup_then_app
call :do_setup ""
if errorlevel 1 exit /b 1
set "PYTHONPATH=%DIR%;%PYTHONPATH%"
"%DIR%.venv\Scripts\python.exe" -m jobshunter %*
exit /b %ERRORLEVEL%

:setup_entry
set "SETUP_ARG=%~2"
if not "%SETUP_ARG%"=="" if /i not "%SETUP_ARG%"=="--yes" (
  echo Uso: jh.bat setup [--yes]
  exit /b 2
)
if exist "%DIR%.venv\Scripts\python.exe" goto setup_have_venv
call :find_python
if defined PYFOUND goto setup_go
call :missing_python
if errorlevel 1 exit /b 1
call :find_python
if defined PYFOUND goto setup_go
echo Installato, ma non lo trovo ancora nel PATH: chiudi e riapri il terminale, poi rilancia jh.bat setup.
exit /b 1
:setup_have_venv
set "PYFOUND=%DIR%.venv\Scripts\python.exe"
:setup_go
call :do_setup "%SETUP_ARG%"
if errorlevel 1 exit /b 1
exit /b 0

rem ---------------------------------------------------------------- funzioni
:find_python
set "PYFOUND="
call :try_py "py -3.13"
call :try_py "py -3.12"
call :try_py "py -3.11"
call :try_py "py -3"
call :try_py "python"
exit /b 0

:try_py
if defined PYFOUND exit /b 0
%~1 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PYFOUND=%~1"
exit /b 0

:missing_python
echo JobsHunter da sorgente ha bisogno di Python 3.11 o superiore, e qui non l'ho trovato o e' troppo vecchio.
echo Cercati, in quest'ordine: py -3.13, py -3.12, py -3.11, py -3, python.
echo I pacchetti scaricabili (.exe, .app, .deb) contengono il proprio Python e non ne hanno bisogno.
where winget >nul 2>&1
if errorlevel 1 goto no_winget
echo Comando per installarlo: winget install -e --id Python.Python.3.13 --scope user
set "ANS="
set /p "ANS=Vuoi installarlo ora? [s/N] "
if /i "%ANS%"=="s" goto do_winget
if /i "%ANS%"=="si" goto do_winget
if /i "%ANS%"=="y" goto do_winget
echo Va bene, non installo nulla.
exit /b 1
:do_winget
winget install -e --id Python.Python.3.13 --scope user
if errorlevel 1 exit /b 1
exit /b 0
:no_winget
echo winget non c'e'. Scarica Python da https://www.python.org/downloads/windows/ e installalo (spunta "Add python.exe to PATH").
set "ANS="
set /p "ANS=Vuoi che apra la pagina di download nel browser? [s/N] "
if /i "%ANS%"=="s" start "" "https://www.python.org/downloads/windows/"
if /i "%ANS%"=="si" start "" "https://www.python.org/downloads/windows/"
if /i "%ANS%"=="y" start "" "https://www.python.org/downloads/windows/"
echo Dopo l'installazione chiudi e riapri il terminale, poi rilancia jh.bat setup.
exit /b 1

:do_setup
if exist "%DIR%.venv\Scripts\python.exe" goto setup_pip
echo Creo l'ambiente .venv con %PYFOUND% ...
%PYFOUND% -m venv "%DIR%.venv"
if errorlevel 1 (
  echo Non sono riuscito a creare .venv.
  exit /b 1
)
:setup_pip
if /i "%~1"=="--yes" goto pip_go
set "ANS="
set /p "ANS=Ora scarico da internet le librerie elencate in requirements.txt (pip install). Continuo? [s/N] "
if /i "%ANS%"=="s" goto pip_go
if /i "%ANS%"=="si" goto pip_go
if /i "%ANS%"=="y" goto pip_go
echo Va bene, mi fermo qui.
exit /b 1
:pip_go
"%DIR%.venv\Scripts\python.exe" -m pip install -r "%DIR%requirements.txt"
if errorlevel 1 (
  echo Installazione delle librerie non riuscita.
  exit /b 1
)
echo Fatto. Prova: jh.bat gui
exit /b 0
