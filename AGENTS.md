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
- **Current local operations snapshot (2026-08-09):** normal Mac startup is
  `bash scripts/local_mac_stack.sh start`. It owns Docker readiness, the
  production frontend build, and six user LaunchAgents (Hermes, backend,
  frontend, connector, factor automation, Asia Radar refresh). Do not bind service lifetime to an
  AI-tool terminal.
  Hermes replacement requires a stable old-PID/port quiescence window.
  Local trust bypasses identity ceremony only; trust cookies are mode-bound,
  readiness reports `admission_mode=local_trust` without candidate identity,
  while `live_trading_enabled=false`, `kill_switch=true`, migration authority,
  and manual live gates remain independent. D-33 factor automation is a
  separate, source-default-OFF dual-Flag path and may create only `paper_only`
  qualifications; the inspected owner runtime enabled all four flags on
  2026-08-10 after full acceptance, and still cannot grant live eligibility.
- D-34 is currently source-only on the paired `codex/d34-mandate-paper`
  worktrees. It adds a durable 30-day Mandate, pinned open Docker RD-Agent/Qlib
  runtime, Futu snapshot, Platform execution replay, Artifact Registry and real
  paper canary loop. Do not apply migration 030–032 to the formal DB or set
  `QS_D34_WORKER_ENABLED=true` before a separate operator window; an installed
  disabled LaunchAgent performs no database, Docker, or order work.
- The only Platform operations authority for the Agent v0.2 local stack is
  [`docs/runbooks/agent-v0-2-local-stack.md`](docs/runbooks/agent-v0-2-local-stack.md).
  Other docs may explain a component, but must link there instead of copying a
  migration, restart, readiness, or restore ladder.
- **Checkout role boundary:** edit, test, commit, and push only from the primary
  checkout or a purpose-named source worktree under
  `/Users/sunyibo/programs/.worktrees/`. The checkout under
  `Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform` is a
  deployment mirror: fetch plus fast-forward only, with no direct development,
  commit, rebase, or push. Follow the source/deployment contract in the local
  stack runbook.
- **Source/live boundary (read-only check, 2026-07-31):** the repository change
  set contains ordered migration source 016–028. Live `quantplatform` exposes
  the inspected 016–027 markers and does not expose the 028 marker. Migration
  028 is a source/change set; this file does not prove whether it is committed,
  installed, isolated-replayed, live-applied, or authorized. The running
  backend at that dated check also predates the new
  provider-free `/api/safety/effective` route. Never promote source, tests,
  backup, replay, or a migration file's presence into a live/runtime claim.
- **Completed-window boundary (read-only check, 2026-08-01):** the authorized
  operator window subsequently observed one 028 marker at version 1, exact two
  `ENABLE ALWAYS` binding triggers, schema fingerprint
  `e3f713ac05a1a990cfa9be45157e880e06709c425a4883736544d8f2b626f33a`,
  live readiness plus `/api/safety/effective`, and a zero-order AlphaZeroBeta
  retest whose Web/session/dispatch/provider/approval/durable-Run/PDF/persistence
  mechanics passed. Its research verdict is nevertheless unverified and not
  accepted: no runtime-enforced, digest-bound `hqa.paper_intake/v1` receipt and
  verifier existed, so factor/backtest/Gate/result work was not evaluated. The
  candidate was then revoked, the connector returned to `reconcile_only`, and
  public release remained OFF. This dated observation does not authorize
  reapplying 028 or opening another window; use the local-stack runbook and the
  cross-repo AlphaZeroBeta audit for evidence.
- Backend startup never applies migrations. Keep
  `QS_DATABASE_AUTO_MIGRATE=false`; a future migration requires the explicit
  `quant-system migrate --apply --allow <exact-file>` operator path and fresh
  authorization. The 016–028 ladder is now historical for the current live
  database: because its 028 marker exists, every 028 plan/apply against that
  database must stop. The retained 028 commands may target only a newly created
  isolated pre-028 restore for rehearsal, never current live; any later
  migration needs its own review and authorization.
- Migration 029 was applied exactly once on 2026-08-10 after its own backup and
  isolated restore rehearsal. It is the append-only factor-automation
  promote/demote/daily-quota authority. Do not replay it. The automatic paper
  operator contract lives in the HQA repo at
  `docs/runbooks/full-automation-paper.md`.
- Migration 028 freezes the candidate write rail to the effective paper
  authority. For the root owner there must be exactly one canonical paper
  account, its ID must be `default`, materialized `kill_switch` must be true,
  and raw JSON `account_id`/`kill_switch` must exactly match those columns.
  Candidate Session/Command writes must bind the current paper-authority epoch;
  stale or ambiguous authority fails closed. Read this provider-free state via
  `GET /api/safety/effective`; it is observation, not release authorization.
