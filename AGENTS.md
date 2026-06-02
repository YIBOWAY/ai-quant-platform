# AGENTS.md

This file is for AI agents working in this repository. Keep user-facing replies
plain and concise. Do the technical work rigorously, verify before reporting,
and avoid claiming completion without running the relevant checks.

## Project Structure

```text
src/quant_system/
  api/                    Local FastAPI API and route modules.
  backtest/               Equity backtest engine and reports.
  config/                 Settings, paths, safety flags, provider config.
  data/                   Equity market data providers and schemas.
  execution/              Paper trading, order manager, paper broker.
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

## Optional PostgreSQL Run Index

Backtest/factor/paper runs are file-based under `data/api_runs/`. An optional
PostgreSQL index (`storage/database.py`, `storage/runs_repository.py`,
`scripts/sql/001_runs_index.sql`) speeds up listing. Off by default; controlled
by `QS_DATABASE_ENABLED` / `QS_DATABASE_URL` / `QS_DATABASE_CONNECT_TIMEOUT_SECONDS`
/ `QS_DATABASE_AUTO_MIGRATE`. The API must keep working with the database off or
unreachable (filesystem fallback). Tests must not touch a real database
(`tests/conftest.py` forces it off). Never run `npm run build` while the
frontend dev server is running — they share `src/frontend/.next` and the build
corrupts the dev server.

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

Use the existing conda environment for Python commands:

```powershell
conda activate ai-quant
```

When installing Python packages, prefer the Tsinghua mirror:

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...
```

## Run Backend

Preferred CLI wrapper:

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

Equivalent direct FastAPI start:

```powershell
conda activate ai-quant
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

Health check:

```powershell
curl http://127.0.0.1:8765/api/health
```

## Run Frontend

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

Open:

```text
http://127.0.0.1:3001
```

## Tests, Lint, Typecheck, Build

Backend tests:

```powershell
conda activate ai-quant
python -m pytest -q
```

Backend lint:

```powershell
conda activate ai-quant
ruff check src/quant_system tests
```

Frontend lint:

```powershell
npm --prefix src/frontend run lint
```

Frontend build and type validation:

```powershell
npm --prefix src/frontend run build
```

Browser smoke tests:

```powershell
cd src/frontend
$env:PW_E2E="1"
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
