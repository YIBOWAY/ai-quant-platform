# Phase 11 Delivery - Polymarket Read-Only Research

## Summary

Phase 11 adds read-only Polymarket research support:

- public read-only provider
- provider factory
- JSONL snapshot persistence and replay
- simple scanner/quasi-backtest
- SVG charts
- markdown and JSON reports
- backend API integration
- frontend provider selection and result display

It does not add live trading, wallet signing, private key handling, token
transfer, redemption, or real order placement.

## Red Flags

- `src/quantum-core-algorithmic-trading-platform.zip` remains untracked. Do not
  commit it without manual inspection.
- `.env` contains local secrets and remains ignored. Do not copy values into
  docs, tests, or logs.

## API Examples

```powershell
curl "http://127.0.0.1:8765/api/prediction-market/markets?provider=sample"
curl -X POST "http://127.0.0.1:8765/api/prediction-market/backtest" ^
  -H "Content-Type: application/json" ^
  -d "{\"provider\":\"sample\",\"min_edge_bps\":200}"
```

## Output Directory

Backtest artifacts are written under:

```text
data/api_runs/prediction_market/backtests/<run_id>/
```

Each run includes:

- `result.json`
- `chart_index.json`
- `report.md`
- SVG chart files

## Verification Log

Final verification should include:

```text
python -m pytest -q
ruff check .
cd src/frontend && npm run lint
cd src/frontend && npm run build
PW_E2E=1 npx playwright test
```

Latest local verification on 2026-05-01:

```text
python -m pytest -q                      exit 0
ruff check .                             All checks passed!
cd src/frontend && npm run lint          exit 0
cd src/frontend && npm run build         exit 0, 13 Next.js routes generated
PW_E2E=1 npx playwright test             11 passed, production-style Next server
real Polymarket read-only smoke          success, live market list + order book + price history + trades
live/cache smoke                         refresh -> live, prefer_cache -> cache
```

API smoke output:

```text
GET /api/health                          200, dry_run=true, paper_trading=true, live_trading_enabled=false, kill_switch=true
GET /api/prediction-market/markets       200, provider=polymarket, cache_status=live, question="Russia-Ukraine Ceasefire before GTA VI?"
GET /api/prediction-market/markets       200, provider=polymarket, cache_status=cache, same market replayed from local cache
POST /api/prediction-market/scan         200, provider=polymarket, cache_status=cache, candidate_count=1
POST /api/prediction-market/backtest     200, provider=polymarket, cache_status=live, opportunity_count=2, chart_count=4
POST /api/prediction-market/scan
  with extra.api_key                     400, credential-like fields rejected
GET /api/orders/submit                   404, no order route exists
```

Latest generated real-data artifact:

```text
data/api_runs/prediction_market/backtests/pm-backtest-20260501T145426Z-9943f775/
  chart_index.json
  cumulative_estimated_edge.svg
  edge_histogram.svg
  opportunity_count.svg
  parameter_sensitivity.svg
  report.md
  result.json
```

Latest generated cache directories:

```text
data/prediction_market/http_cache/markets/
data/prediction_market/http_cache/order_book/
data/prediction_market/http_cache/prices_history/
data/prediction_market/snapshots/2026-05-01/polymarket/
```

Root cause of the earlier HTTP 403:

- Gamma and CLOB public endpoints rejected the original request style.
- Adding a normal read-only `User-Agent` header resolved the block in this
  environment.
- The provider now uses `/markets/keyset` instead of the deprecated `/markets`
  endpoint and writes successful responses into the local HTTP cache.

Observed follow-up behavior after the live fix:

- Later network-only checks became intermittent and returned timeout / connect
  failures from the public Polymarket hosts.
- Because the earlier live fetch had already populated the HTTP cache, the API
  still returned the last real market payload through `cache_status=stale_cache`
  or `cache_status=cache`.
- This is exactly why Phase 11 now has both live-read logic and cache fallback,
  instead of assuming the upstream endpoints stay reachable all day.

## Safety Statement

Phase 11 is strictly read-only research/backtest functionality and does not
include live trading, wallet signing, or real order placement.
