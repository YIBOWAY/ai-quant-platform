from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from quant_system.research.behavior_review import (
    review_factor,
    run_factor_asof,
    run_research_exploration,
    verify_cost_trace,
)


def panel():
    rows = []
    for si, symbol in enumerate(("A", "B", "C", "D", "E", "SPY")):
        for day, stamp in enumerate(pd.date_range("2024-01-01", periods=28, tz="UTC")):
            close = 10 + si * 3 + day * (0.2 + si * 0.07) + ((day + si) % 3) * 0.1
            rows.append(
                dict(
                    symbol=symbol,
                    timestamp=stamp,
                    available_at=stamp,
                    open=close * 0.99,
                    high=close * 1.01,
                    low=close * 0.98,
                    close=close,
                    volume=1000 + si * 100,
                    eligible=True,
                )
            )
    return pd.DataFrame(rows)


GOOD = """
def compute(ohlcv, context):
    f = ohlcv.copy()
    close = f.close.where(f.available_at <= f.timestamp)
    score = close / close.groupby(f.symbol).shift(1) - 1
    return f[['symbol', 'timestamp']].assign(score=score.where(f.eligible & close.notna()))
"""


def test_supported_causal_factor_passes_probes_but_never_authorizes_promotion():
    review = review_factor(GOOD, panel(), {}, expected_expression="$close/Ref($close,1)-1")
    assert review["status"] == "pass", review
    assert review["promotion_authorized"] is False
    assert review["scope"] == "bounded_daily_ohlcv_behavior"


def test_no_reference_is_advisory_only_and_never_signs_pass():
    result = review_factor(GOOD, panel(), {})
    assert result["status"] == "not_evaluated"
    assert result["reference"]["status"] == "not_evaluated"
    assert result["reference"]["reason"] == "expected_expression_required"


def test_advisory_status_never_outlives_the_settled_review_status():
    """A not_evaluated review must not carry a pass-shaped advisory field."""
    result = review_factor(GOOD, panel(), {})
    assert result["status"] == "not_evaluated"
    assert result["advisory_status"] == result["status"]
    assert result["advisory_status"] != "pass"


@pytest.mark.parametrize(
    "expression,pandas_expression",
    [
        ("$close", "close"),
        ("Delta($close,2)", "close - close.groupby(f.symbol).shift(2)"),
        (
            "Mean($close,3)",
            "close.groupby(f.symbol).transform(lambda x: x.rolling(3,min_periods=1).mean())",
        ),
        (
            "Std($close,3)",
            "close.groupby(f.symbol).transform(lambda x: x.rolling(3,min_periods=1).std())",
        ),
        (
            "EMA($close,3)",
            "close.groupby(f.symbol).transform("
            "lambda x: x.ewm(span=3,adjust=True,min_periods=1).mean())",
        ),
    ],
)
def test_matching_supported_references_pass_without_changing_warmup(expression, pandas_expression):
    source = GOOD.replace("close / close.groupby(f.symbol).shift(1) - 1", pandas_expression)
    bars = panel()
    bars = bars[bars.timestamp <= pd.Timestamp("2024-01-08", tz="UTC")]
    review = review_factor(source, bars, {}, expected_expression=expression)
    assert review["status"] == "pass", review
    assert review["reference"]["status"] == "pass"
    assert all(
        row["scores_equal"] and row["rankings_equal"] and row["holdings_equal"]
        for row in review["reference"]["comparisons"].values()
    )


def test_future_shift_is_detected_by_actual_execution():
    source = GOOD.replace("shift(1)", "shift(-1)")
    review = review_factor(source, panel(), {})
    assert review["status"] == "fail"
    assert any(
        p["status"] == "fail"
        for p in review["probes"]
        if p["probe"] in ("future_perturbation", "prefix_truncation")
    )


def test_empty_scores_are_not_behavioral_evidence():
    review = review_factor(
        GOOD.replace("score=score.where(f.eligible & close.notna())", 'score=float("nan")'),
        panel(),
        {},
    )
    assert review["status"] == "not_evaluated"


