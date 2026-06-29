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
> commands; installing automatic scheduling remains a future slice.

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
| `GET` | `/api/paper/strategy-sleeves` | Lists sleeves. |
| `GET` | `/api/paper/strategy-sleeves/{id}` | Returns sleeve, lots, signals, and executions. |
| `POST` | `/api/paper/strategy-sleeves/{id}/signals` | Generates and persists one daily signal. |
| `POST` | `/api/paper/strategy-sleeves/{id}/executions` | Creates one pending execution plan from a selected generated signal. |
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
allocation is saved but before finalization, later sleeve list/detail/signal
paths reconcile the pending journal against `PaperAccount.sleeve_cash`. It does
not change `PaperAccount.cash`, and it does not execute orders.

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
- sleeve detail/process paths and CLI `execute-pending` reconcile pending
  journals under the existing account+sleeve locks
- corrupt pending journal files are preserved as
  `<execution_id>.corrupt-*.json` and skipped rather than deleted silently

MVP-3 Slice 1 adds the shared operations runner in
`src/quant_system/execution/paper_strategy_operations.py`. CLI commands, API
execution processing, and future scheduler adapters should call this runner
rather than duplicate lock, recovery, pending-plan scanning, account-save, or
journal-commit logic.

Scheduler-safe one-shot commands now available:

```bash
quant-system paper strategies generate-due-signals --date 2024-03-20 --format json
quant-system paper strategies execute-due --target-date 2026-06-29
quant-system paper strategies ops-status --target-date 2026-06-29 --format json
```

`generate-due-signals` generates one daily signal per eligible sleeve for the
given date and skips sleeves that already have a signal for that date.
`execute-due` is the scheduler-friendly alias for the existing one-shot pending
execution processor. `ops-status` reports due work, pending journals, blocked
executions, and recovery-required counts without placing any real broker orders.
These commands are safe to call from a host scheduler because file locks and
idempotency checks remain in the backend runner.

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
- installed macOS LaunchAgent scheduling
- near-close simulated fills
- lot transfer between manual and strategy sleeves

The next implementation line is documented in
[`docs/design/paper_strategy_sleeves_mvp3_operations_plan.md`](../design/paper_strategy_sleeves_mvp3_operations_plan.md).
MVP-3 continues with macOS LaunchAgent lifecycle assets, retry semantics, and a
frontend operator status surface. It must not add duplicate schedulers or any
real broker trading path.

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
