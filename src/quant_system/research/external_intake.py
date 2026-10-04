"""Durable, bounded external research intake under an owner-installed policy.

External text is provenance only. The whitelist compiler owns expressions; the
existing strategy library owns validation and simulated activation. No external
proposal can change policy, issue commands, or authorize a historical candidate.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from quant_system.d34 import qlib_expr
from quant_system.factors.registry import build_factor_registry
from quant_system.research import strategy_library as library
from quant_system.research.intake_evaluation import (
    IncrementObjective,
    compare_increment,
    validate_snapshot,
)
from quant_system.research.intake_evaluation import (
    digest as evaluation_digest,
)
from quant_system.research.strategy_definition import StrategyDefinition, formula_factor_id
from quant_system.research.strategy_library_cli import _number, _validation
from quant_system.research.study_profiles import list_study_profiles

CONTRACT = "hqa.external_research_intake/v1"
MAX_JSON_BYTES = 65_536
_ID = re.compile(r"intake-[0-9a-f]{24}\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
_TERMINAL = {"completed", "failed", "outcome_unknown", "activation_blocked"}


class IntakePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    enabled: bool = False
    auto_enable: bool = False
    admission_mode: Literal["parallel", "authoritative"] = "parallel"
    authorization: Literal["owner-grok-research-2026-09-09"] = "owner-grok-research-2026-09-09"
    max_proposals_per_day: int | None = Field(
        default=3,
        ge=1,
        description="Positive daily proposal limit; null disables the owner-configured daily cap.",
    )
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("intake_schema_version_invalid")
        return value


class StrategySpec(BaseModel):
    """Only execution semantics already supported by the frozen definition kernel."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    symbols: list[str] | None = Field(default=None, min_length=1, max_length=60)
    benchmark_symbol: str = "SPY"
    rebalance: Literal["daily", "weekly", "monthly"] = "monthly"
    top_n: int = Field(default=5, gt=0, le=60)
    normalization: Literal["rank", "zscore"] = "rank"
    selection: Literal["top", "positive_top", "bottom"] = "top"
    max_weight_per_symbol: float = Field(default=1.0, gt=0, le=1)
    target_gross_exposure: float = Field(default=1.0, gt=0, le=1)
    min_order_value: float = Field(default=0.0, ge=0)
    factor_weights: dict[str, float] = Field(default_factory=dict)

    @field_validator("symbols")
    @classmethod
    def us_symbols(cls, values):
        if values is not None and any(
            not re.fullmatch(r"[A-Z][A-Z0-9-]{0,9}(?:\.[A-Z]{1,2})?", v) for v in values
        ):
            raise ValueError("intake_us_symbols_required")
        return values

    @field_validator("benchmark_symbol")
    @classmethod
    def us_benchmark(cls, value):
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{0,9}(?:\.[A-Z]{1,2})?", value):
            raise ValueError("intake_us_symbols_required")
        return value


class UpgradeTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidate_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    sleeve_id: str | None = None
    expected_definition_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    expected_config_version: int | None = Field(default=None, ge=1)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
    source_urls: list[str] = Field(min_length=1, max_length=10)
    source_title: str = Field(min_length=1, max_length=300)
    published_at: str | None = Field(
        description=(
            "ISO date YYYY-MM-DD or datetime with timezone; use null if only year/month "
            "is known and preserve that precision in adaptation_note."
        )
    )
    retrieved_at: str = Field(
        description=(
            "Actual retrieval datetime in ISO 8601 with timezone, e.g. "
            "2026-09-09T10:00:00+08:00. A date alone is invalid; do not invent midnight."
        )
    )
    hypothesis: str = Field(min_length=1, max_length=4000)
    expression: str = Field(min_length=1, max_length=400)
    adaptation_note: str = Field(min_length=1, max_length=4000)
    baseline_factor_ids: list[str] = Field(default_factory=list, max_length=2)
    increment_objective: IncrementObjective | None = None
    strategy_spec: StrategySpec | None = None
    upgrade_target: UpgradeTarget | None = None
    hypothesis_card: dict | None = Field(
        default=None, description="Existing hqa.hypothesis_card/v2 JSON with its original digest",
    )

    @field_validator("hypothesis_card")
    @classmethod
    def existing_hypothesis_card(cls, value):
        from quant_system.research.intake_factor_evaluation import validate_hypothesis_card

        return validate_hypothesis_card(value)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("intake_schema_version_invalid")
        return value

    @field_validator("source_title", "hypothesis", "adaptation_note")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("intake_blank_material")
        return value

    @field_validator("source_urls")
    @classmethod
    def source_links(cls, values):
        for value in values:
            parsed = urlsplit(value)
            if (
                len(value) > 2048
                or parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or any(c.isspace() for c in value)
            ):
                raise ValueError("intake_source_url_invalid")
        if len(set(values)) != len(values):
            raise ValueError("intake_source_url_duplicate")
        return values

    @field_validator("published_at")
    @classmethod
    def publication_date(cls, value):
        if value is not None:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                date.fromisoformat(value)
            else:
                _aware_datetime(value)
        return value

    @field_validator("retrieved_at")
    @classmethod
    def retrieval_date(cls, value):
        _aware_datetime(value)
        return value

    @field_validator("baseline_factor_ids")
    @classmethod
    def distinct_baselines(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("intake_baseline_duplicate")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) for value in values):
            raise ValueError("intake_baseline_invalid")
        return values


