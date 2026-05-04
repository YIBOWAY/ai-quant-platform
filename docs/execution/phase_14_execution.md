# Phase 14 Execution Notes

Phase 14 covers the Buy-Side US Options Strategy Assistant. It is wired to the
backend API, CLI, and frontend page. It remains read-only research functionality.

## Environment

```powershell
conda activate ai-quant
```

## Start Backend

```powershell
quant-system serve --host 127.0.0.1 --port 8765
```

Equivalent direct start:

```powershell
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

## Start Frontend

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

Open:

```text
http://127.0.0.1:3001/options-buyside
```

## API

```powershell
curl -X POST http://127.0.0.1:8765/api/options/buy-side/assistant ^
  -H "Content-Type: application/json" ^
  -d "{\"ticker\":\"AAPL\",\"view_type\":\"long_term_aggressive_bullish\",\"target_price\":220,\"target_date\":\"2026-12-31\",\"provider\":\"futu\"}"
```

Contract summary:

- Request schema: `BuySideAssistantRequest`
- Response schema: `BuySideAssistantResponse`
- Expected API errors:
  - `422`: invalid thesis input
  - `404`: ticker or option chain not found
  - `503`: Futu OpenD/provider unavailable
  - `403`: Futu permission issue
  - `400`: unsupported provider or invalid parameter combination

## CLI

```powershell
quant-system options buyside-screen --ticker AAPL --view long_term_aggressive_bullish --target-price 220 --target-date 2026-12-31
```

The CLI prints research output only. It cannot place orders.

## Validation

Backend:

```powershell
python -m pytest -q
ruff check src/quant_system tests
```

Frontend:

```powershell
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```

Browser smoke:

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1 tests/e2e/phase14-buyside-smoke.spec.ts
```

## Safety Checks

The Phase 14 modules must remain read-only:

```powershell
git grep -nE "OpenSecTradeContext|unlock_trade|place_order|modify_order|cancel_order|web3|eth_account|wallet|private_key" -- src/quant_system/options tests src/frontend
```

Expected result: no executable trading code. Documentation may mention these
terms only as disallowed capabilities.

## Risk Disclosure

The `/options-buyside` page must display the required options risk disclosure
and should direct users to OCC's `Characteristics and Risks of Standardized
Options`. This wording is required risk context, not decorative copy.
