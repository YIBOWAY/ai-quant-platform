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
  "strategy": "sell_put",
  "provider": "futu",
  "min_premium": 0.1,
  "max_spread_pct": 0.5,
  "trend_filter": true,
  "hv_iv_filter": false
}
```

Example:

```powershell
curl -X POST "http://127.0.0.1:8765/api/options/screener" `
  -H "Content-Type: application/json" `
  -d "{\"ticker\":\"AAPL\",\"strategy\":\"sell_put\",\"provider\":\"futu\"}"
```

Response includes:

- underlying price
- selected expiration
- candidate count
- candidate table
- assumptions
- safety footer

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
