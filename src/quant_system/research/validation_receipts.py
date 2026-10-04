"""Bindings between a saved strategy, its input data, and both validation outputs."""

import hashlib
import json
import re
from pathlib import Path

_FILES = ("prices.parquet", "platform-result.json", "qlib-replay.json", "signal-analysis.json")
_SOURCES = ("definition_qlib_replay.py", "strategy_signal_validation.py", "qlib_evaluation.py")


def require_activation_receipt(entry, expected):
    """Compare one caller-frozen validation, not merely an unchanged rule ID."""
    fields = {"validation_sha256", "candidate_id", "evaluation"}
    if (
        not isinstance(expected, dict)
        or set(expected) != fields
        or not isinstance(expected.get("validation_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", expected["validation_sha256"]) is None
        or not expected.get("candidate_id")
        or not isinstance(expected.get("evaluation"), dict)
        or not expected["evaluation"].get("evaluation_id")
        or any(entry.get(key) != expected[key] for key in fields)
    ):
        raise ValueError("strategy_activation_receipt_changed")


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def receipt_bindings(directory):
    return {
        "files": {name: file_sha(directory / name) for name in _FILES},
        "sources": {name: file_sha(Path(__file__).with_name(name)) for name in _SOURCES},
    }


def verify_validation_receipt(
    path,
    *,
    expected_sha,
    definition_digest,
    comparison_digest=None,
    require_admission=True,
):
    path = Path(path)
    if file_sha(path) != expected_sha:
        raise ValueError("strategy_validation_receipt_changed")
    value = json.loads(path.read_text())
    if (
        value.get("definition_digest") != definition_digest
        or value.get("status") not in {"passed", "failed"}
        or (
            require_admission
            and (
                value.get("status") != "passed"
                or value.get("blockers")
                or value.get("comparison", {}).get("accepted") is not True
            )
        )
        or (
            comparison_digest is not None
            and value["comparison"]["comparison_digest"] != comparison_digest
        )
    ):
        raise ValueError("strategy_validation_receipt_mismatch")
    if value.get("receipts") != receipt_bindings(path.parent):
        raise ValueError("strategy_validation_inputs_or_code_changed")
    bindings = value["receipts"]["files"]
    platform = json.loads((path.parent / "platform-result.json").read_text())
    qlib = json.loads((path.parent / "qlib-replay.json").read_text())
    analysis = json.loads((path.parent / "signal-analysis.json").read_text())
    if (
        platform.get("definition_digest") != definition_digest
        or qlib.get("status") != "available"
        or qlib.get("definition_digest") != definition_digest
        or analysis.get("definition_digest") != definition_digest
        or analysis.get("status") not in {"available", "not_applicable"}
        or qlib.get("source", {}).get("prices_sha256") != bindings["prices.parquet"]
        or qlib.get("source", {}).get("platform_result_sha256") != bindings["platform-result.json"]
        or analysis.get("source", {}).get("prices_sha256") != bindings["prices.parquet"]
        or analysis.get("source", {}).get("result_sha256") != bindings["platform-result.json"]
        or qlib.get("source", {}).get("replay_source_sha256")
        != value["receipts"]["sources"]["definition_qlib_replay.py"]
        or analysis.get("source", {}).get("validation_source_sha256")
        != value["receipts"]["sources"]["strategy_signal_validation.py"]
        or analysis.get("source", {}).get("fit_metrics_source_sha256")
        != value["receipts"]["sources"]["qlib_evaluation.py"]
    ):
        raise ValueError("strategy_validation_outputs_mismatch")
    return value


def verify_candidate_validation(source_path, *, expected_sha, definition_digest, comparison_digest):
    if not expected_sha:
        raise ValueError("strategy_validation_receipt_required")
    for path in (Path(source_path).parent / "validations").glob("validation-*/validation.json"):
        if file_sha(path) == expected_sha:
            return verify_validation_receipt(
                path,
                expected_sha=expected_sha,
                definition_digest=definition_digest,
                comparison_digest=comparison_digest,
            )
    raise ValueError("strategy_validation_receipt_missing")
