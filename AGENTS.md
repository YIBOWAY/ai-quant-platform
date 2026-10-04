# AGENTS.md

## 2026-09-20 Phase2 execution scope

The owner explicitly authorized the complete Phase2 in HQA's current v3.2 plan,
including evidence-backed automatic review/paper grading, local deployment and
document cleanup. This supersedes historical one-slice stops and repeated paper
approval within that scope, not the frozen data/validation requirements. Missing
evidence is a technical block, never implied approval or a redundant owner gate.
No live orders, remote push, production migration, manual paper cycle, historical
candidate bulk activation or deletion of real data/failure evidence is authorized.
Consult HQA's current implementation receipt for adoption, not this permission.

## 2026-09-09 standing Grok Bot research authorization

The owner explicitly authorized the Grok Bot research team, automated external
daily-formula intake, local backtests, bounded multifactor validation and simulated
activation of qualifying newly created versions, without repeated per-job approval.
The owner-only external intake policy controls this path. It may accept sourced
Bot-proposed whitelist expressions without inventing a same-chat session; it does
not require manual factor-code promotion. This scoped authorization supersedes the
older owner-ask-only/candidate-stop wording below for this intake, and permits the
specific StrategyDefinition calendar repair needed by this integration. Preserve
all automatic quality/cost checks, canonical candidate/account identity, original
paper calendars and live OFF. No historical-candidate batch activation, manual
paper-cycle, remote push, or live order authority is granted. User-facing wording
is 自动质检. See HQA `docs/runbooks/grok-bot-research-team.md` and the dated receipt.

Rules for AI agents working in this repository. Optimize for the user's explicit
result, keep complexity bounded, verify before reporting, and preserve unrelated
dirty work. Historical plans and audits are evidence, not an executable queue.

## Task Scope and Completion

- Explanation, review, and diagnosis requests produce findings; they do not by
  themselves authorize repairs. For an implementation request, complete the
  authorized local change and the relevant verification without stopping at a plan.
- Reuse authorization already given for the same scope. Ask only when missing
  information would materially change the result or the next action exceeds it.
  Checkout paths, runbooks, command examples, and readiness fields do not grant
  deployment, release, live-trading, or other external-action permission.
- Apply domain rules and read the references for the affected area. Finish when
  the requested result and relevant checks are complete; historical plans and
  owner-review/NEXT boundaries do not block unrelated, newly authorized daily work.

Recorded checkout context: the status, plan, migration, and receipt descriptions
below come from this file's documentation snapshot at `d455acd6 on 2026-09-05`;
this rules edit does not re-verify runtime state. Verify only the facts needed for
the current task against this checkout's source/docs or the exact target runtime.
Keep the safety and operator-authorization constraints below. A newer checkout's
status does not establish this checkout's state; a snapshot grants no authorization.

## Repository Role and Checkout Boundary

- This repository is the quant-domain backend and frontend for
  `/Users/sunyibo/programs/Hermes-quant-agent`. For product/roadmap work, start
  with `docs/INDEX.md`. The HQA plan recorded for this checkout is
  `docs/plans/2026-09-14-alpha-research-reset.md` (v3.2 Phase2 authorization).
  `D-32`/`D-33`/`D-34` are leftover code names, not product lines.
- Stable options-model/dividend code anchor: `a307b77`; browser-workflow repair
  anchors: Platform `9d0efee`/`b0615fd` and HQA `d51e376`; recorded receipt:
  HQA plan §13.41. Recheck source/deployment HEADs when the task depends on their
  pairing. The recorded verdict is **READY_FOR_REVIEW, not SEALED/PASS**;
  public/release/live stay OFF and no automatic NEXT exists. Formal 034 and the
  installed local stack are already present and must not be replayed.
- Edit, test, commit, and push only from `/Users/sunyibo/programs/ai-quant-platform`
  or a purpose-named source worktree under `/Users/sunyibo/programs/.worktrees/`.
- The checkout under
  `Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform` is a
  deployment mirror: fetch and fast-forward only. Never edit, commit, rebase, or
  push from it.
- Normal macOS operation uses `bash scripts/local_mac_stack.sh start`. The stack
  owns Docker readiness, the production frontend build, and the Hermes OAuth
  proxy, Hermes, backend, frontend, connector and Asia Radar refresh. The
  research-only worker and D34 paper-cycle are installed separately. Each
  research-worker invocation handles at most one job and does not run a paper-cycle;
  new same-chat verified results reuse the simulated-activation service.
  D34 paper-cycle only handles enabled simulated sleeves on
  its fixed calendar. Service lifetime must not depend on an AI-tool terminal.
- The only full migration/readiness/restart/restore authority is
  `docs/runbooks/agent-v0-2-local-stack.md`. Component runbooks must link there
  instead of copying a competing operator ladder.

## Current Local Boundaries

