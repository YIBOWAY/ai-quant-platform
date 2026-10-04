# Scripts

This directory contains local operator scripts for the paper-only research
platform. Prefer the current entrypoints below before using older phase-named
helpers.

## Daily Entry Points

The connector's absent-env fallback remains `supervised_dispatch` for frozen
compatibility only. Set its mode explicitly; use
`QS_AGENT_V02_CONNECTOR_MODE=reconcile_only` for no-dispatch maintenance.

| Script | Purpose |
| --- | --- |
| `dev.ps1` | Start the local backend and frontend on the canonical ports `8765` and `3001`, with optional Docker/OpenD probes. |
| `dev-stop.ps1` | Stop processes recorded by `dev.ps1` under `data/_runtime/pids/`. |
| `verify.ps1` | Run the standard local verification suite on Windows. Skips frontend build unless `-Build` is passed. |
| `verify.sh` | Unix shell equivalent for the standard verification suite. |
| `audit_study_return.py` | Reconcile a saved study's return metrics against its stored calculation evidence. |
| `random_top5_null.py` | Local research diagnostic: compare random monthly Top-5 selections using saved inputs; not the product backtest engine or a paper-trading task. |
| `review_admission_activation.py` | Close all current-code parallel intake jobs, run fixed source/data/consumer checks, retain changed/unknown decisions, and install only the bounded static-24 activation state when complete; `--review-only` never installs state. No policy, existing protocol, engine, trial, account or sleeve writes. |
| `refresh_market_assessments.py` | Refresh saved US/Asia market assessments through the configured providers and model; an explicit operator action. |
| `refresh_security_catalog.py` | Refresh the local security reference catalog; this is directory data, not historical prices. |
| `check_futu_history_quota.py` | Read-only probe of the local OpenD history-kline quota; prints one JSON line, optionally appends it to `futu_quota_ledger.jsonl` under `QS_DATA_DIR` (`--record`) and fails closed below a floor (`--check-floor N`). Never requests bars. |
| `install_futu_quota_probe_launchagent.sh` | Render and replay-safely install the `com.aiquant.futu-quota-probe` user LaunchAgent that runs `check_futu_history_quota.py --record --check-floor` on a calendar interval; read-only quota probe, no bar requests. |

## Phase2 research evidence (2026-09-20)

These are research and audit tools, not trade or paper-cycle commands. Use fresh
output directories, preserve source manifests and do not overwrite frozen studies.

| Script | Purpose |
| --- | --- |
| `collect_phase2_futu_panel.py` | Read-only, quota-bounded collection into a new per-symbol Futu QFQ panel with metadata; no fallback or frozen-history replacement. |
| `compare_phase2_sources.py` | Offline comparison of explicitly selected Futu/Tiingo files; reports observed price/volume differences, not universal equivalence. |
| `probe_tiingo_backfill.py` | Quota-bounded missing-symbol backfill probe; transient errors are not permanent no-data decisions. |
| `prepare_phase2_wide_inputs.py` | Assemble issuer/ticker-period-bound research inputs and full SHA manifest; unresolved identities stay excluded. |
| `prepare_current_phase2_inputs.py` | Freeze an explicitly new 24-stock-plus-benchmark window from existing real Futu archives; preserves original inputs, prewarm and actual trading-calendar coverage. |
| `run_current_phase2_controls.py` | Run 500 fixed-seed random controls through the real backtest engine on that frozen new window; keeps every curve/order/cost artifact, not an extension of older curves or a funding qualification by itself. |
| `current_phase2_owner_example.py` | Create a fresh isolated owner with exact saved prices and native intake; optional fixed parallel-stage review can precede another native job. Preserves original protocols/trials, keeps `auto_enable=false`, and never uses the formal queue, provider or account. |
| `wide_universe_scorecard.py` | Audit or score the frozen 27-object research manifest; formal input acceptance does not grant admission or capital. |
| `recompute_phase2_evidence.py` | Re-output saved studies/sleeves and run true-engine random controls into separate evidence; no canonical trial or paper-ledger rewriting. |
| `recompute_phase2_full_gate_control.py` | Recheck the frozen 500 real-engine curves through all statistical gate components and optional isolated consumer tests; no new backtests/trials or production qualification switch. |
| `compare_phase2_historical_admission.py` | Compare archived validations under a separately frozen current research context; preserves original decisions and reports missing historical authority/peer evidence instead of rewriting history. |
| `calibrate_admission_semantics.py` | Preregistered artificial bidirectional minimum-quality calibration with fixed objects, effects, seeds and intervals; exact engine cost examples, immutable per-cell results and explicit resume diagnosis. No provider, formal ledger or money writes; not market alpha or whole funding-consumer Monte Carlo. |
| `qualify_admission.py` | Run fixed review/data/consumer checks from real bound inputs; `--register` stores their recomputable result. A supplied `passed` document is not qualification, and this command never changes the catalog or funding switch. |
| `exploration_sandbox_runner.py` | Internal container-only factor runner, not an operator host-execution entrypoint. |
| `run_phase2_exploration_example.py` | Real-price bounded Docker example through behavior/reference checks to a format-valid, unsubmitted research payload. |
| `exploration_admission_example.py` | Replay that exact frozen example through an isolated intake and actual Platform/Qlib engines using saved real prices; records rejection as well as success, never submits to the formal queue or allocates capital. |
| `phase2_public_price_pilot.py` | Independently frozen monthly price-method study on existing PIT inputs; signals and future labels separate, missing group returns stay unknown; not OSAP financial-factor replication. |
| `import_wide_scorecard.py` | Explicit import of a closed 11-file SHA-bound completed run via `--run-dir`, `--expected-output-manifest-sha256`, `--scorecard-store`; never replaces a run in place. |
| `import_study_active_metrics.py` | Verify derived active metrics by recomputing statistics from each bound saved curve, then import a separate display sidecar; no provider/strategy replay/trial mutation, and GET stays read-only. |

