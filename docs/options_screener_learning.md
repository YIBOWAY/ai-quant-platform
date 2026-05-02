# Options Screener Learning Guide

## What The Screener Is

The Options Screener is a research tool that ranks option candidates using Futu read-only option data.

It currently supports:

- Sell Put
- Covered Call / Sell Call

It is not an advice engine and it does not trade.

## Inputs

| Input | Meaning |
|---|---|
| Ticker | US stock ticker, for example `AAPL` |
| Strategy | `Sell Put` or `Covered Call` |
| Expiration | Pulled from Futu OpenD and selected from a dropdown |
| Min premium | Minimum acceptable mid premium |
| Min APR | Minimum simplified annualized premium estimate |
| Min / Max DTE | Expiration window in days |
| Min IV | Optional IV floor |
| Max delta | Optional absolute delta cap |
| Max spread percentage | Rejects illiquid contracts with wide bid/ask spread |
| Min open interest | Rejects thin contracts with too little open interest |
| Max HV/IV | Rejects cases where realized volatility is too high versus IV |
| Trend filter | Optional simple trend check from recent stock history |
| HV/IV filter | Optional comparison between implied volatility and computed historical volatility |

## Presets

The frontend includes three presets:

- `Conservative`: lower delta, tighter spread, higher open interest, HV/IV filter on.
- `Balanced`: middle settings for normal seller-style screening.
- `Aggressive`: wider limits and fewer filters for broader candidate discovery.

Presets only change form parameters. They do not create trades.

## Sell Put Metrics

For a put candidate the screener calculates:

- underlying price
- strike
- bid / ask / mid
- premium estimate from mid price
- downside distance
- days to expiration
- annualized yield estimate
- spread percentage
- IV and HV context when available
- trend filter result
- conservative rating

## Covered Call Metrics

For a call candidate the screener calculates:

- underlying price
- strike
- bid / ask / mid
- premium estimate from mid price
- upside distance
- days to expiration
- annualized yield estimate
- spread percentage
- IV and HV context when available
- trend filter result
- conservative rating

## Rating Logic

The rating is intentionally conservative:

- `Strong`: data is present, spread is acceptable, filters pass, and premium/yield are meaningful.
- `Watch`: usable data exists but one or more conditions are only moderate.
- `Avoid`: missing data, wide spread, failed filters, or low premium.

The rating is a screening label, not a recommendation.

## Important Assumptions

- Premium uses mid price, not guaranteed fill price.
- HV is computed from historical stock returns when needed.
- Missing IV or Greeks are shown as missing; they are not invented.
- Assignment, early exercise, taxes, margin, and account constraints are not modeled.
- No live order is created.

## Quickstart

1. Start OpenD and confirm it is logged in.
2. Start the backend:

```powershell
conda activate ai-quant
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

3. Start the frontend:

```powershell
cd src/frontend
npm run dev -- --port 3001
```

4. Open:

```text
http://127.0.0.1:3001/options-screener
```

5. Try `AAPL`, `Sell Put`, provider `futu`.
6. Choose an expiration from the dropdown. The option chain preview refreshes automatically.
7. Pick a preset or edit parameters manually, then run the screener.

## Common Mistakes

- Treating the rating as investment advice.
- Assuming mid price can always be filled.
- Ignoring bid/ask spread.
- Comparing IV and HV without checking data freshness.
- Forgetting that OpenD must be running.
