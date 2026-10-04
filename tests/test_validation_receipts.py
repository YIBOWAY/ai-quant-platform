"""Sealed receipt fixtures test bindings, not investment performance."""

import json

import pytest

from quant_system.research.validation_receipts import (
    file_sha,
    receipt_bindings,
    verify_validation_receipt,
)


def sealed_validation(directory, definition_digest, comparison_digest):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "prices.parquet").write_bytes(b"sealed receipt test input; not a market dataset")
    (directory / "platform-result.json").write_text(
        json.dumps({"definition_digest": definition_digest})
    )
    source = {
        "prices_sha256": file_sha(directory / "prices.parquet"),
        "platform_result_sha256": file_sha(directory / "platform-result.json"),
    }
    (directory / "qlib-replay.json").write_text(
        json.dumps({"definition_digest": definition_digest, "source": source})
    )
    (directory / "signal-analysis.json").write_text(
        json.dumps(
            {
                "definition_digest": definition_digest,
                "status": "available",
                "source": {
                    "prices_sha256": source["prices_sha256"],
                    "result_sha256": source["platform_result_sha256"],
                },
            }
        )
    )
    sources = receipt_bindings(directory)["sources"]
    source["replay_source_sha256"] = sources["definition_qlib_replay.py"]
    (directory / "qlib-replay.json").write_text(
        json.dumps(
            {"definition_digest": definition_digest, "status": "available", "source": source}
        )
    )
    analysis = json.loads((directory / "signal-analysis.json").read_text())
    analysis["source"].update(
        validation_source_sha256=sources["strategy_signal_validation.py"],
        fit_metrics_source_sha256=sources["qlib_evaluation.py"],
    )
    (directory / "signal-analysis.json").write_text(json.dumps(analysis))
    value = {
        "definition_digest": definition_digest,
        "status": "passed",
        "blockers": [],
        "comparison": {"accepted": True, "comparison_digest": comparison_digest},
        "receipts": receipt_bindings(directory),
    }
    path = directory / "validation.json"
    path.write_text(json.dumps(value))
    return path, file_sha(path)


def test_bound_receipts_and_changed_input(tmp_path):
    path, sha = sealed_validation(tmp_path, "a" * 64, "b" * 64)
    assert (
        verify_validation_receipt(path, expected_sha=sha, definition_digest="a" * 64)["status"]
        == "passed"
    )
    (tmp_path / "prices.parquet").write_bytes(b"changed sealed input")
    with pytest.raises(ValueError, match="inputs_or_code_changed"):
        verify_validation_receipt(path, expected_sha=sha, definition_digest="a" * 64)


def test_rehashed_foreign_analysis_does_not_pass(tmp_path):
    path, _ = sealed_validation(tmp_path, "a" * 64, "b" * 64)
    analysis = json.loads((tmp_path / "signal-analysis.json").read_text())
    analysis["definition_digest"] = "c" * 64
    (tmp_path / "signal-analysis.json").write_text(json.dumps(analysis))
    document = json.loads(path.read_text())
    document["receipts"] = receipt_bindings(tmp_path)
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="outputs_mismatch"):
        verify_validation_receipt(path, expected_sha=file_sha(path), definition_digest="a" * 64)
