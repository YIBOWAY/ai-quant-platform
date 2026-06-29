# AI-Assisted Quant Research Platform

> 中文版：[README_zh.md](README_zh.md)

Local-first quant research, backtesting, paper-trading, read-only market-data,
and options research platform.

The project is currently delivered through Phase 14. It includes:

- US equity and ETF historical data workflows.
- Factor research, Factor Lab diagnostics (real-data-first since 2026-06-11,
  with in-UI provider/universe/symbol/benchmark/time-window/lookback controls,
  saveable factor research runs, and a Backtester prefill handoff),
  strategy/universe
  registries, backtests, experiments, and paper-trading simulation.
- Local FastAPI backend and Next.js frontend.
- AI research assistant with candidate pool and human review gates.
- Read-only Polymarket research, snapshots, replay, and reports.
- Futu read-only US stock and options data.
- Options Income Screener, Options Radar, and Buy-Side Options Assistant.
- Local AlphaGBM-style options toolbox and local Futu option quote cache.
- Strategy Catalog with the reversal/momentum replication, the registered
  cross-sectional Top-N backtest strategy, and a mean-reversion Top-N strategy.
- Reversal/momentum replication runs persist as local `replication-*` artifacts
  with a dedicated detail page.
- Backtest engine controls: rebalance frequency (every bar / weekly / monthly),
  per-symbol weight cap, API-level sector cap when a sector map is supplied,
  and per-name return attribution.
- Optional PostgreSQL run index over local backtest/factor/paper/replication runs.

This project does not add live trading, broker order submission, wallet
connection, signing, Futu account unlock, or real order placement.

## Quick Start

Create and activate the uv-managed `ai-quant` virtual environment, then install Python dependencies:

```powershell
uv venv ai-quant --python 3.11
.\ai-quant\Scripts\Activate.ps1
uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev,prediction_market]"
```

Install frontend dependencies:

```powershell
cd src/frontend
npm install
```

Start both local services from the repository root:

```powershell
.\ai-quant\Scripts\Activate.ps1
.\scripts\dev.ps1
```

This starts the optional `quantplatform-db` Docker container when it exists,
checks the local OpenD port, starts the backend on `127.0.0.1:8765`, starts the
frontend on `127.0.0.1:3001`, and writes logs under `data/_runtime/logs/`.

Stop the local services:

```powershell
.\scripts\dev-stop.ps1
```

Manual backend start:

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system serve --host 127.0.0.1 --port 8765
```

The CLI backend entrypoint writes structured JSONL runtime logs to
`data/_runtime/logs/backend.jsonl` in addition to console output.

Equivalent direct FastAPI command:

```powershell
.\ai-quant\Scripts\Activate.ps1
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

The direct app-factory path uses the same `backend.jsonl` runtime log file.

Manual frontend start in another PowerShell:

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

Open:

```text
http://127.0.0.1:3001
```

Health check:

```powershell
curl http://127.0.0.1:8765/api/health
```

Offline local health summary:

```powershell
quant-system doctor
```

`doctor` does not contact providers or PostgreSQL. It prints the effective
environment, safety flags, default data provider, Futu/OpenD endpoint, optional
database-index settings, and the runtime log path.

## Main Pages

| Page | Purpose |
|---|---|
| `/data-explorer` | US equity historical data viewer. |
| `/factor-lab` | Factor health and timing diagnostics (cross-section / timing tabs); provider, universe, timing symbol, benchmark, time window, lookback, and cache refresh adjustable in the sidebar (default `futu`), plus saveable factor research runs and a Backtester prefill link. |
| `/backtest` | Run strategy, universe, factor-weight, and benchmark backtests. |
| `/strategies` | Strategy Catalog for registered research strategies. |
| `/strategies/[runId]` | Persisted reversal/momentum replication run detail. |
| `/docs/reversal-momentum` | Frontend-readable notes for the paper replication. |
| `/experiments` | Run provider-selectable experiment sweeps with optional walk-forward folds, inspect the fixed factor blend under test, and send best params with the same source to backtest. |
| `/paper-trading` | Persistent paper account (manual orders + one-click strategy rebalance) plus historical replay. |
| `/position-map` | Live paper-account position map (equity, cash, exposure, source attribution); backtest exposure shown as a comparison block. |
| `/options-screener` | Single-ticker seller options screener. |
| `/options-radar` | Daily seller options radar snapshot. |
| `/options-radar/[symbol]` | Single-ticker radar drilldown and live chain loader. |
| `/options-tools` | Local AlphaGBM-style options toolbox. |
| `/options-buyside` | Buy-side options strategy assistant. |
| `/polymarket` | Read-only prediction-market research page. |
| `/agent-studio` | AI research assistant candidate workflows. |
| `/settings` | Masked local settings. |

