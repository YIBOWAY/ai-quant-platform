# Paper Strategy Sleeves MVP-1 Execution Notes

> Status: first through fourth MVP-1 slices implemented on 2026-06-26.
> Domain models, local storage, cash/lot accounting foundations, backend API
> contract, daily signal generation, the manual signal CLI, and the
> `/paper-trading` Strategy Sleeves workspace are available. Automatic
> execution is still a future slice.

## What Exists Now

The first slice establishes the accounting and persistence base:

- Domain models:
  - `StrategyConfig`
  - `StrategySleeve`
  - `SleeveLot`
  - `StrategySignal`
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
rebalance semantics and is not the Strategy Sleeves entrypoint.

The second slice exposes the backend API contract:

| Method | Path | Status |
|---|---|---|
| `POST` | `/api/paper/strategy-configs` | Creates a version-1 `StrategyConfig`. |
| `GET` | `/api/paper/strategy-configs` | Lists latest config versions. |
| `POST` | `/api/paper/strategy-configs/{id}/versions` | Creates the next config version. |
| `POST` | `/api/paper/strategy-sleeves` | Creates signal-only or allocated sleeves. |
| `GET` | `/api/paper/strategy-sleeves` | Lists sleeves. |
| `GET` | `/api/paper/strategy-sleeves/{id}` | Returns sleeve, lots, and signals. |
| `POST` | `/api/paper/strategy-sleeves/{id}/signals` | Generates and persists one daily signal. |
| `POST` | `/api/paper/strategy-sleeves/{id}/pause` | Pauses a running sleeve. |
| `POST` | `/api/paper/strategy-sleeves/{id}/resume` | Resumes a paused sleeve. |
| `POST` | `/api/paper/strategy-sleeves/{id}/stop` | Stops the sleeve and keeps holdings. |

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
  as an advanced full-account path and continues to call
  `POST /api/paper/account/rebalance`.

The workspace is signal-first. Generating a sleeve signal does not create
pending orders, fills, account position mutations, or automatic execution
jobs.

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
      lots.parquet
```

JSON writes use temp files and atomic replace. Signal JSONL persistence rewrites
the complete file atomically for this MVP-1 foundation slice. Lots are persisted
as parquet snapshots.

## Not Implemented Yet

Do not document or present these as available commands or UI workflows until a
later slice implements them:

- `quant-system paper strategies config-create`
- `quant-system paper strategies sleeve-create`
- scheduled or automatic strategy execution
- next-open or near-close simulated fills
- lot transfer between manual and strategy sleeves

## Real Futu Integration Tests

Normal CI remains mocked/offline. The signal-generation slice includes opt-in
read-only Futu/OpenD tests under a dedicated pytest marker:

```text
pytestmark = pytest.mark.futu_opend
QS_TEST_FUTU_OPEND=1
```

The marker is registered in `pyproject.toml`. These tests verify only
read-only data access and signal persistence: OpenD reachable, small OHLCV fetch
works for configured symbols, `StrategySignal.data_provider == "futu"`, real
`data_as_of` is recorded, and unavailable real data becomes `data_unavailable`
instead of falling back to sample data. Do not import or instantiate Futu trade
contexts.

Run them only when a local read-only OpenD service is intentionally available:

```bash
QS_TEST_FUTU_OPEND=1 ./ai-quant/bin/python -m pytest tests/test_paper_strategy_sleeves_futu_integration.py -q
```

## Verification

Focused backend verification:

```powershell
.\ai-quant\Scripts\Activate.ps1
python -m pytest tests/test_paper_account.py tests/test_api_paper_account.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py -q
ruff check src/quant_system/execution/account.py src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/execution/paper_strategy_signal_service.py src/quant_system/factors/pipeline.py src/quant_system/api/schemas/paper.py src/quant_system/api/routes/paper.py src/quant_system/cli.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py
git diff --check
```

On macOS in this checkout the equivalent interpreter path is:

```bash
./ai-quant/bin/python -m pytest tests/test_paper_account.py tests/test_api_paper_account.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py -q
./ai-quant/bin/python -m ruff check src/quant_system/execution/account.py src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/execution/paper_strategy_signal_service.py src/quant_system/factors/pipeline.py src/quant_system/api/schemas/paper.py src/quant_system/api/routes/paper.py src/quant_system/cli.py tests/test_paper_strategy_sleeves.py tests/test_paper_strategy_signals.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py tests/test_factors_pipeline.py
git diff --check
```

Expected focused result as of 2026-06-26 after the third slice:

- focused mock/API/CLI/factor tests pass
- `QS_TEST_FUTU_OPEND=1` Futu/OpenD integration test passes when local OpenD is running
- ruff clean
- `git diff --check` clean