- Keychain readiness is also fail-closed. HQA `probe` is non-creating, and
  ordinary `put`, `bind_resolve`, encrypt, Platform preflight, and connector
  checks must not create a key. Only a human operator, after checking the exact
  committed/installed runtime and preflight, may run HQA `initialize-key`, then
  rerun `probe`. Never expose initialization through the BFF, worker, skill, or
  an automatic retry.
- Private candidate admission is operator-controlled through
  `quant-system hermes candidate status|open|revoke`. `open` is short-lived,
  exact-runtime/schema/evidence bound, local-only, and does not open public
  write. On drift, failure, or abandonment, revoke the exact admission by CAS.
- Local single-user write requires all local mutation/composer settings, exact
  owner/CSRF gates, 028 readiness, effective paper safety, non-creating
  Keychain preflight, an active candidate or accepted release, and a fresh
  supervised connector. `chat_write_ready` is a local readiness field.
  `public_chat_write_ready`, `public_write_authorized`, and
  `release_authorized` remain separate; standing public posture is OFF.
- The active cross-repo roadmap lives in
  `/Users/sunyibo/programs/Hermes-quant-agent/docs/design/2026-07-01-roadmap-phases-0b-4.md`.
- HQA plans and Platform audits are delivery/history records, not live
  operations authority. Do not infer the next slice from old checkboxes or
  append new status ladders to historical Workbench design records.
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
- Canonical candidate root is `resolve_candidates_dir(resolve_agent_output_dir())`.
  Default agent output is the repo-anchored absolute path
  `<repo>/data/agent_run`; candidates live under
  `<repo>/data/agent_run/agent/candidates`. Override only via
  `QS_AGENT_OUTPUT_DIR` (or explicit injectable/CLI agent-output root). Process
  CWD and `QS_DATA_DIR` never relocate the candidate pool. API, CLI, one-shot
  loader, migration, and Gate 3 all share that resolver.
- Candidate reads surface mutually exclusive integrity states: `verified`,
  `migration_required`, and `corrupt`. `legacy_unbound` is non-authority:
  it never authorizes one-shot load, approval, or promotion. Until a separate
  human authorizes `agent migrate-candidates --apply` with an explicit
  `--backup-dir`, each new real migration stays dry-run-only. One bounded Wave 2
  migration was explicitly authorized and applied; that authorization does not
  carry forward to future candidates or conflicts.
- Gate 2 review is expected-digest plus `expected_status=pending` CAS with a
  non-empty note. HQA must pass human-supplied
  `candidate-id + expected-digest + expected-status=pending + note` and must
  never refetch/substitute observed values during approve.
- Scene-B Gate 1 is enforced in HQA, not inferred from a platform review: HQA
  persists the exact reviewed source digest/confirmation and binds it to the
  returned candidate ID plus manifest digest before its Gate 2 caller can
  approve. External source ingestion reads binary bytes, round-trips them
  unchanged into the candidate, and returns a verified `source_sha256` that HQA
  must match before binding. The raw platform review API is a Gate 2 primitive
  only; `agent list-candidates` is diagnostic and emits no approval command.
- Gate 3 public prepare requires `--candidate-id`, `--expected-digest`, and
  `--base-commit`; stdout is the four-field
  `{promotion_id, worktree, patch, manifest}` payload. Status/cleanup locate
  state only by `--promotion-id`; destructive cleanup needs durable reviewed-
  commit evidence or explicit `--abandon`. Prepare materializes only into an
  isolated managed review worktree and never commits, merges, pushes, or
  mutates unrelated main-worktree dirt. Active status must safe-read and hash
  the prepared patch, re-attest the exact three-file bytes/modes/dirty set/Git
  diff, and return manifest/patch/candidate/base/path provenance. A drifted
  prepared workspace is never reported as awaiting human commit.
- Experiment runs allocate `<name>-<UTC microseconds>-<12hex>` identities and
  atomically reserve both experiment and report directories. Collision means
  retry, never reuse or overwrite. Scene-B receipts must bind persisted config,
  summary and report to that unique namespace and reject synthetic providers.
- Legacy `/factor-lab`, `/backtest`, `/experiments`, and `/agent-studio`
  routes remain until separately approved parity/cutover. The retained
  `/agent-studio` route is read-only candidate inspection and must not mount
  task/review controls.
- The current Hermes transport is the official API Server on explicit HTTP
  loopback (default `127.0.0.1:8642`), not the drifted old TUI contract. The
  session pages read through the platform API/BFF and must never receive the
  full-authority Hermes Bearer key. The key is loaded server-side from an
  owner-only regular file. Loopback is a network boundary, not OS-user auth;
  while this local platform has no user authentication, bind it only to
  `127.0.0.1`/`::1`. Health/capability/session reads do not call a provider.
- `hermes/composer_readiness.py` is the single local/public blocker surface.
  Typed research actions remain fail-closed until their exact domain gates;
  ordinary chat uses `conversation_turn` plus the HQA payload reference and
  never places prompt text on `/act` or in PostgreSQL.
