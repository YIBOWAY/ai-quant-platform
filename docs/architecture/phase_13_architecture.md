# Phase 13 Architecture - Options Radar

## Modules

```text
src/quant_system/options/
  universe.py          committed S&P 500 + Nasdaq 100 universe loader
  rate_limiter.py      token-bucket pacing for read-only Futu calls
  iv_history.py        local IV history and IV Rank
  earnings_calendar.py offline earnings-date lookup
  market_regime.py     VIX regime classifier (V5 dual factor)
  vix_data.py          Yahoo Chart REST fetcher + CSV cache for ^VIX/^VIX3M
  radar.py             cross-ticker scanner and score calculation
  radar_storage.py     daily JSONL snapshot store
  sample_provider.py   deterministic offline provider

src/quant_system/api/routes/options_radar.py
  GET /api/options/daily-scan/dates
  GET /api/options/daily-scan

src/frontend/app/options-radar/page.tsx
src/frontend/components/forms/OptionsRadarView.tsx
  daily scan viewer with filters, detail expansion, CSV export
```

## ASCII Architecture

```text
           +----------------------+
           | sp500_nasdaq100.csv  |
           +----------+-----------+
                      |
                      v
           +----------------------+
           | OptionsUniverse      |
           +----------+-----------+
                      |
                      v
+---------------------+----------------------+
| RateLimitedFutuProvider / SampleProvider   |
+---------------------+----------------------+
                      |
                      v
           +----------------------+
           | Existing Screener    |
           +----------+-----------+
                      |
      +---------------+----------------+
      | IV Rank | Earnings | VIX regime |
      +---------------+----------------+
            ^                   ^
            |                   |
  iv_history/*.csv    vix_history.csv (Yahoo Chart REST)
                      |
                      v
           +----------------------+
           | RadarSnapshotStore   |
           +----------+-----------+
                      |
        +-------------+-------------+
        v                           v
  Local API                    Frontend table
```

## Failure Isolation

Each ticker is scanned independently. A single OpenD, permission, or no-data
failure is recorded in `failed_tickers` and does not stop the whole run.

## Rate Limit

Futu quote interfaces are paced at 10 calls per 30 seconds by default. The batch
size for market snapshots defaults to 200, below Futu's documented 400-code
limit.

## VIX Data Source

VIX/VIX3M closes are fetched from `query1.finance.yahoo.com/v8/finance/chart`
over plain HTTPS GET. The fetcher is read-only and uses no API key. Errors
are logged and downgraded to an empty Series so transient outages cannot
abort a scan; the CLI degrades to `market_regime=Unknown` and applies no
seller penalty.

The regime is computed once per scan and serialised into each candidate as
`market_regime` (`Normal` / `Elevated` / `Panic` / `Unknown`) and
`market_regime_penalty` (per-strategy points subtracted from `global_score`).
The frontend `RegimeBanner` reads these fields from the API payload.

## Read-only Boundary

Only quote-data methods are wrapped. Yahoo VIX fetches are anonymous public
GETs. There is no trade context and no route or button that can place an
order.

