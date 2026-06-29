# Paper Strategy Sleeves MVP-3 Operations & Automation Plan

**Status:** Slice 0 execution journal/recovery started on 2026-06-29.
Revised on 2026-06-29 for the Mac always-on local-service direction.
Slice 1 operations runner and scheduler-safe CLI commands started on 2026-06-29.
Slice 2 macOS LaunchAgent templates and runbook started on 2026-06-29.

**Goal:** make Paper Strategy Sleeves reliable as a Mac-local paper-trading
operations workflow: supervised local services, scheduled signal generation,
scheduled due-plan processing, recoverable execution state, clear retry
semantics, and operator visibility. MVP-3 is still paper-only and read-only with
respect to brokers.

## 1. First-Principles Check

The user now wants the app to be able to keep running on the local Mac, start
when the Mac/user session starts, and stop when the Mac shuts down. That changes
the process-lifecycle plan, but it does not change the core product promise:

1. a strategy sleeve owns a bounded cash and lot book inside one persistent
   paper account
2. EOD signals become dated execution intent
3. due execution intent mutates only that sleeve's cash/lots and the aggregate
   paper-account view
4. every mutation is auditable and recoverable
5. missed data, missed windows, and local process downtime are visible instead
   of silently fabricated

From those principles, MVP-3 should separate **service lifecycle** from
**workflow scheduling**:

- `launchd` may supervise the local backend and frontend so the web app is
  available after login.
- Strategy automation should first be expressed as one-shot, scheduler-safe
  operations with deterministic exits and structured status.
- A single backend operations module should own recovery, due-work discovery,
  signal generation, execution processing, and status summarization.
- CLI commands, FastAPI routes, and any future resident worker must call that
  same operations module instead of each encoding business rules.
- MVP-3 should not start with a default FastAPI recurring strategy loop. A
  resident worker can be considered later, behind an explicit setting, only
  after one-shot operation semantics, status, locks, and recovery are stable.

For macOS, use user-level **LaunchAgents** first. They fit this repo's user-owned
paths, local virtualenv, `.env`, Futu/OpenD session assumptions, and
`data/api_runs/` permissions. A root-level LaunchDaemon should be avoided unless
there is a later explicit need to run before user login.

## 2. Non-Goals

MVP-3 must not add:

- real broker trade placement, trade unlock, order modification, or cancellation
- Futu trade contexts; read-only quote and OHLCV access only
- automatic execution from the React UI without an explicit API/CLI action
- duplicate schedulers that can process the same due work through different
  business-rule paths
- a default FastAPI-resident recurring strategy scheduler before one-shot
  operation semantics and status are stable
- synthetic sample prices for account mutation
- cross-sleeve cash reallocation or automatic lot transfer
- near-close fills until next-open automation and recovery are stable

## 3. Hard Invariants

- Local files remain the source of truth.
- `PaperAccount.cash` remains the legacy aggregate cash field.
- `PaperAccount.sleeve_cash` remains the sleeve cash allocation book.
- Old full-account rebalance remains an advanced legacy path, but it must be
  blocked when actual strategy-sleeve lots exist.
- A plan is executable only when `execution_window`, `target_date`, sleeve
  status, account status, prices, cash, and lots are all valid at processing
  time.
- If current paper prices are unavailable, the system records a blocked or
  retryable state. It must not invent a price.
- The same execution plan can be processed repeatedly without duplicate fills.
- Cross-file state changes must become recoverable before unattended scheduling
  is considered done.
- Only one active scheduler path should be enabled for strategy-sleeve
  execution at a time.
- LaunchAgent scripts must run as the local user, never as root, so local files
  and locks keep the same ownership as API/CLI/manual workflows.
- Shell scripts and plist templates must not contain business logic beyond
  selecting the command to run and where logs go.

## 4. Current Adversarial Findings

The 2026-06-29 audit found several issues that shaped MVP-3:

- **Fixed in MVP-2 hardening:** execution plans created without `target_date`
  now default to the local run date; invalid API `target_date` values are
  rejected.
- **Fixed in MVP-2 hardening:** transient price-source failures during execution
  now block the plan as `price_unavailable` instead of surfacing as an
  untracked server error.
- **Fixed in MVP-2 hardening:** `/paper-trading` only enables "process due"
  when a pending `next_open` plan is actually due today.
- **Fixed in MVP-2 hardening:** the page fetches detail for every sleeve and
  does not label historical-version sleeves with the latest config metadata.
- **Fixed in MVP-2 hardening:** old full-account rebalance is blocked only when
  actual sleeve-owned sources exist, not merely because legacy strategy sources
  exist.
- **Fixed in MVP-3 Slice 0:** execution processing writes a pending journal
  with before/after account, sleeve, lots, and execution snapshots before
  mutating files. API/CLI success paths finalize the journal only after the
  account save succeeds; later sleeve detail/process access reconciles pending
  journals.
- **MVP-3 plan revision:** Mac always-on mode changes the service lifecycle
  target to LaunchAgent-supervised local processes, but scheduler semantics
  remain one-shot and lock-protected until the operations runner, status, and
  retry model are stable.
