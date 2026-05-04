# Phase 13 Delivery - Options Radar

## Delivered

- Static `S&P 500 union Nasdaq 100` universe CSV.
- Manual universe and earnings refresh scripts.
- Read-only Futu rate limiter.
- IV history and IV Rank computation.
- Offline earnings calendar.
- VIX regime classifier (V5 dual factor) wired end-to-end via Yahoo Chart REST.
- Yahoo `^VIX` / `^VIX3M` fetcher + CSV cache + manual refresh script.
- Cross-ticker Options Radar scanner with per-strategy regime penalty.
- Single-ticker `/api/options/screener` route + `/options-screener` page now
  share the same VIX regime path: result payload exposes `market_regime` +
  `market_regime_penalty` and applies seller rating demotion (Strong->Watch
  under Elevated; sell_put forced to Avoid under Panic). UI shows a regime
  banner above the metrics grid.
- Idempotent daily JSONL snapshot storage (writes `market_regime` +
  `market_regime_penalty` into every candidate).
- CLI commands:
  - `quant-system options daily-scan`
  - `quant-system options refresh-universe`
  - `quant-system options refresh-earnings`
  - `quant-system options refresh-vix`
- API:
  - `GET /api/options/daily-scan/dates`
  - `GET /api/options/daily-scan`
- Frontend page:
  - `/options-radar`
  - date / strategy / sector / DTE / Top N filters
  - safety banner
  - details expansion
  - CSV export

## Validation Snapshot

```text
pytest: 274 tests collected, full run passed
ruff: All checks passed
frontend lint: passed
frontend build: passed
playwright: 14 passed
```

Sample run with real VIX history (Yahoo refresh ran 2026-05-03):

```text
dry_run=false provider=sample top=5 strategies=sell_put,covered_call output_dir=data\options_scans
market_regime=Normal w_vix=1.0 vix_density=0.227 term_ratio=0.899
run_date=2026-05-03 universe_size=5 scanned_tickers=5 failed_tickers=0 candidates=50 data=data\options_scans\2026-05-03.jsonl meta=data\options_scans\2026-05-03_meta.json
```

Dry-run sample:

```text
dry_run=true provider=sample top=5 strategies=sell_put,covered_call output_dir=data\options_scans
provider_check=skipped
```

Yahoo VIX refresh (read-only, no API key):

```text
python scripts/refresh_vix_history.py --output data/options_universe/vix_history.csv --lookback-days 400
source=yahoo_chart fetched_at=2026-05-03T10:12:27+00:00 vix_rows=274 vix3m_rows=274 end=2026-05-03 output=data\options_universe\vix_history.csv
```

## Final Command Evidence

```text
python -m pytest -q
........................................................................ [ 28%]
........................................................................ [ 56%]
........................................................................ [ 84%]
........................................                                 [100%]
```

```text
ruff check src/quant_system tests
All checks passed!
```

```text
npm --prefix src/frontend run lint
eslint app components lib tests playwright.config.ts eslint.config.mjs next.config.ts
```

```text
npm --prefix src/frontend run build
Compiled successfully
/options-radar included in the built route list
```

```text
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1
14 passed
```

## Safety Check

- No order endpoint was added.
- No Futu trade context was added.
- No account unlock was added.
- No signing, custody-access, or private-key path was added.
- Radar API only reads local snapshot files.
- `/api/orders/submit` still returns `404`.
- `/api/options/daily-scan/dates` includes the `safety` footer.
- Code grep for trade context / signing / custody-sensitive terms under
  `src/quant_system`, `src/frontend`, and `tests` returned no matches.

## Known Limits

- Universe data is committed and should be refreshed manually.
- Earnings dates require manual offline refresh.
- IV Rank starts as empty until daily scans accumulate history.
- VIX history requires a manual Yahoo refresh
  (`quant-system options refresh-vix`) and is cached at
  `data/options_universe/vix_history.csv`. When the cache is missing the
  radar runs without regime adjustment (`market_regime=Unknown`).
- The single-ticker screener also degrades gracefully to
  `market_regime=null` (no penalty) when the VIX cache is missing.