## Phase3 research evidence (2026-09-26)

These are frozen, preregistered research drivers over saved real inputs. They
own no candidate, intake, account or funding path and never recompute archived
component inputs.

| Script | Purpose |
| --- | --- |
| `phase3_etf_research.py` | Finite preregistered ETF research over supplied real snapshots only; the adapter owns targets while the Platform engine owns orders/fills/fees/NAV. No provider calls, production storage or parameter search. |
| `phase3_portfolio_research.py` | Frozen T3.4 offline portfolio experiment (fixed allocation policies × cost tiers with removal/reference replays); default is read-only preflight. Component signal/return inputs are the original archived experiments, never recomputed. |
| `rebuild_factor_contributions.py` | Rebuild immutable original-v4 factor contribution panels with exact reconciliation; does not rerun scorecards or compute SEs. |
| `sec_pit_pilot.py` | Bounded AAPL/NVDA SEC submissions and companyfacts capture with a privately supplied User-Agent; freezes four requests, retains original JSON and incomplete historical as-of views. Research data only, no provider substitution, factors, backtests or funding. |

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
| `restart_agent_v02_stack.sh` | Release-specific backend/frontend restart helper. It leaves the separately running connector mode unchanged and verifies provider-free `/api/settings` plus `/api/hermes/gateway` readiness. Use `local_mac_stack.sh` for normal daily operation. |

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
| `local_mac_stack.sh` | Normal Mac operator entrypoint: `start|restart|build|stop|status|logs`. Starts Docker PostgreSQL, builds the production frontend, drains the prior Hermes socket generation, installs/reloads Hermes + Hermes OAuth proxy + backend + frontend + connector + asia-radar-refresh LaunchAgents, waits for health, and rejects transient AI-tool executables. |
| `run_quant_backend.sh` | Agent v0.2 LaunchAgent target for the localhost FastAPI backend on `127.0.0.1:8765`; loads the owner-only runtime env, rejects startup migration, and serves release-worktree source. |
| `run_quant_frontend.sh` | Agent v0.2 LaunchAgent target for the built Next.js frontend on `127.0.0.1:3001`; requires an owner-only env that explicitly enables Hermes Chat, serves this worktree's `.next`, and can reuse main-repo `node_modules`. |
| `install_agent_v02_stack_launchagents.sh` | Validate, render, and replay-safely install only the Agent v0.2 backend/frontend LaunchAgents. It never installs strategy schedulers. |
| `uninstall_agent_v02_stack_launchagents.sh` | Boot out and remove only the Agent v0.2 backend/frontend LaunchAgents. |
| `run_hermes_oauth_proxy.sh` | Stable local xAI OAuth proxy target on `127.0.0.1:8645`; reuses Hermes login and rejects transient AI-tool binaries. |
| `install_hermes_oauth_proxy_launchagent.sh` | Check the Hermes xAI OAuth session and replay-safely install the persistent `com.aiquant.hermes-oauth-proxy` user LaunchAgent. |
| `uninstall_hermes_oauth_proxy_launchagent.sh` | Boot out and remove only the Hermes OAuth proxy LaunchAgent. |
| `run_agent_v02_connector.sh` | Agent v0.2 connector target; requires a regular, non-symlink, exact-mode-`600` env, rejects startup migration, binds imports to release source, and accepts only `QS_AGENT_V02_CONNECTOR_MODE=reconcile_only` or `supervised_dispatch`. The current owner-only `local_trust` deployment sets `supervised_dispatch` explicitly; `reconcile_only` is the explicit no-dispatch maintenance posture. The absent-env `supervised_dispatch` fallback is frozen compatibility only and must not replace an explicit installed value. Its `--check` is provider/network/database-free. |
| `install_agent_v02_connector_launchagent.sh` | Run the connector `--check` before any launchd mutation, then render and replay-safely install the connector LaunchAgent in the mode selected by its owner-only env. |
| `uninstall_agent_v02_connector_launchagent.sh` | Boot out and remove only the Agent v0.2 connector LaunchAgent. |
| `run_d34_research_worker.sh` | Research-only worker target for the fixed `local-paper-research-v1` resource envelope. Loads the owner backend env, forbids startup migration, projects terminal receipts, and leases at most one exact queued job for 7200 seconds. Model/HQA/Futu/Docker configuration is evaluated only after lease so failure is bound to that job. It constructs no paper account/sleeve/price service and never calls canary or paper-cycle code. |
| `install_d34_research_worker_launchagent.sh` | Owner-run installer for the separately installed current `com.aiquant.d34-research-worker`. It boots out and confirms absence of retired `com.aiquant.d34-worker` and `com.aiquant.factor-automation` labels before replay-safe install; `local_mac_stack.sh` does not own this job. |
| `run_asia_radar_refresh.sh` | Daily Asia Radar target. Warms the 12-ETF Futu bar cache and persists the day's read-only overview snapshot; fails closed when OpenD is unavailable. |
| `install_asia_radar_refresh_launchagent.sh` | Render and replay-safely install `com.aiquant.asia-radar-refresh` (17:05 local, calendar interval); never places orders and never substitutes sample data. |
| `run_brief_auto_archive.sh` | Daily brief auto-archive target. Runs `brief auto-archive` against the local backend to upsert today's `brief_snapshot_v1` issue; fails closed (nothing written, non-zero exit) when a blocking source or the archive database is down. |
| `install_brief_auto_archive_launchagent.sh` | Render and replay-safely install `com.aiquant.brief-auto-archive` (17:20 local, after the radar refresh). The repo ships the files but never loads them for you; read-only facts in, brief archive rows out — no orders, no kill_switch/live_trading/Gate changes. |
| `run_paper_strategy_sleeves.sh` | LaunchAgent/CLI wrapper for one-shot Paper Strategy Sleeves ops commands (`ops-status`, `generate-due-signals`, `execute-due`). |
| `install_paper_strategy_sleeves_launchagent.sh` | Render and bootstrap user-level macOS LaunchAgents under `~/Library/LaunchAgents/`; does not use sudo. |
| `uninstall_paper_strategy_sleeves_launchagent.sh` | Boot out and remove the rendered user-level LaunchAgents. |

