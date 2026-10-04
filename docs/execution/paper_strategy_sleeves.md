# Paper Strategy Sleeves Execution Notes

> **Current boundary (2026-08-27):** the domain models, storage, API/UI, manual
> signal/execution paths, shared operations runner and recovery journal are
> implemented. Generic `paper strategies` commands remain explicit one-shot
> paper operations. Formal natural observation for enabled,
> `automation_managed=true` sleeves is owned only by
> `com.aiquant.d34-paper-cycle`; the optional generic LaunchAgent templates are
> legacy compatibility assets and are not that schedule. Every GET and
> `ops-status` remains observational; recovery requires an explicit mutation or
> `paper strategies recover-pending`.

## What Exists Now

The first slice establishes the accounting and persistence base:

- Domain models:
  - `StrategyConfig`
  - `StrategySleeve`
  - `SleeveLot`
  - `StrategySignal`
  - `StrategyExecutionPlan`
  - `StrategyExecutionOrder`
  - `StrategyExecutionFill`
- API response schema classes for those models in `src/quant_system/api/schemas/paper.py`.
- Local source-of-truth storage in
  `src/quant_system/execution/paper_strategy_sleeve_storage.py`.
- Account-level `sleeve_cash` allocation book in `PaperAccount`.
- `SleeveLotBook` helpers that allow the same symbol to exist in multiple
  sleeves while sells only consume the addressed sleeve lot.
- `PaperStrategySleeveService.create_sleeve()` for signal-only and allocated
  sleeve creation. Allocated sleeve cash is moved from the manual sleeve's
  unreserved available cash and does not create new account principal.

`PaperAccount.cash` remains the legacy total cash field. The existing
`POST /api/paper/account/rebalance` path still uses the old full-account
rebalance semantics and is not the Strategy Sleeves entrypoint. It is rejected
with `409 strategy_sleeve_positions_present` when actual sleeve-owned lots are
present, so it cannot sell strategy sleeve holdings outside the sleeve
execution processor. Manual orders consume only manual-source lots and
`manual_available_cash`; sleeve execution consumes only the addressed sleeve's
cash and lots.

The second slice exposes the backend API contract:

| Method | Path | Status |
|---|---|---|
| `POST` | `/api/paper/strategy-configs` | Creates a version-1 `StrategyConfig`. |
| `GET` | `/api/paper/strategy-configs` | Lists latest config versions. |
| `POST` | `/api/paper/strategy-configs/{id}/versions` | Creates the next config version. |
| `POST` | `/api/paper/strategy-sleeves` | Creates signal-only or allocated sleeves. |
| `GET` | `/api/paper/strategy-sleeves` | Lists finalized sleeves without reconciling pending files. |
| `GET` | `/api/paper/strategy-sleeves/{id}` | Returns persisted sleeve, lots, signals, and executions without recovery writes. |
| `GET` | `/api/paper/strategy-sleeves/hung-effect` | Reconstructs official hung-sleeve NAV/cost/SPY from committed journals and same-day Futu QFQ closes; never writes or recovers state. |
| `POST` | `/api/paper/strategy-sleeves/{id}/signals` | Generates and persists one daily signal. |
| `POST` | `/api/paper/strategy-sleeves/{id}/executions` | Creates one pending execution plan from a selected generated signal. |
| `GET` | `/api/paper/strategy-sleeves/ops/status` | Returns a best-effort read-only status, including separate pending sleeve/journal counts. |
| `POST` | `/api/paper/strategy-sleeves/executions/process` | Processes due pending execution plans once. |
| `GET` | `/api/assistant/remote/book` | Projects requests, verified candidates, hung candidates and fossils without reconciliation or writes. |
| `POST` | `/api/assistant/remote/research` | Records one owner/CSRF-protected, material- and operation-digest-bound chat research request; missing/invalid material or mandate mismatch writes nothing. |
| `GET` | `/api/assistant/remote/request/{operation_id}` | Reads one exact chat research result projection; never runs the worker or reconciles. |
| `POST` | `/api/assistant/remote/hang` | Binds an explicitly selected digest-bound verified candidate to one allocated paper sleeve; research dispatch never calls it automatically. |
| `POST` | `/api/paper/strategy-sleeves/{id}/pause` | Pauses a running sleeve. |
| `POST` | `/api/paper/strategy-sleeves/{id}/resume` | Resumes a paused sleeve. |
| `POST` | `/api/paper/strategy-sleeves/{id}/stop` | Stops the sleeve and keeps holdings. |

