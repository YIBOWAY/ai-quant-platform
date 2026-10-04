import numpy as np
import pytest

from quant_system.research import admission_consumer_checks as checks
from tests.gate_v2_fixtures import platform_result


def test_fixed_control_rejects_other_population_before_any_execution(tmp_path):
    (tmp_path / "inputs.json").write_text("{}")
    with pytest.raises(ValueError, match="not_frozen_batch"):
        checks._load_context({"random_root": str(tmp_path), "data_root": str(tmp_path)})


def test_control_versions_keep_old_window_and_reject_unregistered_inputs(tmp_path):
    assert checks.CONTROL_VERSIONS["futu24-original-20260920"]["context"]["end"] == "2026-09-08"
    assert checks.CONTROL_VERSIONS["futu24-current-20260920"]["context"]["end"] == "2026-09-18"
    for version in ("futu24-current-20260920", "made-up-version"):
        (tmp_path / "inputs.json").write_text("{}")
        with pytest.raises(ValueError, match="not_frozen_batch|version_unsupported"):
            checks._load_context(
                {
                    "random_root": str(tmp_path),
                    "data_root": str(tmp_path),
                    "control_version": version,
                }
            )


def test_residual_null_is_actual_aligned_and_deterministic():
    rng = np.random.default_rng(40)
    payload = platform_result(
        equity_returns=rng.normal(0.001, 0.01, 80).tolist(),
        benchmark_returns=rng.normal(0.001, 0.01, 80).tolist(),
    )
    peers = [
        {
            "sleeve_id": "sealed",
            "dates": [row["date"] for row in payload["curve"]],
            "returns": rng.normal(0.001, 0.01, 80).tolist(),
        }
    ]
    first = checks.concentration_inputs(payload["curve"], 100000, peers)
    second = checks.concentration_inputs(payload["curve"], 100000, peers)
    assert first == second
    assert first[1]["status"] == "evaluated" and first[1]["n_resamples"] == 2000
    peers[0]["dates"] = ["1990-" + str(i) for i in range(80)]
    assert (
        checks.concentration_inputs(payload["curve"], 100000, peers)[1]["status"] == "not_evaluated"
    )


def test_unknown_scope_cannot_use_self_reported_checks(monkeypatch):
    monkeypatch.setattr(checks.subprocess, "run", lambda *a, **k: pytest.fail("execution reached"))
    result = checks.verify_consumer_checks(
        None, code_digest="x", scope="arbitrary", evidence={"passed": True}
    )
    assert all(row["status"] == "not_evaluated" for row in result["checks"].values())


def test_original_execution_bytes_persist_without_destabilizing_semantic_registration(
    tmp_path, monkeypatch
):
    """Serialization-only sealed trace, never supplied to a qualification verifier."""
    import json
    from pathlib import Path
    from types import SimpleNamespace

    result = {"status": "passed", "cases": [["sealed", "passed"]]}
    raw = {
        "junit.xml": b'<testsuite time="1"/>',
        "stdout.txt": b"sealed run one",
        "stderr.txt": b"",
        "execution.json": b'{"exit_code":0}',
    }
    monkeypatch.setitem(checks._TEST_RUN_LOGS, checks._hash(result), raw)
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    first = checks._persist_test_execution(settings, result)
    original = json.loads(Path(first["path"]).read_text())
    xml = next(Path(p) for p in original["files"] if p.endswith("junit.xml"))
    monkeypatch.setitem(
        checks._TEST_RUN_LOGS,
        checks._hash(result),
        {**raw, "junit.xml": b'<testsuite time="2"/>', "stdout.txt": b"sealed run two"},
    )
    assert checks._persist_test_execution(settings, result) == first
    assert xml.read_bytes() == raw["junit.xml"]
    assert len(list(xml.parent.parent.iterdir())) == 2
    xml.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="execution_changed"):
        checks._persist_test_execution(settings, result)


def test_disclosed_empty_trace_index_is_not_a_closed_execution(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace

    result = {"status": "passed", "cases": [["sealed", "passed"]]}
    raw = {
        "junit.xml": b"<testsuite/>",
        "stdout.txt": b"",
        "stderr.txt": b"",
        "execution.json": b"{}",
    }
    monkeypatch.setitem(checks._TEST_RUN_LOGS, checks._hash(result), raw)
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    first = checks._persist_test_execution(settings, result)
    path = Path(first["path"])
    value = json.loads(path.read_text())
    value["files"] = {}
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="closure_invalid"):
        checks._persist_test_execution(settings, result)
