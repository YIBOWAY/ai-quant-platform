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
python -m pytest -q                      exit 0, 177 tests collected
ruff check .                             All checks passed!
cd src/frontend && npm run lint          exit 0
cd src/frontend && npm run build         exit 0, 13 Next.js routes generated
PW_E2E=1 npx playwright test             11 passed, production-style Next server
real Polymarket read-only smoke          HTTP 403 in this environment
```

API smoke output:

```text
GET /api/health                          200, dry_run=true, paper_trading=true, live_trading_enabled=false, kill_switch=true
GET /api/prediction-market/markets       200, provider=sample, 2 sample markets
POST /api/prediction-market/backtest     200, opportunity_count=3, chart_count=4
POST /api/prediction-market/scan
  with extra.api_key                     400, credential-like fields rejected
GET /api/orders/submit                   404, no order route exists
```

Latest generated sample artifact:

```text
data/api_runs/prediction_market/backtests/pm-backtest-20260501T121257Z-932c38a5/
  chart_index.json
  cumulative_estimated_edge.svg
  edge_histogram.svg
  opportunity_count.svg
  parameter_sensitivity.svg
  report.md
  result.json
```

The HTTP 403 came from a public read-only request and did not involve credentials,
wallets, signing, or order placement. Mocked provider tests cover the expected
response parsing and error mapping paths for offline reproducibility.

## Safety Statement

Phase 11 is strictly read-only research/backtest functionality and does not
include live trading, wallet signing, or real order placement.
