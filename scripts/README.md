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

## Agent v0.2.2 Release Hardening

These owner-run entrypoints emit machine-readable evidence into a unique,
owner-only output directory. They fail closed and do not authorize public write
or trading.

| Script | Purpose |
| --- | --- |
| `verify_backend_non_postgres.sh` | Run mandatory Gate 2 in a fresh Python 3.11 environment from committed `uv.lock`: frozen, non-editable install followed by the complete non-PostgreSQL/non-provider backend suite with fail-closed JUnit and skip validation. |
| `backend_non_postgres_gate.py` | Internal helper used only by `verify_backend_non_postgres.sh` to bind tool identities, construct the fresh allowlisted environment, partition the exact macOS sandbox-sensitive tests, and seal Gate 2 results; it is not an operator entrypoint. |
| `verify_python_static.sh` | Run Gate 4's exact repository-defined Ruff surface with the fresh, non-editable Python environment sealed by the successful Gate 2 receipt. |
| `python_static_gate.py` | Internal helper used only by `verify_python_static.sh` to bind the Gate 2 environment, repository and tool identities, deny network access, run Ruff, and seal canonical evidence; it is not an operator entrypoint. |
| `verify_agent_v02_focused_safety.sh` | Run the fixed, repository-authoritative Agent v0.2 focused-safety selector with a release-local Python and an external one-shot basetemp. |
| `verify_agent_v02_postgres_suite.sh` | Create an isolated loopback PostgreSQL cluster, run the authoritative PostgreSQL suite, prove suite-owned roles are removed, and destroy the cluster. |
| `verify_agent_v02_backup_restore.sh` | Back up and restore the full authoritative PostgreSQL state into an independently created destination cluster, then compare schema, role, and data facts. |
| `verify_agent_v02_noneditable_upgrade.sh` | Exercise baseline-to-current non-editable installation in isolated Python environments and reject source-tree import leakage. |
| `verify_agent_v02_zero_effect.sh` | Run the fixed-identity §9.1 blocked paper-replay proof with a durable pre-route claim, exact-byte replay, provider tripwires, and zero effect counters. |
| `restart_agent_v02_stack.sh` | Build the current clean frontend HEAD, bind the complete `.next` digest to its Git commit/tree, restart only backend/frontend, and verify provider-free `/api/settings` plus `/api/hermes/gateway` readiness while the connector remains `reconcile_only`. |

### Gate 2: complete non-PostgreSQL backend suite

Run Gate 2 only from the exact clean final Platform checkout. The evidence
directory must be a canonical absolute path outside that checkout and must
either not exist or be empty, owner-only mode `700`; its existing parent must
be owned by the invoking user and not group/world writable. Bind the final
commit explicitly. The runner also requires branch
`codex/agent-v0-2-release` and
publication remote
`github=https://github.com/YIBOWAY/ai-quant-platform.git`; it rejects a
different identity or dirty checkout before installing:

```bash
FINAL_COMMIT=<exact-final-commit>
scripts/verify_backend_non_postgres.sh \
  --output-dir /absolute/private/path/platform-backend-non-postgres \
  --expected-commit "$FINAL_COMMIT"
```

The authoritative suite expression is
`not pg and not futu_opend and not provider and not network`, over the complete
`tests` selector with strict markers. Repository authority currently declares
zero expected skips; zero collection, any undeclared skip, any failed/error
testcase, a non-zero pytest exit, malformed/count-drifted JUnit, or repository
identity drift fails the gate. The receipt records the commit/tree/branch/URL,
exact argv and allowlisted safety environment, Python and `quant_system` import
identity, `uv` and dependency inventory, `pyproject.toml`/`uv.lock` digests,
installer exit/logs, pytest/JUnit counts, and clean identity before and after.
It does not authorize public write or trading.

Clean identity covers the entire tracked tree, not only the runner authority
files. The runner rejects every `assume-unchanged` or `skip-worktree` index
flag and every unmerged entry, then independently checks index versus `HEAD`
and worktree versus index. The receipt records the tracked-path count, flag
listing digest, zero hidden/conflict counts, and both diff verdicts.

