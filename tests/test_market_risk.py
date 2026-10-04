from datetime import UTC, date, datetime

import pandas as pd
import pytest

from quant_system.factors.market_cross_section import _last_completed_us_session
from quant_system.factors.market_risk import build_market_risk


def _risk(*, last=110.0, periods=260, vix=None, vix3m=None, expected=date(2026, 9, 4)):
    prices = pd.Series(
        [100.0] * (periods - 1) + [last], index=pd.bdate_range(end="2026-09-04", periods=periods)
    )
    return build_market_risk(
        {"SPY": prices, "QQQ": prices},
        expected_session=expected,
        price_source="futu_cache",
        daily_vix=vix,
        daily_vix3m=vix3m,
    )


def _series(values, dates=("2026-09-03", "2026-09-04")):
    return pd.Series(values, index=pd.to_datetime(dates))


def _find(result, key):
    return next(item for item in result["observations"] if item["key"] == key)


def test_complete_fresh_observations_show_raw_values_and_normal_not_probability():
    risk = _risk(vix=_series([15, 16]), vix3m=_series([17, 18]))
    assert risk["status"] == "normal"
    assert risk["attention_count"] == risk["unavailable_count"] == 0
    assert _find(risk, "trend_200d")["value"] == pytest.approx((110 / 100.05 - 1) * 100, abs=0.0001)
    assert _find(risk, "drawdown_252d")["value"] == 0
    assert _find(risk, "vix_term")["value"] == pytest.approx(16 / 18, abs=0.0001)
    assert _find(risk, "vix_level")["threshold"] == 30
    assert _find(risk, "vix_level")["as_of"] == "2026-09-04"
    assert "probability" not in risk and "score" not in risk


def test_large_negative_move_is_pressure_and_positive_extension_is_only_background():
    negative = _risk(last=70, vix=_series([15, 16]), vix3m=_series([17, 18]))
    assert negative["status"] == "attention"
    assert negative["attention_count"] == 4
    assert _find(negative, "trend_200d")["reason"] == "below_200dma"
    assert _find(negative, "drawdown_252d")["value"] == -30
    positive = _risk(last=130, vix=_series([15, 16]), vix3m=_series([17, 18]))
    assert _find(positive, "trend_200d")["reason"] == "extended_above_200dma"
    assert positive["attention_count"] == 0


@pytest.mark.parametrize(("periods", "key"), [(199, "trend_200d"), (251, "drawdown_252d")])
def test_short_windows_are_unknown_not_zero(periods, key):
    item = _find(_risk(periods=periods), key)
    assert item["status"] == "unavailable"
    assert item["value"] is None
    assert item["reason"] == "insufficient_history"


def test_missing_or_stale_volatility_cannot_produce_normal_or_a_term_ratio():
    assert _risk()["status"] == "unavailable"
    stale = _risk(vix=_series([15, 16]), vix3m=_series([20], ["2026-07-17"]))
    item = _find(stale, "vix_term")
    assert item["value"] is None and item["status"] == "unavailable"
    assert item["as_of"] == "2026-07-17"
    assert item["reason"] == "volatility_stale"
    mismatch = _risk(vix=_series([15, 16]), vix3m=_series([20], ["2026-09-03"]))
    assert _find(mismatch, "vix_term")["reason"] == "session_mismatch"


def test_vix_jump_threshold_is_inclusive_and_requires_consecutive_market_sessions():
    jump = _risk(vix=_series([10, 12]))
    assert _find(jump, "vix_change")["status"] == "attention"
    assert _find(jump, "vix_change")["value"] == 20
    missing_day = _risk(vix=_series([10, 12], ["2026-09-02", "2026-09-04"]))
    assert _find(missing_day, "vix_change")["reason"] == "nonconsecutive_sessions"
    assert _find(missing_day, "vix_change")["value"] is None
    invalid = _risk(vix=_series([0, 12]))
    assert _find(invalid, "vix_change")["value"] is None


def test_freshness_uses_us_sessions_and_stale_prices_are_unknown():
    # September 7 is Labor Day: September 4 remains the latest completed session.
    assert _last_completed_us_session(datetime(2026, 9, 7, 22, tzinfo=UTC)) == date(2026, 9, 4)
    risk = _risk(expected=date(2026, 9, 8), vix=_series([15, 16]), vix3m=_series([17, 18]))
    assert risk["status"] == "normal"  # One actual session of publication lag.
    stale = _risk(expected=date(2026, 9, 9), vix=_series([15, 16]), vix3m=_series([17, 18]))
    assert _find(stale, "trend_200d")["value"] is None
    assert _find(stale, "vix_level")["value"] is None
    assert stale["status"] == "unavailable"


def test_missing_benchmarks_and_non_session_prices_do_not_imply_normal():
    risk = build_market_risk(
        {},
        expected_session=date(2026, 9, 4),
        price_source="futu",
        daily_vix=_series([15, 16]),
        daily_vix3m=_series([17, 18]),
    )
    assert risk["status"] == "unavailable"
    assert risk["unavailable_count"] == 4
    assert _find(risk, "trend_200d")["reason"] == "benchmark_not_in_basket"
    prices = pd.Series([100.0] * 252, index=pd.date_range(end="2026-09-05", periods=252))
    weekend = build_market_risk(
        {"SPY": prices}, expected_session=date(2026, 9, 8), price_source="futu"
    )
    assert _find(weekend, "trend_200d")["value"] is None
    assert _find(weekend, "trend_200d")["status"] == "unavailable"
