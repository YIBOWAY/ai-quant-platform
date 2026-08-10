# Paper Strategy Sleeves MVP-1 Execution Notes

> Status: first through fourth MVP-1 slices implemented on 2026-06-26. MVP-2
> pending execution foundation implemented on 2026-06-27. Domain models, local
> storage, cash/lot accounting foundations, backend API contract, daily signal
> generation, manual signal CLI, `/paper-trading` Strategy Sleeves workspace,
> manual pending execution plan creation, and the backend next-open execution
> processor are available. Manual processing API/CLI entrypoints and UI
> execution-state controls are available. Opt-in read-only Futu/OpenD checks now
> cover both signal generation and paper execution processing. MVP-3 Slice 1
> adds a shared operations runner plus scheduler-safe one-shot CLI/status
> commands. MVP-3 Slice 2 adds optional manual-sleeve LaunchAgent templates.
> D-33 (2026-08-10) separately adds a five-minute, dual-Flag LaunchAgent that
> acts only on `automation_managed=true` sleeves; manual sleeves stay one-shot.
> Phase 1a-4 v2 Slice 9A (2026-07-10) separates observation from recovery:
> every strategy-sleeve GET and `ops-status` is strictly read-only; crash
> recovery now requires an explicit mutation or `paper strategies recover-pending`.

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
  allocation book and does not create new account principal.

`PaperAccount.cash` remains the legacy total cash field. The existing
`POST /api/paper/account/rebalance` path still uses the old full-account
rebalance semantics and is not the Strategy Sleeves entrypoint. It is rejected
with `409 strategy_sleeve_positions_present` when actual sleeve-owned lots are
present, so it cannot sell strategy sleeve holdings outside the sleeve
execution processor.

The second slice exposes the backend API contract:

| Method | Path | Status |
|---|---|---|
| `POST` | `/api/paper/strategy-configs` | Creates a version-1 `StrategyConfig`. |
| `GET` | `/api/paper/strategy-configs` | Lists latest config versions. |
| `POST` | `/api/paper/strategy-configs/{id}/versions` | Creates the next config version. |
| `POST` | `/api/paper/strategy-sleeves` | Creates signal-only or allocated sleeves. |
| `GET` | `/api/paper/strategy-sleeves` | Lists finalized sleeves without reconciling pending files. |
| `GET` | `/api/paper/strategy-sleeves/{id}` | Returns persisted sleeve, lots, signals, and executions without recovery writes. |
| `POST` | `/api/paper/strategy-sleeves/{id}/signals` | Generates and persists one daily signal. |
| `POST` | `/api/paper/strategy-sleeves/{id}/executions` | Creates one pending execution plan from a selected generated signal. |
| `GET` | `/api/paper/strategy-sleeves/ops/status` | Returns a best-effort read-only status, including separate pending sleeve/journal counts. |
| `POST` | `/api/paper/strategy-sleeves/executions/process` | Processes due pending execution plans once. |
| `POST` | `/api/paper/strategy-sleeves/{id}/pause` | Pauses a running sleeve. |
| `POST` | `/api/paper/strategy-sleeves/{id}/resume` | Resumes a paused sleeve. |
| `POST` | `/api/paper/strategy-sleeves/{id}/stop` | Stops the sleeve and keeps holdings. |

Active strategy config names are unique at creation time. Reusing a name for a
different config returns `409 strategy_config_name_conflict`; changing the same
config through `/versions` keeps the config identity and increments `version`.

Allocated sleeve creation runs under the existing paper-account in-process lock
and filesystem lock. It allocates from `sleeve_cash["manual"]`, writes the sleeve
cash allocation into the account cash book, and uses a `sleeve.pending.json`
journal before finalizing `sleeve.json`. If the process exits after the account
allocation is saved but before finalization, GET list/detail/status leaves the
journal untouched. Run `quant-system paper strategies recover-pending`, or a
later explicit strategy mutation, to reconcile it against
`PaperAccount.sleeve_cash`. Recovery does not create or process a new execution
plan.

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
Unavailable paper prices or provider failures are recorded on the execution as
`blocked` with reason `price_unavailable`; they are not silently retried or
filled with sample data.

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
pending journal files, blocked executions, and recovery-required counts. It
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

MVP-3 Slice 2 adds macOS LaunchAgent assets and a runbook:

