# Paper Strategy Sleeves MVP-2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Paper Strategy Sleeves from signal observation into auditable
pseudo-live paper execution without introducing live trading, broker trade
contexts, or a long-running FastAPI scheduler.

**Architecture:** MVP-2 adds a pending execution lifecycle between
`StrategySignal` and sleeve lot/cash mutation. The first execution mode is
daily `next_open`: EOD signals create pending executions, a CLI/API call later
executes due plans with real paper prices, and skipped or missed windows are
recorded instead of fabricated. Local files remain the source of truth; the
single persistent `PaperAccount` remains the aggregate account, while
`StrategySleeve.cash` and `SleeveLot` remain the strategy-level accounting
books.

**Tech Stack:** Python 3.11+/Pydantic/FastAPI/Typer/Pandas/Parquet/JSONL,
existing `PaperAccount`, `SleeveLotBook`, `PaperPriceSource`, `PaperBroker`,
and Next.js/Tailwind only after backend execution state exists.

---

## Scope

MVP-2 is about **paper-only strategy sleeve execution**. It does not add real
broker trading. It does not import or instantiate Futu trade contexts, does not
unlock accounts, and does not place, modify, or cancel real broker orders.

## Core Invariants

- `signal_only` sleeves never create executable plans.
- `allocated` sleeves may create executable plans only from generated,
  unblocked signals with proposed orders.
- Execution must consume only the addressed sleeve's cash and lots.
- A sleeve can never sell `manual` lots or another sleeve's lots.
- `PaperAccount.cash` remains the legacy total cash field for old full-account
  behavior. Sleeve execution must update the aggregate account and the sleeve
  accounting book consistently, but must not make the old full-account
  rebalance endpoint sleeve-aware.
- Missing real prices, stale windows, paused sleeves, stopped sleeves, frozen
  accounts, and data provider failures produce durable skipped/blocked/missed
  records. They must not silently disappear.
- Same execution plan is idempotent. Re-running the same due plan cannot fill it
  twice.
- Automatic scheduling is external: CLI plus Task Scheduler/cron/launch agent
  if the user chooses. FastAPI must not become the first scheduler.

## Domain Model Additions

### StrategyExecutionPlan

```text
StrategyExecutionPlan
├─ execution_id
├─ sleeve_id
├─ account_id
├─ signal_id
├─ strategy_config_id
├─ strategy_config_version
├─ execution_window          # next_open first; near_close_5m future
├─ target_date               # trading date the execution is intended for
├─ created_at
├─ updated_at
├─ status                    # pending / filled / partially_filled / skipped /
│                            # blocked / missed_window / failed / cancelled
├─ blocked_reason            # sleeve_paused / account_frozen / stale_price /
│                            # data_unavailable / no_orders / null
├─ orders                    # list[StrategyExecutionOrder]
├─ fills                     # list[StrategyExecutionFill]
├─ warnings
└─ metadata
```

### StrategyExecutionOrder

```text
StrategyExecutionOrder
├─ symbol
├─ side                      # buy / sell
├─ target_weight
├─ current_value
├─ target_value
├─ notional_delta
├─ reference_price
├─ estimated_quantity
├─ min_order_value
└─ reason
```

### StrategyExecutionFill

```text
StrategyExecutionFill
├─ symbol
├─ side
├─ requested_quantity
├─ filled_quantity
├─ fill_price
├─ gross_value
├─ commission
├─ price_kind
├─ filled_at
└─ note
```

## Storage Layout

```text
data/api_runs/paper_strategy_sleeves/
  sleeves/
    <sleeve_id>/
      sleeve.json
      lots.parquet
      signals.jsonl
      executions.jsonl
```

`executions.jsonl` is append-only by semantic event, but persisted atomically by
rewriting the complete compact JSONL file for MVP-2 consistency with the
existing signal storage pattern. Every execution row carries its full current
state so detail pages and CLI commands can load without replaying events.