- Local trust bypasses only the single-owner candidate identity ceremony. It
  does not relax owner/CSRF checks, paper limits, migration authority, the kill
  switch, live qualification, or public release.
- Migrations 006–033 are present in the inspected formal database. Migration 028,
  029, D-34 migrations 030–032, and brief-rollup migration 033 were each applied
  once after their recorded backup/isolated-restore windows. Do not replay them.
  Backend and LaunchAgent startup keep `QS_DATABASE_AUTO_MIGRATE=false`.
- Paper research and the daily paper book are one product. New research is
  owner-ask only; there is no weekly slot. The five-minute worker must not
  invent a cycle. Hung allocated sleeves may fill when
  `QS_PAPER_OBSERVATION_ENABLED` is on (default). That is not live
  eligibility and not automatic GitHub push.
- `hang_if_pass` and `hang_preauthorization` are absent from production, wire,
  book, worker and generated contracts. Same-chat research requires note, a supported
  daily OHLCV Qlib formula and an ordered universe;
  one digest-stable operation creates at most one job/request and projects its
  terminal result back to the originating Hermes session. New same-chat results
  passing the existing quality/cash checks automatically allocate one $10,000
  sleeve through the same digest-bound activation service. Definite refusals
  keep the candidate; partial writes use existing reconciliation. `/library`
  retains manual activation for historical candidates and explicit recovery.
  Manual activation sends candidate ID plus expected source digest through owner/CSRF;
  the service rechecks that digest before and inside the account→sleeve→book
  lock. GET book/request, page load and polling never reconcile or write.
- `live_trading_enabled=false`. `kill_switch` freezes live danger, not hung
  paper observation. `emergency_stop` still freezes paper fills. Isolation
  preview: `bash scripts/coo_unify_preview.sh start` on `:8876`/`:3002` with
  database `quantplatform_coo` only. The preview frontend must keep
  `NEXT_PUBLIC_QUANT_API_BASE_URL` on `:3002` (same-origin `/api`); Next
  rewrites to `:8876`. A preview seed fill is not daily observation and
  its mark-to-market is not strategy P&L. Do not replay 006–034 on live
  `quantplatform`. No paper factor, Artifact, Mandate, trial sleeve or
  routing receipt has a live-upgrade operation. Do not fabricate observations.
- Agent v0.2 has a gated local managed-session write path. Historical/external
  sessions remain Web read-only and require an explicit fork to continue.
  `chat_write_ready` is local readiness; `public_chat_write_ready`,
  `public_write_authorized`, and `release_authorized` remain separate and OFF.
- Hermes updates are operator-controlled through
  `~/.hermes/scripts/hqa-hermes-update.sh check|apply`. Compatibility watchers
  may report drift but never update, restart, merge, or open a gate.

## Project Structure

```text
src/quant_system/
  api/                 FastAPI routes and schemas
  backtest/            Equity backtests and reports
  brief/               Daily brief live/archive services
  config/              Settings, paths, providers, safety
  data/                Market-data providers and caches
  d34/                 Fixed-resource research worker and dual-engine flow
  execution/           Paper account, sleeves, policy, broker/recovery
  experiments/         Experiment configs and artifacts
  factors/             Factor definitions, registry, pipeline
  hermes/              Workflow, research job, Registry and safety authorities
  news/                Read-only news facade and cache
  options/             Futu read-only options research
  prediction_market/   Prediction-market research
  storage/             File/PostgreSQL repositories and migration helpers
src/frontend/          Next.js app, components, API clients and Playwright tests
scripts/sql/           Ordered SQL migrations
docs/                  Current guides/runbooks plus historical delivery evidence
data/                  Local caches, runtime state and generated research outputs
```

## Core Engineering Rules

### Data, research, and factors

- Explicit providers are strict. An unavailable requested real provider must fail
  visibly, never silently become sample/Yahoo/community data.
- Futu use is read-only. Do not import or instantiate trade contexts, unlock an
  account, or call real broker order APIs.
- `/options-radar` is the read-only seller-recommendation surface: it scans the
  tracked 34-symbol `curated_wheel.csv`, persists at most 20 Futu-backed rows,
  starts automatically at 22:00 Monday-Saturday, and may start the same canonical
  task from the page as a background update. Missing IVR history is shown as
  warming and does not block EV/liquidity recommendations; invalid IVR and missing
  quote/event evidence still fail closed.
- Seller recommendation ordering uses annualized physical expected value
  (extrinsic premium minus the closed-form lognormal expected payout with
  volatility min(IV, HV) and drift risk-free rate + equity risk premium)
  multiplied by a 0–1 liquidity factor. Non-positive EV is excluded because
  applying that factor to a negative value would otherwise reward lower
  liquidity. Covered calls treat a source-asserted zero-dividend record as
  evidence; missing dividend evidence still fails closed.