One unique runner-owned runtime root is created under the exact checkout's
ignored `.tmp/` area. Its path is bound to the commit and evidence directory
and must not pre-exist. The fresh non-editable environment, uv cache, HOME/TMP,
pytest basetemp/pycache, and sandbox data all stay below that transient root.
The runner never recursively removes it; the receipt records the exact root so
the outer collector can clean only that root after sealing.

The external owner-only evidence directory contains files only: mode-`600`
plain logs, the mode-`600` JUnit document, and the canonical mode-`600`
receipt. Transient lock files, symlinks, hardlinks, FIFOs, caches, and test data
must never be placed there. The known JSON import probe is parsed strictly in
memory and embedded canonically in the receipt; its newline-terminated raw
stdout is not persisted as a JSON artifact.

The test process runs under the macOS deny-network sandbox after a fail-closed
network-denial probe. Dependency installation is the only phase allowed to
contact the package index. The receipt records every allowlisted install/test
environment name and value; no inherited database URL, Futu/OpenD endpoint,
provider credential, live flag, or pytest/Python injection variable reaches
the test process.

`--describe` prints the machine-readable repository contract and `--self-test`
exercises the result validator's pass/fail cases. Both are diagnostics, not a
Gate 2 pass.

### Gate 4: repository-defined Python static checks

Gate 4 consumes the successful canonical Gate 2 receipt and reuses that
receipt's exact fresh, non-editable Python 3.11 environment under `.tmp/`.
Run it only from the same clean final commit:

```bash
FINAL_COMMIT=<exact-final-commit>
scripts/verify_python_static.sh \
  --gate2-receipt /absolute/private/gate2/backend-non-postgres-receipt.json \
  --output-dir /absolute/private/path/platform-python-static \
  --expected-commit "$FINAL_COMMIT"
```

The runner binds the commit, tree, branch, hidden-index audit, publication
remote, `pyproject.toml`, `uv.lock`, Python/import/direct-URL identity, and Ruff
executable/version. It executes the exact Ruff surface declared by
`scripts/verify.sh` under a deny-network sandbox and an allowlist without
provider or database configuration. Stdout and stderr remain separate
mode-`600` artifacts; the final receipt is sorted, compact canonical UTF-8.

## macOS Local Services

