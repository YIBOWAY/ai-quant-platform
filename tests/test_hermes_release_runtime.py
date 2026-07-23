from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.hermes import release_runtime
from quant_system.hermes.release_runtime import (
    ReleaseRuntimeProbeError,
    file_sha256,
    git_runtime_digest,
    restricted_runtime_security_ready,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _clean_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "runtime"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Agent v0.2 Test")
    _git(repo, "config", "user.email", "agent-v02@example.invalid")
    (repo / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "runtime.py")
    _git(repo, "commit", "-qm", "runtime")
    return repo


def _commit(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


_RUNTIME_NAMES = ("platform", "hqa", "hermes")
_TEST_SUITES = ("platform", "hqa", "hermes_focused", "frontend")
_REAL_FLOWS = (
    "web_chat_multi_turn",
    "hermes_restart_recovery",
    "exact_message_fork",
    "options_vertical_live_futu_ro",
    "paper_factor_gate_1_2_3_via_hermes",
)
_DIGESTS = {
    "transcript": "1" * 64,
    "provider": "2" * 64,
    "candidate": "3" * 64,
    "output": "4" * 64,
}


def _artifact_envelope(
    *,
    kind: str,
    name: str,
    runtime_digests: dict[str, str],
    evidence: dict[str, object],
) -> dict[str, object]:
    return {
        "contract": "agent-v0.2-release-artifact/v2",
        "kind": kind,
        "name": name,
        "passed": True,
        "started_at": "2026-07-24T01:00:00Z",
        "completed_at": "2026-07-24T01:01:00Z",
        "runtime": runtime_digests,
        "evidence": evidence,
    }


def _flow_evidence(name: str) -> dict[str, object]:
    if name == "web_chat_multi_turn":
        return {
            "route": "/hermes",
            "user_message_count": 2,
            "assistant_message_count": 2,
            "command_ids": ["cmd-1", "cmd-2"],
            "run_ids": ["run-1", "run-2"],
        }
    if name == "hermes_restart_recovery":
        return {
            "route": "/hermes",
            "before_transcript_digest": _DIGESTS["transcript"],
            "after_transcript_digest": _DIGESTS["transcript"],
        }
    if name == "exact_message_fork":
        return {
            "route": "/hermes",
            "source_session_id": "session-source",
            "child_session_id": "session-child",
            "fork_point": "message:2",
            "preserve_source": True,
        }
    if name == "options_vertical_live_futu_ro":
        return {
            "route": "/hermes",
            "provider": "futu",
            "provider_evidence_digest": _DIGESTS["provider"],
            "orders_created": 0,
        }
    assert name == "paper_factor_gate_1_2_3_via_hermes"
    return {
        "route": "/hermes",
        "provider": "futu",
        "gate1_confirmation_id": "gate1-confirmation-1",
        "gate2_decision_id": "gate2-decision-1",
        "gate3_promotion_id": "gate3-promotion-1",
        "candidate_id": "candidate-1",
        "candidate_digest": _DIGESTS["candidate"],
        "final_backtest_receipt_id": "backtest-receipt-1",
        "reviewed_commit": "a" * 40,
        "orders_created": 0,
    }


def _release_evidence_payload(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    runtimes: dict[str, object] = {}
    runtime_digests: dict[str, str] = {}
    for logical_name in _RUNTIME_NAMES:
        repo = _clean_repo(tmp_path / logical_name)
        digest = git_runtime_digest(repo, logical_name=logical_name)
        runtimes[logical_name] = {
            "commit": _commit(repo),
            "digest": digest,
        }
        runtime_digests[logical_name] = digest

    artifacts: dict[str, dict[str, object]] = {}
    suites: list[dict[str, object]] = []
    for name in _TEST_SUITES:
        artifact_path = f"artifacts/test-{name}.json"
        artifacts[artifact_path] = _artifact_envelope(
            kind="test",
            name=name,
            runtime_digests=runtime_digests,
            evidence={
                "argv": ["pytest", f"tests/{name}"],
                "exit_code": 0,
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "output_sha256": _DIGESTS["output"],
            },
        )
        suites.append(
            {
                "name": name,
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "artifact": {"path": artifact_path, "sha256": ""},
            }
        )

    flows: list[dict[str, object]] = []
    for name in _REAL_FLOWS:
        artifact_path = f"artifacts/flow-{name}.json"
        artifacts[artifact_path] = _artifact_envelope(
            kind="real_flow",
            name=name,
            runtime_digests=runtime_digests,
            evidence=_flow_evidence(name),
        )
        flows.append(
            {
                "name": name,
                "passed": True,
                "artifact": {"path": artifact_path, "sha256": ""},
            }
        )

    payload = {
        "contract": "agent-v0.2-release-evidence/v2",
        "runtime": runtimes,
        "tests": {
            "passed": True,
            "suites": suites,
        },
        "real_flows": {
            "passed": True,
            "flows": flows,
        },
        "safety": {
            "orders_created": 0,
            "kill_switch": True,
            "live_trading_enabled": False,
        },
    }
    return payload, artifacts


def _write_release_evidence(
    tmp_path: Path,
    *,
    mutate_artifacts: Callable[[dict[str, dict[str, object]]], None] | None = None,
    mutate_manifest: Callable[[dict[str, object]], None] | None = None,
) -> Path:
    payload, artifacts = _release_evidence_payload(tmp_path / "repos")
    if mutate_artifacts is not None:
        mutate_artifacts(artifacts)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)
    for relative_path, artifact in artifacts.items():
        artifact_file = tmp_path / relative_path
        artifact_file.write_text(
            json.dumps(artifact, sort_keys=True),
            encoding="utf-8",
        )
    items = [
        *payload["tests"]["suites"],  # type: ignore[index]
        *payload["real_flows"]["flows"],  # type: ignore[index]
    ]
    for item in items:
        artifact_ref = item["artifact"]
        artifact_file = tmp_path / artifact_ref["path"]
        artifact_ref["sha256"] = hashlib.sha256(artifact_file.read_bytes()).hexdigest()
    if mutate_manifest is not None:
        mutate_manifest(payload)
    evidence = tmp_path / "release-evidence.json"
    evidence.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return evidence


def test_git_runtime_digest_is_stable_for_one_clean_commit(tmp_path: Path) -> None:
    repo = _clean_repo(tmp_path)

    first = git_runtime_digest(repo, logical_name="platform")
    second = git_runtime_digest(repo, logical_name="platform")

    assert first == second
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")
    assert git_runtime_digest(repo, logical_name="hqa") != first


@pytest.mark.parametrize("kind", ["tracked", "untracked"])
def test_git_runtime_digest_fails_closed_for_dirty_source(
    tmp_path: Path,
    kind: str,
) -> None:
    repo = _clean_repo(tmp_path)
    if kind == "tracked":
        (repo / "runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    else:
        (repo / "untracked.py").write_text("DIRTY = True\n", encoding="utf-8")

    with pytest.raises(ReleaseRuntimeProbeError, match="clean"):
        git_runtime_digest(repo, logical_name="platform")


def test_release_evidence_digest_binds_exact_regular_file(tmp_path: Path) -> None:
    evidence = _write_release_evidence(tmp_path / "first")

    first = file_sha256(evidence)
    changed = _write_release_evidence(
        tmp_path / "changed",
        mutate_artifacts=lambda artifacts: artifacts["artifacts/flow-web_chat_multi_turn.json"][
            "evidence"
        ].update({"command_ids": ["cmd-1", "cmd-changed"]}),  # type: ignore[union-attr]
    )
    second = file_sha256(changed)

    assert len(first) == 64
    assert first != second


def test_release_evidence_rejects_arbitrary_json_even_when_named_passed(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "release-evidence.json"
    evidence.write_text(
        json.dumps({"status": "passed", "orders": 0}, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(ReleaseRuntimeProbeError, match="contract"):
        file_sha256(evidence)


def test_release_evidence_rejects_unproven_tests_flows_and_safety(
    tmp_path: Path,
) -> None:
    def _tests_failed(payload: dict[str, object]) -> None:
        payload["tests"]["passed"] = False  # type: ignore[index]

    def _missing_real_flow(payload: dict[str, object]) -> None:
        payload["real_flows"]["flows"].pop()  # type: ignore[index,union-attr]

    def _orders_created(payload: dict[str, object]) -> None:
        payload["safety"]["orders_created"] = 1  # type: ignore[index]

    def _kill_switch_off(payload: dict[str, object]) -> None:
        payload["safety"]["kill_switch"] = False  # type: ignore[index]

    def _live_enabled(payload: dict[str, object]) -> None:
        payload["safety"]["live_trading_enabled"] = True  # type: ignore[index]

    for index, mutation in enumerate(
        (
            _tests_failed,
            _missing_real_flow,
            _orders_created,
            _kill_switch_off,
            _live_enabled,
        )
    ):
        evidence = _write_release_evidence(
            tmp_path / f"invalid-{index}",
            mutate_manifest=mutation,
        )
        with pytest.raises(ReleaseRuntimeProbeError, match="contract"):
            file_sha256(evidence)


def test_release_evidence_runtime_commit_and_digest_must_be_self_consistent(
    tmp_path: Path,
) -> None:
    def _mutate(payload: dict[str, object]) -> None:
        payload["runtime"]["platform"]["digest"] = "f" * 64  # type: ignore[index]

    evidence = _write_release_evidence(tmp_path, mutate_manifest=_mutate)

    with pytest.raises(ReleaseRuntimeProbeError, match="inconsistent"):
        file_sha256(evidence)


def test_release_evidence_rejects_symlink_and_oversize(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ReleaseRuntimeProbeError, match="regular"):
        file_sha256(link)

    large = tmp_path / "large.json"
    large.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ReleaseRuntimeProbeError, match="bounded"):
        file_sha256(large)


def test_release_evidence_v2_rejects_legacy_self_attested_receipts(
    tmp_path: Path,
) -> None:
    payload, _ = _release_evidence_payload(tmp_path / "repos")
    payload["contract"] = "agent-v0.2-release-evidence/v1"
    evidence = tmp_path / "release-evidence.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ReleaseRuntimeProbeError, match="version"):
        file_sha256(evidence)


@pytest.mark.parametrize(
    ("bad_path", "error"),
    [
        ("/tmp/outside.json", "relative"),
        ("../outside.json", "relative"),
        ("artifacts/../outside.json", "relative"),
    ],
)
def test_release_evidence_rejects_unbounded_artifact_paths(
    tmp_path: Path,
    bad_path: str,
    error: str,
) -> None:
    def _mutate(payload: dict[str, object]) -> None:
        payload["tests"]["suites"][0]["artifact"]["path"] = bad_path  # type: ignore[index]

    evidence = _write_release_evidence(tmp_path, mutate_manifest=_mutate)

    with pytest.raises(ReleaseRuntimeProbeError, match=error):
        file_sha256(evidence)


def test_release_evidence_rejects_duplicate_artifact_path(tmp_path: Path) -> None:
    def _mutate(payload: dict[str, object]) -> None:
        suites = payload["tests"]["suites"]  # type: ignore[index]
        suites[1]["artifact"] = dict(suites[0]["artifact"])

    evidence = _write_release_evidence(tmp_path, mutate_manifest=_mutate)

    with pytest.raises(ReleaseRuntimeProbeError, match="duplicate artifact"):
        file_sha256(evidence)


def test_release_evidence_rejects_artifact_symlink_and_writable_file(
    tmp_path: Path,
) -> None:
    evidence = _write_release_evidence(tmp_path)
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    artifact = tmp_path / payload["tests"]["suites"][0]["artifact"]["path"]
    original = artifact.with_suffix(".original")
    artifact.rename(original)
    artifact.symlink_to(original)

    with pytest.raises(ReleaseRuntimeProbeError, match="regular|symlink"):
        file_sha256(evidence)

    artifact.unlink()
    original.rename(artifact)
    artifact.chmod(0o664)
    with pytest.raises(ReleaseRuntimeProbeError, match="writable"):
        file_sha256(evidence)


def test_release_evidence_rejects_artifact_digest_or_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    evidence = _write_release_evidence(tmp_path / "digest")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    artifact_ref = payload["tests"]["suites"][0]["artifact"]
    artifact_ref["sha256"] = "f" * 64
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReleaseRuntimeProbeError, match="digest"):
        file_sha256(evidence)

    duplicate = _write_release_evidence(tmp_path / "duplicate")
    duplicate_payload = json.loads(duplicate.read_text(encoding="utf-8"))
    duplicate_ref = duplicate_payload["tests"]["suites"][0]["artifact"]
    duplicate_file = duplicate.parent / duplicate_ref["path"]
    duplicate_file.write_text(
        '{"contract":"agent-v0.2-release-artifact/v2","contract":"agent-v0.2-release-artifact/v2"}',
        encoding="utf-8",
    )
    duplicate_ref["sha256"] = hashlib.sha256(duplicate_file.read_bytes()).hexdigest()
    duplicate.write_text(json.dumps(duplicate_payload), encoding="utf-8")
    with pytest.raises(ReleaseRuntimeProbeError, match="duplicate keys"):
        file_sha256(duplicate)


def test_release_evidence_artifacts_bind_runtime_and_manifest_facts(
    tmp_path: Path,
) -> None:
    def _bad_runtime(artifacts: dict[str, dict[str, object]]) -> None:
        artifacts["artifacts/test-platform.json"]["runtime"]["platform"] = "f" * 64  # type: ignore[index]

    with pytest.raises(ReleaseRuntimeProbeError, match="runtime"):
        file_sha256(
            _write_release_evidence(
                tmp_path / "runtime",
                mutate_artifacts=_bad_runtime,
            )
        )

    def _bad_count(artifacts: dict[str, dict[str, object]]) -> None:
        artifacts["artifacts/test-platform.json"]["evidence"]["passed"] = 2  # type: ignore[index]

    with pytest.raises(ReleaseRuntimeProbeError, match="counts"):
        file_sha256(
            _write_release_evidence(
                tmp_path / "counts",
                mutate_artifacts=_bad_count,
            )
        )


@pytest.mark.parametrize(
    ("artifact_path", "field", "value", "error"),
    [
        (
            "artifacts/test-platform.json",
            "argv",
            [],
            "argv",
        ),
        (
            "artifacts/test-platform.json",
            "exit_code",
            1,
            "exit",
        ),
        (
            "artifacts/test-platform.json",
            "output_sha256",
            "not-a-digest",
            "output",
        ),
        (
            "artifacts/flow-web_chat_multi_turn.json",
            "route",
            "/api/hermes",
            "route",
        ),
        (
            "artifacts/flow-web_chat_multi_turn.json",
            "assistant_message_count",
            1,
            "multi-turn",
        ),
        (
            "artifacts/flow-web_chat_multi_turn.json",
            "run_ids",
            ["cmd-1", "cmd-2"],
            "command/run",
        ),
        (
            "artifacts/flow-hermes_restart_recovery.json",
            "after_transcript_digest",
            "f" * 64,
            "restart",
        ),
        (
            "artifacts/flow-exact_message_fork.json",
            "fork_point",
            "message:0",
            "fork",
        ),
        (
            "artifacts/flow-exact_message_fork.json",
            "child_session_id",
            "session-source",
            "fork",
        ),
        (
            "artifacts/flow-options_vertical_live_futu_ro.json",
            "provider",
            "fixture",
            "options",
        ),
        (
            "artifacts/flow-options_vertical_live_futu_ro.json",
            "orders_created",
            1,
            "options",
        ),
        (
            "artifacts/flow-paper_factor_gate_1_2_3_via_hermes.json",
            "provider",
            "fixture",
            "paper",
        ),
        (
            "artifacts/flow-paper_factor_gate_1_2_3_via_hermes.json",
            "gate3_promotion_id",
            "",
            "paper",
        ),
        (
            "artifacts/flow-paper_factor_gate_1_2_3_via_hermes.json",
            "gate2_decision_id",
            "gate1-confirmation-1",
            "Gate 1/2/3",
        ),
        (
            "artifacts/flow-paper_factor_gate_1_2_3_via_hermes.json",
            "orders_created",
            1,
            "paper",
        ),
    ],
)
def test_release_evidence_rejects_invalid_artifact_facts(
    tmp_path: Path,
    artifact_path: str,
    field: str,
    value: object,
    error: str,
) -> None:
    def _mutate(artifacts: dict[str, dict[str, object]]) -> None:
        artifacts[artifact_path]["evidence"][field] = value  # type: ignore[index]

    evidence = _write_release_evidence(
        tmp_path,
        mutate_artifacts=_mutate,
    )

    with pytest.raises(ReleaseRuntimeProbeError, match=error):
        file_sha256(evidence)


def test_restricted_runtime_security_includes_connector_schema_rls_and_grants(
    monkeypatch,
) -> None:
    connection = object()
    database = SimpleNamespace(connect=lambda: nullcontext(connection))
    settings = SimpleNamespace()
    monkeypatch.setattr(release_runtime, "get_database", lambda _settings: database)
    monkeypatch.setattr(
        release_runtime,
        "hermes_runtime_security_ready",
        lambda _settings: True,
    )
    monkeypatch.setattr(
        release_runtime,
        "release_authority_runtime_security_ready",
        lambda _settings: True,
    )
    monkeypatch.setattr(
        release_runtime,
        "connector_liveness_runtime_security_is_ready_on_connection",
        lambda conn: conn is connection and False,
    )

    assert restricted_runtime_security_ready(settings) is False

    monkeypatch.setattr(
        release_runtime,
        "connector_liveness_runtime_security_is_ready_on_connection",
        lambda conn: conn is connection,
    )
    assert restricted_runtime_security_ready(settings) is True
