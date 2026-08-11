from __future__ import annotations

from quant_system.d34.engine_comparison import (
    ComparisonPolicy,
    EngineReceipt,
    compare_engine_receipts,
)


def _receipt(
    *,
    engine: str,
    returns,
    nav=1.1,
    weights=None,
    target_digest="d" * 64,
    return_dates=(),
):
    return EngineReceipt(
        engine=engine,
        snapshot_digest="a" * 64,
        universe_digest="b" * 64,
        calendar_digest="c" * 64,
        target_weights_digest=target_digest,
        daily_returns=tuple(returns),
        terminal_nav=nav,
        terminal_weights=weights or {"SPY": 0.5, "QQQ": 0.5},
        receipt_digest=("e" if engine == "qlib" else "f") * 64,
        return_dates=tuple(return_dates),
    )


def test_dual_engine_policy_accepts_only_exact_inputs_and_close_outputs() -> None:
    policy = ComparisonPolicy.initial()
    result = compare_engine_receipts(
        qlib=_receipt(engine="qlib", returns=[0.01, -0.005, 0.004]),
        platform=_receipt(
            engine="platform",
            returns=[0.01001, -0.00501, 0.00399],
            nav=1.0999,
            weights={"SPY": 0.5004, "QQQ": 0.4996},
        ),
        policy=policy,
    )

    assert result.contract == "hqa.d34_comparison/v1"
    assert result.accepted is True
    assert result.reason_codes == ()
    assert result.daily_return_correlation >= 0.995
    assert result.terminal_nav_difference_bps <= 25
    assert result.max_symbol_weight_difference_bps <= 50
    assert result.policy_digest == policy.digest
    assert len(result.comparison_digest) == 64

    mismatched = compare_engine_receipts(
        qlib=_receipt(engine="qlib", returns=[0.01, -0.005, 0.004]),
        platform=_receipt(
            engine="platform",
            returns=[0.01, -0.005, 0.004],
            target_digest="0" * 64,
        ),
        policy=policy,
    )
    assert mismatched.accepted is False
    assert mismatched.exact_inputs is False
    assert "target_weights_digest_mismatch" in mismatched.reason_codes


def test_return_calendar_mismatch_is_not_an_exact_input_match() -> None:
    result = compare_engine_receipts(
        qlib=_receipt(
            engine="qlib",
            returns=[0.01, -0.005, 0.004],
            return_dates=["2026-08-01", "2026-08-02", "2026-08-03"],
        ),
        platform=_receipt(
            engine="platform",
            returns=[0.01, -0.005, 0.004],
            return_dates=["2026-08-01", "2026-08-02", "2026-08-04"],
        ),
        policy=ComparisonPolicy.initial(),
    )

    assert result.accepted is False
    assert result.exact_inputs is False
    assert "return_dates_mismatch" in result.reason_codes


def test_dual_engine_policy_rejects_correlation_nav_and_weight_boundaries() -> None:
    result = compare_engine_receipts(
        qlib=_receipt(engine="qlib", returns=[0.03, 0.02, -0.01], nav=1.1),
        platform=_receipt(
            engine="platform",
            returns=[-0.03, -0.02, 0.01],
            nav=1.096,
            weights={"SPY": 0.51, "QQQ": 0.49},
        ),
        policy=ComparisonPolicy.initial(),
    )

    assert result.accepted is False
    assert set(result.reason_codes) == {
        "daily_return_correlation_below_minimum",
        "terminal_nav_difference_above_maximum",
        "symbol_weight_difference_above_maximum",
    }
