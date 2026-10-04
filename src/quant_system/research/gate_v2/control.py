"""Random-control harness for the v2 gate.

The plan demands "≥500 random variants, false-pass rate ≤5%". This module makes
that a computable, reproducible receipt rather than a slogan.

* **Generation** — the variant returns come from an injected ``curve_factory``
  so the RNG-to-sleeve backtest assembly stays out of the pure layer (it needs
  the product engine and price data). The factory is called as
  ``curve_factory(rng, index) -> {"active_returns", "equity_returns"}`` and the
  only randomness allowed is the explicit PCG64 generator.
* **Family is frozen** — the real v2 family is passed in once and reused for
  every variant, so family jitter cannot contaminate the false-pass metric.
* **Test** — one-sided binomial, ``H0: p <= 0.05``; the observed pass count must
  be at most the exact critical value ``min{k : P(X<=k) >= 0.95}``, and the
  Clopper–Pearson one-sided upper bound is reported alongside. Both are computed
  with exact ``math.comb`` sums — no scipy dependency. Non-rejection of that
  null is not acceptance: the observed rate must actually be <=5%, and the
  one-sided upper bound must also be <=5% for ``calibration_passed``.

The same harness is the single home for the residual-correlation null p95
(``load_null_calibration_v2``), so there is one RNG story and one receipt.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ._constants import (
    CONTROL_SCHEMA_VERSION,
    GATE_V2_NULL_MIN_VARIANTS,
    GATE_V2_NULL_SEED,
    GATE_V2_NULL_VARIANTS,
    NULL_ALPHA,
)
from .active_returns import active_series
from .correlation_v2 import residual_null_p95
from .dsr_v2 import evaluate_dsr_v2
from .health_v2 import health_checks_v2
from .verdict import GATE_V2_CONFIG


def _binom_cdf(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    total = 0.0
    for j in range(k + 1):
        total += math.comb(n, j) * (p**j) * ((1.0 - p) ** (n - j))
    return min(total, 1.0)


def binom_critical(*, n: int, p: float = NULL_ALPHA, alpha: float = NULL_ALPHA) -> int:
    """Smallest ``k`` with ``P(X <= k) >= 1 - alpha`` (exact, no scipy)."""
    for k in range(n + 1):
        if _binom_cdf(k, n, p) >= 1.0 - alpha:
            return k
    return n


def clopper_pearson_upper(*, k: int, n: int, alpha: float = NULL_ALPHA) -> float:
    """One-sided exact upper bound: the ``p`` solving ``P(X <= k; n, p) = alpha``."""
    if k >= n:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(80):
        mid = (low + high) / 2.0
        if _binom_cdf(k, n, mid) > alpha:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def random_control_v2(
    *,
    universe: Sequence[str],
    eval_window: Mapping[str, Any],
    curve_factory: Callable[[np.random.Generator, int], Mapping[str, Any]],
    family: Mapping[str, Any],
    n_variants: int = GATE_V2_NULL_VARIANTS,
    seed: int = GATE_V2_NULL_SEED,
    config: Mapping[str, Any] = GATE_V2_CONFIG,
    artifact_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run ``n_variants`` null sleeves through the v2 gate; report the pass rate."""
    if int(n_variants) < GATE_V2_NULL_MIN_VARIANTS:
        raise ValueError("gate_v2_null_variants_below_floor")
    rng = np.random.default_rng(int(seed))
    dsr_passes = 0
    health_passes = 0
    passes = 0
    for index in range(int(n_variants)):
        sample = curve_factory(rng, index)
        active = active_series(
            active_returns=sample["active_returns"],
            equity_returns=sample["equity_returns"],
        )
        dsr = evaluate_dsr_v2(
            active=active, family=family, dsr_min=config["dsr_v2_min"], config=config
        )
        health = health_checks_v2(active=active, config=config)
        if dsr["passed"]:
            dsr_passes += 1
        if health["passed"]:
            health_passes += 1
        if dsr["passed"] and health["passed"]:
            passes += 1
    critical = binom_critical(n=int(n_variants))
    rate = passes / int(n_variants)
    upper = clopper_pearson_upper(k=passes, n=int(n_variants))
    summary: dict[str, Any] = {
        "schema_version": CONTROL_SCHEMA_VERSION,
        "config_version": config.get("config_version"),
        "seed": int(seed),
        "n_random": int(n_variants),
        "rng": "numpy.random.Generator(PCG64)",
        "universe": sorted(str(symbol).upper() for symbol in universe),
        "eval_window": dict(eval_window),
        "family_key": family.get("family_key"),
        "family_digest": family.get("family_digest"),
        "family_n_trials": family.get("n_trials"),
        "gate_dsr_passes": dsr_passes,
        "gate_health_passes": health_passes,
        "false_pass_rate": rate,
        "binom_critical_95pct": critical,
        "binom_passed": passes <= critical,
        "binom_passed_meaning": "not_rejected_not_acceptance",
        "observed_rate_passed": rate <= NULL_ALPHA,
        "calibration_passed": rate <= NULL_ALPHA and upper <= NULL_ALPHA,
        "clopper_pearson_upper": upper,
        "null_alpha": NULL_ALPHA,
        "artifact_hashes": dict(artifact_hashes or {}),
        "gate_v2_sources": _source_hashes(),
    }
    return summary


def load_null_calibration_v2(
    *,
    left_returns: Sequence[float],
    right_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    block_length: int,
    n_resamples: int = 2000,
    seed: int = GATE_V2_NULL_SEED,
) -> dict[str, Any]:
    """Residual-correlation null p95, sharing the harness seed and block length."""
    return residual_null_p95(
        left_returns=left_returns,
        right_returns=right_returns,
        benchmark_returns=benchmark_returns,
        block_length=block_length,
        n_resamples=n_resamples,
        seed=seed,
    )


def write_control_summary(output_dir: Path, summary: Mapping[str, Any]) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "summary.json"
    path.write_text(json.dumps(dict(summary), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def _source_hashes() -> dict[str, str]:
    try:
        from .verdict import gate_v2_sources

        return gate_v2_sources()
    except Exception:  # noqa: BLE001 - the receipt is best-effort provenance
        return {}
