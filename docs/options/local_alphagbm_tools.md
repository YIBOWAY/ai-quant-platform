# Local AlphaGBM-Style Options Tools

## Summary

This project now includes a local, read-only options toolkit inspired by the
installed AlphaGBM skills.

The local toolkit does not call AlphaGBM APIs and does not require
`ALPHAGBM_API_KEY`. Futu OpenD is the market data source for live stock and
option-chain data. Strategy math is computed locally.

No endpoint can submit, modify, sign, or place a real order.

## Phase 1 Scope

Phase 1 adds the shared building blocks needed by multiple AlphaGBM-style
skills:

- current option snapshot with ATM IV, historical volatility, IV rank proxy,
  and volatility risk premium proxy
- volatility surface across listed strikes and expirations
- volatility smile and 25-delta skew for one expiration
- Black-Scholes pricing, implied volatility, and Greeks
- single-leg and multi-leg payoff simulation
- local templates for common option strategies

These tools are reusable by later stock analysis, earnings, hedge, unusual
activity, watchlist, and alert features.

## API Endpoints

### GET `/api/options/snapshot/{ticker}`

Returns a live Futu-backed option snapshot for a ticker.

Example:

```powershell
curl "http://127.0.0.1:8765/api/options/snapshot/AAPL?provider=futu"
```

Response includes:

- current stock price
- nearest expiration
- ATM implied volatility
- 30-day historical volatility
- local IV rank / percentile proxy
- volatility risk premium proxy
- read-only assumptions

### GET `/api/options/tools/vol-surface/{ticker}`

Returns a live Futu-backed volatility surface.

Example:

```powershell
curl "http://127.0.0.1:8765/api/options/tools/vol-surface/AAPL?provider=futu&max_expirations=2"
```

Response includes:

- moneyness buckets
- expiration axis
- IV grid
- raw surface points
- ATM term structure
- surface shape label

### GET `/api/options/tools/vol-smile/{ticker}`

Returns a live Futu-backed volatility smile for one expiration. If `expiry` is
omitted, the nearest listed expiration is used.

Example:

```powershell
curl "http://127.0.0.1:8765/api/options/tools/vol-smile/AAPL?provider=futu"
```

Response includes:

- strikes
- IVs
- deltas
- moneyness
- 25-delta skew approximation
- smile shape label

### POST `/api/options/tools/greeks`

Computes local Greeks for one option.

Example body:

```json
{
  "spot": 100,
  "strike": 100,
  "expiry_days": 30,
  "iv": 0.25,
  "option_type": "call",
  "rate": 0.04
}
```

### POST `/api/options/tools/implied-volatility`

Solves local implied volatility from an option market price.

Example body:

```json
{
  "market_price": 4.2,
  "spot": 100,
  "strike": 100,
  "expiry_days": 30,
  "option_type": "call",
  "rate": 0.04
}
```

### POST `/api/options/tools/simulate`

Simulates payoff for a single-leg or multi-leg option position.

Example body:

```json
{
  "symbol": "AAPL",
  "spot": 100,
  "legs": [
    {
      "action": "buy",
      "option_type": "call",
      "strike": 100,
      "expiry_days": 30,
      "entry_price": 5,
      "quantity": 1
    }
  ]
}
```

### GET `/api/options/tools/strategy/templates`

Lists local strategy templates.

Current templates:

- long call / long put
- bull call spread / bull put spread
- bear put spread / bear call spread
- covered call / cash-secured put
- collar
- long or short straddle
- long or short strangle
- iron condor
- iron butterfly
- synthetic long / synthetic short

### POST `/api/options/tools/strategy/build`

Builds a local strategy from one of the templates.

Example body:

```json
{
  "mode": "template",
  "template_id": "bull_call_spread",
  "symbol": "AAPL",
  "spot": 100,
  "expiry_days": 30,
  "strikes": [95, 100, 105, 110],
  "iv": 0.25
}
```

### POST `/api/options/tools/score-contracts`

Ranks supplied option contracts with a local multi-factor score.

Example body:

```json
{
  "spot": 100,
  "objective": "sell_premium",
  "contracts": [
    {
      "symbol": "US.AAPL260619P00090000",
      "option_type": "PUT",
      "strike": 90,
      "bid": 1.1,
      "ask": 1.2,
      "volume": 600,
      "open_interest": 1200,
      "implied_volatility": 0.5,
      "delta": -0.24
    }
  ]
}
```

Response includes ranked contracts, total score, rating, subscores, warnings,
and read-only assumptions.

