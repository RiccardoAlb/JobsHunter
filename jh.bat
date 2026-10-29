@echo off
rem Avvio di JobsHunter su Windows: jh.bat gui | app | scan | list | ...
rem Non dipende dalla cartella corrente. Usa il venv del progetto (.venv\Scripts\python.exe) se c e, altrimenti "python".
setlocal
set "DIR=%~dp0"
if exist "%DIR%.venv\Scripts\python.exe" (
  set "PY=%DIR%.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
set "PYTHONPATH=%DIR%;%PYTHONPATH%"
set "PYTHONUTF8=1"
"%PY%" -m jobshunter %*
exit /b %ERRORLEVEL%
