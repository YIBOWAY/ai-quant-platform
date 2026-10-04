"""Gate v2 orchestration: evaluate, grade, recompute-verify, append.

Pure functions plus exactly one writer (``append_verdict_v2``). The emitted
record is a **recompute envelope**: it embeds the raw active/equity series and
the concentration inputs so :func:`verify_verdict_v2` can rebuild every
sub-verdict from the record alone and compare to bit equality. Tampering any
embedded digest, the family member table, the health block or the grade flips
the verification to ``False``.

Nothing here is authoritative: ``mode`` is pinned ``parallel_observe_only`` and
``authoritative`` is ``False``. The tier map only *recommends*; it drives no
capital and no activation path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_system.research.evaluation_service import _hash

from ._constants import (
    CONFIG_VERSION,
    CORR_V2_SCHEMA_VERSION,
    CORRELATION_MAX_V2,
    DSR_V2_COVERAGE_SHORTFALL_BUDGET,
    DSR_V2_FAMILY_MIN_ENTRIES,
    DSR_V2_FAMILY_MIN_PERIODS,
    DSR_V2_MIN,
    DSR_V2_MIN_PERIODS_CANDIDATE,
    DSR_V2_SMALL_FAMILY_MIN_MEMBERS,
    DSR_V2_SMALL_FAMILY_MIN_PERIODS,
    DSR_V2_SMALL_FAMILY_PASS_MIN,
    GATE_V2_AUTHORITATIVE,
    GATE_V2_ENABLED,
    GATE_V2_NULL_SEED,
    GATE_V2_NULL_VARIANTS,
    GATE_V2_SCHEMA_VERSION,
    HEALTH_ANNUAL_VOL_MAX,
    HEALTH_MAX_DRAWDOWN_MAX,
    HEALTH_PSR0_MIN,
    NULL_BLOCK_LENGTH,
    TIER_CAPITAL_USD,
)
from .active_returns import ACTIVE_RETURN_RULE, recompute_active_returns
from .correlation_v2 import concentration_v2, paired_increment_verdict
from .dsr_v2 import PATH_SMALL_FAMILY, evaluate_dsr_v2
from .family import (
    FAMILY_SCOPE_STRATEGY,
    family_digest_payload,
    project_family_v2,
    verify_legacy_member,
)
from .health_v2 import health_checks_v2

GATE_V2_CONFIG: dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "dsr_v2_min": DSR_V2_MIN,
    "dsr_v2_min_source": "DSR_DEFAULT_MIN",
    "dsr_family_min_entries": DSR_V2_FAMILY_MIN_ENTRIES,
    "dsr_small_family_pass_min": DSR_V2_SMALL_FAMILY_PASS_MIN,
    "dsr_small_family_min_members": DSR_V2_SMALL_FAMILY_MIN_MEMBERS,
    "dsr_small_family_min_periods": DSR_V2_SMALL_FAMILY_MIN_PERIODS,
    "dsr_min_periods_candidate": DSR_V2_MIN_PERIODS_CANDIDATE,
    "dsr_family_min_periods": DSR_V2_FAMILY_MIN_PERIODS,
    "coverage_shortfall_budget": DSR_V2_COVERAGE_SHORTFALL_BUDGET,
    "correlation_max": CORRELATION_MAX_V2,
    "health_psr0_min": HEALTH_PSR0_MIN,
    "health_max_drawdown_max": HEALTH_MAX_DRAWDOWN_MAX,
    "health_annual_vol_max": HEALTH_ANNUAL_VOL_MAX,
    "null_seed": GATE_V2_NULL_SEED,
    "null_block_length": NULL_BLOCK_LENGTH,
    "null_variants": GATE_V2_NULL_VARIANTS,
}

_THRESHOLD_SOURCES = {
    "dsr_v2_min": "DSR_DEFAULT_MIN (alias)",
    "dsr_small_family_pass_min": "new (program_rule; activation_requires_qualification)",
    "correlation_max": "FACTOR_CORRELATION_MAX (alias)",
    "health_psr0_min": "new (program_rule; activation_requires_qualification)",
    "health_max_drawdown_max": "new (program_rule; activation_requires_qualification)",
    "health_annual_vol_max": "new (program_rule; activation_requires_qualification)",
}

GRADE_INSUFFICIENT = "D0_insufficient"
GRADE_MARGINAL = "D1_marginal"
GRADE_SUPPORTED = "D2_supported"
_GRADE_TIER = {GRADE_INSUFFICIENT: "T0", GRADE_MARGINAL: "T1", GRADE_SUPPORTED: "T2"}

# DSR failure reasons that are *structural*, not "value below the line": no
# rescale of the pass line can turn them into a pass. The sensitivity sweep must
# respect them, otherwise scaling the threshold silently rewrites a structural
# failure as a pass (observed defect G1: ``reason='family_too_small'``,
# ``value=0.999``, ``dsr_min_used=0.99`` was re-read as passing at ``scale=0.9``
# and flipped ``D0_insufficient`` -> ``D1_marginal``).
_DSR_NON_NUMERIC_REASONS = frozenset(
    {
        "dsr_input_invalid",
        "dsr_moments_invalid",
        "family_too_small",
        "family_member_short_window",
        "candidate_window_too_short",
    }
)

# Blocks that :func:`verify_verdict_v2` cannot rebuild by pure recomputation,
# folded into one envelope digest. The recomputed blocks (inputs / family / dsr /
# health / concentration / upgrade / grade) are compared by equality instead and
# are deliberately excluded.
_ENVELOPE_FIELDS = (
    "schema_version",
    "config_version",
    "authoritative",
    "mode",
    "formula",
    "thresholds",
    "config",
    "tier_recommendation",
    "verdict_parallel",
    "inputs",
    "rng",
    "computed_at",
)

_INCREMENT_RESAMPLES = 2000

_PACKAGE_DIR = Path(__file__).resolve().parent
_GRADING_MODULE = _PACKAGE_DIR.parent / "fingerprint_grading.py"


def thresholds_block(config: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
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
    )
    return {
        key: {"value": config[key], "source": _THRESHOLD_SOURCES.get(key, "program_rule")}
        for key in keys
    }


def gate_v2_sources() -> dict[str, str]:
    paths = sorted(_PACKAGE_DIR.glob("*.py"))
    if _GRADING_MODULE.exists():
        paths.append(_GRADING_MODULE)
    sources: dict[str, str] = {}
    for path in paths:
        sources[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return sources


def _upgrade_accepted(upgrade: Mapping[str, Any]) -> bool:
    """An upgrade counts only when the *primary* interval clears zero.

    ``paired_increment_verdict`` emits ``accepted_evidence`` in ``{None,
    'primary'}``; a favourable secondary statistic (bootstrap fraction positive)
    that did not clear the interval is not an upgrade, and any other evidence
    label is unsigned and unproducible. All of those fail closed here, so the
    "secondary evidence cannot lift a grade" judgement lands at
    ``D0_insufficient`` / ``paired_increment_rejected`` — not at ``D1``.
    """
    return upgrade.get("upgrade_accepted") is True and upgrade.get("accepted_evidence") == "primary"


def grade_v2(
    *,
    dsr: Mapping[str, Any],
    health: Mapping[str, Any],
    concentration: Mapping[str, Any],
    upgrade: Mapping[str, Any],
    family: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Grade one evaluation: D0 (blocks), D1 (passes, conservatively hedged), D2.

    There is deliberately **no** "secondary evidence lifts the grade" path. An
    upgrade is accepted only when the primary paired-increment interval clears
    zero (``paired_increment_verdict`` -> ``accepted_evidence='primary'``); a
    favourable secondary statistic (``fraction_bootstrap_positive``) that does
    not clear the interval is *not* an upgrade, so an applicable-and-not-accepted
    increment is graded ``D0`` (``paired_increment_rejected``) below, never
    softened to ``D1``. The only evidence value the producer can emit is
    ``'primary'`` or ``None``; anything else is unsigned, unproducible, and is
    treated as a non-acceptance.
    """
    insufficient: list[str] = []
    if not health.get("passed"):
        insufficient.extend(f"health_{reason}" for reason in health.get("reasons", []))
        if not health.get("reasons"):
            insufficient.append("health_failed")
    if not dsr.get("passed"):
        insufficient.append("dsr_v2_failed")
    if int(dsr.get("n_periods") or 0) < int(
        config.get("dsr_min_periods_candidate", DSR_V2_MIN_PERIODS_CANDIDATE)
    ):
        insufficient.append("candidate_window_too_short")
    if concentration.get("applicable") and concentration.get("raw_passed") is False:
        insufficient.append("concentration_raw_failed")
    if upgrade.get("applicable") and not _upgrade_accepted(upgrade):
        insufficient.append("paired_increment_rejected")
    if insufficient:
        return {"grade": GRADE_INSUFFICIENT, "reasons": sorted(set(insufficient))}

    marginal: list[str] = []
    if not family.get("trusted", True):
        marginal.append("family_coverage_shortfall")
    if dsr.get("path") == PATH_SMALL_FAMILY:
        marginal.append("small_family_conservative")
    if marginal:
        return {"grade": GRADE_MARGINAL, "reasons": marginal}
    return {"grade": GRADE_SUPPORTED, "reasons": ["dsr_health_family_supported"]}


