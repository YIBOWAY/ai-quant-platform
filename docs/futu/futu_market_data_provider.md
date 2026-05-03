# Futu Market Data Provider

## What It Does

Futu is now the main real US equity data provider for the stock research flow.

It supports:

- `AAPL -> US.AAPL`
- `NVDA -> US.NVDA`
- `MSFT -> US.MSFT`
- `SPY -> US.SPY`
- daily and supported intraday K-line requests
- normalized OHLCV rows for the existing factor, backtest, and paper-trading pipelines

It is read-only.

## What It Does Not Do

It does not:

- unlock an account
- create a trading context
- place orders
- modify orders
- cancel orders
- handle private keys
- enable live trading

## Provider Selection

Supported stock providers:

- `futu`
- `sample`
- `tiingo` as rollback compatibility

Frontend research pages now default to `futu`:

- Market Data
- Factor Lab
- Backtester
- Paper Trading

## Config

| Name | Default | Purpose |
|---|---:|---|
| `QS_FUTU_ENABLED` | `true` | Enables read-only Futu provider selection |
| `QS_FUTU_HOST` | `127.0.0.1` | OpenD host |
| `QS_FUTU_PORT` | `11111` | OpenD API port |
| `QS_FUTU_MARKET` | `US` | Current market scope |
| `QS_FUTU_REQUEST_TIMEOUT_SECONDS` | `15` | Request timeout |
| `QS_FUTU_DEFAULT_KLINE_FREQ` | `1d` | Default K-line frequency |
| `QS_FUTU_CACHE_DIR` | `data/futu` | Reserved local cache path |
| `QS_FUTU_USE_CACHE` | `true` | Reserved cache toggle |

## API Examples

```powershell
curl "http://127.0.0.1:8765/api/market-data/history?ticker=SPY&start=2024-01-02&end=2024-01-12&freq=1d&provider=futu"
```

Expected shape:

```json
{
  "symbol": "SPY",
  "source": "futu",
  "frequency": "1d",
  "row_count": 9,
  "rows": [
    {
      "timestamp": "2024-01-02T00:00:00Z",
      "open": 459.515,
      "high": 460.984,
      "low": 457.889,
      "close": 459.991,
      "volume": 123007793
    }
  ]
}
```

## Manual Verification

```powershell
conda activate ai-quant
python scripts/verify_futu_connection.py
```

Expected:

- `PASS read_only_quote_connectivity`
- stock K-line rows for `US.AAPL`, `US.NVDA`, `US.MSFT`, `US.SPY`

## Known Limits

- OpenD must be running and logged in.
- Data entitlement determines what can be queried.
- Intraday history depends on Futu permissions and API limits.
- The fallback sample provider is still available for offline tests.
