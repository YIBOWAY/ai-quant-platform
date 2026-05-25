# Platform Overview

This repository is a local-first AI quant research and paper-trading platform.
It is built for research, testing, reporting, and read-only market-data
analysis. It is not a live-trading platform.

Current status: Phase 14 is delivered, with additional local options tooling,
radar drilldowns, run-detail pages, experiment review, and local Futu option
quote caching added after the initial delivery.

## What It Can Do

Equity research:

- Read real US equity and ETF historical data.
- Run factor research.
- Run backtests.
- Store experiment results.
- Run paper-trading simulations.

Options research:

- Read Futu US options chains and quote snapshots.
- Run the single-ticker Options Income Screener.
- Run daily Options Radar scans over a local universe.
- Refresh the local radar universe, earnings, and VIX caches from the Radar UI.
- Inspect single-symbol Radar candidates and optionally load a live chain.
- Use VIX/VIX3M history to classify market regime.
- Run the Buy-Side Options Assistant for bullish long-premium structures.
- Use local AlphaGBM-style options tools for Greeks, smiles, surfaces, scoring,
  strategy ranking, and research-only alerts/watchlists.

Prediction-market research:

- Read public market data.
- Collect historical snapshots.
- Run replay-style time-series backtests.
- Generate reports and charts.

AI research assistant:

- Generate candidate factors, experiment configs, and reports.
- Store candidates in a review pool.
- Require human review before anything can be promoted.

## What It Cannot Do

- No live trading.
- No real broker order submission.
- No wallet connection.
- No signing.
- No Futu account unlock.
- No Futu trading context.
- No automatic strategy promotion into live execution.
- No investment advice.

## Safety Boundary

The default safety posture must stay conservative:

- `dry_run = true`
- `paper_trading = true`
- `live_trading_enabled = false`
- `kill_switch = true`
- `no_live_trade_without_manual_approval = true`

Every new feature must preserve these boundaries.

## How To Start

Backend:

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

Frontend:

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

Open:

```text
http://127.0.0.1:3001
```

## New Contributor Reading Order

1. [README.md](../README.md)
2. [INDEX.md](INDEX.md)
3. [SYSTEM_DESIGN_RESEARCH.md](SYSTEM_DESIGN_RESEARCH.md)
4. [execution/phase_13_execution.md](execution/phase_13_execution.md)
5. [delivery/phase_13_delivery.md](delivery/phase_13_delivery.md)
6. [execution/phase_14_execution.md](execution/phase_14_execution.md)
7. [delivery/phase_14_delivery.md](delivery/phase_14_delivery.md)

For options work, also read:

- [futu/futu_options_data_provider.md](futu/futu_options_data_provider.md)
- [options/options_screener_learning.md](options/options_screener_learning.md)
- [options/buyside_strategy_learning.md](options/buyside_strategy_learning.md)

For the next database/cache step, read:

- [architecture/database_cache_plan.md](architecture/database_cache_plan.md)