- Sample option inputs may only use explicit non-canonical development paths;
  they never feed Futu recommendation history or canonical earnings/VIX files.
- `/watch?pane=radar` uses the fixed Futu-backed Asia universe and auditable real/cache
  provenance. Keep unsupported valuation/crowding claims out until a real source
  exists. Read `docs/guides/asia-radar.md` before changing it.
- Factor development is code-first. A runnable backtest strategy needs registry
  metadata and a pipeline builder; paper-account rebalance support is separate.
- Canonical candidates live under repo-anchored
  `data/agent_run/agent/candidates`; only `QS_AGENT_OUTPUT_DIR` may relocate the
  root. CWD and `QS_DATA_DIR` do not. Read states are `verified`,
  `migration_required`, or `corrupt`; legacy/unbound material never authorizes.
- Legacy candidate promotion and every live-eligibility decision retain the
  three human gates. The explicit `verify-from-registered` command is narrower:
  it supports only exact source-adapter-bound registered paper factors, generates
  canonical current-session dual-engine evidence and stops at a verified
  candidate; it never hangs or grants live eligibility.
- D-34 Futu Parquet is the authoritative snapshot. Qlib provider data is a
  rebuildable cache. RD-Agent/Qlib owns hypothesis/factor/target weights;
  Platform independently replays fills, fees, positions, risk and NAV from the
  same digests rather than reimplementing the factor formula.
- Every successful D-34 experiment must persist one digest-bound host trial;
  candidate DSR uses the complete successful-experiment family, never only the
  selected replay. Same run identity with different returns fails closed.

### Storage and PostgreSQL

- SQL migrations live in `scripts/sql/`, run in lexical order, and are exercised
  only against an explicit throwaway `QS_TEST_DATABASE_URL` in tests.
- Migration 034 was applied exactly once to the formal database after the
  recorded backup and restored-sibling rehearsal. Do not replay 006–034.
- Research artifacts remain file-backed under `data/api_runs/`; PostgreSQL rows
  are indexes unless a documented authority explicitly says otherwise.
- All paper-account paths use `build_paper_account_repository`. Mirror mode is
  file-authoritative/best-effort DB; canonical mode is DB-authoritative and fails
  closed. Ordinary reads or mutations must not bootstrap a missing canonical
  account.
- Assistant remote candidate hang first inspects persisted raw cash partitions
  and allocation ledgers without constructing `PaperAccount`, then holds account
  repository → sleeve storage → book locks. An unbound exact remote-hang sleeve is
  durably PAUSED before validation; activity or non-$10k lineage is rejected.
  New sleeves stay PAUSED through pending → account → finalize → book and become
  RUNNING only after binding. Canonical drift/missing/unavailable never falls back
  to a file account or gets repaired by a new hang.
- `PaperAccount.ledger` is the account event fact. Migrations/backfills preserve
  ledger, pending orders, positions, ownership and audit snapshots.
- Repository `load` is observational. Corrupt-file repair belongs to a locked
  mutation path, never an unlocked read.
- Platform must never `import hqa`; encrypted payload operations cross the
  closed subprocess interface. HQA Keychain `probe` is non-creating; only the
  operator may run `initialize-key` for an exact runtime.

### Paper execution and recovery

- Persistent paper mutations use real market prices only. Never fill with sample
  or synthetic prices.
- D-33 and D-34 orders both pass the unified `PaperExecutionPolicy`; preserve
  sleeve/account exposure, daily quota, loss/drawdown, audit and emergency-stop
  checks.
- The persistent-account freeze and global replay kill switch are different
  controls. Do not conflate or bypass them.
- Strategy-sleeve signals do not bypass execution journals. Preserve cash/lot
  ownership, idempotency, pending/outcome-unknown recovery and exact policy
  decisions.
- Hung-sleeve performance is a read-only report over committed execution
  journals: reconstruct each date from sleeve cash + owned lots at same-day
  Futu 1d QFQ closes, use actual fill commission, and mark missing/inconsistent
  journal or price evidence unavailable. Current sleeve cash, full-account NAV,
  fossils and inventory are never substitutes. `/brief` and Hermes consume the
  same `/api/paper/strategy-sleeves/hung-effect` result.
- Connector/provider network I/O stays outside DB transactions. Timeout after an
  external effect is `outcome_unknown`, never blind retry. Empty queues make zero
  provider/Hermes mutation calls.
- Opportunity/action linkage uses exact Platform signal/execution IDs. Symbol or
  ticker similarity is never causal proof.
- No paper feature authorizes live broker execution.

### Frontend and Hermes