- `scripts/run_quant_backend.sh`
- `scripts/run_quant_frontend.sh`
- `scripts/run_paper_strategy_sleeves.sh`
- `scripts/launchd/*.plist.template`
- `scripts/install_paper_strategy_sleeves_launchagent.sh`
- `scripts/uninstall_paper_strategy_sleeves_launchagent.sh`
- `docs/execution/paper_strategy_sleeves_launchd.md`

The backend/frontend LaunchAgents are long-running local services. Strategy
sleeve jobs are one-shot commands with `KeepAlive=false`; UI availability does
not imply automatic execution is enabled.

## D-33 automatic paper cycle

`com.aiquant.factor-automation` is installed by `local_mac_stack.sh`; it is not
one of the optional legacy manual-sleeve schedulers. Both Platform and HQA Flag
pairs must be enabled or the driver reports disabled before mutation. Each
five-minute tick first maintains automatic sleeve risk and then considers only
running sleeves whose metadata has `automation_managed=true`:

- local Tuesday-Saturday after 06:10: generate at most one signal for the date
  and materialize one next-weekday `next_open` plan;
- local Monday-Friday after 21:35: process due plans once through the existing
  paper execution/journal service;
- signal and execution identities make replays and concurrent driver races
  idempotent; manual sleeves are excluded;
- order creation re-checks sleeve and aggregate limits. Risk/limit blocks are
  counted; unexpected identity/config errors fail the driver instead of being
  reported as success.

This uses a weekday rule, not an exchange-holiday calendar. Closed-market or
missing-data cases must remain no-order/blocked facts; they must not fabricate a
fill. The FastAPI lifecycle still does not host this scheduler. Full operation,
pause/quarantine/demote, and rollback semantics are in
`/Users/sunyibo/programs/Hermes-quant-agent/docs/runbooks/full-automation-paper.md`.

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

## Not Implemented Yet

Do not document or present these as available commands or UI workflows until a
later slice implements them:

- `quant-system paper strategies config-create`
- `quant-system paper strategies sleeve-create`
- scheduled or automatic strategy execution
- enabled macOS LaunchAgent scheduling before the operator explicitly installs it
- near-close simulated fills
- lot transfer between manual and strategy sleeves

The next implementation line is documented in
[`docs/design/paper_strategy_sleeves_mvp3_operations_plan.md`](../design/paper_strategy_sleeves_mvp3_operations_plan.md).
MVP-3 continues with retry semantics and a frontend operator status surface. It
must not add duplicate schedulers or any real broker trading path.

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
QS_TEST_FUTU_OPEND=1 ./ai-quant/bin/python -m pytest tests/test_paper_strategy_sleeves_futu_integration.py -q
```

## Verification

Focused backend verification:

```powershell
.\ai-quant\Scripts\Activate.ps1
python -m pytest tests/test_paper_account.py tests/test_api_paper_account.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_paper_strategy_execution.py tests/test_paper_strategy_operations.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py -q
ruff check src/quant_system/execution/account.py src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/execution/paper_strategy_signal_service.py src/quant_system/execution/paper_strategy_execution_service.py src/quant_system/execution/paper_strategy_operations.py src/quant_system/factors/pipeline.py src/quant_system/api/schemas/paper.py src/quant_system/api/routes/paper.py src/quant_system/cli.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_paper_strategy_execution.py tests/test_paper_strategy_operations.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py
git diff --check
```

On macOS in this checkout the equivalent interpreter path is:

```bash
./ai-quant/bin/python -m pytest tests/test_paper_account.py tests/test_api_paper_account.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_paper_strategy_execution.py tests/test_paper_strategy_operations.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py -q
./ai-quant/bin/python -m ruff check src/quant_system/execution/account.py src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/execution/paper_strategy_signal_service.py src/quant_system/execution/paper_strategy_execution_service.py src/quant_system/execution/paper_strategy_operations.py src/quant_system/factors/pipeline.py src/quant_system/api/schemas/paper.py src/quant_system/api/routes/paper.py src/quant_system/cli.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_paper_strategy_execution.py tests/test_paper_strategy_operations.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py
git diff --check
```

Expected focused result after MVP-2 hardening:

- focused mock/API/CLI/factor tests pass
- `QS_TEST_FUTU_OPEND=1` Futu/OpenD integration tests pass when local OpenD is running
- ruff clean
- `git diff --check` clean
