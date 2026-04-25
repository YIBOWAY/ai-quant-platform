from __future__ import annotations

import json
from pathlib import Path

from quant_system.experiments.models import (
    ExperimentConfig,
    FactorBlendConfig,
    FactorDirection,
    FactorWeight,
    WalkForwardConfig,
)


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return ExperimentConfig.model_validate(payload)


def create_sample_experiment_config(
    *,
    symbols: list[str],
    start: str,
    end: str,
    lookbacks: list[int],
    top_ns: list[int],
    initial_cash: float = 100_000.0,
    commission_bps: float = 1.0,
    slippage_bps: float = 5.0,
    rebalance_every_n_bars: int = 1,
) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_name="phase4-sample-experiment",
        symbols=symbols,
        start=start,
        end=end,
        initial_cash=initial_cash,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        factor_blend=FactorBlendConfig(
            factors=[
                FactorWeight(
                    factor_id="momentum",
                    weight=1.0,
                    direction=FactorDirection.HIGHER_IS_BETTER,
                ),
                FactorWeight(
                    factor_id="volatility",
                    weight=0.5,
                    direction=FactorDirection.LOWER_IS_BETTER,
                ),
                FactorWeight(
                    factor_id="liquidity",
                    weight=0.5,
                    direction=FactorDirection.HIGHER_IS_BETTER,
                ),
            ],
            rebalance_every_n_bars=rebalance_every_n_bars,
        ),
        sweep={"lookback": lookbacks, "top_n": top_ns},
        walk_forward=WalkForwardConfig(enabled=False),
    )
