# AI-Assisted Quant Research Platform

> 中文版：[README_zh.md](README_zh.md)

Local-first quant research, backtesting, paper-trading, read-only market-data,
and options research platform.

The Phase 0-14 documents describe delivered historical capability layers, not
the current implementation queue. Start with [docs/INDEX.md](docs/INDEX.md).
HQA Slices 9A-9G, the read-only mini 9H Hermes artifact shelf, and full 9H
automation/notifications are delivered. D-31 Waves 1-3 have delivered the
fail-closed gateway contract, candidate integrity/scoped Gate 3, the
professional read-only Hermes shell, official-API persisted-session reads,
migration 005's durable transport ledger, a reconcile-only connector-worker
framework, and a read-only Unified Results catalog/detail UI. Slice 3C.1 now has
code-accepted exact workflow-binding/inventory primitives for HQA Task/Attempt and
immutable payload metadata, but migration 006 is not applied to the live database
and no browser or worker path consumes it. This is not a
write bridge: real local-Hermes chat/provider use, approval mutations, exact
Hermes-run links, full results cutover, and legacy-page retirement remain
unfinished and require later independent evidence gates. Slice 9E is an HQA-local locked
prediction event ledger that reuses, but does not modify, the platform. Slice 9D adds a strict read-only
`data prices` JSON seam: explicit Futu, QFQ, and 1d only; at most 25 symbols
and 500 inclusive calendar dates; no sample/local/Tiingo/Longbridge fallback.
HQA portfolio-risk v2 uses the previous UTC date as `end` and `end-400 days`
as `start`,
globally inner-joins dates before computing returns, requires at least 60
aligned returns, and reports per-position beta versus SPY plus position-pair
correlations. It does not calculate aggregate beta, VaR, or a threshold
verdict. The 2026-07-11 live acceptance used 274 aligned returns and measured
AAPL beta at `0.8576599678`; the platform suite reported
`1027 passed, 15 skipped`, while 20 observed state/cache files retained
identical bytes, mtimes,
and hashes. This repository's
[frontend redesign and Hermes integration plan](docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md)
is the Slice 0-8 delivery record and UI backlog. The cross-repo product roadmap
remains in `/Users/sunyibo/programs/Hermes-quant-agent`; this repository is its
domain backend, not an independent Phase 15 product track.

- US equity and ETF historical data workflows.
- Factor research, Factor Lab diagnostics (real-data-first since 2026-06-11,
  with in-UI provider/universe/symbol/benchmark/time-window/lookback controls,
  saveable factor research runs, and a Backtester prefill handoff),
  strategy/universe
  registries, backtests, experiments, and paper-trading simulation.
- Local FastAPI backend and Next.js frontend.
- AI research assistant with a digest-bound candidate pool and human review
  gates (Gate 2 CAS + isolated Gate 3 review worktree; never auto-commits).
  Active Gate 3 status re-attests the exact patch, three-file dirty workspace,
  and provenance. Experiment artifacts use exclusively reserved per-invocation
  namespaces and never overwrite an existing experiment.
- Read-only Polymarket research, snapshots, replay, and reports.
- Futu read-only US stock and options data.
- Options Income Screener, Options Radar, and Buy-Side Options Assistant.
- Local AlphaGBM-style options toolbox and local Futu option quote cache.
- Read-only AI HOT news research feed with optional PostgreSQL stale fallback.
- Strategy Catalog with the reversal/momentum replication, the registered
  cross-sectional Top-N backtest strategy, and a mean-reversion Top-N strategy.
- Reversal/momentum replication runs persist as local `replication-*` artifacts
  with a dedicated detail page.
- Backtest engine controls: rebalance frequency (every bar / weekly / monthly),
  per-symbol weight cap, API-level sector cap when a sector map is supplied,
  and per-name return attribution.
