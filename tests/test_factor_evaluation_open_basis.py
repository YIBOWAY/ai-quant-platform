"""Open-to-open forward-return labels: qlib alignment, gap rules, NW inference.

Hand-computed vectors are sealed to exact values; every number here was recomputed by
hand from the definitions in the T2.1 design before being frozen.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_system.factors.evaluation import (
    FORWARD_RETURN_SCHEMA_VERSION,
    METHODOLOGY_VERSION,
    build_price_frame,
    calculate_ic_decay,
    calculate_information_coefficients,
    forward_return_matrix,
    make_forward_returns,
    make_forward_returns_audited,
    make_forward_returns_multi,
    newey_west_lag_rule,
    newey_west_stats,
    newey_west_t_statistic,
    prepare_evaluation_frames,
    summarize_ic_series,
)

EXPECTED_COLUMNS = [
    "symbol",
    "signal_ts",
    "entry_ts",
    "return_end_ts",
    "forward_return",
    "price_basis",
    "horizon",
]


def _panel(opens: dict[str, list[float]], *, days: int, close_offset: float = 1.0) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days, freq="B", tz="UTC")
    rows = []
    for symbol, values in opens.items():
        for index, open_price in enumerate(values):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": dates[index],
                    "open": float(open_price),
                    "high": float(open_price) + 2.0,
                    "low": float(open_price) - 2.0,
                    "close": float(open_price) + close_offset,
                    "volume": 1_000.0,
                }
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# qlib alignment, hand-computed
# --------------------------------------------------------------------------------------


def _five_day_panel() -> pd.DataFrame:
    return _panel(
        {"AAA": [10.0, 11.0, 12.0, 13.0, 14.0], "BBB": [20.0, 19.0, 18.0, 17.0, 16.0]},
        days=5,
    )


def test_open_basis_labels_match_hand_computed_values() -> None:
    panel = _five_day_panel()
    dates = pd.date_range("2024-01-01", periods=5, freq="B", tz="UTC")
    labels = make_forward_returns(panel, horizon=1, price_basis="open_to_open")

    assert list(labels.columns) == EXPECTED_COLUMNS
    assert labels.groupby("symbol").size().to_dict() == {"AAA": 3, "BBB": 3}

    aaa = labels[labels["symbol"] == "AAA"].reset_index(drop=True)
    assert aaa["forward_return"].tolist() == pytest.approx(
        [12 / 11 - 1, 13 / 12 - 1, 14 / 13 - 1], abs=1e-12
    )
    assert aaa["signal_ts"].tolist() == list(dates[:3])
    assert aaa["entry_ts"].tolist() == list(dates[1:4])
    assert aaa["return_end_ts"].tolist() == list(dates[2:5])

    bbb = labels[labels["symbol"] == "BBB"].reset_index(drop=True)
    assert bbb["forward_return"].tolist() == pytest.approx(
        [18 / 19 - 1, 17 / 18 - 1, 16 / 17 - 1], abs=1e-12
    )
    # The two trailing signal days have no mature label.
    assert sorted(aaa["forward_return"]) == pytest.approx(
        sorted([0.0909090909090909, 0.0833333333333333, 0.0769230769230769]), abs=1e-12
    )
    assert sorted(bbb["forward_return"]) == pytest.approx(
        sorted([-0.0526315789473684, -0.0555555555555556, -0.0588235294117647]), abs=1e-12
    )
    assert (labels["price_basis"] == "open_to_open").all()
    assert (labels["horizon"] == 1).all()
    assert FORWARD_RETURN_SCHEMA_VERSION == "forward_returns/v2"
    assert METHODOLOGY_VERSION == "factor-eval-2"


def test_open_basis_matches_qlib_shift_formula_in_place() -> None:
    panel = _five_day_panel()
    opens = panel.pivot(index="timestamp", columns="symbol", values="open").sort_index()
    qlib_labels = (opens.shift(-2) / opens.shift(-1) - 1).stack(future_stack=True).dropna()

    ours = make_forward_returns(panel, horizon=1, price_basis="open_to_open")
    lookup = ours.set_index(["signal_ts", "symbol"])["forward_return"]
    for (date, symbol), value in qlib_labels.items():
        assert lookup.loc[(date, symbol)] == pytest.approx(value, abs=1e-12)
    assert len(lookup) == len(qlib_labels)


def test_open_basis_labels_match_qlib_evaluation_anchor() -> None:
    from quant_system.research import qlib_evaluation

    panel = _five_day_panel()
    prices = panel.loc[:, ["timestamp", "symbol", "open", "close"]].copy()
    prices["provider"] = "futu"
    prices["price_adjustment"] = "qfq"
    dates = pd.date_range("2024-01-01", periods=5, freq="B", tz="UTC").tz_localize(None)
    index = pd.MultiIndex.from_product(
        [dates, ["AAA", "BBB"]], names=["datetime", "instrument"]
    )
    features = pd.DataFrame(
        {"momentum": 1.0, "volatility": 2.0, "liquidity": 3.0}, index=index
    )
    _, _, labels, _ = qlib_evaluation._inputs(prices, features)

    ours = make_forward_returns(panel, horizon=1, price_basis="open_to_open")
    lookup = ours.set_index(["signal_ts", "symbol"])["forward_return"]
    assert len(labels) == len(ours)
    for (datetime, instrument), value in labels.items():
        assert lookup.loc[(datetime.tz_localize("UTC"), instrument)] == pytest.approx(
            value, abs=1e-12
        )


# --------------------------------------------------------------------------------------
# Newey-West, hand-computed
# --------------------------------------------------------------------------------------


def test_newey_west_hand_computed_vector() -> None:
    # x = [0.02, 0, 0.02, 0]; lag 1 -> gamma0 = 1e-4, gamma1 = -7.5e-5, LRV = 2.5e-5,
    # t = 0.01 / sqrt(2.5e-5 / 4) = 4.0 exactly.
    stats = newey_west_stats([0.02, 0.0, 0.02, 0.0], lag=1, min_observations=0, min_pairs=0)
    assert stats["gamma_0"] == pytest.approx(1e-4, abs=1e-18)
    assert stats["lrv"] == pytest.approx(2.5e-5, abs=1e-18)
    assert stats["t_stat"] == pytest.approx(4.0, abs=1e-12)
    assert newey_west_t_statistic(
        [0.02, 0.0, 0.02, 0.0], lag=1, min_observations=0, min_pairs=0
    ) == pytest.approx(4.0, abs=1e-12)


def test_newey_west_lag_rule_reference_values() -> None:
    assert newey_west_lag_rule(126) == 4
    assert newey_west_lag_rule(250) == 4
    assert newey_west_lag_rule(252) == 4
    assert newey_west_lag_rule(504) == 5
    assert newey_west_lag_rule(756) == 6
    assert newey_west_lag_rule(1260) == 7
    # Overlap floor: h=5 -> at least 4; h=21 -> at least 20; capped at T-1.
    assert newey_west_lag_rule(10, horizon=5) >= 4
    assert newey_west_lag_rule(100, horizon=21) >= 20
    assert newey_west_lag_rule(3, horizon=21) == 2


def test_newey_west_pairwise_complete_with_missing_days() -> None:
    # Inserting a NaN day must reproduce the pairwise-complete hand calculation:
    # T=4, mu=0.01, gamma0=1e-4, gamma1=-5e-5, LRV=5e-5, t=0.01/sqrt(1.25e-5)=2.82842712...
    stats = newey_west_stats([0.02, float("nan"), 0.0, 0.02, 0.0], lag=1, min_observations=0)
    assert stats["n_obs"] == 4
    assert stats["pair_counts"] == {1: 2}
    assert stats["lrv"] == pytest.approx(5e-5, abs=1e-18)
    assert stats["t_stat"] == pytest.approx(float(np.sqrt(8.0)), abs=1e-9)


def test_newey_west_declines_constant_and_short_series() -> None:
    with pytest.warns(UserWarning):
        stats = newey_west_stats([0.0] * 80, lag=4, horizon=5)
    assert stats["t_stat"] is None
    assert stats["reason"] == "nonpositive_lrv"

    short = newey_west_stats([0.01] * 10, lag=1)
    assert short["t_stat"] is None
    assert short["reason"] == "insufficient_observations"

    guarded = newey_west_stats([0.01] * 80, lag=4, horizon=5, min_pairs=1000)
    assert guarded["t_stat"] is None
    assert guarded["reason"] == "insufficient_pairs_at_required_lag"


def test_newey_west_shrinks_under_overlapping_windows() -> None:
    rng = np.random.default_rng(7)
    shocks = rng.normal(0.0, 0.01, 300)
    window = 5
    overlapping = pd.Series(shocks).rolling(window).mean().dropna().to_numpy()
    n = len(overlapping)
    naive_t = float(overlapping.mean() / (overlapping.std(ddof=1) / np.sqrt(n)))
    lag = newey_west_lag_rule(n, horizon=window)
    assert lag >= window - 1
    nw_t = newey_west_t_statistic(overlapping, lag=lag, horizon=window)
    assert nw_t is not None
    # Positive overlap autocorrelation inflates the long-run variance, so the HAC
    # t statistic is smaller in magnitude than the i.i.d. one (the sample mean is
    # negative here, hence the absolute values).
    assert abs(nw_t) < abs(naive_t)


# --------------------------------------------------------------------------------------
# Gap / termination semantics
# --------------------------------------------------------------------------------------


def _gap_panel() -> pd.DataFrame:
    panel = _panel({"AAA": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]}, days=6)
    bbb = _panel({"BBB": [20.0, 21.0, 22.0, 23.0, 24.0, 25.0]}, days=6)
    dates = pd.date_range("2024-01-01", periods=6, freq="B", tz="UTC")
    # Drop BBB's third session: the missing session must not become a later entry price.
    bbb = bbb[bbb["timestamp"] != dates[2]]
    return pd.concat([panel, bbb], ignore_index=True)


def test_missing_session_does_not_slide_to_a_later_entry_price() -> None:
    labels = make_forward_returns(_gap_panel(), horizon=1, price_basis="open_to_open")
    dates = pd.date_range("2024-01-01", periods=6, freq="B", tz="UTC")

    aaa = labels[labels["symbol"] == "AAA"]
    assert aaa["signal_ts"].tolist() == list(dates[:4])
    assert aaa["forward_return"].tolist() == pytest.approx(
        [12 / 11 - 1, 13 / 12 - 1, 14 / 13 - 1, 15 / 14 - 1], abs=1e-12
    )

    # BBB: only the day whose entry *and* exit sessions are both observed survives.
    # A per-symbol row shift would instead bridge the gap and emit 22/21 - 1 here.
    bbb = labels[labels["symbol"] == "BBB"]
    assert bbb["signal_ts"].tolist() == [dates[3]]
    assert bbb["forward_return"].tolist() == pytest.approx([25 / 24 - 1], abs=1e-12)

    audited, audit = make_forward_returns_audited(_gap_panel(), horizon=1)
    bbb_audit = audited[audited["symbol"] == "BBB"].reset_index(drop=True)
    reasons = dict(zip(bbb_audit["signal_ts"], bbb_audit["exclusion_reason"], strict=True))
    assert reasons[dates[0]] == "exit_open_missing"
    assert reasons[dates[1]] == "entry_open_missing"
    assert reasons[dates[3]] is None
    assert reasons[dates[4]] == "exit_open_missing"
    assert audit["excluded_entry_open_missing"] == 3
    assert audit["excluded_exit_open_missing"] == 3
    assert audit["n_signal_rows"] == 11
    assert audit["n_valid"] == 5
    assert audit["excluded_terminal_exit"] == {}


def test_terminated_symbol_uses_last_session_and_counts_terminal_exits() -> None:
    complete = _panel({"AAA": [10.0] * 8, "BBB": [20.0] * 8}, days=8)
    ccc = _panel({"CCC": [30.0, 31.0, 32.0, 33.0, 34.0]}, days=8)
    panel = pd.concat([complete, ccc], ignore_index=True)
    dates = pd.date_range("2024-01-01", periods=8, freq="B", tz="UTC")

    audited, audit = make_forward_returns_audited(panel, horizon=1)
    ccc_rows = audited[audited["symbol"] == "CCC"].reset_index(drop=True)
    by_date = dict(zip(ccc_rows["signal_ts"], ccc_rows["exclusion_reason"], strict=True))

    # The final observed session is a real, usable exit price when it is exactly t+1+h.
    assert by_date[dates[2]] is None
    assert ccc_rows.loc[ccc_rows["signal_ts"] == dates[2], "forward_return"].iloc[0] == (
        pytest.approx(34 / 33 - 1, abs=1e-12)
    )
    assert by_date[dates[3]] == "exit_open_missing"
    # The last observed session has no next session to enter at, so the entry leg is
    # the one that breaks; either way the label needs a session past the series end.
    assert by_date[dates[4]] == "entry_open_missing"
    assert audit["excluded_terminal_exit"] == {"CCC": 2}
    assert audit["n_signal_rows"] == 21
    assert audit["n_valid"] == 15
    assert audit["excluded_entry_open_missing"] == 3
    assert audit["excluded_exit_open_missing"] == 3
    assert audit["excluded_invalid_price"] == 0
    # Price-side audit identity: every observed signal row is classified exactly once.
    assert audit["n_signal_rows"] == (
        audit["n_valid"]
        + audit["excluded_entry_open_missing"]
        + audit["excluded_exit_open_missing"]
        + audit["excluded_invalid_price"]
    )


def test_duplicate_price_rows_are_rejected() -> None:
    panel = _five_day_panel()
    duplicated = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="evaluation_duplicate_price_rows"):
        build_price_frame(duplicated)


def test_invalid_prices_become_nan_and_are_counted() -> None:
    symbols = {f"S{index:02d}": [100.0] * 10 for index in range(11)}
    panel = _panel(symbols, days=10)
    # Break S00's *entry* session (day 1): the row exists but the price is unusable.
    panel.loc[1, "open"] = 0.0
    prices = build_price_frame(panel)
    assert prices.invalid_cells == 1
    assert prices.observed_mask.iloc[1, 0]
    assert prices.invalid_mask.iloc[1, 0]
    assert np.isnan(prices.matrix.iloc[1, 0])

    audited, audit = make_forward_returns_audited(panel, horizon=1)
    assert audit["invalid_cells"] == 1
    assert audit["excluded_invalid_price"] == 1
    broken = audited[(audited["symbol"] == "S00") & (audited["signal_ts"] == prices.calendar[0])]
    assert broken["exclusion_reason"].iloc[0] == "invalid_price"
    # A signal day's own open is not part of an open-to-open label, so day 1 itself
    # still produces a mature return.
    intact = audited[(audited["symbol"] == "S00") & (audited["signal_ts"] == prices.calendar[1])]
    assert intact["exclusion_reason"].iloc[0] is None
    assert intact["forward_return"].notna().all()


def test_excessive_invalid_prices_raise() -> None:
    symbols = {f"S{index:02d}": [100.0] * 10 for index in range(11)}
    panel = _panel(symbols, days=10)
    panel.loc[0, "open"] = 0.0
    panel.loc[1, "open"] = -1.0
    with pytest.raises(ValueError, match="evaluation_excessive_invalid_prices"):
        build_price_frame(panel)


# --------------------------------------------------------------------------------------
# Multi-horizon consistency and boundaries
# --------------------------------------------------------------------------------------


def test_multi_horizon_matches_single_shot_bitwise() -> None:
    panel = _panel({"AAA": [10.0 + index for index in range(12)]}, days=12)
    panel = pd.concat(
        [panel, _panel({"BBB": [20.0 + index for index in range(12)]}, days=12)],
        ignore_index=True,
    )
    multi = make_forward_returns_multi(panel, horizons=(1, 5, 21))
    for horizon, frame in multi.items():
        single = make_forward_returns(panel, horizon=horizon)
        pd.testing.assert_frame_equal(frame, single)
    assert multi[21].empty


def test_prepare_frames_feed_ic_consistently() -> None:
    panel = _five_day_panel()
    factor_results = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"] * 4,
            "signal_ts": [
                date
                for date in pd.date_range("2024-01-01", periods=4, freq="B", tz="UTC")
                for _ in range(2)
            ],
            "factor_id": ["f"] * 8,
            "value": [1.0, 4.0, 2.0, 3.0, 3.0, 2.0, 4.0, 1.0],
        }
    )
    prepared = prepare_evaluation_frames(factor_results, panel, horizons=(1,))
    direct = calculate_information_coefficients(factor_results, panel, horizon=1)
    manual = []
    for signal_ts, group in prepared[1].groupby("signal_ts", sort=True):
        clean = group.dropna(subset=["value", "forward_return"])
        manual.append((signal_ts, clean["value"].corr(clean["forward_return"])))
    assert [row["signal_ts"] for row in direct.to_dict("records")] == [
        signal_ts for signal_ts, _ in manual
    ]
    for row, (_, value) in zip(direct.to_dict("records"), manual, strict=True):
        if pd.isna(value):
            assert pd.isna(row["ic"])
        else:
            assert row["ic"] == pytest.approx(value, abs=1e-15)


def test_horizon_beyond_history_returns_empty_frame() -> None:
    panel = _five_day_panel()
    labels = make_forward_returns(panel, horizon=10)
    assert labels.empty
    assert list(labels.columns) == EXPECTED_COLUMNS


def test_single_symbol_day_keeps_nan_ic_row() -> None:
    panel = _panel({"AAA": [10.0, 11.0, 12.0]}, days=3)
    factor_results = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "signal_ts": pd.date_range("2024-01-01", periods=2, freq="B", tz="UTC"),
            "factor_id": ["f", "f"],
            "value": [1.0, 2.0],
        }
    )
    ic = calculate_information_coefficients(factor_results, panel, horizon=1)
    # Day 0 has a single comparable symbol (NaN IC, n=1); day 1 has no mature label
    # because its exit session falls past the panel (n=0).
    assert len(ic) == 2
    assert ic["ic"].isna().all()
    assert ic["rank_ic"].isna().all()
    assert ic["n"].tolist() == [1, 0]


def test_all_nan_factor_values_produce_zero_sample_rows() -> None:
    panel = _five_day_panel()
    factor_results = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "signal_ts": [pd.Timestamp("2024-01-01", tz="UTC")] * 2,
            "factor_id": ["f", "f"],
            "value": [float("nan"), float("nan")],
        }
    )
    ic = calculate_information_coefficients(factor_results, panel, horizon=1)
    assert ic.loc[0, "n"] == 0
    assert np.isnan(ic.loc[0, "ic"])
    assert (ic["price_basis"] == "open_to_open").all()
    assert (ic["horizon"] == 1).all()


def test_duplicate_factor_rows_are_rejected() -> None:
    panel = _five_day_panel()
    row = {
        "symbol": "AAA",
        "signal_ts": pd.Timestamp("2024-01-01", tz="UTC"),
        "factor_id": "f",
        "value": 1.0,
    }
    factor_results = pd.DataFrame([row, row])
    with pytest.raises(ValueError, match="evaluation_duplicate_factor_rows"):
        prepare_evaluation_frames(factor_results, panel, horizons=(1,))


# --------------------------------------------------------------------------------------
# ic_decay regression fixes
# --------------------------------------------------------------------------------------


def test_ic_decay_accepts_frames_without_timestamp_column() -> None:
    panel = _five_day_panel()
    factor_results = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "AAA", "BBB"],
            "signal_ts": [
                pd.Timestamp("2024-01-01", tz="UTC"),
                pd.Timestamp("2024-01-01", tz="UTC"),
                pd.Timestamp("2024-01-02", tz="UTC"),
                pd.Timestamp("2024-01-02", tz="UTC"),
            ],
            "factor_id": ["f"] * 4,
            "value": [1.0, 2.0, 3.0, 4.0],
        }
    )
    decay = calculate_ic_decay(factor_results, panel, horizons=(1,))
    assert [row["horizon"] for row in decay] == [1]
    assert decay[0]["n"] == 4


def test_ic_decay_normalizes_lowercase_symbols() -> None:
    panel = _five_day_panel()
    factor_results = pd.DataFrame(
        {
            "symbol": ["aaa", "bbb", "aaa", "bbb"],
            "signal_ts": [
                pd.Timestamp("2024-01-01", tz="UTC"),
                pd.Timestamp("2024-01-01", tz="UTC"),
                pd.Timestamp("2024-01-02", tz="UTC"),
                pd.Timestamp("2024-01-02", tz="UTC"),
            ],
            "factor_id": ["f"] * 4,
            "value": [1.0, 2.0, 3.0, 4.0],
        }
    )
    decay = calculate_ic_decay(factor_results, panel, horizons=(1,))
    assert decay[0]["n"] == 4
    assert decay[0]["rank_ic"] is not None


def test_forward_return_matrix_matches_row_level_helper() -> None:
    panel = _five_day_panel()
    prices = build_price_frame(panel)
    wide = forward_return_matrix(prices, 1)
    audited, _ = make_forward_returns_audited(panel, horizon=1)
    lookup = audited.set_index(["signal_ts", "symbol"])["forward_return"]
    for (date, symbol), value in wide.stack(future_stack=True).dropna().items():
        assert lookup.loc[(date, symbol)] == pytest.approx(value, abs=1e-15)


def test_summarize_ic_series_reports_descriptive_and_formal_statistics() -> None:
    rng = np.random.default_rng(3)
    values = rng.normal(0.02, 0.05, 300)
    frame = pd.DataFrame(
        {
            "factor_id": ["f"] * 300,
            "signal_ts": pd.date_range("2020-01-01", periods=300, freq="B", tz="UTC"),
            "ic": values,
            "rank_ic": values * 0.9,
        }
    )
    summary = summarize_ic_series(frame, horizon=1)
    assert summary["n_days"] == 300
    assert summary["ic_mean"] == pytest.approx(float(values.mean()), abs=1e-15)
    assert summary["nw_t"] is not None
    assert summary["nw_lag"] == newey_west_lag_rule(300, horizon=1)
    assert summary["reason"] is None