Equity data endpoints only accept explicit `provider=sample|futu|tiingo`.
Unknown overrides, or explicitly requested real providers that are unavailable,
return `400 provider_unavailable` instead of silently substituting sample data.
When no provider override is supplied, read-only market-data views may still
fall back to a clearly labelled sample response for offline use.
Intraday market-data requests (`freq` other than `1d`) are Futu-only; they do
not fall back to sample data because that would mislabel daily synthetic bars
as intraday history.
At the provider layer, `SampleOHLCVProvider` and `TiingoEODProvider` reject
non-`1d` intervals before returning data.
The code default and `.env.example` both use `QS_DEFAULT_DATA_PROVIDER="futu"`;
set it to `sample` only for explicit offline workflow tests.

## Async Backtest Jobs

`POST /api/backtests/run` keeps the historical synchronous `200 BacktestRunResponse`
path by default. Set `QS_BACKTEST_JOBS_ENABLED=true` to make it return
`202 BacktestJobStateResponse` immediately, with `poll_url` pointing at
`GET /api/backtests/jobs/{run_id}` and `result_url` becoming available after the
job reaches `completed`. `POST /api/backtests/jobs/{run_id}/cancel` cancels queued
jobs and cooperatively cancels running jobs between backtest pipeline stages.
The local runner is process-local (`ThreadPoolExecutor`, default
`QS_BACKTEST_JOBS_MAX_WORKERS=1`) and waits up to
`QS_BACKTEST_JOBS_SHUTDOWN_TIMEOUT_SECONDS=5` during API shutdown before marking
still-running jobs cancelled. Startup marks any leftover queued/running/cancelling
metadata as failed because there is no distributed queue to resume from.

The UI is bilingual (English / 中文). Use the top-bar language toggle or open
locale-prefixed paths such as `/en/options-radar` and `/zh/options-radar`.
The choice is also stored in the `qs_lang` cookie for unprefixed paths. See
[docs/frontend/frontend_chinese_version.md](docs/frontend/frontend_chinese_version.md).

## Futu Read-Only Data

Futu OpenD is used for US stock and options market data only.

Requirements:

1. OpenD is running locally and logged in.
2. `futu-api` is installed in the `ai-quant` environment.
3. The platform only uses quote/data paths, not trading paths.

Verification:

```powershell
.\ai-quant\Scripts\Activate.ps1
python scripts/verify_futu_connection.py
```

Important constraints:

- No Futu trade context.
- No account unlock.
- No order placement.
- No broker execution.

Interactive options pages include a short-lived in-process cache, a local
DuckDB-backed Futu option quote cache, and a one-time retry for Futu rate-limit
responses. Broad daily scans should still be scheduled and expected to run
slowly under Futu pacing.

## Optional PostgreSQL Run Index

Backtest, factor, paper, and replication runs are always written to local files
under `data/api_runs/<kind>/<run_id>/`. You can optionally index those four
kinds into PostgreSQL for fast history listing. It is **disabled by default**;
when the database is off or unreachable, every indexed endpoint falls back to
the filesystem.

To enable it against a local Docker container:

```powershell
# container named quantplatform-db, db=quantplatform, user=quant, pass=quantpass
docker start quantplatform-db
```

```text
# .env
QS_DATABASE_ENABLED=true
QS_DATABASE_URL="postgresql://quant:quantpass@127.0.0.1:5432/quantplatform"
QS_DATABASE_CONNECT_TIMEOUT_SECONDS=1
QS_DATABASE_AUTO_MIGRATE=true
```

On startup the backend starts run-index migration/backfill in the background:
it creates the `quant_system.runs` table, backfills existing file runs, and
prunes index rows whose files were removed. If PostgreSQL is down, the first
probe is short and later failed requests use a brief cooldown window while
continuing to read local files. Healthy PostgreSQL connections may proceed
concurrently. Check it with:

```powershell
curl http://127.0.0.1:8765/api/health   # database.reachable should be true
```

Run the optional PostgreSQL integration test against a throwaway database, not
your usual `quantplatform` database:

```powershell
$env:QS_TEST_DATABASE_URL='postgresql://quant:quantpass@127.0.0.1:5432/quantplatform_codex_tmp'
python -m pytest tests/test_runs_repository_postgres.py -q
```

The test may create the target database when its name is clearly temporary
(`*_tmp` or containing `test`). This keeps its prune checks away from your
normal run index.

The `psycopg` driver ships with the `api` extra. The database stores research
run metadata only; the connection URL is masked in `/api/settings`. See
[docs/architecture/database_cache_plan.md](docs/architecture/database_cache_plan.md).

## Backup Local Runs

Research runs and the persistent paper account are local files under
`data/api_runs/`. Create a zip backup before large refactors or disk moves:

```powershell
.\ai-quant\Scripts\Activate.ps1
python scripts/backup_api_runs.py --data-dir data --output-dir data/backups
```

The archive includes `api_runs/` and a `manifest.json`; it does not include
`.env`, DuckDB files, lock files, logs, or API keys.

## Paper Account

A single persistent paper account (funded at $1,000,000) lets you trade by hand
or let a strategy rebalance for you, all reflected on the Position Map. It is
simulation-only — no real orders, broker, wallet, or account unlock.

- Manual order: `POST /api/paper/account/orders` (buy/sell, quantity or
  notional, optional limit). Fills at the Futu real-time snapshot price, or the
  most recent real historical close from local cache/Tiingo when OpenD is
  offline. A limit order that does not meet that paper price is stored in the
  account `pending_orders` queue and can be rechecked with
  `POST /api/paper/account/orders/process` or cancelled with
  `POST /api/paper/account/orders/{order_id}/cancel`; the `/paper-trading` page
  shows the pending list, a check button, and per-order cancel controls. Pending
  buy limits reserve cash at `quantity * limit_price`, pending sell limits
  reserve share quantity, and account responses expose both `cash` and
  `available_cash`. The API background worker also checks existing pending orders
  every 30 seconds by default
  (`QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED` /
  `QS_PAPER_ACCOUNT_AUTO_PROCESS_INTERVAL_SECONDS`). When the current paper
  price still misses the limit, pending-order processing also checks real daily
  OHLCV high/low ranges for complete days after the order's last check/creation
  and before the current check date, then fills touched orders at the original
  limit price. It never uses sample data and does not infer same-day intraday
  ordering. The persistent account never uses sample/demo prices.
- Strategy rebalance: `POST /api/paper/account/rebalance` (one-click; aborts
  atomically if any leg cannot fill). The strategy picker is driven by
  `supports_account_rebalance` in the backend strategy registry; currently the
  account path supports `cross_sectional_top_n` and `mean_reversion_top_n`.
  It only uses real market history; sample strategy history never mutates the
  persistent account. Every current holding and target symbol must have a
  finite positive paper price before the rebalance plan is built; missing or
  invalid prices abort the whole rebalance rather than producing a partial
  order plan.
- View / freeze / reset / ledger: `GET /api/paper/account`,
  `POST /api/paper/account/kill-switch`, `POST /api/paper/account/reset`,
  `GET /api/paper/account/ledger`.
  The account store keeps `account.json.bak` before overwrites; if the main
  account JSON is corrupt, it preserves the bad file as `account.corrupt-*.json`
  and restores a valid backup before opening a fresh account. Atomic save
  retries never fall back to plain text overwrite; if replace keeps failing,
  the old account file stays intact and the save fails visibly.
  Paper-account domain failures return structured API details with
  `detail.code` and `detail.message` (for example `price_unavailable`,
  `account_frozen`, or `unsupported_account_rebalance_strategy`).
  Historical replay kill-switch rejections use the same structured shape
  (`replay_kill_switch_enabled` / `global_kill_switch_enabled`).

