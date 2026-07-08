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
  news/                   Read-only AI HOT news client, models, optional cache.
  options/                Futu read-only options research modules.
  prediction_market/      Read-only Polymarket / prediction market research.
  risk/                   Risk limits and checks.
  storage/                DuckDB options cache + optional PostgreSQL helper/run index.
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
scripts/sql/              Plain SQL migrations for optional local PostgreSQL mirrors.
data/                     Local cache, fixtures, generated research outputs.
```

## Hermes Integration Route

- This repository is the domain backend for
  `/Users/sunyibo/programs/Hermes-quant-agent`.
- The active cross-repo roadmap lives in
  `/Users/sunyibo/programs/Hermes-quant-agent/docs/design/2026-07-01-roadmap-phases-0b-4.md`.
- `docs/phases/phase_15_iteration_roadmap.md` is reference material only; do
  not continue it as a standalone product roadmap.
- Candidate factors must not reach resident paper/live paths from `.candidate`
  files. One-shot research backtests may explicitly load approved candidates;
  paper sleeve allocation requires promoted, registered, tested factor code.
- Future frontend convergence should fold `/factor-lab` and `/agent-studio`
  into the Hermes workbench while preserving approval UI and removing platform
  LLM/task-running affordances.

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
route `/strategies/[runId]` read it back. These runs are file-persisted and are
included in the optional PostgreSQL run index / `/api/runs/recent` mirror; the
filesystem remains the source of truth.

`POST /api/backtests/run` is synchronous by default. If `QS_BACKTEST_JOBS_ENABLED=true`,
it returns `202` job state from the process-local `BacktestJobRunner`; poll
`GET /api/backtests/jobs/{run_id}` and cancel through
`POST /api/backtests/jobs/{run_id}/cancel`. The runner is local-only, bounded by
`QS_BACKTEST_JOBS_MAX_WORKERS`, and must keep queued/running/cancelling metadata
recoverable across restart.

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

## Optional PostgreSQL Local Mirrors

Backtest/factor/paper/replication runs are file-based under `data/api_runs/`.
An optional PostgreSQL run index (`storage/database.py`,
`storage/runs_repository.py`, `scripts/sql/001_runs_index.sql`) speeds up
listing. AI News also uses the same optional database as a read-only stale
fallback cache (`news/repository.py`, `scripts/sql/002_ai_news_cache.sql`).
`scripts/sql/003_app_users_brief_ai_reports.sql` adds the root user plus
brief issue/snapshot/source and AI daily report tables. Brief archive
generate/read APIs, `/brief/{public_id}`, and AI HOT daily report stale
fallback are wired; paper-account DB mirror/canonical remains follow-on work.
The database is off by default; controlled by `QS_DATABASE_ENABLED` /
`QS_DATABASE_URL` / `QS_DATABASE_CONNECT_TIMEOUT_SECONDS` /
`QS_DATABASE_AUTO_MIGRATE`; default connect timeout is 1 second. Startup
migration/backfill runs in a background thread, healthy short-lived connections
may proceed concurrently, failed probes enter a short cooldown, and endpoints
must keep falling back to files/live upstreams when the database is off, slow,
or unreachable. Tests must not touch a real database (`tests/conftest.py`
forces it off; AI News repository tests use fakes). Never run `npm run build`
while the frontend dev server is running — they share `src/frontend/.next` and
the build corrupts the dev server.

## AI News Integration

AI News is a read-only AI HOT integration:

- Backend modules: `src/quant_system/news/aihot_client.py`,
  `src/quant_system/news/models.py`, `src/quant_system/news/repository.py`.
- API route/schema: `src/quant_system/api/routes/news.py` and
  `src/quant_system/api/schemas/news.py`.
- Frontend route/component: `/ai-news`,
  `src/frontend/app/ai-news/page.tsx`, and
  `src/frontend/components/forms/AiNewsView.tsx`.
- Public local API: `GET /api/news/aihot/items`,
  `GET /api/news/aihot/daily`, `GET /api/news/aihot/dailies`,
  `GET /api/news/aihot/status`.
- Settings: `QS_AIHOT_ENABLED`, `QS_AIHOT_BASE_URL`,
  `QS_AIHOT_TIMEOUT_SECONDS`, `QS_AIHOT_CACHE_TTL_SECONDS`,
  `QS_AIHOT_USER_AGENT`.

Rules: AI HOT `/api/public/*` needs a browser-style User-Agent; the status
route must not probe upstream; tests must mock AI HOT and must not hit real
network; cached fallback is for `items` only and must be labelled via warnings.
Do not connect AI News to factors, strategies, backtests, paper account,
strategy sleeves, Futu trade contexts, or any trading path.

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

## Paper Strategy Sleeves

Paper Strategy Sleeves are a new MVP-1 business line for isolating strategy
cash/lots inside the single persistent paper account. As of 2026-06-29, the
backend foundation, API contract, daily signal generation, manual pending
execution planning, next-open paper execution processor, and UI execution-state
controls are implemented:

- Domain/accounting models:
  `src/quant_system/execution/paper_strategy_sleeves.py`
  (`StrategyConfig`, `StrategySleeve`, `SleeveLot`, `StrategySignal`,
  `StrategyExecutionPlan`, `StrategyExecutionOrder`, `StrategyExecutionFill`,
  `SleeveLotBook`, `PaperStrategySleeveService`).
- Execution processor:
  `src/quant_system/execution/paper_strategy_execution_service.py` processes
  due `next_open` pending plans through `PaperPriceSource`, updates only the
  addressed sleeve cash/lots plus aggregate paper-account view, and records
  `sleeve_execution_fill` ledger entries. Default pending processing only
  selects plans whose `target_date` is the local run date; historical catch-up
  must pass an explicit target date. Filled executions write a pending
  execution journal with before/after account, sleeve, lots, and execution
  snapshots before mutating files; API/CLI success paths commit the journal only
  after the account save succeeds, and later sleeve detail/process access can
  reconcile pending journals.
- Local file source of truth:
  `src/quant_system/execution/paper_strategy_sleeve_storage.py`, under
  `data/api_runs/paper_strategy_sleeves/`. Allocated sleeve creation uses a
  `sleeve.pending.json` journal and reconciles it against
  `PaperAccount.sleeve_cash` on later list/detail/signal access. Filled
  execution journals live under each sleeve's `execution_journal/` directory as
  `.pending.json`, `.committed.json`, or preserved `.corrupt-*.json` files.
- API response schema classes live in `src/quant_system/api/schemas/paper.py`.
- API routes live in `src/quant_system/api/routes/paper.py`:
  `POST/GET /api/paper/strategy-configs`,
  `POST /api/paper/strategy-configs/{id}/versions`,
  `POST/GET /api/paper/strategy-sleeves`,
  `GET /api/paper/strategy-sleeves/{id}`,
  `POST /api/paper/strategy-sleeves/{id}/signals`,
  `POST /api/paper/strategy-sleeves/{id}/executions`,
  `GET /api/paper/strategy-sleeves/ops/status`,
  `POST /api/paper/strategy-sleeves/executions/process`,
  and pause/resume/stop endpoints.
- Daily signal generation service:
  `src/quant_system/execution/paper_strategy_signal_service.py`. It writes
  `StrategySignal` records only; it does not create pending orders, fills, or
  account position mutations, and it does not persist a new account file when
  no account exists yet. Paused/frozen states set `execution_blocked_reason`;
  stopped sleeves reject generation.
- Manual CLI trigger:
  `quant-system paper strategies generate-signal --sleeve <id>`,
  `quant-system paper strategies create-execution --sleeve <id> --signal <signal_id>`,
  `quant-system paper strategies execute-pending`,
  `quant-system paper strategies execute-due`,
  and `quant-system paper strategies ops-status`.
- Frontend workspace:
  `src/frontend/components/forms/PaperStrategySleevesPanel.tsx` is mounted in
  `/paper-trading` live account tab. It can create strategy configs, open
  signal-only or allocated sleeves, generate signals, and pause/resume/stop
  sleeves, then explicitly create/process one-shot paper execution plans. It
  does not auto-run a scheduler and generated signals do not auto-fill orders.
- `PaperAccount.sleeve_cash` is a cash allocation book. Keep
  `PaperAccount.cash` as the legacy total cash field so the old full-account
  rebalance path keeps its existing behavior for non-sleeve positions. When
  actual sleeve-owned lots exist, the old full-account rebalance API must reject
  with `strategy_sleeve_positions_present` instead of selling those lots outside
  the sleeve execution processor.
- Focused tests: `tests/test_paper_strategy_sleeves.py`, plus existing
  `tests/test_paper_strategy_signals.py`,
  `tests/test_api_paper_strategy_sleeves.py`,
  `tests/test_paper_strategy_sleeves_futu_integration.py`,
  `tests/test_paper_strategy_execution.py`,
  `tests/test_paper_account.py`, and `tests/test_api_paper_account.py`.

Not yet implemented: scheduler-safe due-signal commands, config/sleeve creation
CLI helpers, automatic execution, near-close fills, or lot transfer. Do not
document those as user-available until a later slice lands. The legacy
`POST /api/paper/account/rebalance` remains an advanced full-account rebalance
path, not a strategy sleeve entrypoint.

Normal signal-generation tests stay mocked/offline. Real Futu/OpenD checks are
behind the opt-in `futu_opend` pytest marker plus `QS_TEST_FUTU_OPEND=1`. Real
Futu tests cover read-only signal generation plus the paper next-open execution
processor, and must not import trade contexts.

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
