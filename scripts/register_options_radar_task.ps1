param(
    [string]$TaskName = "AIQuant Options Radar Daily Task",
    [string]$StartTime = "06:30"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$RadarScript = Join-Path $Root "scripts\run_options_radar.ps1"

if (-not (Test-Path $RadarScript)) {
    throw "Options radar scheduler target not found: $RadarScript"
}

$Action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RadarScript`""

schtasks.exe /Create `
    /TN $TaskName `
    /SC WEEKLY `
    /D MON,TUE,WED,THU,FRI `
    /ST $StartTime `
    /TR $Action `
    /F

Write-Output "task_name=$TaskName"
Write-Output "schedule=weekly:MON,TUE,WED,THU,FRI@$StartTime"
Write-Output "target=$RadarScript"
