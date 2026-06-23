# AGENTS.md

This file is for AI agents working in this repository. Keep user-facing replies
plain and concise. Do the technical work rigorously, verify before reporting,
and avoid claiming completion without running the relevant checks.
回答问题时需避免过分的夸赞。请记住，你的回答不一定是对的，我的判断也不一定是对的。对待所有问题都要反复推敲，优先保证准确性，必要时你可以主动向我索要补充信息或证据。回答时保持结构化输出，条理清晰。

## Project Structure

```text
src/quant_system/
  api/                    Local FastAPI API and route modules.
  backtest/               Equity backtest engine and reports.
  config/                 Settings, paths, safety flags, provider config.
  data/                   Equity market data providers and schemas.
  execution/              Paper account (persistent), paper trading replay,
                          order manager, paper broker, price source.
  experiments/            Experiment configs, storage, summaries.
  factors/                Factor definitions, registry, pipeline.
  options/                Futu read-only options research modules.
  prediction_market/      Read-only Polymarket / prediction market research.
  risk/                   Risk limits and checks.
  storage/                DuckDB options cache + optional PostgreSQL run index.
  strategies/             Strategy metadata registry (catalog entries).

src/frontend/
  app/                    Next.js routes.
  components/             Shared UI and form components.
  lib/                    Frontend API client and utilities.
  tests/e2e/              Playwright smoke tests.

docs/
  architecture/           Phase architecture docs.
  delivery/               Phase delivery and validation notes.
  execution/              Runbooks and operational steps.
  guides/                 Current user-facing workflow guides.
  learning/               Beginner-friendly learning docs.
  futu/                   Futu read-only market data docs.
  options/                Options screener / radar docs.
  polymarket/             Prediction market docs.

tests/                    Python unit and API tests.
scripts/                  Local verification and refresh scripts.
scripts/sql/              Plain SQL migrations for the optional run index.
data/                     Local cache, fixtures, generated research outputs.
```

## Backtest Strategy Registry

Backtest-engine strategies are dispatched by `strategy_id` in
`src/quant_system/backtest/pipeline.py` (`_BACKTEST_STRATEGY_BUILDERS`). To add a
runnable backtest strategy: register metadata in
`src/quant_system/strategies/registry.py` with `result_type="backtest"` and add a
builder entry in the pipeline. It then appears automatically in the Backtester
and Strategy Catalog. Currently runnable: `cross_sectional_top_n`,
`mean_reversion_top_n`. `reversal_momentum` is `result_type="replication"` and
runs through its own endpoint.

Persistent paper-account rebalancing is a narrower capability. A strategy must
set `supports_account_rebalance=true` in `strategies/registry.py` before
`POST /api/paper/account/rebalance` and `AccountTradePanel` will offer it. Keep
that flag false for research replications or strategies whose account execution
path has not been implemented and tested.

Factor development is code-first. Do not add a frontend expression builder for
ad-hoc factor formulas; implement and test new factor logic in
`src/quant_system/factors/`, register it in the backend factor registry, and let
Factor Lab, Backtester, and Strategy Catalog consume the registered metadata.

Backtest sector caps are API/code-level controls and must be paired with a
`sector_map`; requests that set `sector_cap` without `sector_map` are rejected.
The frontend Backtester exposes the safer per-symbol cap only.

Backtest order realism controls are explicit and default-compatible:
`min_order_value` defaults to `0`, and `whole_share_orders` defaults to `false`.
When whole-share mode is enabled, both generated order quantities and
cash-constrained partial fills are floored to whole shares.

Reversal/momentum replication runs (`result_type="replication"`) persist under
`data/api_runs/replications/<run_id>/` as `metadata.json` + `result.json`.
`POST /api/replications/reversal-momentum/run` returns a `replication-*`
`run_id`; `GET /api/replications/reversal-momentum/{run_id}` and the frontend
route `/replications/[runId]` read it back. These runs are file-persisted but
are not part of the optional PostgreSQL run index, whose schema currently
covers only backtest/factor/paper kinds.

## Experiments Provider Semantics

`POST /api/experiments/run` accepts `provider=sample|futu|tiingo`. The
frontend defaults to `futu`, and the backend builds the provider through
`build_ohlcv_provider`; an explicitly unavailable real provider returns
`400 provider_unavailable` instead of silently falling back to sample data. The
actual source is persisted to `agent_summary.data.source`, and `/experiments`
"Send to Backtest" preserves that source when constructing the `/backtest`
link. Old experiments without `data.source` are treated as `sample`. The run
request also accepts a `walk_forward` object (`enabled`, `train_bars`,
`validation_bars`, `step_bars`); the frontend keeps it off by default and only
generates `walk_forward_folds.parquet` when the user explicitly enables
Walk-forward folds. Experiment detail cards also render
`experiment_config.factor_blend` as a read-only "Strategy under test" summary;
this makes the fixed factor blend visible but does not add UI-side strategy
editing.

