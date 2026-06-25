# Paper Strategy Sleeves MVP-1 Execution Notes

> Status: first backend foundation slice implemented on 2026-06-26. This is not
> a user-facing trading workflow yet. API routes, CLI commands, frontend panels,
> signal generation, and automatic execution are still future slices.

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

- `POST /api/paper/strategy-configs`
- `POST /api/paper/strategy-sleeves`
- `quant-system paper strategies config-create`
- `quant-system paper strategies sleeve-create`
- `quant-system paper strategies generate-signal`
- `/paper-trading` Strategy Sleeves panel
- scheduled or automatic strategy execution
- next-open or near-close simulated fills
- lot transfer between manual and strategy sleeves

## Verification

Focused backend verification:

```powershell
.\ai-quant\Scripts\Activate.ps1
python -m pytest tests/test_paper_account.py tests/test_api_paper_account.py tests/test_paper_strategy_sleeves.py -q
ruff check src/quant_system/execution/account.py src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/api/schemas/paper.py tests/test_paper_strategy_sleeves.py
git diff --check
```

On macOS in this checkout the equivalent interpreter path is:

```bash
./ai-quant/bin/python -m pytest tests/test_paper_account.py tests/test_api_paper_account.py tests/test_paper_strategy_sleeves.py -q
./ai-quant/bin/python -m ruff check src/quant_system/execution/account.py src/quant_system/execution/paper_strategy_sleeves.py src/quant_system/execution/paper_strategy_sleeve_storage.py src/quant_system/api/schemas/paper.py tests/test_paper_strategy_sleeves.py
git diff --check
```

Expected focused result as of 2026-06-26:

- `56 passed`
- ruff clean
- `git diff --check` clean
