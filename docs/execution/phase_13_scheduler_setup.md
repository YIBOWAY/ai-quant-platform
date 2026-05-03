# Phase 13 Windows Scheduler Setup

Use Windows Task Scheduler. Do not write registry keys or auto-start entries.

## Trigger

- Frequency: every weekday
- Time: BJT 06:30
- Rationale: after the US market close

## Action

Program:

```text
powershell.exe
```

Arguments:

```text
-ExecutionPolicy Bypass -File E:\programs\AI-assisted_quant_research_and_paper-trading_platform\scripts\run_options_radar.ps1
```

## Conditions

- Run only when network is available.
- Keep OpenD running and logged in before the task fires.

## Script

```powershell
scripts/run_options_radar.ps1
```

The script uses:

```text
D:\anaconda3\envs\ai-quant\python.exe
```

and calls:

```text
python -m quant_system.cli options daily-scan --top 100
```