- `/hermes` is the local-owner assistant desk: the Today/research/paper
  ledgers, the only managed-session composer, recent sessions, and
  source-attributed read-only results (`/hermes/results`,
  `/hermes/sessions/[sessionId]`). The Tasks/Approvals pages and the D-34
  Mandate/job/Artifact/canary controls were retired on 2026-08-23 in `417be6d`;
  `/library` is the only surface with the digest-bound owner/CSRF hang action.
  Nothing here authorizes public or live behavior.
- There is no `/api/agent/tasks` fallback or fake async job. Historical/external
  session reads remain GET-only; composer readiness stays separately gated.
- Keep legacy research deep links until an independently accepted parity/cutover.
  Agent Studio redirect remains reversible and default OFF.
- Same-origin frontend reads use `lib/api.ts`; client mutations use
  `lib/apiClient.ts` and established query/mutation patterns. Preserve additive
  API compatibility and localized safety language.
- Only GET may receive the single bounded transport retry. A non-idempotent
  mutation is sent once; 5xx, disconnect or timeout remains visibly
  `outcome_unknown`, never a blind replay or ordinary success.
- “Read-only AI news” forbids research/trading/account mutation; successful GETs
  may best-effort update the optional news cache. `/brief` archives only on the
  explicit save/auto-archive path.

## Commands

Normal persistent Mac stack:

```bash
bash scripts/local_mac_stack.sh start
bash scripts/local_mac_stack.sh status
bash scripts/local_mac_stack.sh logs
bash scripts/local_mac_stack.sh stop
```

Foreground backend/frontend debugging:

```bash
./ai-quant/bin/python -m quant_system.cli serve --host 127.0.0.1 --port 8765
npm --prefix src/frontend run dev -- --hostname 127.0.0.1 --port 3001
```

Available verification commands — select the affected causal path; this is not a
mandatory per-slice bundle. Choose focused pytest/Vitest, changed-file
lint/type checks, builds, or the smallest real read-only smoke as relevant. Run the
Platform full suite only for a batch/release boundary or a shared change whose impact cannot be
bounded; run the HQA full suite only when HQA or an HQA-consumed contract changes.
If a broad suite has known failures, report the observed failures and whether
a comparable baseline shows an expanded failure set; without that comparison,
state the uncertainty. Never call a failing suite passed.

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/ruff check src/quant_system tests
npm --prefix src/frontend run test
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```

Use the Python 3.11 `.venv` shown above. For the broad macOS verifier, bind it
explicitly with `PYTHON_BIN="$PWD/.venv/bin/python" bash scripts/verify.sh` because
the older `ai-quant` environment may use another Python version. Purpose
worktrees that reuse the main `.venv` must set `PYTHONPATH="$PWD/src"` so tests
import the worktree rather than main.

## Deep References

Read only the references for the affected area; this table is not a universal
startup checklist.

| Area | Read before changing |
|---|---|
| Current route/status | `docs/INDEX.md`, `docs/OVERVIEW.md` |
| Local stack/migrations | `docs/runbooks/agent-v0-2-local-stack.md` |
| Historical D-34 internals | `docs/architecture/d34-autonomous-paper.md` |
| Storage/PostgreSQL | `docs/architecture/database_cache_plan.md` |
| Paper account/sleeves | `docs/guides/paper-trading.md`, `docs/execution/paper_strategy_sleeves.md` |
| Backtests/strategies | `docs/guides/backtester.md`, `docs/guides/strategy-catalog.md` |
| Hermes sessions | `docs/guides/hermes-sessions.md` |
| AI News | `docs/guides/ai-news.md` |
| Futu/options | `docs/guides/options-recommendations.md`, `docs/futu/`, `docs/options/` |

## Do Not

- Do not modify unrelated user WIP, hide errors, weaken tests, or add speculative
  abstractions/fallbacks/retries.
- Do not create a standalone app or revive a Platform-side LLM factor runner.
- Do not call live Futu trading APIs in code or tests.
- Do not weaken `dry_run`, `paper_trading`, `live_trading_enabled=false`, the
  kill switch, emergency stop, paper limits, manual live gates, or public gates.
- Do not expose secrets, tokens, cookies, private keys, prompts, or encrypted
  payload bodies in logs, docs, argv, PostgreSQL projections or frontend bundles.
- Do not present scans, factors, backtests, radar results, or paper P&L as
  investment advice or guaranteed outcomes.
- Do not infer current work from old Phase/Wave checkboxes, test counts, PIDs or
  historical audits. Check only the current code, Git state, documentation or
  runtime evidence needed for the requested conclusion.

## Definition of Done

- The requested findings or authorized behavior change and its causal path are
  complete.
- Checks selected for the affected path pass; tests, lint, build, and browser
  checks are required only when they substantiate that result. Check changed
  user-visible frontend behavior in a browser when practical.
- Current source/runtime facts are distinguished from historical evidence.
- Safety and paper/live language remain accurate.
- Changed files and skipped verification are reported honestly.
- No unrelated files are staged, committed, reset, or deleted.
