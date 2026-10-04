"""Read-only active-metric overlays bound to exact saved study results.

Explicit import verifies statistics using the local calculator and original curve.
GET projection never calculates. Neither path calls a provider, model or backtest.
This module is deliberately outside every strategy calculation fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from quant_system.research.evaluation_service import _file_hash, _hash, _write

SCHEMA = "qs.study_active_metrics_sidecar/v2"
SHA = re.compile(r"[0-9a-f]{64}")


def _json(path: Path, expected_sha256: str | None = None):
    raw = path.read_bytes()
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("study_active_bytes_changed")
    return json.loads(
        raw,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")),
    )


def _same_statistics(actual, claimed) -> bool:
    if isinstance(actual, dict):
        return (
            isinstance(claimed, dict)
            and set(actual) == set(claimed)
            and all(_same_statistics(v, claimed[k]) for k, v in actual.items())
        )
    if isinstance(actual, list):
        return (
            isinstance(claimed, list)
            and len(actual) == len(claimed)
            and all(_same_statistics(a, b) for a, b in zip(actual, claimed, strict=True))
        )
    if type(actual) in {float, int} and type(claimed) in {float, int}:
        return (
            math.isfinite(actual)
            and math.isfinite(claimed)
            and math.isclose(actual, claimed, rel_tol=1e-10, abs_tol=1e-12)
        )
    return type(actual) is type(claimed) and actual == claimed


def _run_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"study-[A-Za-z0-9_-]{1,100}", value):
        raise ValueError("invalid_study_run_id")
    return value


def _bundle_files(root: Path) -> dict:
    if any(not p.is_file() or p.is_symlink() for p in (root / "studies").iterdir()):
        raise ValueError("study_active_evidence_file_closure")
    paths = {p.name: _file_hash(p) for p in sorted((root / "studies").iterdir()) if p.is_file()}
    return {
        "studies": paths,
        "source_report": _file_hash(root / "saved-study-snapshot.json"),
        "source_index": _file_hash(root / "inputs.json"),
    }


def evidence_digest(evidence_root: str | Path) -> str:
    return _hash(_bundle_files(Path(evidence_root)))


def import_study_active_evidence(
    settings, evidence_root: str | Path, *, expected_evidence_digest: str
) -> dict:
    """Explicit import; source-result mismatch rejects the whole batch before writes."""
    root = Path(evidence_root).resolve()
    files = _bundle_files(root)
    if not SHA.fullmatch(expected_evidence_digest) or _hash(files) != expected_evidence_digest:
        raise ValueError("study_active_evidence_digest_mismatch")
    snapshot = _json(root / "saved-study-snapshot.json", files["source_report"])
    run_id = _run_id(snapshot["run_id"])
    store = settings.data.data_dir / "strategy_studies"
    saved = _json(store / "runs" / run_id / "report.json")
    if saved.get("run_id") != run_id:
        raise ValueError("study_active_run_identity_mismatch")
    originals = {r["profile"]["id"]: r for r in saved["results"]}
    source = {r["profile"]["id"]: r for r in snapshot["results"]}
    if len(originals) != len(saved["results"]) or set(originals) != set(source):
        raise ValueError("study_active_profile_set_mismatch")
    if set(files["studies"]) != {name + ".json" for name in source}:
        raise ValueError("study_active_evidence_file_closure")
    # Calculation is permitted only for this explicit import, never GET.
    import pandas as pd

    from quant_system.research import active_metrics as calculator_module
    from quant_system.research.profile_backtests import INITIAL_CASH

    calculator_sha = _file_hash(Path(calculator_module.__file__))
    index = _json(root / "inputs.json", files["source_index"])
    reported_calculator = index.get("source_hashes", {}).get(
        "src/quant_system/research/active_metrics.py"
    )
    if reported_calculator != calculator_sha:
        raise ValueError("study_active_calculator_identity_mismatch")
    entries = {}
    for profile_id, result in originals.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", profile_id):
            raise ValueError("invalid_study_profile_id")
        item = _json(
            root / "studies" / f"{profile_id}.json", files["studies"][profile_id + ".json"]
        )
        actual = _hash(result)
        if _hash(source[profile_id]) != actual or item.get("source_result_digest") != actual:
            raise ValueError("study_active_source_result_mismatch:" + profile_id)
        if (
            item.get("profile_id") != profile_id
            or item.get("evaluation_only") is not True
            or item.get("new_research_trial") is not False
        ):
            raise ValueError("study_active_scope_mismatch")
        for supplied, original_key in (
            ("old_metrics", "metrics"),
            ("old_active_metrics", "active_metrics"),
            ("original_status", "status"),
        ):
            if supplied in item and item[supplied] != result.get(original_key):
                raise ValueError("study_active_original_fields_mismatch")
        active = item.get("active_metrics")
        if active is not None:
            if not isinstance(active, dict):
                raise ValueError("study_active_metrics_contract_mismatch")
            disclosure = active.get("disclosure", {})
            if (
                active.get("schema_version") != "active_metrics_v1"
                or disclosure.get("evaluation_only") is not True
                or disclosure.get("dsr_family_member") is not False
                or disclosure.get("tradeable_claim") is not False
            ):
                raise ValueError("study_active_metrics_contract_mismatch")
            comparison = active.get("vs_benchmark")
            if (
                comparison is not None
                and comparison.get("benchmark_symbol") != result["profile"]["benchmark_symbol"]
            ):
                raise ValueError("study_active_benchmark_mismatch")
        elif item.get("status") != "unavailable":
            raise ValueError("study_active_metrics_missing")
        if item.get("initial_cash", INITIAL_CASH) != INITIAL_CASH:
            raise ValueError("study_active_capital_claim_mismatch")
        curve = pd.DataFrame(result.get("curve", [])).rename(columns={"date": "timestamp"})
        if curve.empty or not {"timestamp", "equity", "benchmark", "peer"}.issubset(curve):
            raise ValueError("study_active_source_curve_unavailable")
        curve["timestamp"] = pd.to_datetime(curve.timestamp, utc=True)
        if not curve.timestamp.is_monotonic_increasing or curve.timestamp.duplicated().any():
            raise ValueError("study_active_source_calendar_invalid")
        original_return = result.get("metrics", {}).get("total_return")
        total_return = float(curve.equity.iloc[-1]) / INITIAL_CASH - 1
        if type(original_return) not in {int, float} or not math.isclose(
            original_return, total_return, rel_tol=1e-10, abs_tol=1e-12
        ):
            raise ValueError("study_active_original_capital_basis_unverified")
        recalculated = calculator_module.active_metrics(
            curve,
            initial_cash=INITIAL_CASH,
            benchmark_symbol=result["profile"]["benchmark_symbol"],
            include_peer=True,
        )
        if not _same_statistics(recalculated, active):
            raise ValueError("study_active_metrics_recompute_mismatch:" + profile_id)
        if _file_hash(Path(calculator_module.__file__)) != calculator_sha:
            raise ValueError("study_active_calculator_changed_during_verification")
        entries[profile_id] = {
            "source_result_digest": actual,
            "source_curve_digest": _hash(result.get("curve", [])),
            "evidence_file_sha256": files["studies"][profile_id + ".json"],
            "result": item,
            "statistics_validation": {
                "method": "trusted_recompute_from_saved_curve",
                "initial_cash": INITIAL_CASH,
                "benchmark_symbol": result["profile"]["benchmark_symbol"],
                "calculator_sha256": calculator_sha,
                "recomputed_digest": _hash(recalculated),
                "relative_tolerance": 1e-10,
                "absolute_tolerance": 1e-12,
            },
        }
    payload = {
        "schema_version": SCHEMA,
        "run_id": run_id,
        "evidence_digest": expected_evidence_digest,
        "source_report_sha256": files["source_report"],
        "source_index_sha256": files["source_index"],
        "calculator_sha256": calculator_sha,
        "entries": entries,
        "evaluation_only": True,
        "new_research_trial": False,
    }
    payload["payload_digest"] = _hash(payload)
    directory = store / "active_metrics_sidecars"
    path = directory / f"{run_id}-{expected_evidence_digest}.json"
    if path.exists():
        if _json(path) != payload:
            raise ValueError("study_active_existing_sidecar_mismatch")
    else:
        _write(path, payload)
    _write(directory / f"{run_id}.json", {"file": path.name, "sha256": _file_hash(path)})
    return {
        "status": "imported",
        "run_id": run_id,
        "profiles": len(entries),
        "sidecar_path": str(path),
        "sha256": _file_hash(path),
        "evidence_digest": expected_evidence_digest,
        "source_reports_modified": False,
        "statistics_recomputed_for_validation": True,
        "strategy_rerun": False,
        "href": "/research-evaluation?tab=studies",
    }


def project_study_active_metrics(settings, report: dict) -> dict:
    """Attach derived metrics only after checking the current raw result identity."""
    shown = dict(report)
    entries, failure, payload = {}, "not_imported", {}
    run_id = report.get("run_id")
    if run_id:
        try:
            directory = settings.data.data_dir / "strategy_studies/active_metrics_sidecars"
            pointer = _json(directory / f"{_run_id(run_id)}.json")
            name = pointer["file"]
            if Path(name).name != name or not name.startswith(run_id + "-"):
                raise ValueError("invalid_sidecar_path")
            path = directory / name
            payload = _json(path, pointer["sha256"])
            if (
                payload.get("schema_version") != SCHEMA
                or payload.get("run_id") != run_id
                or payload.get("payload_digest")
                != _hash({k: v for k, v in payload.items() if k != "payload_digest"})
            ):
                raise ValueError("sidecar_identity_mismatch")
            entries = payload["entries"]
            if not isinstance(entries, dict) or any(
                not isinstance(item, dict) or not isinstance(item.get("result"), dict)
                for item in entries.values()
            ):
                raise ValueError("sidecar_invalid_entries")
            if any(
                item.get("statistics_validation", {}).get("method")
                != "trusted_recompute_from_saved_curve"
                or item["statistics_validation"].get("calculator_sha256")
                != payload.get("calculator_sha256")
                for item in entries.values()
            ):
                raise ValueError("sidecar_unverified_statistics")
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            failure = "sidecar_unreadable_or_unbound"
            entries = {}
    results = []
    for original in report.get("results", []):
        row = dict(original)
        if original.get("active_metrics") is not None:
            row["active_metrics_evidence"] = {"kind": "native", "status": "stored_with_result"}
        else:
            item = entries.get(original.get("profile", {}).get("id"))
            reason = failure
            if item:
                if item.get("source_result_digest") != _hash(original) or item.get(
                    "source_curve_digest"
                ) != _hash(original.get("curve", [])):
                    reason = "source_result_digest_mismatch"
                else:
                    result = item["result"]
                    row["active_metrics"] = result.get("active_metrics")
                    row["active_metrics_evidence"] = {
                        "kind": "derived_sidecar",
                        "status": result.get("status", "unavailable"),
                        "reason": result.get("reason"),
                        "source_result_digest": item["source_result_digest"],
                        "source_curve_digest": item["source_curve_digest"],
                        "evidence_digest": payload["evidence_digest"],
                        "calculator_sha256": payload["calculator_sha256"],
                        "statistics_validation": item.get("statistics_validation"),
                        "evaluation_only": True,
                        "new_research_trial": False,
                    }
            if "active_metrics_evidence" not in row:
                row["active_metrics"] = None
                row["active_metrics_evidence"] = {
                    "kind": "derived_sidecar",
                    "status": "unavailable",
                    "reason": reason,
                }
        results.append(row)
    shown["results"] = results
    return shown
