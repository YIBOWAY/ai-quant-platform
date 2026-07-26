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
- **Agent v0.2 final-source addendum (2026-07-26):** the current release
  branch contains migrations 016–024, private candidate admission and sealed
  real-flow evidence, PostgreSQL-only release/cutover authority, managed
  external-session exact-message fork with selected plus Hermes-resolved
  lineage, durable conversation-root/resolved-run-tip identity, crash-safe
  approval/stop outcomes, a browser Run-stop control with same-action replay,
  natural-language paper research entry, and browser Gate 1 exact-source
  review. Full-suite JUnit evidence has a separate bounded 8 MiB allowance;
  logs, receipts and manifests remain capped at 4 MiB. The dated V4–V8 notes below are historical
  provenance, not the current queue. Apply 016–024 only in order after backup and isolated
  replay. Never infer live migration, connector, candidate, stamp, cutover or
  `chat_write_ready` state from this file: query PostgreSQL metadata, runtime
  identities, the effective release gate and health in the current operator
  window. Public cutover is never a prerequisite for private candidate E2E.
  Release order is full/focused tests -> live migration -> sealed test
  preflight -> private candidate -> connector -> real browser flows -> verified
  evidence -> candidate accept -> release stamp/cutover -> smoke/rollback.
  Throughout this product slice, `paper_trading=true`,
  `live_trading_enabled=false`, `kill_switch=true`, and zero orders are
  invariant.
- The active cross-repo roadmap lives in
  `/Users/sunyibo/programs/Hermes-quant-agent/docs/design/2026-07-01-roadmap-phases-0b-4.md`.
- HQA Slices 9A-9G, the read-only mini 9H artifact shelf, full 9H
  automation/notifications, and D-31 Wave 2 Scene-B are delivered. The real
  Scene-B flow completed final receipt -> Gate 3 prepare -> human diff/commit ->
  reviewed/cleanup, and promoted commit `524e791` is merged. The professional
  Hermes default shell now includes an official-API persisted-session read
  surface (`sessionRead=true`) through a server-side GET-only BFF. D-31 Wave 3
  has also delivered migration 005's durable command/event/outbox/run-link
  ledger, a deterministic **reconcile-only** connector-worker framework, and
  the read-only Unified Results catalog/detail UI. This does not prove command
  dispatch: real Hermes chat/provider evidence, Hermes approval mutations,
  exact Hermes-run links, full results cutover, and legacy-page retirement
  remain blocked behind independent evidence gates.
  Slice 9E lives in HQA and reuses Slice 9D's price seam. Slice 9D's
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
- Later frontend convergence should fold `/factor-lab`, `/backtest`,
  `/experiments`, and `/agent-studio` into the Hermes workbench only after
  approval and result-evidence parity. The delivered Hermes Approvals surface
  is read-only (`approvalMutations=false`); mutations stay disabled until a
  bridge/approval plan lands.
  The retained `/agent-studio` route is also read-only candidate inspection:
  it must not mount `AgentTaskForm` or expose task/review controls.
- The current Hermes transport is the official API Server on explicit HTTP
  loopback (default `127.0.0.1:8642`), not the drifted old TUI contract. The
  session pages read through the platform API/BFF and must never receive the
  full-authority Hermes Bearer key. The key is loaded server-side from an
  owner-only regular file. Loopback is a network boundary, not OS-user auth;
  while this local platform has no user authentication, bind it only to
  `127.0.0.1`/`::1`. Health/capability/session reads do not call a provider.
