# Futu Frontend / Backend Integration Report

## Scope

This report records the Futu integration smoke test for:

- backend Futu market-data endpoints
- frontend Market Data page
- frontend Options Screener page
- Chinese query-parameter version
- research pipeline defaults for Factor Lab, Backtester, and Paper Trading

## Safety Statement

The integration is read-only. It does not unlock accounts, submit orders, modify orders, sign transactions, or enable live trading.

## Environment

| Item | Value |
|---|---|
| Conda env | `ai-quant` |
| Backend | `http://127.0.0.1:8765` |
| Frontend | `http://127.0.0.1:3001` |
| OpenD host | `127.0.0.1` |
| OpenD port | `11111` |

## Verification Commands

```powershell
conda activate ai-quant
python scripts/verify_futu_connection.py
```

Expected key line:

```text
PASS read_only_quote_connectivity
```

```powershell
python -m pytest tests/test_data_futu_provider.py tests/test_api_options_futu.py tests/test_options_screener.py -q
```

Expected:

```text
passed
```

```powershell
cd src/frontend
npm run lint
npm run build
```

Expected:

```text
lint passed
build passed
```

## API Smoke Examples

Stock history:

```powershell
curl "http://127.0.0.1:8765/api/market-data/history?ticker=SPY&start=2024-01-02&end=2024-01-12&freq=1d&provider=futu"
```

Options screener:

```powershell
curl -X POST "http://127.0.0.1:8765/api/options/screener" `
  -H "Content-Type: application/json" `
  -d "{\"ticker\":\"AAPL\",\"strategy\":\"sell_put\",\"provider\":\"futu\"}"
```

## Frontend Smoke Checklist

- `/data-explorer` loads with provider `futu`.
- Ticker, date range, and frequency can be changed.
- Market Data accepts manually typed tickers and renders a true OHLC candlestick chart.
- Long date ranges use sparse time-axis labels instead of one label per bar.
- Data source badge shows `futu` when OpenD returns data.
- `/data-explorer?lang=zh` renders Chinese labels.
- `/options-screener` can run a Futu-backed screen.
- `/options-screener` loads Futu expiration dates into a dropdown and refreshes the option-chain preview as expiration changes.
- `/options-screener` includes conservative / balanced / aggressive presets for seller-style screening.
- `/options-screener?lang=zh` renders Chinese labels.
- Factor Lab, Backtester, and Paper Trading forms default to provider `futu`.
- No page exposes order placement or account unlock controls.

## Latest Local Result

Last refreshed: 2026-05-02.

OpenD / SDK verification:

```text
PASS read_only_quote_connectivity
US.AAPL: rows=9
US.NVDA: rows=9
US.MSFT: rows=9
US.SPY: rows=9
option expiries=26
option chain rows=88
```

Backend / frontend smoke:

```text
health_live=False kill_switch=True
history_source=futu rows=9 first_close=459.991975474
options_candidates=44 expiration=2026-05-04 first_rating=Strong first_symbol=US.AAPL260504P297500
frontend_data_explorer_status=200
frontend_options_zh_status=200
```

Automated browser smoke:

```text
11 passed (1.2m)
options_screener_ui_ok
data_explorer_zh_ui_ok
options_zh_ok expirations=36 selected=2026-05-12 label=2026-05-12 · 10 DTE
data_explorer_ok tick_labels=10
```

Quality gates:

```text
python -m pytest -q      -> passed
ruff check .             -> All checks passed
npm run lint             -> passed
npm run build            -> passed
```

## Known Limits

- OpenD must stay running.
- Futu permission controls field availability.
- Options Screener ratings are screening labels, not investment advice.
- Paper Trading remains simulated and controlled by existing safety flags.