For everyday Mac use, run `bash scripts/local_mac_stack.sh start`; do not keep
services alive by leaving an AI-tool terminal open. See
`docs/runbooks/agent-v0-2-local-stack.md` for the stack and
`docs/execution/paper_strategy_sleeves_launchd.md` for the legacy/optional
generic paper-sleeve jobs. The backend/frontend jobs are long-running local
services; formal hung-sleeve observation uses `com.aiquant.d34-paper-cycle`,
not those generic templates.

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
| `run_options_radar.ps1` | Legacy Windows Task Scheduler target for the pre-v3 options radar contract. It is retained for reproducibility and is not a canonical current scheduler. |
| `register_options_radar_task.ps1` | Register the legacy Windows task above. Do not use it to mirror or supplement the current Hermes cron. |

On the current macOS deployment, HQA owns Hermes cron `hqa-options-collect`
(`0 22 * * 1-6`, `Asia/Shanghai`) and calls the same Platform `options
daily-task` used by the page's manual refresh. The operator contract is in
`/Users/sunyibo/programs/Hermes-quant-agent/docs/runbooks/options-recommendations.md`;
the Platform user contract is in
[`docs/guides/options-recommendations.md`](../docs/guides/options-recommendations.md).
Do not load a second LaunchAgent or Windows task alongside that cron.

## Paper Cycle And Isolation Preview

| Script | Purpose |
| --- | --- |
| `run_d34_paper_cycle.sh` | Current observation-day-only driver behind loaded `com.aiquant.d34-paper-cycle`: the digest-gated cycle for already-hung sleeves. It deliberately ignores `QS_D34_WORKER_ENABLED` and never runs the research factory. Do not invoke it manually to manufacture an observation day. |
| `coo_unify_preview.sh` | Start/stop the isolated coo-unify preview stack; never binds `:3001`/`:8765` and never uses the live `quantplatform` database. |
| `coo_unify_d34_worker_once.sh` | Run one isolation D-34 cycle against `quantplatform_coo`; never uses the live LaunchAgent. |
| `coo_unify_preview_seed.py` | Seed one hung paper sleeve fill under `QS_DATA_DIR` for the isolated preview; does not touch live `api_runs` or `quantplatform`. |
| `coo_unify_seed_paper_authority.py` | Mirror the isolation file paper account into `quantplatform_coo` only. |

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
| `sql/004_paper_account_tables.sql` | Historical paper-account schema foundation used by mirror and canonical repositories. The current local deployment is PostgreSQL `canonical`; this migration file is not an instruction to switch back to file authority or replay migrations. |
