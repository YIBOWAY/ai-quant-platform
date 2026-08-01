from __future__ import annotations

from pydantic import BaseModel, Field


class StrategyMetadata(BaseModel):
    id: str
    name: str
    # Optional zh display layer; ids and name stay canonical English.
    display_name_zh: str | None = None
    description: str
    paper_source: str | None = None
    run_endpoint: str
    result_type: str
    supports_account_rebalance: bool = False
    parameter_schema: dict = Field(default_factory=dict)
    default_payload: dict = Field(default_factory=dict)


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, StrategyMetadata] = {}

    def register(self, metadata: StrategyMetadata) -> None:
        if metadata.id in self._strategies:
            raise ValueError(f"strategy id {metadata.id!r} is already registered")
        self._strategies[metadata.id] = metadata

    def strategy_ids(self) -> list[str]:
        return list(self._strategies)

    def list_metadata(self) -> list[StrategyMetadata]:
        return list(self._strategies.values())

    def get(self, strategy_id: str) -> StrategyMetadata:
        try:
            return self._strategies[strategy_id]
        except KeyError as exc:
            raise KeyError(f"unknown strategy id {strategy_id!r}") from exc


def build_default_strategy_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(
        StrategyMetadata(
            id="cross_sectional_top_n",
            name="Cross-Sectional Top-N",
            display_name_zh="横截面 Top-N",
            description=(
                "Ranks a selected universe by blended factor score and holds the "
                "top positive-scoring names."
            ),
            paper_source=None,
            run_endpoint="/api/backtests/run",
            result_type="backtest",
            supports_account_rebalance=True,
            parameter_schema={
                "fields": {
                    "universe_id": {"type": "universe", "required": True},
                    "factor_ids": {"type": "factor_multi_select", "required": True},
                    "weights": {"type": "factor_weight_map", "required": False},
                    "top_n": {"type": "integer", "default": 3, "min": 1},
                    "benchmark_symbol": {"type": "symbol", "default": "SPY"},
                    "start": {"type": "date", "default": "2024-01-02"},
                    "end": {"type": "date", "default": "2024-06-28"},
                    "provider": {"type": "provider", "default": "sample"},
                }
            },
            default_payload={
                "strategy_id": "cross_sectional_top_n",
                "universe_id": "etf",
                "factor_ids": ["momentum", "volatility", "liquidity"],
                "weights": {"momentum": 1.0, "volatility": 0.5, "liquidity": 0.5},
                "benchmark_symbol": "SPY",
                "top_n": 3,
                "provider": "sample",
            },
        )
    )
    registry.register(
        StrategyMetadata(
            id="reversal_momentum",
            name="Short-Term Reversal / Longer-Term Momentum",
            display_name_zh="短期反转 / 长期动量",
            description=(
                "Local research-only replication of monthly short-term reversal "
                "and longer-term momentum portfolios."
            ),
            paper_source=(
                "Short-Term Reversals and Longer-Term Momentum, Review of Financial "
                "Studies, DOI 10.1093/rfs/hhaf057"
            ),
            run_endpoint="/api/replications/reversal-momentum/run",
            result_type="replication",
            parameter_schema={
                "fields": {
                    "symbols": {"type": "symbol_list", "required": True},
                    "start": {"type": "date", "default": "2023-01-01"},
                    "end": {"type": "date", "default": "2026-05-22"},
                    "provider": {"type": "provider", "default": "futu"},
                    "initial_cash": {"type": "number", "default": 1.0, "min": 0},
                    "top_n": {"type": "integer_or_null", "default": None, "min": 1},
                }
            },
            default_payload={
                "symbols": ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLY"],
                "start": "2023-01-01",
                "end": "2026-05-22",
                "provider": "futu",
                "initial_cash": 1.0,
                "top_n": None,
            },
        )
    )
    registry.register(
        StrategyMetadata(
            id="mean_reversion_top_n",
            name="Mean-Reversion Top-N",
            display_name_zh="均值回归 Top-N",
            description=(
                "Contrarian counterpart to Cross-Sectional Top-N. Buys the "
                "lowest blended-score names (recent underperformers) each "
                "period, betting on short-term mean reversion, and "
                "equal-weights them."
            ),
            paper_source=None,
            run_endpoint="/api/backtests/run",
            result_type="backtest",
            supports_account_rebalance=True,
            parameter_schema={
                "fields": {
                    "universe_id": {"type": "universe", "required": True},
                    "factor_ids": {"type": "factor_multi_select", "required": True},
                    "weights": {"type": "factor_weight_map", "required": False},
                    "top_n": {"type": "integer", "default": 3, "min": 1},
                    "benchmark_symbol": {"type": "symbol", "default": "SPY"},
                    "start": {"type": "date", "default": "2024-01-02"},
                    "end": {"type": "date", "default": "2024-06-28"},
                    "provider": {"type": "provider", "default": "sample"},
                }
            },
            default_payload={
                "strategy_id": "mean_reversion_top_n",
                "universe_id": "etf",
                "factor_ids": ["momentum", "volatility", "liquidity"],
                "weights": {"momentum": 1.0, "volatility": 0.5, "liquidity": 0.5},
                "benchmark_symbol": "SPY",
                "top_n": 3,
                "provider": "sample",
            },
        )
    )
    # Research draft only. Factor is Gate-2 approved candidate, not Gate-3
    # promoted; default payload keeps a runnable resident blend so catalog
    # listing does not break /api/backtests/run. Full candidate binding and
    # sample evidence live under strategies/drafts/.
    registry.register(
        StrategyMetadata(
            id="drift_regime_reversal_top_n_v1",
            name="Drift Regime Reversal Top-N (Research Draft)",
            display_name_zh="漂移状态反转 Top-N（研究草稿）",
            description=(
                "RESEARCH DRAFT — long-only Top-N inspired by arXiv:2511.12490 "
                "(drift-regime gated value + short-term reversal). Candidate "
                "factor_id=drift_regime_reversal_edge_v1 is approved but not "
                "resident-promoted. Catalog default_payload uses resident "
                "momentum as a placeholder so the UI remains runnable; see "
                "strategies/drafts/drift_regime_reversal_top_n_v1.json for the "
                "true candidate binding and sample-lab evidence. Not paper/live."
            ),
            paper_source=(
                "Discovery of a 13-Sharpe OOS Factor: Drift Regimes Unlock "
                "Hidden Cross-Sectional Predictability, arXiv:2511.12490"
            ),
            run_endpoint="/api/backtests/run",
            result_type="backtest",
            supports_account_rebalance=False,
            parameter_schema={
                "fields": {
                    "universe_id": {"type": "universe", "required": True},
                    "factor_ids": {"type": "factor_multi_select", "required": True},
                    "weights": {"type": "factor_weight_map", "required": False},
                    "top_n": {"type": "integer", "default": 3, "min": 1},
                    "benchmark_symbol": {"type": "symbol", "default": "SPY"},
                    "start": {"type": "date", "default": "2024-01-02"},
                    "end": {"type": "date", "default": "2024-12-31"},
                    "provider": {"type": "provider", "default": "sample"},
                }
            },
            default_payload={
                "strategy_id": "cross_sectional_top_n",
                "universe_id": "etf",
                # Placeholder resident factor — true research factor is still
                # candidate-only (drift_regime_reversal_edge_v1).
                "factor_ids": ["momentum"],
                "weights": {"momentum": 1.0},
                "benchmark_symbol": "SPY",
                "top_n": 3,
                "provider": "sample",
                "start": "2024-01-02",
                "end": "2024-12-31",
            },
        )
    )
    return registry
