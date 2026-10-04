"""Sealed input/order/report tests; native Qlib smoke is a separate explicit run."""

import numpy as np
import pandas as pd
import pytest

from quant_system.research.definition_qlib_replay import (
    ONE_WAY_COST,
    normalize_qlib_report,
    plan_open_orders,
    prepare_replay,
)


def _inputs():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    prices = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp(day, tz="UTC"),
                "symbol": symbol,
                "open": 10.0,
                "close": 11.0,
                "high": 12.0,
                "low": 9.0,
                "volume": 1000,
                "provider": "futu",
                "price_adjustment": "qfq",
            }
            for day in dates
            for symbol in ("AAA", "SPY")
        ]
    )
    result = {
        "status": "available",
        "definition": {"symbols": ["AAA"], "benchmark_symbol": "SPY", "initial_cash": 100_000},
        "start": dates[0],
        "end": dates[-1],
        "curve": [{"date": day, "equity": 100_000} for day in dates],
        "signals": [
            {"trade_date": dates[0], "targets": {"AAA": 1}},
            {"trade_date": dates[1], "targets": None},
            {"trade_date": dates[2], "targets": {}},
        ],
    }
    return prices, result


def test_replay_preserves_none_cash_exit_and_explicit_evaluation_capital():
    prices, result = _inputs()
    result["evaluation_initial_cash"] = 10_000
    prepared = prepare_replay(prices, result)
    assert prepared["initial_cash"] == 10_000
    assert prepared["targets"]["2026-01-05"] is None
    assert prepared["targets"]["2026-01-06"] == {}


@pytest.mark.parametrize(
    "change,error",
    [
        (lambda p, r: r.update(end="2026-01-05"), "platform_period_mismatch"),
        (lambda p, r: r["signals"][0].update(trade_date="2026-01-03"), "signal_date_mismatch"),
        (lambda p, r: r["signals"][0].update(targets={"MISSING": 1}), "target_universe_mismatch"),
        (lambda p, r: r["signals"][0].update(targets={"AAA": 1.1}), "leverage_not_supported"),
        (lambda p, r: r["signals"][0].update(targets={"AAA": float("nan")}), "invalid_weights"),
        (
            lambda p, r: r["definition"].update(whole_share_orders=True),
            "fractional_shares_required",
        ),
    ],
)
def test_invalid_input_fails_before_qlib(change, error):
    prices, result = _inputs()
    change(prices, result)
    with pytest.raises(ValueError, match=error):
        prepare_replay(prices, result)


def test_missing_benchmark_session_and_duplicate_quotes_are_not_filled():
    prices, result = _inputs()
    with pytest.raises(ValueError, match="snapshot_calendar_mismatch"):
        prepare_replay(prices.drop(index=3), result)
    with pytest.raises(ValueError, match="duplicate_prices"):
        prepare_replay(pd.concat([prices, prices.iloc[:1]]), result)


def test_missing_open_cannot_be_substituted_with_a_valid_close():
    prices, result = _inputs()
    prices.loc[0, "open"] = np.nan
    assert prices.loc[0, "close"] == 11
    with pytest.raises(ValueError, match="invalid_target_open:2026-01-02:AAA"):
        prepare_replay(prices, result)
    with pytest.raises(ValueError, match="missing_target_quote"):
        prepare_replay(prices.drop(index=0), result)


def test_open_nav_sizing_sells_first_and_costs_limit_only_the_last_buy():
    orders = plan_open_orders(
        holdings={"AAA": 10}, cash=0, opens={"AAA": 20, "BBB": 10}, targets={"BBB": 1}
    )
    assert [(o["symbol"], o["side"]) for o in orders] == [("AAA", "sell"), ("BBB", "buy")]
    assert orders[0]["quantity"] == 10
    assert orders[1]["quantity"] == pytest.approx(20 * (1 - ONE_WAY_COST) / (1 + ONE_WAY_COST))
    purchases = plan_open_orders(
        holdings={}, cash=100, opens={"AAA": 10, "BBB": 10}, targets={"AAA": 0.5, "BBB": 0.5}
    )
    assert purchases[0]["quantity"] == 5
    assert purchases[1]["quantity"] < 5


def test_hold_and_liquidate_remain_distinct_and_min_notional_is_respected():
    args = dict(holdings={"AAA": 10}, cash=0, opens={"AAA": 10})
    assert plan_open_orders(**args, targets=None) == []
    assert plan_open_orders(**args, targets={}) == [
        {"symbol": "AAA", "side": "sell", "quantity": 10}
    ]
    assert plan_open_orders(**args, targets={"AAA": 0.95}, min_order_value=6) == []
    with pytest.raises(ValueError, match="missing_open"):
        plan_open_orders(**{**args, "opens": {}}, targets={})


def test_report_requires_every_date_and_finite_real_returns():
    prices, result = _inputs()
    prepared = prepare_replay(prices, result)
    report = pd.DataFrame(
        {
            "account": [100_000, 101_000, 99_000],
            "cash": [0, 0, 99_000],
            "return": [0, 0.01, 99_000 / 101_000 - 1],
            "cost": [0, 0, 0],
        },
        index=pd.to_datetime(prepared["dates"]),
    )

    class Position:
        def calculate_value(self):
            return 99_000

        def get_cash(self):
            return 99_000

        def get_stock_weight_dict(self, only_stock=False):
            return {}

    positions = {day: Position() for day in report.index}
    output = normalize_qlib_report(report, positions, prepared)
    assert output["return_dates"] == prepared["dates"]
    assert output["terminal_nav"] == 99_000 and output["terminal_nav_unit"] == "USD"
    assert output["daily_returns"][0] == 0
    with pytest.raises(ValueError, match="return_calendar_mismatch"):
        normalize_qlib_report(report.iloc[:-1], positions, prepared)
    report.loc[report.index[0], "return"] = np.nan
    with pytest.raises(ValueError, match="nonfinite_report"):
        normalize_qlib_report(report, positions, prepared)
