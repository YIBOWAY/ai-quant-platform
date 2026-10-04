"""Factor scorecards: hand-computed seals, coverage audits, persistence and wiring.

All sealed numbers were recomputed by hand from the T2.1 design before freezing; the
service tests always pass an explicit ``output_dir`` so no production data directory is
touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_system.config.settings import reload_settings
from quant_system.factors.evaluation import METHODOLOGY_VERSION
from quant_system.factors.registry import build_factor_registry
from quant_system.factors.scorecard import (
    SCORECARD_SCHEMA_VERSION,
    SOURCE_DIGEST_VERSION,
    build_factor_scorecard_bundle,
    build_factor_scorecards,
    current_source_digest,
    long_short_beta_hedge,
    sleeve_marginal_contribution,
)
from quant_system.factors.scorecard_service import (
    read_factor_scorecards,
    refresh_factor_scorecards,
)
from quant_system.research.trials import TrialsLedger

HAND_SEAL_ABS = 1e-9


def _panel_from_opens(opens: dict[str, list[float]], dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for symbol, values in opens.items():
        for index, price in enumerate(values):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": dates[index],
                    "open": float(price),
                    "high": float(price) + 1.0,
                    "low": float(price) - 1.0,
                    "close": float(price),
                    "volume": 1_000.0,
                }
            )
    return pd.DataFrame(rows)


def _factor_frame(
    rows: list[tuple[str, pd.Timestamp, float]], factor_id: str = "f"
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [row[0] for row in rows],
            "signal_ts": [row[1] for row in rows],
            "factor_id": [factor_id] * len(rows),
            "value": [row[2] for row in rows],
        }
    )


# --------------------------------------------------------------------------------------
# Q5 - Q1 hand seal
# --------------------------------------------------------------------------------------


def _ten_symbol_panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    dates = pd.date_range("2024-01-01", periods=4, freq="B", tz="UTC")
    opens = {
        f"S{index:02d}": [100.0, 100.0, 100.0 * (1 + 0.001 * index), 100.0]
        for index in range(1, 11)
    }
    panel = _panel_from_opens(opens, dates)
    factors = _factor_frame(
        [(f"S{index:02d}", dates[0], float(index)) for index in range(1, 11)]
    )
    return panel, factors, dates


def test_long_short_spread_hand_computed_quantile_means() -> None:
    panel, factors, dates = _ten_symbol_panel()
    scorecard = build_factor_scorecards(
        factor_results=factors,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="SPY",
        horizons=(1,),
        quantiles=5,
    )
    entry = scorecard["factors"][0]
    block = entry["horizons"]["1"]

    # Q5 = {S09, S10} mean 0.0095; Q1 = {S01, S02} mean 0.0015; spread 0.008.
    assert block["quantiles"]["quantile_means"] == pytest.approx(
        [0.0015, 0.0035, 0.0055, 0.0075, 0.0095], abs=HAND_SEAL_ABS
    )
    assert block["quantiles"]["quantile_monotonic"] is True
    assert block["long_short"]["spread_mean_daily"] == pytest.approx(0.008, abs=HAND_SEAL_ABS)
    assert block["long_short"]["spread_mean_daily_raw"] == pytest.approx(0.008, abs=HAND_SEAL_ABS)
    assert block["long_short"]["spread_annualized"] == pytest.approx(0.008 * 252, abs=1e-9)
    assert block["long_short"]["spread_t_nw"] is None
    assert block["long_short"]["spread_nw_reason"] == "insufficient_observations"
    assert block["long_short"]["evaluation_only"] is True
    assert block["long_short"]["tradeable_claim"] is False
    assert "无摩擦卖空" in block["long_short"]["short_assumption"]
    assert entry["direction_defaulted"] is True
    assert entry["industry_neutral"]["status"] == "field_unavailable"
    assert scorecard["methodology"]["costs"] == "none_evaluation_only"


@pytest.mark.parametrize("horizon", [1, 5, 21])
def test_long_short_daily_and_annualized_spread_respect_return_horizon(horizon) -> None:
    dates = pd.date_range("2024-01-01", periods=horizon + 2, freq="B", tz="UTC")
    opens = {
        f"S{index:02d}": [100.0] * (horizon + 1) + [100.0 * (1 + horizon * 0.001 * index)]
        for index in range(1, 11)
    }
    factors = _factor_frame(
        [(f"S{index:02d}", dates[0], float(index)) for index in range(1, 11)]
    )
    scorecard = build_factor_scorecards(
        factor_results=factors,
        ohlcv=_panel_from_opens(opens, dates),
        factor_metadata=[],
        horizons=(horizon,),
    )
    entry = scorecard["factors"][0]["horizons"][str(horizon)]
    # Q5 - Q1 is 0.008 * h over h sessions, hence 0.008 per session.
    assert entry["quantiles"]["quantile_means"][-1] == pytest.approx(0.0095 * horizon)
    assert entry["long_short"]["spread_mean_daily"] == pytest.approx(0.008)
    assert entry["long_short"]["spread_mean_daily_raw"] == pytest.approx(0.008)
    assert entry["long_short"]["spread_annualized"] == pytest.approx(0.008 * 252)


@pytest.mark.parametrize("frequency", [None, "month_end"])
@pytest.mark.parametrize("step", [20, 21])
def test_sparse_monthly_signals_do_not_claim_252_annual_opportunities(frequency, step):
    dates = pd.date_range("2018-01-01", periods=1500, freq="B", tz="UTC")
    opens = {
        f"S{i:02d}": (100 * np.cumprod(1 + 0.0001 * i + 0.003 * np.sin(np.arange(1500)))).tolist()
        for i in range(1, 11)
    }
    opens["SPY"] = (100 * np.cumprod(1 + 0.0005 + 0.002 * np.sin(np.arange(1500)))).tolist()
    factors = _factor_frame([
        (f"S{i:02d}", day, float(i)) for day in dates[::step] for i in range(1, 11)
    ])
    metadata = [{"factor_id": "f", "frequency": frequency}] if frequency else []
    result = build_factor_scorecards(
        factor_results=factors, ohlcv=_panel_from_opens(opens, dates),
        factor_metadata=metadata, horizons=(1, 21),
    )["factors"][0]["horizons"]
    monthly = result["21"]
    from quant_system.factors.evaluation import newey_west_lag_rule

    # 21-session labels touch at step21; at step20 adjacent labels overlap.
    # The lag unit is observations, not 20 monthly observations in either case.
    overlap = 1 if step == 20 else 0
    assert monthly["inference"]["overlap_lags"] == overlap
    assert monthly["ic"]["nw_lag"] == newey_west_lag_rule(
        monthly["ic"]["n_days"], horizon=overlap + 1,
    )
    assert monthly["long_short"]["spread_nw_lag"] == newey_west_lag_rule(
        monthly["long_short"]["n_days"], horizon=overlap + 1,
    )
    result = result["1"]["long_short"]
    assert result["spread_mean_daily"] is not None
    assert result["spread_annualized"] is None
    assert result["annualization_reason"] == "sparse_signal_calendar_not_a_daily_portfolio"
    assert result["beta_neutral"]["status"] == "ready"
    assert result["beta_neutral"]["alpha_annualized"] is None
    assert result["beta_neutral"]["beta_neutral_spread_annualized"] is None


def test_one_declared_month_end_observation_cannot_default_to_daily_annualization():
    panel, factors, _ = _ten_symbol_panel()
    card = build_factor_scorecards(
        factor_results=factors, ohlcv=panel,
        factor_metadata=[{"factor_id": "f", "frequency": "month_end"}], horizons=(1,),
    )
    assert card["factors"][0]["horizons"]["1"]["long_short"]["spread_annualized"] is None


def test_month_end_factor_requires_a_real_daily_portfolio_before_sleeve_marginal_claim():
    panel, factors, dates = _ten_symbol_panel()
    card = build_factor_scorecards(
        factor_results=factors, ohlcv=panel,
        factor_metadata=[{"factor_id": "f", "frequency": "month_end"}], horizons=(1,),
        sleeve_returns={day.isoformat(): 0.001 for day in dates},
    )
    result = card["factors"][0]["marginal_contribution"]
    assert result["status"] == "not_evaluated"
    assert result["reason"] == "non_daily_signal_portfolio_required"
    assert result["marginal_sharpe_delta"] is None


def test_turnover_hand_computed_membership_change() -> None:
    dates = pd.date_range("2024-01-01", periods=4, freq="B", tz="UTC")
    opens = {"A": [100.0] * 4, "B": [100.0] * 4, "C": [100.0] * 4, "D": [100.0] * 4}
    panel = _panel_from_opens(opens, dates)
    factors = _factor_frame(
        [
            ("A", dates[0], 4.0),
            ("B", dates[0], 3.0),
            ("C", dates[0], 2.0),
            ("D", dates[0], 1.0),
            ("A", dates[1], 4.0),
            ("C", dates[1], 3.0),
            ("B", dates[1], 2.0),
            ("D", dates[1], 1.0),
        ]
    )
    scorecard = build_factor_scorecards(
        factor_results=factors,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="SPY",
        horizons=(1,),
        quantiles=2,
    )
    turnover = scorecard["factors"][0]["horizons"]["1"]["turnover"]

    # {A,B} -> {A,C}: (1/2) * (|0.5-0.5| + |0.5-0| + |0-0.5|) = 0.5 on each side.
    assert turnover["turnover_per_step"]["top"] == pytest.approx(0.5, abs=HAND_SEAL_ABS)
    assert turnover["turnover_per_step"]["bottom"] == pytest.approx(0.5, abs=HAND_SEAL_ABS)
    assert turnover["turnover_per_step"]["mean"] == pytest.approx(0.5, abs=HAND_SEAL_ABS)
    assert turnover["cadence"] == "regular"
    assert turnover["n_steps"] == 1
    assert turnover["turnover_annualized"]["top"] == pytest.approx(0.5 * 365.25, abs=1e-6)


# --------------------------------------------------------------------------------------
# Beta neutralisation hand seals
# --------------------------------------------------------------------------------------


def test_long_short_beta_hedge_hand_computed() -> None:
    dates = pd.date_range("2024-01-01", periods=4, freq="B", tz="UTC")
    benchmark = pd.Series([0.01, -0.01, 0.01, -0.01], index=dates)
    errors = np.asarray([0.001, 0.003, 0.003, 0.001])
    spread = pd.Series(2.0 * benchmark.to_numpy() + errors, index=dates)

    block = long_short_beta_hedge(
        spread, benchmark, horizon=1, min_days=4, nw_min_observations=0
    )

    assert block["status"] == "ready"
    assert block["beta"] == pytest.approx(2.0, abs=1e-12)
    assert block["alpha_annualized"] == pytest.approx(0.504, abs=1e-12)
    assert block["beta_neutral_spread_annualized"] == pytest.approx(0.504, abs=1e-12)
    assert block["beta_neutral_t"] == pytest.approx(4.6188, abs=1e-3)
    assert block["n_days"] == 4
    assert block["beta_estimation"] == "full_sample_ols"


@pytest.mark.parametrize("horizon", [1, 5, 21])
def test_long_short_beta_hedge_annualizes_the_window_alpha(horizon) -> None:
    dates = pd.date_range("2024-01-01", periods=4, freq="B", tz="UTC")
    benchmark = pd.Series([0.01, -0.01, 0.01, -0.01], index=dates) * horizon
    errors = np.asarray([0.001, 0.003, 0.003, 0.001]) * horizon
    spread = pd.Series(2.0 * benchmark.to_numpy() + errors, index=dates)
    block = long_short_beta_hedge(
        spread, benchmark, horizon=horizon, min_days=4, nw_min_observations=0
    )

    assert block["beta"] == pytest.approx(2.0)
    assert block["alpha_annualized"] == pytest.approx(0.002 * 252)
    assert block["beta_neutral_spread_annualized"] == pytest.approx(0.002 * 252)


def _beta_proxy_panel(days: int = 132) -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    betas = {"S1": 0.5, "S2": 1.0, "S3": 1.5, "S4": 2.0}
    epsilons = {"S1": 1e-6, "S2": -1e-6, "S3": -1e-6, "S4": 1e-6}
    dates = pd.date_range("2024-01-01", periods=days, freq="B", tz="UTC")
    benchmark_returns = [0.002 + 0.001 * ((index % 7) - 3) / 3 for index in range(days)]
    series = {"BMK": [100.0], **{symbol: [100.0] for symbol in betas}}
    for index in range(1, days):
        series["BMK"].append(series["BMK"][-1] * (1 + benchmark_returns[index]))
        for symbol, beta in betas.items():
            series[symbol].append(
                series[symbol][-1] * (1 + beta * benchmark_returns[index] + epsilons[symbol])
            )
    panel = pd.DataFrame(
        [
            {"symbol": symbol, "timestamp": dates[index], "open": value, "close": value}
            for symbol, values in series.items()
            for index, value in enumerate(values)
        ]
    )
    signal_days = [dates[index] for index in (126, 127, 128, 129)]
    factors = _factor_frame(
        [
            (symbol, day, beta)
            for symbol, beta in betas.items()
            for day in signal_days
        ],
        factor_id="beta_proxy",
    )
    return panel, factors, dates


def test_residual_ic_strips_benchmark_exposure() -> None:
    panel, factors, _dates = _beta_proxy_panel()
    scorecard = build_factor_scorecards(
        factor_results=factors,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="BMK",
        horizons=(1,),
        quantiles=5,
    )
    block = scorecard["factors"][0]["horizons"]["1"]

    assert block["ic"]["ic_mean"] > 0.99
    assert block["residual_ic"]["status"] == "ready"
    assert block["residual_ic"]["ic_mean"] == pytest.approx(0.0, abs=1e-6)
    assert block["residual_ic"]["excluded_no_beta"] == 0
    assert block["residual_ic"]["beta_estimation"] == "rolling_252d_min126_pit"


@pytest.mark.parametrize("missing_benchmark", [False, True])
def test_residual_beta_does_not_fill_a_missing_close(missing_benchmark) -> None:
    panel, factors, dates = _beta_proxy_panel()
    factors = factors[factors.signal_ts == dates[126]]
    target = panel.symbol.eq("BMK") if missing_benchmark else panel.symbol.ne("BMK")
    panel.loc[target & panel.timestamp.eq(dates[50]), "close"] = np.nan
    result = build_factor_scorecards(
        factor_results=factors, ohlcv=panel, factor_metadata=[],
        benchmark_symbol="BMK", horizons=(1,),
    )
    block = result["factors"][0]["horizons"]["1"]["residual_ic"]
    assert block["excluded_no_beta"] == 4
    assert block["status"] == "unavailable"


def test_residual_ic_aligns_rows_with_non_contiguous_labels() -> None:
    """A second factor makes the merged labels non-contiguous; the residual IC must
    still pair each symbol with its own residual.

    The panel carries a known beta on the benchmark plus a symbol-day idiosyncratic
    term, so the two planted factors have opposite residual signatures: the alpha
    proxy (whose value is the next day's idiosyncratic return) must keep a high
    residual IC, while the beta proxy is fully explained by the benchmark and must
    collapse to roughly zero. Mis-pairing rows collapses both.
    """

    days = 132
    betas = {"S1": 0.5, "S2": 1.0, "S3": 1.5, "S4": 2.0}
    dates = pd.date_range("2024-01-01", periods=days, freq="B", tz="UTC")
    benchmark_returns = [0.02 + 0.006 * ((index % 7) - 3) / 3 for index in range(days)]
    epsilons = {
        symbol: [0.002 * ((index + offset) % 5 - 2) / 2 for index in range(days)]
        for offset, symbol in enumerate(betas)
    }
    series = {"BMK": [100.0], **{symbol: [100.0] for symbol in betas}}
    for index in range(1, days):
        series["BMK"].append(series["BMK"][-1] * (1 + benchmark_returns[index]))
        for symbol, beta in betas.items():
            series[symbol].append(
                series[symbol][-1] * (1 + beta * benchmark_returns[index] + epsilons[symbol][index])
            )
    panel = pd.DataFrame(
        [
            {"symbol": symbol, "timestamp": dates[index], "open": value, "close": value}
            for symbol, values in series.items()
            for index, value in enumerate(values)
        ]
    )
    signal_days = [dates[index] for index in (126, 127, 128, 129)]
    beta_proxy = _factor_frame(
        [(symbol, day, beta) for symbol, beta in betas.items() for day in signal_days],
        factor_id="beta_proxy",
    )
    # The open-to-open label of signal day t is the return of day t+1, i.e. the
    # price move from dates[i+1] to dates[i+2], so the realized idiosyncratic part
    # the label carries sits at epsilons[symbol][i + 2].
    alpha_proxy = _factor_frame(
        [
            (symbol, day, epsilons[symbol][dates.get_loc(day) + 2])
            for symbol in betas
            for day in signal_days
        ],
        factor_id="alpha_proxy",
    )
    # Deliberately non-contiguous labels, mirroring the merged frame the service path
    # hands to the residual block once more than one factor row set is present.
    factors = pd.concat([beta_proxy, alpha_proxy], ignore_index=True)
    factors.index = list(range(len(beta_proxy))) + list(range(100, 100 + len(alpha_proxy)))

    scorecard = build_factor_scorecards(
        factor_results=factors,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="BMK",
        horizons=(1,),
        quantiles=5,
    )
    by_factor = {block["factor_id"]: block["horizons"]["1"] for block in scorecard["factors"]}

    alpha_residual = by_factor["alpha_proxy"]["residual_ic"]
    beta_residual = by_factor["beta_proxy"]["residual_ic"]
    assert alpha_residual["status"] == "ready"
    assert beta_residual["status"] == "ready"
    assert alpha_residual["excluded_no_beta"] == 0
    assert beta_residual["excluded_no_beta"] == 0
    assert alpha_residual["ic_mean"] > 0.9
    # The beta proxy ranks symbols by their true beta, so its raw IC is near one;
    # stripping the benchmark exposure must remove most of that signal (the residual
    # keeps a small level-dependent term from the beta estimation error).
    beta_ic = by_factor["beta_proxy"]["ic"]["ic_mean"]
    assert beta_ic > 0.9
    assert abs(beta_residual["ic_mean"]) < 0.4


def test_residual_ic_reports_missing_benchmark() -> None:
    panel, factors, _dates = _beta_proxy_panel()
    scorecard = build_factor_scorecards(
        factor_results=factors,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="SPY",
        horizons=(1,),
        quantiles=5,
    )
    block = scorecard["factors"][0]["horizons"]["1"]

    assert block["residual_ic"]["status"] == "benchmark_missing"
    assert block["residual_ic"]["reason"] == "benchmark_symbol_absent"
    assert block["long_short"]["beta_neutral"]["status"] == "unavailable"


# --------------------------------------------------------------------------------------
# Sleeve marginal contribution hand seals
# --------------------------------------------------------------------------------------


def _four_day_series(left: list[float], right: list[float]) -> tuple[pd.Series, dict[str, float]]:
    dates = pd.date_range("2024-01-01", periods=4, freq="B", tz="UTC")
    sleeve = {str(day.date()): value for day, value in zip(dates, left, strict=True)}
    return pd.Series(right, index=[str(day.date()) for day in dates]), sleeve


def test_marginal_contribution_hand_computed() -> None:
    candidate, sleeve = _four_day_series(
        [0.01, -0.01, 0.01, -0.01], [0.01, 0.01, -0.005, -0.005]
    )
    block = sleeve_marginal_contribution(candidate, sleeve)

    # with = [0.01, 0, 0.0025, -0.0075] -> sharpe = 0.2 * sqrt(252) = 3.17490...
    assert block["marginal_sharpe_delta"] == pytest.approx(0.2 * np.sqrt(252), abs=HAND_SEAL_ABS)
    assert block["sharpe_without"] == 0.0
    assert block["n_shared_days"] == 4
    assert block["status"] == "insufficient_sample_descriptive_only"
    assert block["paired_difference"] is None
    assert block["tradeable_claim"] is False


def test_marginal_contribution_accepts_date_indexed_series() -> None:
    candidate, sleeve_mapping = _four_day_series(
        [0.01, -0.01, 0.01, -0.01], [0.01, 0.01, -0.005, -0.005]
    )
    as_series = sleeve_marginal_contribution(candidate, pd.Series(sleeve_mapping, dtype="float64"))
    as_mapping = sleeve_marginal_contribution(candidate, sleeve_mapping)

    assert as_series["n_shared_days"] == 4
    assert as_series["status"] == as_mapping["status"]
    assert as_series["marginal_sharpe_delta"] == pytest.approx(
        as_mapping["marginal_sharpe_delta"], abs=0.0
    )


def test_marginal_contribution_unavailable_without_sleeve() -> None:
    candidate, _sleeve = _four_day_series([0.01, 0.02, 0.03, 0.04], [0.01, 0.0, 0.01, 0.0])
    block = sleeve_marginal_contribution(candidate, None)
    assert block["status"] == "unavailable"
    assert block["reason"] == "sleeve_returns_not_provided"
    assert block["marginal_sharpe_delta"] is None


def test_marginal_contribution_thin_sample_keeps_point_estimate_only() -> None:
    dates = pd.date_range("2024-01-01", periods=60, freq="B", tz="UTC")
    rng = np.random.default_rng(11)
    sleeve = {
        str(day.date()): float(value)
        for day, value in zip(dates, rng.normal(0, 0.01, 60), strict=True)
    }
    candidate = pd.Series(rng.normal(0, 0.005, 60), index=[str(day.date()) for day in dates])
    block = sleeve_marginal_contribution(candidate, sleeve)

    assert block["status"] == "insufficient_sample_descriptive_only"
    assert block["reason"] == "insufficient_sample_for_inference"
    assert block["marginal_sharpe_delta"] is not None
    assert block["paired_difference"] is None


def test_marginal_contribution_leaves_required_years_null_for_nonpositive_mean() -> None:
    dates = pd.date_range("2024-01-01", periods=130, freq="B", tz="UTC")
    sleeve_values = [0.01 if index % 2 == 0 else -0.01 for index in range(130)]
    sleeve = {str(day.date()): value for day, value in zip(dates, sleeve_values, strict=True)}
    candidate = pd.Series(
        [value - 0.001 for value in sleeve_values],
        index=[str(day.date()) for day in dates],
    )
    block = sleeve_marginal_contribution(candidate, sleeve)

    assert block["status"] == "ready"
    assert block["paired_difference"] is not None
    assert block["paired_difference"]["mean_d"] < 0
    assert block["paired_difference"]["required_years"] is None
    assert block["paired_difference"]["detectable_annualized_delta_sharpe"] is None


# --------------------------------------------------------------------------------------
# Library correlation
# --------------------------------------------------------------------------------------


def test_max_factor_correlation_identifies_planted_peer() -> None:
    dates = pd.date_range("2024-01-01", periods=25, freq="B", tz="UTC")
    symbols = [f"S{index}" for index in range(6)]
    rng = np.random.default_rng(5)
    rows = []
    library_rows = []
    for day in dates:
        for symbol in symbols:
            value = float(rng.normal(0, 1))
            rows.append((symbol, day, value))
            library_rows.append(("peer_monotone", symbol, day, value**3))
            library_rows.append(("peer_noise", symbol, day, float(rng.normal(0, 1))))
    candidate = _factor_frame(rows, factor_id="candidate")
    library = pd.DataFrame(
        {
            "factor_id": [row[0] for row in library_rows],
            "symbol": [row[1] for row in library_rows],
            "signal_ts": [row[2] for row in library_rows],
            "value": [row[3] for row in library_rows],
        }
    )
    panel = _panel_from_opens(
        {symbol: [100.0] * len(dates) for symbol in symbols}, dates
    )
    scorecard = build_factor_scorecards(
        factor_results=candidate,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="SPY",
        horizons=(1,),
        quantiles=3,
        library_factor_results=library,
    )
    block = scorecard["factors"][0]["correlation"]

    assert block["status"] == "ready"
    assert block["max_correlation_factor_id"] == "peer_monotone"
    assert block["max_abs_factor_correlation"] == pytest.approx(1.0, abs=1e-9)
    assert block["n_peers"] == 2
    assert set(scorecard["provenance"]["peer_factor_ids"]) == {"peer_monotone", "peer_noise"}
    assert "advisory" in block["note"]
    assert "gate" not in json.dumps(block)


def test_correlation_block_is_unavailable_without_library() -> None:
    panel, factors, _dates = _ten_symbol_panel()
    scorecard = build_factor_scorecards(
        factor_results=factors,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="SPY",
        horizons=(1,),
        quantiles=5,
    )
    block = scorecard["factors"][0]["correlation"]
    assert block["status"] == "unavailable"
    assert block["reason"] == "library_factor_results_not_provided"


def test_correlation_block_reports_explicit_reason_for_empty_library() -> None:
    panel, factors, _dates = _ten_symbol_panel()
    scorecard = build_factor_scorecards(
        factor_results=factors,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="SPY",
        horizons=(1,),
        quantiles=5,
        library_factor_results=pd.DataFrame(),
    )
    block = scorecard["factors"][0]["correlation"]
    assert block["status"] == "unavailable"
    assert block["reason"] == "library_factor_values_unavailable"
    assert block["max_abs_factor_correlation"] is None


# --------------------------------------------------------------------------------------
# Coverage identity (R-cal-8)
# --------------------------------------------------------------------------------------


def _gap_panel_with_factor() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    dates = pd.date_range("2024-01-01", periods=6, freq="B", tz="UTC")
    aaa = _panel_from_opens({"AAA": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]}, dates)
    bbb = _panel_from_opens({"BBB": [20.0, 21.0, 22.0, 23.0, 24.0, 25.0]}, dates)
    bbb = bbb[bbb["timestamp"] != dates[2]]
    panel = pd.concat([aaa, bbb], ignore_index=True)
    factors = _factor_frame(
        [
            ("AAA", dates[0], 1.0),
            ("AAA", dates[1], 2.0),
            ("AAA", dates[2], 3.0),
            ("AAA", dates[3], 4.0),
            ("AAA", dates[4], 5.0),
            ("AAA", dates[5], 6.0),
            ("BBB", dates[0], 1.0),
            ("BBB", dates[1], float("nan")),
            ("BBB", dates[3], 3.0),
            ("BBB", dates[4], 4.0),
            ("BBB", dates[5], 5.0),
        ]
    )
    return panel, factors, dates


def test_coverage_identity_holds_per_factor_and_horizon() -> None:
    panel, factors, _dates = _gap_panel_with_factor()
    scorecard, artifacts = build_factor_scorecard_bundle(
        factor_results=factors,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="SPY",
        horizons=(1,),
        quantiles=2,
    )
    coverage = scorecard["factors"][0]["horizons"]["1"]["coverage"]

    assert coverage["n_signals"] == 11
    assert coverage["n_valid"] == 5
    assert coverage["excluded_entry_open_missing"] == 2
    assert coverage["excluded_exit_open_missing"] == 3
    assert coverage["excluded_invalid_price"] == 0
    assert coverage["excluded_factor_value_missing"] == 1
    assert coverage["coverage"] == pytest.approx(5 / 11, abs=1e-12)
    assert coverage["status"] == "ready"
    assert coverage["n_signals"] == (
        coverage["n_valid"]
        + coverage["excluded_entry_open_missing"]
        + coverage["excluded_exit_open_missing"]
        + coverage["excluded_invalid_price"]
        + coverage["excluded_factor_value_missing"]
    )
    audit = artifacts["audit"]
    aggregate = audit[(audit["symbol"] == "") & (audit["factor_id"] == "f")]
    assert len(aggregate) == 1
    assert int(aggregate.iloc[0]["n_signals"]) == 11
    assert artifacts["ic_daily"].columns.tolist() == [
        "factor_id",
        "signal_ts",
        "horizon",
        "price_basis",
        "ic",
        "rank_ic",
        "n",
        "residual_ic",
        "residual_rank_ic",
        "residual_n",
    ]


def test_industry_neutral_raises_when_fields_are_supplied() -> None:
    panel, factors, _dates = _ten_symbol_panel()
    with pytest.raises(NotImplementedError, match="industry_neutral_pending_fields"):
        build_factor_scorecards(
            factor_results=factors,
            ohlcv=panel,
            factor_metadata=[],
            benchmark_symbol="SPY",
            horizons=(1,),
            quantiles=5,
            industry_membership={"AAA": "tech"},
        )


def test_scorecard_is_json_sealed_with_schema_blocks() -> None:
    panel, factors, _dates = _ten_symbol_panel()
    scorecard = build_factor_scorecards(
        factor_results=factors,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="SPY",
        horizons=(1,),
        quantiles=5,
    )
    dumped = json.dumps(scorecard, allow_nan=False)
    assert SCORECARD_SCHEMA_VERSION == "factor_scorecard_v1"
    assert scorecard["schema_version"] == SCORECARD_SCHEMA_VERSION
    assert scorecard["stale"] is False
    methodology = scorecard["methodology"]
    assert methodology["forward_return"] == "open_t+1_to_open_t+1+h"
    assert methodology["label_formula"] == "open(t+1+h)/open(t+1)-1"
    assert methodology["calendar"] == "union_observed_no_fill"
    assert methodology["gap_rules"] == "R-cal-1..8"
    assert methodology["nw_lag_rule"].startswith("min(max(h-1")
    assert methodology["evaluation_only"] is True
    assert methodology["tradeable_claim"] is False
    provenance = scorecard["provenance"]
    assert provenance["methodology_version"] == METHODOLOGY_VERSION
    assert provenance["forward_return_schema_version"] == "forward_returns/v2"
    assert len(provenance["input_digest"]) == 64
    assert len(provenance["prices_sha256"]) == 64
    assert len(provenance["source_digest"]) == 64
    assert "factor-eval-2" in dumped


# --------------------------------------------------------------------------------------
# Service: layout, tombstone, staleness
# --------------------------------------------------------------------------------------


def _refresh_args(tmp_path):
    panel, factors, _dates = _ten_symbol_panel()
    return {
        "request": {"provider": "sample", "start": "2024-01-01", "end": "2024-01-05"},
        "output_dir": tmp_path / "factor_scorecards",
        "factor_results": factors,
        "ohlcv": panel,
    }


def _long_panel(days: int = 60, symbols: int = 10, seed: int = 7):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=days, freq="B", tz="UTC")
    names = [f"S{index:02d}" for index in range(symbols)]
    opens = {}
    for name in names:
        price = 100.0
        series = []
        for _ in dates:
            price *= float(1 + rng.normal(0, 0.01))
            series.append(price)
        opens[name] = series
    return _panel_from_opens(opens, dates), dates, names


def test_refresh_injects_registry_default_library_for_single_factor(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    panel, dates, names = _long_panel()
    rng = np.random.default_rng(3)
    candidate = _factor_frame(
        [(name, day, float(rng.normal(0, 1))) for day in dates for name in names],
        factor_id="candidate",
    )

    latest = refresh_factor_scorecards(
        settings,
        request={"provider": "sample", "lookback": 2, "start": "2024-01-01", "end": "2024-06-30"},
        output_dir=tmp_path / "factor_scorecards",
        factor_results=candidate,
        ohlcv=panel,
    )

    block = latest["factors"][0]["correlation"]
    assert block["status"] == "ready"
    assert block["max_abs_factor_correlation"] is not None
    assert block["max_correlation_factor_id"] in set(build_factor_registry().factor_ids())
    assert latest["provenance"]["peer_factor_ids"]
    assert "candidate" not in latest["provenance"]["peer_factor_ids"]


def test_refresh_reports_explicit_reason_when_default_library_unavailable(
    tmp_path, monkeypatch
) -> None:
    import quant_system.factors.scorecard_service as scorecard_service

    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    panel, dates, names = _long_panel()
    rng = np.random.default_rng(4)
    candidate = _factor_frame(
        [(name, day, float(rng.normal(0, 1))) for day in dates for name in names],
        factor_id="candidate",
    )

    def _unavailable(*_args, **_kwargs):
        raise RuntimeError("factor_values_not_computed")

    monkeypatch.setattr(scorecard_service, "compute_factor_pipeline", _unavailable)

    latest = refresh_factor_scorecards(
        settings,
        request={"provider": "sample", "lookback": 2, "start": "2024-01-01", "end": "2024-06-30"},
        output_dir=tmp_path / "factor_scorecards",
        factor_results=candidate,
        ohlcv=panel,
    )

    block = latest["factors"][0]["correlation"]
    assert block["status"] == "unavailable"
    assert block["reason"] == "library_factor_values_unavailable"
    assert latest["provenance"]["peer_factor_ids"] == []


def test_refresh_default_provider_path_survives_multiple_factors(tmp_path, monkeypatch) -> None:
    """The provider default path must not use non-contiguous row labels as positions.

    Regression for the residual-IC block: ``subset`` keeps the labels of the merged
    frame, so once more than one factor row set is present the labels are no longer
    0..n-1 and a positional lookup raises IndexError. This is the path the API/CLI
    use when no explicit frames are supplied.
    """

    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()

    latest = refresh_factor_scorecards(
        settings,
        request={"provider": "sample", "lookback": 3, "start": "2024-01-02", "end": "2024-03-29"},
        output_dir=tmp_path / "factor_scorecards",
    )

    assert len(latest["factors"]) > 1
    for block in latest["factors"]:
        assert block["horizons"], "each factor must carry per-horizon blocks"
        for horizon_block in block["horizons"].values():
            assert horizon_block["ic"]["status"] in {"ready", "unavailable"}
            assert horizon_block["residual_ic"]["status"] in {"ready", "unavailable"}
            coverage = horizon_block["coverage"]
            assert coverage["status"] in {"ready", "unavailable"}
            if coverage["status"] == "ready":
                assert coverage["n_signals"] == (
                    coverage["n_valid"]
                    + coverage["excluded_entry_open_missing"]
                    + coverage["excluded_exit_open_missing"]
                    + coverage["excluded_invalid_price"]
                    + coverage["excluded_factor_value_missing"]
                )
        assert block["correlation"]["status"] in {"ready", "unavailable"}


def test_refresh_writes_layout_and_tombstone(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()

    latest = refresh_factor_scorecards(settings, **_refresh_args(tmp_path))

    base = tmp_path / "factor_scorecards"
    run_dir = Path(latest["run"]["run_dir"])
    assert run_dir.parent == base / "runs"
    assert (base / "latest.json").exists()
    for name in ("request.json", "scorecard.json"):
        assert (run_dir / name).exists()
    for name in (
        "ic_daily",
        "quantile_daily",
        "long_short_daily",
        "correlation_daily",
        "audit",
    ):
        assert (run_dir / f"{name}.parquet").exists()
    stored = json.loads((run_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert stored["schema_version"] == SCORECARD_SCHEMA_VERSION
    assert latest["run"]["request"]["provider"] == "sample"

    rows = TrialsLedger(Path(settings.data.data_dir) / "trials").list()
    assert len(rows) == 1
    assert rows[0].kind == "factor_scorecard"
    assert rows[0].metadata["skipped"] is True
    assert rows[0].metadata["skip_reason"] == "evaluation_dashboard_not_dsr_family"
    assert rows[0].metadata["request"]["provider"] == "sample"


def test_read_flags_stale_and_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    output_dir = tmp_path / "factor_scorecards"

    missing = read_factor_scorecards(settings, output_dir=output_dir)
    assert missing["status"] == "unavailable"
    assert missing["reason"] == "no_scorecard_run"

    refresh_factor_scorecards(settings, **_refresh_args(tmp_path))
    fresh = read_factor_scorecards(settings, output_dir=output_dir)
    assert fresh["stale"] is False
    assert fresh["schema_version"] == SCORECARD_SCHEMA_VERSION

    latest_path = output_dir / "latest.json"
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    payload["provenance"]["source_digest"] = "0" * 64
    latest_path.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
    # The refresh recorded a version-2 provenance, which staleness compares on the
    # extended digest; the legacy field only governs runs written before the marker.
    assert read_factor_scorecards(settings, output_dir=output_dir)["stale"] is False

    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    payload["provenance"]["source_digest_extended"] = "0" * 64
    latest_path.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
    assert read_factor_scorecards(settings, output_dir=output_dir)["stale"] is True


def test_new_provenance_records_the_digest_version_and_the_extended_digest() -> None:
    panel, factors, _dates = _ten_symbol_panel()
    scorecard = build_factor_scorecards(
        factor_results=factors,
        ohlcv=panel,
        factor_metadata=[],
        benchmark_symbol="SPY",
        horizons=(1,),
        quantiles=5,
    )
    provenance = scorecard["provenance"]
    assert provenance["source_digest_version"] == SOURCE_DIGEST_VERSION == 2
    assert provenance["source_digest"] == current_source_digest()
    assert provenance["source_digest_extended"] != provenance["source_digest"]
    assert len(provenance["source_digest_extended"]) == 64


def test_staleness_follows_the_recorded_digest_version(monkeypatch) -> None:
    from quant_system.factors import scorecard as scorecard_module

    legacy = {"source_digest": current_source_digest()}
    assert scorecard_module.source_digest_version(legacy) == 1
    assert scorecard_module.provenance_is_stale(legacy) is False
    assert scorecard_module.provenance_is_stale({"source_digest": "0" * 64}) is True

    current = {
        "source_digest": current_source_digest(),
        "source_digest_version": SOURCE_DIGEST_VERSION,
        "source_digest_extended": scorecard_module._source_digest(SOURCE_DIGEST_VERSION),
    }
    assert scorecard_module.provenance_is_stale(current) is False

    wide_factor_set = (
        Path(scorecard_module._REPO_ROOT) / "src/quant_system/research/wide_factor_set.py"
    )
    read_source_bytes = scorecard_module._read_source_bytes
    monkeypatch.setattr(
        scorecard_module,
        "_read_source_bytes",
        lambda path: b"changed" if Path(path) == wide_factor_set else read_source_bytes(path),
    )
    assert scorecard_module.provenance_is_stale(current) is True
    assert scorecard_module._source_digest(1) == legacy["source_digest"]
    assert scorecard_module.provenance_is_stale(legacy) is False


def test_unknown_or_missing_digest_version_cannot_be_certified() -> None:
    from quant_system.factors import scorecard as scorecard_module

    assert scorecard_module.provenance_is_stale(None) is True
    assert scorecard_module.provenance_is_stale({}) is True
    assert (
        scorecard_module.provenance_is_stale(
            {"source_digest_version": 3, "source_digest_extended": "0" * 64}
        )
        is True
    )


def test_absent_wide_sources_fall_back_to_the_version_1_record(monkeypatch) -> None:
    from quant_system.factors import scorecard as scorecard_module

    legacy_pair = scorecard_module._SOURCE_DIGEST_VERSION_FILES[1]
    monkeypatch.setattr(
        scorecard_module,
        "_SOURCE_DIGEST_VERSION_FILES",
        {1: legacy_pair, 2: (*legacy_pair, Path("absent/wide_factor_set.py"))},
    )
    recorded = scorecard_module.recorded_source_digests()
    assert set(recorded) == {"source_digest"}
    assert recorded["source_digest"] == current_source_digest()
    assert scorecard_module.provenance_is_stale(recorded) is False


# --------------------------------------------------------------------------------------
# Pipeline / lab wiring
# --------------------------------------------------------------------------------------


def test_run_factor_research_persists_open_basis_ic(tmp_path) -> None:
    from quant_system.factors.pipeline import run_sample_factor_research

    result = run_sample_factor_research(
        symbols=["SPY", "AAPL"],
        start="2024-01-02",
        end="2024-03-29",
        output_dir=tmp_path,
    )
    ic_frame = pd.read_parquet(Path(result.ic_path))
    assert (ic_frame["price_basis"] == "open_to_open").all()
    assert (ic_frame["horizon"] == 1).all()
    quantiles = pd.read_parquet(Path(result.quantile_returns_path))
    assert (quantiles["price_basis"] == "open_to_open").all()


def test_factor_lab_cache_key_carries_methodology(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    from quant_system.factors.lab import build_factor_lab_dashboard

    kwargs = {
        "settings": settings,
        "output_dir": tmp_path / "out",
        "provider": "sample",
        "universe_id": "etf",
        "symbol": "QQQ",
        "start": "2024-01-02",
        "end": "2024-03-29",
        "lookback": 3,
    }
    payload = build_factor_lab_dashboard(**kwargs)
    assert payload["cache"]["status"] == "recomputed"
    assert payload["cache"]["key"]["methodology"] == METHODOLOGY_VERSION

    cache_path = tmp_path / "out" / "factor_lab" / "factor_lab_cache.json"
    legacy = json.loads(cache_path.read_text(encoding="utf-8"))
    legacy["cache"]["key"].pop("methodology")
    cache_path.write_text(json.dumps(legacy), encoding="utf-8")

    recomputed = build_factor_lab_dashboard(**kwargs)
    assert recomputed["cache"]["status"] == "recomputed"
