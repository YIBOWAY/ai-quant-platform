param(
    [switch]$StopDatabase,
    [string]$DatabaseContainer = "quantplatform-db"
)

$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$PidDir = Join-Path $Root "data\_runtime\pids"

function Stop-ProcessTree {
    param([int]$RootProcessId)

    $Children = Get-CimInstance Win32_Process |
        Where-Object { $_.ParentProcessId -eq $RootProcessId }
    foreach ($Child in $Children) {
        Stop-ProcessTree -RootProcessId $Child.ProcessId
    }
    if (Get-Process -Id $RootProcessId) {
        Stop-Process -Id $RootProcessId -Force
    }
}

foreach ($Name in @("frontend", "backend")) {
    $PidPath = Join-Path $PidDir "$Name.pid"
    if (Test-Path $PidPath) {
        $ProcessId = [int](Get-Content -Raw $PidPath)
        if (Get-Process -Id $ProcessId) {
            Stop-ProcessTree -RootProcessId $ProcessId
            Write-Output "stopped_$Name=$ProcessId"
        }
        Remove-Item $PidPath -Force
    }
}

if ($StopDatabase -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    $Exists = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $DatabaseContainer }
    if ($Exists) {
        docker stop $DatabaseContainer | Out-Null
        Write-Output "stopped_database=$DatabaseContainer"
    }
}
