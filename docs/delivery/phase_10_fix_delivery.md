# Phase 10 Fix Delivery

## Scope

Phase 10 fixes the Phase 9 frontend/backend integration audit findings while keeping the
platform local-only, paper-only, and safe by default.

## Fix Plan Checklist

- [x] P0-1 Sidebar routes and `/settings` page aligned with existing frontend routes.
- [x] P0-2 Fake telemetry, decorative metrics, fake logs, and misleading widgets removed.
- [x] P0-3 OHLCV provider factory and source labels.
- [ ] P0-4 Interactive client forms for POST workflows.
- [ ] P0-5 LLM settings and masked LLM config endpoint.
- [ ] P0-6 CORS default includes frontend port 3001.
- [ ] P1-1 Dark readable native `<option>` styling.
- [ ] P1-2 Loading, error, and empty state components across pages.
- [ ] P1-3 Documentation/code drift cleanup.
- [ ] P1-4 Playwright smoke.

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

## Manual Smoke Output

Full final smoke output will be captured after P0 and P1 are complete.