def test_asof_adapter_never_mounts_future_or_unpublished_observations():
    source = """
import pandas as pd
def compute(ohlcv, context):
    # Even deliberately querying the last available bar cannot see tomorrow.
    score = ohlcv.close.groupby(ohlcv.symbol).transform('last')
    assert ohlcv.timestamp.max() == pd.Timestamp('2024-01-10', tz='UTC')
    assert len(context['observations']) == 1
    assert context['observations'][0]['value'] == 1
    return ohlcv[['symbol', 'timestamp']].assign(score=score)
"""
    context = {
        "observations": [
            dict(symbol="A", available_at=day, value=value)
            for day, value in [("2024-01-09T00:00:00Z", 1), ("2024-01-11T00:00:00Z", 999)]
        ]
    }
    result = run_factor_asof(source, panel(), context, as_of="2024-01-10T00:00:00Z")
    assert result["status"] == "ok", result
    assert {row["timestamp"] for row in result["scores"]} == {"2024-01-10T00:00:00.000Z"}
    assert len(result["scores"]) == 6


def test_cost_trace_checks_both_legs_and_never_passes_missing_evidence():
    assert verify_cost_trace(None)["status"] == "not_evaluated"
    trades = [
        dict(quantity=10, price=100, commission=0.1, slippage=0.5),
        dict(quantity=-10, price=110, commission=0.11, slippage=0.55),
    ]
    assert verify_cost_trace(trades)["status"] == "pass"
    assert verify_cost_trace([{**row, "commission": 0} for row in trades])["status"] == "fail"


def test_real_code_scorecard_dsl_and_temporary_ledger_path(tmp_path):
    result = run_research_exploration(
        GOOD, panel(), {}, expression="$close/Ref($close,1)-1", output_dir=tmp_path / "fresh"
    )
    assert result["status"] == "research_candidate", result
    assert result["translation"]["status"] == "pass"
    assert result["translation"]["scores_equal"]
    assert result["translation"]["rankings_equal"]
    assert result["translation"]["holdings_equal"]
    assert result["causal_execution"]["status"] == "pass"
    assert result["batch_vs_causal_equal"]
    assert result["promotion_authorized"] is False
    assert (tmp_path / "fresh" / "scorecard.json").is_file()
    assert (tmp_path / "fresh" / "trials.jsonl").is_file()


# Fixed development corpus. These are regression cases, NEVER independent holdout.
# Each faulty expression is actually executed in isolated Docker containers.
DEFECTS = [
    ("F01_forward_shift", "close.groupby(f.symbol).shift(-1)"),
    ("F02_forward_two_sessions", "close.groupby(f.symbol).shift(-2)"),
    (
        "F03_centered_window",
        "close.groupby(f.symbol).transform(lambda x: x.rolling(3, center=True).mean())",
    ),
    ("F04_full_sample_mean", 'close / close.groupby(f.symbol).transform("mean")'),
    ("F05_full_sample_std", 'close / close.groupby(f.symbol).transform("std")'),
    ("F06_full_sample_max", 'close / close.groupby(f.symbol).transform("max")'),
    ("F07_full_sample_sum", 'close / close.groupby(f.symbol).transform("sum")'),
    ("F08_final_observation", 'close.groupby(f.symbol).transform("last")'),
    ("F09_full_sample_rank", "close.groupby(f.symbol).rank(pct=True)"),
    ("F10_global_normalization", "close / close.mean()"),
    ("F11_global_maximum", "close / close.max()"),
    ("F12_sample_length", "close / len(f)"),
    ("F13_future_shift_fill", "close.groupby(f.symbol).shift(-1).fillna(close)"),
    ("F14_reverse_expansion", "close.iloc[::-1].expanding().mean().iloc[::-1]"),
    ("F15_positional_tail", "close * 0 + close.iloc[-1]"),
    ("F16_future_high", "f.high.groupby(f.symbol).shift(-1)"),
    ("F17_future_low", "f.low.groupby(f.symbol).shift(-1)"),
    ("F18_future_open", "f.open.groupby(f.symbol).shift(-1)"),
    ("F19_future_volume", "f.volume.groupby(f.symbol).shift(-1)"),
    ("F20_bfill_warmup", "(close / close.groupby(f.symbol).shift(1) - 1).bfill()"),
    ("F21_ignore_available_at", "f.close / f.close.groupby(f.symbol).shift(1) - 1"),
]


@pytest.mark.parametrize("case_id,expression", DEFECTS, ids=[row[0] for row in DEFECTS])
def test_known_factor_defect_regressions(case_id, expression):
    source = GOOD.replace("close / close.groupby(f.symbol).shift(1) - 1", expression)
    result = review_factor(source, panel(), {})
    assert result["status"] == "fail", (case_id, result)


