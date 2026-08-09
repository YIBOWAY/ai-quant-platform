"""Production probes for the durable Agent v0.2 release gate.

The gate consumes observations only. This module binds those observations to
the actual clean Platform/HQA/Hermes checkouts, the live PostgreSQL schema and
runtime role, one sealed local evidence file, and a fresh loopback Hermes
capability response.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from quant_system.config.settings import Settings
from quant_system.hermes.connector_liveness import (
    connector_liveness_runtime_security_is_ready_on_connection,
)
from quant_system.hermes.effective_release_gate import (
    EffectiveReleaseDecision,
    EffectiveReleaseGate,
    HermesDurableCapabilityObservation,
    LocalReleaseFlags,
    ReleaseEvidenceObservation,
    RuntimeIdentityObservation,
)
from quant_system.hermes.gateway_client import HermesApiReadClient
from quant_system.hermes.release_authority import (
    ReleaseAuthority,
    release_authority_runtime_security_ready,
    release_authority_schema_ready,
)
from quant_system.hermes.session_registry import hermes_runtime_security_ready
from quant_system.hermes.test_execution_evidence import (
    TestExecutionEvidenceError,
    read_owner_only_file,
    validate_test_execution_receipt,
)
from quant_system.storage.database import get_database, schema_fingerprint

_LOGICAL_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
_EVIDENCE_CONTRACT_V4 = "agent-v0.2-release-evidence/v4"
_ARTIFACT_CONTRACT = "agent-v0.2-release-artifact/v2"
_RUNTIME_NAMES = ("platform", "hqa", "hermes")
_REQUIRED_TEST_SUITES = frozenset({"platform", "hqa", "hermes_focused", "frontend"})
_REQUIRED_REAL_FLOWS = frozenset(
    {
        "web_chat_multi_turn",
        "hermes_restart_recovery",
        "exact_message_fork",
        "options_vertical_live_futu_ro",
        "paper_factor_gate_1_2_3_via_hermes",
    }
)
_HEX_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_FORK_POINT_RE = re.compile(r"^message:[1-9][0-9]*$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
_MAX_ARTIFACT_PATH_BYTES = 512


class ReleaseRuntimeProbeError(RuntimeError):
    """A runtime identity/evidence observation could not be trusted."""


def _runtime_digest_from_commit(logical_name: str, commit: str) -> str:
    if _LOGICAL_NAME_RE.fullmatch(logical_name) is None:
        raise ReleaseRuntimeProbeError("runtime logical name is invalid")
    if _HEX_COMMIT_RE.fullmatch(commit) is None:
        raise ReleaseRuntimeProbeError("runtime commit identity is invalid")
    payload = b"agent-v0.2-runtime\x00" + logical_name.encode("ascii")
    payload += b"\x00commit\x00" + commit.encode("ascii") + b"\x00"
    return hashlib.sha256(payload).hexdigest()


def _run_git(root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseRuntimeProbeError("runtime root is not a readable Git checkout") from exc
    if len(completed.stdout) > 1024 * 1024:
        raise ReleaseRuntimeProbeError("Git runtime observation is oversized")
    return completed.stdout


def git_runtime_digest(root: Path, *, logical_name: str) -> str:
    """Hash one logical runtime name plus its exact clean Git commit."""

    if _LOGICAL_NAME_RE.fullmatch(logical_name) is None:
        raise ReleaseRuntimeProbeError("runtime logical name is invalid")
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        raise ReleaseRuntimeProbeError("runtime root is unavailable")
    commit = _run_git(path, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if not re.fullmatch(rb"[0-9a-f]{40,64}", commit):
        raise ReleaseRuntimeProbeError("runtime commit identity is invalid")
    dirty = _run_git(
        path,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    if dirty:
        raise ReleaseRuntimeProbeError("runtime checkout must be clean before release admission")
    return _runtime_digest_from_commit(logical_name, commit.decode("ascii"))


def hermes_process_runtime_digest(
    payload: Mapping[str, object],
    *,
    runtime_root: Path,
) -> str:
    """Validate the boot-frozen identity reported by the live Hermes process."""

    runtime = payload.get("runtime")
    if not isinstance(runtime, Mapping):
        raise ReleaseRuntimeProbeError("Hermes process identity is unavailable")
    instance_id = runtime.get("instance_id")
    started_at = runtime.get("started_at")
    pid = runtime.get("pid")
    if (
        not isinstance(instance_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", instance_id) is None
        or not isinstance(started_at, str)
        or _UTC_TIMESTAMP_RE.fullmatch(started_at) is None
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
    ):
        raise ReleaseRuntimeProbeError("Hermes process identity is invalid")

    build = runtime.get("build")
    required_build_keys = frozenset(
        {
            "schema_version",
            "source",
            "ready",
            "root_realpath",
            "module_realpath",
            "entrypoint_sha256",
            "commit",
            "tree",
            "clean",
            "digest",
        }
    )
    if not isinstance(build, Mapping) or frozenset(build) != required_build_keys:
        raise ReleaseRuntimeProbeError("Hermes process build identity is unavailable")
    if (
        build.get("schema_version") != 1
        or build.get("source") != "git_worktree"
        or build.get("ready") is not True
        or build.get("clean") is not True
    ):
        raise ReleaseRuntimeProbeError("Hermes process build is not release-ready")

    expected_root = Path(runtime_root).expanduser().resolve()
    expected_module = (expected_root / "gateway/platforms/api_server.py").resolve()
    if build.get("root_realpath") != str(expected_root) or build.get("module_realpath") != str(
        expected_module
    ):
        raise ReleaseRuntimeProbeError("Hermes process root identity mismatches")
    commit = build.get("commit")
    tree = build.get("tree")
    entrypoint_sha256 = build.get("entrypoint_sha256")
    claimed_digest = build.get("digest")
    if (
        not isinstance(commit, str)
        or _HEX_COMMIT_RE.fullmatch(commit) is None
        or not isinstance(tree, str)
        or _HEX_COMMIT_RE.fullmatch(tree) is None
        or not isinstance(entrypoint_sha256, str)
        or _HEX_DIGEST_RE.fullmatch(entrypoint_sha256) is None
        or not isinstance(claimed_digest, str)
        or _HEX_DIGEST_RE.fullmatch(claimed_digest) is None
    ):
        raise ReleaseRuntimeProbeError("Hermes process build identity is invalid")

    digest_document = dict(build)
    digest_document.pop("digest")
    recomputed_digest = hashlib.sha256(
        json.dumps(
            digest_document,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if recomputed_digest != claimed_digest:
        raise ReleaseRuntimeProbeError("Hermes process build digest mismatches")

    expected_commit = (
        _run_git(
            expected_root,
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
        )
        .strip()
        .decode("ascii")
    )
    expected_tree = (
        _run_git(
            expected_root,
            "rev-parse",
            "--verify",
            "HEAD^{tree}",
        )
        .strip()
        .decode("ascii")
    )
    if commit != expected_commit or tree != expected_tree:
        raise ReleaseRuntimeProbeError("Hermes running build mismatches reviewed checkout")
    if _run_git(
        expected_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ):
        raise ReleaseRuntimeProbeError("Hermes reviewed checkout is no longer clean")
    try:
        current_entrypoint_sha256 = hashlib.sha256(expected_module.read_bytes()).hexdigest()
    except OSError as exc:
        raise ReleaseRuntimeProbeError("Hermes process entrypoint is unavailable") from exc
    if current_entrypoint_sha256 != entrypoint_sha256:
        raise ReleaseRuntimeProbeError("Hermes process entrypoint identity mismatches")
    return _runtime_digest_from_commit("hermes", commit)


def _read_bounded_owned_file(path: Path) -> bytes:
    try:
        return read_owner_only_file(
            path,
            maximum_bytes=_MAX_EVIDENCE_BYTES,
        )
    except TestExecutionEvidenceError as exc:
        raise ReleaseRuntimeProbeError(
            f"release evidence must be a safe mode 0600 file: {exc}"
        ) from exc


def _json_object_without_duplicates(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseRuntimeProbeError("release evidence contract contains duplicate keys")
        result[key] = value
    return result


def _exact_mapping(
    value: object,
    *,
    keys: frozenset[str],
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ReleaseRuntimeProbeError(f"release evidence contract field {field} is invalid")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReleaseRuntimeProbeError(f"release evidence contract field {field} is invalid")
    return value


def _hex_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _HEX_DIGEST_RE.fullmatch(value) is None:
        raise ReleaseRuntimeProbeError(f"release evidence contract field {field} digest is invalid")
    return value


def _bounded_identity(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > 256
        or any(ord(character) < 0x20 for character in value)
    ):
        raise ReleaseRuntimeProbeError(f"release evidence contract field {field} is invalid")
    return value


def _utc_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise ReleaseRuntimeProbeError(f"release evidence artifact timestamp {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseRuntimeProbeError(
            f"release evidence artifact timestamp {field} is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ReleaseRuntimeProbeError(f"release evidence artifact timestamp {field} is invalid")
    return parsed


def _strict_json(content: bytes, *, field: str) -> object:
    try:
        return json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicates,
        )
    except ReleaseRuntimeProbeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReleaseRuntimeProbeError(
            f"release evidence {field} must be valid UTF-8 JSON"
        ) from exc


def _artifact_file(
    *,
    manifest_path: Path,
    relative_path: object,
    used_paths: set[Path],
) -> Path:
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or len(relative_path.encode("utf-8")) > _MAX_ARTIFACT_PATH_BYTES
        or "\\" in relative_path
    ):
        raise ReleaseRuntimeProbeError(
            "release evidence artifact path must be a bounded relative path"
        )
    logical_path = PurePosixPath(relative_path)
    if (
        logical_path.is_absolute()
        or any(part in {"", ".", ".."} for part in logical_path.parts)
        or logical_path.as_posix() != relative_path
    ):
        raise ReleaseRuntimeProbeError(
            "release evidence artifact path must be a bounded relative path"
        )

    manifest_directory = Path(os.path.abspath(os.fspath(manifest_path.expanduser().parent)))
    candidate = manifest_directory.joinpath(*logical_path.parts)
    if candidate in used_paths:
        raise ReleaseRuntimeProbeError(
            "release evidence contract contains a duplicate artifact path"
        )
    used_paths.add(candidate)
    return candidate


def _artifact_payload(
    *,
    manifest_path: Path,
    artifact_ref: object,
    runtime_digests: Mapping[str, str],
    expected_kind: str,
    expected_name: str,
    used_paths: set[Path],
) -> Mapping[str, object]:
    reference = _exact_mapping(
        artifact_ref,
        keys=frozenset({"path", "sha256"}),
        field=f"{expected_kind}.{expected_name}.artifact",
    )
    expected_digest = _hex_digest(
        reference["sha256"],
        field=f"{expected_kind}.{expected_name}.artifact.sha256",
    )
    artifact_path = _artifact_file(
        manifest_path=manifest_path,
        relative_path=reference["path"],
        used_paths=used_paths,
    )
    content = _read_bounded_owned_file(artifact_path)
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise ReleaseRuntimeProbeError(
            "release evidence artifact digest does not match its manifest reference"
        )
    artifact = _exact_mapping(
        _strict_json(content, field="artifact"),
        keys=frozenset(
            {
                "contract",
                "kind",
                "name",
                "passed",
                "started_at",
                "completed_at",
                "runtime",
                "evidence",
            }
        ),
        field=f"{expected_kind}.{expected_name}.artifact",
    )
    if (
        artifact["contract"] != _ARTIFACT_CONTRACT
        or artifact["kind"] != expected_kind
        or artifact["name"] != expected_name
        or artifact["passed"] is not True
    ):
        raise ReleaseRuntimeProbeError(
            "release evidence artifact identity or passed state is invalid"
        )
    started_at = _utc_timestamp(artifact["started_at"], field="started_at")
    completed_at = _utc_timestamp(artifact["completed_at"], field="completed_at")
    if completed_at < started_at:
        raise ReleaseRuntimeProbeError("release evidence artifact timestamps are invalid")
    artifact_runtime = _exact_mapping(
        artifact["runtime"],
        keys=frozenset(_RUNTIME_NAMES),
        field=f"{expected_kind}.{expected_name}.artifact.runtime",
    )
    for logical_name in _RUNTIME_NAMES:
        digest = _hex_digest(
            artifact_runtime[logical_name],
            field=(f"{expected_kind}.{expected_name}.artifact.runtime.{logical_name}"),
        )
        if digest != runtime_digests[logical_name]:
            raise ReleaseRuntimeProbeError(
                "release evidence artifact runtime binding is inconsistent"
            )
    return artifact


def _validate_test_receipt(
    *,
    manifest_path: Path,
    receipt_ref: object,
    expected_name: str,
    expected_runtime: Mapping[str, Mapping[str, str]],
    expected_passed: int,
    expected_failed: int,
    expected_skipped: int,
    used_paths: set[Path],
) -> None:
    reference = _exact_mapping(
        receipt_ref,
        keys=frozenset({"path", "sha256"}),
        field=f"test.{expected_name}.receipt",
    )
    expected_digest = _hex_digest(
        reference["sha256"],
        field=f"test.{expected_name}.receipt.sha256",
    )
    receipt_path = _artifact_file(
        manifest_path=manifest_path,
        relative_path=reference["path"],
        used_paths=used_paths,
    )
    receipt_content = _read_bounded_owned_file(receipt_path)
    if hashlib.sha256(receipt_content).hexdigest() != expected_digest:
        raise ReleaseRuntimeProbeError("release evidence test receipt digest mismatches")
    try:
        execution = validate_test_execution_receipt(
            receipt_path,
            expected_name=expected_name,
            expected_runtime=expected_runtime,
        )
    except TestExecutionEvidenceError as exc:
        raise ReleaseRuntimeProbeError(str(exc)) from exc
    if (
        execution.counts.passed,
        execution.counts.failed,
        execution.counts.skipped,
    ) != (
        expected_passed,
        expected_failed,
        expected_skipped,
    ):
        raise ReleaseRuntimeProbeError(
            "release evidence test receipt counts do not match the manifest"
        )
    for evidence_path in (execution.output_path, execution.junit_path):
        absolute = Path(os.path.abspath(os.fspath(evidence_path)))
        if absolute in used_paths:
            raise ReleaseRuntimeProbeError(
                "release evidence contract contains a duplicate artifact path"
            )
        used_paths.add(absolute)


def _identity_list(
    value: object,
    *,
    field: str,
    minimum: int,
) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum or len(value) > 256:
        raise ReleaseRuntimeProbeError(f"release evidence {field} is invalid")
    identities = [
        _bounded_identity(item, field=f"{field}[{index}]") for index, item in enumerate(value)
    ]
    if len(set(identities)) != len(identities):
        raise ReleaseRuntimeProbeError(f"release evidence {field} must contain distinct identities")
    return identities


def _validate_flow_artifact(
    artifact: Mapping[str, object],
    *,
    name: str,
) -> None:
    raw_evidence = artifact["evidence"]
    if name == "web_chat_multi_turn":
        evidence = _exact_mapping(
            raw_evidence,
            keys=frozenset(
                {
                    "route",
                    "user_message_count",
                    "assistant_message_count",
                    "command_ids",
                    "run_ids",
                }
            ),
            field="web_chat_multi_turn",
        )
        if (
            evidence["route"] != "/hermes"
            or _nonnegative_int(
                evidence["user_message_count"],
                field="web_chat_multi_turn.user_message_count",
            )
            < 2
            or _nonnegative_int(
                evidence["assistant_message_count"],
                field="web_chat_multi_turn.assistant_message_count",
            )
            < 2
        ):
            raise ReleaseRuntimeProbeError(
                "release evidence web chat multi-turn route/counts are invalid"
            )
        command_ids = _identity_list(
            evidence["command_ids"],
            field="web chat multi-turn command IDs",
            minimum=2,
        )
        run_ids = _identity_list(
            evidence["run_ids"],
            field="web chat multi-turn run IDs",
            minimum=2,
        )
        if set(command_ids) & set(run_ids):
            raise ReleaseRuntimeProbeError(
                "release evidence web chat multi-turn command/run IDs must be distinct"
            )
        return

    if name == "hermes_restart_recovery":
        evidence = _exact_mapping(
            raw_evidence,
            keys=frozenset(
                {
                    "route",
                    "before_transcript_digest",
                    "after_transcript_digest",
                }
            ),
            field=name,
        )
        before = _hex_digest(
            evidence["before_transcript_digest"],
            field=f"{name}.before_transcript_digest",
        )
        after = _hex_digest(
            evidence["after_transcript_digest"],
            field=f"{name}.after_transcript_digest",
        )
        if evidence["route"] != "/hermes" or before != after:
            raise ReleaseRuntimeProbeError("release evidence Hermes restart recovery is invalid")
        return

    if name == "exact_message_fork":
        evidence = _exact_mapping(
            raw_evidence,
            keys=frozenset(
                {
                    "route",
                    "source_session_id",
                    "child_session_id",
                    "fork_point",
                    "preserve_source",
                }
            ),
            field=name,
        )
        source = _bounded_identity(
            evidence["source_session_id"],
            field=f"{name}.source_session_id",
        )
        child = _bounded_identity(
            evidence["child_session_id"],
            field=f"{name}.child_session_id",
        )
        if (
            evidence["route"] != "/hermes"
            or source == child
            or not isinstance(evidence["fork_point"], str)
            or _FORK_POINT_RE.fullmatch(evidence["fork_point"]) is None
            or evidence["preserve_source"] is not True
        ):
            raise ReleaseRuntimeProbeError("release evidence exact message fork is invalid")
        return

    if name == "options_vertical_live_futu_ro":
        evidence = _exact_mapping(
            raw_evidence,
            keys=frozenset(
                {
                    "route",
                    "provider",
                    "provider_evidence_digest",
                    "orders_created",
                }
            ),
            field=name,
        )
        _hex_digest(
            evidence["provider_evidence_digest"],
            field=f"{name}.provider_evidence_digest",
        )
        if (
            evidence["route"] != "/hermes"
            or evidence["provider"] != "futu"
            or _nonnegative_int(
                evidence["orders_created"],
                field=f"{name}.orders_created",
            )
            != 0
        ):
            raise ReleaseRuntimeProbeError(
                "release evidence options Futu read-only flow is invalid"
            )
        return

    if name != "paper_factor_gate_1_2_3_via_hermes":
        raise ReleaseRuntimeProbeError("release evidence real flow identity is invalid")
    evidence = _exact_mapping(
        raw_evidence,
        keys=frozenset(
            {
                "route",
                "provider",
                "gate1_confirmation_id",
                "gate2_decision_id",
                "gate3_promotion_id",
                "candidate_id",
                "candidate_digest",
                "final_backtest_receipt_id",
                "reviewed_commit",
                "orders_created",
            }
        ),
        field=name,
    )
    gate_fields = (
        "gate1_confirmation_id",
        "gate2_decision_id",
        "gate3_promotion_id",
    )
    gate_ids = [
        _bounded_identity(evidence[field], field=f"{name}.{field}") for field in gate_fields
    ]
    if len(set(gate_ids)) != len(gate_ids):
        raise ReleaseRuntimeProbeError(
            "release evidence paper Gate 1/2/3 identities must be distinct"
        )
    for field in (
        "candidate_id",
        "final_backtest_receipt_id",
    ):
        _bounded_identity(evidence[field], field=f"{name}.{field}")
    _hex_digest(evidence["candidate_digest"], field=f"{name}.candidate_digest")
    reviewed_commit = evidence["reviewed_commit"]
    if (
        evidence["route"] != "/hermes"
        or evidence["provider"] != "futu"
        or not isinstance(reviewed_commit, str)
        or _HEX_COMMIT_RE.fullmatch(reviewed_commit) is None
        or _nonnegative_int(
            evidence["orders_created"],
            field=f"{name}.orders_created",
        )
        != 0
    ):
        raise ReleaseRuntimeProbeError("release evidence paper Gate 1/2/3 flow is invalid")


def release_evidence_observation(path: Path) -> ReleaseEvidenceObservation:
    """Validate and bind the complete Agent v0.2 release evidence manifest."""

    content = _read_bounded_owned_file(path)
    raw_root = _strict_json(content, field="contract")
    if not isinstance(raw_root, Mapping):
        raise ReleaseRuntimeProbeError("release evidence contract field root is invalid")
    contract = raw_root.get("contract")
    if contract != _EVIDENCE_CONTRACT_V4:
        raise ReleaseRuntimeProbeError("release evidence contract version is invalid")
    root = _exact_mapping(
        raw_root,
        keys=frozenset(
            {
                "candidate",
                "contract",
                "real_flows",
                "runtime",
                "safety",
                "tests",
            }
        ),
        field="root",
    )

    runtime = _exact_mapping(
        root["runtime"],
        keys=frozenset(_RUNTIME_NAMES),
        field="runtime",
    )
    runtime_digests: dict[str, str] = {}
    runtime_document: dict[str, dict[str, str]] = {}
    for logical_name in _RUNTIME_NAMES:
        item = _exact_mapping(
            runtime[logical_name],
            keys=frozenset({"commit", "digest"}),
            field=f"runtime.{logical_name}",
        )
        commit = item["commit"]
        digest = item["digest"]
        if not isinstance(commit, str) or _HEX_COMMIT_RE.fullmatch(commit) is None:
            raise ReleaseRuntimeProbeError(
                f"release evidence contract runtime.{logical_name}.commit is invalid"
            )
        if not isinstance(digest, str) or _HEX_DIGEST_RE.fullmatch(digest) is None:
            raise ReleaseRuntimeProbeError(
                f"release evidence contract runtime.{logical_name}.digest is invalid"
            )
        if digest != _runtime_digest_from_commit(logical_name, commit):
            raise ReleaseRuntimeProbeError(
                f"release evidence contract runtime.{logical_name} is inconsistent"
            )
        runtime_digests[logical_name] = digest
        runtime_document[logical_name] = {
            "commit": commit,
            "digest": digest,
        }

    used_artifact_paths: set[Path] = set()
    tests = _exact_mapping(
        root["tests"],
        keys=frozenset({"passed", "suites"}),
        field="tests",
    )
    if tests["passed"] is not True or not isinstance(tests["suites"], list):
        raise ReleaseRuntimeProbeError("release evidence contract tests did not pass")
    suite_names: set[str] = set()
    for index, raw_suite in enumerate(tests["suites"]):
        suite = _exact_mapping(
            raw_suite,
            keys=frozenset({"name", "passed", "failed", "skipped", "receipt"}),
            field=f"tests.suites[{index}]",
        )
        name = suite["name"]
        if not isinstance(name, str) or not name or name in suite_names:
            raise ReleaseRuntimeProbeError(
                "release evidence contract test suite identity is invalid"
            )
        suite_names.add(name)
        passed = _nonnegative_int(
            suite["passed"],
            field=f"tests.suites[{index}].passed",
        )
        failed = _nonnegative_int(
            suite["failed"],
            field=f"tests.suites[{index}].failed",
        )
        skipped = _nonnegative_int(
            suite["skipped"],
            field=f"tests.suites[{index}].skipped",
        )
        if passed < 1 or failed != 0:
            raise ReleaseRuntimeProbeError("release evidence contract tests did not pass")
        _validate_test_receipt(
            manifest_path=path,
            receipt_ref=suite["receipt"],
            expected_name=name,
            expected_runtime=runtime_document,
            expected_passed=passed,
            expected_failed=failed,
            expected_skipped=skipped,
            used_paths=used_artifact_paths,
        )
    if suite_names != _REQUIRED_TEST_SUITES:
        raise ReleaseRuntimeProbeError("release evidence contract required test suites are missing")

    real_flows = _exact_mapping(
        root["real_flows"],
        keys=frozenset({"passed", "flows"}),
        field="real_flows",
    )
    if real_flows["passed"] is not True or not isinstance(real_flows["flows"], list):
        raise ReleaseRuntimeProbeError("release evidence contract real flows did not pass")
    flow_names: set[str] = set()
    for index, raw_flow in enumerate(real_flows["flows"]):
        flow = _exact_mapping(
            raw_flow,
            keys=frozenset({"name", "passed", "artifact"}),
            field=f"real_flows.flows[{index}]",
        )
        name = flow["name"]
        if (
            not isinstance(name, str)
            or not name
            or name in flow_names
            or flow["passed"] is not True
        ):
            raise ReleaseRuntimeProbeError("release evidence contract real flow receipt is invalid")
        flow_names.add(name)
        artifact = _artifact_payload(
            manifest_path=path,
            artifact_ref=flow["artifact"],
            runtime_digests=runtime_digests,
            expected_kind="real_flow",
            expected_name=name,
            used_paths=used_artifact_paths,
        )
        _validate_flow_artifact(artifact, name=name)
    if not _REQUIRED_REAL_FLOWS.issubset(flow_names):
        raise ReleaseRuntimeProbeError("release evidence contract required real flows are missing")

    safety = _exact_mapping(
        root["safety"],
        keys=frozenset({"orders_created", "kill_switch", "live_trading_enabled"}),
        field="safety",
    )
    if (
        _nonnegative_int(
            safety["orders_created"],
            field="safety.orders_created",
        )
        != 0
        or safety["kill_switch"] is not True
        or safety["live_trading_enabled"] is not False
    ):
        raise ReleaseRuntimeProbeError("release evidence contract safety facts are unsafe")

    candidate = _exact_mapping(
        root["candidate"],
        keys=frozenset(
            {
                "admission_digest",
                "admission_id",
                "evidence_set_digest",
                "evidence_set_id",
                "final_order_snapshot_digest",
            }
        ),
        field="candidate",
    )
    candidate_fields = {
        "candidate_admission_id": _bounded_identity(
            candidate["admission_id"],
            field="candidate.admission_id",
        ),
        "candidate_admission_digest": _hex_digest(
            candidate["admission_digest"],
            field="candidate.admission_digest",
        ),
        "evidence_set_id": _bounded_identity(
            candidate["evidence_set_id"],
            field="candidate.evidence_set_id",
        ),
        "evidence_set_digest": _hex_digest(
            candidate["evidence_set_digest"],
            field="candidate.evidence_set_digest",
        ),
        "final_order_snapshot_digest": _hex_digest(
            candidate["final_order_snapshot_digest"],
            field="candidate.final_order_snapshot_digest",
        ),
    }

    return ReleaseEvidenceObservation(
        digest=hashlib.sha256(content).hexdigest(),
        platform_runtime_digest=runtime_digests["platform"],
        hqa_runtime_digest=runtime_digests["hqa"],
        hermes_runtime_digest=runtime_digests["hermes"],
        contract=str(contract),
        **candidate_fields,
    )


def file_sha256(path: Path) -> str:
    """Return the digest of one fully validated release evidence manifest."""

    return release_evidence_observation(path).digest


def platform_runtime_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _capture_platform_boot_runtime_digest() -> str | None:
    try:
        return git_runtime_digest(
            platform_runtime_root(),
            logical_name="platform",
        )
    except ReleaseRuntimeProbeError:
        return None


# Capture once for the lifetime of this Python process.  A checkout moving
# underneath an old backend must close release admission, not relabel that
# already-imported process as the new build.
_PLATFORM_BOOT_RUNTIME_DIGEST = _capture_platform_boot_runtime_digest()


def runtime_identity_observation(settings: Settings) -> RuntimeIdentityObservation:
    if _PLATFORM_BOOT_RUNTIME_DIGEST is None:
        raise ReleaseRuntimeProbeError(
            "platform process did not boot from a clean reviewed runtime"
        )
    return RuntimeIdentityObservation(
        platform_runtime_digest=_PLATFORM_BOOT_RUNTIME_DIGEST,
        hqa_runtime_digest=git_runtime_digest(
            settings.intent_payload.hqa_root,
            logical_name="hqa",
        ),
        hermes_runtime_digest=git_runtime_digest(
            settings.hermes_gateway.runtime_root,
            logical_name="hermes",
        ),
    )


def restricted_runtime_security_ready(settings: Settings) -> bool:
    """Verify every Agent v0.2 write authority under the constrained login."""

    try:
        if not hermes_runtime_security_ready(settings):
            return False
        if not release_authority_runtime_security_ready(settings):
            return False
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as connection:
            return connector_liveness_runtime_security_is_ready_on_connection(connection)
    except Exception:  # noqa: BLE001 - any observation uncertainty closes writes
        return False


def build_effective_release_gate(
    settings: Settings,
    *,
    gateway_client: HermesApiReadClient | None = None,
    now: Callable[[], datetime] | None = None,
) -> EffectiveReleaseGate:
    clock = now or (lambda: datetime.now(UTC))
    client = gateway_client or HermesApiReadClient(settings.hermes_gateway)

    def _capability() -> HermesDurableCapabilityObservation:
        payload = client.capabilities()
        hermes_digest = hermes_process_runtime_digest(
            payload,
            runtime_root=settings.hermes_gateway.runtime_root,
        )
        return HermesDurableCapabilityObservation(
            runtime_digest=hermes_digest,
            observed_at=clock(),
            payload=payload,
        )

    return EffectiveReleaseGate(
        authority=ReleaseAuthority(settings),
        local_flags_probe=lambda: LocalReleaseFlags(
            mutation_enabled=settings.local_mutation.enabled,
            composer_open=settings.local_mutation.composer_open,
            hermes_gateway_enabled=settings.hermes_gateway.enabled,
            kill_switch_enabled=settings.safety.kill_switch,
            live_trading_enabled=settings.safety.live_trading_enabled,
            candidate_admission_enabled=(settings.candidate_admission.enabled),
        ),
        runtime_identity_probe=lambda: runtime_identity_observation(settings),
        database_schema_fingerprint_probe=lambda: schema_fingerprint(get_database(settings)),
        release_evidence_probe=lambda: release_evidence_observation(
            settings.agent_v02_release.evidence_file
        ),
        runtime_role_readiness_probe=lambda: restricted_runtime_security_ready(settings),
        authority_schema_readiness_probe=lambda: release_authority_schema_ready(settings),
        hermes_capability_probe=_capability,
        now=clock,
        capability_max_age=timedelta(seconds=settings.agent_v02_release.capability_max_age_seconds),
    )


def current_release_decision(
    settings: Settings,
    *,
    gateway_client: HermesApiReadClient | None = None,
    now: Callable[[], datetime] | None = None,
) -> EffectiveReleaseDecision:
    return build_effective_release_gate(
        settings,
        gateway_client=gateway_client,
        now=now,
    ).evaluate(settings.agent_v02_release.workspace_id)


__all__ = [
    "ReleaseRuntimeProbeError",
    "ReleaseEvidenceObservation",
    "build_effective_release_gate",
    "current_release_decision",
    "file_sha256",
    "git_runtime_digest",
    "hermes_process_runtime_digest",
    "platform_runtime_root",
    "release_evidence_observation",
    "restricted_runtime_security_ready",
    "runtime_identity_observation",
]