def _aware_datetime(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("intake_timestamp_requires_timezone")
    return parsed


def _now():
    return datetime.now(UTC)


def _sha(value):
    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("intake_duplicate_json_key")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("intake_nonfinite_json")


def strict_json(raw: str) -> dict:
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("intake_input_too_large")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("intake_json_invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("intake_json_object_required")
    return value


def root(settings) -> Path:
    return settings.data.data_dir / "research_intake"


def _private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise ValueError("intake_directory_owner_invalid")
    path.chmod(0o700)


def _write(path: Path, value):
    """Atomic, fsynced, owner-only records; never expose proposal text in logs."""
    fd, name = tempfile.mkstemp(prefix=".intake-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_policy(settings) -> IntakePolicy:
    path = root(settings) / "policy.json"
    if not path.exists():
        return IntakePolicy()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("intake_policy_requires_owner_only_regular_file")
    return IntakePolicy.model_validate(strict_json(path.read_text(encoding="utf-8")))


@contextmanager
def _lock(path, *, nonblocking=False):
    with path.open("a+") as stream:
        os.chmod(path, 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _profile():
    return next(p for p in list_study_profiles() if p["id"] == "stocks_momentum_12_2")


def capabilities(settings):
    profile = _profile()
    served_ranges = _served_symbol_ranges(settings, profile["symbols"])
    return {
        "schema_version": 1,
        "policy": read_policy(settings).model_dump(),
        "proposal_schema": Proposal.model_json_schema(),
        "scope": {
            "profile_id": profile["id"],
            "symbols": profile["symbols"],
            "benchmark_symbol": profile["benchmark_symbol"],
            "provider": "futu",
            "interval": "1d",
            "price_adjustment": "qfq",
            "long_only": True,
            "rebalance": "monthly",
            "supported_rebalances": ["daily", "weekly", "monthly"],
            "scope_values_are_defaults": True,
            "top_n": 5,
            "normalization": "rank",
            "factor_weights": "equal_by_default_explicit_strategy_spec_override",
            "commission_bps": 1,
            "slippage_bps": 5,
            "dsr_min": 0.95,
            "max_hung_correlation": 0.7,
            "max_components": 3,
            "max_variants_per_proposal": 2,
            "worker_concurrency": 1,
            "formula_direction": "higher_is_better_use_explicit_negation_for_inverse",
            "historical_scope": "retrospective_not_unseen_holdout",
            "membership_mode": profile["membership_mode"],
            "universe_snapshot_date": profile["universe_snapshot_date"],
            "existing_strategy_window": "paired_evaluation_on_one_frozen_snapshot",
            "strategy_spec": "optional_supported_daily_ohlcv_rule_parameters",
            "hypothesis_card": {
                "schema": "hqa.hypothesis_card/v2", "optional": True,
                "digest_required": True,
                "unsupported_required_fields": "persist_waiting_data_without_running_price_proxy",
                "legacy_v1": "local_formula_only_original_method_unknown",
            },
            "automatic_activation": "new_version_and_predeclared_paired_increment_objective",
            "cost_stress_method": "extra_linear_cost_penalty_on_net_return",
            "cost_stress_exact_replay": False,
            "legacy_net_return_at_2x": "legacy_name_for_extra_linear_cost_stress_not_exact_replay",
        },
        "expression": {
            "fields": ["$" + field for field in sorted(qlib_expr.FIELDS)],
            "unary_functions": sorted(qlib_expr.UNARY_FUNCS),
            "window_functions": sorted(qlib_expr.WINDOW_FUNCS),
            "arithmetic": ["+", "-", "*", "/"],
            "max_length": 400,
            "window_min": qlib_expr.MIN_WINDOW,
            "window_max": qlib_expr.MAX_WINDOW,
            "max_depth": qlib_expr.MAX_DEPTH,
            "max_nodes": qlib_expr.MAX_NODES,
            "Rank_semantics": "time_series_percentile; strategy normalization is cross_sectional",
            "Max_Min_semantics": (
                "trailing window includes the signal session and window-1 preceding "
                "aligned daily sessions"
            ),
            "formation_requirement": (
                "full finite input window determined by compiler; "
                "missing input sessions exclude the score"
            ),
            "price_semantics": "Futu qfq daily close, not CRSP-adjusted price or intraday high",
            "rolling_window_includes_signal_bar": True,
            "Ref_Delta_semantics": "lag/difference by the explicit window; not rolling aggregates",
            "missing_policy": "complete finite input window; exclude nonfinite output",
            "factor_blend_eligibility": "each formula factor uses its frozen spec.lookback",
            "profile_eligibility_note": (
                "max(252, compiled.lookback) belongs to the separate legacy profile study; "
                "do not apply it to this factor_blend intake"
            ),
        },
        "baseline_factors": [
            {"factor_id": m.factor_id, "lookback": m.lookback, "direction": m.direction}
            for m in build_factor_registry().list_metadata()
        ]
        + _formula_baselines(settings),
        # Additive keys only: appended after baseline_factors; they do not bump
        # schema_version and every pre-existing key stays byte-stable.
        "universe": _universe_block(profile),
        "data_availability": {
            "status": served_ranges.get("status"),
            "price_data": {
                "provider": "futu",
                "interval": "1d",
                "price_adjustment": "qfq",
                "fetch_start": _fetch_start(),
                "serving_semantics": "exact_request_verified_snapshots_reused_else_fetched",
                "coverage_semantics": "served_ranges_are_locally_verified_not_provider_promises",
            },
            **served_ranges,
            "provider_readiness": _provider_readiness(settings),
            "as_of": _now().isoformat(),
        },
        "research_guidance": {
            "version": "owner-2026-09-25",
            "scope": "research_direction_only_not_admission_or_capital_authority",
            "novel_or_proprietary_factor_required": False,
            "accepted_research": [
                "published_method", "single_factor", "factor_or_strategy_combination",
            ],
            "objective": "cost_and_risk_aware_increment_to_an_appropriate_benchmark",
            "freeze_before_results": [
                "mechanism", "universe", "direction", "windows", "rebalance", "weights",
                "benchmark", "costs", "validation_partitions", "trial_budget",
            ],
            "default_strategy_spec_is_not_a_universal_research_design": True,
            "tick_requires_new_formula": False,
            "existing_queue": "continue_and_report_without_resubmitting_old_failures",
            "consecutive_failures": "conclude_continue_archive_or_build_data_for_the_fixed_family",
            "missing_fields": "use_original_hypothesis_card_and_specific_data_needs",
            "known_local_batch": {
                "id": "phase3-etf-20260925",
                "preregistration_sha256": (
                    "4434c18ebf46c40df2e0546d0986f9c36b0dbd306384d9bdb87740e9c77b2bf2"
                ),
                "hypotheses": ["B_MOM", "B_SMA", "B_COMBINED"],
                "status": "archived_fixed_hypotheses_increment_not_established",
                "paper_enabled": False,
                "repeat_same_experiment": False,
            },
        },
    }


def _spec_constraint(field_name, constraint_name):
    """Read one StrategySpec constraint from pydantic field metadata; None if unreadable."""
    try:
        for item in StrategySpec.model_fields[field_name].metadata:
            value = getattr(item, constraint_name, None)
            if type(value) in (int, float):
                return value
    except (AttributeError, KeyError, TypeError):
        return None
    return None


def _universe_block(profile) -> dict:
    """Pure projection of the frozen study profile and StrategySpec limits; no I/O."""
    spec_defaults = StrategySpec()
    symbols_max = _spec_constraint("symbols", "max_length")
    top_n_max = _spec_constraint("top_n", "le")
    return {
        "profile_id": profile["id"],
        "membership_mode": profile["membership_mode"],
        "universe_snapshot_date": profile["universe_snapshot_date"],
        "symbols": profile["symbols"],
        "peer_symbols": profile["peer_symbols"],
        "defensive_symbol": profile["defensive_symbol"],
        "benchmark_symbol": profile["benchmark_symbol"],
        "symbol_source": "static_registry_snapshot_not_index_membership",
        "strategy_spec_limits": {
            "symbols_max": 60 if symbols_max is None else symbols_max,
            "symbol_pattern": r"[A-Z][A-Z0-9-]{0,9}(?:\.[A-Z]{1,2})?",
            "top_n_max": 60 if top_n_max is None else top_n_max,
            "rebalance_allowed": ["daily", "weekly", "monthly"],
            "normalization_allowed": ["rank", "zscore"],
            "selection_allowed": ["top", "positive_top", "bottom"],
            "max_weight_per_symbol": {
                "gt": _spec_constraint("max_weight_per_symbol", "gt"),
                "le": _spec_constraint("max_weight_per_symbol", "le"),
                "default": spec_defaults.max_weight_per_symbol,
            },
            "target_gross_exposure": {
                "gt": _spec_constraint("target_gross_exposure", "gt"),
                "le": _spec_constraint("target_gross_exposure", "le"),
                "default": spec_defaults.target_gross_exposure,
            },
            "min_order_value": {
                "ge": _spec_constraint("min_order_value", "ge"),
                "default": spec_defaults.min_order_value,
            },
            "defaults_when_omitted": {
                "symbols": "profile_universe_when_omitted",
                "benchmark_symbol": spec_defaults.benchmark_symbol,
                "rebalance": spec_defaults.rebalance,
                "top_n": spec_defaults.top_n,
                "normalization": spec_defaults.normalization,
                "selection": spec_defaults.selection,
                "max_weight_per_symbol": spec_defaults.max_weight_per_symbol,
                "target_gross_exposure": spec_defaults.target_gross_exposure,
                "min_order_value": spec_defaults.min_order_value,
                "factor_weights": "equal_by_default_explicit_strategy_spec_override",
            },
        },
        "limitations": profile["limitations"],
    }


def _fetch_start() -> str:
    """Mirror the frozen evaluation-library fetch start; degrade to the same literal."""
    try:
        from quant_system.research.strategy_study_service import FETCH_START

        return FETCH_START
    except Exception:
        return "2015-01-01"


def _served_symbol_ranges(settings, symbols) -> dict:
    """Locally verified per-symbol ranges from the equity bar cache; never creates the file."""
    try:
        base = Path(getattr(settings.data, "duckdb_path", Path("data/quant_system.duckdb")))
        path = base.parent / "futu_equity_bars.duckdb"
    except Exception:
        return {
            "status": "unavailable",
            "reason": "served_ranges_unreadable",
            "served_symbol_ranges": [],
        }
    if not path.exists():
        return {
            "status": "unavailable",
            "reason": "equity_bar_cache_not_initialized",
            "served_symbol_ranges": [],
        }
    try:
        import duckdb

        placeholders = ", ".join("?" for _ in symbols)
        with duckdb.connect(str(path), read_only=True) as connection:
            rows = connection.execute(
                f"""
                SELECT symbol, MIN(session_date), MAX(session_date), COUNT(*)
                FROM equity_bars
                WHERE provider = ?
                  AND interval = ?
                  AND adjustment = ?
                  AND symbol IN ({placeholders})
                GROUP BY symbol
                ORDER BY symbol
                """,
                ["futu", "1d", "qfq", *symbols],
            ).fetchall()
    except Exception:
        return {
            "status": "unavailable",
            "reason": "served_ranges_unreadable",
            "served_symbol_ranges": [],
        }
    return {
        "status": "available",
        "served_symbol_ranges": [
            {
                "symbol": symbol,
                "first_served_date": first,
                "last_served_date": last,
                "sessions": sessions,
            }
            for symbol, first, last, sessions in rows
        ],
    }


def _provider_readiness(settings) -> list:
    """Best-effort mirror of the data-source check record; empty on any failure."""
    try:
        from quant_system.research.data_source_checks import read_checks

        return read_checks(settings)["sources"]
    except Exception:
        return []


def _job_path(settings, job_id):
    if not _ID.fullmatch(job_id):
        raise ValueError("intake_job_id_invalid")
    return root(settings) / "jobs" / (job_id + ".json")


def _load_job(settings, job_id):
    value = json.loads(_job_path(settings, job_id).read_text(encoding="utf-8"))
    if value["job_id"] != job_id or _sha(value["proposal"]) != value["payload_sha256"]:
        raise ValueError("intake_record_integrity_failed")
    if _sha(value["plans"]) != value["plans_sha256"]:
        raise ValueError("intake_plan_integrity_failed")
    from quant_system.research.intake_factor_evaluation import validate_research_design

    validate_research_design(value)
    markers = [plan.get("origin", {}).get("admission_protocol_digest") for plan in value["plans"]]
    if "admission_protocol" in value or any(markers):
        from quant_system.research import admission_v2

        protocol = value.get("admission_protocol")
        admission_v2.verify_protocol(
            protocol, job_id=job_id, proposal_digest=value["payload_sha256"],
            current_code=False, current_config=False,
        )
        if any(marker != protocol["protocol_digest"] for marker in markers):
            raise ValueError("admission_v2_plan_protocol_mismatch")
    return value


def _jobs(settings):
    return [
        _load_job(settings, path.stem) for path in sorted((root(settings) / "jobs").glob("*.json"))
    ]


def _summary(job, *, settings=None):
    summary = {
        key: job.get(key)
        for key in (
            "job_id",
            "proposal_id",
            "payload_sha256",
            "status",
            "created_at",
            "updated_at",
            "policy_snapshot",
            "formula_factor_id",
            "results",
            "error",
            "lease",
            "events",
            "comparison_status",
            "provenance_verification",
            "evaluation",
            "increment",
        )
    }
    if "admission_protocol" in job:
        summary["admission_protocol"] = job["admission_protocol"]
    summary["comparison_status_recorded"] = job.get("comparison_status")
    if job.get("comparison_status") == "available":
        evaluation = job.get("evaluation") or {}
        pair = [r for r in job.get("results", []) if r.get("variant") in {"baseline", "augmented"}]
        bound_pair = (
            bool(evaluation.get("evaluation_id"))
            and bool(evaluation.get("prices_sha256"))
            and len(pair) == 2
            and all(r.get("evaluation") == evaluation for r in pair)
            and compare_increment({**job, "proposal": {}}).get("comparable") is True
        )
        if not bound_pair:
            # This is a read projection, not a rewrite or a retrospective
            # admission decision about already completed historical jobs.
            summary["comparison_status"] = "legacy_unpaired"
            summary["comparison_note"] = "archived_available_without_frozen_paired_evidence"
    # Keep persisted status/CLI exit semantics, but distinguish a research rejection
    # from an operational error even for receipts created before this field existed.
    outcome = job.get("status")
    if (job.get("admission_protocol") or {}).get("mode") == "authoritative":
        primary = next((r for r in job.get("results", []) if r.get("variant") != "baseline"), {})
        tier_status = (primary.get("admission_v2") or {}).get("status")
        if tier_status in {"recorded", "shadow"}:
            outcome = "unfunded_record" if tier_status == "recorded" else "shadow_evidence"
    if outcome == "failed":
        results = job.get("results", [])
        quality_rejected = (
            not job.get("error")
            and bool(results)
            and all(
                r.get("phase") == "done"
                and not r.get("error")
                and r.get("status") in {"validated", "paper_running", "validation_failed"}
                and (r.get("validation") or {}).get("run_id")
                for r in results
            )
            and any(
                r.get("status") == "validation_failed"
                and (r.get("validation") or {}).get("blockers")
                for r in results
            )
        )
        outcome = "quality_rejected" if quality_rejected else "errored"
    summary["outcome"] = outcome
    from quant_system.research.intake_factor_evaluation import (
        evaluation_chain,
        verified_evaluation_chain,
    )

    summary["evaluation_chain"] = (
        verified_evaluation_chain(settings, job) if settings is not None else evaluation_chain(job)
    )
    summary["increment_scope"] = "recorded_result_current_evidence_in_evaluation_chain"
    return summary


def _diagnostics(settings, result):
    """Read scalar diagnostics from this exact archived receipt, including rejects."""
    try:
        run_id = result["validation"]["run_id"]
        if not re.fullmatch(r"validation-[0-9a-f]{32}", run_id):
            raise ValueError("invalid_receipt_identity")
        path = library._directory(settings, result["strategy_id"]) / "validations" / run_id
        raw = (path / "validation.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != result["validation_sha256"]:
            raise ValueError("receipt_changed")
        receipt = json.loads(raw)
        if (
            receipt.get("run_id") != run_id
            or receipt.get("definition_digest") != result["definition_digest"]
        ):
            raise ValueError("receipt_identity_mismatch")
        gates = receipt.get("gates") or {}
        return {
            "status": "available",
            "binding": "archived_validation_sha256_not_revalidation",
            "dsr": {
                key: _number((gates.get("dsr") or {}).get(key))
                for key in ("value", "n_trials", "threshold_sr", "dsr_min")
            },
            "cost": {
                **{
                    key: (gates.get("cost") or {})[key]
                    for key in ("method", "exact_replay")
                    if key in (gates.get("cost") or {})
                },
                **{
                    key: _number((gates.get("cost") or {}).get(key))
                    for key in (
                        "net_return_at_2x",
                        "cost_drag_annual_1x",
                        "multiplier",
                        "cost_bps",
                        "extra_cost_multiplier",
                    )
                },
            },
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"status": "unavailable", "reason": "bound_validation_diagnostics_unavailable"}


def show(settings, job_id):
    summary = _summary(_load_job(settings, job_id), settings=settings)
    summary["results"] = [
        {**result, "diagnostics": _diagnostics(settings, result)} for result in summary["results"]
    ]
    return summary


def list_jobs(settings):
    return {"items": [_summary(job, settings=settings) for job in _jobs(settings)]}


def sync_report(settings):
    """Export all persisted outcomes for cloud reconciliation; never resume work.

    The digest excludes capture time so a consumer can detect changed receipts.
    Capture is not cloud acknowledgement or a live paper-performance check.
    """
    items = []
    counts = {}
    for job in _jobs(settings):
        summary = _summary(job, settings=settings)
        outcome = summary["outcome"]
        counts[outcome] = counts.get(outcome, 0) + 1
        item = {
            key: summary.get(key)
            for key in (
                "job_id", "proposal_id", "payload_sha256", "created_at", "updated_at",
                "status", "outcome", "error", "comparison_status", "increment",
            )
        }
        chain = summary.get("evaluation_chain") or {}
        item["increment"] = chain.get("portfolio_increment")
        item["increment_scope"] = "verified_archived_receipts"
        if item.get("comparison_status") == "available" and not (
            (item["increment"] or {}).get("comparable")
        ):
            item["comparison_status"] = "partial"
        item["factor_evaluation"] = {
            "status": (chain.get("factor_evaluation") or {}).get("status"),
            "reason": (chain.get("factor_evaluation") or {}).get("reason"),
            "receipt_sha256": chain.get("factor_receipt_sha256"),
            "design_digest": (job.get("research_design") or {}).get("design_digest"),
        }
        item["record_sha256"] = _sha(job)
        item["evaluation_id"] = (summary.get("evaluation") or {}).get("evaluation_id")
        item["results"] = [
            {
                **{key: result.get(key) for key in (
                    "variant", "phase", "status", "error", "strategy_id", "definition_digest",
                    "candidate_id", "sleeve_id", "validation_sha256",
                )},
                "validation_run_id": (result.get("validation") or {}).get("run_id"),
                "blockers": (result.get("validation") or {}).get("blockers", []),
            }
            for result in summary.get("results") or []
        ]
        items.append(item)
    items.sort(key=lambda item: (item.get("created_at") or "", item["job_id"]))
    content = {"policy": read_policy(settings).model_dump(), "items": items}
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "persisted_intake_receipts_not_live_paper_state",
        "ledger_root": str(root(settings).resolve()),
        "cloud_acknowledged": False,
        "total_jobs": len(items),
        "counts_by_outcome": counts,
        "latest_job_updated_at": max(
            (item["updated_at"] for item in items if item.get("updated_at")), default=None
        ),
        "content_sha256": _sha(content),
        **content,
    }


def _formula_baselines(settings):
    from quant_system.research.factor_catalog import formula_components

    return formula_components(settings)


def _replacement_plans(proposal, job_id, proposal_digest, target):
    """The baseline is the exact old recipe, never a reconstruction from factor IDs."""
    from quant_system.research.fingerprint_grading import frozen_definition_identity

    old = frozen_definition_identity(target["definition"])
    if old.kind != "factor_blend" or proposal.increment_objective is None:
        raise ValueError("intake_replacement_requires_frozen_blend_and_objective")
    if (proposal.baseline_factor_ids
            and proposal.baseline_factor_ids != [f.factor_id for f in old.factors]):
        raise ValueError("intake_replacement_baseline_mismatch")
    spec = proposal.strategy_spec
    if spec is not None:
        for key in spec.model_fields_set - {"factor_weights"}:
            actual = list(old.symbols) if key == "symbols" else getattr(old, key)
            if getattr(spec, key) != actual:
                raise ValueError("intake_replacement_execution_contract_changed")
    compiled = qlib_expr.compile_qlib_expr(proposal.expression)
    factor_id = formula_factor_id(compiled.qlib)
    factors = [f.model_dump(mode="json") for f in old.factors]
    if factor_id in {f["factor_id"] for f in factors}:
        raise ValueError("intake_replacement_factor_already_present")
    factors.append({"factor_id": factor_id, "expression": compiled.qlib,
                    "lookback": compiled.lookback, "direction": "higher_is_better", "weight": 1.0})
    weights = spec.factor_weights if spec else {}
    if set(weights) - {f["factor_id"] for f in factors}:
        raise ValueError("intake_weight_factor_unknown")
    for component in factors:
        component["weight"] = weights.get(component["factor_id"], component["weight"])
    fields = old.model_dump(mode="json", exclude={"content_digest", "source_fingerprints"})
    # A changed shared engine requires a new baseline validation on current
    # code. The original target is only identity evidence and is never executed.
    baseline = StrategyDefinition(**fields)
    fields.update(title=f"Grok {proposal.proposal_id} / replacement", factors=factors)
    augmented = StrategyDefinition(**fields)
    plans = []
    for variant, definition in (("baseline", baseline), ("augmented", augmented)):
        plans.append({
            "variant": variant, "activation_eligible": variant == "augmented",
            "strategy_id": "strategy-" + definition.content_digest[:24],
            "definition_digest": definition.content_digest,
            "history_start": definition.history_start,
            "payload": definition.model_dump(mode="json", exclude={"history_start"}),
            "origin": {"type": "external_intake", "job_id": job_id,
                       "proposal_sha256": proposal_digest, "variant": variant,
                       "start": "2018-01-01",
                       "end": (_now().date() - timedelta(days=1)).isoformat(),
                       "historical_scope": "retrospective_not_unseen_holdout",
                       "replacement_target": target["replacement_target"],
                       "baseline_revalidation": {
                           "original_definition_digest": old.content_digest,
                           "original_source_sha256": target["source_sha256"],
                           "original_source_fingerprints": dict(old.source_fingerprints),
                           "current_baseline_digest": baseline.content_digest,
                           "historical_validation_reused": False,
                       }},
        })
    return plans, factor_id


def _plans(proposal, job_id, proposal_digest, settings=None, *, replacement=None):
    if replacement is not None:
        return _replacement_plans(proposal, job_id, proposal_digest, replacement)
    compiled = qlib_expr.compile_qlib_expr(proposal.expression)
    registry = {m.factor_id: m for m in build_factor_registry().list_metadata()}
    formulas = {r["factor_id"]: r for r in _formula_baselines(settings)} if settings else {}
    if any(
        identifier not in registry and identifier not in formulas
        for identifier in proposal.baseline_factor_ids
    ):
        raise ValueError("intake_baseline_not_registered")
    base = [
        (
            {
                "factor_id": identifier,
                "lookback": registry[identifier].lookback,
                "direction": registry[identifier].direction,
                "weight": 1.0,
            }
            if identifier in registry
            else {
                key: value
                for key, value in formulas[identifier].items()
                if key
                in {
                    "factor_id",
                    "lookback",
                    "direction",
                    "expression",
                    "factor_version",
                    "source_digest",
                }
            }
        )
        for identifier in proposal.baseline_factor_ids
    ]
    factor = {
        "factor_id": formula_factor_id(compiled.qlib),
        "expression": compiled.qlib,
        "lookback": compiled.lookback,
        "direction": "higher_is_better",
        "weight": 1.0,
    }
    variants = (
        [("baseline", base), ("augmented", [*base, factor])] if base else [("formula", [factor])]
    )
    profile = _profile()
    spec = proposal.strategy_spec or StrategySpec()
    allowed_ids = {*proposal.baseline_factor_ids, factor["factor_id"]}
    if set(spec.factor_weights) - allowed_ids:
        raise ValueError("intake_weight_factor_unknown")
    for component in [*base, factor]:
        component["weight"] = spec.factor_weights.get(component["factor_id"], 1.0)
    parameters = spec.model_dump(exclude={"symbols", "factor_weights"})
    plans = []
    for label, factors in variants:
        definition = StrategyDefinition(
            kind="factor_blend",
            title=f"Grok {proposal.proposal_id} / {label}",
            symbols=spec.symbols or profile["symbols"],
            history_start="2015-01-01",
            factors=factors,
            **parameters,
        )
        payload = definition.model_dump(mode="json", exclude={"history_start"})
        plans.append(
            {
                "variant": label,
                "activation_eligible": label != "baseline",
                "strategy_id": "strategy-" + definition.content_digest[:24],
                "definition_digest": definition.content_digest,
                "payload": payload,
                "origin": {
                    "type": "external_intake",
                    "job_id": job_id,
                    "proposal_sha256": proposal_digest,
                    "variant": label,
                    "start": "2018-01-01",
                    "end": (_now().date() - timedelta(days=1)).isoformat(),
                    "historical_scope": "retrospective_not_unseen_holdout",
                },
            }
        )
    return plans, factor["factor_id"]


def submit(settings, raw):
    proposal = Proposal.model_validate(raw)
    body = proposal.model_dump(mode="json")
    # Preserve v1 idempotency for stored proposals created before these fields.
    for key in ("increment_objective", "strategy_spec", "upgrade_target", "hypothesis_card"):
        if body[key] is None:
            body.pop(key)
    digest = _sha(body)
    job_id = "intake-" + hashlib.sha256(proposal.proposal_id.encode()).hexdigest()[:24]
    policy = read_policy(settings)
    if not policy.enabled:
        raise ValueError("intake_paused")
    _private_directory(root(settings))
    _private_directory(root(settings) / "jobs")
    with _lock(root(settings) / "queue.lock"):
        path = _job_path(settings, job_id)
        if path.exists():
            existing = _load_job(settings, job_id)
            if existing["payload_sha256"] != digest:
                raise ValueError("intake_proposal_id_conflict")
            return {**_summary(existing, settings=settings), "duplicate": True}
        policy = read_policy(settings)
        if not policy.enabled:
            raise ValueError("intake_paused")
        today = _now().astimezone(ZoneInfo(policy.timezone)).date().isoformat()
        if (
            policy.max_proposals_per_day is not None
            and sum(job["budget_day"] == today for job in _jobs(settings))
            >= policy.max_proposals_per_day
        ):
            raise ValueError("intake_daily_budget_exhausted")
        from quant_system.research.intake_factor_evaluation import (
            _unsupported_fields,
            freeze_research_design,
        )

        if proposal.hypothesis_card and _unsupported_fields(proposal.hypothesis_card):
            # Preserve the source formula and its data needs before invoking the
            # OHLCV compiler. A fundamental method must not invent a price proxy
            # merely to obtain a durable waiting-data receipt.
            now = _now().isoformat()
            job = {
                "job_id": job_id, "proposal_id": proposal.proposal_id,
                "payload_sha256": digest, "proposal": body, "plans": [],
                "plans_sha256": _sha([]), "formula_factor_id": None,
                "policy_snapshot": policy.model_dump(), "budget_day": today,
                "status": "waiting_data", "created_at": now, "updated_at": now,
                "results": [], "error": "intake_hypothesis_fields_unavailable", "lease": None,
                "comparison_status": "not_requested",
                "provenance_verification": "submitted_not_independently_fetched",
                "events": [{"at": now, "state": "waiting_data"}],
                "research_design": freeze_research_design(proposal, []),
            }
            _write(path, job)
            return {**_summary(job, settings=settings), "duplicate": False}
        replacement = None
        if proposal.upgrade_target is not None:
            from quant_system.execution.strategy_replacement import inspect_replacement_target

            request = proposal.upgrade_target
            replacement = inspect_replacement_target(
                settings, candidate_id=request.candidate_id, sleeve_id=request.sleeve_id,
            )
            target = replacement["replacement_target"]
            if (
                request.expected_definition_digest is not None
                and request.expected_definition_digest != target["definition_digest"]
                or request.expected_config_version is not None
                and request.expected_config_version != target["config_version"]
            ):
                raise ValueError("intake_replacement_target_changed")
        plans, factor_id = _plans(proposal, job_id, digest, settings, replacement=replacement)
        from quant_system.research import admission_v2
        from quant_system.research.admission_activation import protocol_binding

        activation = protocol_binding(settings, plans=plans)
        # A valid single-window stage cannot freeze another date/rule into its
        # authority. That proposal can still be researched under parallel gates.
        installed = protocol_binding(settings) if activation is None else activation
        mode = "authoritative" if activation else (
            "parallel" if installed is not None else policy.admission_mode
        )
        protocol = admission_v2.freeze_protocol(
            job_id, digest, mode=mode,
            intent={"kind": "replacement", "target": replacement["replacement_target"]}
            if replacement is not None else None,
            activation=activation,
        )
        for plan in plans:
            plan["origin"]["admission_protocol_digest"] = protocol["protocol_digest"]
        now = _now().isoformat()
        job = {
            "job_id": job_id,
            "proposal_id": proposal.proposal_id,
            "payload_sha256": digest,
            "proposal": body,
            "admission_protocol": protocol,
            "plans": plans,
            "plans_sha256": _sha(plans),
            "formula_factor_id": factor_id,
            "policy_snapshot": policy.model_dump(),
            "budget_day": today,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "results": [],
            "error": None,
            "lease": None,
            "comparison_status": "pending" if len(plans) == 2 else "not_requested",
            "provenance_verification": "submitted_not_independently_fetched",
            "events": [{"at": now, "state": "queued"}],
        }
        job["research_design"] = freeze_research_design(proposal, plans)
        _write(path, job)
    return {**_summary(job, settings=settings), "duplicate": False}


def _persist(settings, job, event):
    job["updated_at"] = _now().isoformat()
    job["events"].append({"at": job["updated_at"], "state": event})
    _write(_job_path(settings, job["job_id"]), job)


def _error(exc):
    code = getattr(exc, "code", str(exc))
    return code if isinstance(code, str) and _CODE.fullmatch(code) else "intake_operation_failed"


def _capture(result, entry):
    if (
        entry.get("strategy_id") != result["strategy_id"]
        or entry.get("definition_digest") != result["definition_digest"]
    ):
        raise ValueError("intake_strategy_identity_mismatch")
    result.update(
        status=entry["status"],
        validation=_validation(entry.get("validation")),
        validation_sha256=entry.get("validation_sha256"),
        candidate_id=entry.get("candidate_id"),
        sleeve_id=entry.get("sleeve_id"),
        error=_error(ValueError(entry["error"])) if entry.get("error") else None,
        execution_ready=entry.get("execution_ready"),
    )
    if entry.get("evaluation"):
        result["evaluation"] = entry["evaluation"]
    if "admission_v2" in entry:
        result["admission_v2"] = entry["admission_v2"]
    if "qualification_flow" in entry:
        result["qualification_flow"] = entry["qualification_flow"]
    for key in ("replacement", "replacement_id", "replaced_by", "replaces"):
        if key in entry:
            result[key] = entry[key]
    origin = entry.get("origin") or {}
    validation = entry.get("validation") or {}
    result["evaluation_calendar_digest"] = validation.get("evaluation_calendar_digest")
    result["window"] = {
        "start": validation.get("start") or origin.get("start"),
        "end": validation.get("end") or origin.get("end"),
        "historical_scope": "retrospective_not_unseen_holdout",
    }


def _read_existing(settings, strategy_id):
    try:
        return library.read_strategy(settings, strategy_id)
    except FileNotFoundError:
        return None


def _activation_receipt(result):
    return {key: result.get(key) for key in ("validation_sha256", "candidate_id", "evaluation")}


def _activation_confirmed(entry, result):
    return (
        entry is not None
        and entry.get("status") == "paper_running"
        and bool(entry.get("sleeve_id"))
        and all(
            value is not None and entry.get(key) == value
            for key, value in _activation_receipt(result).items()
        )
    )


def _owned(entry, plan):
    # The origin is written atomically by the strategy library's existing
    # write.lock. Preflight absence cannot prove which concurrent caller created it.
    return entry.get("origin") == plan["origin"]


def _save_plan(settings, plan):
    definition = StrategyDefinition(
        history_start=plan.get("history_start", "2015-01-01"), **plan["payload"],
    )
    # compose_strategy uses this same immutable save primitive. Passing the
    # intake origin here binds creation ownership and the frozen historical
    # window inside its write lock, without mutating an existing strategy.
    return library._save_definition(settings, definition, plan["origin"])


def _prepare_evaluation(settings, job):
    """Fetch once per job; both variants and retries consume these exact bytes."""
    if job.get("evaluation"):
        validate_snapshot(settings, job["evaluation"])
        return job["evaluation"]
    directory = root(settings) / "evaluations" / job["job_id"]
    _private_directory(directory)
    manifest = directory / "snapshot.json"
    if manifest.exists():
        evaluation = strict_json(manifest.read_text())
        validate_snapshot(settings, evaluation)
    else:
        plan = job["plans"][0]
        symbols = list(
            dict.fromkeys(
                [
                    *plan["payload"]["symbols"],
                    plan["payload"]["benchmark_symbol"],
                ]
            )
        )
        prices, _ = library._collect_prices(settings, symbols, plan["origin"]["end"])
        path = directory / "prices.parquet"
        prices.to_parquet(path, index=False)
        path.chmod(0o600)
        evaluation = {
            "job_id": job["job_id"],
            "plans_sha256": job["plans_sha256"],
            "prices_path": str(path.resolve()),
            "prices_sha256": library._file_hash(path),
            "start": plan["origin"]["start"],
            "end": plan["origin"]["end"],
            "symbols": symbols,
            "cash": 10_000,
            "commission_bps": 1,
            "slippage_bps": 5,
        }
        evaluation["evaluation_id"] = "evaluation-" + evaluation_digest(evaluation)
        _write(manifest, evaluation)
    if evaluation["plans_sha256"] != job["plans_sha256"]:
        raise ValueError("intake_evaluation_plan_changed")
    job["evaluation"] = evaluation
    _persist(settings, job, "evaluation_frozen")
    return evaluation


def _process_plan(settings, job, plan):
    result = next((r for r in job["results"] if r["variant"] == plan["variant"]), None)
    refresh_admission = result is not None and result["phase"] == "admission_waiting"
    if result is not None and result["phase"] in {"done", "activation_blocked"}:
        return
    if result is None:
        result = {
            "variant": plan["variant"],
            "strategy_id": plan["strategy_id"],
            "definition_digest": plan["definition_digest"],
            "phase": "compose_started",
            "created_by_intake": False,
            "validation_started_by_intake": False,
            "last_action": "compose",
            "status": "pending",
            "error": None,
        }
        job["results"].append(result)
        _persist(settings, job, plan["variant"] + ":compose_started")
        entry = _save_plan(settings, plan)
        _capture(result, entry)
        result["created_by_intake"] = _owned(entry, plan)
        result["phase"] = "composed"
        _persist(settings, job, plan["variant"] + ":composed")
    else:
        entry = _read_existing(settings, plan["strategy_id"])
        if entry is None:
            result.update(phase="outcome_unknown", error="intake_strategy_outcome_unknown")
            _persist(settings, job, plan["variant"] + ":outcome_unknown")
            return
        result["created_by_intake"] = _owned(entry, plan)
        if result.get("last_action") in {"enable", "replace"}:
            if _activation_confirmed(entry, result):
                _capture(result, entry)
                result.update(phase="done", error=None)
                _persist(settings, job, plan["variant"] + ":activation_reconciled")
            elif result.get("last_action") == "enable":
                result.update(phase="outcome_unknown", error="intake_activation_not_confirmed")
            if result.get("last_action") == "enable" or result["phase"] == "done":
                return
        if result.get("last_action") == "validate":
            archived = library.find_evaluation(settings, plan["strategy_id"], job["evaluation"])
            if archived is not None:
                entry = archived
                _capture(result, entry)
                result.update(phase="validated", error=None)
            elif library.evaluation_recovery_ready(
                settings, plan["strategy_id"], job["evaluation"]
            ):
                result.update(phase="composed", error=None)
                _persist(settings, job, plan["variant"] + ":computation_resumable")
            else:
                result.update(phase="outcome_unknown", error="intake_computation_liveness_unknown")
                _persist(settings, job, plan["variant"] + ":outcome_unknown")
                return
        if result["phase"] == "compose_started":
            result["phase"] = "composed"
        if refresh_admission:
            entry = library.refresh_admission(
                settings, result["strategy_id"], job["evaluation"], job["admission_protocol"],
                publish_entry=result["created_by_intake"] and plan["activation_eligible"],
            )
            _capture(result, entry)
    if result["phase"] == "composed":
        if not read_policy(settings).enabled:
            raise ValueError("intake_paused")
        result.update(
            phase="validate_started", validation_started_by_intake=True, last_action="validate"
        )
        _persist(settings, job, plan["variant"] + ":validate_started")
        entry = library.validate_strategy(
            settings,
            result["strategy_id"],
            result["definition_digest"],
            evaluation=job["evaluation"],
            publish_entry=result["created_by_intake"] and plan["activation_eligible"],
            **({"admission_context": job["admission_protocol"]}
               if "admission_protocol" in job else {}),
        )
        _capture(result, entry)
    if entry["status"] not in {"validated", "validation_failed", "paper_running"}:
        result.update(phase="outcome_unknown", error="intake_existing_strategy_requires_review")
        _persist(settings, job, plan["variant"] + ":outcome_unknown")
        return
    result["phase"] = "validated"
    _persist(settings, job, plan["variant"] + ":validation_recorded")
    authoritative = (job.get("admission_protocol") or {}).get("mode") == "authoritative"
    replacement = (
        (job.get("admission_protocol", {}).get("intent") or {}).get("kind") == "replacement"
    )
    if replacement and not authoritative and plan["activation_eligible"]:
        result.update(
            phase="done", error=None, activation_note="replacement_parallel_research_only",
        )
        _persist(settings, job, plan["variant"] + ":replacement_parallel_research_only")
        return
    if authoritative and plan["activation_eligible"]:
        ref = result.get("admission_v2") or {}
        if ref.get("status") == "not_evaluated" or not ref:
            from quant_system.research.admission_activation import FROZEN_SCOPE_REJECTIONS

            refused = [
                str(reason)
                for reason in ref.get("reasons") or []
                if reason in FROZEN_SCOPE_REJECTIONS
            ]
            if refused:
                # An input bound outside the frozen scope has no retry that could
                # ever succeed, so it must not stay in a waiting state.
                result.update(phase="activation_blocked", error=refused[0])
                _persist(settings, job, plan["variant"] + ":activation_blocked")
                return
            result.update(phase="admission_waiting", error="admission_v2_evidence_incomplete")
            _persist(settings, job, plan["variant"] + ":admission_waiting")
            return
        if ref.get("validated_tier") != "T2" or ref.get("status") != "passed":
            result.update(phase="done", error=None)
            _persist(settings, job, plan["variant"] + ":unfunded_research_tier")
            return
    policy = read_policy(settings)
    authorized_version = (
        job["policy_snapshot"]["auto_enable"]
        and plan["activation_eligible"]
        and result["created_by_intake"]
        and result["validation_started_by_intake"]
        and entry["status"] == "validated"
    )
    if authorized_version and (not policy.enabled or not policy.auto_enable):
        result["phase"] = "validated_waiting_policy"
        _persist(settings, job, plan["variant"] + ":validated_waiting_policy")
        return
    if authorized_version:
        from quant_system.research.admission_activation import (
            capital_requires_authoritative_job,
        )

        if capital_requires_authoritative_job(settings, job.get("admission_protocol")):
            result.update(phase="activation_blocked", error="activation_parallel_capital_blocked")
            _persist(settings, job, plan["variant"] + ":activation_blocked")
            return
        job["increment"] = compare_increment(job)
        if not (authoritative and len(job["plans"]) == 1) and not job["increment"]["passed"]:
            result.update(phase="activation_blocked", error=job["increment"]["reason"])
            _persist(settings, job, plan["variant"] + ":activation_blocked")
            return
        action = "replace" if replacement else "enable"
        result.update(phase=action + "_started", last_action=action)
        _persist(settings, job, plan["variant"] + ":" + action + "_started")
        # The existing service rechecks validation digest, limits, account and
        # scheduler readiness. A refusal stays recorded; it is never bypassed.
        try:
            operation = library.replace_strategy if replacement else library.enable_strategy
            entry = operation(
                settings,
                result["strategy_id"],
                result["definition_digest"],
                expected_receipt=_activation_receipt(result),
                **({"expected_admission_sha": result["admission_v2"]["sha256"]}
                   if "admission_v2" in result else {}),
            )
            if not _activation_confirmed(entry, result):
                raise ValueError("intake_activation_not_confirmed")
            _capture(result, entry)
        except Exception as exc:
            if (
                _error(exc) == "strategy_activation_receipt_changed"
                or str(exc).startswith("admission_v2_")
            ):
                result.update(
                    phase="activation_blocked", error=_error(exc)
                )
                _persist(settings, job, plan["variant"] + ":activation_blocked")
                return
            reconciled = _read_existing(settings, result["strategy_id"])
            if _activation_confirmed(reconciled, result):
                _capture(result, reconciled)
            else:
                result.update(phase="outcome_unknown", error=_error(exc))
                _persist(settings, job, plan["variant"] + ":activation_unconfirmed")
                return
        if result["status"] != "paper_running" or not result.get("sleeve_id"):
            result.update(phase="outcome_unknown", error="intake_activation_not_confirmed")
            _persist(settings, job, plan["variant"] + ":activation_unconfirmed")
            return
    result["phase"] = "done"
    _persist(settings, job, plan["variant"] + ":done")


def _finished_status(job):
    if any(r["phase"] == "outcome_unknown" for r in job["results"]):
        return "outcome_unknown"
    results = {r["variant"]: r for r in job["results"]}
    if "baseline" in results:
        job["increment"] = compare_increment(job)
        job["comparison_status"] = "available" if job["increment"].get("comparable") else "partial"
    primary = next(plan for plan in job["plans"] if plan["activation_eligible"])
    result = results.get(primary["variant"])
    if result is not None and result["phase"] in {
        "validated_waiting_policy", "activation_blocked", "admission_waiting",
    }:
        return result["phase"]
    if result is None or result["phase"] != "done":
        return "paused"
    if (
        (job.get("admission_protocol") or {}).get("mode") == "authoritative"
        and (result.get("admission_v2") or {}).get("status") in {"recorded", "shadow"}
    ):
        return "completed"
    return "completed" if result["status"] in {"validated", "paper_running"} else "failed"


def reconcile(settings, job_id):
    """Refresh unknown results from saved domain receipts; never run a mutation.

    A proven unfinished draft/validation boundary becomes paused/resumable. An
    unconfirmed enable or incomplete validation remains unknown without retry.
    """
    with _lock(root(settings) / "worker.lock", nonblocking=True):
        job = _load_job(settings, job_id)
        if job["status"] not in {
            "running",
            "outcome_unknown",
            "paused",
            "validated_waiting_policy",
        }:
            return _summary(job, settings=settings)
        plans = {plan["variant"]: plan for plan in job["plans"]}
        for result in job["results"]:
            if result["phase"] == "done":
                continue
            entry = _read_existing(settings, result["strategy_id"])
            if entry is None:
                result.update(phase="outcome_unknown", error="intake_strategy_outcome_unknown")
                continue
            result["created_by_intake"] = _owned(entry, plans[result["variant"]])
            action = result.get("last_action")
            if action in {"enable", "replace"}:
                confirmed = _activation_confirmed(entry, result)
                if confirmed:
                    _capture(result, entry)
                result["phase"] = "done" if confirmed else "outcome_unknown"
            elif action == "validate":
                evaluation = job.get("evaluation")
                archived = (
                    library.find_evaluation(settings, result["strategy_id"], evaluation)
                    if evaluation
                    else None
                )
                if archived is not None:
                    _capture(result, archived)
                    result.update(phase="validated", error=None)
                elif evaluation and library.evaluation_recovery_ready(
                    settings, result["strategy_id"], evaluation
                ):
                    result.update(phase="composed", error=None)
                else:
                    result["phase"] = "outcome_unknown"
            else:
                result["phase"] = "composed" if result["created_by_intake"] else "outcome_unknown"
        job.update(status=_finished_status(job), lease=None)
        _persist(settings, job, "reconciled:" + job["status"])
        return _summary(job, settings=settings)


def _pending(job, settings=None):
    if job["status"] == "admission_waiting" and settings is not None:
        from quant_system.research.admission_qualification_flow import should_retry

        primary = next((r for r in job.get("results", []) if r.get("variant") != "baseline"), {})
        previous = primary.get("qualification_flow") or {}
        if previous.get("attempt_id"):
            return should_retry(
                settings, validation_path=previous["validation_path"],
                protocol=job["admission_protocol"], previous=previous,
            )
    if job["status"] in {
        "queued", "running", "paused", "validated_waiting_policy", "admission_waiting",
    }:
        return True
    return (
        job["status"] == "outcome_unknown"
        and bool(job.get("evaluation"))
        and bool(job.get("results"))
        and all(r.get("last_action") != "enable" for r in job["results"])
    )


def run_once(settings):
    policy = read_policy(settings)
    if not policy.enabled:
        return {"status": "paused", "processed": 0}
    pending = [job for job in _jobs(settings) if _pending(job, settings)]
    if not pending:
        return {"status": "empty", "processed": 0}
    try:
        with _lock(root(settings) / "worker.lock", nonblocking=True):
            # Re-read after acquiring the exclusive OS lease. A crashed process
            # releases flock; its durable running job takes priority over new work.
            pending = [job for job in _jobs(settings) if _pending(job, settings)]
            if not pending:
                return {"status": "empty", "processed": 0}
            job = min(
                pending,
                key=lambda j: (
                    {
                        "running": 0,
                        "queued": 1,
                        "paused": 1,
                        "validated_waiting_policy": 2,
                        "admission_waiting": 2,
                        "outcome_unknown": 3,
                    }[j["status"]],
                    j["created_at"],
                    j["job_id"],
                ),
            )
            job.update(
                status="running",
                error=None,
                lease={"pid": os.getpid(), "claimed_at": _now().isoformat()},
            )
            _persist(settings, job, "running")
            try:
                if not read_policy(settings).enabled:
                    raise ValueError("intake_paused")
                _prepare_evaluation(settings, job)
                from quant_system.research.intake_factor_evaluation import ensure_factor_evaluation

                job["factor_evaluation"] = ensure_factor_evaluation(settings, job)
                _persist(settings, job, "factor_evaluation_recorded")
                for plan in job["plans"]:
                    if not read_policy(settings).enabled:
                        raise ValueError("intake_paused")
                    _process_plan(settings, job, plan)
                    if job["results"][-1]["phase"] == "outcome_unknown":
                        break
                job["status"] = _finished_status(job)
            except Exception as exc:
                error = _error(exc)
                job.update(
                    status="paused" if error == "intake_paused" else "outcome_unknown", error=error
                )
            job["lease"] = None
            _persist(settings, job, job["status"])
            return {**_summary(job, settings=settings), "processed": 1}
    except BlockingIOError:
        return {"status": "busy", "processed": 0}
