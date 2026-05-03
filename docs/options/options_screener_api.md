# Options Screener API

## Summary

The Options Screener API exposes read-only option research endpoints backed by Futu OpenD.

No endpoint can submit, modify, sign, or place a real order.

## Endpoints

### GET `/api/options/expirations`

Query parameters:

| Name | Required | Example |
|---|---|---|
| `ticker` | yes | `AAPL` |
| `provider` | no | `futu` |

Example:

```powershell
curl "http://127.0.0.1:8765/api/options/expirations?ticker=AAPL&provider=futu"
```

Response shape:

```json
{
  "ticker": "AAPL",
  "provider": "futu",
  "expirations": ["2026-05-04"],
  "safety": {
    "dry_run": true,
    "paper_trading": true,
    "live_trading_enabled": false,
    "kill_switch": true,
    "bind_address": "127.0.0.1"
  }
}
```

### GET `/api/options/chain`

Query parameters:

| Name | Required | Example |
|---|---|---|
| `ticker` | yes | `AAPL` |
| `expiration` | yes | `2026-05-04` |
| `provider` | no | `futu` |

Example:

```powershell
curl "http://127.0.0.1:8765/api/options/chain?ticker=AAPL&expiration=2026-05-04&provider=futu"
```

### POST `/api/options/screener`

Example body:

```json
{
  "ticker": "AAPL",
  "strategy_type": "sell_put",
  "provider": "futu",
  "min_premium": 0.1,
  "min_apr": 10,
  "min_dte": 10,
  "max_dte": 60,
  "max_spread_pct": 0.15,
  "min_open_interest": 50,
  "max_hv_iv": 1.5,
  "trend_filter": true,
  "hv_iv_filter": true
}
```

Example:

```powershell
curl -X POST "http://127.0.0.1:8765/api/options/screener" `
  -H "Content-Type: application/json" `
  -d "{\"ticker\":\"AAPL\",\"strategy_type\":\"sell_put\",\"provider\":\"futu\",\"min_apr\":10,\"min_dte\":10,\"max_dte\":60,\"max_spread_pct\":0.15,\"min_open_interest\":50}"
```

Response includes:

- underlying price
- scanned expiration count and scanned expiration dates
- candidate count
- candidate table
- DTE / spread / open-interest / APR filter effects
- assumptions
- safety footer

If `expiration` is omitted, the backend scans every Futu expiration inside `min_dte` and `max_dte`, then ranks the combined candidate list. Supplying `expiration` is still accepted for API compatibility, but the frontend does not require it.

## Error Mapping

| Error | Typical Cause |
|---|---|
| `400` | invalid ticker, unsupported provider, bad parameter |
| `403` | permission denied |
| `404` | no option chain or no market data |
| `503` | OpenD unavailable or timeout |

Raw tracebacks are not returned.

## Safety

The API only reads market data. It does not expose order, broker, wallet, signing, or live execution endpoints.
