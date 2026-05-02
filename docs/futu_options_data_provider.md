# Futu Options Data Provider

## Scope

The Futu options provider is a read-only data adapter for US option research.

It supports:

- option expiration lookup
- option chain lookup
- option quote snapshot lookup
- underlying stock snapshot lookup
- normalized fields for the Options Screener

It does not support:

- account unlock
- order placement
- order modification
- exercise or assignment operations
- wallet or private-key handling
- live trading

## OpenD Requirement

OpenD must be running and logged in before the provider can query options.

Default connection:

| Setting | Default |
|---|---:|
| `QS_FUTU_HOST` | `127.0.0.1` |
| `QS_FUTU_PORT` | `11111` |
| `QS_FUTU_OPTIONS_ENABLED` | `true` |

## Data Flow

```text
Frontend Options Screener
  -> /api/options/*
  -> FutuMarketDataProvider
  -> local OpenD quote context
  -> Futu public market data
  -> normalized response
```

Only quote APIs are used. No trade context is created.

## Normalized Option Fields

| Field | Meaning |
|---|---|
| `code` | Futu option code |
| `underlying` | Normalized underlying, for example `US.AAPL` |
| `option_type` | `call` or `put` when available |
| `strike` | Strike price |
| `expiry` | Expiration date |
| `bid` | Best bid, nullable |
| `ask` | Best ask, nullable |
| `last` | Last traded price, nullable |
| `volume` | Current volume, nullable |
| `open_interest` | Open interest, nullable |
| `implied_volatility` | Futu-provided IV, nullable |
| `delta` | Futu-provided delta, nullable |
| `gamma` | Futu-provided gamma, nullable |
| `theta` | Futu-provided theta, nullable |
| `vega` | Futu-provided vega, nullable |
| `source` | Always `futu` for this provider |
| `fetched_at` | Local fetch timestamp in UTC |

Missing fields are returned as `null`. The system does not invent IV or Greeks.

## Permission Notes

The user reported:

- US stock LV3 data
- US options LV1 data

Manual verification showed that OpenD can return:

- US stock historical K-line data
- option expiration dates
- option chains
- option quote snapshots with bid, ask, IV, Greeks, open interest, and volume fields

Actual field availability may still vary by account, symbol, market session, and Futu permission state.

## Manual Verification

```powershell
conda activate ai-quant
python scripts/verify_futu_connection.py
```

Expected output includes:

- `PASS read_only_quote_connectivity`
- option expiration count
- option chain row count
- option snapshot field sample

## API Examples

```powershell
curl "http://127.0.0.1:8765/api/options/expirations?ticker=AAPL&provider=futu"
```

```powershell
curl "http://127.0.0.1:8765/api/options/chain?ticker=AAPL&expiration=2026-05-04&provider=futu"
```

## Safe Failure Modes

| Situation | Response |
|---|---|
| OpenD not running | frontend-readable connection error |
| No permission | permission error, no traceback |
| Invalid ticker | validation error |
| Missing chain fields | nullable fields |
| Empty option chain | empty list with clear source metadata |

## Safety Boundary

This provider is strictly read-only. It does not create a trading context and does not expose any API path that can submit an order.