Equity data provider overrides are intentionally strict. `build_ohlcv_provider`
only accepts explicit `sample`, `futu`, or `tiingo` requests. Unknown explicit
providers, and unavailable explicit real providers, must return
`400 provider_unavailable`; they must not silently fall back to `sample`. Default
provider fallback may still use a clearly labelled sample response for read-only
market-data viewing when no provider override was supplied.

## Optional PostgreSQL Run Index

Backtest/factor/paper runs are file-based under `data/api_runs/`. An optional
PostgreSQL index (`storage/database.py`, `storage/runs_repository.py`,
`scripts/sql/001_runs_index.sql`) speeds up listing. Off by default; controlled
by `QS_DATABASE_ENABLED` / `QS_DATABASE_URL` / `QS_DATABASE_CONNECT_TIMEOUT_SECONDS`
/ `QS_DATABASE_AUTO_MIGRATE`; default connect timeout is 1 second. Startup
migration/backfill runs in a background thread, healthy short-lived connections
may proceed concurrently, failed probes enter a short cooldown, and list endpoints
must keep falling back to the filesystem when the database is off, slow, or
unreachable. Tests must not touch a real database
(`tests/conftest.py` forces it off). Never run `npm run build` while the
frontend dev server is running — they share `src/frontend/.next` and the build
corrupts the dev server.

## Paper Account (Interactive Auto + Manual Trading)

Separate from the immutable historical-replay runs (`POST /api/paper/run`),
there is a single **persistent paper account** funded at $1,000,000. Manual
orders and strategy rebalances both land in the same account and are reflected
on the Position Map.

- Account model + append-only ledger: `src/quant_system/execution/account.py`
  (`PaperAccount`, `AccountPosition` with `avg_cost`, `LedgerEntry`). The account
  snapshot and its complete audit ledger are persisted together.
- Persistence: `src/quant_system/execution/account_storage.py` writes
  `data/api_runs/paper_account/<account_id>/account.json` +
  `positions_snapshot.parquet` (atomic write with retry; no non-atomic
  overwrite fallback), keeps `account.json.bak` before overwrites, restores a
  valid backup if the main JSON is corrupt, preserves corrupt files as
  `account.corrupt-*.json`, and archives on reset.
- Pricing: `src/quant_system/execution/price_source.py` (`PaperPriceSource`) —
  Futu real-time snapshot first (`fetch_market_snapshots`), falls back to the
  most recent real historical close from local cache / Tiingo when OpenD is
  down, and never uses sample/demo prices. `price_kind` (`futu_snapshot` /
  `last_close`) flows to the ledger and UI.
- Service: `src/quant_system/execution/account_service.py` — manual orders and
  strategy rebalance share one `OrderRequest -> RiskEngine -> PaperBroker ->
  account.apply_fill` primitive. Rebalance is plan-then-commit: it dry-runs the
  whole plan on a deep copy and aborts with no mutation if any leg is rejected
  (prevents "sold everything then failed to buy"). Every current holding and
  target symbol must have a finite positive paper price before a rebalance plan
  can be built; missing or invalid prices abort instead of silently skipping a
  leg.
- API (`src/quant_system/api/routes/paper.py`): `GET /api/paper/account`,
  `POST /api/paper/account/orders` (quantity or notional, optional limit),
  `POST /api/paper/account/orders/process` (check queued paper limit orders),
  `POST /api/paper/account/orders/{order_id}/cancel` (cancel one queued limit order),
  `POST /api/paper/account/rebalance`, `POST /api/paper/account/reset`,
  `POST /api/paper/account/kill-switch`, `GET /api/paper/account/ledger`.
  All mutating routes serialize per account in-process and share a filesystem
  lock with CLI/scheduled rebalance processes.
