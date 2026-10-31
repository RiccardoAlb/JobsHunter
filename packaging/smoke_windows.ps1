# Prova un pacchetto Windows GIA' costruito: scompatta lo zip in una cartella temporanea CON SPAZI, lancia JobsHunter.exe --smoke
# (server locale con dati temporanei, nessuna rete, nessuna finestra) e controlla che il codice di uscita sia 0.
# L'eseguibile e' senza console: il resoconto si legge dal file indicato con --smoke-log.
# Uso: powershell -ExecutionPolicy Bypass -File packaging\smoke_windows.ps1 -Package JobsHunter-<versione>-Windows-x64.zip
param([Parameter(Mandatory = $true)][string]$Package)
$ErrorActionPreference = "Stop"
$Package = (Resolve-Path $Package).Path
$tmp = Join-Path $env:TEMP ("jobshunter smoke " + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Package, $tmp)
    $exe = Join-Path $tmp "JobsHunter\JobsHunter.exe"
    if (-not (Test-Path $exe)) { throw "JobsHunter.exe non trovato nello zip" }
    $log = Join-Path $tmp "smoke.log"
    $p = Start-Process -FilePath $exe -ArgumentList @("--smoke", "--smoke-log", "`"$log`"") -Wait -PassThru -WindowStyle Hidden
    if (Test-Path $log) { Get-Content $log }
    if ($p.ExitCode -ne 0) { Write-Host "Test di fumo FALLITO (codice $($p.ExitCode))"; exit 1 }
    Write-Host "Test di fumo riuscito: $Package"
    exit 0
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
