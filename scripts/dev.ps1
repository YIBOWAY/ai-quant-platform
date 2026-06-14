param(
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8765,
    [string]$FrontendHost = "127.0.0.1",
    [int]$FrontendPort = 3001,
    [string]$DatabaseContainer = "quantplatform-db",
    [string]$DatabaseUser = "quant",
    [string]$DatabaseName = "quantplatform",
    [string]$OpenDHost = "127.0.0.1",
    [int]$OpenDPort = 11111,
    [switch]$SkipDatabase,
    [switch]$SkipOpenDCheck
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $Root "src\frontend"
$RuntimeDir = Join-Path $Root "data\_runtime"
$PidDir = Join-Path $RuntimeDir "pids"
$LogDir = Join-Path $RuntimeDir "logs"

New-Item -ItemType Directory -Force -Path $PidDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-PortOpen {
    param([string]$HostName, [int]$Port)
    try {
        $Client = New-Object System.Net.Sockets.TcpClient
        $Async = $Client.BeginConnect($HostName, $Port, $null, $null)
        $Ready = $Async.AsyncWaitHandle.WaitOne(500)
        if ($Ready -and $Client.Connected) {
            $Client.EndConnect($Async)
            $Client.Close()
            return $true
        }
        $Client.Close()
        return $false
    } catch {
        return $false
    }
}

function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSeconds = 60)
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        try {
            $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 750
        }
    }
    throw "Service did not become ready: $Url"
}

function Start-DatabaseIfAvailable {
    if ($SkipDatabase) {
        Write-Output "database_status=skipped"
        return
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Output "database_status=docker_not_found"
        return
    }

    $Exists = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $DatabaseContainer }
    if (-not $Exists) {
        Write-Output "database_status=container_not_found:$DatabaseContainer"
        return
    }

    $Running = docker inspect -f "{{.State.Running}}" $DatabaseContainer
    if ($Running -ne "true") {
        docker start $DatabaseContainer | Out-Null
    }

    try {
        docker exec $DatabaseContainer pg_isready -U $DatabaseUser -d $DatabaseName | Out-Null
        Write-Output "database_status=ready:$DatabaseContainer"
    } catch {
        Write-Output "database_status=not_ready:$DatabaseContainer"
    }
}

if (Test-PortOpen -HostName $BackendHost -Port $BackendPort) {
    throw "Backend port $BackendHost`:$BackendPort is already in use. Run .\scripts\dev-stop.ps1 or choose another port."
}
if (Test-PortOpen -HostName $FrontendHost -Port $FrontendPort) {
    throw "Frontend port $FrontendHost`:$FrontendPort is already in use. Run .\scripts\dev-stop.ps1 or choose another port."
}

Start-DatabaseIfAvailable

if (-not $SkipOpenDCheck) {
    if (Test-PortOpen -HostName $OpenDHost -Port $OpenDPort) {
        Write-Output "opend_status=ready:$OpenDHost`:$OpenDPort"
    } else {
        Write-Output "opend_status=not_detected:$OpenDHost`:$OpenDPort"
    }
}

$PythonCandidates = @()
$CondaCommand = Get-Command conda -ErrorAction SilentlyContinue
if ($CondaCommand) {
    $CondaBase = (& conda info --base 2>$null)
    if ($CondaBase) {
        $PythonCandidates += (Join-Path $CondaBase "envs\ai-quant\python.exe")
    }
}
$PythonCandidates += "D:\anaconda3\envs\ai-quant\python.exe"
if ($env:CONDA_PREFIX) {
    $PythonCandidates += (Join-Path $env:CONDA_PREFIX "python.exe")
}
$PythonCandidates += (Get-Command python -ErrorAction Stop).Source

$PythonExe = $PythonCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

$BackendOutLog = Join-Path $LogDir "backend-api.out.log"
$BackendErrLog = Join-Path $LogDir "backend-api.err.log"
$FrontendOutLog = Join-Path $LogDir "frontend-next.out.log"
$FrontendErrLog = Join-Path $LogDir "frontend-next.err.log"

$env:QS_API_BIND_ADDRESS = $BackendHost
$env:PYTHONPATH = (Join-Path $Root "src")

$Backend = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList @(
        "-m",
        "uvicorn",
        "quant_system.api.server:create_app",
        "--factory",
        "--host",
        $BackendHost,
        "--port",
        "$BackendPort"
    ) `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $BackendOutLog `
    -RedirectStandardError $BackendErrLog `
    -PassThru

Set-Content -Path (Join-Path $PidDir "backend.pid") -Value $Backend.Id
Wait-HttpOk -Url "http://$BackendHost`:$BackendPort/api/health"

$env:NEXT_PUBLIC_QUANT_API_BASE_URL = "http://$BackendHost`:$BackendPort"
$Frontend = Start-Process `
    -FilePath "npm.cmd" `
    -ArgumentList @("run", "dev") `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $FrontendOutLog `
    -RedirectStandardError $FrontendErrLog `
    -PassThru

Set-Content -Path (Join-Path $PidDir "frontend.pid") -Value $Frontend.Id
Wait-HttpOk -Url "http://$FrontendHost`:$FrontendPort"

Write-Output "backend_url=http://$BackendHost`:$BackendPort"
Write-Output "frontend_url=http://$FrontendHost`:$FrontendPort"
Write-Output "backend_pid=$($Backend.Id)"
Write-Output "frontend_pid=$($Frontend.Id)"
Write-Output "logs=$LogDir"
