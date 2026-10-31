# Costruisce JobsHunter-<versione>-Windows-x64.zip (cartella JobsHunter\ con JobsHunter.exe) e, se Inno Setup e' installato,
# anche JobsHunter-<versione>-Windows-x64-Setup.exe; poi prova il pacchetto con --smoke.
# Uso (PowerShell, dalla cartella del progetto, per esempio C:\jh):
#     powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 [-Out CARTELLA] [-NoSmoke] [-Python percorso\python.exe]
# Stesse opzioni della CI. Il testo e' solo ASCII: Windows PowerShell 5.1 legge i file senza BOM nella tabella ANSI.
#
# Richiede Python 3.11 o superiore (la CI usa 3.13) con le dipendenze del progetto (requirements.txt + requirements-gui.txt).
# Se esiste .venv nella cartella del progetto si usa quello. Nessun dato personale entra nel pacchetto.
param(
    [string]$Out = "",
    [switch]$NoSmoke,
    [string]$Python = ""
)
$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $PSScriptRoot
Set-Location $proj
if (-not $Out) { $Out = Join-Path $proj "dist-release" }
# Percorso assoluto: Inno Setup legge /DOutDir rispetto alla cartella dello script .iss, non a quella di lavoro
if (-not [System.IO.Path]::IsPathRooted($Out)) { $Out = Join-Path $proj $Out }
if (-not $Python) {
    $venv = Join-Path $proj ".venv\Scripts\python.exe"
    if (Test-Path $venv) { $Python = $venv } else { $Python = "python" }
}
function Run($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Comando fallito ($LASTEXITCODE): $exe $($arguments -join ' ')" }
}

$ver = (& $Python -c "import jobshunter; print(jobshunter.__version__)").Trim()
if (-not $ver) { throw "Non riesco a leggere la versione" }
$work = if ($env:JH_WORK) { $env:JH_WORK } else { Join-Path $env:TEMP "jobshunter-build-release" }
$zipName = "JobsHunter-$ver-Windows-x64.zip"
$setupName = "JobsHunter-$ver-Windows-x64-Setup.exe"

Run $Python @("-m", "pip", "install", "-q", "pyinstaller", "pillow", "pywebview")
Run $Python @("branding\make_icons.py")

if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force -Path $work | Out-Null
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Run $Python @("-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", (Join-Path $work "dist"), "--workpath", (Join-Path $work "work"), "packaging\JobsHunter.spec")

$dist = Join-Path $work "dist\JobsHunter"
$exe = Join-Path $dist "JobsHunter.exe"
if (-not (Test-Path $exe)) { throw "JobsHunter.exe non trovato in $dist" }
$mb = [math]::Round(((Get-ChildItem $dist -Recurse | Measure-Object Length -Sum).Sum) / 1MB, 1)
Write-Host "Cartella del programma: $mb MB"

$zipPath = Join-Path $Out $zipName
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($dist, $zipPath, [System.IO.Compression.CompressionLevel]::Optimal, $true)
Write-Host ("Creato: {0} ({1} MB)" -f $zipPath, [math]::Round((Get-Item $zipPath).Length / 1MB, 1))

# ---- installer (facoltativo: serve Inno Setup 6) ----
$iscc = $null
$cmd = Get-Command iscc -ErrorAction SilentlyContinue
if ($cmd) { $iscc = $cmd.Source }
foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
    if (-not $iscc -and $p -and (Test-Path $p)) { $iscc = $p }
}
$setupPath = Join-Path $Out $setupName
if ($iscc) {
    Run $iscc @("/Qp", "/DAppVersion=$ver", "/DSourceDir=$dist", "/DOutDir=$Out", "/DIconFile=$proj\branding\JobsHunter.ico", "packaging\JobsHunter.iss")
    Write-Host ("Creato: {0} ({1} MB)" -f $setupPath, [math]::Round((Get-Item $setupPath).Length / 1MB, 1))
} else {
    Write-Host "Installer non costruito: Inno Setup non e' installato (e' facoltativo). Resta lo zip."
}

# ---- test di fumo ----
if (-not $NoSmoke) {
    & (Join-Path $proj "packaging\smoke_windows.ps1") -Package $zipPath
    if ($LASTEXITCODE -ne 0) { throw "Test di fumo fallito" }
}