- Connector worker CLI defaults to `reconcile_only` (LISTEN/NOTIFY, scan, and
  expired-lease reconciliation). `supervised_dispatch` is allowed only inside
  the bounded local candidate/release window described by the local-stack
  runbook. Network I/O stays outside DB transactions; timeout is
  `outcome_unknown`, never blind retry. An empty queue makes zero provider and
  Hermes mutation calls. Do not use an LLM cron as a queue.
- Platform must never `import hqa`; Intent Payload Store operations use the
  closed subprocess port (`QS_INTENT_PAYLOAD_*`). Owner mutation is loopback
  signed cookie plus CSRF, not multi-user authentication. Frontend calls use
  same-origin `/api/*` rewrites. Message IDs must be Hermes API session IDs,
  never registry/workspace IDs.


## Core Engineering Rules

### Data, research, and factors

- Explicit providers are strict: `sample`, `futu`, or `tiingo`. An unavailable
  requested real provider must fail clearly, never silently become sample.
  `/asia-radar` is an Asia 12-market read-only radar over the fixed 12-ETF Futu
  universe; its dedicated API (`/api/asia-radar/overview`) requires
  `provider=futu`, uses an auditable `futu|futu_cache` provenance, and never
  reuses the generic `/ohlcv` sample fallback. Keep it free of PE/PB/ERP,
  crowding, and risk-list figures until real cross-market sources exist.
- Factor development is code-first. Register backend factor code; do not add a
  free-form frontend expression builder.
- A runnable backtest strategy needs both registry metadata and a pipeline
  builder. Paper-account rebalance support is a separate, explicit capability.
- Candidate files may be loaded only for explicit one-shot research after
  digest-bound approval re-verification. Resident paper/live paths use
  promoted, registered, tested factors only.
- Hermes generates source artifacts. The platform may ingest/review/promote
  them deterministically, but must not revive a platform-side LLM runner.
  Candidate publication is immutable after atomic publish; same-ID retries are
  idempotent only for the same manifest digest.
- Paper-intake acceptance is a runtime contract, not a skill/prompt convention.
  A succeeded Command/Run, provider calls, direct PDF/full-text reads, or skill
  instructions do not establish an accepted actionable/non-actionable verdict.
  Until a digest-bound `hqa.paper_intake/v1` receipt is enforced and verified at
  runtime, report the verdict as `unverified/not accepted` and downstream
  factor/backtest/Gate/result work as `not evaluated`.

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
- `/hermes` is the reversible default read-only COO workbench backed by
  `GET /api/hermes/artifacts` and the candidate read API. It renders Today,
  Tasks, Approvals, Results, risk, prediction, foresight, weekly, opportunity,
  and automation facts. `/hermes/sessions` additionally reads persisted Hermes
  sessions through the official-API GET-only BFF. There is no
  `POST /api/agent/tasks`, fake async job, approval mutation, or enabled
  composer.
- Keep `sessionRead=true` observational. The read-only Unified Results
  preview/catalog is visible, while `unifiedResultsCutoverAccepted=false`;
  `chat`, `execution`, `approvalMutations`, and `legacyRedirects` remain hard
  false until their independent evidence gates land. Read
  `docs/guides/hermes-sessions.md` before touching the bridge or deployment.
- “Read-only AI news” means no research/trading/account mutation; successful
  AI HOT GETs intentionally best-effort update the optional news item/fetch
  cache. `/brief` live rendering may therefore contact AI HOT and write cache
  rows even though it never creates a brief snapshot without the explicit save
  action.
- Keep `/factor-lab` and the read-only `/agent-studio` inspection route until
  approval and evidence parity is proven; do not delete deep links or restore
  legacy Agent Studio mutations. A page-scoped Agent Studio redirect may exist
  only as an independently reversible, default-off gate
  (`QS_HERMES_AGENT_STUDIO_REDIRECT_ENABLED=true`); do not enable it or any
  global legacy redirect without exact parity evidence and user approval.
- Server reads use the existing `lib/api.ts` pattern; client mutations use
  `lib/apiClient.ts` / TanStack Query. Preserve additive API compatibility.

### Deep references

| Area | Read before changing |
|---|---|
| Current route/status | `docs/INDEX.md` and the active frontend/Hermes plan |
| Storage/PostgreSQL | `docs/architecture/database_cache_plan.md` |
| Asia Radar | `docs/guides/asia-radar.md` |
| Paper account | `docs/guides/paper-trading.md` |
| Strategy sleeves | `docs/execution/paper_strategy_sleeves.md` |
| Backtests/strategies | `docs/guides/backtester.md`, `docs/guides/strategy-catalog.md` |
| AI News | `docs/guides/ai-news.md` |
| Futu/options | `docs/futu/`, `docs/options/` |
| Prediction markets | `docs/polymarket/` |

## Environment

On macOS, prefer the persistent project-owned stack for normal operation:

```bash
bash scripts/local_mac_stack.sh start
bash scripts/local_mac_stack.sh status
```

Use the manual Python/npm commands below only for foreground debugging.

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