- Migration 005 now provides the PostgreSQL command/event/outbox/run-link
  ledger and schema metadata, including tested claim/lease/heartbeat primitives.
  Migration 006 is a separate exact workflow-binding schema; until its live
  readiness and the HQA authority binding are verified, every claim path must
  fail closed. Its presence in source never authorizes the runnable worker to
  claim or dispatch.
  **Live 006/007 applied 2026-07-21** on `quantplatform` after explicit authorization
  (backup + idempotent replay + readiness evidence in
  `docs/audits/2026-07-21-v4-live-migrate-006-007.md`). Do **not** treat schema
  readiness as write authorization. V4 006 is Scheme A:
  `UNIQUE(attempt_id)` + `UNIQUE(task_id, attempt_number)`; readiness refuses the
  obsolete `UNIQUE(task_id)`-only shape. Additive 007 is the session registry.
  `hermes/composer_readiness.py` is the single blocker/readiness surface.
  **Public** write standing default OFF (V8-M6 hermetic G7/G8 surface ACCEPT@a2953cb; operator open is explicit; full V8 release stamp still requires fresh auth; `release_authorized=false`). Local single-user may open
  `QS_LOCAL_MUTATION_ENABLED` / `QS_LOCAL_MUTATION_COMPOSER_OPEN` (and FE
  `QS_HERMES_CHAT_ENABLED` draft) under the trading kill switch — that is local
  dark enablement, not public cutover and not Plan-V6 full-UI acceptance.
  Typed `research.*` actions remain fail-closed for browser research submit until
  their Gate; L2a uses `conversation_turn` + payload ref claim path (migration
  `008_l2a_conversation_turn_claim.sql`) instead of putting prompts on `/act`.
  Cross-repo status (2026-07-23): V0 formal DONE (`release_authorized=false`),
  V1 code DONE / V1.2A live role+RLS PARTIAL, V2 source accepted / live durable
  OFF, V3 HQA dark install DONE, **V4 live schema ACCEPT**, **V5 dark
  claim/dispatch ACCEPT**, **V6 local dark enablement ACCEPT**, **L2a-Send
  M1+M2 ACCEPT**, **L2b-Observe M1+M2 ACCEPT**, **L3a-Transcript M1 ACCEPT**,
  **L3b-Transcript-Polish M1 ACCEPT**, **L4a-Task-Drawer M1 ACCEPT** (command
  Activity from workspace `commands[]`; Task/Attempt authority still empty),
  **L4b-SSE-Follow M1 ACCEPT** (BFF `GET …/follow/stream` + shared FE follow
  spine; SSE preferred / poll fallback; Activity consumes spine; no assistant
  bodies on follow), **L5a-Hermes-Approval-Observe M1 ACCEPT** (snapshot
  `approvals=[]` + `command_approval=unavailable`; Composer waits on shared
  spine; read-only Approvals panel; no allow/deny write; ≠ Gate 1/2/3),
  **L5b-Authority-Projection M1 ACCEPT** (honest empty Task/Attempt/Run/result
  slots + health on spine; read-only Authority panel; no invented HQA rows),
  **L5c-Workbench-A11y M1 ACCEPT** (FE-only shell a11y: workbench region landmark,
  responsive pad, collapse/long-id contracts, composer focus-visible;
  marker `data-hermes-workbench-a11y=l5c-m1`; no mutation routes).
  **V7a–V7g-A-M1 ACCEPT** (exact allow_once|deny CAS + hermetic respond_approval release/signal + hermetic Run-scoped stop with §5.5 layered receipt + durable approval projector + Domain Gate 1/2/3 surfaces + typed results on spine + hermetic Vertical A options bind → Task/Attempt/Run + typed result → completed|completed_degraded; sample/real fail-closed; no always-allow; Gates ≠ command-approval ≠ results; no Task invention from conversation.turn; no catalog-on-spine; zero live Futu/orders). Next: V7g-A-M2 live Futu RO → V7g-B;
  full operator V8 release stamp still closed (`release_authorized=false`; standing public default OFF). See HQA `docs/README.md`, L2a ADR, and platform audits
  `docs/audits/2026-07-21-v5-dark-supervised-dispatch.md` /
  `docs/audits/2026-07-21-v6-local-off-to-on.md`.
  Connector worker CLI **defaults to `reconcile_only`** (LISTEN/NOTIFY + scan +
  expired-lease). `--mode supervised_dispatch` claims with a real
  `HttpHermesDispatchAdapter` (or injected port in tests). Empty queue must
  never call an LLM. Do not implement Hermes cron prompt polling as a queue.
  Platform must never `import hqa`; Intent Payload Store I/O goes through the
  subprocess CLI port (`QS_INTENT_PAYLOAD_*`). Owner gate is loopback cookie +
  CSRF only; default `accepted_origin` is first CORS entry
  (`http://127.0.0.1:3001` — FE port). FE workspace client uses same-origin
  `/api/*` rewrites, not absolute `:8765` with credentials omit. Messages ids
  must be Hermes API sessions (`run_…`); never registry `web_` / workspace `wm_`.


## Core Engineering Rules

### Data, research, and factors

- Explicit providers are strict: `sample`, `futu`, or `tiingo`. An unavailable
  requested real provider must fail clearly, never silently become sample.
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
