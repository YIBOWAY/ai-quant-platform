# Scripts

This directory contains local operator scripts for the paper-only research
platform. Prefer the current entrypoints below before using older phase-named
helpers.

## Daily Entry Points

| Script | Purpose |
| --- | --- |
| `dev.ps1` | Start the local backend and frontend on the canonical ports `8765` and `3001`, with optional Docker/OpenD probes. |
| `dev-stop.ps1` | Stop processes recorded by `dev.ps1` under `data/_runtime/pids/`. |
| `verify.ps1` | Run the standard local verification suite on Windows. Skips frontend build unless `-Build` is passed. |
| `verify.sh` | Unix shell equivalent for the standard verification suite. |

## Data And Maintenance

| Script | Purpose |
| --- | --- |
| `backup_api_runs.py` | Zip `data/api_runs/` research and paper-account artifacts with a manifest, excluding secrets, DuckDB files, and locks. |
| `export_openapi.py` | Dump the FastAPI OpenAPI schema to stdout; the frontend `npm run generate:api-types` pipeline consumes it to regenerate `src/frontend/lib/api.generated.ts`. |
| `cleanup_api_run_duckdb.py` | Report or remove obsolete per-run DuckDB copies under `data/api_runs/`; does not touch ingest/cache DuckDB files. |
| `check_api_keys.py` | Local-only smoke test for configured read-only provider keys. It does not print secret values. |
| `verify_futu_connection.py` | Read-only Futu OpenD connectivity check. |
| `verify_tiingo_adjustment.py` | Operator / external gate: with a real Tiingo token, validate that a known split window is adjusted (no split-sized discontinuity). Prints SKIP and exits 0 without a token; never part of pytest. |

## Options Radar Operations

| Script | Purpose |
| --- | --- |
| `refresh_options_universe.py` | Refresh the local options universe cache. |
| `refresh_earnings_calendar.py` | Refresh the local earnings calendar cache. |
| `refresh_vix_history.py` | Refresh VIX/VIX3M history used by options radar inputs. |
| `run_options_radar.ps1` | Windows Task Scheduler target for the read-only daily options radar scan. |
| `register_options_radar_task.ps1` | Register the Windows scheduled task that calls `run_options_radar.ps1`. |

## Legacy Or Historical Helpers

| Script | Purpose |
| --- | --- |
| `start_phase9_full_stack.ps1` | Legacy compatibility wrapper for the old Phase 9 full-stack startup path. Prefer `dev.ps1`. |
| `stop_phase9_full_stack.ps1` | Legacy compatibility wrapper for the old Phase 9 stop path. Prefer `dev-stop.ps1`. |
| `run_spy_qqq_phase5_full_check.py` | Historical Phase 0-5 SPY/QQQ validation harness. Keep for reproducibility, not daily operation. |

## SQL

| Path | Purpose |
| --- | --- |
| `sql/001_runs_index.sql` | Optional PostgreSQL run-index migration. The file-based `data/api_runs/` artifacts remain the source of truth. |
