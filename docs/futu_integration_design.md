# Futu Read-Only Integration Design

## 1. Scope

This phase adds Futu OpenAPI / OpenD as the primary **read-only** market data source for:

- US equity historical market data
- US options chain and option quote data when permissions and API fields allow
- frontend market-data exploration
- factor research, backtest, and paper-trading data inputs
- a new read-only Options Screener workflow

This phase does **not** change Polymarket research modules.

## 2. Non-goals

This phase explicitly does **not** do any of the following:

- real trading
- order placement
- account unlock
- trading context creation
- order modification / cancellation
- wallet / signing / private key handling
- live execution
- broker account management
- Polymarket execution changes

Futu is used for **market data only**.

## 3. Existing Data Provider Map

### 3.1 Backend stock data providers today

- `SampleOHLCVProvider`
  - file: `src/quant_system/data/providers/sample.py`
  - purpose: deterministic offline sample data
- `TiingoEODProvider`
  - file: `src/quant_system/data/providers/tiingo.py`
  - purpose: historical EOD stock data
- `build_ohlcv_provider(...)`
  - file: `src/quant_system/data/provider_factory.py`
  - currently supports `sample` and `tiingo`

### 3.2 Existing config fields

- `QS_DEFAULT_DATA_PROVIDER`
- `QS_TIINGO_API_TOKEN`
- legacy keys still present in `ApiKeySettings`:
  - Finnhub
  - Alpha Vantage
  - Tiingo
  - Twelve Data
  - Polygon
  - News API
  - Twitter

### 3.3 Existing backend stock-data call sites

- `src/quant_system/api/routes/data.py`
- `src/quant_system/api/routes/benchmark.py`
- `src/quant_system/factors/pipeline.py`
- `src/quant_system/backtest/pipeline.py`
- `src/quant_system/execution/pipeline.py`

### 3.4 Existing frontend stock-data flow

- page: `src/frontend/app/data-explorer/page.tsx`
- controls: `src/frontend/components/forms/DataExplorerControls.tsx`
- API client: `src/frontend/lib/api.ts`
- provider defaults currently point to `tiingo`
- factor/backtest/paper forms also currently use `sample | tiingo`

### 3.5 Existing options support

- No real options data provider exists today
- No backend options route exists today
- No options screener page exists today

### 3.6 Existing Polymarket boundary

Prediction-market modules already exist under:

- `src/quant_system/prediction_market/**`
- `src/quant_system/api/routes/prediction_market.py`
- `src/frontend/app/order-book/**`

These must remain functionally unchanged.

## 4. Existing Backend API Flow

### 4.1 OHLCV flow today

```text
Frontend / CLI
    -> /api/ohlcv
    -> LocalDataStorage local parquet check
    -> build_ohlcv_provider(settings, requested)
    -> provider.fetch_ohlcv(...)
    -> normalized rows
    -> safety footer in API middleware
```

### 4.2 Factor / backtest / paper flow today

```text
Frontend / CLI
    -> /api/factors/run or /api/backtests/run or /api/paper/run
    -> run_* pipeline
    -> build_ohlcv_provider(...)
    -> provider.fetch_ohlcv(...)
    -> factor/backtest/paper logic
    -> artifacts on disk
    -> API detail pages
```

This is good news: one provider change can propagate through the whole research stack.

## 5. Existing Frontend Flow

### 5.1 Market Data page today

```text
Data Explorer page
    -> read search params
    -> getSymbols()
    -> getOhlcv(symbol, start, end, provider)
    -> render source badge
    -> render simple price chart
```

### 5.2 Research pages affected

- `Factor Lab`
- `Backtester`
- `Paper Trading`

These already accept a provider parameter and can be switched to Futu with limited UI changes.

## 6. Futu Integration Architecture

### 6.1 Provider strategy

Add a new read-only provider:

- `FutuMarketDataProvider`

Responsibilities:

- normalize US tickers: `AAPL -> US.AAPL`
- connect to local OpenD quote service only
- fetch historical K-line data
- fetch options chain / options quotes when available
- normalize to project schema
- map Futu / OpenD failures into clear application errors

### 6.2 Safety boundary

The provider must:

- create quote context only
- never create trading context
- never unlock trade
- never submit orders
- never expose credentials

### 6.3 Provider selection

Supported stock providers after this phase:

- `sample`
- `futu`
- `tiingo` kept temporarily for compatibility / rollback

Recommended default after validation:

- `QS_DEFAULT_DATA_PROVIDER="futu"` when OpenD is available locally

