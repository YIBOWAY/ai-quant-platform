# Documentation Index

This is the main map for the repository. Use it to find architecture docs,
execution runbooks, learning notes, delivery records, and safety boundaries.

Current status: Phase 14 is delivered, with follow-up local options tools,
radar drilldowns, run-detail pages, experiment review, and local Futu option
quote caching documented below.

## 1. Start Here

| Document | Purpose |
|---|---|
| [../README.md](../README.md) | Fast project entry point and run commands. |
| [OVERVIEW.md](OVERVIEW.md) | Short platform overview and safety summary. |
| [SYSTEM_DESIGN_RESEARCH.md](SYSTEM_DESIGN_RESEARCH.md) | Original system design and long-range architecture. |
| [AGENTS.md](../AGENTS.md) | Rules for AI agents working in this repo. |

## 2. Phase Map

| Phase | Scope | Architecture | Execution | Learning | Delivery |
|---|---|---|---|---|---|
| 0 | Project skeleton | [architecture](architecture/phase_0_architecture.md) | [execution](execution/phase_0_execution.md) | [learning](learning/phase_0_learning.md) | [delivery](delivery/phase_0_delivery.md) |
| 1 | Data layer MVP | [architecture](architecture/phase_1_architecture.md) | [execution](execution/phase_1_execution.md) | [learning](learning/phase_1_learning.md) | [delivery](delivery/phase_1_delivery.md) |
| 2 | Factor research MVP | [architecture](architecture/phase_2_architecture.md) | [execution](execution/phase_2_execution.md) | [learning](learning/phase_2_learning.md) | [delivery](delivery/phase_2_delivery.md) |
| 3 | Backtest MVP | [architecture](architecture/phase_3_architecture.md) | [execution](execution/phase_3_execution.md) | [learning](learning/phase_3_learning.md) | [delivery](delivery/phase_3_delivery.md) |
| 4 | Multi-factor experiments | [architecture](architecture/phase_4_architecture.md) | [execution](execution/phase_4_execution.md) | [learning](learning/phase_4_learning.md) | [delivery](delivery/phase_4_delivery.md) |
| 5 | Risk and paper trading | [architecture](architecture/phase_5_architecture.md) | [execution](execution/phase_5_execution.md) | [learning](learning/phase_5_learning.md) | [delivery](delivery/phase_5_delivery.md) |
| 7 | AI research assistant | [architecture](architecture/phase_7_architecture.md) | [execution](execution/phase_7_execution.md) | [learning](learning/phase_7_learning.md) | [delivery](delivery/phase_7_delivery.md) |
| 8 | Prediction-market interfaces | [architecture](architecture/phase_8_architecture.md) | [execution](execution/phase_8_execution.md) | [learning](learning/phase_8_learning.md) | [delivery](delivery/phase_8_delivery.md) |
| 9 | Local HTTP API | [architecture](architecture/phase_9_api_architecture.md) | [execution](execution/phase_9_api_execution.md) | [learning](learning/phase_9_api_learning.md) | [delivery](delivery/phase_9_api_delivery.md) |
| 10 | Frontend/backend fixes | - | [execution](execution/phase_10_execution.md) | [learning](learning/phase_10_learning.md) | [delivery](delivery/phase_10_fix_delivery.md) |
| 11 | Read-only Polymarket data | [architecture](architecture/phase_11_architecture.md) | [execution](execution/phase_11_execution.md) | [learning](learning/phase_11_learning.md) | [delivery](delivery/phase_11_delivery.md) |
| 12 | Polymarket history replay | [architecture](architecture/phase_12_architecture.md) | [execution](execution/phase_12_execution.md) | [learning](learning/phase_12_learning.md) | [delivery](delivery/phase_12_delivery.md) |
| 13 | Options Radar | [architecture](architecture/phase_13_architecture.md) | [execution](execution/phase_13_execution.md) | [learning](learning/phase_13_learning.md) | [delivery](delivery/phase_13_delivery.md) |
| 14 | Buy-Side Options Assistant | - | [execution](execution/phase_14_execution.md) | [learning](options/buyside_strategy_learning.md) | [delivery](delivery/phase_14_delivery.md) |

## 3. Key Code Entry Points

