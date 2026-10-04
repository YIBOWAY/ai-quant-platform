from __future__ import annotations

import pandas as pd
import pytest

from quant_system.d34.qlib_expr import QlibExprError, compile_qlib_expr
from quant_system.d34.research_driver import ResearchProposal, render_factor_source


def test_compiles_catalog_equivalent_momentum() -> None:
    compiled = compile_qlib_expr("$close/Ref($close,5)-1")
    assert "Ref($close,5)" in compiled.qlib
    assert compiled.qlib.count("close") >= 2
    assert 'frame["close"]' in compiled.pandas_body
    assert "shift(5)" in compiled.pandas_body
    assert compiled.node_count <= 24
    assert compiled.depth <= 6


def test_compiles_rank_of_mean_reversion() -> None:
    compiled = compile_qlib_expr("Rank(1-$close/Ref($close,20), 1)")
    assert compiled.qlib.startswith("Rank(")
    assert "rank(pct=True)" in compiled.pandas_body


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("Rank($close,3)", [1.0, 1.0, 2 / 3, 1.0]),
        ("EMA($close,3)", [10.0, 70 / 3, 150 / 7, 470 / 15]),
        ("Mean($close,3)", [10.0, 20.0, 20.0, 30.0]),
        ("Std($close,3)", [float("nan"), 200 ** 0.5, 10.0, 10.0]),
        ("Sum($close,3)", [10.0, 40.0, 60.0, 90.0]),
        ("Max($close,3)", [10.0, 30.0, 30.0, 40.0]),
        ("Min($close,3)", [10.0, 10.0, 10.0, 20.0]),
    ],
)
def test_generated_factor_matches_pinned_qlib_window_semantics(
    expression: str, expected: list[float]
) -> None:
    # Qlib da920b7: Rank is time-series rank, rolling min_periods=1,
    # Std uses ddof=1, and EMA uses adjusted exponential weights.
    proposal = ResearchProposal(
        title="Window parity", thesis="Use the same scores in research and paper.",
        operator="composed", long_window=3, qlib_expr=expression,
        rationale="Verify generated factor behavior.",
    )
    source, _digest = render_factor_source(proposal=proposal, factor_id="window_parity")
    namespace: dict = {}
    exec(source, namespace)
    frame = pd.DataFrame({
        "symbol": ["AAPL", "MSFT"] * 4,
        "date": pd.date_range("2026-01-01", periods=4).repeat(2),
        "close": [10.0, 100.0, 30.0, 300.0, 20.0, 200.0, 40.0, 400.0],
    })
    observed = namespace["D34_FACTOR"]()._compute_values(frame)
    multiplier = 1 if expression.startswith("Rank") else 10
    pd.testing.assert_series_equal(
        observed,
        pd.Series([value for x in expected for value in (x, x * multiplier)], name="close"),
    )


def test_rejects_unknown_field_and_function() -> None:
    with pytest.raises(QlibExprError) as unknown_field:
        compile_qlib_expr("$vwap/Ref($close,5)")
    assert unknown_field.value.code == "d34_qlib_expr_invalid"
    with pytest.raises(QlibExprError) as unknown_fn:
        compile_qlib_expr("Skew($close,20)")
    assert unknown_fn.value.code == "d34_qlib_expr_invalid"


def test_rejects_overlong_window_and_deep_trees() -> None:
    with pytest.raises(QlibExprError) as window:
        compile_qlib_expr("Mean($close,253)")
    assert window.value.code == "d34_qlib_expr_window_invalid"
    nested = "$close"
    for _ in range(8):
        nested = f"Abs({nested})"
    with pytest.raises(QlibExprError) as deep:
        compile_qlib_expr(nested)
    assert deep.value.code == "d34_qlib_expr_too_complex"


def test_nested_expression_lookback_covers_the_formula() -> None:
    compiled = compile_qlib_expr("Mean(Ref($close,20),60)")
    assert compiled.lookback == 80
    proposal = ResearchProposal(
        title="Nested lookback", thesis="Retain all formula observations.",
        operator="composed", long_window=20,
        qlib_expr="Mean(Ref($close,20),60)", rationale="Exact replication.",
    )
    source, _digest = render_factor_source(proposal=proposal, factor_id="nested_lookback")
    assert "default_lookback = 80" in source