Active strategy config names are unique at creation time. Reusing a name for a
different config returns `409 strategy_config_name_conflict`; changing the same
config through `/versions` keeps the config identity and increments `version`.

Allocated sleeve creation resolves the selected account adapter through
`build_paper_account_repository` and takes its mutation lock before the sleeve
storage lock. In file/mirror mode that includes the filesystem account lock; in
canonical mode it is the PostgreSQL advisory lock. It allocates from
`manual_available_cash()` so pending manual buy orders stay reserved, writes the
sleeve cash allocation into the selected account fact source, and uses a
`sleeve.pending.json` journal before finalizing
`sleeve.json`. If the process exits after the account allocation is saved but
before finalization, GET list/detail/status leaves the journal untouched. Run
`quant-system paper strategies recover-pending`, or a later explicit strategy
mutation, to reconcile it against `PaperAccount.sleeve_cash`. Recovery does not
create or process a new execution plan.

## Assistant remote candidate hang

`POST /api/assistant/remote/hang` is the separate, explicit promotion step after
research has produced a verified candidate. `/library` is the only product
surface that exposes this internal action under the user-facing label
"Enable simulated running" / “启用模拟运行”. Research verification alone is
insufficient: DSR, locked-book correlation and cost admission must all pass.
The owner/CSRF-protected request must name the
candidate and repeat the exact source digest displayed by the GET projection;
the implementation compares it both before mutation and again inside the final
account→sleeve→book critical section, then validates the persisted source bytes.
Research dispatch cannot turn this into an automatic "hang if passed" path;
the legacy shortcut fields are not part of any production or generated contract.

`hang_candidate` resolves the account through the same repository factory as
orders and sleeve creation. One critical section holds the account repository,
sleeve storage and remote-book locks in that order while it:

1. inspects the persisted raw partition and raw/materialized allocation ledgers
   before constructing `PaperAccount`; existing drift fails without a write;
2. reloads the remote book and reconciles pending sleeves already represented in
   the selected account;
3. persists any exact unbound remote-hang lineage as PAUSED/non-observable before
   validating it; signals, executions, fills, lots, journals or a non-$10,000
   initial/current allocation make recovery fail closed;
4. rejects a new allocation with `hang_recovery_required` while any other
   unbound remote-hang sleeve needs book recovery;
5. evaluates DSR, locked-book correlation and cost admission gates; and
6. persists `pending PAUSED sleeve → account allocation → finalized PAUSED
   sleeve → book binding → RUNNING activation`.

A missing canonical account returns `paper_account_bootstrap_required`; an
unavailable canonical database remains a visible failure. Neither case creates
or updates a file account. A save known not to have committed discards the
pending sleeve; a committed-but-lost response, finalize failure, book-save
failure or final activation failure keeps enough evidence for the next explicit
retry to converge on the same allocation. Bare legacy and `not_book_bound`
remote-hang orphans are made non-observable before recovery checks. Preview,
digest-less and other fossil reasons remain rejected across repeated retries and
cannot acquire a recoverable activation marker.

The third slice adds manual daily signal generation:

- Service:
  `src/quant_system/execution/paper_strategy_signal_service.py`.
- API:
  `POST /api/paper/strategy-sleeves/{id}/signals`.
- CLI:
  `quant-system paper strategies generate-signal --sleeve <sleeve_id>`.

