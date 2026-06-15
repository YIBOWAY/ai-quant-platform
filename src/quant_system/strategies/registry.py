from __future__ import annotations

from pydantic import BaseModel, Field


class StrategyMetadata(BaseModel):
    id: str
    name: str
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
    return registry
