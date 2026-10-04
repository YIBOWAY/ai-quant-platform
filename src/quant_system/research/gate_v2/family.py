"""Read-only, versioned projections of the complete compatible evaluation family.

The historical no-contract rule is retained for exact reproduction. New capital
uses an explicit universe/return/benchmark/frequency/cost/data contract: record
kind chooses its evidence adapter and does not erase genuine research attempts.
No projection appends, repairs or rewrites the original trial ledger.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, get_args

from quant_system.research.evaluation_service import _hash
from quant_system.research.trials import (
    TrialKind,
    performance_from_daily_returns,
)
from quant_system.research.trials import (
    universe_digest as digest_universe,
)

from ._constants import (
    DSR_V2_COVERAGE_SHORTFALL_BUDGET,
    DSR_V2_FAMILY_MIN_ENTRIES,
    DSR_V2_FAMILY_MIN_PERIODS,
    DSR_V2_SMALL_FAMILY_MIN_MEMBERS,
    FAMILY_V2_SCHEMA_VERSION,
)
from .active_returns import recompute_active_returns

MEMBERSHIP_RULE = (
    "kind==platform_backtest AND metadata.strategy_definition_digest present "
    "AND universe_digest matches AND n_periods>=DSR_V2_FAMILY_MIN_PERIODS "
    "AND curve resolvable AND sha256(curve)==metadata.equity_curve_digest"
)
FAMILY_SCOPE_STRATEGY = "strategy_hypothesis"
LEGACY_EVIDENCE_VERSION = "gate_v2_archived_evidence/v1"
FAMILY_RULE_VERSION = "compatible_evaluation_family/v2"
COMPATIBILITY_SCHEMA = "research_family_compatibility/v1"
_COMPATIBILITY_FIELDS = (
    "return_definition",
    "benchmark",
    "frequency",
    "cost_definition",
    "market_data_contract",
)


def _document(row):
    value = row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row)
    return json.loads(json.dumps(value, allow_nan=False))


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ArchivedCurveResolver:
    """Read only canonical archive locations and require exact original identities.

    trusted_trials is supplied by the owner from its ledger snapshot, not from a
    proposal. The resolver never mints a missing definition digest. A verifier
    must call legacy() again; saved sidecar verdict numbers are not authority.
    """

    def __init__(self, data_root: Path, *, trusted_trials: Sequence[Any]):
        self.data_root = Path(data_root).resolve()
        self.trials = {str(_field(row, "trial_id")): _document(row) for row in trusted_trials}
        self.curves, self.family_curves, self.legacy_runs, self.failures = {}, {}, {}, []
        for path in sorted((self.data_root / "strategy_studies/runs").glob("*/report.json")):
            try:
                report = json.loads(path.read_text())
                prices = path.parent / "prices.parquet"
                prices_sha = _file_sha(prices)
                if report.get("source", {}).get("prices_sha256") != prices_sha:
                    raise ValueError("archived_price_digest_mismatch")
                sections = [
                    ("results", report.get("results") or []),
                    ("discovery.results", (report.get("discovery") or {}).get("results") or []),
                ]
                for section, results in sections:
                    for index, payload in enumerate(results):
                        if not payload.get("curve") or not payload.get("profile"):
                            continue
                        run_id = "recorded-study-" + _hash(
                            {
                                "profile": payload["profile"],
                                "prices": prices_sha,
                                "curve": payload["curve"],
                            }
                        )
                        evidence = {
                            "schema": LEGACY_EVIDENCE_VERSION,
                            "type": "recorded_study",
                            "run_id": run_id,
                            "selector": {"section": section, "index": index},
                            "profile_digest": _hash(payload["profile"]),
                            "files": {str(path): _file_sha(path), str(prices): prices_sha},
                        }
                        self.legacy_runs.setdefault(run_id, []).append((payload, evidence))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.failures.append({"path": str(path), "reason": type(exc).__name__})
        for path in sorted(
            (self.data_root / "strategy_library").glob("*/validations/*/platform-result.json")
        ):
            try:
                payload = json.loads(path.read_text())
                if payload.get("curve"):
                    self.curves[_hash(payload["curve"])] = (payload, path, _file_sha(path))
                    self.family_curves.setdefault(_hash(payload["curve"]), []).append(
                        (payload, path, _file_sha(path))
                    )
                validation_path, qlib_path, prices = (
                    path.parent / "validation.json",
                    path.parent / "qlib-replay.json",
                    path.parent / "prices.parquet",
                )
                validation, qlib = (
                    json.loads(validation_path.read_text()),
                    json.loads(qlib_path.read_text()),
                )
                definition = payload.get("definition_digest")
                prices_sha = _file_sha(prices)
                if (
                    not definition
                    or payload.get("evaluation_initial_cash") != 10000
                    or validation.get("definition_digest") != definition
                    or qlib.get("definition_digest") != definition
                    or qlib.get("status") != "available"
                    or qlib.get("source", {}).get("platform_result_sha256") != _file_sha(path)
                    or qlib.get("source", {}).get("prices_sha256") != prices_sha
                ):
                    raise ValueError("archived_validation_unbound")
                content_id = "definition-validation-" + _hash(
                    {
                        "definition": definition,
                        "prices": prices_sha,
                        "start": payload["start"],
                        "end": payload["end"],
                        "cash": 10000,
                    }
                )
                ids = [content_id]
                if validation.get("run_id") == path.parent.name:
                    ids.append(validation["run_id"])
                for run_id in ids:
                    evidence = {
                        "schema": LEGACY_EVIDENCE_VERSION,
                        "type": "validation_receipts",
                        "run_id": run_id,
                        "definition_digest": definition,
                        "files": {
                            str(file): _file_sha(file)
                            for file in (path, validation_path, qlib_path, prices)
                        },
                    }
                    self.legacy_runs.setdefault(run_id, []).append((payload, evidence))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.failures.append({"path": str(path), "reason": type(exc).__name__})

    def __call__(self, row):
        metadata = _field(row, "metadata") or {}
        if metadata.get("family_evidence_path"):
            return self._explicit_family_curve(row)
        expected = (_field(row, "metadata") or {}).get("equity_curve_digest")
        found = next(
            (
                item
                for item in self.family_curves.get(expected, [])
                if item[0].get("definition_digest") == metadata.get("strategy_definition_digest")
            ),
            self.curves.get(expected),
        )
        if found is None:
            return None
        payload, path, file_sha = found
        if _file_sha(path) != file_sha:
            return None
        # Preserve the old curve interface. New-rule consumers additionally
        # require owner-owned original files and the definition binding below.
        enriched = dict(payload)
        try:
            trusted = self.trials.get(str(_field(row, "trial_id")))
            if trusted != _document(row):
                return None
            if metadata.get("strategy_definition_digest") != payload.get("definition_digest"):
                return None
            validation_path = path.parent / "validation.json"
            validation = json.loads(validation_path.read_text())
            if validation.get("definition_digest") != payload.get("definition_digest"):
                return None
            definition = payload.get("definition")
            if not definition:
                return enriched
            from quant_system.research.strategy_definition import StrategyDefinition

            frozen = StrategyDefinition.model_validate(definition)
            if frozen.content_digest != payload.get("definition_digest"):
                return None
            if digest_universe(frozen.symbols) != _field(row, "universe_digest"):
                return None
            enriched["family_contract"] = compatibility_contract_from_result(payload)
            enriched["family_evidence"] = {
                "adapter": "bound_definition_result/v1",
                "trial_digest": _hash(trusted),
                "files": {str(path): file_sha, str(validation_path): _file_sha(validation_path)},
                "definition_digest": frozen.content_digest,
            }
            prices = path.parent / "prices.parquet"
            if prices.is_file():
                enriched["family_evidence"]["files"][str(prices)] = _file_sha(prices)
        except (OSError, KeyError, TypeError, ValueError):
            # Legacy reads retain the original payload; the strict contract
            # path rejects absent proof rather than guessing historical costs.
            return payload
        return enriched

    def _explicit_family_curve(self, row):
        """Resolve a digest-pinned producer receipt without inventing a definition.

        This is the common adapter for genuine D34/Qlib/other trials. It does
        not turn their scalar Sharpe into an active curve. Producers must save
        the original equity and benchmark levels under their own input identity.
        """
        try:
            trusted = self.trials.get(str(_field(row, "trial_id")))
            if trusted != _document(row):
                return None
            metadata = _field(row, "metadata") or {}
            path = self.data_root / metadata["family_evidence_path"]
            path = path.resolve(strict=True)
            if not path.is_relative_to(self.data_root) or not path.is_file():
                return None
            file_sha = _file_sha(path)
            if file_sha != metadata.get("family_evidence_sha256"):
                return None
            payload = json.loads(path.read_text())
            identity = {
                key: _field(row, key)
                for key in (
                    "kind",
                    "subject",
                    "universe_digest",
                    "window_start",
                    "window_end",
                    "n_periods",
                )
            }
            if (
                payload.get("schema") != "research_family_curve/v1"
                or payload.get("trial_identity") != identity
                or payload.get("run_id") != metadata.get("run_id")
                or not payload.get("input_identity")
            ):
                return None
            files = {str(path): file_sha}
            for name, expected in (payload.get("source_files") or {}).items():
                source = (self.data_root / name).resolve(strict=True)
                if (
                    not source.is_relative_to(self.data_root)
                    or not source.is_file()
                    or _file_sha(source) != expected
                ):
                    return None
                files[str(source)] = expected
            return {
                **payload,
                "family_evidence": {
                    "adapter": "producer_family_curve/v1",
                    "trial_digest": _hash(trusted),
                    "files": files,
                    "input_identity": payload["input_identity"],
                },
            }
        except (OSError, KeyError, TypeError, ValueError):
            return None

    def legacy(self, row):
        document = _document(row)
        trusted = self.trials.get(str(_field(row, "trial_id")))
        if trusted is None or _hash(trusted) != _hash(document):
            return None
        metadata = _field(row, "metadata") or {}
        # A recorded canonical curve digest can never be downgraded to a legacy
        # proof after corruption or disappearance of its original curve.
        if metadata.get("equity_curve_digest") is not None:
            return None
        for payload, proof in self.legacy_runs.get(metadata.get("run_id"), []):
            if any(_file_sha(path) != expected for path, expected in proof["files"].items()):
                continue
            active = recompute_active_returns(
                payload["curve"], initial_cash=payload.get("evaluation_initial_cash", 100000.0)
            )
            raw = performance_from_daily_returns(active["equity_returns"])
            if (
                payload.get("source") != _field(row, "source")
                or payload.get("source") != "futu"
                or payload.get("price_adjustment") != "qfq"
                or payload["profile"]["id"] != _field(row, "subject")
                or digest_universe(payload["profile"]["symbols"]) != _field(row, "universe_digest")
                or active["n_periods"] != _field(row, "n_periods")
                or active["start"] != _field(row, "window_start")
                or active["end"] != _field(row, "window_end")
                or not math.isclose(
                    raw["total_return"], _field(row, "total_return"), rel_tol=1e-9, abs_tol=1e-12
                )
                or (
                    metadata.get("strategy_definition_digest") is not None
                    and metadata["strategy_definition_digest"] != payload.get("definition_digest")
                )
            ):
                continue
            evidence = {
                **proof,
                "original_trial": document,
                "curve_digest": _hash(payload["curve"]),
                "initial_cash": payload.get("evaluation_initial_cash", 100000.0),
            }
            return {**payload, "legacy_evidence": evidence}
        return None


def verify_legacy_member(member, resolver):
    """Resolve the original files again and recompute the saved member statistics."""
    evidence = member.get("legacy_evidence")
    if not evidence or resolver is None:
        return False
    try:
        original = evidence["original_trial"]
        if (
            member.get("trial_id") != original.get("trial_id")
            or member.get("run_id") != (original.get("metadata") or {}).get("run_id")
            or evidence.get("run_id") != member.get("run_id")
        ):
            return False
        payload = resolver(evidence["original_trial"])
        if payload is None or payload.get("legacy_evidence") != evidence:
            return False
        active = recompute_active_returns(payload["curve"], initial_cash=evidence["initial_cash"])
        return (
            member["n_periods"] == active["n_periods"]
            and member["recomputed_sharpe"]
            == performance_from_daily_returns(active["active_returns"])["sharpe_period"]
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def family_key(*, universe_digest: str, scope_tag: str = FAMILY_SCOPE_STRATEGY) -> str:
    """``universe|scope`` — separates a strategy-hypothesis family from a diagnosis one."""
    return f"{universe_digest}|{scope_tag}"


def _field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _run_id(row: Any) -> Any:
    metadata = _field(row, "metadata") or {}
    return metadata.get("run_id") if isinstance(metadata, Mapping) else None


def is_member(
    row: Any, *, universe_digest: str, curve_resolver: Callable[[Any], Any]
) -> tuple[bool, str | None]:
    """Full membership check; returns ``(True, None)`` or ``(False, reason)``."""
    if _field(row, "kind") != "platform_backtest":
        return False, "kind_excluded"
    metadata = _field(row, "metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    digest = metadata.get("strategy_definition_digest")
    if not digest:
        return False, "definition_digest_missing"
    if _field(row, "universe_digest") != universe_digest:
        return False, "universe_mismatch"
    n_periods = _field(row, "n_periods")
    if n_periods is None or int(n_periods) < DSR_V2_FAMILY_MIN_PERIODS:
        return False, "short_window"
    try:
        payload = curve_resolver(row)
    except Exception:  # noqa: BLE001 - a broken resolver is a coverage gap, not a crash
        return False, "curve_unreadable"
    if payload is None:
        return False, "curve_unresolved"
    curve = payload.get("curve") if isinstance(payload, Mapping) else None
    if not curve:
        return False, "curve_unresolved"
    expected = metadata.get("equity_curve_digest")
    if expected is None or _hash(curve) != expected:
        return False, "curve_digest_mismatch"
    return True, None


def validation_dir_resolver(validation_dirs: Sequence[Any]) -> Callable[[Any], Any]:
    """Default ``curve_resolver``: index platform-result payloads by curve digest.

    A bound-validation trial records ``metadata.equity_curve_digest``; the
    matching ``platform-result.json`` under a ``validation-<hex>`` directory
    carries the same curve, so the digest is the join key. Resolution is never
    trusted blindly — :func:`is_member` re-hashes the resolved curve and rejects
    a mismatch.
    """
    import json

    index: dict[str, Any] = {}
    for directory in validation_dirs:
        root = Path(directory)
        candidates = [root / "platform-result.json", *sorted(root.glob("*/platform-result.json"))]
        for result_path in candidates:
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            curve = payload.get("curve") if isinstance(payload, Mapping) else None
            if curve:
                index[_hash(curve)] = payload

    def resolve(row: Any) -> Any:
        digest = (_field(row, "metadata") or {}).get("equity_curve_digest")
        return index.get(digest) if digest else None

    return resolve


def _project_family_legacy(
    *,
    trials_rows: Sequence[Any],
    validation_dirs: Sequence[Any] = (),
    universe_digest: str,
    scope_tag: str = FAMILY_SCOPE_STRATEGY,
    curve_resolver: Callable[[Any], Any],
    legacy_resolver: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """Rebuild the DSR family: recompute every member's per-period Sharpe.

    ``curve_resolver(row)`` returns the platform-result payload (with ``curve``
    and ``evaluation_initial_cash``) for a trial row, or ``None``. Every member
    is re-measured with the *same* active-return definition as the candidate.
    """
    members: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    out_of_scope: list[dict[str, Any]] = []
    for row in trials_rows:
        if _field(row, "kind") != "platform_backtest":
            out_of_scope.append(
                {
                    "trial_id": _field(row, "trial_id"),
                    "run_id": _run_id(row),
                    "reason": "kind_excluded",
                }
            )
            continue
        ok, reason = is_member(row, universe_digest=universe_digest, curve_resolver=curve_resolver)
        legacy_payload = None
        if (
            not ok
            and legacy_resolver is not None
            and (_field(row, "metadata") or {}).get("equity_curve_digest") is None
            and _field(row, "universe_digest") == universe_digest
            and int(_field(row, "n_periods", 0)) >= DSR_V2_FAMILY_MIN_PERIODS
        ):
            try:
                legacy_payload = legacy_resolver(row)
            except (OSError, ValueError, KeyError, TypeError):
                legacy_payload = None
            ok = bool(legacy_payload and legacy_payload.get("legacy_evidence"))
        if not ok:
            excluded.append(
                {"trial_id": _field(row, "trial_id"), "run_id": _run_id(row), "reason": reason}
            )
            continue
        payload = legacy_payload or curve_resolver(row)
        curve_rows = payload.get("curve") if isinstance(payload, Mapping) else None
        initial_cash = (
            payload.get("evaluation_initial_cash", 100_000.0)
            if isinstance(payload, Mapping)
            else 100_000.0
        )
        try:
            active = recompute_active_returns(curve_rows, initial_cash=initial_cash)
        except ValueError:
            excluded.append(
                {
                    "trial_id": _field(row, "trial_id"),
                    "run_id": _run_id(row),
                    "reason": "curve_unreadable",
                }
            )
            continue
        perf = performance_from_daily_returns(active["active_returns"])
        members.append(
            {
                "trial_id": _field(row, "trial_id"),
                "run_id": _run_id(row),
                "n_periods": active["n_periods"],
                "recomputed_sharpe": perf["sharpe_period"],
                "curve_digest_verified": True,
                **(
                    {"legacy_evidence": legacy_payload["legacy_evidence"]} if legacy_payload else {}
                ),
            }
        )
    members.sort(key=lambda item: str(item["trial_id"]))
    excluded.sort(key=lambda item: str(item["trial_id"]))
    total = len(members) + len(excluded)
    shortfall = (len(excluded) / total) if total else 0.0
    family_digest = _hash(
        {
            "members": members,
            "excluded": excluded,
            "coverage_shortfall": shortfall,
            "family_key": family_key(universe_digest=universe_digest, scope_tag=scope_tag),
        }
    )
    return {
        "schema_version": FAMILY_V2_SCHEMA_VERSION,
        "membership_rule": MEMBERSHIP_RULE,
        "family_key": family_key(universe_digest=universe_digest, scope_tag=scope_tag),
        "scope_tag": scope_tag,
        "universe_digest": universe_digest,
        "n_trials": len(members),
        "family_digest": family_digest,
        "members": members,
        "excluded": excluded,
        "out_of_scope": out_of_scope,
        "coverage_shortfall": shortfall,
        "trusted": bool(shortfall <= DSR_V2_COVERAGE_SHORTFALL_BUDGET),
        "recomputed_sharpes": [
            float(item["recomputed_sharpe"])
            for item in members
            if item["recomputed_sharpe"] is not None and math.isfinite(item["recomputed_sharpe"])
        ],
    }


def _compatibility_contract(value):
    """Validate a complete semantic contract, not a display label or rule name."""
    if not isinstance(value, Mapping) or value.get("schema") != COMPATIBILITY_SCHEMA:
        raise ValueError("family_compatibility_contract_invalid")
    if set(value) != {"schema", *_COMPATIBILITY_FIELDS}:
        raise ValueError("family_compatibility_contract_invalid")
    result = json.loads(json.dumps(value, allow_nan=False))
    if result["return_definition"] not in {
        "arithmetic_net_active",
        "net_total_return",
        "net_total",
        "gross_total",
    } or result["frequency"] not in {"daily", "monthly"}:
        raise ValueError("family_compatibility_contract_invalid")
    benchmark, cost, market = (
        result[key] for key in ("benchmark", "cost_definition", "market_data_contract")
    )
    if (
        not isinstance(benchmark, dict)
        or set(benchmark) != {"symbol", "method"}
        or not (
            all(isinstance(v, str) and v.strip() for v in benchmark.values())
            or benchmark == {"symbol": None, "method": "none"}
        )
    ):
        raise ValueError("family_benchmark_contract_missing")
    model_fields = {
        "proportional_bps": {"commission_bps", "slippage_bps", "cash_interest"},
        "qlib_combined_bps": {"one_way_bps", "min_cost", "cash_interest"},
    }
    fields = model_fields.get(cost.get("model")) if isinstance(cost, dict) else None
    if (
        not fields
        or set(cost) != {"model", *fields}
        or any(
            isinstance(cost[k], bool)
            or not isinstance(cost[k], (float, int))
            or not math.isfinite(cost[k])
            or cost[k] < 0
            for k in fields
        )
    ):
        raise ValueError("family_cost_contract_missing")
    if (
        not isinstance(market, dict)
        or set(market) != {"provider", "price_adjustment", "currency", "bar"}
        or not all(isinstance(v, str) and v.strip() for v in market.values())
    ):
        raise ValueError("family_market_data_contract_missing")
    return result


def compatibility_contract_from_result(payload, *, definition=None):
    """Derive the current supported producer's contract from its frozen fields.

    An old study without its fee configuration is insufficient; the adapter
    never borrows today's fee constants. The fixed USD/zero-interest/benchmark
    convention is the recorded StrategyDefinition result producer, not a claim
    that QFQ is a dividend-reinvestment total-return series.
    """
    definition = definition if definition is not None else payload.get("definition")
    if hasattr(definition, "model_dump"):
        definition = definition.model_dump(mode="json")
    if not isinstance(definition, Mapping) or any(
        key not in definition for key in ("commission_bps", "slippage_bps")
    ):
        raise ValueError("family_cost_contract_missing")
    benchmark = (payload.get("profile") or {}).get("benchmark_symbol")
    if not benchmark or benchmark != definition.get("benchmark_symbol"):
        raise ValueError("family_benchmark_contract_missing")
    if payload.get("source") != "futu" or payload.get("price_adjustment") != "qfq":
        raise ValueError("family_market_data_contract_missing")
    if (
        definition.get("cash_rule", "unallocated_cash_zero_interest")
        != "unallocated_cash_zero_interest"
    ):
        raise ValueError("family_cost_contract_missing")
    return _compatibility_contract(
        {
            "schema": COMPATIBILITY_SCHEMA,
            "return_definition": "arithmetic_net_active",
            "benchmark": {"symbol": benchmark, "method": "net_buy_and_hold"},
            "frequency": payload.get("frequency"),
            "cost_definition": {
                "model": "proportional_bps",
                "commission_bps": definition["commission_bps"],
                "slippage_bps": definition["slippage_bps"],
                "cash_interest": 0.0,
            },
            "market_data_contract": {
                "provider": payload["source"],
                "price_adjustment": payload["price_adjustment"],
                "currency": "USD",
                "bar": "1d",
            },
        }
    )


def family_digest_payload(family):
    """Content covered by the family digest, versioned for historical replay.

    Audit rows from other universes/contracts intentionally do not affect the
    in-family digest. The containing verdict envelope still covers those rows.
    """
    value = {
        key: family[key] for key in ("members", "excluded", "coverage_shortfall", "family_key")
    }
    if family.get("rule_version") == FAMILY_RULE_VERSION:
        value.update(
            {
                key: family[key]
                for key in (
                    "rule_version",
                    "compatibility_contract",
                    "compatibility_contract_digest",
                    "evidence_state",
                    "n_trials",
                    "n_applicable_trials",
                )
            }
        )
    return value


def _contract_member(row, payload):
    if not isinstance(payload, Mapping) or not payload.get("curve"):
        raise ValueError("curve_unresolved")
    metadata = _field(row, "metadata") or {}
    expected_curve = metadata.get("equity_curve_digest")
    legacy = payload.get("legacy_evidence")
    evidence = payload.get("family_evidence") or {}
    if evidence:
        if evidence.get("trial_digest") != _hash(_document(row)):
            raise ValueError("family_evidence_trial_mismatch")
        files = evidence.get("files")
        if not isinstance(files, Mapping) or not files:
            raise ValueError("family_evidence_files_missing")
        for name, expected in files.items():
            path = Path(name)
            if not path.is_file() or _file_sha(path) != expected:
                raise ValueError("family_evidence_file_changed")
    if expected_curve is not None:
        if _hash(payload["curve"]) != expected_curve:
            raise ValueError("curve_digest_mismatch")
    elif not legacy and evidence.get("curve_digest") != _hash(payload["curve"]):
        raise ValueError("curve_digest_missing")
    raw_contract = payload.get("family_contract")
    if raw_contract is None:
        raise ValueError("family_contract_missing")
    contract = _compatibility_contract(raw_contract)
    expected_contract = metadata.get("family_contract_digest")
    if expected_contract is not None:
        if expected_contract != _hash(contract):
            raise ValueError("family_contract_digest_mismatch")
    elif not evidence or evidence.get("trial_digest") != _hash(_document(row)):
        raise ValueError("family_contract_unbound")
    if evidence and evidence.get("trial_digest") != _hash(_document(row)):
        raise ValueError("family_evidence_trial_mismatch")
    return contract, evidence


def _validate_curve(curve, *, active):
    previous = None
    for row in curve:
        label = row.get("date")
        try:
            stamp = date.fromisoformat(label)
        except (TypeError, ValueError) as exc:
            raise ValueError("family_curve_invalid") from exc
        if label != stamp.isoformat() or (previous is not None and label <= previous):
            raise ValueError("family_curve_invalid")
        for key in ("equity", "benchmark") if active else ("equity",):
            value = row.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or (key == "benchmark" and value == 0)
            ):
                raise ValueError("family_curve_invalid")
        previous = label


def _family_returns(payload, contract):
    active = contract["return_definition"] == "arithmetic_net_active"
    curve = payload["curve"]
    _validate_curve(curve, active=active)
    if "evaluation_initial_cash" not in payload:
        raise ValueError("family_initial_cash_missing")
    initial = payload["evaluation_initial_cash"]
    if active:
        return recompute_active_returns(curve, initial_cash=initial)
    if (
        isinstance(initial, bool)
        or not isinstance(initial, (int, float))
        or not math.isfinite(initial)
        or initial <= 0
    ):
        raise ValueError("gate_v2_initial_cash_invalid")
    values, dates = [], []
    previous = initial
    for mark in curve:
        if previous <= 0:
            raise ValueError("family_curve_invalid")
        values.append(mark["equity"] / previous - 1)
        dates.append(mark["date"])
        previous = mark["equity"]
    return {
        "active_returns": values,
        "equity_returns": values,
        "dates": dates,
        "n_periods": len(values),
        "start": dates[0],
        "end": dates[-1],
    }


def project_family_v2(
    *,
    trials_rows: Sequence[Any],
    validation_dirs: Sequence[Any] = (),
    universe_digest: str,
    scope_tag: str = FAMILY_SCOPE_STRATEGY,
    curve_resolver: Callable[[Any], Any],
    legacy_resolver: Callable[[Any], Any] | None = None,
    compatibility_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a full compatible evaluation family without mutating its ledger.

    No-contract calls reproduce the historical rule exactly. They are *not* a
    current funding qualification. A new capital consumer must require the new
    rule_version and an explicit compatible contract as well as current source,
    family, peers and qualification evidence.
    """
    if compatibility_contract is None:
        return _project_family_legacy(
            trials_rows=trials_rows,
            validation_dirs=validation_dirs,
            universe_digest=universe_digest,
            scope_tag=scope_tag,
            curve_resolver=curve_resolver,
            legacy_resolver=legacy_resolver,
        )
    expected = _compatibility_contract(compatibility_contract)
    if (
        expected["return_definition"] not in {"arithmetic_net_active", "net_total_return"}
        or expected["frequency"] != "daily"
    ):
        raise ValueError("family_candidate_return_contract_unsupported")
    if expected["return_definition"] == "net_total_return" and expected["benchmark"] != {
        "symbol": None,
        "method": "none",
    }:
        raise ValueError("family_total_return_benchmark_must_be_none")
    if (
        expected["return_definition"] == "arithmetic_net_active"
        and expected["benchmark"]["method"] != "net_buy_and_hold"
    ):
        raise ValueError("family_active_benchmark_contract_invalid")
    members, excluded, out_of_scope = [], [], []
    identities = {}
    for row in trials_rows:
        document = _document(row)
        trial_id = str(_field(row, "trial_id"))
        trial_digest = _hash(document)
        if trial_id in identities:
            if identities[trial_id] != trial_digest:
                raise ValueError("family_trial_identity_conflict")
            continue
        identities[trial_id] = trial_digest
        audit = {
            "trial_id": _field(row, "trial_id"),
            "run_id": _run_id(row),
            "kind": _field(row, "kind"),
            "trial_digest": trial_digest,
        }
        # Universe precedes adapter and evidence checks: unrelated damaged rows
        # do not become missing evidence in this evaluation family.
        if _field(row, "universe_digest") != universe_digest:
            out_of_scope.append({**audit, "reason": "universe_mismatch"})
            continue
        try:
            if digest_universe(_field(row, "universe") or []) != universe_digest:
                raise ValueError("trial_universe_digest_mismatch")
            if _field(row, "kind") not in get_args(TrialKind):
                raise ValueError("trial_kind_invalid")
            try:
                payload = curve_resolver(row)
                if payload is None and legacy_resolver is not None:
                    payload = legacy_resolver(row)
            except Exception as exc:  # noqa: BLE001 - resolver failures are evidence gaps
                raise ValueError("curve_unreadable") from exc
            contract, evidence = _contract_member(row, payload)
            differing = [
                field for field in _COMPATIBILITY_FIELDS if contract[field] != expected[field]
            ]
            if differing:
                out_of_scope.append(
                    {
                        **audit,
                        "reason": "incompatible_" + differing[0],
                        "incompatible_fields": differing,
                        "contract": contract,
                        "evidence": evidence,
                    }
                )
                continue
            active = _family_returns(payload, contract)
            if (
                active["n_periods"] != _field(row, "n_periods")
                or active["start"] != _field(row, "window_start")
                or active["end"] != _field(row, "window_end")
            ):
                raise ValueError("trial_curve_identity_mismatch")
            if active["n_periods"] < DSR_V2_FAMILY_MIN_PERIODS:
                raise ValueError("short_window")
            raw = performance_from_daily_returns(active["equity_returns"])
            if _field(row, "total_return") is None or not math.isclose(
                raw["total_return"], _field(row, "total_return"), rel_tol=1e-9, abs_tol=1e-12
            ):
                raise ValueError("trial_curve_returns_mismatch")
            perf = performance_from_daily_returns(active["active_returns"])
            sharpe = perf["sharpe_period"]
            if sharpe is None or not math.isfinite(sharpe):
                raise ValueError("active_sharpe_unmeasurable")
            members.append(
                {
                    **audit,
                    "n_periods": active["n_periods"],
                    "recomputed_sharpe": sharpe,
                    "return_definition": contract["return_definition"],
                    "returns_digest": _hash(active["active_returns"]),
                    "curve_digest_verified": True,
                    "curve_digest": _hash(payload["curve"]),
                    "evidence": evidence,
                    "window": {"start": active["start"], "end": active["end"]},
                    "contract_digest": _hash(contract),
                    **(
                        {"legacy_evidence": payload["legacy_evidence"]}
                        if payload.get("legacy_evidence")
                        else {}
                    ),
                }
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            excluded.append(
                {
                    **audit,
                    "reason": str(exc)
                    if isinstance(exc, ValueError)
                    else "family_evidence_invalid",
                }
            )
    for collection in (members, excluded, out_of_scope):
        collection.sort(key=lambda item: str(item["trial_id"]))
    total = len(members) + len(excluded)
    shortfall = len(excluded) / total if total else 0.0
    state = (
        "incomplete_evidence"
        if excluded
        else "empty"
        if not members
        else "insufficient_members"
        if len(members) < DSR_V2_SMALL_FAMILY_MIN_MEMBERS
        else "small_family"
        if len(members) < DSR_V2_FAMILY_MIN_ENTRIES
        else "complete"
    )
    result = {
        "schema_version": FAMILY_V2_SCHEMA_VERSION,
        "rule_version": FAMILY_RULE_VERSION,
        "membership_rule": (
            "same universe and proven compatible return/benchmark/frequency/cost/data; "
            "kind selects evidence adapter"
        ),
        "family_key": universe_digest + "|" + _hash(expected),
        "scope_tag": scope_tag,
        "compatibility_contract": expected,
        "compatibility_contract_digest": _hash(expected),
        "universe_digest": universe_digest,
        "n_trials": len(members),
        "n_applicable_trials": total,
        "members": members,
        "excluded": excluded,
        "out_of_scope": out_of_scope,
        "coverage_shortfall": shortfall,
        "evidence_state": state,
        "trusted": bool(members) and shortfall <= DSR_V2_COVERAGE_SHORTFALL_BUDGET,
        "recomputed_sharpes": [float(row["recomputed_sharpe"]) for row in members],
    }
    result["family_digest"] = _hash(family_digest_payload(result))
    return result
