# AI-Assisted Quant Research Platform

Local-first quant research, backtesting, paper-trading, read-only market-data,
and options research platform.

The project is currently delivered through Phase 14. It includes:

- US equity and ETF historical data workflows.
- Factor research, backtests, experiments, and paper-trading simulation.
- Local FastAPI backend and Next.js frontend.
- AI research assistant with candidate pool and human review gates.
- Read-only Polymarket research, snapshots, replay, and reports.
- Futu read-only US stock and options data.
- Options Income Screener, Options Radar, and Buy-Side Options Assistant.
- Local AlphaGBM-style options toolbox and local Futu option quote cache.
- Paper replication workbench for the reversal/momentum strategy.

This project does not add live trading, broker order submission, wallet
connection, signing, Futu account unlock, or real order placement.

## Quick Start

Install Python dependencies in the existing conda environment:

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev]"
```

Install frontend dependencies:

```powershell
cd src/frontend
npm install
```

Start the backend:

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

Equivalent direct FastAPI command:

```powershell
conda activate ai-quant
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

Start the frontend in another PowerShell:

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

Open:

```text
http://127.0.0.1:3001
```

Health check:

```powershell
curl http://127.0.0.1:8765/api/health
```

## Main Pages

| Page | Purpose |
|---|---|
| `/data-explorer` | US equity historical data viewer. |
| `/factor-lab` | Run factors and inspect factor outputs. |
| `/backtest` | Run research backtests. |
| `/replications` | Reproduce the short-term reversal and longer-term momentum paper workflow. |
| `/docs/reversal-momentum` | Frontend-readable notes for the paper replication. |
| `/experiments` | Inspect experiment sweeps, folds, comparisons, and send best params to backtest. |
| `/paper-trading` | Run paper-trading simulation only. |
| `/position-map` | Inspect latest backtest positions and paper-trading safety state. |
| `/options-screener` | Single-ticker seller options screener. |
| `/options-radar` | Daily seller options radar snapshot. |
| `/options-radar/[symbol]` | Single-ticker radar drilldown and live chain loader. |
| `/options-tools` | Local AlphaGBM-style options toolbox. |
| `/options-buyside` | Buy-side options strategy assistant. |
| `/order-book` | Read-only prediction-market research page. |
| `/agent-studio` | AI research assistant candidate workflows. |
| `/settings` | Masked local settings. |

The UI is bilingual (English / 中文). Use the language toggle in the top bar to
switch the whole site; the choice is stored in the `qs_lang` cookie. See
[docs/frontend/frontend_chinese_version.md](docs/frontend/frontend_chinese_version.md).

## Futu Read-Only Data

Futu OpenD is used for US stock and options market data only.

Requirements:

1. OpenD is running locally and logged in.
2. `futu-api` is installed in the `ai-quant` environment.
3. The platform only uses quote/data paths, not trading paths.

Verification:

```powershell
conda activate ai-quant
python scripts/verify_futu_connection.py
```

Important constraints:

- No Futu trade context.
- No account unlock.
- No order placement.
- No broker execution.

Interactive options pages include a short-lived in-process cache, a local
DuckDB-backed Futu option quote cache, and a one-time retry for Futu rate-limit
responses. Broad daily scans should still be scheduled and expected to run
slowly under Futu pacing.

## Options Workflows

Single-ticker seller screener:

```text
http://127.0.0.1:3001/options-screener
```

Daily seller radar:

```powershell
conda activate ai-quant
quant-system options daily-scan --top 10
```

Radar UI:

```text
http://127.0.0.1:3001/options-radar
```

The Radar page can run a sample scan and refresh the local universe, earnings,
and VIX caches from public or sample sources.

Local options toolbox:

```text
http://127.0.0.1:3001/options-tools
```

Buy-side assistant debug CLI:

```powershell
conda activate ai-quant
quant-system options buyside-screen --ticker AAPL --view long_term_aggressive_bullish --target-price 220 --target-date 2026-12-31
```

Buy-side assistant page:

```text
http://127.0.0.1:3001/options-buyside
```

All options outputs are research-only decision support. They are not financial
advice and cannot place orders.

## Polymarket / Prediction Market

The prediction-market module is read-only research:

```powershell
conda activate ai-quant
quant-system prediction-market collect --provider sample --duration 0 --limit 10
quant-system prediction-market timeseries-backtest --provider sample
```

It does not sign, redeem, transfer, or submit real market orders.

## Validation

Backend:

```powershell
conda activate ai-quant
python -m pytest -q
ruff check src/quant_system tests
```

Frontend:

```powershell
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```

Browser smoke:

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1
```

## Recommended Reading

Start here:

- [docs/OVERVIEW.md](docs/OVERVIEW.md)
- [docs/INDEX.md](docs/INDEX.md)
- [docs/SYSTEM_DESIGN_RESEARCH.md](docs/SYSTEM_DESIGN_RESEARCH.md)

Current options docs:

- [docs/futu/futu_environment_setup.md](docs/futu/futu_environment_setup.md)
- [docs/futu/futu_options_data_provider.md](docs/futu/futu_options_data_provider.md)
- [docs/options/options_screener_learning.md](docs/options/options_screener_learning.md)
- [docs/options/buyside_strategy_learning.md](docs/options/buyside_strategy_learning.md)
- [docs/options/local_alphagbm_tools.md](docs/options/local_alphagbm_tools.md)
- [docs/delivery/phase_14_delivery.md](docs/delivery/phase_14_delivery.md)

Paper replication:

- [docs/replications/reversal_momentum_replication.md](docs/replications/reversal_momentum_replication.md)

Local cache plan and current status:

- [docs/architecture/database_cache_plan.md](docs/architecture/database_cache_plan.md)

## Safety Boundary

Default platform posture:

- `QS_DRY_RUN=true`
- `QS_PAPER_TRADING=true`
- `QS_LIVE_TRADING_ENABLED=false`
- `QS_NO_LIVE_TRADE_WITHOUT_MANUAL_APPROVAL=true`
- `QS_KILL_SWITCH=true`

These boundaries must not be bypassed by frontend pages, API routes, agents,
strategies, backtests, or paper-trading flows.
