# Phase 11 Execution Guide

## Environment

```powershell
conda activate ai-quant
pip install -e ".[api]"
cd src/frontend
npm install
```

## Safe Defaults

```text
QS_PREDICTION_MARKET_PROVIDER=sample
QS_POLYMARKET_READ_ONLY=true
QS_POLYMARKET_REQUEST_TIMEOUT_SECONDS=10
QS_POLYMARKET_CACHE_TTL_SECONDS=300
QS_POLYMARKET_CACHE_STALE_IF_ERROR_SECONDS=86400
QS_POLYMARKET_USER_AGENT=ai-quant-platform/phase11
```

No Polymarket API key is required or accepted.

## Run Backend and Frontend

```powershell
conda activate ai-quant
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

```powershell
cd src/frontend
npm run dev -- -H 127.0.0.1 -p 3001
```

Open:

```text
http://127.0.0.1:3001/order-book
```

## API Smoke

```powershell
curl "http://127.0.0.1:8765/api/prediction-market/markets?provider=polymarket&cache_mode=refresh&limit=2"
curl -X POST "http://127.0.0.1:8765/api/prediction-market/backtest" ^
  -H "Content-Type: application/json" ^
  -d "{\"provider\":\"polymarket\",\"cache_mode\":\"prefer_cache\",\"min_edge_bps\":50,\"max_markets\":2}"
```

Cache modes:

- `refresh`: force a new public read-only request, then overwrite local cache.
- `prefer_cache`: use fresh cache first, then network if needed.
- `network_only`: bypass cache reads; useful for debugging but less resilient.

## Tests

```powershell
conda activate ai-quant
python -m pytest -q
ruff check .
cd src/frontend
npm run lint
npm run build
$env:PW_E2E="1"; npx playwright test
```

The Playwright smoke uses a production-style frontend server (`next build` then
`next start`) to avoid `next dev` first-run hot-refresh timing noise. For manual
development, keep using `npm run dev -- -H 127.0.0.1 -p 3001`.

## Success Signs

- Backend safety footer says `live_trading_enabled=false`.
- `/api/orders/submit` returns 404.
- Prediction-market backtest response has `run_id`, `metrics`, `chart_index`,
  and `report_path`.
- A first `provider=polymarket&cache_mode=refresh` request returns
  `cache_status=live`.
- A second `provider=polymarket&cache_mode=prefer_cache` request returns
  `cache_status=cache`.
- The frontend says read-only and shows no wallet or order controls.