## API Contract

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/paper/strategy-sleeves/{id}/signals` | Keep existing signal generation. In MVP-2 it may also create a pending execution for allocated sleeves when `create_execution=true`. Default should stay compatible until UI opts in. |
| `POST` | `/api/paper/strategy-sleeves/{id}/executions` | Create a pending execution from a selected signal. |
| `GET` | `/api/paper/strategy-sleeves/{id}` | Include latest executions alongside sleeve, lots, and signals. |
| `POST` | `/api/paper/strategy-sleeves/executions/process` | Process due pending executions for a window, initially `next_open`. |
| `GET` | `/api/paper/strategy-sleeves/executions/recent` | Optional listing for UI history after backend is stable. |

## CLI Contract

```bash
quant-system paper strategies create-execution --sleeve <id> --signal <signal_id> --window next-open
quant-system paper strategies execute-pending --window next-open --target-date YYYY-MM-DD
```

The CLI must exit non-zero when a requested execution cannot be created or when
processing due executions finds a hard failure. It may exit zero for skipped or
missed plans if those states are expected and durably recorded.

## MVP-2 Slices

### Slice 1: Pending Execution Foundation

Status: implemented on 2026-06-27.

**Files:**

- Modify: `src/quant_system/execution/paper_strategy_sleeves.py`
- Modify: `src/quant_system/execution/paper_strategy_sleeve_storage.py`
- Modify: `src/quant_system/api/schemas/paper.py`
- Modify: `tests/test_paper_strategy_sleeves.py`
- Modify: `tests/test_api_paper_strategy_sleeves.py`
- Modify: `docs/execution/paper_strategy_sleeves.md`
- Modify: `docs/guides/paper-trading.md`

**Behavior:**

- Add `StrategyExecutionPlan`, `StrategyExecutionOrder`, and
  `StrategyExecutionFill` Pydantic models.
- Add storage helpers:
  - `sleeve_executions_path(sleeve_id)`
  - `append_execution(plan)`
  - `save_executions(sleeve_id, plans)`
  - `load_executions(sleeve_id)`
  - `latest_execution_for_signal(sleeve_id, signal_id)`
- Add a service method that builds a pending plan from a generated signal
  without mutating account cash, positions, sleeve cash, or lots.
- Reject plan creation for:
  - signal-only sleeve (`signal_only_no_execution`)
  - stopped sleeve (`sleeve_stopped`)
  - paused sleeve (`sleeve_paused`)
  - frozen account (`account_frozen`)
  - signal without proposed orders (`no_proposed_orders`)
  - duplicate signal execution (`execution_already_exists`)

**Verification:**

```bash
./ai-quant/bin/python -m pytest -q tests/test_paper_strategy_sleeves.py tests/test_api_paper_strategy_sleeves.py
./ai-quant/bin/python -m ruff check src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/api/schemas/paper.py src/quant_system/api/routes/paper.py tests/test_paper_strategy_sleeves.py tests/test_api_paper_strategy_sleeves.py
```

### Slice 2: Next-Open Execution Processor

Status: backend service implemented on 2026-06-27. API/CLI processing
entrypoints remain Slice 3.

**Files:**

- Create: `src/quant_system/execution/paper_strategy_execution_service.py`
- Modify: `src/quant_system/execution/paper_strategy_sleeves.py`
- Modify: `src/quant_system/execution/paper_strategy_sleeve_storage.py`
- Modify: `src/quant_system/execution/account.py` only if aggregate
  source-quantity updates need a narrow helper; do not change legacy rebalance
  semantics.
- Test: `tests/test_paper_strategy_execution.py`

**Behavior:**

- Load pending plans for `execution_window="next_open"` and `target_date`.
- Re-check sleeve/account state immediately before execution.
- Resolve real paper prices through the existing price path; no sample prices.
- Apply fills in this order:
  1. sell orders against `SleeveLotBook.sell()`
  2. buy orders against `StrategySleeve.cash`
  3. update aggregate `PaperAccount.positions` source quantity for
     `strategy:<sleeve_id>`
  4. append ledger entries with `kind="sleeve_execution_fill"`
  5. persist account, sleeve, lots, and execution state under the shared locks
- If any leg fails in a way that would leave partial inconsistent state, abort
  before mutation. If partial fill is intentionally allowed later, it must be a
  separate explicit design change.

**Verification:**

```bash
./ai-quant/bin/python -m pytest -q tests/test_paper_strategy_execution.py tests/test_paper_account.py
./ai-quant/bin/python -m ruff check src/quant_system/execution/paper_strategy_execution_service.py tests/test_paper_strategy_execution.py
```

### Slice 3: CLI And API Processing Entrypoints

Status: implemented on 2026-06-27.

**Files:**

- Modify: `src/quant_system/api/routes/paper.py`
- Modify: `src/quant_system/api/schemas/paper.py`
- Modify: `src/quant_system/cli.py`
- Modify: `tests/test_api_paper_strategy_sleeves.py`
- Modify: `tests/test_cli.py`

**Behavior:**

- Add pending execution processing endpoint.
- Add CLI commands:
  - `paper strategies create-execution`
  - `paper strategies execute-pending`
- Maintain file and account locks around all mutations.

The manual execution creation endpoint landed in Slice 1:
`POST /api/paper/strategy-sleeves/{id}/executions`.

**Verification:**

```bash
./ai-quant/bin/python -m pytest -q tests/test_api_paper_strategy_sleeves.py tests/test_cli.py
./ai-quant/bin/python -m ruff check src/quant_system/api/routes/paper.py src/quant_system/api/schemas/paper.py src/quant_system/cli.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py
```

### Slice 4: Paper Trading UI Execution State

**Status:** implemented on 2026-06-27.

**Files:**

- Modify: `src/frontend/lib/api.ts`
- Modify: `src/frontend/components/forms/PaperStrategySleevesPanel.tsx`
- Modify: `tests/test_frontend_paper_strategy_sleeves_ui_contract.py`
- Optional after backend is stable: `src/frontend/lib/paperStrategySleeves.ts`

**Behavior:**

- Show latest pending/executed/missed execution per sleeve.
- Add a conservative "Create execution plan" action only for allocated running
  sleeves with a generated unblocked signal.
- Add a conservative manual "Process pending" action that calls the backend
  one-shot processor for the selected sleeve.
- Do not show an auto-run toggle until a scheduler story exists.
- Keep all copy explicit: paper-only, no live trading, no broker execution.

**Verification:**

```bash
npm --prefix src/frontend run lint
npm --prefix src/frontend run type-check
npm --prefix src/frontend test -- paperStrategySleeves.test.ts
./ai-quant/bin/python -m pytest -q tests/test_frontend_paper_strategy_sleeves_ui_contract.py
```

### Slice 5: Opt-In Real Futu Execution Window Check

**Files:**

- Modify: `tests/test_paper_strategy_sleeves_futu_integration.py`
- Modify: `docs/execution/paper_strategy_sleeves.md`

**Behavior:**

- Keep normal CI mocked/offline.
- Under `QS_TEST_FUTU_OPEND=1`, verify that a real Futu snapshot or latest real
  close can support the execution processor without importing trade contexts.
- The test must stay read-only and must not place real orders.

**Verification:**

```bash
QS_TEST_FUTU_OPEND=1 ./ai-quant/bin/python -m pytest -q tests/test_paper_strategy_sleeves_futu_integration.py
```

## Done Criteria For MVP-2

- An allocated sleeve can turn a generated signal into exactly one pending
  execution plan.
- A due pending execution can be processed once and only once.
- Successful execution mutates only that sleeve's cash/lots plus the aggregate
  paper account view.
- Missing prices, paused/frozen/stopped state, and missed windows become durable
  execution states.
- Old `POST /api/paper/account/rebalance` behavior is unchanged.
- Normal tests do not require Futu/OpenD.
- Real Futu/OpenD checks remain opt-in, read-only, and never touch trade
  contexts.
