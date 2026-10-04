"""Parallel invariant L4: the v2 tree is invisible to every fingerprint table.

The T2.2 ``1acf259d`` regression was exactly this class — new files landing in a
fingerprint set and invalidating every recorded definition/receipt. These tests
prove ``gate_v2`` and ``fingerprint_grading`` cannot enter any of the three
lumping tables, so their presence or absence leaves the fingerprints identical.
"""

from __future__ import annotations

from pathlib import Path

from quant_system.research import strategy_study_service, validation_receipts
from quant_system.research.strategy_definition import (
    _COMMON_SOURCES,
    StrategyDefinition,
    StrategyFactor,
    current_source_fingerprints,
)


def _definition() -> StrategyDefinition:
    return StrategyDefinition(
        kind="factor_blend",
        title="fingerprint fixture",
        symbols=["AAPL", "MSFT", "NVDA"],
        history_start="2019-01-02",
        top_n=2,
        factors=(
            StrategyFactor(
                factor_id="momentum", lookback=2, direction="higher_is_better", weight=1
            ),
            StrategyFactor(
                factor_id="volatility", lookback=5, direction="lower_is_better", weight=1
            ),
        ),
    )


def test_no_v2_path_is_in_the_common_source_table() -> None:
    for path in _COMMON_SOURCES:
        assert "gate_v2" not in path
        assert "fingerprint_grading" not in path


def test_the_definition_fingerprint_set_contains_no_v2_key() -> None:
    fingerprints = current_source_fingerprints(_definition())
    assert fingerprints  # non-trivial
    for key in fingerprints:
        assert "gate_v2" not in key
        assert "fingerprint_grading" not in key


def test_the_definition_fingerprint_set_is_independent_of_the_v2_tree() -> None:
    # The fingerprint keys are exactly the static source tuple plus the profile/
    # factor/dependency extras — none of which can be resolved inside gate_v2/.
    fingerprints = current_source_fingerprints(_definition())
    static_keys = set(_COMMON_SOURCES) | {
        "dependency:exchange_calendars",
        "factors/base.py",
        "factors/registry.py",
        "experiments/scoring.py",
        "d34/qlib_expr.py",
    }
    assert all(
        key in static_keys or key.startswith("factor:") for key in fingerprints
    )
    assert all("gate_v2" not in key for key in static_keys)


def test_the_study_service_file_table_is_clean() -> None:
    source = (
        Path(strategy_study_service.__file__).read_text(encoding="utf-8")
    )
    assert "gate_v2" not in source
    digest = strategy_study_service.calculation_digest()
    assert isinstance(digest, str) and len(digest) == 64


def test_the_receipt_bindings_are_clean() -> None:
    for name in validation_receipts._SOURCES:
        assert "gate_v2" not in name
    for name in validation_receipts._FILES:
        assert "gate_v2" not in name
