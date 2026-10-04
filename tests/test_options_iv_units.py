from __future__ import annotations

import pandas as pd
import pytest

from quant_system.options.iv_units import (
    IV_UNIT_PERCENT,
    IV_UNIT_RATIO,
    declare_unit,
    frame_to_ratio,
    frame_unit,
    legacy_cache_unit,
    to_percent,
    to_ratio,
)


def test_to_ratio_converts_percent_and_passes_ratio_through() -> None:
    assert to_ratio(42.0, unit=IV_UNIT_PERCENT) == 0.42
    assert to_ratio(0.42, unit=IV_UNIT_RATIO) == 0.42
    assert to_ratio(0.42) == 0.42  # undeclared means the canonical ratio


def test_to_percent_is_the_inverse_of_to_ratio() -> None:
    assert to_percent(0.42, unit=IV_UNIT_RATIO) == 42.0
    assert to_percent(42.0, unit=IV_UNIT_PERCENT) == 42.0
    assert to_percent(to_ratio(214.227, unit=IV_UNIT_PERCENT)) == pytest.approx(214.227)


def test_conversions_reject_unusable_values() -> None:
    for value in (None, 0, 0.0, -0.1, float("inf"), float("-inf"), float("nan"), "abc"):
        assert to_ratio(value) is None
        assert to_percent(value) is None


def test_frame_unit_is_declared_and_defaults_to_ratio() -> None:
    frame = pd.DataFrame({"implied_volatility": [0.42]})
    assert frame_unit(frame) == IV_UNIT_RATIO
    declare_unit(frame, IV_UNIT_PERCENT)
    assert frame_unit(frame) == IV_UNIT_PERCENT
    declare_unit(frame, "bogus")
    assert frame_unit(frame) == IV_UNIT_RATIO
    assert frame_unit(object()) == IV_UNIT_RATIO
    assert legacy_cache_unit() == IV_UNIT_PERCENT


def test_frame_to_ratio_converts_only_declared_percent_frames() -> None:
    ratio_frame = pd.DataFrame({"implied_volatility": [0.42]})
    assert frame_to_ratio(ratio_frame) is ratio_frame

    percent_frame = pd.DataFrame({"implied_volatility": [42.0, 0.0, float("nan")]})
    declare_unit(percent_frame, IV_UNIT_PERCENT)
    converted = frame_to_ratio(percent_frame)
    values = converted["implied_volatility"].tolist()
    assert values[0] == 0.42
    assert pd.isna(values[1])
    assert pd.isna(values[2])
    assert frame_unit(converted) == IV_UNIT_RATIO
    # The input frame is left untouched.
    assert percent_frame["implied_volatility"].tolist()[0] == 42.0


def test_undeclared_percent_magnitude_warns_once_but_keeps_ratio_semantics(caplog) -> None:
    import quant_system.options.iv_units as iv_units

    iv_units._undeclared_percent_warning_emitted = False
    suspect = pd.DataFrame({"implied_volatility": [59.83]})  # percent scale, no unit declared
    with caplog.at_level("WARNING", logger=iv_units.__name__):
        assert frame_to_ratio(suspect) is suspect
        assert frame_to_ratio(suspect) is suspect  # second call does not re-log
    warnings = [r for r in caplog.records if "no declared unit" in r.message]
    assert len(warnings) == 1
    assert suspect["implied_volatility"].iloc[0] == 59.83  # values untouched


def test_undeclared_ratio_magnitude_and_declared_percent_do_not_warn(caplog) -> None:
    import quant_system.options.iv_units as iv_units

    iv_units._undeclared_percent_warning_emitted = False
    ratio_frame = pd.DataFrame({"implied_volatility": [0.5983]})
    percent_frame = pd.DataFrame({"implied_volatility": [59.83]})
    declare_unit(percent_frame, IV_UNIT_PERCENT)
    with caplog.at_level("WARNING", logger=iv_units.__name__):
        assert frame_to_ratio(ratio_frame) is ratio_frame
        frame_to_ratio(percent_frame)
    assert [r for r in caplog.records if "no declared unit" in r.message] == []
