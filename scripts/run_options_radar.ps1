# Windows Task Scheduler target for the Phase 13 read-only Options Radar.
# Suggested trigger: every weekday at BJT 06:30, after the US market close.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "data\_runtime\logs"
$LogPath = Join-Path $LogDir "options-radar.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$PythonCandidates = @()
$CondaCommand = Get-Command conda -ErrorAction SilentlyContinue
if ($CondaCommand) {
    $CondaBase = (& conda info --base 2>$null)
    if ($CondaBase) {
        $PythonCandidates += (Join-Path $CondaBase "envs\ai-quant\python.exe")
    }
}
if ($env:CONDA_PREFIX) {
    $PythonCandidates += (Join-Path $env:CONDA_PREFIX "python.exe")
}
$PythonCandidates += (Get-Command python -ErrorAction Stop).Source

$PythonExe = $PythonCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $PythonExe) {
    throw "No usable Python interpreter found for options radar scan."
}

Set-Location $Root
$env:PYTHONPATH = (Join-Path $Root "src")

& $PythonExe -m quant_system.cli options daily-scan --top 100 2>&1 |
    Tee-Object -FilePath $LogPath -Append