Safe fallback behavior:

- if explicit `provider=futu` but OpenD is unavailable -> return typed error to API caller
- if default provider is `futu` and OpenD is unavailable -> optionally fallback to sample only where current API conventions require a non-crashing response, but the response must clearly say it is fallback

### 6.4 Options provider shape

Options data should stay read-only and likely live in one of two shapes:

- extend `futu.py` with quote + option-chain helpers
- or add `futu_options.py` if that keeps code clearer without touching unrelated modules

Final choice should minimize abstraction churn.

## 7. Config Design

Add safe settings for Futu / OpenD:

- `QS_FUTU_ENABLED=true`
- `QS_FUTU_HOST=127.0.0.1`
- `QS_FUTU_PORT=11111`
- `QS_FUTU_MARKET=US`
- `QS_FUTU_REQUEST_TIMEOUT_SECONDS=15`
- `QS_FUTU_DEFAULT_KLINE_FREQ=1d`
- `QS_FUTU_CACHE_DIR=data/futu`
- `QS_FUTU_USE_CACHE=true`

Optional:

- `QS_FUTU_OPTIONS_ENABLED=true`

No secret is required for local OpenD connectivity in this project design.

Legacy vendor keys remain loaded but should be documented as deprecated for US stock / option market data.

## 8. Backend API Design

### 8.1 Existing endpoints to extend

- `GET /api/ohlcv`
- `GET /api/benchmark`
- `POST /api/factors/run`
- `POST /api/backtests/run`
- `POST /api/paper/run`

Provider enum changes:

- from `sample | tiingo`
- to `sample | futu | tiingo`

### 8.2 New stock-market endpoint

Add a clearer frontend-facing endpoint:

`GET /api/market-data/history?ticker=AAPL&start=2024-01-01&end=2024-12-31&freq=1d&provider=futu`

Purpose:

- keep existing `/api/ohlcv` working
- give the frontend a ticker/frequency-oriented endpoint that is easy to reason about

### 8.3 Options endpoints

Add read-only options routes:

- `GET /api/options/chain`
- `GET /api/options/expirations`
- `POST /api/options/screener`

All responses must still include safety footer.

## 9. Frontend UI Design

### 9.1 Market Data page

User inputs:

- ticker
- provider (`sample | futu`)
- start date
- end date
- frequency

Display:

- source badge
- fetched-at time
- latest close
- number of bars
- K-line / candlestick chart
- readable error block when OpenD is offline or permission is missing

### 9.2 Options Screener page

New page under frontend app structure with:

- ticker input
- strategy type
  - Sell Put
  - Covered Call / Sell Call
- expiration selector
- min IV
- target delta / max delta
- min premium
- max spread %
- trend filter
- HV/IV timing filter
- run button
- results table
- explanation / disclaimer block

### 9.3 Chinese frontend version

No i18n framework exists today. The lowest-risk approach is:

- add a small locale dictionary layer
- keep the same logic
- expose English and Chinese labels from a shared map

If that becomes too invasive, a route-based `/zh` wrapper is acceptable, but only if logic reuse stays high.

## 10. Options Screener Design

### 10.1 Strategy outputs

For each candidate:

- underlying price
- option symbol
- strategy type
- strike
- expiry
- bid / ask / mid
- premium estimate
- spread %
- moneyness / distance
- annualized yield estimate
- IV if available from Futu
- HV computed locally from stock history
- trend filter result
- conservative rating

### 10.2 Rating

Human-readable only:

- `Strong`
- `Watch`
- `Avoid`

The scoring must be conservative and documented. Missing data must reduce confidence instead of inventing values.

### 10.3 Disclaimer

The screener must display:

- read-only data mode
- research only
- no live trading
- not investment advice

## 11. Files Likely To Be Modified

This plan likely touches **more than 30 files**. Reason:

1. provider implementation
2. config and env templates
3. API routes and schemas
4. factor/backtest/paper provider enums
5. CLI data-ingestion path
6. frontend market-data page
7. new options page and API client types
8. Chinese labels
9. tests
10. docs

Likely code changes:

- `src/quant_system/config/settings.py`
- `.env.example`
- `src/quant_system/data/provider_factory.py`
- `src/quant_system/data/providers/__init__.py`
- new Futu provider module(s)
- `src/quant_system/data/pipeline.py`
- `src/quant_system/cli.py`
- `src/quant_system/api/routes/data.py`
- `src/quant_system/api/routes/benchmark.py`
- new `src/quant_system/api/routes/options.py`
- `src/quant_system/api/server.py`
- relevant API schemas
- factor/backtest/paper schemas
- factor/backtest/paper frontend forms
- `src/frontend/lib/api.ts`
- `src/frontend/app/data-explorer/page.tsx`
- chart component(s)
- new options screener frontend page/components
- sidebar/nav files
- tests
- docs

## 12. Files That Must Not Be Touched

Unless a tiny shared-interface fix becomes unavoidable:

- `src/quant_system/prediction_market/**`
- Polymarket API behavior
- Polymarket frontend workflows
- any live trading path
- any wallet/signing/private-key logic

## 13. Testing Strategy

### 13.1 Unit tests

- ticker normalization
- OHLCV normalization
- provider factory selection
- Futu SDK success path with mocks
- OpenD unavailable
- permission denied
- invalid symbol
- empty data
- options chain normalization
- missing IV / Greeks fields
- screener scoring behavior

### 13.2 API tests

- `/api/ohlcv` or `/api/market-data/history`
- benchmark
- factor run with `provider=futu`
- backtest run with `provider=futu`
- paper run with `provider=futu`
- options chain / screener endpoints

### 13.3 Frontend tests

- market data page form
- provider switch
- loading / error states
- chart render on mocked data
- options screener page happy path
- Chinese labels render

### 13.4 Manual verification

Because real OpenD connectivity is local-state dependent, add:

- `scripts/verify_futu_connection.py`
- step-by-step manual verification doc

## 14. Manual Verification Strategy

Manual checks must confirm:

1. `ai-quant` environment is active
2. Futu SDK imports in that environment
3. local OpenD is reachable
4. quote context can query basic US market data
5. at least one US stock K-line request succeeds
6. option chain / quotes work if permission allows
7. frontend market-data page loads real Futu data
8. options screener returns readable results
9. Polymarket page still works

## 15. Error Mapping

Map Futu/OpenD failures into frontend-readable errors:

- OpenD not running
- cannot connect to host/port
- market permission denied
- invalid symbol
- unsupported frequency
- empty dataset
- timeout

The API should not leak raw tracebacks.

## 16. Rollback Plan

If Futu validation fails:

1. keep `sample` and `tiingo` paths intact
2. switch default provider back to current safe default
3. keep Futu routes hidden behind explicit provider selection
4. document the blocker without breaking existing research flows

Rollback granularity:

- provider factory only
- frontend provider dropdown only
- options screener can stay hidden until API is verified

## 17. Official Skills / SDK Installation Note

The official Futu skills were installed into the global Codex skills directory:

- `futuapi`
- `install-futu-opend`

The local OpenD GUI was already installed and running, so this project did not reinstall OpenD.

Verification path:

1. verify the existing local OpenD GUI first
2. verify whether the Futu Python SDK is already installed inside `ai-quant`
3. install `futu-api` only into `ai-quant` if missing
4. document the manual equivalent steps in `docs/futu_environment_setup.md`

## 18. ASCII Flow Diagram

```text
                +---------------------------+
                |   Futu OpenD (local GUI)  |
                |   quote only / read-only  |
                +-------------+-------------+
                              |
                              v
                +---------------------------+
                | FutuMarketDataProvider    |
                | - ticker normalize        |
                | - kline fetch             |
                | - option chain fetch      |
                | - quote normalize         |
                +-------------+-------------+
                              |
          +-------------------+-------------------+
          |                   |                   |
          v                   v                   v
 +----------------+  +----------------+  +----------------+
 | /api/ohlcv     |  | /api/benchmark |  | /api/options/* |
 +--------+-------+  +--------+-------+  +--------+-------+
          |                   |                   |
          v                   v                   v
 +--------------------------------------------------------+
 | factor / backtest / paper pipelines use provider       |
 +---------------------------+----------------------------+
                             |
                             v
         +---------------------------------------------+
         | Frontend: Market Data / Factor / Backtest / |
         | Paper / Options Screener / Chinese labels   |
         +---------------------------------------------+
```

## 19. Phase Ordering

1. Design freeze
2. Verify `ai-quant` + SDK + OpenD
3. Implement stock provider
4. Route existing stock flows through Futu
5. Add options provider
6. Add options screener
7. Frontend integration
8. Chinese frontend labels
9. Regression + docs

## 20. Safety Statement

This integration uses Futu only for **read-only market data**. It does **not** add real order placement, account unlock, wallet/private-key handling, or live trading.
