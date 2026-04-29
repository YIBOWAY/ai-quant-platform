$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$PidDir = Join-Path $Root "data\_runtime\pids"

foreach ($Name in @("frontend", "backend")) {
    $PidPath = Join-Path $PidDir "$Name.pid"
    if (Test-Path $PidPath) {
        $ProcessId = [int](Get-Content -Raw $PidPath)
        if (Get-Process -Id $ProcessId) {
            Stop-Process -Id $ProcessId -Force
            Write-Output "stopped_$Name=$ProcessId"
        }
        Remove-Item $PidPath -Force
    }
}
