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
  brief/                  Deterministic daily-brief snapshots and repository.
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
  storage/                DuckDB cache + PostgreSQL migrations/helpers/run index.
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
  superpowers/plans/      Active implementation plan and historical plan inputs.

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
- HQA Slices 9A-9G, the read-only mini 9H artifact shelf, and full 9H
  automation/notifications are delivered. There is no selected next slice;
  future frontend backlog work needs a new product decision and an independent
  bite-sized plan. Slice 9E lives in HQA and reuses Slice 9D's price seam. Slice 9D's
  `data prices` seam is strictly read-only Futu/QFQ/1d JSON, capped at 25
  symbols and 500 calendar days, with no sample/local/Tiingo/Longbridge
  fallback. The platform 2026-07-08 frontend plan is the Slice 0-8 record and
  future UI backlog.
- The platform consumes Hermes feed schema 1.0 with exactly three sources and
  schema 1.1 with exactly six: risk, prediction, foresight, weekly review,
  opportunity summary, and automation status. Whole-feed freshness is 10,800
  seconds. Full 9H scheduling and outbound delivery live in HQA; this platform
  has no Hermes scheduler, outbound worker, new POST route, or new database
  migration for that slice.
- The HQA 2026-07-07 Phase 1a-4 plan is superseded implementation material.
  Do not follow its task templates directly.
- `docs/phases/phase_15_iteration_roadmap.md` is reference material only; do
  not continue it as a standalone product roadmap.
- Candidate factors must not reach resident paper/live paths from `.candidate`
  files. One-shot research backtests may explicitly load approved candidates;
  paper sleeve allocation requires promoted, registered, tested factor code.
- Future frontend convergence should fold `/factor-lab` and `/agent-studio`
  into the Hermes workbench while preserving approval UI and removing platform
  LLM/task-running affordances.


## Core Engineering Rules

### Data, research, and factors

- Explicit providers are strict: `sample`, `futu`, or `tiingo`. An unavailable
  requested real provider must fail clearly, never silently become sample.
- Factor development is code-first. Register backend factor code; do not add a
  free-form frontend expression builder.
- A runnable backtest strategy needs both registry metadata and a pipeline
  builder. Paper-account rebalance support is a separate, explicit capability.
- Candidate files may be loaded only for explicit one-shot research. Resident
  paper/live paths use promoted, registered, tested factors only.
- Hermes generates source artifacts. The platform may ingest/review/promote
  them deterministically, but must not revive a platform-side LLM runner.

### Storage and PostgreSQL

- Research run artifacts remain file-backed under `data/api_runs/`; optional
  PostgreSQL run rows are an index, not a replacement for their artifacts.
- All paper-account API, CLI, and operations paths must use
  `build_paper_account_repository`; never instantiate a storage backend to
  bypass the selected `file` / `mirror` / `canonical` mode.
- Mirror writes are best effort and file-authoritative. Canonical mode is
  database-authoritative and must fail closed for mutations when PostgreSQL is
  unavailable. A missing canonical account requires explicit backfill; ordinary
  GET/mutation paths must not bootstrap a replacement account. Never silently
  change modes.
- Repository `load` is observational. Corrupt-file preservation/restoration
  belongs to a locked mutation path, never an unlocked snapshot/CLI read.
- API/CLI/HQA paper-account observations must use `PaperAccountSnapshotReader`
  through the repository factory; do not read account JSON, Parquet snapshots,
  or PostgreSQL audit snapshots as an alternate current-account source.
- Treat `PaperAccount.ledger` as the account event fact. Migrations/backfills
  must preserve ledger, pending orders, current positions, ownership, and
  audit snapshots rather than copying only cash/positions.
- SQL migrations live in `scripts/sql/`, run in lexical order, and must be
  idempotent. Default tests must not access the user's database; PostgreSQL
  integration tests require an explicit throwaway `QS_TEST_DATABASE_URL`.

### Paper and execution safety

- Persistent paper-account mutations use real market prices only: Futu first,
  then an explicitly real cached/last-close source. Never fill with sample data.
- The persistent-account freeze and global replay kill switch are different
  controls; do not conflate them.
- Strategy-sleeve signals do not auto-execute. Preserve cash/lot ownership,
  journal/recovery semantics, and explicit processing gates.
- `paper strategies observations` is a CLI-only, bounded fact read. It must not
  enter account repository/provider/recovery paths, mutate files, or compute
  whether an HQA opportunity was missed.
- No paper feature authorizes broker/live execution.

### Frontend and Hermes

- Follow the active slice in the frontend/Hermes plan. Old P0-P4 templates are
  archived inputs, not executable instructions.
- `lib/navConfig.ts` is the navigation route/order source of truth. Keep copy
  localized in the rendering components unless the active plan changes it.
- `/hermes` is a read-only artifact shelf backed by `GET /api/hermes/artifacts`.
  It renders risk, prediction, foresight, weekly, opportunity, and automation
  artifacts; there is no `POST /api/agent/tasks`, fake async job, or enabled
  composer.
- Keep `/factor-lab` and `/agent-studio` until approval and evidence parity is
  proven; do not add early redirects or delete deep links.
- Server reads use the existing `lib/api.ts` pattern; client mutations use
  `lib/apiClient.ts` / TanStack Query. Preserve additive API compatibility.

### Deep references

| Area | Read before changing |
|---|---|
| Current route/status | `docs/INDEX.md` and the active frontend/Hermes plan |
| Storage/PostgreSQL | `docs/architecture/database_cache_plan.md` |
| Paper account | `docs/guides/paper-trading.md` |
| Strategy sleeves | `docs/execution/paper_strategy_sleeves.md` |
| Backtests/strategies | `docs/guides/backtester.md`, `docs/guides/strategy-catalog.md` |
| AI News | `docs/guides/ai-news.md` |
| Futu/options | `docs/futu/`, `docs/options/` |
| Prediction markets | `docs/polymarket/` |

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
