"""Drift categories never exempt trading behavior from current validation."""

from __future__ import annotations

import pytest

from quant_system.research.fingerprint_grading import (
    FINGERPRINT_GRADING_ENABLED,
    classify_source,
    current_source_fingerprints_v2,
    validate_definition_v2,
)
from quant_system.research.strategy_definition import (
    StrategyDefinition,
    StrategyFactor,
    validate_definition,
)


def _definition() -> StrategyDefinition:
    return StrategyDefinition(
        kind="factor_blend",
        title="grading fixture",
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


def _drift(path: str) -> dict:
    raw = _definition().model_dump(mode="json")
    raw["source_fingerprints"] = {**raw["source_fingerprints"], path: "0" * 64}
    raw["content_digest"] = ""
    return raw


def test_the_switch_is_closed_by_default() -> None:
    assert FINGERPRINT_GRADING_ENABLED is False


def test_classification_names_the_known_roles() -> None:
    assert classify_source("research/definition_paper.py") == "dual_role"
    assert classify_source("execution/definition_open_prices.py") == "dual_role"
    assert classify_source("research/strategy_runtime.py") == "dual_role"
    assert classify_source("research/reference_backtests.py") == "dual_role"
    assert classify_source("research/strategy_definition.py") == "algorithm"
    assert classify_source("backtest/engine.py") == "algorithm"
    assert classify_source("dependency:exchange_calendars") == "algorithm"
    assert classify_source("factor:momentum") == "algorithm"


def test_graded_fingerprints_split_observation_out() -> None:
    definition = _definition()
    lumped = current_source_fingerprints_v2(definition, graded=False)
    graded = current_source_fingerprints_v2(definition, graded=True)
    assert graded["observation"] == {}
    assert set(graded["algorithm"]) | set(graded["observation"]) == set(lumped["algorithm"])
    assert graded["advisory"] == sorted(graded["observation"])


def test_fail_closed_matches_v1_on_a_clean_definition() -> None:
    raw = _definition().model_dump(mode="json")
    assert validate_definition(raw) == validate_definition_v2(raw)["definition"]
    assert validate_definition_v2(raw)["status"] == "ok"


def test_observation_drift_is_fail_closed_by_default() -> None:
    raw = _drift("research/definition_paper.py")
    with pytest.raises(ValueError, match="strategy_algorithm_source_mismatch"):
        validate_definition(raw)
    with pytest.raises(ValueError, match="strategy_algorithm_source_mismatch"):
        validate_definition_v2(raw)  # the default path is byte-for-byte the v1 one


@pytest.mark.parametrize("path", [
    "research/definition_paper.py",
    "execution/definition_open_prices.py",
    "execution/paper_strategy_signal_service.py",
    "execution/paper_strategy_execution_service.py",
])
@pytest.mark.parametrize("enabled", [False, True])
def test_execution_or_fee_changes_never_get_a_file_category_exemption(monkeypatch, path, enabled):
    from quant_system.research import fingerprint_grading

    monkeypatch.setattr(fingerprint_grading, "FINGERPRINT_GRADING_ENABLED", enabled)
    with pytest.raises(ValueError, match="strategy_algorithm_source_mismatch"):
        validate_definition_v2(_drift(path), observation_mode="advisory")


def test_algorithm_drift_still_fails_under_advisory() -> None:
    raw = _drift("research/strategy_definition.py")
    with pytest.raises(ValueError, match="strategy_algorithm_source_mismatch"):
        validate_definition_v2(raw, observation_mode="advisory")


def test_dual_role_files_still_fail_under_advisory() -> None:
    raw = _drift("research/strategy_runtime.py")
    with pytest.raises(ValueError, match="strategy_algorithm_source_mismatch"):
        validate_definition_v2(raw, observation_mode="advisory")


def test_an_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="fingerprint_grading_mode_invalid"):
        validate_definition_v2(_definition(), observation_mode="lax")  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["content_digest", "source_fingerprints"])
def test_frozen_identity_requires_existing_seal(field):
    from quant_system.research.fingerprint_grading import frozen_definition_identity

    raw = _definition().model_dump(mode="json")
    raw.pop(field)
    with pytest.raises(ValueError, match="strategy_definition_binding_required"):
        frozen_definition_identity(raw)


def test_frozen_identity_rejects_mutated_parameters_and_factor_implementation():
    from quant_system.research.fingerprint_grading import frozen_definition_identity

    raw = _definition().model_dump(mode="json")
    raw["top_n"] = 1
    with pytest.raises(ValueError, match="strategy_content_digest_mismatch"):
        frozen_definition_identity(raw)
    raw = _definition().model_dump(mode="json")
    raw["factors"][0]["source_digest"] = "0" * 64
    with pytest.raises(ValueError, match="strategy_factor_source_mismatch"):
        frozen_definition_identity(raw)