| Area | Entry Point |
|---|---|
| Equity data provider factory | `src/quant_system/data/provider_factory.py` |
| Futu equity data provider | `src/quant_system/data/providers/futu.py` |
| Factor pipeline | `src/quant_system/factors/pipeline.py` |
| Factor Lab dashboard engine | `src/quant_system/factors/lab.py` |
| Backtest pipeline | `src/quant_system/backtest/pipeline.py` |
| Strategy registry | `src/quant_system/strategies/registry.py` |
| Universe registry | `src/quant_system/universe/registry.py` |
| Reversal/momentum paper replication | `src/quant_system/replication/reversal_momentum.py` |
| Paper-trading pipeline | `src/quant_system/execution/pipeline.py` |
| Options seller screener | `src/quant_system/options/screener.py` |
| Options Radar | `src/quant_system/options/radar.py` |
| Options Radar refresh helpers | `src/quant_system/options/data_refresh.py` |
| Local AlphaGBM-style options tools | `src/quant_system/options/local_tools.py` |
| Local options research helpers | `src/quant_system/options/local_research.py` |
| Futu options DuckDB cache | `src/quant_system/storage/options_cache.py` |
| PostgreSQL run index (optional) | `src/quant_system/storage/runs_repository.py` |
| Database connection + migrations | `src/quant_system/storage/database.py` |
| Buy-side metrics | `src/quant_system/options/buy_side_metrics.py` |
| Buy-side strategy generation | `src/quant_system/options/buy_side_strategy.py` |
| Buy-side scenario lab | `src/quant_system/options/buy_side_scenarios.py` |
| Buy-side decision API logic | `src/quant_system/options/buy_side_decision.py` |
| Futu stock/options provider | `src/quant_system/data/providers/futu.py` |
| Prediction-market provider factory | `src/quant_system/prediction_market/provider_factory.py` |
| Prediction-market collector | `src/quant_system/prediction_market/collector.py` |
| Prediction-market replay backtest | `src/quant_system/prediction_market/timeseries_backtest.py` |
| API routes | `src/quant_system/api/routes/` |
| Frontend routes | `src/frontend/app/` |

## 4. Options And Futu Docs

| Document | Purpose |
|---|---|
| [futu/futu_integration_design.md](futu/futu_integration_design.md) | Futu integration design. |
| [futu/futu_environment_setup.md](futu/futu_environment_setup.md) | OpenD and SDK setup. |
| [futu/futu_market_data_provider.md](futu/futu_market_data_provider.md) | Futu equity data provider. |
| [futu/futu_options_data_provider.md](futu/futu_options_data_provider.md) | Futu options provider, fields, rate limits, and safe failures. |
| [futu/futu_troubleshooting.md](futu/futu_troubleshooting.md) | Futu troubleshooting. |
| [options/options_screener_api.md](options/options_screener_api.md) | Options screener API reference. |
| [options/options_screener_learning.md](options/options_screener_learning.md) | Seller options screener guide. |
| [options/buyside_strategy_learning.md](options/buyside_strategy_learning.md) | Buy-side assistant guide, Scenario Lab, and risk disclosure. |
| [options/local_alphagbm_tools.md](options/local_alphagbm_tools.md) | Local AlphaGBM-style options tools and endpoints. |
| [delivery/phase_14_delivery.md](delivery/phase_14_delivery.md) | Phase 14 delivery and validation record. |
| [audits/README.md](audits/README.md) | Historical audit notes and current-state pointers. |
| [audits/FRONTEND_REAL_DATA_REVIEW_2026-05-31.md](audits/FRONTEND_REAL_DATA_REVIEW_2026-05-31.md) | Current frontend real-data and sample-labeling review. |

## 5. Research Replication Docs

| Document | Purpose |
|---|---|
| [replications/reversal_momentum_replication.md](replications/reversal_momentum_replication.md) | Local replication guide for the short-term reversal and longer-term momentum paper. |
| [learning/research_registry_pipeline_2026_06_02.md](learning/research_registry_pipeline_2026_06_02.md) | Strategy, universe, backtest, and read-only Factor Lab registry workflow. |

## 6. Polymarket / Prediction-Market Docs