Scheduled auto-rebalance (e.g. via Windows Task Scheduler):

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system paper rebalance --account default --strategy cross_sectional_top_n
```

The legacy `POST /api/paper/run` historical replay lives on the
"History Replay (research)" tab of the same page (since 2026-06-11). See
[docs/guides/paper-trading.md](docs/guides/paper-trading.md) and
[docs/design/paper_trading_position_map_redesign.md](docs/design/paper_trading_position_map_redesign.md).

### Paper Strategy Sleeves

Paper Strategy Sleeves are the next accounting layer for the persistent paper
account: one account, multiple isolated manual/strategy cash and lot segments.
The backend foundation, API contract, daily signal, `/paper-trading`
Strategy Sleeves workspace, and manual next-open paper execution slices are
available:

- `StrategyConfig`, `StrategySleeve`, `SleeveLot`, `StrategySignal`, and
  `SleeveLotBook` in `src/quant_system/execution/paper_strategy_sleeves.py`.
- Local source-of-truth storage under
  `data/api_runs/paper_strategy_sleeves/`.
- `PaperAccount.sleeve_cash` for internal manual/strategy cash allocations,
  while `PaperAccount.cash` remains the legacy total cash field used by the
  existing full-account rebalance path.
- Backend API routes now cover strategy config creation/listing/versioning and
  strategy sleeve create/list/detail/signal generation/pause/resume/stop:
  `/api/paper/strategy-configs` and `/api/paper/strategy-sleeves`. Active
  strategy config names are unique; same-name creation returns a structured
  `409 strategy_config_name_conflict`.
- Daily signal generation is available through
  `POST /api/paper/strategy-sleeves/{id}/signals` and
  `quant-system paper strategies generate-signal --sleeve <id>`.
- The `/paper-trading` live account tab can create strategy configs, open
  signal-only or allocated sleeves, generate sleeve signals, and pause/resume
  or stop sleeves. Allocated sleeves can explicitly create and process one-shot
  pending execution plans.
- Manual execution entrypoints are available through
  `POST /api/paper/strategy-sleeves/{id}/executions`,
  `POST /api/paper/strategy-sleeves/executions/process`,
  `quant-system paper strategies create-execution`, and
  `quant-system paper strategies execute-pending`.

Scheduled sleeve execution is not implemented yet: generated signals do not
auto-fill and the FastAPI process does not run a resident scheduler. The
existing `POST /api/paper/account/rebalance` endpoint remains a full-account
rebalance path, not a Strategy Sleeves entrypoint or liquidation shortcut; it is
rejected when actual sleeve-owned lots exist. See
[docs/design/paper_strategy_sleeves_plan.md](docs/design/paper_strategy_sleeves_plan.md),
[docs/design/paper_strategy_sleeves_mvp3_operations_plan.md](docs/design/paper_strategy_sleeves_mvp3_operations_plan.md),
and
[docs/execution/paper_strategy_sleeves.md](docs/execution/paper_strategy_sleeves.md).

## Factor Lab Refresh

Since 2026-06-11 the Factor Lab UI defaults to real data (`provider=futu`),
with sidebar controls for provider / universe / timing symbol / benchmark /
start / end / lookback / cache refresh, and supports saveable factor research
runs. Since 2026-06-16 its query card links to Backtester with provider /
universe / benchmark / start / end / lookback / factor IDs prefilled; the link
does not run a backtest. The CLI below refreshes the local diagnostics cache
from the backend or a scheduled task:

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system factor refresh-lab --provider sample --universe-id etf --symbol QQQ --benchmark-symbol QQQ
```

The command only writes local research cache files. It does not place orders.

New factors are added by implementing and testing backend factor code, then
registering it in the factor registry. The frontend reads registered factors;
it is not intended to be a free-form factor-expression editor.

## Options Workflows

Single-ticker seller screener:

```text
http://127.0.0.1:3001/options-screener
```

The screener offers conservative / balanced / aggressive presets plus quality
filters for minimum option mid price, underlying average daily volume, and
market capitalization. `min_market_cap=0` disables the market-cap gate. Results
hide `Avoid` contracts by default; enable "Show Avoid contracts" /
`include_rejected=true` when auditing rejected rows. The Notes column explains
why a row was downgraded or filtered.

Daily seller radar:

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system options daily-scan --top 10
```

Scheduled refresh + radar task:

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system options daily-task --top 100 --universe-source public --earnings-source public --vix-source public
```

Register the Windows Task Scheduler entrypoint:

```powershell
.\scripts\register_options_radar_task.ps1
```

Radar UI:

```text
http://127.0.0.1:3001/options-radar
```

