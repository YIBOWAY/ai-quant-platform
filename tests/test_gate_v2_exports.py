"""G5: the previously untested exports get direct coverage.

``thresholds_block``, ``ols_resid``, ``load_null_calibration_v2`` and the new
``envelope_digest`` each had no test asserting their contract.
"""

from __future__ import annotations

import numpy as np
import pytest

from quant_system.research import gate_v2 as g
from tests.gate_v2_fixtures import noise_returns

_THRESHOLD_KEYS = {
    "dsr_v2_min",
    "dsr_family_min_entries",
    "dsr_small_family_pass_min",
    "dsr_small_family_min_members",
    "dsr_small_family_min_periods",
    "dsr_min_periods_candidate",
    "dsr_family_min_periods",
    "coverage_shortfall_budget",
    "correlation_max",
    "health_psr0_min",
    "health_max_drawdown_max",
    "health_annual_vol_max",
}


def test_thresholds_block_echoes_every_value_with_its_source() -> None:
    block = g.thresholds_block(g.GATE_V2_CONFIG)
    assert set(block) == _THRESHOLD_KEYS
    assert all(set(entry) == {"value", "source"} for entry in block.values())
    for key in _THRESHOLD_KEYS:
        assert block[key]["value"] == g.GATE_V2_CONFIG[key]
    assert block["dsr_v2_min"]["source"] == "DSR_DEFAULT_MIN (alias)"
    assert block["correlation_max"]["source"] == "FACTOR_CORRELATION_MAX (alias)"
    assert block["dsr_family_min_entries"]["source"] == "program_rule"


def test_thresholds_block_follows_a_custom_config() -> None:
    config = {**g.GATE_V2_CONFIG, "dsr_v2_min": 0.5, "correlation_max": 0.25}
    block = g.thresholds_block(config)
    assert block["dsr_v2_min"]["value"] == 0.5
    assert block["correlation_max"]["value"] == 0.25


def test_ols_resid_returns_the_orthogonal_complement() -> None:
    rng = np.random.default_rng(3)
    regressor = rng.normal(0.0, 0.01, 300)
    target = 2.0 * regressor + rng.normal(0.0, 0.001, 300)
    residual = g.ols_resid(target.tolist(), regressor.tolist())
    assert residual.shape == target.shape
    assert abs(float(residual.mean())) < 1e-12
    assert abs(float(np.dot(residual, regressor))) < 1e-12
    # A perfectly linear pair leaves nothing behind.
    straight = g.ols_resid([2.0, 5.0, 8.0, 11.0], [0.0, 1.0, 2.0, 3.0])
    assert np.allclose(straight, 0.0)


def _calibration_inputs() -> tuple[list[float], list[float], list[float]]:
    left = noise_returns(200, seed=1)
    right = noise_returns(200, seed=2)
    benchmark = noise_returns(200, seed=3)
    return left, right, benchmark


def test_load_null_calibration_v2_is_deterministic_and_bounded() -> None:
    left, right, benchmark = _calibration_inputs()
    first = g.load_null_calibration_v2(
        left_returns=left,
        right_returns=right,
        benchmark_returns=benchmark,
        block_length=g.NULL_BLOCK_LENGTH,
        n_resamples=500,
        seed=g.GATE_V2_NULL_SEED,
    )
    second = g.load_null_calibration_v2(
        left_returns=left,
        right_returns=right,
        benchmark_returns=benchmark,
        block_length=g.NULL_BLOCK_LENGTH,
        n_resamples=500,
        seed=g.GATE_V2_NULL_SEED,
    )
    assert first == second
    assert first["block_length"] == g.NULL_BLOCK_LENGTH
    assert first["n_resamples"] == 500
    assert 0.0 <= first["null_p95"] <= 1.0
    assert first["null_median"] <= first["null_p95"]


def test_load_null_calibration_v2_reports_an_invalid_block_length() -> None:
    left, right, benchmark = _calibration_inputs()
    result = g.load_null_calibration_v2(
        left_returns=left,
        right_returns=right,
        benchmark_returns=benchmark,
        block_length=0,
    )
    assert result["null_p95"] is None
    assert result["reason"] == "invalid_block_length"


def test_envelope_digest_tracks_every_covered_field() -> None:
    record = {
        "schema_version": g.GATE_V2_SCHEMA_VERSION,
        "config_version": g.CONFIG_VERSION,
        "authoritative": False,
        "mode": "parallel_observe_only",
        "formula": "bailey_lopez_de_prado_2014",
        "thresholds": {},
        "config": dict(g.GATE_V2_CONFIG),
        "tier_recommendation": {"tier": "T2", "tier_source": "program_rule"},
        "verdict_parallel": {"v1_passed": True, "v2_passed": True, "conclusion_changed": False},
        "rng": {"seed": g.GATE_V2_NULL_SEED},
        "computed_at": "2026-09-18T00:00:00+00:00",
    }
    digest = g.envelope_digest(record)
    assert len(digest) == 64
    record["computed_at"] = "2026-09-18T00:00:01+00:00"
    assert g.envelope_digest(record) != digest


@pytest.mark.parametrize("field", ["mode", "authoritative", "formula", "config_version"])
def test_envelope_digest_is_sensitive_to_a_single_field(field: str) -> None:
    record = {
        "mode": "parallel_observe_only",
        "authoritative": False,
        "formula": "bailey_lopez_de_prado_2014",
        "config_version": g.CONFIG_VERSION,
    }
    digest = g.envelope_digest(record)
    record[field] = "tampered" if not isinstance(record[field], bool) else True
    assert g.envelope_digest(record) != digest
