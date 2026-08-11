from __future__ import annotations

from quant_system.execution.paper_execution_policy import (
    PaperExecutionBatch,
    PaperExecutionPolicy,
)


def _batch(*, source: str = "d33", **overrides: object) -> PaperExecutionBatch:
    values: dict[str, object] = {
        "source": source,
        "workspace_id": "local-default",
        "account_id": "paper-main",
        "sleeve_id": f"sleeve-{source}",
        "orders": ({"symbol": "SPY", "notional_delta": 2_000.0},),
        "sleeve_equity": 10_000.0,
        "nav": 1_000_000.0,
        "aggregate_symbol_values": {"SPY": 45_000.0},
        "emergency_stop": False,
        "paper_execution_enabled": True,
        "mandate_active": source != "d34",
        "mandate_paper_execution_allowed": source != "d34",
    }
    values.update(overrides)
    return PaperExecutionBatch(**values)  # type: ignore[arg-type]


def test_d33_and_d34_use_one_deterministic_batch_policy() -> None:
    policy = PaperExecutionPolicy()

    d33 = policy.evaluate_batch(_batch())
    d34 = policy.evaluate_batch(
        _batch(
            source="d34",
            mandate_active=True,
            mandate_paper_execution_allowed=True,
        )
    )

    assert d33.allowed is True
    assert d34.allowed is True
    assert d33.policy_digest == d34.policy_digest
    assert d33.decision_digest != d34.decision_digest
    assert policy.evaluate_batch(_batch()).decision_digest == d33.decision_digest
    assert d34.contract == "hqa.paper_execution_policy_decision/v1"


def test_d34_requires_active_paper_enabled_mandate_but_d33_does_not() -> None:
    policy = PaperExecutionPolicy()

    missing = policy.evaluate_batch(_batch(source="d34"))
    no_execution = policy.evaluate_batch(
        _batch(source="d34", mandate_active=True)
    )
    legacy = policy.evaluate_batch(_batch())

    assert missing.allowed is False
    assert missing.blockers == (
        "d34_mandate_inactive",
        "d34_mandate_paper_execution_not_allowed",
    )
    assert no_execution.blockers == (
        "d34_mandate_paper_execution_not_allowed",
    )
    assert legacy.allowed is True


def test_d34_top_one_canary_uses_account_symbol_limit_not_d33_diversification() -> None:
    policy = PaperExecutionPolicy()
    values = {
        "orders": ({"symbol": "SPY", "notional_delta": 990.0},),
        "sleeve_equity": 1_000.0,
        "nav": 100_000.0,
        "aggregate_symbol_values": {},
    }

    d34 = policy.evaluate_batch(
        _batch(
            source="d34",
            mandate_active=True,
            mandate_paper_execution_allowed=True,
            **values,
        )
    )
    d33 = policy.evaluate_batch(_batch(**values))

    assert d34.allowed is True
    assert d33.blockers == ("sleeve_symbol_limit",)


def test_emergency_stop_and_paper_switch_fail_closed_for_both_sources() -> None:
    policy = PaperExecutionPolicy()

    for source in ("d33", "d34"):
        decision = policy.evaluate_batch(
            _batch(
                source=source,
                mandate_active=True,
                mandate_paper_execution_allowed=True,
                emergency_stop=True,
                paper_execution_enabled=False,
            )
        )
        assert decision.allowed is False
        assert decision.blockers[:2] == (
            "emergency_stop_active",
            "paper_execution_disabled",
        )


def test_batch_policy_reports_all_order_limit_breaches_in_stable_order() -> None:
    decision = PaperExecutionPolicy().evaluate_batch(
        _batch(
            orders=(
                {"symbol": "SPY", "notional_delta": 10_001.0},
                {"symbol": "QQQ", "notional_delta": 4_001.0},
            ),
            aggregate_symbol_values={"SPY": 45_000.0, "QQQ": 49_000.0},
        )
    )

    assert decision.allowed is False
    assert decision.blockers == (
        "order_value_limit",
        "sleeve_symbol_limit",
        "aggregate_symbol_limit",
    )
    assert decision.projected_symbol_values == {
        "QQQ": 53_001.0,
        "SPY": 55_001.0,
    }


def test_batch_policy_rejects_unknown_source_and_invalid_numeric_inputs() -> None:
    policy = PaperExecutionPolicy()

    unknown = policy.evaluate_batch(_batch(source="other"))
    invalid = policy.evaluate_batch(_batch(nav=0.0))

    assert unknown.blockers == ("unsupported_automation_source",)
    assert invalid.blockers == ("invalid_nav",)
