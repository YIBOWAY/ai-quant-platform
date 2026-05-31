# Frontend Real-Data Review — 2026-05-31

This review checks whether the frontend is showing backend-derived data or
unlabeled sample/demo output. It was run against the local backend on
`127.0.0.1:8765` and the frontend on `127.0.0.1:3001`.

## Completion Standard

- Backend and frontend are reachable.
- Main pages render without frontend runtime errors.
- Market-data pages identify their source.
- Sample or example inputs are not silently presented as live data.
- Beginner-facing pages explain read-only / research-only boundaries.

## Current Data Truth Map

| Page | Current source behavior | Review result |
|---|---|---|
| `/` Dashboard | Calls `/api/health`, `/api/symbols`, `/api/factors`, `/api/backtests`, `/api/paper`, and `/api/agent/candidates`. Latest saved run sources are now shown on the cards. | Backend-derived. Saved sample runs are labeled as sample / not real. |
| `/data-explorer` | Defaults to Futu unless `provider=sample` is explicitly selected. The chart and table use `/api/market-data/history`. | Backend-derived. Futu run was verified with real OHLCV rows. |
| `/factor-lab` | Runs `/api/factors` and `/api/factors/run`; default provider is Futu. | Backend-derived. |
| `/backtest` | Runs `/api/backtests`, `/api/backtests/{id}`, `/api/benchmark`, and `/api/backtests/run`; default provider is Futu. | Backend-derived. Latest saved sample runs and benchmark sources are labeled. |
| `/replications` | Calls `/api/replications/reversal-momentum/run`; default provider is Futu. | Backend-derived. Sample provider remains only for smoke testing. |
| `/paper-trading` | Runs `/api/paper`, `/api/paper/{id}`, `/api/health`, and `/api/paper/run`; default provider is Futu. | Backend-derived local simulation only. |
| `/position-map` | Reads latest saved backtest positions plus paper safety state. | Backend-derived local artifacts. Sources are shown. |
| `/options-screener` | Calls live read-only Futu option chain through backend. | Backend-derived. Browser run returned real SPY option candidates. |
| `/options-radar` | Reads saved radar snapshots and can run a backend scan. | Backend-derived snapshots. The sample scan option remains explicit. |
| `/options-radar/[symbol]` | Reads saved candidates and optionally loads live chain data. | Backend-derived. |
| `/options-buyside` | Posts to `/api/options/buy-side/assistant`. Backend fetches Futu spot and option-chain rows, then ranks strategies in `buy_side_decision.py`. | Backend-derived. The scoring process is real backend logic, not a frontend mock. |
| `/options-tools` | Market-sensitive tools first fetch the entered ticker's Futu snapshot and option chain, then call local backend calculators with those inputs. Non-market operations such as templates/watchlist remain local backend calls. | Backend-derived for option-chain calculations; local-only calls are labeled as backend research operations, not live market data. |
| `/order-book` | Defaults to Polymarket read-only public data. Sample remains selectable but is warning-labeled. | Backend-derived by default. |
| `/agent-studio` | Reads candidate files and agent API data. | Backend-derived local artifacts. |
| `/settings` | Reads masked `/api/settings` and `/api/health`. | Backend-derived. |

## Buy-Side Options Scoring

The buy-side score shown in `/options-buyside` is not a decorative frontend
number. The frontend calls `POST /api/options/buy-side/assistant`; the backend
builds a Futu market-data provider, fetches the underlying snapshot and option
chain, then ranks Long Call, Bull Call Spread, LEAPS Call, and LEAPS Call Spread
candidates in `src/quant_system/options/buy_side_decision.py`.

The page now shows the data source as backend Futu option-chain data beside the
spot and timestamp fields.

## Changes Made From This Review

- Language toggle now performs a hard page refresh after saving the cookie, so
  the visible shell switches immediately.
- Dashboard KPI/details now include latest saved run source labels.
- `DataSourceBadge` marks any sample source as `sample / not real`.
- Backtest benchmark source is shown beside the benchmark card.
- Options Tools now loads live Futu option-chain context before Greeks,
  strategy ranking, contract scoring, simulation, and signal calculations.
  Local-only research operations are labeled separately.
- Buy-Side Options Assistant now states that recommendations come from backend
  Futu option-chain data.
- Prediction Market Order Book defaults to `polymarket` instead of `sample`.
  Sample mode is still available for smoke tests, but not the default path.

## Remaining Guardrails

- `sample` providers still exist for deterministic smoke tests and offline
  development. They must remain explicitly labeled and should not be the default
  for user-facing research pages.
- Saved historical runs may have been produced from sample data. Those are real
  saved backend artifacts, but their source must stay visible so users do not
  mistake them for live-market results.
- Options Tools still includes local research operations that do not need market
  data, such as templates and watchlist actions. They must stay labeled as local
  backend calls rather than live market calculations.

## Verification Notes

- `/api/health` returned `status=ok`, `configured_default=futu`,
  `live_trading_enabled=false`, and `kill_switch=true`.
- `/api/symbols` returned the Futu default basket.
- `/api/market-data/history?provider=futu&ticker=SPY&start=2026-05-01&end=2026-05-31`
  returned 20 real OHLCV rows with `source=futu`.
- `/api/options/snapshot/AAPL` returned `source=futu`, current spot, nearest
  expiry, IV, HV, and IV-rank fields.
- `/api/prediction-market/markets?provider=polymarket&limit=2` returned live
  Polymarket public markets and order books.
- Browser checks covered Dashboard, Data Explorer, Factor Lab, Backtest,
  Replications, Paper Trading, Position Map, Options Screener, Options Radar,
  Options Tools, Buy-Side Options Assistant, Order Book, Agent Studio, Settings,
  and the reversal/momentum docs page.