def tier_for_grade(grade: str) -> str:
    return _GRADE_TIER.get(grade, "T0")


def _build_inputs(
    *,
    active: Mapping[str, Any],
    initial_cash: float,
    universe_digest: str,
    benchmark_symbol: str | None,
    definition_digest: str | None,
    hung_sleeves: Sequence[Mapping[str, Any]],
    benchmark_returns: Sequence[float] | None,
    null_p95: float | None,
    increment: Mapping[str, Any] | None,
    upgrade_target: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "active_return_rule": ACTIVE_RETURN_RULE,
        "initial_cash_rule": active["initial_cash_rule"],
        "initial_cash": float(initial_cash),
        "returns_digest": active["returns_digest"],
        "dates_digest": active["dates_digest"],
        "n_periods": active["n_periods"],
        "start": active["start"],
        "end": active["end"],
        "universe_digest": universe_digest,
        "benchmark_symbol": benchmark_symbol,
        "definition_digest": definition_digest,
        "active_returns": active["active_returns"],
        "equity_returns": active["equity_returns"],
        "dates": active["dates"],
        "hung_sleeves": [
            {
                "sleeve_id": sleeve.get("sleeve_id"),
                "definition_digest": sleeve.get("definition_digest"),
                "returns": list(sleeve.get("returns") or []),
                "dates": list(sleeve.get("dates") or []),
            }
            for sleeve in hung_sleeves
        ],
        "benchmark_returns": list(benchmark_returns) if benchmark_returns is not None else None,
        "null_p95": null_p95,
        "upgrade_target": dict(upgrade_target) if upgrade_target is not None else None,
        "increment": (
            {
                "baseline": list(increment.get("baseline") or []),
                "augmented": list(increment.get("augmented") or []),
            }
            if increment is not None
            else None
        ),
    }