### POST `/api/options/tools/strategy/rank`

Ranks local strategy templates for a market view.

Example body:

```json
{
  "market_view": "bullish",
  "spot": 100,
  "expiry_days": 45,
  "strikes": [85, 90, 95, 100, 105, 110, 115],
  "iv": 0.25
}
```

### POST `/api/options/tools/bull-put-signal`

Applies the local FearScore threshold rule and selects a research-only Bull Put
Spread candidate from supplied put contracts when possible.

### POST `/api/options/tools/fear-score`

Computes a local ticker panic score from supplied VIX, IV rank, RSI,
options-volume anomaly, Put/Call ratio, and consecutive-down-day inputs.

### POST `/api/options/tools/iv-rank`

Computes IV rank / percentile from supplied local IV history values.

### POST `/api/options/tools/market-sentiment`

Builds a local market sentiment regime from supplied VIX, Put/Call ratio,
breadth, and trend inputs.

### POST `/api/options/tools/earnings-crush`

Estimates historical earnings IV crush from supplied pre/post IV observations.

### POST `/api/options/tools/hedge-advisor`

Builds research-only Long Put / Collar hedge candidates from supplied holdings
and option contracts.

### POST `/api/options/tools/unusual-activity`

Flags unusual options activity from supplied volume and open-interest fields.

### GET `/api/options/tools/watchlist`

Reads the local options watchlist.

### POST `/api/options/tools/watchlist`

Adds a ticker to the local options watchlist. The watchlist is a local JSON file
under the configured output directory.

### POST `/api/options/tools/alerts/evaluate`

Evaluates supplied local alert definitions against a supplied ticker context.
This endpoint does not send notifications.

### POST `/api/options/tools/health-check`

Checks supplied local research profile metadata for stale updates and missing
theses.

### POST `/api/options/refresh/universe`

Refreshes the local Options Radar universe CSV. Supported sources:

- `public` / `github`: public S&P 500 + Nasdaq 100 CSV snapshots
- `sample`: deterministic offline sample universe for local testing

### POST `/api/options/refresh/earnings`

Refreshes the local earnings calendar CSV used by Options Radar. Supported
sources:

- `public` / `yfinance`: read-only yfinance calendar lookup
- `sample`: deterministic offline sample calendar for local testing

### POST `/api/options/refresh/vix`

Refreshes the local VIX/VIX3M history CSV used by market-regime scoring.
Supported sources:

- `public`: Yahoo Chart first, Cboe public CSV fallback
- `sample`: deterministic offline sample VIX history for local testing

These refresh endpoints only write local CSV caches. They do not submit,
modify, sign, or place orders.

## Replication Plan

The installed AlphaGBM skills describe product workflows and remote API calls;
they do not include the full remote scoring backend. The local replication plan
therefore recreates equivalent project features on top of Futu data and local
models.

### Phase 1: Local Options Core

Status: implemented.

- snapshot
- volatility surface
- volatility smile
- Greeks
- implied volatility
- payoff simulation
- strategy templates

### Phase 2: Local Ranking And Strategy Selection

Status: implemented.

- option contract scoring
- multi-factor strategy ranking
- Bull Put Spread signal workflow
- buy-side and sell-side unified ranking
- local IV rank dashboard helper using supplied or persisted IV histories

### Phase 3: Research Dashboards

Status: implemented as local backend research helpers.

- market sentiment dashboard using VIX and breadth data
- per-ticker fear score
- IV rank dashboard
- earnings IV crush workflow
- hedge advisor workflow
- unusual options activity scan from supplied volume/open-interest changes

### Phase 4: Monitoring

Status: implemented as lightweight local file/stateless helpers.

- local watchlists
- price / IV / activity alerts
- health checks for stale research profiles

### Phase 5: Durable Local Cache

Status: first implementation complete.

- Futu option quote windows are cached in a local DuckDB file.
- Fresh cache entries are reused across backend restarts.
- Options Screener, Options Radar, Buy-Side Options Assistant, and local options
  tools use the cache through the shared Futu provider.
- Cache entries stay research-only and do not contain secrets, account state, or
  order instructions.

Still not implemented:

- scheduled refreshes
- notification delivery

## Verification

Phase 1 was verified with:

- focused unit tests
- focused API tests
- related existing option API tests
- live Futu OpenD calls for AAPL snapshot, volatility smile, and volatility
  surface

All live checks are read-only.

Phases 2-4 were verified with focused unit and API tests. These helpers are
local-only and do not call AlphaGBM APIs.