| Document | Purpose |
|---|---|
| [polymarket/polymarket_read_only_integration.md](polymarket/polymarket_read_only_integration.md) | Read-only integration guide. |
| [polymarket/polymarket_history_collection.md](polymarket/polymarket_history_collection.md) | Historical snapshot collector guide. |
| [polymarket/polymarket_timeseries_backtest_learning.md](polymarket/polymarket_timeseries_backtest_learning.md) | Time-series replay learning guide. |
| [polymarket/polymarket_charts_and_metrics.md](polymarket/polymarket_charts_and_metrics.md) | Charts and metrics explanation. |
| [polymarket/polymarket_troubleshooting.md](polymarket/polymarket_troubleshooting.md) | Troubleshooting guide. |
| [polymarket/polymarket_safety_boundaries.md](polymarket/polymarket_safety_boundaries.md) | Safety and non-goals. |

## 7. Current Frontend Pages

| Page | Purpose |
|---|---|
| `/data-explorer` | Equity data viewer. |
| `/factor-lab` | Read-only factor health and single-symbol timing dashboard. |
| `/factor-lab/[runId]` | Factor run details. |
| `/backtest` | Strategy, universe, and factor-weight backtest runs. |
| `/backtest/[runId]` | Backtest run details. |
| `/replications` | Strategy Catalog backed by the strategy registry. |
| `/docs/reversal-momentum` | Frontend-readable replication documentation. |
| `/experiments` | Experiment sweep, fold, comparison, and best-run review. |
| `/paper-trading` | Paper-trading simulation. |
| `/paper-trading/[runId]` | Paper-trading run details. |
| `/position-map` | Latest backtest position map and paper safety context. |
| `/options-screener` | Single-ticker seller options screen. |
| `/options-radar` | Daily seller options radar snapshot. |
| `/options-radar/[symbol]` | Saved radar candidates plus optional live chain load. |
| `/options-tools` | Local AlphaGBM-style options toolbox. |
| `/options-buyside` | Buy-side options strategy assistant. |
| `/order-book` | Read-only prediction-market research. |
| `/agent-studio` | AI research assistant workflows. |
| `/settings` | Masked local settings. |

Frontend docs:

| Document | Purpose |
|---|---|
| [frontend/frontend_chinese_version.md](frontend/frontend_chinese_version.md) | Site-wide English / 中文 language paths, toggle, and cookie fallback. |
| [frontend/design_brief.md](frontend/design_brief.md) | Frontend design brief and component plan. |

## 8. Common Commands

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

Tests and lint:

```powershell
conda activate ai-quant
python -m pytest -q
ruff check src/quant_system tests
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```

Options Radar sample-sized real run:

```powershell
conda activate ai-quant
quant-system options daily-scan --top 10
```

Buy-side assistant debug run:

```powershell
conda activate ai-quant
quant-system options buyside-screen --ticker AAPL --view long_term_aggressive_bullish --target-price 220 --target-date 2026-12-31
```

## 9. Safety Checklist

1. `/api/health` shows `live_trading_enabled=false`.
2. `/api/orders/submit` returns 404.
3. `/api/settings` masks secrets.
4. `/api/agent/llm-config` does not return API keys.
5. Prediction-market requests carrying `polymarket_api_key` return 400.
6. No wallet, signing, broker, or live order route exists.
7. Futu code uses quote/data context only.
8. Frontend pages label research-only / read-only outputs clearly.

## 10. Cache Layer Status

Two local storage layers are implemented:

- DuckDB caches local Futu option quote windows
  (`storage/options_cache.py`).
- An optional PostgreSQL **run index** (`storage/database.py`,
  `storage/runs_repository.py`, `scripts/sql/001_runs_index.sql`) mirrors
  file-based backtest/factor/paper runs for fast listing. It is off by default
  (`QS_DATABASE_ENABLED`), reconciles with the filesystem on startup, and the API
  falls back to scanning files when the database is off or unreachable.

Read:

- [architecture/database_cache_plan.md](architecture/database_cache_plan.md)

Current and next directions:

- DuckDB is used now for local Futu option quote windows.
- PostgreSQL is used now (optionally) for the backtest/factor/paper run index.
- Remaining PostgreSQL targets: radar runs, request logs, and richer
  API-visible snapshots.
- Parquet / DuckDB for large OHLCV and analytical time-series datasets.
- Optional TimescaleDB later if PostgreSQL becomes the main time-series store.