Signal generation loads the sleeve's fixed `StrategyConfig` version, fetches
read-only OHLCV through the configured provider, computes factor scores, writes
a `StrategySignal` to `signals.jsonl`, and returns target weights plus advisory
`proposed_orders` for allocated sleeves. It does not write pending orders, fills,
account position changes, or a new account file when no account exists yet.
Paused sleeves still record observation signals with `execution_blocked_reason=sleeve_paused`; frozen accounts record
`execution_blocked_reason=account_frozen`. Stopped sleeves reject new signal
generation.

The fourth slice adds the `/paper-trading` Strategy Sleeves workspace:

- Frontend component:
  `src/frontend/components/forms/PaperStrategySleevesPanel.tsx`.
- Frontend API wrapper/types:
  `src/frontend/lib/api.ts`.
- Live account tab capabilities:
  create strategy configs, open `signal_only` or `allocated` sleeves, generate
  sleeve signals, and pause/resume/stop sleeves.
- The existing full-account rebalance form is still present, but it is labeled
  as an advanced full-account path, not a liquidation button or sleeve
  creation flow, and continues to call `POST /api/paper/account/rebalance`.

The workspace is signal-first. Generating a sleeve signal does not create
pending orders, fills, account position mutations, or automatic execution
jobs.

The first MVP-2 slice adds manual pending execution plan creation through
`POST /api/paper/strategy-sleeves/{id}/executions`. A plan is created from one
generated allocated-sleeve signal and is persisted to `executions.jsonl` with
`status=pending`. This endpoint does not fetch execution prices, create paper
orders, fill lots, mutate account positions, or change sleeve cash. It rejects
signal-only sleeves, paused/stopped sleeves, frozen accounts, non-generated
signals, signals with no proposed orders, and duplicate execution plans for the
same signal. If the request omits `target_date`, the plan uses the local run
date; invalid `target_date` values are rejected by the API schema.

The second MVP-2 slice adds the backend next-open execution processor in
`src/quant_system/execution/paper_strategy_execution_service.py`. It processes a
pending plan against paper prices by preflighting all legs, selling before
buying, updating only the addressed sleeve's lot/source ownership on sells, and
persisting account/sleeve/lots/execution state through a local execution
journal. Hard failures such as missing prices or insufficient sleeve cash mark
the plan `blocked` before raising and do not mutate account cash, positions,
sleeve cash, or lots. This service is exposed through manual API/CLI
entrypoints only; it is not a scheduler or UI action.

The third MVP-2 slice exposes manual processing entrypoints:

- API:
  `POST /api/paper/strategy-sleeves/executions/process`.
- CLI:
  `quant-system paper strategies create-execution --sleeve <id> --signal <signal_id>`.
- CLI:
  `quant-system paper strategies execute-pending --target-date <YYYY-MM-DD>`.
- CLI:
  `quant-system paper strategies execute-due --target-date <YYYY-MM-DD>`.
- CLI:
  `quant-system paper strategies ops-status --target-date <YYYY-MM-DD> --format json`.
- CLI:
  `quant-system paper strategies recover-pending --format json`.

These entrypoints are one-shot commands intended for explicit local use or an
external scheduler. The FastAPI process does not run an in-process recurring
trading loop. When processing pending executions without an explicit
`target_date`, the service selects only plans whose `target_date` is the local
run date. Historical catch-up or replay must pass `target_date` explicitly.
Unavailable paper prices or provider failures are retried a bounded number of
times with a short backoff inside the same processing run (default 2 retries,
30 s apart; each attempt is recorded on the plan under
`metadata["price_unavailable_retry"]`). The bounded retries and that 30 s
backoff run **outside** the account/sleeve mutation locks: only the re-read
re-validation and the persistent writes stay inside the lock, so a concurrent
API/CLI mutation is never blocked by a price outage. If every attempt fails, the
execution
is recorded as `blocked` with reason `price_unavailable` (or
`strategy_definition_open_data_unavailable` for digest-bound definitions); it
is never filled with sample data and never retried silently. A `next_open`
plan is executable only on its target date: each processing run first marks
any older still-unexecuted plan — pending, or blocked by those same transient
price reasons — as `missed_window`, preserving the prior status and reason
under `metadata["missed_window"]`. Plans blocked by deterministic authority
rejections (for example insufficient cash or policy blocks) stay `blocked`
and are never retried.

