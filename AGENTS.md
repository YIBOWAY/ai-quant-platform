# AGENTS.md

Rules for AI agents working in this repository. Optimize for the user's explicit
result, keep complexity bounded, verify before reporting, and preserve unrelated
dirty work. Historical plans and audits are evidence, not an executable queue.

## Repository Role and Checkout Boundary

- This repository is the quant-domain backend and frontend for
  `/Users/sunyibo/programs/Hermes-quant-agent`. Start with `docs/INDEX.md`; the
  cross-repo roadmap remains in the HQA repository.
- Edit, test, commit, and push only from `/Users/sunyibo/programs/ai-quant-platform`
  or a purpose-named source worktree under `/Users/sunyibo/programs/.worktrees/`.
- The checkout under
  `Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform` is a
  deployment mirror: fetch and fast-forward only. Never edit, commit, rebase, or
  push from it.
- Normal macOS operation uses `bash scripts/local_mac_stack.sh start`. The stack
  owns Docker readiness, the production frontend build, and the Hermes OAuth
  proxy, Hermes, backend, frontend, connector, D-33 factor automation, Asia Radar
  refresh, and D-34 worker LaunchAgents. Service lifetime must not depend on an
  AI-tool terminal.
- The only full migration/readiness/restart/restore authority is
  `docs/runbooks/agent-v0-2-local-stack.md`. Component runbooks must link there
  instead of copying a competing operator ladder.

## Current Local Boundaries

- Local trust bypasses only the single-owner candidate identity ceremony. It
  does not relax owner/CSRF checks, paper limits, migration authority, the kill
  switch, live qualification, or public release.
- Migrations 006–032 are present in the inspected formal database. Migration 028,
  029, and D-34 migrations 030–032 were each applied once after their recorded
  backup/isolated-restore windows. Do not replay them. Backend and LaunchAgent
  startup keep `QS_DATABASE_AUTO_MIGRATE=false`.
- D-33 is a dual-Flag automatic `paper_only` exception. It may machine-review,
  locally ff-land, allocate and maintain bounded paper sleeves; it never grants
  live eligibility or automatically pushes GitHub.
- D-34 is integrated and deployed locally: an active 30-day Mandate drives strict
  Futu Parquet → pinned RD-Agent/Qlib → Platform replay → Artifact/Policy → real
  paper-canary work. Natural soak is `1/10` complete cycles and `1/5` observation
  days, so D-33 remains the default new-research entry. Never fabricate
  observations or cut over early. Final cutover requires the exact current
  zero-duplicate/no-live receipt; rollback restores D-33 intake without flattening.
- `live_trading_enabled=false`, `kill_switch=true`, and manual live qualification
  remain independent. No D-33/D-34 factor, Artifact, Mandate, canary or routing
  receipt has a live-upgrade operation.
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
  d34/                 Mandate research worker and dual-engine flow
  execution/           Paper account, sleeves, policy, broker/recovery
  experiments/         Experiment configs and artifacts
  factors/             Factor definitions, registry, pipeline
  hermes/              Workflow, Mandate, job, Registry and safety authorities
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
- `/asia-radar` uses the fixed Futu-backed Asia universe and auditable real/cache
  provenance. Keep unsupported valuation/crowding claims out until a real source
  exists. Read `docs/guides/asia-radar.md` before changing it.
- Factor development is code-first. A runnable backtest strategy needs registry
  metadata and a pipeline builder; paper-account rebalance support is separate.
- Canonical candidates live under repo-anchored
  `data/agent_run/agent/candidates`; only `QS_AGENT_OUTPUT_DIR` may relocate the
  root. CWD and `QS_DATA_DIR` do not. Read states are `verified`,
  `migration_required`, or `corrupt`; legacy/unbound material never authorizes.
- Manual Scene-B remains three human gates: exact source digest/note binding,
  expected-digest/status Gate 2 CAS, and final-receipt-bound isolated Gate 3
  diff/commit. Raw Platform primitives do not prove HQA provenance. D-33 and D-34
  are separate machine-policy exceptions for paper only.
- D-34 Futu Parquet is the authoritative snapshot. Qlib provider data is a
  rebuildable cache. RD-Agent/Qlib owns hypothesis/factor/target weights;
  Platform independently replays fills, fees, positions, risk and NAV from the
  same digests rather than reimplementing the factor formula.

### Storage and PostgreSQL

- SQL migrations live in `scripts/sql/`, run in lexical order, and are exercised
  only against an explicit throwaway `QS_TEST_DATABASE_URL` in tests.
- Research artifacts remain file-backed under `data/api_runs/`; PostgreSQL rows
  are indexes unless a documented authority explicitly says otherwise.
- All paper-account paths use `build_paper_account_repository`. Mirror mode is
  file-authoritative/best-effort DB; canonical mode is DB-authoritative and fails
  closed. Ordinary reads or mutations must not bootstrap a missing canonical
  account.
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
- Connector/provider network I/O stays outside DB transactions. Timeout after an
  external effect is `outcome_unknown`, never blind retry. Empty queues make zero
  provider/Hermes mutation calls.
- Opportunity/action linkage uses exact Platform signal/execution IDs. Symbol or
  ticker similarity is never causal proof.
- No paper feature authorizes live broker execution.

### Frontend and Hermes

- `/hermes` is the reversible local-owner COO workbench: Today, Tasks,
  Approvals, Results, managed sessions, artifact shelf, and D-34 Mandate/job/
  Artifact/canary controls. D-34 mutations use existing owner/CSRF gates and do
  not authorize public or live behavior.
- There is no `/api/agent/tasks` fallback or fake async job. Historical/external
  session reads remain GET-only; composer readiness stays separately gated.
- Keep legacy research deep links until an independently accepted parity/cutover.
  Agent Studio redirect remains reversible and default OFF.
- Same-origin frontend reads use `lib/api.ts`; client mutations use
  `lib/apiClient.ts` and established query/mutation patterns. Preserve additive
  API compatibility and localized safety language.
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

Relevant verification:

```bash
./ai-quant/bin/python -m pytest -q
./ai-quant/bin/ruff check src/quant_system tests
npm --prefix src/frontend run test
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```

Use the Python 3.11 environment. Purpose worktrees that reuse the main `.venv`
must set `PYTHONPATH="$PWD/src"` so tests import the worktree rather than main.

## Deep References

| Area | Read before changing |
|---|---|
| Current route/status | `docs/INDEX.md`, `docs/OVERVIEW.md` |
| Local stack/migrations | `docs/runbooks/agent-v0-2-local-stack.md` |
| D-34 | `docs/architecture/d34-autonomous-paper.md`, `docs/guides/d34-workbench.md`, `docs/runbooks/d34-autonomous-paper.md` |
| Storage/PostgreSQL | `docs/architecture/database_cache_plan.md` |
| Paper account/sleeves | `docs/guides/paper-trading.md`, `docs/execution/paper_strategy_sleeves.md` |
| Backtests/strategies | `docs/guides/backtester.md`, `docs/guides/strategy-catalog.md` |
| Hermes sessions | `docs/guides/hermes-sessions.md` |
| AI News | `docs/guides/ai-news.md` |
| Futu/options | `docs/futu/`, `docs/options/` |

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
  historical audits. Re-read code, git state, runtime and the current docs.

## Definition of Done

- The requested behavior and its causal path are complete.
- Relevant tests/lint/build pass; browser behavior is checked for frontend work.
- Current source/runtime facts are distinguished from historical evidence.
- Safety and paper/live language remain accurate.
- Changed files and skipped verification are reported honestly.
- No unrelated files are staged, committed, reset, or deleted.
