"""Strict, test-only evidence contract for Agent v0.2 candidate admission.

Candidate admission exists to break the release bootstrap cycle without
pretending that public real-flow evidence already exists.  Its evidence is
therefore deliberately narrower than final release evidence: four required
test suites, exact three-repository runtime identities, and immutable safety
facts.  Any real-flow field is rejected by the exact root schema.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from quant_system.hermes.test_execution_evidence import (
    TestExecutionEvidenceError,
    read_owner_only_file,
    validate_test_execution_receipt,
)

_CONTRACT = "agent-v0.2-candidate-evidence/v2"
_RUNTIME_NAMES = ("platform", "hqa", "hermes")
_REQUIRED_TEST_SUITES = frozenset({"platform", "hqa", "hermes_focused", "frontend"})
_HEX_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_PATH_BYTES = 512


class CandidateEvidenceError(RuntimeError):
    """Candidate evidence is malformed, mutable, or inconsistently bound."""


@dataclass(frozen=True)
class CandidatePreflightEvidenceObservation:
    digest: str
    platform_runtime_digest: str
    hqa_runtime_digest: str
    hermes_runtime_digest: str
    test_passed_count: int
    test_failed_count: int
    test_skipped_count: int


def _runtime_digest_from_commit(logical_name: str, commit: str) -> str:
    payload = b"agent-v0.2-runtime\x00" + logical_name.encode("ascii")
    payload += b"\x00commit\x00" + commit.encode("ascii") + b"\x00"
    return hashlib.sha256(payload).hexdigest()


def _read_mode_600_file(path: Path) -> bytes:
    try:
        return read_owner_only_file(
            path,
            maximum_bytes=_MAX_FILE_BYTES,
        )
    except TestExecutionEvidenceError as exc:
        raise CandidateEvidenceError(
            f"candidate evidence must be a safe mode 0600 file: {exc}"
        ) from exc


def _without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateEvidenceError("candidate evidence contains duplicate JSON keys")
        result[key] = value
    return result


def _strict_json(content: bytes) -> object:
    try:
        return json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_without_duplicate_keys,
        )
    except CandidateEvidenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CandidateEvidenceError("candidate evidence must be valid UTF-8 JSON") from exc


def _exact_mapping(
    value: object,
    *,
    keys: frozenset[str],
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CandidateEvidenceError(f"candidate evidence field {field} is invalid")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CandidateEvidenceError(f"candidate evidence field {field} is invalid")
    return value


def _digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _HEX_DIGEST_RE.fullmatch(value) is None:
        raise CandidateEvidenceError(f"candidate evidence field {field} is invalid")
    return value


def _artifact_path(
    manifest_path: Path,
    relative_path: object,
    *,
    used_paths: set[Path],
) -> Path:
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or len(relative_path.encode("utf-8")) > _MAX_PATH_BYTES
        or "\\" in relative_path
    ):
        raise CandidateEvidenceError(
            "candidate evidence artifact path must be a bounded relative path"
        )
    logical = PurePosixPath(relative_path)
    if (
        logical.is_absolute()
        or any(part in {"", ".", ".."} for part in logical.parts)
        or logical.as_posix() != relative_path
    ):
        raise CandidateEvidenceError(
            "candidate evidence artifact path must be a bounded relative path"
        )
    directory = Path(os.path.abspath(os.fspath(manifest_path.expanduser().parent)))
    candidate = directory.joinpath(*logical.parts)
    if candidate in used_paths:
        raise CandidateEvidenceError("candidate evidence contains a duplicate artifact path")
    used_paths.add(candidate)
    return candidate


def _test_artifact(
    *,
    manifest_path: Path,
    suite: Mapping[str, object],
    runtime: Mapping[str, Mapping[str, str]],
    used_paths: set[Path],
) -> None:
    name = suite["name"]
    assert isinstance(name, str)
    reference = _exact_mapping(
        suite["receipt"],
        keys=frozenset({"path", "sha256"}),
        field=f"tests.{name}.receipt",
    )
    expected_file_digest = _digest(
        reference["sha256"],
        field=f"tests.{name}.receipt.sha256",
    )
    path = _artifact_path(
        manifest_path,
        reference["path"],
        used_paths=used_paths,
    )
    content = _read_mode_600_file(path)
    if hashlib.sha256(content).hexdigest() != expected_file_digest:
        raise CandidateEvidenceError(
            "candidate evidence receipt digest does not match its reference"
        )
    try:
        execution = validate_test_execution_receipt(
            path,
            expected_name=name,
            expected_runtime=runtime,
        )
    except TestExecutionEvidenceError as exc:
        raise CandidateEvidenceError(str(exc)) from exc
    counts = (
        execution.counts.passed,
        execution.counts.failed,
        execution.counts.skipped,
    )
    manifest_counts = tuple(
        _nonnegative_int(suite[key], field=f"tests.{name}.{key}")
        for key in ("passed", "failed", "skipped")
    )
    if counts != manifest_counts:
        raise CandidateEvidenceError(
            "candidate evidence test receipt counts do not match the manifest"
        )
    for evidence_path in (execution.output_path, execution.junit_path):
        absolute = Path(os.path.abspath(os.fspath(evidence_path)))
        if absolute in used_paths:
            raise CandidateEvidenceError("candidate evidence contains a duplicate artifact path")
        used_paths.add(absolute)


def candidate_preflight_evidence_observation(
    path: Path,
) -> CandidatePreflightEvidenceObservation:
    """Validate one immutable test-only candidate-admission manifest."""

    content = _read_mode_600_file(path)
    root = _exact_mapping(
        _strict_json(content),
        keys=frozenset({"contract", "runtime", "tests", "safety"}),
        field="root",
    )
    if root["contract"] != _CONTRACT:
        raise CandidateEvidenceError("candidate evidence contract version is invalid")
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
        if not isinstance(commit, str) or _HEX_COMMIT_RE.fullmatch(commit) is None:
            raise CandidateEvidenceError(
                f"candidate evidence runtime.{logical_name}.commit is invalid"
            )
        digest = _digest(
            item["digest"],
            field=f"runtime.{logical_name}.digest",
        )
        if digest != _runtime_digest_from_commit(logical_name, commit):
            raise CandidateEvidenceError(
                f"candidate evidence runtime.{logical_name} is inconsistent"
            )
        runtime_digests[logical_name] = digest
        runtime_document[logical_name] = {
            "commit": commit,
            "digest": digest,
        }

    tests = _exact_mapping(
        root["tests"],
        keys=frozenset({"passed", "suites"}),
        field="tests",
    )
    suites = tests["suites"]
    if tests["passed"] is not True or not isinstance(suites, list):
        raise CandidateEvidenceError("candidate evidence tests did not pass")
    names: set[str] = set()
    totals = [0, 0, 0]
    used_paths: set[Path] = set()
    for index, raw_suite in enumerate(suites):
        suite = _exact_mapping(
            raw_suite,
            keys=frozenset({"name", "passed", "failed", "skipped", "receipt"}),
            field=f"tests.suites[{index}]",
        )
        name = suite["name"]
        if not isinstance(name, str) or not name or name in names:
            raise CandidateEvidenceError("candidate evidence test suite identity is invalid")
        names.add(name)
        counts = [
            _nonnegative_int(suite[key], field=f"tests.{name}.{key}")
            for key in ("passed", "failed", "skipped")
        ]
        if counts[0] < 1 or counts[1] != 0:
            raise CandidateEvidenceError("candidate evidence tests did not pass")
        for position, count in enumerate(counts):
            totals[position] += count
        _test_artifact(
            manifest_path=path,
            suite=suite,
            runtime=runtime_document,
            used_paths=used_paths,
        )
    if names != _REQUIRED_TEST_SUITES:
        raise CandidateEvidenceError("candidate evidence required test suites are missing")

    safety = _exact_mapping(
        root["safety"],
        keys=frozenset({"orders_created", "kill_switch", "live_trading_enabled"}),
        field="safety",
    )
    if (
        _nonnegative_int(safety["orders_created"], field="safety.orders_created") != 0
        or safety["kill_switch"] is not True
        or safety["live_trading_enabled"] is not False
    ):
        raise CandidateEvidenceError("candidate evidence safety facts are unsafe")

    return CandidatePreflightEvidenceObservation(
        digest=hashlib.sha256(content).hexdigest(),
        platform_runtime_digest=runtime_digests["platform"],
        hqa_runtime_digest=runtime_digests["hqa"],
        hermes_runtime_digest=runtime_digests["hermes"],
        test_passed_count=totals[0],
        test_failed_count=totals[1],
        test_skipped_count=totals[2],
    )


__all__ = [
    "CandidateEvidenceError",
    "CandidatePreflightEvidenceObservation",
    "candidate_preflight_evidence_observation",
]
