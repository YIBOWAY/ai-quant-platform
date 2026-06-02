# Phase 14 Delivery Notes

Phase 14 delivers the Buy-Side US Options Strategy Assistant as read-only
quantitative decision support. It covers backend scoring, API / CLI wiring, and
the frontend page at `/options-buyside`.

## Delivered

- Futu option record normalization helper:
  - `src/quant_system/options/option_data.py`
- Buy-side data contracts:
  - `src/quant_system/options/models.py`
- Single-contract metrics engine:
  - `src/quant_system/options/buy_side_metrics.py`
- Strategy candidate engine:
  - `src/quant_system/options/buy_side_strategy.py`
- Scenario Lab engine:
  - `src/quant_system/options/buy_side_scenarios.py`
- Deterministic decision engine:
  - `src/quant_system/options/buy_side_decision.py`
- API route:
  - `POST /api/options/buy-side/assistant`
  - request schema: `BuySideAssistantRequest`
  - response schema: `BuySideAssistantResponse`
  - documented errors: 400 / 403 / 404 / 422 / 503
- CLI command:
  - `quant-system options buyside-screen`
- Frontend page:
  - `/options-buyside`
  - thesis form
  - market snapshot panel
  - recommendation cards
  - comparison table
  - anti-pitfall checklist
  - Scenario Lab summary
  - required risk disclosure text
- Market regime buyer penalty:
  - `src/quant_system/options/market_regime.py`
- Tests:
  - `tests/test_options_option_data.py`
  - `tests/test_options_buy_side_models.py`
  - `tests/test_options_buy_side_metrics.py`
  - `tests/test_options_buy_side_strategy.py`
  - `tests/test_options_buy_side_scenarios.py`
  - `tests/test_options_buy_side_decision.py`
  - `tests/test_api_options_buy_side.py`
  - `tests/test_options_buy_side_cli.py`
  - `src/frontend/tests/e2e/phase14-buyside-smoke.spec.ts`

## Post-Phase 14 Extensions

After the initial buy-side assistant delivery, the local options research
surface was extended with:

- Local AlphaGBM-style tools at `/options-tools`.
- Options Radar current-date scan and public/sample cache-refresh controls on
  `/options-radar`.
- Single-symbol radar drilldown at `/options-radar/[symbol]`.
- Run detail pages for backtests, factors, and paper-trading simulations.
- A populated `/position-map` page using latest saved research outputs.
- Enriched `/experiments` review with sweep, fold, comparison, and send-to-backtest views.
- A local DuckDB-backed Futu option quote cache shared by options pages.
- Data Explorer default-provider handling that labels sample fallback clearly.

The original Phase 14 scope remains research-only and does not add any trading
capability.

## Safety Status

Phase 14 remains research-only:

- No live trading.
- No order placement.
- No Futu account unlock.
- No Futu trading context.
- No wallet or signing path.
- Tests use mocked/local data and do not call live Futu APIs.

The frontend includes this required disclosure:

```text
This tool provides quantitative decision support only and is not financial advice. Options involve risk and may lose value rapidly due to time decay, volatility changes, liquidity, and adverse underlying price movement. Review official options risk disclosures before trading.
```

Users should read OCC's `Characteristics and Risks of Standardized Options`
before trading options.

## Verification Record

Latest validation pass in `ai-quant`:

```powershell
conda activate ai-quant
python -m pytest -q
```

Result: full backend suite passed in the latest validation pass.

```powershell
ruff check src/quant_system tests
```

Result: all checks passed.

```powershell
npm --prefix src/frontend run lint
```

Result: passed.

```powershell
npm --prefix src/frontend run build
```

Result: passed.

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1 tests/e2e/phase14-buyside-smoke.spec.ts
```

Result: browser smoke test passed.

## Known Limitations

- Scenario PnL is approximate and based on Greeks.
- Large spot moves and long holding periods reduce reliability.
- Exact pricing, probability of profit, and event-driven repricing are out of
  scope for Phase 14.
- Futu data requires local OpenD to be running for real data usage.
- The assistant compares structures under user assumptions; it does not know the
  user's account, taxes, execution quality, or actual fill prices.

## Follow-Up QA Fixes

After live UI testing, several usability and data-quality issues were tightened:

- Seller screener recommendation tables now hide `Avoid` contracts by default.
  This keeps deep-in-the-money puts, zero-OI contracts, and failed-filter rows
  out of the displayed candidate list. Rejected rows remain available through
  `include_rejected=true` for audit.
- VIX market-regime classification now uses the recent three-month VIX/VIX3M
  cache window, matching the intended regime banner behavior.
- Futu option range queries use a short-lived in-process cache and a local
  DuckDB-backed option quote cache to reduce repeated requests against the same
  underlying and DTE window.
- Options Radar details now show a fallback explanation when a stored snapshot
  candidate has no notes, and the page warns when a snapshot was generated from
  only a tiny universe.
- Buy-side page Chinese selects now render localized labels, view-type changes
  apply reasonable form presets, max-loss budget was removed from the input
  form, and Scenario Lab uses a horizon date plus clearer subjective-EV copy.
- Futu rate-limit responses from OpenD are now typed as `rate_limited` and the
  provider waits once before retrying the read-only request. This reduces
  repeated failures when switching from AAPL to SPY / QQQ / NVDA in the
  interactive options pages.
- Options Radar now passes the same loaded VIX regime into the per-ticker
  screener, so the radar and single-name screener use one market-regime
  classification source for the same scan date.
- Buy-side recommendation cards now show the concrete selected contracts
  directly on each card, and multiple cards can keep their details expanded at
  the same time.
- A live `quant-system options daily-scan --top 100` attempt was started on
  2026-05-05 but did not finish within a 30-minute guard timeout because of
  Futu pacing. A smaller live refresh completed successfully:

```powershell
conda activate ai-quant
quant-system options daily-scan --top 10
```

Result:

```text
run_date=2026-05-05 universe_size=10 scanned_tickers=10 failed_tickers=0 candidates=50
data=data\options_scans\2026-05-05.jsonl meta=data\options_scans\2026-05-05_meta.json
```

## Definition of Done Status

- Backend tests: full suite passed.
- Backend lint: passed.
- Frontend lint/build: passed.
- Browser smoke: passed.
- Risk disclosure: present.
- Advice-language review: covered by backend and browser tests.
- Trading safety boundary: unchanged.