- **Still open for MVP-3:** lock-timeout errors and retryable vs terminal
  blocked states need explicit operator semantics.

## 5. MVP-3 Slices

### Slice 0: Execution Journal And Recovery

This is the first blocker for unattended automation.

Add a small execution journal under each sleeve before mutating account/sleeve
state:

```text
data/api_runs/paper_strategy_sleeves/sleeves/<sleeve_id>/
  executions.jsonl
  execution_journal/
    <execution_id>.pending.json
    <execution_id>.committed.json
```

Flow:

1. acquire account lock and sleeve lock
2. preflight prices, cash, lots, and idempotency
3. write a pending journal containing before/after account fingerprints,
   before/after sleeve cash, before/after lots, planned fills, and target
   execution status
4. write account, sleeve, lots, and execution state
5. replace the journal with committed status
6. on startup or any sleeve detail/process call, reconcile pending journals

Recovery rules:

- If the journal exists and no fill ledger entries exist, replay or roll back
  based on stored fingerprints.
- If account ledger already has the execution fill ids and sleeve/lots lag,
  finalize sleeve/lots/execution from the journal.
- If account and sleeve/lots disagree and fingerprints do not match, mark the
  execution `blocked` with `recovery_required` and surface it in ops status.
- Never re-create broker-facing actions; this is paper-only local state repair.

Tests:

- crash after journal/sleeve/lots/execution writes before account save
- account already has fill ledger entries while sleeve/lots/execution lag
- detail/process recovery finalizes pending journals after account save
- double process after committed journal
- corrupt journal is preserved and skipped, not silently deleted

Implemented in Slice 0:

- `PaperStrategyExecutionService.execute_plan()` computes the after-state on
  deep copies, writes a pending journal, then materializes account, sleeve,
  lots, and execution state.
- `PaperStrategyExecutionService.reconcile_execution_journals()` repairs
  interrupted executions from pending journals and can defer journal finalizing
  until the caller saves the account.
- `PaperStrategySleeveStorage` owns pending/committed/corrupt journal files.
- API sleeve detail/process and CLI `execute-pending` reconcile pending
  journals under the existing account+sleeve locks.

Still open after Slice 0:

- expose `recovery_required` in an operator status view
- map lock timeouts to structured API/CLI status
- split retryable vs terminal blocked states

Implemented in Slice 1 so far:

- `src/quant_system/execution/paper_strategy_operations.py` defines
  `PaperStrategyOperationsRunner`, the shared operations seam for CLI/API/future
  scheduler adapters.
- CLI commands now include `generate-due-signals`, `execute-due`, and
  `ops-status`.
- `execute-pending` remains available and now delegates to the operations
  runner.
- `POST /api/paper/strategy-sleeves/executions/process` delegates to the same
  runner instead of carrying its own pending-plan processing loop.

### Slice 1: Operations Runner And Scheduler-Safe Commands

Add a deep operations module that becomes the single seam used by CLI, API, and
future schedulers:

```text
src/quant_system/execution/paper_strategy_operations.py
  PaperStrategyOperationsRunner
    generate_signal_once(...)
    create_execution_once(...)
    process_pending_executions_once(...)
    ops_status(...)
```

Responsibilities:

- acquire account and sleeve locks in the established order
- reconcile pending sleeve allocation journals
- reconcile execution journals before status or processing
- discover due signals and due execution plans
- call `PaperStrategySignalService`, `PaperStrategySleeveService`, and
  `PaperStrategyExecutionService`
- save account state and finalize execution journals in the existing recovery
  order
- return structured results that CLI/API/UI can render without reimplementing
  accounting rules

Add host-scheduler friendly commands with deterministic exits and structured
status output:

```bash
quant-system paper strategies generate-due-signals --date YYYY-MM-DD
quant-system paper strategies execute-due --window next_open --target-date YYYY-MM-DD
quant-system paper strategies ops-status --date YYYY-MM-DD --format json
```

Behavior:

- no default resident strategy scheduler
- no route-level scheduling logic
- one command does one bounded unit of work
- file locks protect CLI/API concurrency
- lock timeout returns a documented non-zero exit and structured status
- `--dry-run` is available for status and plan preview commands only
- CLI can be used directly by LaunchAgent one-shot jobs or by an operator during
  manual recovery

### Slice 2: Mac Local Service Lifecycle

Add macOS local-service assets only after Slice 1 has stable status semantics.

Recommended files:

```text
scripts/run_paper_strategy_sleeves.sh
scripts/launchd/com.aiquant.paper-sleeves.signals.plist.template
scripts/launchd/com.aiquant.paper-sleeves.execute-due.plist.template
scripts/install_paper_strategy_sleeves_launchagent.sh
scripts/uninstall_paper_strategy_sleeves_launchagent.sh
docs/execution/paper_strategy_sleeves_launchd.md
```

Initial stance:

- use LaunchAgent, not LaunchDaemon
- do not require `sudo`
- use absolute paths for the repo and Python interpreter
- write logs under `data/_runtime/logs/`
- keep strategy tasks as one-shot jobs with `KeepAlive=false`
- install backend/frontend LaunchAgents separately from strategy one-shot jobs
  so UI availability does not imply auto-execution is enabled
