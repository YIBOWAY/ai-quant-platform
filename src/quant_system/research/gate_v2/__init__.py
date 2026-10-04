"""Parallel gate v2 — an observation-only DSR/concentration/health decision layer.

This package adds a **second, non-authoritative** judgement beside the v1 gate.
It changes no v1 constant, writes no v1 key, and can never enter the v1 DSR
trial family. Its only write面 is an append-only ``verdicts.jsonl`` and it is
switched off by default (``GATE_V2_ENABLED``); ``GATE_V2_AUTHORITATIVE`` is
``False`` and flipping either is an Owner gate.

Design anchors:

* **Same math, new inputs** — the DSR formula is v1's ``deflated_sharpe_ratio``
  verbatim; only ``SR``/``skew``/``kurt``/``n`` (from the active-return series)
  and the recomputed family change.
* **Explicit family rule** — v2's family admits only digest-verified
  ``platform_backtest`` rows, repairing the ``trial_sharpes`` kind-filter defect.
* **Recompute envelope** — every verdict embeds its inputs so
  :func:`verify_verdict_v2` requires caller-owned original trials and a curve
  resolver, rebuilds the family from those sources, then checks bit equality.
  The verdict module's explicitly named ``verify_verdict_integrity_v2`` checks
  embedded mathematics only and never provides admission authority.
"""

from __future__ import annotations

from ._constants import (
    CONFIG_VERSION,
    CONTROL_SCHEMA_VERSION,
    CORR_V2_SCHEMA_VERSION,
    CORRELATION_MAX_V2,
    DEFAULT_TIER,
    DSR_V2_COVERAGE_SHORTFALL_BUDGET,
    DSR_V2_FAMILY_MIN_ENTRIES,
    DSR_V2_FAMILY_MIN_PERIODS,
    DSR_V2_MIN,
    DSR_V2_MIN_PERIODS_CANDIDATE,
    DSR_V2_SCHEMA_VERSION,
    DSR_V2_SMALL_FAMILY_MIN_MEMBERS,
    DSR_V2_SMALL_FAMILY_MIN_PERIODS,
    DSR_V2_SMALL_FAMILY_PASS_MIN,
    FAMILY_V2_SCHEMA_VERSION,
    FINGERPRINT_GRADING_ENABLED,
    GATE_V2_AUTHORITATIVE,
    GATE_V2_ENABLED,
    GATE_V2_NULL_SEED,
    GATE_V2_NULL_VARIANTS,
    GATE_V2_SCHEMA_VERSION,
    HEALTH_ANNUAL_VOL_MAX,
    HEALTH_MAX_DRAWDOWN_MAX,
    HEALTH_PSR0_MIN,
    HEALTH_V2_SCHEMA_VERSION,
    NULL_BLOCK_LENGTH,
    NULL_P95_LEVEL,
    TIER_CAPITAL_USD,
)
from .active_returns import (
    ACTIVE_RETURN_RULE,
    INITIAL_CASH_RULE,
    active_series,
    recompute_active_returns,
)
from .control import (
    binom_critical,
    clopper_pearson_upper,
    load_null_calibration_v2,
    random_control_v2,
    write_control_summary,
)
from .correlation_v2 import (
    concentration_v2,
    ols_resid,
    paired_increment_verdict,
    raw_concentration_v2,
    residual_correlation_v2,
    residual_null_p95,
)
from .dsr_v2 import evaluate_dsr_v2
from .family import (
    FAMILY_SCOPE_STRATEGY,
    is_member,
    project_family_v2,
    validation_dir_resolver,
)
from .health_v2 import health_checks_v2
from .switch import derive_conclusion_changes_v2, switch_review_document
from .verdict import (
    GATE_V2_CONFIG,
    GRADE_INSUFFICIENT,
    GRADE_MARGINAL,
    GRADE_SUPPORTED,
    append_verdict_v2,
    envelope_digest,
    evaluate_gate_v2,
    evaluate_sensitivity_v2,
    gate_v2_sources,
    grade_v2,
    thresholds_block,
    tier_for_grade,
    verify_verdict_v2,
)

__all__ = [
    # version stamps
    "GATE_V2_SCHEMA_VERSION",
    "DSR_V2_SCHEMA_VERSION",
    "FAMILY_V2_SCHEMA_VERSION",
    "CORR_V2_SCHEMA_VERSION",
    "HEALTH_V2_SCHEMA_VERSION",
    "CONTROL_SCHEMA_VERSION",
    "CONFIG_VERSION",
    # switches
    "GATE_V2_ENABLED",
    "GATE_V2_AUTHORITATIVE",
    "FINGERPRINT_GRADING_ENABLED",
    # thresholds
    "CORRELATION_MAX_V2",
    "DSR_V2_MIN",
    "DSR_V2_FAMILY_MIN_PERIODS",
    "DSR_V2_FAMILY_MIN_ENTRIES",
    "DSR_V2_SMALL_FAMILY_PASS_MIN",
    "DSR_V2_SMALL_FAMILY_MIN_MEMBERS",
    "DSR_V2_SMALL_FAMILY_MIN_PERIODS",
    "DSR_V2_MIN_PERIODS_CANDIDATE",
    "DSR_V2_COVERAGE_SHORTFALL_BUDGET",
    "HEALTH_PSR0_MIN",
    "HEALTH_MAX_DRAWDOWN_MAX",
    "HEALTH_ANNUAL_VOL_MAX",
    "GATE_V2_NULL_SEED",
    "GATE_V2_NULL_VARIANTS",
    "NULL_BLOCK_LENGTH",
    "NULL_P95_LEVEL",
    "GATE_V2_CONFIG",
    # tiers
    "TIER_CAPITAL_USD",
    "DEFAULT_TIER",
    # input layer
    "ACTIVE_RETURN_RULE",
    "INITIAL_CASH_RULE",
    "recompute_active_returns",
    "active_series",
    # family
    "FAMILY_SCOPE_STRATEGY",
    "is_member",
    "project_family_v2",
    "validation_dir_resolver",
    # decisions
    "evaluate_dsr_v2",
    "health_checks_v2",
    "concentration_v2",
    "raw_concentration_v2",
    "residual_correlation_v2",
    "residual_null_p95",
    "ols_resid",
    "paired_increment_verdict",
    "grade_v2",
    "tier_for_grade",
    "thresholds_block",
    "GRADE_INSUFFICIENT",
    "GRADE_MARGINAL",
    "GRADE_SUPPORTED",
    "evaluate_gate_v2",
    "verify_verdict_v2",
    "envelope_digest",
    "evaluate_sensitivity_v2",
    "append_verdict_v2",
    "gate_v2_sources",
    # control
    "random_control_v2",
    "load_null_calibration_v2",
    "binom_critical",
    "clopper_pearson_upper",
    "write_control_summary",
    # switch
    "derive_conclusion_changes_v2",
    "switch_review_document",
]