def _increment_verdict(config: Mapping[str, Any], increment: Mapping[str, Any]) -> dict[str, Any]:
    """The paired-increment verdict for one (baseline, augmented) objective.

    Deterministic given ``config`` and the two series, so :func:`verify_verdict_v2`
    can rebuild it (including its bootstrap artifact) from the embedded inputs.
    """
    return paired_increment_verdict(
        baseline=increment["baseline"],
        augmented=increment["augmented"],
        block_length=int(config.get("null_block_length", NULL_BLOCK_LENGTH)),
        n_resamples=_INCREMENT_RESAMPLES,
        seed=int(config.get("null_seed", GATE_V2_NULL_SEED)),
    )


def _not_applicable_upgrade() -> dict[str, Any]:
    return {
        "schema_version": CORR_V2_SCHEMA_VERSION,
        "applicable": False,
        "upgrade_accepted": None,
        "accepted_evidence": None,
        "secondary": None,
        "reason": "not_an_increment_objective",
    }


def envelope_digest(record: Mapping[str, Any]) -> str:
    """Digest of the blocks :func:`verify_verdict_v2` cannot recompute.

    Covers ``config``, ``thresholds``, ``tier_recommendation``, the parallel
    verdict, the whole ``inputs`` block (the embedded curve/return series and
    their metadata such as ``universe_digest``/``initial_cash``) and the
    provenance stamps. Detects *partial* tampering of any of those. It is **not**
    a signature: see :func:`verify_verdict_v2` for the explicit boundary of what
    remains forgeable.
    """
    return _hash({key: record.get(key) for key in _ENVELOPE_FIELDS})