- document how to bootstrap, unload, inspect logs, and run commands manually

For the web app, long-running local use should prefer production-style frontend
serving over `npm run dev`. Never run `npm run build` while a frontend dev
server is using the same `.next` directory.

Implemented in Slice 2 so far:

- backend and frontend LaunchAgent templates are separated from strategy
  one-shot job templates
- backend/frontend wrappers bind to localhost and write runtime logs
- strategy wrappers expose `ops-status`, `generate-due-signals`, and
  `execute-due`
- install/uninstall scripts render templates into `~/Library/LaunchAgents/`
  and use `launchctl bootstrap/bootout gui/$(id -u)` without `sudo`
- runbook:
  `docs/execution/paper_strategy_sleeves_launchd.md`

### Slice 3: Retry Semantics

Split blocked outcomes into terminal and retryable classes.

Suggested statuses:

- `pending`
- `filled`
- `blocked`
- `retryable_blocked`
- `missed`
- `recovery_required`

Retryable examples:

- `price_unavailable`
- `data_unavailable`
- `lock_timeout`
- `account_temporarily_unavailable`

Terminal examples:

- `insufficient_sleeve_cash`
- `insufficient_sleeve_lot`
- `sleeve_paused`
- `account_frozen`
- `duplicate_execution`
- `invalid_target_date`

MVP-3 can either add `retry_class` to the existing model or introduce the
`retryable_blocked` status. The implementation should choose the smaller schema
change after tests prove the UI and CLI can distinguish operator action from
automatic retry.

### Slice 4: Config And Sleeve CLI Helpers

Add CLI helpers only after recovery and scheduler status are in place:

```bash
quant-system paper strategies config-create ...
quant-system paper strategies sleeve-create ...
quant-system paper strategies sleeve-show --sleeve <id>
```

These are convenience wrappers around existing API/domain behavior. They must
not add new execution semantics.

### Slice 5: Operations Surface

Add a compact status panel to `/paper-trading`, not a separate heavy dashboard
at first:

- due signals today
- pending executions due today
- missed executions
- retryable blocked executions
- recovery-required executions
- last scheduler command result if an ops status file exists

The UI should remain explicit that the user is seeing local paper automation,
not broker automation.

Frontend design direction:

- place the panel in the live account tab after account summary and before the
  sleeve workspace
- keep the visual language dense, calm, and audit-oriented
- show `paper-only`, `live trading disabled`, scheduler mode, target date, local
  timezone, last refresh, due counts, retryable issues, recovery-required
  items, and latest command result
- keep refresh/status actions separate from execution actions
- do not merge old full-account rebalance into this panel

### Slice 6: Near-Close Research Gate

Only start near-close simulation after Slice 0 through Slice 4 pass.

Required design decisions:

- market calendar and timezone source
- same-day 5m bar vs snapshot preference
- missed window semantics
- no historical backfill that pretends the near-close window was observed live

### Slice 7: Manual Lot Transfer

Lot transfer is optional and should remain operator-explicit:

- transfer from manual to sleeve
- transfer from sleeve to manual
- never automatic cross-sleeve rebucketing
- ledger entries must preserve source, quantity, cost basis, and reason

## 6. Verification Matrix

Always-run checks:

```bash
./ai-quant/bin/python -m pytest -q \
  tests/test_paper_strategy_sleeves.py \
  tests/test_paper_strategy_execution.py \
  tests/test_api_paper_strategy_sleeves.py \
  tests/test_cli.py
./ai-quant/bin/python -m ruff check \
  src/quant_system/execution/paper_strategy_sleeves.py \
  src/quant_system/execution/paper_strategy_sleeve_storage.py \
  src/quant_system/execution/paper_strategy_execution_service.py \
  src/quant_system/api/schemas/paper.py \
  src/quant_system/api/routes/paper.py \
  src/quant_system/cli.py \
  tests/test_paper_strategy_sleeves.py \
  tests/test_paper_strategy_execution.py \
  tests/test_api_paper_strategy_sleeves.py \
  tests/test_cli.py
npm --prefix src/frontend run type-check
git diff --check
```

Opt-in real Futu/OpenD checks:

```bash
QS_TEST_FUTU_OPEND=1 ./ai-quant/bin/python -m pytest -q \
  tests/test_paper_strategy_sleeves_futu_integration.py
```

Safety checks:

```bash
rg "OpenSecTradeContext|unlock_trade|place_order|modify_order|cancel_order" \
  src/quant_system tests docs
```

Any allowed matches must be existing safety tests or explicit "do not use"
documentation, not runtime strategy-sleeve code.

## 7. Done Criteria

MVP-3 is done only when:

- scheduled commands can be run repeatedly by LaunchAgent or another external
  scheduler
- a stopped FastAPI/frontend process does not lose due work
- Mac service lifecycle docs explain start on login, stop on shutdown, logs,
  unload, and manual recovery
- interrupted execution processing is recoverable and tested
- operator status tells the user what ran, what filled, what was skipped, and
  what needs manual intervention
- real Futu/OpenD tests remain opt-in and read-only
- no real broker trading imports or calls are introduced
