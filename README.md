# AI-Assisted Quant Research Platform

> 中文版：[README_zh.md](README_zh.md)

Local-first quant research, backtesting, paper-trading, read-only market-data,
and options research platform.

The project is currently delivered through Phase 14. It includes:

- US equity and ETF historical data workflows.
- Factor research, Factor Lab diagnostics (real-data-first since 2026-06-11,
  with in-UI provider/universe/symbol/benchmark controls and saveable factor
  research runs), strategy/universe registries, backtests, experiments, and
  paper-trading simulation.
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
- Optional PostgreSQL run index over local backtest/factor/paper runs.

This project does not add live trading, broker order submission, wallet
connection, signing, Futu account unlock, or real order placement.

## Quick Start

Install Python dependencies in the existing conda environment:

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev]"
```

Install frontend dependencies:

```powershell
cd src/frontend
npm install
```

Start both local services from the repository root:

```powershell
conda activate ai-quant
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
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

The CLI backend entrypoint writes structured JSONL runtime logs to
`data/_runtime/logs/backend.jsonl` in addition to console output.

Equivalent direct FastAPI command:

```powershell
conda activate ai-quant
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

## Main Pages

| Page | Purpose |
|---|---|
| `/data-explorer` | US equity historical data viewer. |
| `/factor-lab` | Factor health and timing diagnostics (cross-section / timing tabs); provider, universe, timing symbol, and benchmark adjustable in the sidebar (default `futu`), plus saveable factor research runs. |
| `/backtest` | Run strategy, universe, factor-weight, and benchmark backtests. |
| `/replications` | Strategy Catalog for registered research strategies. |
| `/replications/[runId]` | Persisted reversal/momentum replication run detail. |
| `/docs/reversal-momentum` | Frontend-readable notes for the paper replication. |
| `/experiments` | Run provider-selectable experiment sweeps with optional walk-forward folds, inspect the fixed factor blend under test, and send best params with the same source to backtest. |
| `/paper-trading` | Persistent paper account (manual orders + one-click strategy rebalance) plus historical replay. |
| `/position-map` | Live paper-account position map (equity, cash, exposure, source attribution); backtest exposure shown as a comparison block. |
| `/options-screener` | Single-ticker seller options screener. |
| `/options-radar` | Daily seller options radar snapshot. |
| `/options-radar/[symbol]` | Single-ticker radar drilldown and live chain loader. |
| `/options-tools` | Local AlphaGBM-style options toolbox. |
| `/options-buyside` | Buy-side options strategy assistant. |
| `/order-book` | Read-only prediction-market research page. |
| `/agent-studio` | AI research assistant candidate workflows. |
| `/settings` | Masked local settings. |

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
conda activate ai-quant
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

Backtest, factor, and paper runs are always written to local files under
`data/api_runs/<kind>/<run_id>/`. You can optionally index those three kinds
into PostgreSQL for fast history listing. Reversal/momentum replication runs are
also file-persisted under `data/api_runs/replications/<run_id>/`, but they are
not part of the optional PostgreSQL run index. It is **disabled by default**;
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

The `psycopg` driver ships with the `api` extra. The database stores research
run metadata only; the connection URL is masked in `/api/settings`. See
[docs/architecture/database_cache_plan.md](docs/architecture/database_cache_plan.md).

## Backup Local Runs

Research runs and the persistent paper account are local files under
`data/api_runs/`. Create a zip backup before large refactors or disk moves:

```powershell
conda activate ai-quant
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
  shows the pending list, a check button, and per-order cancel controls. The
  persistent account never uses sample/demo prices.
- Strategy rebalance: `POST /api/paper/account/rebalance` (one-click; aborts
  atomically if any leg cannot fill). It only uses real market history; sample
  strategy history never mutates the persistent account.
- View / freeze / reset / ledger: `GET /api/paper/account`,
  `POST /api/paper/account/kill-switch`, `POST /api/paper/account/reset`,
  `GET /api/paper/account/ledger`.

Scheduled auto-rebalance (e.g. via Windows Task Scheduler):

```powershell
conda activate ai-quant
quant-system paper rebalance --account default --strategy cross_sectional_top_n
```

The legacy `POST /api/paper/run` historical replay is unchanged and lives on
the "History Replay (research)" tab of the same page (since 2026-06-11). See
[docs/guides/paper-trading.md](docs/guides/paper-trading.md) and
[docs/design/paper_trading_position_map_redesign.md](docs/design/paper_trading_position_map_redesign.md).

## Factor Lab Refresh

Since 2026-06-11 the Factor Lab UI defaults to real data (`provider=futu`),
with sidebar controls for provider / universe / timing symbol / benchmark, and
supports saveable factor research runs. The CLI below refreshes the local
diagnostics cache from the backend or a scheduled task:

```powershell
conda activate ai-quant
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

Daily seller radar:

```powershell
conda activate ai-quant
quant-system options daily-scan --top 10
```

Scheduled refresh + radar task:

```powershell
conda activate ai-quant
quant-system options daily-task --top 100 --universe-source public --earnings-source public --vix-source public
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
is expected and you want API startup to run a background daily-scan catch-up if
the latest weekday snapshot is missing. Weekend startups target the prior
Friday; full exchange-holiday handling is still left to the scheduled
`daily-task` workflow. CLI scans, API-triggered scans, scheduled `daily-task`,
and startup catch-up share `options_radar_scan.lock` in the radar output
directory; a locked startup catch-up skips without overwriting
`daily_task_status.json`.

Local options toolbox:

```text
http://127.0.0.1:3001/options-tools
```

Buy-side assistant debug CLI:

```powershell
conda activate ai-quant
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
conda activate ai-quant
quant-system prediction-market collect --provider sample --duration 0 --limit 10
quant-system prediction-market timeseries-backtest --provider sample
```

It does not sign, redeem, transfer, or submit real market orders.

## Validation

One-command local check:

```powershell
conda activate ai-quant
.\scripts\verify.ps1
```

This runs the Python version check, backend lint/tests, frontend lint, and
frontend unit tests. It skips `npm run build` by default because that command
rewrites `src/frontend/.next`; run `.\scripts\verify.ps1 -Build` only when the
frontend dev server is stopped.

Backend-only checks:

```powershell
conda activate ai-quant
python -m pytest -q
ruff check src/quant_system tests
```

Frontend-only checks:

```powershell
npm --prefix src/frontend run lint
npm --prefix src/frontend run test
npm --prefix src/frontend run build   # only when the dev server is stopped
```

Browser smoke:

```powershell
cd src/frontend
$env:PW_E2E="1"
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
- `QS_LIVE_TRADING_ENABLED=false`
- `QS_NO_LIVE_TRADE_WITHOUT_MANUAL_APPROVAL=true`
- `QS_KILL_SWITCH=true`

These boundaries must not be bypassed by frontend pages, API routes, agents,
strategies, backtests, or paper-trading flows.
