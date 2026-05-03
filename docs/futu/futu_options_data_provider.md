# Futu Options Data Provider

## Scope

The Futu options provider is a read-only data adapter for US option research.

It supports:

- option expiration lookup
- option chain lookup
- option chain range lookup for seller-style DTE-window scanning
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

The seller Options Screener no longer requires a manually selected expiration. It reads Futu
expiration dates, keeps those inside the configured DTE window, requests chains by date range,
and batches quote snapshots so it does not exceed Futu's per-request symbol limit.

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

## Permission Notes (Required entitlements)

This project's owner runs with:

- US stock **LV3** data
- US options **LV1** data

**Important — Futu US options entitlement model:** Futu's US options market-data
tier is **LV1 only**. There is no separate "LV2" upgrade for US options;
LV1 already includes the full set of fields this screener / radar uses
(real-time bid / ask / mid, IV, delta / gamma / theta / vega, open interest,
volume). Earlier internal drafts that mentioned an "LV2 dependency" were
incorrect and have been corrected.

Manual verification with the LV1 entitlement showed that OpenQuoteContext returns:

- US stock historical K-line data (LV3 stock entitlement covers depth; LV1 stock
  alone is also sufficient for OHLCV used by this project)
- `get_option_expiration_date` — option expirations
- `get_option_chain` — full chain with strikes
- `get_market_snapshot` on option codes — bid, ask, IV, delta, gamma, theta,
  vega, open interest, volume, turnover, total_market_val

If a field comes back null, do **not** assume an LV2 upgrade is needed.
Re-check in this order:

1. OpenD process running and logged in?
2. Account real-name verified?
3. Market session open (US options quotes are sparse pre/post-market)?
4. Contract itself liquid (very far OTM weeklies often have empty quotes)?
5. Per-interface rate limit (10 calls / 30s) not exhausted?

## Stock-side note

The screener's underlying snapshot (price, volume, market cap) is read from the
stock symbol, not the option code. LV1 stock entitlement is sufficient there
too; LV2/LV3 only adds order-book depth which the screener does not use.

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
