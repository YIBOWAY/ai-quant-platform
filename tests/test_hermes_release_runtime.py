from __future__ import annotations

import json
import subprocess
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


def _release_evidence_payload(tmp_path: Path) -> dict[str, object]:
    runtimes: dict[str, object] = {}
    for logical_name in ("platform", "hqa", "hermes"):
        repo = _clean_repo(tmp_path / logical_name)
        runtimes[logical_name] = {
            "commit": _commit(repo),
            "digest": git_runtime_digest(repo, logical_name=logical_name),
        }
    return {
        "contract": "agent-v0.2-release-evidence/v1",
        "runtime": runtimes,
        "tests": {
            "passed": True,
            "suites": [
                {"name": "platform", "passed": 1, "failed": 0, "skipped": 0},
                {"name": "hqa", "passed": 1, "failed": 0, "skipped": 0},
                {
                    "name": "hermes_focused",
                    "passed": 1,
                    "failed": 0,
                    "skipped": 0,
                },
                {"name": "frontend", "passed": 1, "failed": 0, "skipped": 0},
            ],
        },
        "real_flows": {
            "passed": True,
            "flows": [
                {
                    "name": name,
                    "passed": True,
                    "receipt_digest": str(index) * 64,
                }
                for index, name in enumerate(
                    (
                        "web_chat_multi_turn",
                        "hermes_restart_recovery",
                        "exact_message_fork",
                        "paper_factor_gate_1_2_3",
                    ),
                    start=1,
                )
            ],
        },
        "safety": {
            "orders_created": 0,
            "kill_switch": True,
            "live_trading_enabled": False,
        },
    }


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
    evidence = tmp_path / "release-evidence.json"
    evidence.write_text(
        json.dumps(_release_evidence_payload(tmp_path), sort_keys=True),
        encoding="utf-8",
    )

    first = file_sha256(evidence)
    payload = _release_evidence_payload(tmp_path / "changed")
    payload["real_flows"]["flows"][0]["receipt_digest"] = "f" * 64  # type: ignore[index]
    evidence.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    second = file_sha256(evidence)

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
    baseline = _release_evidence_payload(tmp_path)
    evidence = tmp_path / "release-evidence.json"

    invalid_payloads = []
    tests_failed = json.loads(json.dumps(baseline))
    tests_failed["tests"]["passed"] = False
    invalid_payloads.append(tests_failed)
    missing_real_flow = json.loads(json.dumps(baseline))
    missing_real_flow["real_flows"]["flows"].pop()
    invalid_payloads.append(missing_real_flow)
    orders_created = json.loads(json.dumps(baseline))
    orders_created["safety"]["orders_created"] = 1
    invalid_payloads.append(orders_created)
    kill_switch_off = json.loads(json.dumps(baseline))
    kill_switch_off["safety"]["kill_switch"] = False
    invalid_payloads.append(kill_switch_off)
    live_enabled = json.loads(json.dumps(baseline))
    live_enabled["safety"]["live_trading_enabled"] = True
    invalid_payloads.append(live_enabled)

    for payload in invalid_payloads:
        evidence.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ReleaseRuntimeProbeError, match="contract"):
            file_sha256(evidence)


def test_release_evidence_runtime_commit_and_digest_must_be_self_consistent(
    tmp_path: Path,
) -> None:
    payload = _release_evidence_payload(tmp_path)
    payload["runtime"]["platform"]["digest"] = "f" * 64  # type: ignore[index]
    evidence = tmp_path / "release-evidence.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")

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