| Script | Purpose |
| --- | --- |
| `local_mac_stack.sh` | Normal Mac operator entrypoint: `start|restart|build|stop|status|logs`. Starts Docker PostgreSQL, builds the production frontend, drains the prior Hermes socket generation, installs/reloads Hermes + Hermes OAuth proxy + backend + frontend + connector + factor-automation + D-34 + asia-radar-refresh LaunchAgents, waits for health, and rejects transient AI-tool executables. |
| `run_quant_backend.sh` | Agent v0.2 LaunchAgent target for the localhost FastAPI backend on `127.0.0.1:8765`; loads the owner-only runtime env, rejects startup migration, and serves release-worktree source. |
| `run_quant_frontend.sh` | Agent v0.2 LaunchAgent target for the built Next.js frontend on `127.0.0.1:3001`; requires an owner-only env that explicitly enables Hermes Chat, serves this worktree's `.next`, and can reuse main-repo `node_modules`. |
| `install_agent_v02_stack_launchagents.sh` | Validate, render, and replay-safely install only the Agent v0.2 backend/frontend LaunchAgents. It never installs strategy schedulers. |
| `uninstall_agent_v02_stack_launchagents.sh` | Boot out and remove only the Agent v0.2 backend/frontend LaunchAgents. |
| `run_hermes_oauth_proxy.sh` | Stable local xAI OAuth proxy target on `127.0.0.1:8645`; reuses Hermes login and rejects transient AI-tool binaries. |
| `install_hermes_oauth_proxy_launchagent.sh` | Check the Hermes xAI OAuth session and replay-safely install the persistent `com.aiquant.hermes-oauth-proxy` user LaunchAgent. |
| `uninstall_hermes_oauth_proxy_launchagent.sh` | Boot out and remove only the Hermes OAuth proxy LaunchAgent. |
| `run_agent_v02_connector.sh` | Agent v0.2 connector target; requires a regular, non-symlink, exact-mode-`600` env, rejects startup migration, binds imports to release source, and accepts only `QS_AGENT_V02_CONNECTOR_MODE=reconcile_only` or `supervised_dispatch`. The installed safety posture sets `QS_AGENT_V02_CONNECTOR_MODE=reconcile_only`; the legacy absent-env fallback remains `supervised_dispatch` only for frozen compatibility. Its `--check` is provider/network/database-free. |
| `install_agent_v02_connector_launchagent.sh` | Run the connector `--check` before any launchd mutation, then render and replay-safely install the connector LaunchAgent in the mode selected by its owner-only env. |
| `uninstall_agent_v02_connector_launchagent.sh` | Boot out and remove only the Agent v0.2 connector LaunchAgent. |
| `run_factor_automation_driver.sh` | Five-minute D-33 target and exact installed enqueue bridge. Loads the owner-only backend env, rejects transient HQA runtimes, defaults to one fail-closed `paper_only` queue/maintenance cycle, and accepts only `enqueue --request-file <absolute path>` as an explicit operation. |
| `install_factor_automation_launchagent.sh` | Check and replay-safely install `com.aiquant.factor-automation`; the driver remains disabled unless both HQA and Platform Flag pairs are true. |
| `run_d34_worker.sh` | Five-minute D-34 target. Loads the owner backend env, stays idle unless `QS_D34_WORKER_ENABLED=true`, rejects startup migration and processes at most one already-queued owner research job plus canary maintenance. Enabled `--check` requires the formal safety authorities plus real versions/Qlib/LLM JSON/Futu/Docker preflight; disabled `--check` remains import-only. |
| `install_d34_worker_launchagent.sh` | Run the D-34 check and replay-safely install `com.aiquant.d34-worker`; installing it does not enable D-34 or apply migration 030–032, while an enabled install fails before launchd mutation unless full preflight succeeds. |
| `uninstall_d34_worker_launchagent.sh` | Boot out and remove only the D-34 user LaunchAgent; it does not alter Mandates, Artifact Registry rows or held paper positions. |
| `run_asia_radar_refresh.sh` | Daily Asia Radar target. Warms the 12-ETF Futu bar cache and persists the day's read-only overview snapshot; fails closed when OpenD is unavailable. |
| `install_asia_radar_refresh_launchagent.sh` | Render and replay-safely install `com.aiquant.asia-radar-refresh` (17:05 local, calendar interval); never places orders and never substitutes sample data. |
| `run_brief_auto_archive.sh` | Daily brief auto-archive target. Runs `brief auto-archive` against the local backend to upsert today's `brief_snapshot_v1` issue; fails closed (nothing written, non-zero exit) when a blocking source or the archive database is down. |
| `install_brief_auto_archive_launchagent.sh` | Render and replay-safely install `com.aiquant.brief-auto-archive` (17:20 local, after the radar refresh). The repo ships the files but never loads them for you; read-only facts in, brief archive rows out — no orders, no kill_switch/live_trading/Gate changes. |
| `run_paper_strategy_sleeves.sh` | LaunchAgent/CLI wrapper for one-shot Paper Strategy Sleeves ops commands (`ops-status`, `generate-due-signals`, `execute-due`). |
| `install_paper_strategy_sleeves_launchagent.sh` | Render and bootstrap user-level macOS LaunchAgents under `~/Library/LaunchAgents/`; does not use sudo. |
| `uninstall_paper_strategy_sleeves_launchagent.sh` | Boot out and remove the rendered user-level LaunchAgents. |

For everyday Mac use, run `bash scripts/local_mac_stack.sh start`; do not keep
services alive by leaving an AI-tool terminal open. See
`docs/runbooks/agent-v0-2-local-stack.md` for the stack,
`/Users/sunyibo/programs/Hermes-quant-agent/docs/runbooks/full-automation-paper.md`
for D-33, and
`docs/execution/paper_strategy_sleeves_launchd.md` for the separate paper
schedulers. The backend/frontend jobs are long-running local services;
legacy strategy-sleeve jobs are one-shot paper commands.

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