- Optional PostgreSQL run/news caches plus brief, AI daily-report, and paper
  account business facts with explicit `file` / `mirror` / `canonical` modes.

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
| `/hermes` | Reversible default, read-only COO workbench with Today, Tasks, Approvals, Unified Results preview, one safety strip, and a disabled composer. It reads local Hermes health/capabilities and saved sessions through a server-side official-API adapter, but submits no prompt and consumes no Hermes provider quota. |
| `/hermes/sessions` | GET-only list/detail view over real saved local-Hermes sessions; the bearer key remains server-side and the transcript composer stays disabled. |
| `/hermes/results` | Read-only unified catalog/detail projection over authoritative platform runs, experiments, candidate records, HQA artifacts, and exact run links. Preview is visible while `unifiedResultsCutoverAccepted=false`; no Hermes run is inferred from symbol/name similarity. |
| `/brief` | Live UI-assembled factual daily-brief preview and PostgreSQL archive control; saving is disabled if the authoritative paper-account source is unavailable. Its AI HOT GET may contact that upstream and best-effort mirror news/cache-audit rows to PostgreSQL; merely viewing the live preview does not create a brief snapshot. The server validates the complete factual-v1 schema and watermarks, but does not independently refetch every upstream source. |
| `/brief/[publicId]` | Immutable historical brief snapshot rendered from its stored payload and source watermarks. |
| `/data-explorer` | US equity historical data viewer. |
| `/factor-lab` | Current factor diagnostics surface; planned to become a run/detail analysis surface under the Hermes workbench. |
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
| `/ai-news` | Read-only AI HOT news feed with selected/all items, category/keyword/time-window filters, daily reports, original-source links, and no strategy/backtest/paper-account mutations. |
| `/polymarket` | Read-only prediction-market research page. |
| `/agent-studio` | Transitional **read-only** candidate inspection surface. It shows source plus exact digest-bound review evidence (legacy/global unbound audit is excluded), has no task submission or approve/reject controls, and links back to Hermes. A page-scoped redirect gate exists but is default-off. Repository-unavailable is distinct from an empty pool. Canonical candidates live under repo-anchored `data/agent_run/agent/candidates` (override only via `QS_AGENT_OUTPUT_DIR`; `QS_DATA_DIR`/CWD do not relocate them). |
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

Strict multi-symbol QFQ daily history for machine consumers:

```powershell
quant-system data prices --symbol AAPL --symbol SPY --start 2026-01-01 --end 2026-07-10 --provider futu --adjustment qfq --format json
```

This leaf emits exactly one JSON document on stdout, uses no local/sample
fallback, and does not persist OHLCV or initialize the option DuckDB cache.
Dates must be `YYYY-MM-DD`; the window is capped at 500 dates including both
endpoints. Invalid settings/requests and OpenD connect/query failures return a
typed JSON error with a nonzero exit. `QS_FUTU_REQUEST_TIMEOUT_SECONDS`
controls both initial connection and request deadlines.

Important constraints:

- No Futu trade context.
- No account unlock.
- No order placement.
- No broker execution.

## Read-only Hermes Artifact Shelf

`GET /api/hermes/artifacts?limit=20` reads HQA's versioned, rebuildable
`artifacts/hermes-feed/manifest.v1.json`. Schema 1.0 keeps exactly three sources
(`portfolio_risk`, `prediction`, `market_foresight`); schema 1.1 requires exactly
six by adding `weekly_review`, `opportunity_summary`, and `automation_status`.
The `/hermes` page renders all six artifact kinds. The platform never parses
raw HQA JSONL, writes HQA state, enables the Composer, or calls
`POST /api/agent/tasks`.

The catalog reports stable `available`, `empty`, `degraded`, or `unavailable`
states, validates the manifest, limits file size, and does not expose local paths
or raw exceptions. Configure it with:

```text
QS_HERMES_ARTIFACT_FEED_PATH=/absolute/path/to/manifest.v1.json
QS_HERMES_ARTIFACT_FRESHNESS_BUDGET_SECONDS=10800
QS_HERMES_ARTIFACT_MAX_FUTURE_CLOCK_SKEW_SECONDS=300
QS_HERMES_ARTIFACT_MAX_MANIFEST_BYTES=4194304
```

The default path resolves to the sibling `Hermes-quant-agent` repository. A
source may legitimately be `empty` while other source cards remain healthy.
Full 9H scheduling and outbound delivery run in HQA; this platform remains a
read-only consumer and adds no Hermes scheduler, outbound worker, POST route,
or database migration.

