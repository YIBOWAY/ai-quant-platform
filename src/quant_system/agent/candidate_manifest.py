"""Exact-byte candidate manifests and verified snapshots.

Identity validation, canonical digests, and dirfd-backed reads for the
candidate pool. Consumers of a VerifiedCandidateSnapshot must use the already
verified artifact_bytes and must not reopen snapshot.candidate_dir / name.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_system.agent.candidate_fs import (
    CandidateConflictError,
    CandidateIntegrityError,
    OpenedDirectory,
    assert_entry_is_open_fd,
    open_absolute_directory,
    open_directory_at,
    read_regular_bytes_at,
)
from quant_system.agent.models import ReviewRecord
from quant_system.agent.paths import resolve_agent_output_dir, resolve_candidates_dir

__all__ = [
    "CandidateConflictError",
    "CandidateFileDigest",
    "CandidateIntegrityError",
    "CandidateManifestV1",
    "CandidateMigrationRequiredError",
    "CandidateReviewStateStaleError",
    "CandidateStaleError",
    "VerifiedCandidateSnapshot",
    "_normalized_relative_path",
    "_validate_candidate_id",
    "build_candidate_manifest",
    "canonical_json_bytes",
    "load_verified_candidate_snapshot",
    "verify_candidate_directory",
]

_SAFE_CANDIDATE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_RESERVED_CANDIDATE_COMPONENTS = frozenset(
    {
        "metadata.json",
        "manifest.v1.json",
        "approved.lock",
        "rejected.lock",
        "legacy-approved.lock",
        "legacy-rejected.lock",
        "reviews.jsonl",
        ".candidate-pool.lock",
    }
)
_RESERVED_CASEFOLD = frozenset(
    name.casefold() for name in _RESERVED_CANDIDATE_COMPONENTS
)

_METADATA_NAME = "metadata.json"
_MANIFEST_NAME = "manifest.v1.json"
_APPROVED_LOCK = "approved.lock"
_REJECTED_LOCK = "rejected.lock"
_LEGACY_APPROVED_LOCK = "legacy-approved.lock"
_LEGACY_REJECTED_LOCK = "legacy-rejected.lock"


class CandidateMigrationRequiredError(CandidateIntegrityError):
    """Candidate is safely readable but lacks a stored manifest.v1.json."""


class CandidateStaleError(RuntimeError):
    """Review/write expected digest or state no longer matches."""


class CandidateReviewStateStaleError(CandidateStaleError):
    """Review expected_status no longer matches."""


class CandidateFileDigest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str
    size_bytes: int
    sha256: str


class CandidateManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str
    artifact_type: str
    goal: str
    universe: list[str]
    metadata_sha256: str
    files: list[CandidateFileDigest]


class CandidateReviewLockV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"]
    candidate_id: str = Field(min_length=1)
    decision: Literal["approve", "reject"]
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    created_at: str = Field(min_length=1)


class VerifiedCandidateSnapshot(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    candidate_id: str
    candidate_dir: Path
    metadata: dict[str, Any]
    manifest: CandidateManifestV1
    manifest_digest: str
    approval_binding: Literal["pending", "approved", "rejected", "legacy_unbound"]
    artifact_bytes: dict[str, bytes] = Field(default_factory=dict)
    review_record: ReviewRecord | None = None


def _validate_candidate_id(value: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or PurePosixPath(value).is_absolute()
        or _SAFE_CANDIDATE_ID.fullmatch(value) is None
        or value in _RESERVED_CANDIDATE_COMPONENTS
    ):
        raise CandidateIntegrityError("candidate_id is not a canonical component")
    return value


def _normalized_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or "." in path.parts
        or ".." in path.parts
        or len(path.parts) != 1
        or str(path) != value
        or not value.isascii()
        or path.name.casefold() in _RESERVED_CASEFOLD
    ):
        raise CandidateIntegrityError("candidate file path is not canonical")
    return path


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _parse_metadata(metadata_bytes: bytes) -> dict[str, Any]:
    try:
        metadata = json.loads(metadata_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateIntegrityError("metadata.json is not valid UTF-8 JSON") from exc
    if not isinstance(metadata, dict):
        raise CandidateIntegrityError("metadata.json must be a JSON object")
    return metadata


def _coerce_str_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CandidateIntegrityError(f"metadata.{field} must be a list of strings")
    return list(value)


def _build_manifest_from_opened(
    opened: OpenedDirectory,
) -> tuple[CandidateManifestV1, str, dict[str, bytes], dict[str, Any], bytes]:
    candidate_id = _validate_candidate_id(opened.name)
    assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)

    metadata_bytes = read_regular_bytes_at(opened.fd, _METADATA_NAME)
    metadata = _parse_metadata(metadata_bytes)

    meta_id = metadata.get("candidate_id")
    if not isinstance(meta_id, str) or meta_id != candidate_id:
        raise CandidateIntegrityError(
            "candidate_id mismatch between directory and metadata"
        )

    artifact_type = metadata.get("artifact_type")
    goal = metadata.get("goal")
    if not isinstance(artifact_type, str) or not artifact_type:
        raise CandidateIntegrityError("metadata.artifact_type is required")
    if not isinstance(goal, str):
        raise CandidateIntegrityError("metadata.goal is required")
    universe = _coerce_str_list(metadata.get("universe", []), field="universe")
    files_value = metadata.get("files")
    if not isinstance(files_value, list) or not all(
        isinstance(item, str) for item in files_value
    ):
        raise CandidateIntegrityError("metadata.files must be a list of strings")

    seen_casefold: set[str] = set()
    normalized_names: list[str] = []
    for raw_name in files_value:
        path = _normalized_relative_path(raw_name)
        name = path.name
        folded = name.casefold()
        if folded in seen_casefold:
            raise CandidateIntegrityError(
                f"duplicate candidate file path (casefold): {name!r}"
            )
        seen_casefold.add(folded)
        normalized_names.append(name)

    artifact_bytes: dict[str, bytes] = {}
    digests: list[CandidateFileDigest] = []
    for name in normalized_names:
        payload = read_regular_bytes_at(opened.fd, name)
        artifact_bytes[name] = payload
        digests.append(
            CandidateFileDigest(
                path=name,
                size_bytes=len(payload),
                sha256=_sha256_hex(payload),
            )
        )

    # Explicit POSIX basename order for the authoritative file list.
    digests_sorted = sorted(digests, key=lambda item: item.path)
    artifact_bytes = {item.path: artifact_bytes[item.path] for item in digests_sorted}

    manifest = CandidateManifestV1(
        schema_version="1.0",
        candidate_id=candidate_id,
        artifact_type=artifact_type,
        goal=goal,
        universe=universe,
        metadata_sha256=_sha256_hex(metadata_bytes),
        files=digests_sorted,
    )
    digest = _sha256_hex(canonical_json_bytes(manifest.model_dump(mode="json")))
    assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
    return manifest, digest, artifact_bytes, metadata, metadata_bytes


def build_candidate_manifest(
    candidate_dir: Path,
) -> tuple[CandidateManifestV1, str, dict[str, bytes]]:
    """Build an exact-byte manifest from metadata.json and listed artifacts."""
    with open_absolute_directory(Path(candidate_dir), create=False) as opened:
        manifest, digest, artifact_bytes, _metadata, _raw = _build_manifest_from_opened(
            opened
        )
        return manifest, digest, artifact_bytes


def _try_read_control(parent_fd: int, name: str) -> bytes | None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot stat control {name!r}") from exc
    # Present: must be a safe single-link regular file (hardlinks/symlinks corrupt).
    return read_regular_bytes_at(parent_fd, name)


def _parse_bound_review(
    payload: bytes, *, decision: Literal["approve", "reject"]
) -> tuple[ReviewRecord, str] | None:
    """Parse a structured review lock; return (record, lowercase hex digest) or None."""
    try:
        data = json.loads(payload.decode("utf-8"))
        lock = CandidateReviewLockV1.model_validate(data)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if lock.decision != decision:
        return None
    if payload != canonical_json_bytes(lock.model_dump(mode="json")):
        return None
    try:
        return (
            ReviewRecord(
                candidate_id=lock.candidate_id,
                decision=lock.decision,
                note=lock.note,
                reviewer=lock.reviewer,
                created_at=lock.created_at,
                manifest_digest=lock.manifest_digest,
            ),
            lock.manifest_digest,
        )
    except Exception:
        return None


def _approval_binding_at(
    parent_fd: int,
    *,
    candidate_id: str,
    manifest_digest: str,
) -> tuple[Literal["pending", "approved", "rejected", "legacy_unbound"], ReviewRecord | None]:
    """Read approval controls; authorize only when ID + digest bind to this candidate."""
    approved = _try_read_control(parent_fd, _APPROVED_LOCK)
    rejected = _try_read_control(parent_fd, _REJECTED_LOCK)
    legacy_approved = _try_read_control(parent_fd, _LEGACY_APPROVED_LOCK)
    legacy_rejected = _try_read_control(parent_fd, _LEGACY_REJECTED_LOCK)

    present = [
        name
        for name, payload in (
            (_APPROVED_LOCK, approved),
            (_REJECTED_LOCK, rejected),
            (_LEGACY_APPROVED_LOCK, legacy_approved),
            (_LEGACY_REJECTED_LOCK, legacy_rejected),
        )
        if payload is not None
    ]
    if not present:
        return "pending", None
    if len(present) > 1:
        # Conflicting controls are not a trustworthy binding.
        return "legacy_unbound", None

    if approved is not None:
        parsed = _parse_bound_review(approved, decision="approve")
        if (
            parsed is not None
            and parsed[0].candidate_id == candidate_id
            and parsed[1] == manifest_digest
        ):
            return "approved", parsed[0]
        # Structured-but-unbound / wrong-id / wrong-digest never authorize.
        return "legacy_unbound", None
    if rejected is not None:
        parsed = _parse_bound_review(rejected, decision="reject")
        if (
            parsed is not None
            and parsed[0].candidate_id == candidate_id
            and parsed[1] == manifest_digest
        ):
            return "rejected", parsed[0]
        return "legacy_unbound", None
    # legacy-* locks never authorize.
    return "legacy_unbound", None


def _verify_from_opened(
    opened: OpenedDirectory, *, candidate_dir: Path
) -> VerifiedCandidateSnapshot:
    manifest, digest, artifact_bytes, metadata, _raw = _build_manifest_from_opened(
        opened
    )

    # Stored manifest is required for verified authority.
    try:
        os.stat(_MANIFEST_NAME, dir_fd=opened.fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise CandidateMigrationRequiredError(
            "manifest.v1.json is missing; migration_required"
        ) from exc
    except OSError as exc:
        raise CandidateIntegrityError("cannot stat manifest.v1.json") from exc

    stored_bytes = read_regular_bytes_at(opened.fd, _MANIFEST_NAME)
    try:
        stored_obj = json.loads(stored_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateIntegrityError("manifest.v1.json is not valid UTF-8 JSON") from exc
    if not isinstance(stored_obj, dict):
        raise CandidateIntegrityError("manifest.v1.json must be a JSON object")

    stored_id = stored_obj.get("candidate_id")
    if not isinstance(stored_id, str) or stored_id != manifest.candidate_id:
        raise CandidateIntegrityError(
            "candidate_id mismatch between directory/metadata and stored manifest"
        )

    try:
        stored_manifest = CandidateManifestV1.model_validate(stored_obj)
    except Exception as exc:
        raise CandidateIntegrityError("manifest.v1.json failed schema validation") from exc

    rebuilt_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
    stored_canonical = canonical_json_bytes(stored_manifest.model_dump(mode="json"))
    if stored_canonical != rebuilt_bytes:
        raise CandidateIntegrityError(
            "stored manifest does not match exact current candidate bytes"
        )
    if stored_bytes != rebuilt_bytes:
        raise CandidateIntegrityError(
            "stored manifest bytes are not canonical JSON"
        )
    if _sha256_hex(rebuilt_bytes) != digest:
        raise CandidateIntegrityError("manifest digest mismatch")

    binding, review_record = _approval_binding_at(
        opened.fd,
        candidate_id=manifest.candidate_id,
        manifest_digest=digest,
    )
    assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)

    return VerifiedCandidateSnapshot(
        candidate_id=manifest.candidate_id,
        candidate_dir=Path(candidate_dir),
        metadata=metadata,
        manifest=manifest,
        manifest_digest=digest,
        approval_binding=binding,
        artifact_bytes=artifact_bytes,
        review_record=review_record,
    )


def verify_candidate_directory(candidate_dir: Path) -> VerifiedCandidateSnapshot:
    """Verify a candidate directory against stored manifest.v1.json."""
    path = Path(candidate_dir)
    with open_absolute_directory(path, create=False) as opened:
        return _verify_from_opened(opened, candidate_dir=path)


def load_verified_candidate_snapshot(
    *, agent_output_dir: str | Path, candidate_id: str
) -> VerifiedCandidateSnapshot:
    """Open agent/candidates/<id> only through the dirfd boundary and verify."""
    candidate_id = _validate_candidate_id(candidate_id)
    agent_root = resolve_agent_output_dir(agent_output_dir)
    candidates_dir = resolve_candidates_dir(agent_root)

    # Walk agent_output → agent → candidates → candidate_id holding FDs.
    with open_absolute_directory(agent_root, create=False) as agent_opened:
        assert_entry_is_open_fd(
            agent_opened.parent_fd, agent_opened.name, agent_opened.fd
        )
        agent_fd = open_directory_at(agent_opened.fd, "agent")
        try:
            assert_entry_is_open_fd(agent_opened.fd, "agent", agent_fd)
            candidates_fd = open_directory_at(agent_fd, "candidates")
            try:
                assert_entry_is_open_fd(agent_fd, "candidates", candidates_fd)
                candidate_fd = open_directory_at(candidates_fd, candidate_id)
                try:
                    assert_entry_is_open_fd(candidates_fd, candidate_id, candidate_fd)
                    st = os.fstat(candidate_fd)
                    opened = OpenedDirectory(
                        fd=candidate_fd,
                        parent_fd=candidates_fd,
                        name=candidate_id,
                        st_dev=st.st_dev,
                        st_ino=st.st_ino,
                    )
                    candidate_path = Path(candidates_dir) / candidate_id
                    snapshot = _verify_from_opened(
                        opened, candidate_dir=candidate_path
                    )
                    assert_entry_is_open_fd(candidates_fd, candidate_id, candidate_fd)
                    assert_entry_is_open_fd(agent_fd, "candidates", candidates_fd)
                    assert_entry_is_open_fd(agent_opened.fd, "agent", agent_fd)
                    assert_entry_is_open_fd(
                        agent_opened.parent_fd, agent_opened.name, agent_opened.fd
                    )
                    return snapshot
                finally:
                    os.close(candidate_fd)
            finally:
                os.close(candidates_fd)
        finally:
            os.close(agent_fd)
