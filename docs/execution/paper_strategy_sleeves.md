# Paper Strategy Sleeves MVP-1 Execution Notes

> Status: first and second backend slices implemented on 2026-06-26. Domain
> models, local storage, cash/lot accounting foundations, and the backend API
> contract are available. CLI commands, frontend panels, signal generation, and
> automatic execution are still future slices.

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
| `POST` | `/api/paper/strategy-sleeves/{id}/pause` | Pauses a running sleeve. |
| `POST` | `/api/paper/strategy-sleeves/{id}/resume` | Resumes a paused sleeve. |
| `POST` | `/api/paper/strategy-sleeves/{id}/stop` | Stops the sleeve and keeps holdings. |

Allocated sleeve creation runs under the existing paper-account in-process lock
and filesystem lock. It allocates from `sleeve_cash["manual"]`, writes the sleeve
under `paper_strategy_sleeves/`, and saves the account. It does not change
`PaperAccount.cash`, and it does not execute orders.

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
- `quant-system paper strategies generate-signal`
- `/paper-trading` Strategy Sleeves panel
- daily signal generation service
- scheduled or automatic strategy execution
- next-open or near-close simulated fills
- lot transfer between manual and strategy sleeves

## Real Futu Integration Test Plan

Normal CI remains mocked/offline. The signal-generation slice must add opt-in
read-only Futu/OpenD tests under a dedicated pytest marker:

```text
pytestmark = pytest.mark.futu_opend
QS_TEST_FUTU_OPEND=1
```

The marker is registered in `pyproject.toml`. These tests should verify only
read-only data access and signal persistence: OpenD reachable, small OHLCV fetch
works for configured symbols, `StrategySignal.data_provider == "futu"`, real
`data_as_of` is recorded, and unavailable real data becomes `data_unavailable`
instead of falling back to sample data. Do not import or instantiate Futu trade
contexts.

## Verification

Focused backend verification:

```powershell
.\ai-quant\Scripts\Activate.ps1
python -m pytest tests/test_paper_account.py tests/test_api_paper_account.py tests/test_paper_strategy_sleeves.py tests/test_api_paper_strategy_sleeves.py -q
ruff check src/quant_system/execution/account.py src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/api/schemas/paper.py src/quant_system/api/routes/paper.py tests/test_paper_strategy_sleeves.py tests/test_api_paper_strategy_sleeves.py
git diff --check
```

On macOS in this checkout the equivalent interpreter path is:

```bash
./ai-quant/bin/python -m pytest tests/test_paper_account.py tests/test_api_paper_account.py tests/test_paper_strategy_sleeves.py tests/test_api_paper_strategy_sleeves.py -q
./ai-quant/bin/python -m ruff check src/quant_system/execution/account.py src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/api/schemas/paper.py src/quant_system/api/routes/paper.py tests/test_paper_strategy_sleeves.py tests/test_api_paper_strategy_sleeves.py
git diff --check
```

Expected focused result as of 2026-06-26:

- `62 passed`
- ruff clean
- `git diff --check` clean