The Radar page can run the current-date read-only scan and refresh the local
universe, earnings, and VIX caches. Public sources are the default; the local
sample source is only for explicit offline testing. Scheduled runs should use
`daily-task`, which refreshes those local inputs before writing the daily
snapshot and `daily_task_status.json`; the Radar page reads the same file
through `GET /api/options/daily-scan/status` and shows the latest scheduled-task
state. Startup catch-up is opt-in: set
`QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED=true` only when OpenD/cache readiness
is expected and you want API startup to refresh the local universe, earnings,
and VIX inputs before running a background daily-scan catch-up if the latest
regular US market session snapshot is missing. Weekend and regular full-day US
market holidays target the prior session; ad-hoc exchange closures and half-days
are still a scheduler/operator concern. CLI scans, API-triggered scans,
scheduled `daily-task`, and startup catch-up share `options_radar_scan.lock` in
the radar output directory; a locked startup catch-up skips without overwriting
`daily_task_status.json`.

Local options toolbox:

```text
http://127.0.0.1:3001/options-tools
```

Buy-side assistant debug CLI:

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system options buyside-screen --ticker AAPL --view long_term_aggressive_bullish --target-price 220 --target-date 2026-12-31
```

Buy-side assistant page:

```text
http://127.0.0.1:3001/options-buyside
```

All options outputs are research-only decision support. They are not financial
advice and cannot place orders.

## Polymarket / Prediction Market

The prediction-market module is read-only research:

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system prediction-market collect --provider sample --duration 0 --limit 10
quant-system prediction-market timeseries-backtest --provider sample
```

It does not sign, redeem, transfer, or submit real market orders.

## Validation

One-command local check:

```powershell
.\ai-quant\Scripts\Activate.ps1
.\scripts\verify.ps1
```

This runs the Python version check, backend lint/tests, frontend lint,
frontend type-check, and frontend unit tests. It skips `npm run build` by default because that command
rewrites `src/frontend/.next`; run `.\scripts\verify.ps1 -Build` only when the
frontend dev server is stopped.

Backend-only checks:

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system doctor
python -m pytest -q
ruff check src/quant_system tests
```

Frontend-only checks:

```powershell
npm --prefix src/frontend run lint
npm --prefix src/frontend run type-check
npm --prefix src/frontend run test
npm --prefix src/frontend run build   # only when the dev server is stopped
```

Browser smoke:

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1
```

If your normal local stack is already using ports 8765/3001, run the smoke test
on isolated alternate ports:

```powershell
cd src/frontend
$env:PW_E2E="1"
$env:PW_BACKEND_PORT="8766"
$env:PW_FRONTEND_PORT="3002"
$env:QUANT_API_COMMAND=".\ai-quant\Scripts\python.exe -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8766"
npx playwright test --config playwright.config.ts --workers=1
```

## Recommended Reading

Start here:

- [docs/OVERVIEW.md](docs/OVERVIEW.md)
- [docs/INDEX.md](docs/INDEX.md)
- [docs/SYSTEM_DESIGN_RESEARCH.md](docs/SYSTEM_DESIGN_RESEARCH.md)

Current options docs:

- [docs/futu/futu_environment_setup.md](docs/futu/futu_environment_setup.md)
- [docs/futu/futu_options_data_provider.md](docs/futu/futu_options_data_provider.md)
- [docs/options/options_screener_learning.md](docs/options/options_screener_learning.md)
- [docs/options/buyside_strategy_learning.md](docs/options/buyside_strategy_learning.md)
- [docs/options/local_alphagbm_tools.md](docs/options/local_alphagbm_tools.md)
- [docs/delivery/phase_14_delivery.md](docs/delivery/phase_14_delivery.md)

Paper replication:

- [docs/replications/reversal_momentum_replication.md](docs/replications/reversal_momentum_replication.md)

Local cache plan and current status:

- [docs/architecture/database_cache_plan.md](docs/architecture/database_cache_plan.md)

## Safety Boundary

Default platform posture:

- `QS_DRY_RUN=true`
- `QS_PAPER_TRADING=true`
- `QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED=true`
- `QS_LIVE_TRADING_ENABLED=false`
- `QS_NO_LIVE_TRADE_WITHOUT_MANUAL_APPROVAL=true`
- `QS_KILL_SWITCH=true`

These boundaries must not be bypassed by frontend pages, API routes, agents,
strategies, backtests, or paper-trading flows.
