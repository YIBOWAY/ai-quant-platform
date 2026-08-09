from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.hermes import release_runtime
from quant_system.hermes.release_runtime import (
    ReleaseRuntimeProbeError,
    file_sha256,
    git_runtime_digest,
    hermes_process_runtime_digest,
    restricted_runtime_security_ready,
)
from quant_system.hermes.test_execution_evidence import executable_evidence


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
    if tmp_path.name == "platform":
        frontend = repo / "src" / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text(
            '{"scripts":{"test":"vitest run"},"type":"module"}\n',
            encoding="utf-8",
        )
    _git(repo, "add", "runtime.py")
    if tmp_path.name == "platform":
        _git(repo, "add", "src/frontend/package.json")
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


def _tree(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _hermes_process_payload(repo: Path) -> dict[str, object]:
    module = repo / "gateway" / "platforms" / "api_server.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    if not module.exists():
        module.write_text("BOOT = 1\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "api server")
    build: dict[str, object] = {
        "schema_version": 1,
        "source": "git_worktree",
        "ready": True,
        "root_realpath": str(repo.resolve()),
        "module_realpath": str(module.resolve()),
        "entrypoint_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
        "commit": _commit(repo),
        "tree": _tree(repo),
        "clean": True,
    }
    build["digest"] = hashlib.sha256(
        json.dumps(
            build,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "runtime": {
            "instance_id": "a" * 32,
            "started_at": "2026-07-24T01:00:00.000000Z",
            "pid": 12345,
            "build": build,
        }
    }


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
    runtime_roots: dict[str, Path] = {}
    for logical_name in _RUNTIME_NAMES:
        repo = _clean_repo(tmp_path / logical_name)
        runtime_roots[logical_name] = repo
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
        output = f"{name} output\n".encode()
        junit = (
            f'<testsuite tests="1" failures="0" errors="0" skipped="0">'
            f'<testcase name="{name}"/></testsuite>'
        ).encode()
        output_digest = hashlib.sha256(output).hexdigest()
        junit_digest = hashlib.sha256(junit).hexdigest()
        stem = f"test-{name.replace('_', '-')}"
        runtime_name = {
            "platform": "platform",
            "hqa": "hqa",
            "hermes_focused": "hermes",
            "frontend": "platform",
        }[name]
        now = datetime.now(UTC)
        if name == "frontend":
            pnpm = shutil.which("pnpm")
            assert pnpm is not None
            executable = Path(pnpm).resolve()
            argv = [
                str(executable),
                "test",
                "--reporter=junit",
                f"--outputFile=/tmp/{name}.junit.xml.tmp",
            ]
            cwd = runtime_roots[runtime_name] / "src/frontend"
            cwd_relative = "src/frontend"
        else:
            executable = Path(sys.executable)
            argv = [
                sys.executable,
                "-m",
                "pytest",
                "tests",
                f"--junitxml=/tmp/{name}.junit.xml.tmp",
            ]
            cwd = runtime_roots[runtime_name]
            cwd_relative = "."
        artifacts[artifact_path] = {
            "argv": argv,
            "completed_at": now.isoformat().replace("+00:00", "Z"),
            "contract": "agent-v0.2-test-execution-receipt/v1",
            "cwd": {
                "realpath": str(cwd.resolve()),
                "relative": cwd_relative,
                "runtime": runtime_name,
            },
            "executable": executable_evidence(executable),
            "exit_code": 0,
            "junit": {
                "path": f"{stem}-junit-{junit_digest}.xml",
                "sha256": junit_digest,
                "size_bytes": len(junit),
                "_content": junit.decode(),
            },
            "name": name,
            "output": {
                "path": f"{stem}-output-{output_digest}.log",
                "sha256": output_digest,
                "size_bytes": len(output),
                "_content": output.decode(),
            },
            "runtime": {logical_name: dict(runtime) for logical_name, runtime in runtimes.items()},
            "started_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "summary": {
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "total": 1,
            },
        }
        suites.append(
            {
                "name": name,
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "receipt": {"path": artifact_path, "sha256": ""},
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
        "candidate": {
            "admission_id": "candidate-exact",
            "admission_digest": "5" * 64,
            "evidence_set_id": "evidence-exact",
            "evidence_set_digest": "6" * 64,
            "final_order_snapshot_digest": "7" * 64,
        },
        "contract": "agent-v0.2-release-evidence/v4",
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
    suites = payload["tests"]["suites"]  # type: ignore[index]
    for index, name in enumerate(_TEST_SUITES):
        logical_path = f"artifacts/test-{name}.json"
        receipt = artifacts[logical_path]
        output = receipt["output"]
        junit = receipt["junit"]
        assert isinstance(output, dict)
        assert isinstance(junit, dict)
        output_content = output.pop("_content").encode()
        junit_content = junit.pop("_content").encode()
        output_file = artifacts_dir / str(output["path"])
        junit_file = artifacts_dir / str(junit["path"])
        output_file.write_bytes(output_content)
        junit_file.write_bytes(junit_content)
        output_file.chmod(0o600)
        junit_file.chmod(0o600)
        receipt_content = json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        receipt_digest = hashlib.sha256(receipt_content).hexdigest()
        receipt_name = f"test-{name.replace('_', '-')}-receipt-{receipt_digest}.json"
        receipt_file = artifacts_dir / receipt_name
        receipt_file.write_bytes(receipt_content)
        receipt_file.chmod(0o600)
        suites[index]["receipt"] = {
            "path": f"artifacts/{receipt_name}",
            "sha256": receipt_digest,
        }
    flows = payload["real_flows"]["flows"]  # type: ignore[index]
    for index, name in enumerate(_REAL_FLOWS):
        logical_path = f"artifacts/flow-{name}.json"
        artifact_file = tmp_path / logical_path
        artifact_file.write_text(
            json.dumps(artifacts[logical_path], sort_keys=True),
            encoding="utf-8",
        )
        artifact_file.chmod(0o600)
        flows[index]["artifact"]["sha256"] = hashlib.sha256(  # type: ignore[index]
            artifact_file.read_bytes()
        ).hexdigest()
    if mutate_manifest is not None:
        mutate_manifest(payload)
    evidence = tmp_path / "release-evidence.json"
    evidence.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    evidence.chmod(0o600)
    return evidence


def test_git_runtime_digest_is_stable_for_one_clean_commit(tmp_path: Path) -> None:
    repo = _clean_repo(tmp_path)

    first = git_runtime_digest(repo, logical_name="platform")
    second = git_runtime_digest(repo, logical_name="platform")

    assert first == second
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")
    assert git_runtime_digest(repo, logical_name="hqa") != first


def test_hermes_process_runtime_digest_binds_live_boot_to_reviewed_checkout(
    tmp_path: Path,
) -> None:
    repo = _clean_repo(tmp_path)
    payload = _hermes_process_payload(repo)

    assert hermes_process_runtime_digest(
        payload,
        runtime_root=repo,
    ) == git_runtime_digest(repo, logical_name="hermes")


def test_hermes_process_runtime_digest_rejects_stale_process_after_checkout_moves(
    tmp_path: Path,
) -> None:
    repo = _clean_repo(tmp_path)
    stale_payload = _hermes_process_payload(repo)
    (repo / "runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "move reviewed checkout")

    with pytest.raises(
        ReleaseRuntimeProbeError,
        match="running build mismatches",
    ):
        hermes_process_runtime_digest(stale_payload, runtime_root=repo)


def test_hermes_process_runtime_digest_rejects_forged_or_dirty_identity(
    tmp_path: Path,
) -> None:
    repo = _clean_repo(tmp_path)
    payload = _hermes_process_payload(repo)
    payload["runtime"]["build"]["digest"] = "f" * 64  # type: ignore[index]
    with pytest.raises(ReleaseRuntimeProbeError, match="build digest"):
        hermes_process_runtime_digest(payload, runtime_root=repo)

    payload = _hermes_process_payload(repo)
    (repo / "untracked.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(ReleaseRuntimeProbeError, match="no longer clean"):
        hermes_process_runtime_digest(payload, runtime_root=repo)


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
    evidence.chmod(0o600)

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
    large.chmod(0o600)
    with pytest.raises(ReleaseRuntimeProbeError, match="bounded"):
        file_sha256(large)


@pytest.mark.parametrize(
    "legacy_contract",
    [
        "agent-v0.2-release-evidence/v1",
        "agent-v0.2-release-evidence/v2",
        "agent-v0.2-release-evidence/v3",
    ],
)
def test_release_evidence_v4_rejects_legacy_self_attested_receipts(
    tmp_path: Path,
    legacy_contract: str,
) -> None:
    payload, _ = _release_evidence_payload(tmp_path / "repos")
    payload["contract"] = legacy_contract
    evidence = tmp_path / "release-evidence.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    evidence.chmod(0o600)

    with pytest.raises(ReleaseRuntimeProbeError, match="version"):
        file_sha256(evidence)


def test_release_evidence_v4_binds_verified_candidate_set_identity(
    tmp_path: Path,
) -> None:
    evidence = _write_release_evidence(tmp_path)

    observation = release_runtime.release_evidence_observation(evidence)

    assert observation.contract == "agent-v0.2-release-evidence/v4"
    assert observation.candidate_admission_id == "candidate-exact"
    assert observation.candidate_admission_digest == "5" * 64
    assert observation.evidence_set_id == "evidence-exact"
    assert observation.evidence_set_digest == "6" * 64
    assert observation.final_order_snapshot_digest == "7" * 64


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
        payload["tests"]["suites"][0]["receipt"]["path"] = bad_path  # type: ignore[index]

    evidence = _write_release_evidence(tmp_path, mutate_manifest=_mutate)

    with pytest.raises(ReleaseRuntimeProbeError, match=error):
        file_sha256(evidence)


def test_release_evidence_rejects_duplicate_artifact_path(tmp_path: Path) -> None:
    def _mutate(payload: dict[str, object]) -> None:
        suites = payload["tests"]["suites"]  # type: ignore[index]
        suites[1]["receipt"] = dict(suites[0]["receipt"])

    evidence = _write_release_evidence(tmp_path, mutate_manifest=_mutate)

    with pytest.raises(ReleaseRuntimeProbeError, match="duplicate artifact"):
        file_sha256(evidence)


def test_release_evidence_rejects_artifact_symlink_and_writable_file(
    tmp_path: Path,
) -> None:
    evidence = _write_release_evidence(tmp_path)
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    artifact = tmp_path / payload["tests"]["suites"][0]["receipt"]["path"]
    original = artifact.with_suffix(".original")
    artifact.rename(original)
    artifact.symlink_to(original)

    with pytest.raises(ReleaseRuntimeProbeError, match="regular|symlink"):
        file_sha256(evidence)

    artifact.unlink()
    original.rename(artifact)
    artifact.chmod(0o664)
    with pytest.raises(ReleaseRuntimeProbeError, match="mode 0600"):
        file_sha256(evidence)


@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-link contract")
@pytest.mark.parametrize("target_kind", ["manifest", "flow"])
def test_release_evidence_rejects_hardlinked_manifest_or_flow_artifact(
    tmp_path: Path,
    target_kind: str,
) -> None:
    evidence = _write_release_evidence(tmp_path)
    target = evidence
    if target_kind == "flow":
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        target = tmp_path / payload["real_flows"]["flows"][0]["artifact"]["path"]
    os.link(target, target.with_suffix(".alias"))

    with pytest.raises(ReleaseRuntimeProbeError, match="single-link"):
        file_sha256(evidence)


def test_release_evidence_rejects_artifact_digest_or_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    evidence = _write_release_evidence(tmp_path / "digest")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    artifact_ref = payload["tests"]["suites"][0]["receipt"]
    artifact_ref["sha256"] = "f" * 64
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReleaseRuntimeProbeError, match="digest"):
        file_sha256(evidence)

    duplicate = _write_release_evidence(tmp_path / "duplicate")
    duplicate_payload = json.loads(duplicate.read_text(encoding="utf-8"))
    duplicate_ref = duplicate_payload["tests"]["suites"][0]["receipt"]
    duplicate_file = duplicate.parent / duplicate_ref["path"]
    duplicate_file.write_text(
        '{"contract":"agent-v0.2-release-artifact/v2","contract":"agent-v0.2-release-artifact/v2"}',
        encoding="utf-8",
    )
    duplicate_ref["sha256"] = hashlib.sha256(duplicate_file.read_bytes()).hexdigest()
    duplicate.write_text(json.dumps(duplicate_payload), encoding="utf-8")
    with pytest.raises(ReleaseRuntimeProbeError, match="duplicate.*keys"):
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
        artifacts["artifacts/test-platform.json"]["summary"]["passed"] = 2  # type: ignore[index]

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
        artifact = artifacts[artifact_path]
        if artifact_path.startswith("artifacts/test-"):
            if field == "output_sha256":
                artifact["output"]["sha256"] = value  # type: ignore[index]
            else:
                artifact[field] = value
        else:
            artifact["evidence"][field] = value  # type: ignore[index]

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
