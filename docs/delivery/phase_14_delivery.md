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

Result: 320 collected tests passed.

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

Result: 1 browser smoke test passed.

## Known Limitations

- Scenario PnL is approximate and based on Greeks.
- Large spot moves and long holding periods reduce reliability.
- Exact pricing, probability of profit, and event-driven repricing are out of
  scope for Phase 14.
- Futu data requires local OpenD to be running for real data usage.
- The assistant compares structures under user assumptions; it does not know the
  user's account, taxes, execution quality, or actual fill prices.

## Definition of Done Status

- Backend tests: passed.
- Backend lint: passed.
- Frontend lint/build: passed.
- Browser smoke: passed.
- Risk disclosure: present.
- Advice-language review: covered by backend and browser tests.
- Trading safety boundary: unchanged.