def _concentration_peers(active, hung_sleeves, upgrade_target, increment):
    """Exclude only an exact replaced version, with same-window paired evidence.

    This is an evidence check, not an account mutation or caller authentication.
    Product callers must resolve the target identity from the canonical book.
    """
    if upgrade_target is None:
        return list(hung_sleeves)
    target_id = str(upgrade_target.get("sleeve_id") or "")
    digest = str(upgrade_target.get("definition_digest") or "")
    if not target_id or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("gate_v2_upgrade_target_invalid")
    matches = [s for s in hung_sleeves if s.get("sleeve_id") == target_id]
    if len(matches) != 1 or matches[0].get("definition_digest") != digest:
        raise ValueError("gate_v2_upgrade_target_mismatch")
    target = matches[0]
    if increment is None or list(target.get("dates") or []) != list(active.get("dates") or []):
        raise ValueError("gate_v2_upgrade_pair_window_mismatch")
    pairs = (
        (list(increment.get("baseline") or []), list(target.get("returns") or [])),
        (list(increment.get("augmented") or []), list(active.get("equity_returns") or [])),
    )
    for left, right in pairs:
        if (
            not left
            or len(left) != len(right)
            or not all(abs(float(a) - float(b)) <= 1e-12 for a, b in zip(left, right, strict=True))
        ):
            raise ValueError("gate_v2_upgrade_pair_returns_mismatch")
    return [s for s in hung_sleeves if s.get("sleeve_id") != target_id]


def evaluate_gate_v2(
    *,
    curve_rows: Sequence[Mapping[str, Any]],
    initial_cash: float,
    universe_digest: str,
    benchmark_symbol: str | None = None,
    definition_digest: str | None = None,
    trials_rows: Sequence[Any] = (),
    validation_dirs: Sequence[Any] = (),
    curve_resolver: Any = None,
    legacy_resolver: Any = None,
    increment_objective: Mapping[str, Any] | None = None,
    upgrade_target: Mapping[str, Any] | None = None,
    hung_sleeves: Sequence[Mapping[str, Any]] = (),
    benchmark_returns: Sequence[float] | None = None,
    null_p95: float | None = None,
    v1_passed: bool | None = None,
    scope_tag: str = FAMILY_SCOPE_STRATEGY,
    compatibility_contract: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] = GATE_V2_CONFIG,
) -> dict[str, Any]:
    """Evaluate one candidate under the v2 gate; returns the recompute envelope."""
    active = recompute_active_returns(curve_rows, initial_cash=initial_cash)
    if curve_resolver is None:
        from .family import validation_dir_resolver

        curve_resolver = validation_dir_resolver(validation_dirs)
    family = project_family_v2(
        trials_rows=trials_rows,
        validation_dirs=validation_dirs,
        universe_digest=universe_digest,
        scope_tag=scope_tag,
        curve_resolver=curve_resolver,
        legacy_resolver=legacy_resolver,
        compatibility_contract=compatibility_contract,
    )
    dsr = evaluate_dsr_v2(active=active, family=family, dsr_min=config["dsr_v2_min"], config=config)
    health = health_checks_v2(active=active, config=config)
    concentration_peers = _concentration_peers(
        active, hung_sleeves, upgrade_target, increment_objective
    )
    concentration = concentration_v2(
        active=active,
        hung_sleeves=concentration_peers,
        benchmark_returns=benchmark_returns,
        null_p95=null_p95,
        config=config,
        require_dates=compatibility_contract is not None,
    )
    increment = None
    if increment_objective is not None:
        increment = {
            "baseline": list(increment_objective.get("baseline") or []),
            "augmented": list(increment_objective.get("augmented") or []),
        }
        upgrade = _increment_verdict(config, increment)
    else:
        upgrade = _not_applicable_upgrade()
    grade = grade_v2(
        dsr=dsr,
        health=health,
        concentration=concentration,
        upgrade=upgrade,
        family=family,
        config=config,
    )
    tier = tier_for_grade(grade["grade"])
    v2_passed = bool(
        dsr.get("passed")
        and health.get("passed")
        and concentration.get("passed")
        and (_upgrade_accepted(upgrade) if upgrade.get("applicable") else True)
    )
    conclusion_changed = v1_passed is not None and bool(v1_passed) != v2_passed
    inputs = _build_inputs(
        active=active,
        initial_cash=initial_cash,
        universe_digest=universe_digest,
        benchmark_symbol=benchmark_symbol,
        definition_digest=definition_digest,
        hung_sleeves=hung_sleeves,
        benchmark_returns=benchmark_returns,
        null_p95=null_p95,
        increment=increment,
        upgrade_target=upgrade_target,
    )
    if compatibility_contract is not None:
        inputs["family_contract"] = family["compatibility_contract"]
        inputs["correlation_require_dates"] = True
    record: dict[str, Any] = {
        "schema_version": GATE_V2_SCHEMA_VERSION,
        "config_version": config.get("config_version", CONFIG_VERSION),
        "config": dict(config),
        "authoritative": GATE_V2_AUTHORITATIVE,
        "mode": "parallel_observe_only",
        "formula": "bailey_lopez_de_prado_2014",
        "inputs": inputs,
        "family": family,
        "thresholds": thresholds_block(config),
        "dsr": dsr,
        "health": health,
        "concentration": concentration,
        "upgrade": upgrade,
        "grade": grade,
        "tier_recommendation": {
            "tier": tier,
            "tier_source": "program_rule",
            "allocated_cash": TIER_CAPITAL_USD.get(tier, 0.0),
        },
        "verdict_parallel": {
            "v1_passed": v1_passed,
            "v2_passed": v2_passed,
            "conclusion_changed": conclusion_changed,
        },
        "rng": {
            "descriptor": "numpy.random.Generator(PCG64)",
            "seed": int(config.get("null_seed", GATE_V2_NULL_SEED)),
            "harness": "gate_v2.control.random_control_v2",
        },
        "code": {
            "gate_v2_sources": gate_v2_sources(),
            "v2_code_digest": _hash(gate_v2_sources()),
        },
        "computed_at": datetime.now(UTC).isoformat(),
    }
    record["envelope_digest"] = envelope_digest(record)
    return record


