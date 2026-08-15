from __future__ import annotations

import pytest

from quant_system.d34.qlib_expr import QlibExprError, compile_qlib_expr


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
