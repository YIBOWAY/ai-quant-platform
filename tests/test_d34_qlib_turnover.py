"""Artificial scalar contracts; no market or admission result is manufactured."""

import json

import pandas as pd
import pytest

from quant_system.d34.rdagent_qlib_runtime import _period_turnover
from quant_system.d34.research_request import digest_document
from quant_system.d34.worker import _qlib_turnover_period


def test_period_turnover_is_sum_of_gross_trade_over_previous_nav():
    # Buy $500 on $1000 NAV, then sell $250 on $1250 previous NAV.
    report = pd.DataFrame({"turnover": [500 / 1000, 0.0, 250 / 1250]})
    assert _period_turnover(report) == pytest.approx(0.7)
    assert _period_turnover(report.iloc[:2]) == pytest.approx(0.5)
    assert _period_turnover(pd.DataFrame({"turnover": [0.0, 0.0]})) == 0.0


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -0.1, True, "0.2"])
def test_period_turnover_does_not_skip_or_coerce_invalid_days(bad):
    report = pd.DataFrame({"turnover": pd.Series([0.3, bad], dtype=object)})
    assert _period_turnover(report) is None


def test_period_turnover_requires_column_nonempty_and_finite_sum():
    assert _period_turnover(pd.DataFrame({"cost": [0.001]})) is None
    assert _period_turnover(pd.DataFrame({"turnover": []})) is None
    assert _period_turnover(pd.DataFrame({"turnover": [1e308, 1e308]})) is None


@pytest.mark.parametrize(
    "turnover,expected",
    [(0.0, 0.0), (0.7, 0.7), (None, None), (-1, None), (True, None), ("0.7", None)],
)
def test_worker_binds_only_finite_nonnegative_original_turnover(tmp_path, turnover, expected):
    body = {"metrics": {"turnover": turnover}}
    digest = digest_document(body)
    path = tmp_path / "raw.json"
    path.write_text(json.dumps({**body, "receipt_digest": digest}))
    assert _qlib_turnover_period(path, expected_receipt_digest=digest) == expected


def test_worker_never_invents_missing_turnover_or_accepts_changed_raw(tmp_path):
    body = {"metrics": {"mean_daily_cost": 0.0001}}
    digest = digest_document(body)
    path = tmp_path / "raw.json"
    path.write_text(json.dumps({**body, "receipt_digest": digest}))
    assert _qlib_turnover_period(path, expected_receipt_digest=digest) is None
    body["metrics"]["turnover"] = 0.7
    path.write_text(json.dumps({**body, "receipt_digest": digest_document(body)}))
    with pytest.raises(ValueError, match="d34_engine_receipt_lineage_mismatch"):
        _qlib_turnover_period(path, expected_receipt_digest=digest)