def _recompute_dsr(record: Mapping[str, Any]) -> dict[str, Any]:
    inputs = record["inputs"]
    family = record["family"]
    config = record["config"]
    active = {
        "active_returns": inputs["active_returns"],
        "equity_returns": inputs["equity_returns"],
        "dates": inputs["dates"],
        "n_periods": inputs["n_periods"],
        "initial_cash_rule": inputs["initial_cash_rule"],
    }
    from .dsr_v2 import evaluate_dsr_v2

    return evaluate_dsr_v2(
        active=active, family=family, dsr_min=config["dsr_v2_min"], config=config
    )


def verify_verdict_v2(
    record: Mapping[str, Any], *, trusted_trials=None, curve_resolver=None, legacy_resolver=None
) -> bool:
    """Verify against caller-owned original trials and fresh source resolution.

    Unlike the former mathematical verifier, this returns False without trusted
    context. The original trial ID set, exclusions, required legacy proof type
    and every recomputed member must match. Removing self-described evidence and
    re-signing an envelope cannot downgrade this external-proof requirement.
    """
    if trusted_trials is None or curve_resolver is None:
        return False
    try:
        expected = project_family_v2(
            trials_rows=trusted_trials,
            universe_digest=record["inputs"]["universe_digest"],
            scope_tag=record["family"]["scope_tag"],
            curve_resolver=curve_resolver,
            legacy_resolver=legacy_resolver,
            compatibility_contract=record["inputs"].get("family_contract"),
        )
        if expected != record["family"]:
            return False
        if any(
            not verify_legacy_member(member, legacy_resolver)
            for member in expected["members"]
            if member.get("legacy_evidence")
        ):
            return False
        return verify_verdict_integrity_v2(record)
    except (OSError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return False


def verify_verdict_integrity_v2(record: Mapping[str, Any]) -> bool:
    """Recompute embedded mathematics and content integrity, NEVER authority.

    Covered by recomputation: the active/dates digests, the family member table
    and its digest, the DSR block, the health block, the concentration block, the
    upgrade block (including its bootstrap artifact, re-run from the embedded
    increment series with the record's seed), the grade and the tier. Covered by
    the envelope digest: ``config`` (so an unused-but-plausible key like
    ``config_version`` cannot be edited silently), ``thresholds``,
    ``tier_recommendation`` and the provenance stamps — plus an explicit
    semantic tie of ``allocated_cash`` to ``TIER_CAPITAL_USD``.

    **Explicit boundary — this helper does not authorize.** A writer who rewrites
    *every* covered field consistently (inputs, recomputed blocks and
    ``envelope_digest`` together) produces a self-consistent forgery this
    function accepts: verification is an integrity / partial-tamper check, not
    an authenticity check, and it says nothing about whether the *inputs* were
    honestly measured. ``computed_at``, ``code`` (a disk-relative source hash)
    and ``rng`` are provenance, not evidence. Authenticity is the Owner's
    digest-pinned receipt plus the append-only ledger, not this primitive.
    """
    try:
        inputs = record["inputs"]
        family = record["family"]
        if _hash(inputs["active_returns"]) != inputs["returns_digest"]:
            return False
        if _hash(inputs["dates"]) != inputs["dates_digest"]:
            return False
        expected_family_digest = _hash(family_digest_payload(family))
        if expected_family_digest != family["family_digest"]:
            return False
        if inputs.get("family_contract") is not None and (
            inputs["family_contract"] != family.get("compatibility_contract")
            or inputs.get("correlation_require_dates") is not True
        ):
            return False
        if _recompute_dsr(record) != dict(record["dsr"]):
            return False
        active = {
            "equity_returns": inputs["equity_returns"],
            "n_periods": inputs["n_periods"],
        }
        if health_checks_v2(active=active, config=record["config"]) != dict(record["health"]):
            return False
        active_all = {
            "active_returns": inputs["active_returns"],
            "equity_returns": inputs["equity_returns"],
            "dates": inputs["dates"],
            "n_periods": inputs["n_periods"],
        }
        recomputed_concentration = concentration_v2(
            active=active_all,
            hung_sleeves=_concentration_peers(
                active_all,
                inputs["hung_sleeves"],
                inputs.get("upgrade_target"),
                inputs.get("increment"),
            ),
            benchmark_returns=inputs["benchmark_returns"],
            null_p95=inputs["null_p95"],
            config=record["config"],
            require_dates=inputs.get("correlation_require_dates", False),
        )
        for key in (
            "raw_max",
            "raw_passed",
            "residual_max",
            "null_p95",
            "residual_passed",
            "residual_reason",
            "applicable",
            "passed",
        ):
            if record["concentration"].get(key) != recomputed_concentration.get(key):
                return False
        if inputs.get("correlation_require_dates") and any(
            record["concentration"].get(key) != recomputed_concentration.get(key)
            for key in ("raw_status", "raw_reason", "raw_unavailable_sleeves",
                        "raw_peer_diagnostics", "dates_required", "n_hung_sleeves")
        ):
            return False
        if not _upgrade_matches(record):
            return False
        grade = grade_v2(
            dsr=record["dsr"],
            health=record["health"],
            concentration=record["concentration"],
            upgrade=record["upgrade"],
            family=family,
            config=record["config"],
        )
        if grade != dict(record["grade"]):
            return False
        tier = tier_for_grade(grade["grade"])
        tier_block = record["tier_recommendation"]
        if tier_block.get("tier") != tier:
            return False
        if tier_block.get("tier_source") != "program_rule":
            return False
        if tier_block.get("allocated_cash") != TIER_CAPITAL_USD.get(tier, 0.0):
            return False
        expected_v2 = bool(
            record["dsr"].get("passed")
            and record["health"].get("passed")
            and record["concentration"].get("passed")
            and (
                _upgrade_accepted(record["upgrade"])
                if record["upgrade"].get("applicable")
                else True
            )
        )
        parallel = record["verdict_parallel"]
        if parallel.get("v2_passed") is not expected_v2:
            return False
        if parallel.get("conclusion_changed") is not (
            parallel.get("v1_passed") is not None and bool(parallel["v1_passed"]) is not expected_v2
        ):
            return False
        return envelope_digest(record) == record.get("envelope_digest")
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False


def _upgrade_matches(record: Mapping[str, Any]) -> bool:
    """Re-run the paired increment from the embedded series, or check the absent form."""
    upgrade = record["upgrade"]
    if not upgrade.get("applicable"):
        return upgrade == _not_applicable_upgrade()
    increment = record["inputs"]["increment"]
    if not increment:
        return False
    return dict(upgrade) == _increment_verdict(record["config"], increment)


def append_verdict_v2(
    path: Path, record: Mapping[str, Any], *, enabled: bool | None = None
) -> dict[str, Any]:
    """Append one verdict to the append-only ``verdicts.jsonl`` (the sole write面).

    ``flock(LOCK_EX)`` + ``flush`` + ``fsync``, mirroring the trials ledger. When
    the v2 emission switch is closed (default) this is a no-op: **zero v2 bytes
    reach any location**, which is the L0 invariant.
    """
    if enabled is None:
        enabled = GATE_V2_ENABLED
    if not enabled:
        return {"written": False, "reason": "gate_v2_disabled"}
    import fcntl
    import os

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0, os.SEEK_END)
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return {"written": True, "path": str(path)}


