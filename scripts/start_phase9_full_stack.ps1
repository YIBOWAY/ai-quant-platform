param(
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8765,
    [string]$FrontendHost = "127.0.0.1",
    [int]$FrontendPort = 3000
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
    param([string]$Url, [int]$TimeoutSeconds = 40)
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

if (Test-PortOpen -HostName $BackendHost -Port $BackendPort) {
    throw "Backend port $BackendHost`:$BackendPort is already in use."
}
if (Test-PortOpen -HostName $FrontendHost -Port $FrontendPort) {
    throw "Frontend port $FrontendHost`:$FrontendPort is already in use."
}

$PythonExe = Join-Path $env:CONDA_PREFIX "python.exe"
if (-not (Test-Path $PythonExe)) {
    $Command = Get-Command python -ErrorAction Stop
    $PythonExe = $Command.Source
}

$BackendOutLog = Join-Path $LogDir "backend-api.out.log"
$BackendErrLog = Join-Path $LogDir "backend-api.err.log"
$FrontendOutLog = Join-Path $LogDir "frontend-next.out.log"
$FrontendErrLog = Join-Path $LogDir "frontend-next.err.log"

$env:QS_API_BIND_ADDRESS = $BackendHost

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
    -ArgumentList @("run", "dev", "--", "-H", $FrontendHost, "-p", "$FrontendPort") `
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