Interactive options pages include a short-lived in-process cache, a local
DuckDB-backed Futu option quote cache, and a one-time retry for Futu rate-limit
responses. Broad daily scans should still be scheduled and expected to run
slowly under Futu pacing.

## Optional PostgreSQL Business Facts

Backtest, factor, paper-run, and replication artifacts remain files under
`data/api_runs/<kind>/<run_id>/`; PostgreSQL only indexes those run records.
The same optional database stores AI HOT cache rows, immutable brief snapshots,
owner-scoped AI daily reports, and the persistent paper account's simulated
ledger/current state. It never stores broker credentials or live orders.
`QS_DATABASE_ENABLED` defaults to `false`; paper mode defaults to `file`.

Paper-account persistence has three explicit modes:

- `file` (default): local `account.json` is authoritative; PostgreSQL account
  reconciliation is not applicable.
- `mirror`: files remain authoritative; API/CLI/operations writes then update
  PostgreSQL best-effort. A database failure leaves the file mutation intact
  and surfaces a warning.
- `canonical`: PostgreSQL is authoritative for load/open/save/reset. Mutations
  fail closed when the database is unavailable; the factory never silently
  changes the configured mode to file. If the canonical account is absent,
  ordinary GET/mutation paths return `409 paper_account_bootstrap_required`;
  they never create a replacement account in an unbackfilled database.

All paper-account entrypoints use the same repository factory. Account IDs are
centrally validated before they can become a filesystem path or database key;
the repository key must also match the payload account ID. API snapshot reads
and `quant-system paper account-show --format text|json` share
`PaperAccountSnapshotReader`. In file/mirror mode a missing account is reported
without creating directories, locks, or a new account; canonical mode returns
the explicit bootstrap error. A corrupt primary may be read from a valid backup,
but read-only paths never rename or repair files; repair happens only on a locked
mutation path.