@pytest.mark.parametrize(
    "case_id,source",
    [
        ("F22_static_members", GOOD.replace("f.eligible & close.notna()", "close.notna()")),
        (
            "F23_missing_quote_filled",
            GOOD.replace(
                "score=score.where(f.eligible & close.notna())",
                "score=score.fillna(0).where(f.eligible)",
            ),
        ),
        (
            "F24_drop_unscored_rows",
            GOOD.replace("return f[", "return f[").replace(
                "score=score.where(f.eligible & close.notna()))",
                "score=score.where(f.eligible & close.notna())).dropna()",
            ),
        ),
        (
            "F25_wrong_symbol_identity",
            GOOD.replace(
                "f[['symbol', 'timestamp']]", "f[['symbol', 'timestamp']].assign(symbol='WRONG')"
            ),
        ),
        (
            "F26_swallowed_missing_column",
            GOOD.replace("f.close.where", 'f.get("close", f.open).where'),
        ),
    ],
)
def test_contract_defect_regressions(case_id, source):
    result = review_factor(source, panel(), {})
    assert result["status"] == "fail", (case_id, result)


@pytest.mark.parametrize(
    "case_id,patch",
    [
        ("C01_free_commission", {"commission": 0}),
        ("C02_free_slippage", {"slippage": 0}),
        ("C03_bps_as_percent", {"commission": 11}),
        ("C04_sell_signed_commission", {"commission": -0.11}),
        ("C05_sell_signed_slippage", {"slippage": -0.55}),
        ("C06_double_commission", {"commission": 0.22}),
    ],
)
def test_known_cost_defect_regressions(case_id, patch):
    trade = dict(quantity=-10, price=110, commission=0.11, slippage=0.55)
    assert verify_cost_trace([{**trade, **patch}])["status"] == "fail", case_id


def test_unreviewed_merge_table_is_not_evaluated():
    assert (
        review_factor(GOOD, panel(), {"other": [{"symbol": "A", "eps": 999}]})["status"]
        == "not_evaluated"
    )


def test_unreviewed_observation_columns_are_not_evaluated():
    context = {
        "observations": [dict(symbol="A", available_at="2024-01-28T00:00:00Z", value=1, eps=999)]
    }
    result = review_factor(GOOD, panel(), context)
    assert result["status"] == "not_evaluated"
    assert result["reason"] == "unsupported_observation_schema"


def test_future_published_records_detected_even_after_gated_merge():
    source = """
import pandas as pd
def compute(ohlcv, context):
    f = ohlcv.copy()
    records = pd.DataFrame(context['observations'])
    gated = records[pd.to_datetime(records.available_at, utc=True) <= f.timestamp.min()]
    # Deliberate historical F9 shape: gated left side does not filter right side.
    unfiltered = records.groupby('symbol', as_index=False).value.sum()
    leak = gated[['symbol']].drop_duplicates().merge(unfiltered, on='symbol')
    result = f.merge(leak, on='symbol', how='left')
    return result[['symbol', 'timestamp']].assign(
        score=result.value.where(result.eligible & result.close.notna() &
                                 (result.available_at <= result.timestamp)))
"""
    observations = [
        dict(symbol=symbol, available_at=day, value=value)
        for symbol in panel().symbol.unique()
        for day, value in [("2023-12-31T00:00:00Z", 1), ("2024-01-25T00:00:00Z", 3)]
    ]
    review = review_factor(source, panel(), {"observations": observations})
    probe = [
        item for item in review["probes"] if item["probe"] == "published_observations_visibility"
    ]
    assert probe[0]["status"] == "fail"


@pytest.mark.parametrize(
    "case_id,reference,expected_status",
    [
        # Cross-sectional rank is deliberately outside the existing DSL, so unknown
        # stays unknown. Never count this unsupported example as a true positive.
        ("M02", None, "not_evaluated"),
        ("M03", "$close", "fail"),
        ("M04", "$close", "fail"),
        ("E01", "Delta($close,1)", "fail"),
    ],
)
def test_disclosed_independent_failures_become_regressions(case_id, reference, expected_status):
    document = json.loads(
        (Path(__file__).parent / "fixtures" / "behavior_review_known_regressions.json").read_text()
    )
    assert document["status"] == "disclosed_regression_only_not_new_holdout"
    case = next(item for item in document["cases"] if item["id"] == case_id)
    result = review_factor(
        case["source"],
        pd.DataFrame(document["ohlcv"]),
        document["context"],
        expected_expression=reference,
    )
    assert result["status"] == expected_status, result
    if case_id == "M03":
        assert any(
            p["status"] == "fail" and p["probe"] == "future_perturbation" for p in result["probes"]
        )
