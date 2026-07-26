param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Command
    )

    Write-Host "==> $Name"
    & $Command[0] @($Command | Select-Object -Skip 1)
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

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
$PathPython = Get-Command python -ErrorAction SilentlyContinue
if ($PathPython) {
    $PythonCandidates += $PathPython.Source
}

$PythonExe = $PythonCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $PythonExe) {
    throw "No usable Python interpreter found. Run: conda activate ai-quant"
}

$env:PYTHONPATH = (Join-Path $Root "src")

Invoke-Step "Python version" @($PythonExe, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 'Python 3.11+ required; run: conda activate ai-quant')")
Invoke-Step "Ruff" @($PythonExe, "-m", "ruff", "check", "src/quant_system", "tests")
Invoke-Step "Pytest" @($PythonExe, "-m", "pytest", "-q")
Invoke-Step "Frontend API contract" @("npm", "--prefix", "src/frontend", "run", "check:api-types")
Invoke-Step "Frontend lint" @("npm", "--prefix", "src/frontend", "run", "lint")
Invoke-Step "Frontend type-check" @("npm", "--prefix", "src/frontend", "run", "type-check")
Invoke-Step "Frontend tests" @("npm", "--prefix", "src/frontend", "run", "test")

if ($Build) {
    Invoke-Step "Frontend build" @("npm", "--prefix", "src/frontend", "run", "build")
} else {
    Write-Host "==> Frontend build skipped (pass -Build when no frontend dev server is running)"
}
