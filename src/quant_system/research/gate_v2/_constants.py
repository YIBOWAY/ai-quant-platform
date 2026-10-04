"""Version and threshold constants for the parallel ``gate_v2`` layer.

Every value here is one of two things:

* a **new v2 symbol** with no v1 counterpart (e.g. the small-family fixed pass
  line), every one of which is flagged ``待批准`` in the design and is a *program
  rule*, never a human gate; or
* an **alias** that references a frozen v1 constant rather than copying it —
  ``CORRELATION_MAX_V2 = FACTOR_CORRELATION_MAX`` and
  ``DSR_V2_MIN = DSR_DEFAULT_MIN``. The redline tests assert symbol identity
  (``is``), so a future edit to a v1 red-line constant can never leave a stale
  second source of truth behind.

No v1 constant is modified here. The two values v1 freezes as pass lines
(``0.7`` correlation, ``0.95`` DSR) appear only as **aliases** of the v1 symbols
(``CORRELATION_MAX_V2 is FACTOR_CORRELATION_MAX``, ``DSR_V2_MIN is
DSR_DEFAULT_MIN``) and are never restated as literals. The one ``0.95`` float in
this file is ``NULL_P95_LEVEL`` — the *quantile level* of the residual-correlation
null distribution, a statistical calibration line, not a capital gate — and it is
the single node the redline AST scan whitelists by name
(``test_gate_v2_redlines._named_null_quantile_nodes``). ``gate_v2`` is
observation-only in this batch: ``GATE_V2_ENABLED`` and ``GATE_V2_AUTHORITATIVE``
both default to ``False``, and flipping either is an Owner gate, not a code change.
"""

from __future__ import annotations

from quant_system.research.active_metrics import BOOTSTRAP_SEED
from quant_system.research.trials import (
    DSR_DEFAULT_MIN,
    DSR_FAMILY_MIN_PERIODS,
    FACTOR_CORRELATION_MAX,
)

# --- schema / version stamps (all new keys; the v1 key set is untouched) ----
GATE_V2_SCHEMA_VERSION = "gate_v2_v1"
DSR_V2_SCHEMA_VERSION = "dsr_v2_v1"
FAMILY_V2_SCHEMA_VERSION = "trial_family_v2_v1"
CORR_V2_SCHEMA_VERSION = "corr_v2_v1"
HEALTH_V2_SCHEMA_VERSION = "health_v2_v1"
CONTROL_SCHEMA_VERSION = "gate_v2_control_v1"
CONFIG_VERSION = "gate_v2_config_v1"

# --- parallel-safety switches (Owner gates; both stay closed this batch) ----
GATE_V2_ENABLED = False
GATE_V2_AUTHORITATIVE = False

# --- aliases, never copies -------------------------------------------------
CORRELATION_MAX_V2 = FACTOR_CORRELATION_MAX  # == FACTOR_CORRELATION_MAX (is)
DSR_V2_MIN = DSR_DEFAULT_MIN  # default DSR pass line binds the v1 symbol
DSR_V2_FAMILY_MIN_PERIODS = DSR_FAMILY_MIN_PERIODS

# --- new v2 thresholds (program rules; 待批准, sensitivity-checked) ---------
DSR_V2_FAMILY_MIN_ENTRIES = 10
DSR_V2_SMALL_FAMILY_PASS_MIN = 0.99
DSR_V2_SMALL_FAMILY_MIN_MEMBERS = 3
DSR_V2_SMALL_FAMILY_MIN_PERIODS = 60
DSR_V2_MIN_PERIODS_CANDIDATE = 126
DSR_V2_COVERAGE_SHORTFALL_BUDGET = 0.25
HEALTH_PSR0_MIN = 0.5
HEALTH_MAX_DRAWDOWN_MAX = 0.30
HEALTH_ANNUAL_VOL_MAX = 0.35

# --- random control --------------------------------------------------------
GATE_V2_NULL_SEED = BOOTSTRAP_SEED
GATE_V2_NULL_VARIANTS = 2000
GATE_V2_NULL_MIN_VARIANTS = 500
NULL_BLOCK_LENGTH = 21
NULL_ALPHA = 0.05
# Quantile level of the residual-correlation null distribution (a p95 line,
# NOT a pass threshold — it calibrates a diagnostic, it does not gate capital).
NULL_P95_LEVEL = 0.95

# --- observation-layer fingerprint grading (default CLOSED) ----------------
FINGERPRINT_GRADING_ENABLED = False

# --- tier capital map: T2 is the one non-zero entry and it *is* the -------
# existing literal; T0/T1 carry no new money (shadow observation).
SleeveTier = str
TIER_CAPITAL_USD = {"T0": 0.0, "T1": 0.0, "T2": 10_000.0}
# Fallback when no grade/level information is available. This must be the
# **unfunded** tier: the safe default is "no capital allocated", never the
# 10_000 tier. It matches ``verdict.tier_for_grade``'s unknown-grade fallback.
DEFAULT_TIER = "T0"
