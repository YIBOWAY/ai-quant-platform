# Database Cache Plan

Status: two local storage layers are implemented — (1) a DuckDB-backed Futu
options cache, and (2) an optional PostgreSQL **run index** over file-based
backtest / factor / paper runs.

The DuckDB options cache lives in `src/quant_system/storage/options_cache.py`
and persists Futu option quote windows to `data/futu/options_cache.duckdb` when
`QS_FUTU_USE_CACHE=true` (the default).

The PostgreSQL run index lives in `src/quant_system/storage/database.py` and
`src/quant_system/storage/runs_repository.py`, with schema in
`scripts/sql/001_runs_index.sql`. It is **optional and off by default**; when
enabled it indexes existing file-based runs for fast listing, and the API falls
back to scanning the filesystem whenever the database is disabled or unreachable.

## PostgreSQL Run Index (implemented)

Files under `data/api_runs/<kind>/<run_id>/metadata.json` remain the source of
truth. The run index is a queryable mirror, not a replacement.

- Settings (`config/settings.py` → `DatabaseSettings`, env prefix `QS_DATABASE_`):
  - `QS_DATABASE_ENABLED` (default `false`)
  - `QS_DATABASE_URL` (e.g. `postgresql://quant:quantpass@127.0.0.1:5432/quantplatform`;
    held as a secret and masked in `/api/settings`)
  - `QS_DATABASE_CONNECT_TIMEOUT_SECONDS` (default `5`)
  - `QS_DATABASE_AUTO_MIGRATE` (default `true`)
- Schema: a single table `quant_system.runs` (`kind`, `run_id`, `source`,
  `created_at`, `indexed_at`, `artifact_path`, `metadata` JSONB), keyed by
  `(kind, run_id)`. `kind` is `backtest`, `factor`, or `paper`.
- Startup (`api/server.py` lifespan) runs migrations then **reconciles**:
  backfills present file runs and prunes index rows whose files are gone
  (self-healing against listing a run whose detail would 404).
- List endpoints (`/api/backtests`, `/api/factors/runs`, `/api/paper`) read
  DB-first and fall back to the filesystem on any DB error. Run endpoints index
  each new run fire-and-forget (a DB failure never blocks the run).
- `/api/health` reports a `database` block (`enabled`, `reachable`, `error`).
- Tests force `QS_DATABASE_ENABLED=false` via `tests/conftest.py` so the suite
  never writes to a shared container.

Uses `psycopg` directly (no ORM, no connection pool — short-lived per-operation
connections, matching the DuckDB cache style).

## Why This Exists

Interactive Futu options pages use a short-lived in-process cache, a one-time
retry for rate-limit responses, and now a local DuckDB cache for successful
option quote windows. The DuckDB cache persists across backend restarts and is
shared by Options Screener, Options Radar, Buy-Side Options Assistant, and local
options tools that call the Futu provider.

The cache layer exists so the platform can:

- Reuse recently fetched option chains and snapshots.
- Reduce repeated Futu OpenD requests.
- Keep Options Screener, Options Radar, and Buy-Side Options Assistant
  consistent for the same ticker and timestamp.
- Store scan results in a queryable format for the frontend.
- Preserve read-only safety boundaries.

## Recommended Storage Split

Use a hybrid local storage model:

| Storage | Best For |
|---|---|
| PostgreSQL | Metadata, option-chain cache index, option quote snapshots, radar runs, API task records, provider request logs. |
| Parquet / DuckDB | Large OHLCV history, replay datasets, wide analytical tables, batch research. |
| JSONL | Portable fixtures and small append-only research artifacts. |

PostgreSQL is a good fit for the user's local Docker setup, especially for
querying latest option-chain snapshots and serving frontend views. It should not
replace Parquet / DuckDB for every large historical research dataset.

The first shipped cache uses DuckDB to avoid requiring Docker or a database
server for local users.

## Proposed Tables

Minimal first version:

| Table | Purpose |
|---|---|
| `provider_requests` | One row per provider call, including provider, symbol, endpoint type, status, error code, and fetched time. |
| `equity_bars` | Optional cached OHLCV rows for small frontend windows. |
| `option_chain_snapshots` | Snapshot metadata: ticker, expiration range, option type, provider, fetched time, cache expiry. |
| `option_contract_quotes` | Normalized option rows tied to a chain snapshot. |
| `vix_history` | VIX/VIX3M cache rows if moved out of CSV later. |
| `options_radar_runs` | Daily radar run metadata. |
| `options_radar_candidates` | Radar candidate rows for API and frontend filtering. |

Implemented in the first DuckDB pass:

- `option_chain_snapshots`
- `option_contract_quotes`

## Cache Policy

Suggested safe defaults:

- Equity daily bars: expire after 24 hours for recent ranges; never refresh
  automatically inside tests.
- Option chains: expire after 15 minutes during market hours, longer outside
  market hours.
- Option snapshots: expire after 5 minutes during market hours.
- Radar runs: immutable by `run_date` unless the user explicitly reruns the scan.
- Provider errors: store typed error codes to help diagnose OpenD and rate-limit
  issues.

All cache entries must record:

- `provider`
- `ticker`
- requested date or expiration window
- `fetched_at`
- `expires_at`
- normalized source label
- error code if the request failed

## API Behavior

Provider-backed endpoints should use this order:

1. Return fresh cache if present.
2. If cache is stale or missing and provider is explicitly requested, fetch from
   the read-only provider.
3. Write successful normalized data to cache.
4. Return typed provider errors without raw tracebacks.

No endpoint should add order placement or broker execution.

## Suggested Implementation Phases

1. Add database settings for an optional PostgreSQL-backed mode. (implemented as
   `QS_DATABASE_ENABLED`, `QS_DATABASE_URL`, `QS_DATABASE_CONNECT_TIMEOUT_SECONDS`,
   `QS_DATABASE_AUTO_MIGRATE`; the schema name `quant_system` is fixed in SQL, not
   a setting)
2. Add a small storage package: (implemented)
   - `src/quant_system/storage/database.py` (PostgreSQL connect + migrations)
   - `src/quant_system/storage/runs_repository.py` (run index, DB-first + fallback)
   - `src/quant_system/storage/options_cache.py` (DuckDB option cache)
3. Add plain SQL migrations under `scripts/sql/`. (implemented:
   `scripts/sql/001_runs_index.sql`)
4. Cache Futu option-chain and snapshot results first. (implemented for option
   quote windows)
5. Point Options Screener and Buy-Side Options Assistant at the cache-first path.
   (implemented through the shared Futu provider)
6. Move Options Radar JSONL reads behind a storage facade while preserving JSONL
   export for portability.
7. Add frontend-visible cache metadata: source, fetched time, and cache age.

## Dependency Guidance

Recommended minimal dependency:

- `psycopg[binary]` for PostgreSQL access.

Avoid adding SQLAlchemy or Alembic in the first pass unless the project starts
needing complex schema migrations. Plain SQL is enough for the first local cache
module.

## Safety Rules

- The database stores market data and research outputs only.
- Do not store secrets, account unlock state, broker credentials, private keys,
  wallet data, or live order instructions.
- Do not add Futu trading context.
- Do not add real order tables.
- Keep all cache-backed outputs labeled as research data.

## Remaining Open Questions

- PostgreSQL is now optional and off by default; the run index points at the
  local Docker container `quantplatform-db` only when `QS_DATABASE_ENABLED=true`.
  Whether to also move the options cache and radar runs into PostgreSQL is still
  open.
- Whether TimescaleDB is available in the user's local Docker image.
- The run index stores the full run metadata as JSONB. Whether option quote
  snapshots (if moved to PostgreSQL later) should be compressed JSONB or fully
  normalized rows is still open. The first DuckDB implementation stores
  normalized option quote rows.