def _scaled_dsr(record: Mapping[str, Any], scale: float) -> tuple[dict[str, Any], str | None]:
    """Rescale the DSR pass line, but never lift a structural failure.

    Returns the rescaled DSR block and, when the original failure was structural,
    the pinned reason (also kept on the block). A structural reason is reported
    rather than silently excluded: the sensitivity table shows *why* a row could
    not be moved, and the conclusion-flip rate is not inflated by a rescale that
    has no meaning.
    """
    dsr = dict(record["dsr"])
    reason = dsr.get("reason")
    if dsr.get("passed") is False and reason in _DSR_NON_NUMERIC_REASONS:
        dsr["passed"] = False
        return dsr, str(reason)
    dsr_min = dsr.get("dsr_min_used")
    dsr["passed"] = bool(
        dsr.get("value") is not None
        and dsr_min is not None
        and float(dsr["value"]) >= float(dsr_min) * float(scale)
    )
    return dsr, None


def evaluate_sensitivity_v2(
    record: Mapping[str, Any], *, scales: Sequence[float] = (0.9, 1.1)
) -> dict[str, Any]:
    """Re-run the grade with each threshold scaled; report the conclusion-flip rate.

    Only *numeric* pass lines move. A record whose DSR block failed for a
    structural reason (family too small / member window too short / invalid
    moments) stays failed at every scale and carries ``pinned_reason``; otherwise
    scaling ``dsr_min_used`` — or a passing record's line — would flip a
    structural failure into a pass (defect G1).
    """
    baseline = record["grade"]["grade"]
    results: list[dict[str, Any]] = []
    for scale in scales:
        dsr, pinned_reason = _scaled_dsr(record, float(scale))
        health = dict(record["health"])
        health["passed"] = _rescale_health(health, float(scale))
        health["reasons"] = [] if health["passed"] else ["scaled_health_failure"]
        concentration = dict(record["concentration"])
        raw_max = concentration.get("raw_max")
        if raw_max is not None:
            concentration["raw_passed"] = bool(
                float(raw_max) <= float(concentration["raw_limit"]) * float(scale)
            )
            concentration["passed"] = bool(concentration["raw_passed"])
        grade = grade_v2(
            dsr=dsr,
            health=health,
            concentration=concentration,
            upgrade=record["upgrade"],
            family=record["family"],
            config=record["config"],
        )
        results.append(
            {
                "scale": float(scale),
                "grade": grade["grade"],
                "changed": grade["grade"] != baseline,
                "pinned_reason": pinned_reason,
            }
        )
    rate = sum(1 for item in results if item["changed"]) / len(results)
    return {"results": results, "flip_rate": rate, "load_bearing": rate > 0.10}


def _rescale_health(health: Mapping[str, Any], scale: float) -> bool:
    psr = health.get("psr_total", {})
    drawdown = health.get("max_drawdown", {})
    volatility = health.get("annual_volatility", {})
    psr_ok = psr.get("value") is not None and float(psr["value"]) > float(psr["min"]) * scale
    dd_ok = (
        drawdown.get("value") is not None
        and float(drawdown["value"]) <= float(drawdown["max"]) * scale
    )
    vol_ok = (
        volatility.get("value") is not None
        and float(volatility["value"]) <= float(volatility["max"]) * scale
    )
    return bool(psr_ok and dd_ok and vol_ok)