Paper-account API responses add `storage_mode`, `stale`, `warnings`, and a
structured `reconciliation` object. Reconciliation reports `in_sync`,
`different`, `unavailable`, or `not_applicable`, with summary hashes and typed
differences for raw state, account materialized columns, full ledger rows,
positions, pending orders, and latest snapshot state/integrity/freshness. These
fields are diagnostic evidence; they do not authorize a mode switch.

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
QS_PAPER_ACCOUNT_DB_MODE="file"  # file | mirror | canonical
```

On startup the backend applies `scripts/sql/*.sql` in lexical order. Migrations
003/004 create 11 business tables: root user, brief issue/snapshot/source,
AI daily reports, and six paper-account tables for account, ledger, pending
orders, current positions, and position snapshots. Migration 005 adds five
Hermes transport-ledger tables for schema metadata, commands, events, outbox,
and exact run links. Together with migration 001's run index and migration
002's two AI-news cache tables, migrations 001–005 define 19 `quant_system` tables.
Migration 006 source adds an independent workflow-binding schema-meta table and an
append-only exact command-to-HQA binding table, making the source target 21 tables;
it is **code accepted but not live applied**, so the current live database remains at
migration 005 / 19 tables until separately authorized.
There is no general `schema_migrations` ledger; the SQL
files are idempotently replayed in lexical order. Startup also backfills the
file-based run index and prunes index rows whose files were removed. If
PostgreSQL is down, the first probe is short and later failed requests use a
brief cooldown window while continuing to read local files or live upstreams.
Healthy PostgreSQL connections may proceed concurrently. Check it with:

```powershell
curl http://127.0.0.1:8765/api/health   # database.reachable should be true
```

Run the optional PostgreSQL integration test against a throwaway database, not
your usual `quantplatform` database:

```powershell
$env:QS_TEST_DATABASE_URL='postgresql://quant:quantpass@127.0.0.1:5432/quantplatform_codex_tmp'
python -m pytest tests/test_runs_repository_postgres.py tests/test_api_brief_persistence.py tests/test_paper_account_postgres_repository.py -q -m pg
```

The test may create the target database when its name is clearly temporary
(`*_tmp` or containing `test`). This keeps its prune checks away from your
normal run index.

The `psycopg` driver ships with the `api` extra, and the connection URL is
masked in `/api/settings`. See
[docs/architecture/database_cache_plan.md](docs/architecture/database_cache_plan.md).

The brief archive uses the same database: `POST /api/brief/issues/generate`
writes an immutable version, `GET /api/brief/issues/latest` resolves the latest
issue, `GET /api/brief/issues/{public_id}` reads a stored issue, and
`/brief/{public_id}` renders it. Database-unavailable paths fail explicitly
instead of fabricating history.

## AI News Research Feed

`/ai-news` is a local FastAPI proxy for AI HOT public endpoints. The frontend
only calls `/api/news/aihot/*`; the backend adds the browser-style User-Agent
required by AI HOT, normalizes responses, and keeps the feature research-only.

Optional configuration:

```text
QS_AIHOT_ENABLED=true
QS_AIHOT_BASE_URL="https://aihot.virxact.com"
QS_AIHOT_TIMEOUT_SECONDS=8
QS_AIHOT_CACHE_TTL_SECONDS=120
QS_AIHOT_USER_AGENT="Mozilla/5.0 ..."
```

When `QS_DATABASE_ENABLED=true`, successful feed requests are mirrored into
`quant_system.ai_news_items`. If AI HOT is temporarily unavailable, the items
endpoint can return matching cached rows with a warning. The 003 migration also
creates `quant_system.ai_news_daily_reports`; the daily endpoint now writes
successful reports best-effort and can return same-date cached daily reports
with warnings when AI HOT is temporarily unavailable. The page never creates
trading signals, starts backtests, mutates the paper account, or calls broker
trading APIs. See [docs/guides/ai-news.md](docs/guides/ai-news.md) and
[docs/design/ai_news_integration_plan.md](docs/design/ai_news_integration_plan.md).

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
  `GET /api/paper/strategy-sleeves/ops/status`,
  `quant-system paper strategies create-execution`, and
  `quant-system paper strategies execute-pending` / `execute-due` /
  `ops-status`. Strategy GET/status reads are observational and never reconcile
  files; use the explicit recovery-only command
  `quant-system paper strategies recover-pending` for crash journals.
- Slice 9G adds a separate bounded observation command for exact causal audit:
  `quant-system paper strategies observations --from-date 2026-07-01
  --to-date 2026-07-12 --signal-id <signal_id> --limit 200 --format json`.
  It is CLI-only and strictly read-only: there is no HTTP route, account/provider
  access, recovery, mutation, scheduler or missed-opportunity calculation.

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

- [docs/INDEX.md](docs/INDEX.md)
- [docs/OVERVIEW.md](docs/OVERVIEW.md)
- [Previous frontend/Hermes Slice 0-8 record](docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md)
- [Local storage and PostgreSQL status](docs/architecture/database_cache_plan.md)

`docs/SYSTEM_DESIGN_RESEARCH.md`, phase delivery records, and audits are
historical design/evidence sources, not the current work queue.

Current handoff: D-31 Wave 3A/3B and read-only 3E-A are delivered and locally
accepted; 3C is a reconcile-only framework, not command dispatch. 3C.1's
Task/Attempt/payload exact-binding foundation is code accepted, while migration 006
is still pending live authorization/application. Wave 3D chat
remains fail-closed, and 3F provides only a default-off Agent Studio redirect
mechanism. The next implementation must close the explicit upstream/platform
write gates or prove parity before any legacy-page cutover; neither is silently
implied by an older backlog.

Current options docs:

- [docs/futu/futu_environment_setup.md](docs/futu/futu_environment_setup.md)
- [docs/futu/futu_options_data_provider.md](docs/futu/futu_options_data_provider.md)
- [docs/options/options_screener_learning.md](docs/options/options_screener_learning.md)
- [docs/options/buyside_strategy_learning.md](docs/options/buyside_strategy_learning.md)
- [docs/options/local_alphagbm_tools.md](docs/options/local_alphagbm_tools.md)
- [docs/delivery/phase_14_delivery.md](docs/delivery/phase_14_delivery.md)

Paper replication:

- [docs/replications/reversal_momentum_replication.md](docs/replications/reversal_momentum_replication.md)

AI News:

- [docs/guides/ai-news.md](docs/guides/ai-news.md)
- [docs/design/ai_news_integration_plan.md](docs/design/ai_news_integration_plan.md)

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
