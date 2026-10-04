"""Artificial fixed-seed examples for the date-bound concentration contract.

No provider, account, qualification or statistical core is mocked. These tests
cover the pure contract only; actual funding consumers are verified separately.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from quant_system.research.gate_v2.correlation_v2 import (
    concentration_v2,
    raw_concentration_v2,
)
from quant_system.research.trials import date_aligned_correlation


def panel(n=60, offset=0):
    # Calendar-date examples; exchange-session membership belongs to the caller.
    dates = [(date(2024, 1, 1) + timedelta(days=i + offset)).isoformat() for i in range(n)]
    values = np.random.default_rng(2026100301 + offset).normal(0, 0.01, n).tolist()
    return values, dates


def check(values, dates, peers, **kwargs):
    return raw_concentration_v2(
        candidate_returns=values,
        candidate_dates=dates,
        hung_sleeves=peers,
        require_dates=True,
        **kwargs,
    )


def peer(values, dates, identity="existing"):
    return {"sleeve_id": identity, "returns": values, "dates": dates}


def test_empty_peer_set_is_explicitly_not_applicable():
    result = check([], None, [])
    assert result["raw_status"] == "not_applicable"
    assert result["raw_reason"] == "no_peers"
    assert result["raw_max"] is None
    assert result["raw_passed"] is True
    assert result["n_hung_sleeves"] == 0
    assert result["raw_peer_diagnostics"] == []


@pytest.mark.parametrize("side", ["candidate", "peer"])
@pytest.mark.parametrize("bad_dates", [None, [], "2024-01-01"])
def test_date_required_never_falls_back_to_position(side, bad_dates):
    values, dates = panel()
    candidate_dates = bad_dates if side == "candidate" else dates
    other_dates = bad_dates if side == "peer" else dates
    result = check(values, candidate_dates, [peer(values, other_dates)])
    assert result["raw_status"] == "not_evaluated"
    assert result["raw_passed"] is False
    assert result["raw_max"] is None
    assert result["raw_unavailable_sleeves"] == ["existing"]
    assert result["raw_peer_diagnostics"][0]["reason"].startswith(side + "_")


@pytest.mark.parametrize("side", ["candidate", "peer"])
@pytest.mark.parametrize("defect", ["duplicate", "impossible", "timestamp", "short", "non_string"])
def test_date_shape_is_not_silently_truncated_or_deduplicated(side, defect):
    values, dates = panel()
    bad = dates.copy()
    if defect == "duplicate":
        bad[-1] = bad[0]
    elif defect == "impossible":
        bad[-1] = "2024-02-30"
    elif defect == "timestamp":
        bad[-1] += "T00:00:00Z"
    elif defect == "short":
        bad.pop()
    else:
        bad[-1] = date(2024, 2, 29)
    result = check(values, bad if side == "candidate" else dates,
                   [peer(values, bad if side == "peer" else dates)])
    assert result["raw_status"] == "not_evaluated"
    assert result["raw_passed"] is False
    assert result["raw_by_sleeve"] == []
    assert result["raw_peer_diagnostics"][0]["reason"].startswith(side + "_")


@pytest.mark.parametrize("side", ["candidate", "peer"])
@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -float("inf"), "0.1", True])
def test_return_shape_rejects_nonfinite_and_nonnumeric_values(side, bad_value):
    values, dates = panel()
    bad = values.copy()
    bad[0] = bad_value
    result = check(bad if side == "candidate" else values, dates,
                   [peer(bad if side == "peer" else values, dates)])
    assert result["raw_status"] == "not_evaluated"
    assert result["raw_passed"] is False
    assert result["raw_peer_diagnostics"][0]["reason"] == side + "_returns_invalid"


@pytest.mark.parametrize("shared", [19, 20])
def test_shared_calendar_threshold_is_exactly_twenty(shared):
    values, dates = panel(40)
    other, other_dates = panel(40, offset=40 - shared)
    result = check(values, dates, [peer(other, other_dates)])
    detail = result["raw_peer_diagnostics"][0]
    assert detail["shared_observations"] == shared
    assert result["raw_status"] == ("evaluated" if shared == 20 else "not_evaluated")
    if shared == 19:
        assert result["raw_passed"] is False
        assert detail["reason"] == "insufficient_shared_observations"
    else:
        assert result["raw_max"] == date_aligned_correlation(values, dates, other, other_dates)


def test_comparable_low_correlation_does_not_hide_unknown_peer():
    values, dates = panel()
    other = np.random.default_rng(2026100302).normal(0, 0.01, len(values)).tolist()
    result = check(values, dates, [peer(other, dates, "known"), peer(other, None, "unknown")])
    assert result["raw_max"] < 0.7
    assert result["raw_by_sleeve"] == [{"sleeve_id": "known", "correlation": result["raw_max"]}]
    assert result["raw_unavailable_sleeves"] == ["unknown"]
    assert result["raw_status"] == "not_evaluated"
    assert result["raw_passed"] is False


def test_zero_variance_is_unknown_even_with_twenty_shared_dates():
    values, dates = panel(20)
    result = check(values, dates, [peer([0.0] * 20, dates)])
    assert result["raw_passed"] is False
    assert result["raw_peer_diagnostics"][0]["reason"] == "correlation_unmeasurable"
    assert result["raw_peer_diagnostics"][0]["shared_observations"] == 20


@pytest.mark.parametrize("offset", [0, 10, 25])
def test_valid_dated_inputs_preserve_exact_existing_pearson_scalar(offset):
    values, dates = panel(80)
    other, other_dates = panel(80, offset)
    expected = date_aligned_correlation(values, dates, other, other_dates)
    # Date order may differ while correspondence remains exact and unique.
    result = check(values, dates, [peer(other[::-1], other_dates[::-1])])
    assert result["raw_status"] == "evaluated"
    assert result["raw_max"] == expected
    assert result["raw_passed"] is (expected <= 0.7)
    assert result["dates_required"] is True


def test_positional_math_is_explicit_diagnostic_option():
    values, _ = panel()
    result = raw_concentration_v2(
        candidate_returns=values, candidate_dates=None,
        hung_sleeves=[peer(values, None)], require_dates=False,
    )
    assert result["raw_status"] == "evaluated"
    assert result["raw_max"] == pytest.approx(1.0)
    assert result["dates_required"] is False
    assert result["raw_peer_diagnostics"][0]["alignment"] == "positional_diagnostic"


def test_combined_report_forwards_strict_date_policy_and_unknown_detail():
    values, dates = panel()
    result = concentration_v2(
        active={"equity_returns": values, "dates": dates},
        hung_sleeves=[peer(values, None)], require_dates=True,
    )
    assert result["raw_status"] == "not_evaluated"
    assert result["raw_peer_diagnostics"][0]["reason"] == "peer_dates_missing"
    assert result["dates_required"] is True
    assert result["passed"] is False


@pytest.mark.parametrize("ids", [[None], [""], ["same", "same"]])
def test_peer_identity_is_not_ambiguous(ids):
    values, dates = panel()
    result = check(values, dates, [peer(values, dates, identity) for identity in ids])
    assert result["raw_status"] == "not_evaluated"
    assert result["raw_passed"] is False
    assert all(row["reason"] == "peer_identity_invalid" for row in result["raw_peer_diagnostics"])
