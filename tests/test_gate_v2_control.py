"""Random control: floor, false-pass rate, binomial test, determinism, no legacy RNG."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from quant_system.research import gate_v2 as g


def _family(n_members: int = 12) -> dict:
    sharpes = [0.06 * ((index % 5) - 2) for index in range(n_members)]
    return {
        "members": [
            {"trial_id": f"m{index}", "n_periods": 260, "recomputed_sharpe": value}
            for index, value in enumerate(sharpes)
        ],
        "family_digest": "frozen-family",
        "family_key": "uni|strategy_hypothesis",
        "n_trials": n_members,
        "trusted": True,
    }


def _factory(rng: np.random.Generator, index: int) -> dict:
    return {
        "active_returns": [float(value) for value in rng.normal(0.0, 0.008, 252)],
        "equity_returns": [float(value) for value in rng.normal(0.0002, 0.008, 252)],
    }


def _run(**kwargs) -> dict:
    return g.random_control_v2(
        universe=["AAA"], eval_window={}, curve_factory=_factory, family=_family(), **kwargs
    )


def test_the_variant_floor_is_enforced() -> None:
    with pytest.raises(ValueError, match="gate_v2_null_variants_below_floor"):
        _run(n_variants=100)


def test_non_rejection_of_binomial_null_does_not_pass_five_percent_acceptance(monkeypatch):
    from quant_system.research.gate_v2 import control

    calls = iter(range(500))
    monkeypatch.setattr(control, "evaluate_dsr_v2", lambda **_: {"passed": next(calls) < 30})
    monkeypatch.setattr(control, "health_checks_v2", lambda **_: {"passed": True})
    summary = _run(n_variants=500)
    assert summary["false_pass_rate"] == 0.06
    assert summary["binom_passed"] is True  # non-rejection is not evidence of <=5%
    assert summary["observed_rate_passed"] is False
    assert summary["calibration_passed"] is False


def test_zero_passes_has_explicit_acceptance_and_precision(monkeypatch):
    from quant_system.research.gate_v2 import control

    monkeypatch.setattr(control, "evaluate_dsr_v2", lambda **_: {"passed": False})
    monkeypatch.setattr(control, "health_checks_v2", lambda **_: {"passed": True})
    summary = _run(n_variants=500)
    assert summary["observed_rate_passed"] is True
    assert summary["calibration_passed"] is True
    assert summary["clopper_pearson_upper"] < 0.01


def test_false_pass_rate_is_under_the_five_percent_line() -> None:
    summary = g.random_control_v2(
        universe=["AAA", "BBB"],
        eval_window={"start": "2015-01-05", "end": "2016-01-05"},
        curve_factory=_factory,
        family=_family(),
        n_variants=600,
        seed=20260918,
    )
    assert summary["n_random"] == 600
    assert summary["false_pass_rate"] <= 0.05
    passes = round(summary["false_pass_rate"] * 600)
    assert passes <= summary["binom_critical_95pct"]
    assert summary["binom_passed"] is True
    assert 0.0 <= summary["clopper_pearson_upper"] <= 1.0


def test_the_family_is_frozen_across_the_run() -> None:
    family = _family()
    summary = g.random_control_v2(
        universe=["AAA"], eval_window={}, curve_factory=_factory, family=family, n_variants=500
    )
    assert summary["family_digest"] == "frozen-family"
    assert summary["family_n_trials"] == family["n_trials"]


def test_same_seed_is_identical_and_a_different_seed_differs() -> None:
    first = _run(n_variants=500, seed=1)
    again = _run(n_variants=500, seed=1)
    other = _run(n_variants=500, seed=2)
    assert first["gate_dsr_passes"] == again["gate_dsr_passes"]
    assert first["gate_health_passes"] == again["gate_health_passes"]
    assert (first["gate_dsr_passes"], first["gate_health_passes"]) != (
        other["gate_dsr_passes"],
        other["gate_health_passes"],
    )


def test_the_harness_never_touches_the_legacy_global_rng(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("legacy global numpy RNG must not be used")

    for name in ("random", "randint", "normal", "uniform", "choice", "shuffle", "seed"):
        monkeypatch.setattr(np.random, name, _boom)
    summary = _run(n_variants=500, seed=3)
    assert summary["n_random"] == 500


def test_the_binomial_helpers_are_exact() -> None:
    # For 20 trials at p=0.05, the 95% critical value is 2 (P(X<=2) ~= 0.9245 < 0.95,
    # P(X<=3) ~= 0.9841 >= 0.95).
    assert g.binom_critical(n=20) == 3
    assert g.binom_critical(n=2000) == 116
    upper = g.clopper_pearson_upper(k=0, n=20)
    assert 0.0 < upper < 0.2


def test_the_summary_receipt_is_written(tmp_path: Path) -> None:
    summary = g.random_control_v2(
        universe=["AAA"], eval_window={}, curve_factory=_factory, family=_family(), n_variants=500
    )
    path = g.write_control_summary(tmp_path / "gate-v2-control", summary)
    document = json.loads(path.read_text())
    for key in (
        "seed",
        "n_random",
        "rng",
        "false_pass_rate",
        "binom_critical_95pct",
        "clopper_pearson_upper",
        "schema_version",
        "gate_v2_sources",
    ):
        assert key in document
    assert document["schema_version"] == g.CONTROL_SCHEMA_VERSION
