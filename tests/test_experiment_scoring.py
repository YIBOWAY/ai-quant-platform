import pandas as pd
import pytest

from quant_system.experiments.models import FactorBlendConfig, FactorDirection, FactorWeight
from quant_system.experiments.scoring import build_multifactor_score_frame


def _factor_results() -> pd.DataFrame:
    signal_ts = pd.Timestamp("2024-01-02", tz="UTC")
    tradeable_ts = pd.Timestamp("2024-01-03", tz="UTC")
    rows = []
    for factor_id, values in {
        "momentum": [1.0, 2.0, 3.0],
        "volatility": [1.0, 2.0, 3.0],
    }.items():
        for symbol, value in zip(["AAA", "BBB", "CCC"], values, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "signal_ts": signal_ts,
                    "tradeable_ts": tradeable_ts,
                    "factor_id": factor_id,
                    "factor_version": "0.1.0",
                    "factor_name": factor_id.title(),
                    "lookback": 3,
                    "value": value,
                }
            )
    return pd.DataFrame(rows)


def test_multifactor_score_standardizes_direction_and_weights() -> None:
    config = FactorBlendConfig(
        factors=[
            FactorWeight(
                factor_id="momentum",
                weight=1.0,
                direction=FactorDirection.HIGHER_IS_BETTER,
            ),
            FactorWeight(
                factor_id="volatility",
                weight=1.0,
                direction=FactorDirection.LOWER_IS_BETTER,
            ),
        ]
    )

    score_frame = build_multifactor_score_frame(_factor_results(), config)

    assert {"momentum", "volatility", "score"}.issubset(score_frame.columns)
    assert score_frame.loc[score_frame["symbol"] == "AAA", "score"].iloc[0] == pytest.approx(0)
    assert score_frame.loc[score_frame["symbol"] == "BBB", "score"].iloc[0] == pytest.approx(0)
    assert score_frame.loc[score_frame["symbol"] == "CCC", "score"].iloc[0] == pytest.approx(0)
    assert score_frame["score"].notna().all()


def test_multifactor_score_can_filter_rebalance_dates() -> None:
    frame = pd.concat(
        [
            _factor_results(),
            _factor_results().assign(
                signal_ts=pd.Timestamp("2024-01-03", tz="UTC"),
                tradeable_ts=pd.Timestamp("2024-01-04", tz="UTC"),
            ),
            _factor_results().assign(
                signal_ts=pd.Timestamp("2024-01-04", tz="UTC"),
                tradeable_ts=pd.Timestamp("2024-01-05", tz="UTC"),
            ),
        ],
        ignore_index=True,
    )
    config = FactorBlendConfig(
        factors=[
            FactorWeight(
                factor_id="momentum",
                weight=1.0,
                direction=FactorDirection.HIGHER_IS_BETTER,
            )
        ],
        rebalance_every_n_bars=2,
    )

    score_frame = build_multifactor_score_frame(frame, config)

    assert list(score_frame["tradeable_ts"].drop_duplicates()) == [
        pd.Timestamp("2024-01-03", tz="UTC"),
        pd.Timestamp("2024-01-05", tz="UTC"),
    ]