- Manual limit orders that do not meet the current paper price are persisted in
  `PaperAccount.pending_orders`, surfaced on `/paper-trading`, and can be
  rechecked through `POST /api/paper/account/orders/process` or cancelled via
  `POST /api/paper/account/orders/{order_id}/cancel`. Pending buy limits reserve
  cash at `quantity * limit_price`; pending sell limits reserve share quantity,
  so later manual or strategy orders cannot double-spend the same buying power
  or position. The API starts a lightweight background worker by default
  (`QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED=true`,
  `QS_PAPER_ACCOUNT_AUTO_PROCESS_INTERVAL_SECONDS=30`) that processes existing
  pending orders through the same locked `process_pending_orders` path; tests
  force it off. If the current paper price still misses the limit, processing
  also checks real daily OHLCV high/low ranges for complete days after the
  order's last check/creation and before the current check date, then fills
  touched orders at the original limit price. This backfill never uses sample
  data and does not infer same-day intraday ordering.
- CLI: `quant-system paper rebalance --account default --strategy <id>` (for
  scheduled auto-rebalance; exits non-zero on abort/failure) and
  `quant-system paper account-show`.
- Frontend: account summary + `AccountTradePanel` (manual ticket, one-click
  rebalance, real freeze toggle) on `/paper-trading`; account-driven
  `/position-map` (`src/frontend/components/AccountRefreshControl.tsx` for
  optional 30s auto-refresh).
- Account-level kill switch (default OFF, user-toggleable) freezes only this
  paper account. It is distinct from the global `QS_KILL_SWITCH` that gates the
  legacy `POST /api/paper/run` replay path — do not conflate them.
- Persistent-account fills and strategy rebalances must use real market data:
  Futu snapshots first, then a real local/Tiingo close. Never use synthetic
  sample prices or sample strategy history to mutate the account.

## Options Module Notes

Current options work is split into sell-side and buy-side research modules:

- Sell-side single-ticker screener: `src/quant_system/options/screener.py`.
- Sell-side cross-ticker radar: `src/quant_system/options/radar.py`.
- Radar refresh helpers: `src/quant_system/options/data_refresh.py`.
- Buy-side contracts and scenario data: `src/quant_system/options/models.py`.
- Buy-side contract diagnostics: `src/quant_system/options/buy_side_metrics.py`.
- Buy-side candidate generation: `src/quant_system/options/buy_side_strategy.py`.
- Buy-side scenario lab: `src/quant_system/options/buy_side_scenarios.py`.
- Local AlphaGBM-style tools and research helpers:
  `src/quant_system/options/local_tools.py` and
  `src/quant_system/options/local_research.py`.
- Durable local option quote cache:
  `src/quant_system/storage/options_cache.py`.
- Scheduled sell-side radar CLI: `quant-system options daily-task` refreshes
  the universe, earnings calendar, and VIX history before running
  `run_options_radar`; `scripts/run_options_radar.ps1` is the Windows Task
  Scheduler entrypoint and writes `daily_task_status.json` next to radar
  snapshots. `GET /api/options/daily-scan/status` exposes that file and
  `/options-radar` shows the latest scheduled-task status. Optional startup
  catch-up is controlled by `QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED=false` by
  default; when enabled, API startup first refreshes the local universe,
  earnings calendar, and VIX inputs, then runs a background daily-scan catch-up
  only if the latest regular US market session radar snapshot is missing.
  Weekend and regular full-day US market holidays target the prior session;
  ad-hoc exchange closures and half-days remain a scheduler/operator concern.
  CLI scans, API-triggered scans, scheduled `daily-task`, and startup catch-up
  share `options_radar_scan.lock` in the radar output directory; lock conflicts
  fail API/CLI scans fast and make startup catch-up skip without overwriting
  `daily_task_status.json`.
- Buy-side decision API: `POST /api/options/buy-side/assistant`.
- Buy-side debug CLI: `quant-system options buyside-screen`.
- Buy-side frontend page: `src/frontend/app/options-buyside/page.tsx` (main
  component `src/frontend/components/forms/BuySideOptionsAssistant.tsx`,
  bilingual en/zh, route `/options-buyside`).
- Local tools frontend page: `src/frontend/app/options-tools/page.tsx` (main
  component `src/frontend/components/forms/OptionsToolsWorkbench.tsx`).
- Radar symbol drilldown page: `src/frontend/app/options-radar/[symbol]/page.tsx`.

Buy-side Phase 14 ships with backend logic, API, CLI, and frontend wiring.
Keep pure decision modules free of live data calls; only the API/CLI layer
may call the existing read-only Futu quote provider.

Futu options calls can hit OpenD pacing limits. The provider has a short-lived
in-process option-chain cache plus one read-only retry for typed `rate_limited`
responses. It also has a local DuckDB-backed option quote cache under
`data/futu/options_cache.duckdb` when `QS_FUTU_USE_CACHE=true`. Follow
`docs/architecture/database_cache_plan.md` for cache status and remaining
storage work.

