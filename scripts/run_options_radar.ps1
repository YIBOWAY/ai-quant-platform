# Windows Task Scheduler target for the Phase 13 read-only Options Radar.
# Suggested trigger: every weekday at BJT 06:30, after the US market close.
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."
$env:PYTHONPATH = "."
& D:\anaconda3\envs\ai-quant\python.exe -m quant_system.cli options daily-scan --top 100
