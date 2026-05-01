# Phase 10 Fix Delivery

## Scope

Phase 10 fixes the Phase 9 frontend/backend integration audit findings while keeping the
platform local-only, paper-only, and safe by default.

## Fix Plan Checklist

- [x] P0-1 Sidebar routes and `/settings` page aligned with existing frontend routes.
- [x] P0-2 Fake telemetry, decorative metrics, fake logs, and misleading widgets removed.
- [x] P0-3 OHLCV provider factory and source labels.
- [x] P0-4 Interactive client forms for POST workflows.
- [x] P0-5 LLM settings and masked LLM config endpoint.
- [x] P0-6 CORS default includes frontend port 3001.
- [x] P1-1 Dark readable native `<option>` styling.
- [x] P1-2 Loading, error, and empty state components across pages.
- [x] P1-3 Documentation/code drift cleanup.
- [x] P1-4 Playwright smoke.
- [x] P1-5 Run buttons do not fall back to native page submits before hydration.

## Verification Log

### P0-1

```text
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
Route smoke on 127.0.0.1:3001             /, /data-explorer, /factor-lab,
                                          /backtest, /experiments, /paper-trading,
                                          /agent-studio, /order-book, /position-map,
                                          /settings all returned 200
```

### P0-2

```text
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
rg "45%|65%|99\.98%|MLK Day|Live Sync"   no matches
Route smoke on 127.0.0.1:3001             /, /data-explorer, /factor-lab,
                                          /backtest, /experiments, /paper-trading,
                                          /agent-studio, /order-book, /position-map,
                                          /settings all returned 200
```

### P0-3

```text
python -m pytest tests/test_provider_factory.py tests/test_api_data_provider_param.py -q
6 passed
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
```

### P0-4

Added frontend-only dependencies:

- `@tanstack/react-query`: mutation state for synchronous local API calls.
- `react-hook-form` + `zod`: accessible forms with local validation.
- `sonner`: success/error toasts after local run requests.

```text
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
manual API smoke                          backtest, factor, paper, agent task,
                                          agent review, prediction-market scan,
                                          dry-arbitrage all returned success
manual frontend smoke                     /backtest, /factor-lab, /paper-trading,
                                          /agent-studio, /data-explorer,
                                          /order-book all returned 200
```

### P0-5

```text
python -m pytest tests/test_settings_llm_alias.py tests/test_api_agent_llm_config.py tests/test_llm_factory.py -q
5 passed
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
```

### P0-6

```text
python -m pytest tests/test_api_cors.py -q
1 passed
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
```

### P1

Added frontend dev dependency:

- `@playwright/test`: gated local smoke tests. It does not run unless `PW_E2E=1`.

The run buttons in backtest, factor, paper, agent, and prediction-market forms
stay disabled until the client page is ready, then use explicit client-side
click handlers instead of native form submits. This prevents a browser-level
page navigation or no-op click if the user clicks before the client bundle has
fully hydrated.

```text
rg "<option(?![^>]*style)" -P src/frontend   no matches
rg legacy-paper-label .                     no matches
cd src/frontend && npx playwright test       all tests skipped unless PW_E2E=1
PW_E2E=1 npx playwright test                 11 passed
```

## Manual Smoke Output

Backend was started on `127.0.0.1:8765` with a temporary data directory and
`QS_LLM_PROVIDER=stub` for the agent workflow smoke. Frontend was started on
`127.0.0.1:3001`.

```text
health status=ok dry_run=True paper=True live=False kill_switch=True bind=127.0.0.1
ohlcv symbol=SPY source=tiingo rows=9
llm provider=stub model= has_api_key=False key_value_returned=False
settings masked_contains_star=True contains_api_key_field=True
backtest run_id=backtest-20260429T181631Z-b0ae0dcf total_return=0.281682946899275
factor run_id=factor-20260429T181632Z-48a6a121 rows=284
paper run_id=paper-20260429T181634Z-429ec952 orders= breaches=
agent candidate_id=factor-low_vol_momentum-9de4cebf99 auto_promotion=False
agent review decision=approve registration=manual_required
pm scan candidates=3
pm dry proposed_trades=3
orders route status=404
pm live-key status=400
page / status=200
page /data-explorer status=200
page /factor-lab status=200
page /backtest status=200
page /experiments status=200
page /paper-trading status=200
page /agent-studio status=200
page /order-book status=200
page /position-map status=200
page /settings status=200
```

Browser smoke:

```text
Running 11 tests using 1 worker

  ✓ route / loads
  ✓ route /data-explorer loads
  ✓ route /factor-lab loads
  ✓ route /backtest loads
  ✓ route /experiments loads
  ✓ route /paper-trading loads
  ✓ route /agent-studio loads
  ✓ route /order-book loads
  ✓ route /position-map loads
  ✓ route /settings loads
  ✓ primary local workflow buttons are clickable

  11 passed
```

## Review Update - 2026-05-01

During a fresh frontend/backend review, the browser smoke found that some run
buttons could be visible before the client page was ready. The affected buttons
now stay disabled until hydration is complete, then call the API through the
client mutation path. This avoids both native form navigation and no-op clicks
under fast automated or impatient manual use.

```text
python -m pytest -q                         PASS, 156 collected
ruff check .                                 PASS
cd src/frontend && npm run lint              PASS
cd src/frontend && npm run build             PASS
PW_E2E=1 npx playwright test                 11 passed
API smoke                                    health/settings/llm/ohlcv/backtest/
                                             factor/paper/prediction-market OK
Safety smoke                                 /api/orders/submit -> 404,
                                             Polymarket API key request -> 400
```
