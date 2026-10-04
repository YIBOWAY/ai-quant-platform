"""Red lines: v1 constants untouched, no second 0.7/0.95 judgement literal.

Everything here locks a value or an identity that the batch must not move. The
AST scan is the mechanical guard against a *second source of truth*: it walks
every constant in the new modules and fails if a bare ``0.7`` or ``0.95`` float
literal appears, so the v2 pass lines can only be aliases of the v1 symbols.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

import pytest

from quant_system.config.settings import SafetySettings
from quant_system.research import gate_v2 as g
from quant_system.research.strategy_definition import StrategyDefinition
from quant_system.research.trials import DSR_DEFAULT_MIN, FACTOR_CORRELATION_MAX

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
_PACKAGE = _SRC / "quant_system" / "research" / "gate_v2"
_GRADING = _SRC / "quant_system" / "research" / "fingerprint_grading.py"


def _new_module_paths() -> list[Path]:
    return sorted([*_PACKAGE.glob("*.py"), _GRADING])


def test_v1_red_line_constants_are_unchanged() -> None:
    assert DSR_DEFAULT_MIN == 0.95
    assert FACTOR_CORRELATION_MAX == 0.7
    assert g.DSR_V2_FAMILY_MIN_PERIODS == 20


def test_correlation_max_v2_is_an_alias_not_a_copy() -> None:
    assert g.CORRELATION_MAX_V2 is FACTOR_CORRELATION_MAX


def test_dsr_v2_min_binds_the_v1_symbol() -> None:
    assert g.DSR_V2_MIN is DSR_DEFAULT_MIN


def test_no_second_0_7_or_0_95_judgement_literal_in_the_v2_modules() -> None:
    offenders: list[str] = []
    for path in _new_module_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        allowed = _named_null_quantile_nodes(tree) if path.name == "_constants.py" else set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, float)
                and node.value in (0.7, 0.95)
                and id(node) not in allowed
            ):
                offenders.append(f"{path.name}:{node.lineno}={node.value}")
    assert offenders == [], f"second threshold source of truth: {offenders}"


def _named_null_quantile_nodes(tree: ast.Module) -> set[int]:
    """The one permitted 0.95: the null-distribution p95 quantile level."""
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and node.value.value in (0.7, 0.95)
        ):
            targets = [item.id for item in node.targets if isinstance(item, ast.Name)]
            if targets and all(item == "NULL_P95_LEVEL" for item in targets):
                allowed.add(id(node.value))
    return allowed


def test_commission_and_slippage_literals_are_unchanged() -> None:
    fields = StrategyDefinition.model_fields
    assert get_args(fields["commission_bps"].annotation) == (1.0,)
    assert get_args(fields["slippage_bps"].annotation) == (5.0,)
    assert fields["commission_bps"].default == 1.0
    assert fields["slippage_bps"].default == 5.0


def test_safety_switches_are_untouched() -> None:
    safety = SafetySettings()
    assert safety.kill_switch is True
    assert safety.live_trading_enabled is False
    for path in _new_module_paths():
        text = path.read_text(encoding="utf-8")
        assert "release_authorized" not in text
        assert "live_trading_enabled" not in text
        assert "kill_switch" not in text


def test_the_known_hardcoded_0_7_in_v1_is_still_recorded_unchanged() -> None:
    source = (_SRC / "quant_system" / "research" / "strategy_library.py").read_text(
        encoding="utf-8"
    )
    assert "corr > 0.7" in source  # 挂账: v1 hard-codes the limit; the batch leaves it


def test_switches_default_closed() -> None:
    assert g.GATE_V2_ENABLED is False
    assert g.GATE_V2_AUTHORITATIVE is False
    assert g.FINGERPRINT_GRADING_ENABLED is False


@pytest.mark.parametrize("tier,capital", [("T0", 0.0), ("T1", 0.0), ("T2", 10_000.0)])
def test_tier_capital_map(tier: str, capital: float) -> None:
    assert g.TIER_CAPITAL_USD[tier] == capital


def test_tier_capital_t2_matches_the_existing_hang_allocation_literal() -> None:
    from quant_system.execution import assistant_remote

    assert assistant_remote._HANG_ALLOCATION_CASH == 10_000.0
    assert g.TIER_CAPITAL_USD["T2"] == assistant_remote._HANG_ALLOCATION_CASH