## Environment

Use the uv-managed `ai-quant` virtual environment for Python commands:

```powershell
uv venv ai-quant --python 3.11
.\ai-quant\Scripts\Activate.ps1
uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev,prediction_market]"
```

When installing additional Python packages, prefer uv with the Tsinghua mirror:

```powershell
uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...
```

## Run Backend

Preferred CLI wrapper:

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system serve --host 127.0.0.1 --port 8765
```

This writes structured backend JSONL logs to
`data/_runtime/logs/backend.jsonl`.

Equivalent direct FastAPI start:

```powershell
.\ai-quant\Scripts\Activate.ps1
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

The app factory also writes the same backend runtime log file.

Health check:

```powershell
curl http://127.0.0.1:8765/api/health
```

## Run Frontend

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

If the backend must run on a non-default port, set
`NEXT_PUBLIC_QUANT_API_BASE_URL` before starting the frontend, for example
`$env:NEXT_PUBLIC_QUANT_API_BASE_URL='http://127.0.0.1:8766'`.

Open:

```text
http://127.0.0.1:3001
```

## Tests, Lint, Typecheck, Build

One-command local verification:

```powershell
.\ai-quant\Scripts\Activate.ps1
.\scripts\verify.ps1
```

This runs the Python version check, backend lint/tests, frontend lint, and
frontend unit tests. It skips `npm run build` by default because the build
rewrites `src/frontend/.next`; use `.\scripts\verify.ps1 -Build` only when the
frontend dev server is stopped.

Backend tests:

```powershell
.\ai-quant\Scripts\Activate.ps1
python -m pytest -q
```

Backend lint:

```powershell
.\ai-quant\Scripts\Activate.ps1
ruff check src/quant_system tests
```

Frontend lint:

```powershell
npm --prefix src/frontend run lint
```

Frontend type validation:

```powershell
npm --prefix src/frontend run type-check
```

Frontend build:

```powershell
npm --prefix src/frontend run build
```

Browser smoke tests:

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1
```

If ports 8765/3001 are already occupied by the normal local stack, use isolated
E2E ports instead:

```powershell
cd src/frontend
$env:PW_E2E="1"
$env:PW_BACKEND_PORT="8766"
$env:PW_FRONTEND_PORT="3002"
$env:QUANT_API_COMMAND=".\ai-quant\Scripts\python.exe -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8766"
npx playwright test --config playwright.config.ts --workers=1
```

## Coding Conventions

- Reuse existing modules and patterns before adding new ones.
- Keep research logic, API routes, and frontend UI separated.
- Keep strategy logic separate from execution and risk modules.
- Keep all Futu usage read-only through quote data paths.
- Preserve existing safety flags and API safety footers.
- Add focused tests for new behavior.
- Update docs when adding public commands, routes, settings, or pages.
- Use clear names that distinguish research output from executable orders.
- Prefer small, scoped changes over broad refactors.
- Keep frontend text explicit about read-only / no live trading behavior.

## Do-Not Rules

- Do not create a standalone app.
- Do not modify unrelated modules.
- Do not call live Futu APIs in tests; mock providers and SDK bindings instead.
- Do not use financial-advice language.
- Do not add real trading, order placement, signing, wallet, broker, or account
  unlock logic.
- Do not import or instantiate Futu trade contexts such as
  `OpenSecTradeContext`.
- Do not call `unlock_trade`, `place_order`, `modify_order`, or `cancel_order`
  for real broker trading.
- Do not weaken `dry_run`, `paper_trading`, `live_trading_enabled=false`, or
  `kill_switch=true`.
- Do not expose secrets, API keys, tokens, private keys, or credentials in logs,
  docs, tests, frontend bundles, or API responses.
- Do not present scans, scores, backtests, or radar results as investment
  advice or guaranteed outcomes.

## Safety Boundaries

Default platform posture:

- `dry_run = true`
- `paper_trading = true`
- `live_trading_enabled = false`
- `kill_switch = true`
- `no_live_trade_without_manual_approval = true`

Futu is for read-only market data only. Polymarket is for read-only public data,
historical snapshots, replay, and research only.

## Definition of Done

Before reporting completion:

- Relevant tests pass.
- Relevant lint / build checks pass.
- Frontend changes are browser-checked when practical.
- Changed files are summarized.
- Risk warnings and read-only safety language are preserved.
- Any skipped or impossible verification is stated clearly with the reason.
- No unrelated files are changed.
