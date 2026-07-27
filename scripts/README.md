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

## macOS Local Services

| Script | Purpose |
| --- | --- |
| `run_quant_backend.sh` | Agent v0.2 LaunchAgent target for the localhost FastAPI backend on `127.0.0.1:8765`; loads the owner-only runtime env, rejects startup migration, and serves release-worktree source. |
| `run_quant_frontend.sh` | Agent v0.2 LaunchAgent target for the built Next.js frontend on `127.0.0.1:3001`; requires an owner-only env that explicitly enables Hermes Chat, serves this worktree's `.next`, and can reuse main-repo `node_modules`. |
| `install_agent_v02_stack_launchagents.sh` | Validate, render, and replay-safely install only the Agent v0.2 backend/frontend LaunchAgents. It never installs strategy schedulers. |
| `uninstall_agent_v02_stack_launchagents.sh` | Boot out and remove only the Agent v0.2 backend/frontend LaunchAgents. |
| `run_agent_v02_connector.sh` | Agent v0.2 connector target; requires a regular, non-symlink, exact-mode-`600` env, rejects startup migration, binds imports to release source, and accepts only `QS_AGENT_V02_CONNECTOR_MODE=reconcile_only` or `supervised_dispatch`. The installed safety posture sets `QS_AGENT_V02_CONNECTOR_MODE=reconcile_only`; the legacy absent-env fallback remains `supervised_dispatch` only for frozen compatibility. Its `--check` is provider/network/database-free. |
| `install_agent_v02_connector_launchagent.sh` | Run the connector `--check` before any launchd mutation, then render and replay-safely install the connector LaunchAgent in the mode selected by its owner-only env. |
| `uninstall_agent_v02_connector_launchagent.sh` | Boot out and remove only the Agent v0.2 connector LaunchAgent. |
| `run_paper_strategy_sleeves.sh` | LaunchAgent/CLI wrapper for one-shot Paper Strategy Sleeves ops commands (`ops-status`, `generate-due-signals`, `execute-due`). |
| `install_paper_strategy_sleeves_launchagent.sh` | Render and bootstrap user-level macOS LaunchAgents under `~/Library/LaunchAgents/`; does not use sudo. |
| `uninstall_paper_strategy_sleeves_launchagent.sh` | Boot out and remove the rendered user-level LaunchAgents. |

See `docs/runbooks/agent-v0-2-local-stack.md` for the dedicated Web stack and
`docs/execution/paper_strategy_sleeves_launchd.md` for the separate paper
schedulers. The backend/frontend jobs are long-running local services;
strategy-sleeve jobs are one-shot paper commands.

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
| `sql/002_ai_news_cache.sql` | Optional PostgreSQL AI HOT item cache and fetch-audit migration for read-only `/ai-news` stale fallback. |
| `sql/003_app_users_brief_ai_reports.sql` | Optional PostgreSQL root user, brief issue/snapshot/source, and AI daily report tables. Brief archive APIs and AI daily fallback are wired. |
| `sql/004_paper_account_tables.sql` | Optional PostgreSQL paper account mirror tables for explicit `account.json` backfill and `QS_PAPER_ACCOUNT_DB_MODE=mirror` API/CLI dual-write. File storage remains canonical until the later DB-canonical slice. |
