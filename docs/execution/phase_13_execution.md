# Phase 13 Execution Guide

## Offline Sample Run

```powershell
conda activate ai-quant
quant-system options daily-scan --provider sample --top 5 --date 2026-05-03 --output-dir data\_phase13_sample_scan
```

Expected output:

```text
dry_run=false provider=sample top=5 strategies=sell_put,covered_call output_dir=data\_phase13_sample_scan
run_date=2026-05-03 universe_size=5 scanned_tickers=5 failed_tickers=0 candidates=50 data=data\_phase13_sample_scan\2026-05-03.jsonl meta=data\_phase13_sample_scan\2026-05-03_meta.json
```

## Dry Run

```powershell
quant-system options daily-scan --provider sample --top 5 --date 2026-05-03 --output-dir data\_phase13_sample_scan --dry-run
```

Expected output:

```text
dry_run=true provider=sample top=5 strategies=sell_put,covered_call output_dir=data\_phase13_sample_scan
provider_check=skipped
```

## Futu Read-only Check

```powershell
quant-system options daily-scan --top 5 --dry-run
```

On a machine where OpenD is running, this prints `provider_check=ok`.
If OpenD is unavailable, the command exits with code `3` and prints
`provider_check=failed`.

## API

```powershell
curl "http://127.0.0.1:8765/api/options/daily-scan/dates"
curl "http://127.0.0.1:8765/api/options/daily-scan?date=2026-05-03&strategy=sell_put&top=20"
```

## Frontend

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765

cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

Open:

```text
http://127.0.0.1:3001/options-radar
```

## Verification Commands

Run Playwright from the nested frontend package so it uses the same local
`@playwright/test` dependency as the app:

```powershell
conda activate ai-quant
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts
```

Expected output:

```text
14 passed
```

The Playwright config locates the repository root by walking upward until it
finds `pyproject.toml` and `src/frontend/package.json`, so the API and frontend
servers use the current checkout instead of a stale working directory.

## Manual Refresh Commands

```powershell
python scripts/refresh_options_universe.py --bootstrap-github --output data/options_universe/sp500_nasdaq100.csv
python scripts/refresh_earnings_calendar.py --top 100
python scripts/refresh_vix_history.py --output data/options_universe/vix_history.csv --lookback-days 400
```

The last command pulls `^VIX` / `^VIX3M` daily closes from
`query1.finance.yahoo.com` (read-only HTTPS GET, no API key) and writes a
CSV cache. The next `daily-scan` will print a `market_regime=...` line such
as:

```text
market_regime=Normal w_vix=1.0 vix_density=0.227 term_ratio=0.899
```

When the CSV is missing the scan still runs but logs
`market_regime=Unknown reason=no_vix_history` and applies no penalty.