MVP-3 Slice 0 adds recovery journals for filled execution plans:

- before any file mutation, `execute_plan()` writes
  `execution_journal/<execution_id>.pending.json` with before/after snapshots of
  account, sleeve, lots, and execution state
- API/CLI processing moves the journal to
  `execution_journal/<execution_id>.committed.json` only after the account save
  succeeds
- explicit process paths, CLI `execute-pending`, and the recovery-only CLI
  `recover-pending` reconcile pending journals under the existing
  account+sleeve locks
- corrupt pending journal files are preserved as
  `<execution_id>.corrupt-*.json` and skipped rather than deleted silently

## Official hung-sleeve effect reporting

`GET /api/paper/strategy-sleeves/hung-effect` is the single report source for
the Hermes paper tab and the morning brief. It validates committed journal
identity, fill-driven cash/quantity transitions, adjacent state continuity and
the latest canonical sleeve/lots before calculating any mark. Each observation
date is `sleeve cash + owned lot quantity × same-day Futu 1d QFQ close`;
turnover uses fill notional and cost drag uses the actual fill commission. SPY
is fetched independently so an unavailable benchmark does not erase a valid
sleeve NAV.

Only a true zero-observation state is `empty`. Missing/tampered journals,
missing strategy prices, untrusted provider/adjustment provenance and book/effect
count mismatches are explicit `unavailable` states. The report never substitutes
current remaining cash, full-account equity, manual inventory or fossil lots.
The GET path is observational and does not reconcile pending journals.

MVP-3 Slice 1 adds the shared operations runner in
`src/quant_system/execution/paper_strategy_operations.py`. CLI commands, API
execution processing, and future scheduler adapters should call this runner
rather than duplicate lock, recovery, pending-plan scanning, account-save, or
journal-commit logic.

Scheduler-safe one-shot commands now available:

```bash
quant-system paper strategies generate-due-signals --target-date 2024-03-20 --format json
quant-system paper strategies execute-due --target-date 2026-06-29
quant-system paper strategies ops-status --target-date 2026-06-29 --format json
```

`generate-due-signals` generates one daily signal per eligible sleeve for the
given date and skips sleeves that already have a signal for that date.
`execute-due` is the scheduler-friendly alias for the existing one-shot pending
execution processor. `ops-status` reports finalized/pending sleeves, due work,
pending journal files, blocked executions for the requested `target_date`, and
recovery-required counts. Historical blocked executions remain queryable by
their own date and do not make today's read model look blocked. It
does not load the account repository, acquire mutation locks, repair corrupt
journals, or change disk state; its multi-file result is a best-effort rather
than transactionally consistent snapshot.

Crash recovery is deliberately separate:

```bash
quant-system paper strategies recover-pending --format json
```

`recover-pending` reconciles sleeve/execution crash journals but never generates
signals, creates plans, or processes a pending plan. This command is a mutation
and must not be added to read-only wrapper allowlists.

## Slice 9G bounded observations

HQA links an opportunity to platform activity only through exact persisted
signal and execution identities. The platform exposes those facts through a
separate bounded CLI read:

```bash
quant-system paper strategies observations \
  --from-date 2026-07-01 \
  --to-date 2026-07-12 \
  --signal-id <signal_id> \
  --limit 200 \
  --format json
```

All filters are optional and `limit` is bounded to 1-500. The versioned JSON
envelope contains `snapshot_at`, the normalized `query`,
`read_status=available|empty|degraded`, `returned_count`, `truncated`,
`ops_quality`, bounded `observations`, and `errors`. Quality counters cover
pending sleeves/journals, corrupt journals and recovery-required executions.
Each observation carries the complete strategy signal identity plus every
causally linked execution identity and literal status; ticker similarity is not
a link.

`empty` with zero quality counters and no errors is an honest complete result,
not a failure. `degraded`, non-zero quality, errors or `truncated=true` cannot
establish complete action coverage. The reader never computes `missed`.

This seam is CLI-only and file-backed. It does not open the account repository
or market provider, take mutation locks, perform crash recovery, expose an HTTP
route, or add a database table/migration. Reads must leave every sleeve and
journal file unchanged.

The same status payload is exposed through:

```bash
curl "http://127.0.0.1:8765/api/paper/strategy-sleeves/ops/status?target_date=2026-06-29"
```

The API accepts `target_date=YYYY-MM-DD` and currently supports
`execution_window=next_open`.

MVP-3 Slice 2 added legacy/optional macOS LaunchAgent assets and a runbook:

- `scripts/run_quant_backend.sh`
- `scripts/run_quant_frontend.sh`
- `scripts/run_paper_strategy_sleeves.sh`
- `scripts/launchd/*.plist.template`
- `scripts/install_paper_strategy_sleeves_launchagent.sh`
- `scripts/uninstall_paper_strategy_sleeves_launchagent.sh`
- `docs/execution/paper_strategy_sleeves_launchd.md`

The backend/frontend LaunchAgents are long-running local services. Strategy
sleeve jobs are one-shot commands with `KeepAlive=false`; UI availability does
not imply automatic execution is enabled. The current local stack owns the
backend/frontend services, and formal hung-sleeve observation uses the separate
D34 paper-cycle rather than these generic templates.

The fourth MVP-2 slice exposes the same manual execution lifecycle in the
`/paper-trading` Strategy Sleeves workspace. For each sleeve, the panel shows
the latest execution plan state and can:

- create a `next_open` pending execution plan from the latest generated signal
  when the sleeve is allocated, running, and has proposed orders
- process due pending plans through
  `POST /api/paper/strategy-sleeves/executions/process`

These buttons are explicit one-shot local paper actions. They do not add a
FastAPI-resident scheduler, do not place real broker orders, and do not call the
legacy full-account rebalance endpoint.

## Local Storage Layout

The first slice writes under the API runs directory:

```text
data/api_runs/paper_strategy_sleeves/
  strategy_configs/
    <strategy_config_id>/
      config.v1.json
      config.v2.json
      metadata.json
  sleeves/
    <sleeve_id>/
      sleeve.json
      signals.jsonl
      executions.jsonl
      lots.parquet
      execution_journal/
        <execution_id>.pending.json
        <execution_id>.committed.json
        <execution_id>.corrupt-*.json
```

JSON writes use temp files and atomic replace. Signal and execution JSONL
persistence rewrites the complete file atomically for these foundation slices.
Lots are persisted as parquet snapshots.

## Remaining generic-sleeve boundaries

The following are not generic CLI/UI capabilities:

- `quant-system paper strategies config-create`
- `quant-system paper strategies sleeve-create`
- near-close simulated fills
- lot transfer between manual and strategy sleeves

The formal D34 paper-cycle is implemented, but it is not a general-purpose
automatic sleeve runner: it accepts only enabled digest-bound sleeves and
does not make the commands above available. The dated MVP-3 plan is historical
design evidence, not the current NEXT.

## Real Futu Integration Tests

Normal CI remains mocked/offline. The signal-generation and execution slices
include opt-in read-only Futu/OpenD tests under a dedicated pytest marker:

```text
pytestmark = pytest.mark.futu_opend
QS_TEST_FUTU_OPEND=1
```

The marker is registered in `pyproject.toml`. These tests verify only read-only
data access and local paper accounting: OpenD reachable, small OHLCV fetch works
for configured symbols, `StrategySignal.data_provider == "futu"`, real
`data_as_of` is recorded, a real `PaperPriceSource` snapshot/latest close can
drive the next-open paper execution processor, and unavailable real data becomes
`data_unavailable` instead of falling back to sample data. Do not import or
instantiate Futu trade contexts.

Run them only when a local read-only OpenD service is intentionally available:

```bash
QS_TEST_FUTU_OPEND=1 ./.venv/bin/python -m pytest tests/test_paper_strategy_sleeves_futu_integration.py -q
```

## Verification

### Assistant remote canonical hang changes

Run the ordinary remote/API contract without PostgreSQL-marked cases:

```bash
./.venv/bin/python -m pytest -q \
  tests/test_assistant_remote.py \
  tests/test_api_assistant_remote.py \
  -m 'not pg'
```

Then point `QS_TEST_DATABASE_URL` only at a throwaway/test-named PostgreSQL base
and run the six disposable-database cases. Each test creates and drops its own
sibling database; never use the live `quantplatform` database:

```bash
QS_TEST_DATABASE_URL='postgresql://.../quantplatform_tmp' \
  ./.venv/bin/python -m pytest -q tests/test_assistant_remote.py -m pg
```

These cases cover the normal canonical allocation/no-file-side-write path,
known account-save failure, commit response loss, finalize failure, book-save
failure, and missing canonical account. Concurrency, orphan blocking and fossil
recovery contracts remain in the non-PG focused set.

### Hung-effect and brief reporting changes

For changes limited to the read-only hung-effect/API/brief/Hermes Today chain,
run the directly affected selectors instead of both repositories' full suites:

```bash
./.venv/bin/python -m pytest -q \
  tests/test_d34_hung_sleeve_effect.py \
  tests/test_api_paper_strategy_sleeves.py \
  tests/test_brief_auto_archive.py

cd src/frontend
npx vitest run \
  lib/briefLede.test.ts \
  lib/briefRouteContract.test.ts \
  components/hermes/desk/HermesDeskToday.test.ts
```

When schemas or generated clients change, also run
`npm --prefix src/frontend run check:api-types`; the broader Python response-type
export test currently has a known baseline failure, so compare its exact node
rather than calling it passed. When rendered copy or wiring changes, finish with
one real read-only GET/page smoke and confirm the report inputs are unchanged.
At `e30af59` these selectors
recorded 79 Python and 19 frontend passes; those counts are a receipt, not a
future gate. A Platform-only reporting change does not require the HQA full
suite unless an HQA consumer contract also changes. Keep the Platform full suite
for a batch/release boundary or a genuinely unbounded shared change.

### Broader sleeve changes

Focused backend verification:

```powershell
.\ai-quant\Scripts\Activate.ps1
python -m pytest tests/test_paper_account.py tests/test_api_paper_account.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_paper_strategy_execution.py tests/test_paper_strategy_operations.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py -q
ruff check src/quant_system/execution/account.py src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/execution/paper_strategy_signal_service.py src/quant_system/execution/paper_strategy_execution_service.py src/quant_system/execution/paper_strategy_operations.py src/quant_system/factors/pipeline.py src/quant_system/api/schemas/paper.py src/quant_system/api/routes/paper.py src/quant_system/cli.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_paper_strategy_execution.py tests/test_paper_strategy_operations.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py
git diff --check
```

On macOS in this checkout the equivalent interpreter path is:

```bash
./.venv/bin/python -m pytest tests/test_paper_account.py tests/test_api_paper_account.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_paper_strategy_execution.py tests/test_paper_strategy_operations.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py -q
./.venv/bin/python -m ruff check src/quant_system/execution/account.py src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/execution/paper_strategy_signal_service.py src/quant_system/execution/paper_strategy_execution_service.py src/quant_system/execution/paper_strategy_operations.py src/quant_system/factors/pipeline.py src/quant_system/api/schemas/paper.py src/quant_system/api/routes/paper.py src/quant_system/cli.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_paper_strategy_execution.py tests/test_paper_strategy_operations.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py
git diff --check
```

Expected focused result after MVP-2 hardening:

- focused mock/API/CLI/factor tests pass
- `QS_TEST_FUTU_OPEND=1` Futu/OpenD integration tests pass when local OpenD is running
- ruff clean
- `git diff --check` clean
