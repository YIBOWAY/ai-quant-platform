"""Atomic candidate repository with digest-bound review CAS.

All create/review mutations hold the candidates-root pool lock and write only
through Task-2 dirfd primitives. Metadata and artifact bytes are immutable after
publication; review status is derived from structured decision locks.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat as stat_mod
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from quant_system.agent.candidate_fs import (
    CandidateConflictError,
    CandidateIntegrityError,
    OpenedDirectory,
    assert_entry_is_open_fd,
    atomic_write_noreplace_at,
    locked_candidates_root,
    mkdir_exclusive_at,
    open_absolute_directory,
    open_directory_at,
    read_regular_bytes_at,
    remove_entry_tree_at,
    rename_directory_noreplace_at,
    write_regular_exclusive_at,
)
from quant_system.agent.candidate_manifest import (
    CandidateMigrationRequiredError,
    CandidateReviewStateStaleError,
    CandidateStaleError,
    VerifiedCandidateSnapshot,
    _build_manifest_from_opened,
    _normalized_relative_path,
    _validate_candidate_id,
    _verify_from_opened,
    canonical_json_bytes,
    load_verified_candidate_snapshot,
)
from quant_system.agent.models import (
    CandidateArtifact,
    CandidateReadItem,
    CandidateStatus,
    ReviewRecord,
    utc_now_iso,
)
from quant_system.agent.paths import resolve_candidates_dir

__all__ = [
    "CandidateConflictError",
    "CandidateIntegrityError",
    "CandidateMigrationRequiredError",
    "CandidatePool",
    "CandidateReviewStateStaleError",
    "CandidateStaleError",
]

_SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_]+")
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PROTECTED_METADATA_KEYS = frozenset(
    {
        "candidate_id",
        "task_id",
        "artifact_type",
        "goal",
        "universe",
        "status",
        "created_at",
        "updated_at",
        "files",
        "safety",
    }
)
_METADATA_NAME = "metadata.json"
_MANIFEST_NAME = "manifest.v1.json"
_APPROVED_LOCK = "approved.lock"
_REJECTED_LOCK = "rejected.lock"
_LEGACY_APPROVED_LOCK = "legacy-approved.lock"
_LEGACY_REJECTED_LOCK = "legacy-rejected.lock"
_CONTROL_NAMES = (
    _APPROVED_LOCK,
    _REJECTED_LOCK,
    _LEGACY_APPROVED_LOCK,
    _LEGACY_REJECTED_LOCK,
)
_SKIP_LIST_NAMES = frozenset({".candidate-pool.lock", ".", ".."})


def _slug(value: str, *, fallback: str = "candidate", max_length: int = 40) -> str:
    cleaned = _SAFE_ID_PATTERN.sub("_", value.lower()).strip("_")
    return (cleaned or fallback)[:max_length].strip("_") or fallback


def _candidate_id(*, task_id: str, artifact_type: str, goal: str) -> str:
    digest = hashlib.sha256(f"{task_id}|{artifact_type}|{goal}".encode()).hexdigest()[:10]
    return _validate_candidate_id(
        f"{_slug(artifact_type)}-{_slug(goal)}-{digest}"
    )


def _validate_filename(filename: str) -> str:
    return _normalized_relative_path(filename).name


def _validate_digest(value: str) -> str:
    if not isinstance(value, str) or _HEX_DIGEST.fullmatch(value) is None:
        raise CandidateIntegrityError("manifest digest must be lowercase 64-char hex")
    return value


def _validate_note(note: str) -> str:
    if not isinstance(note, str) or not (1 <= len(note) <= 2000):
        raise CandidateIntegrityError("review note must be 1..2000 characters")
    return note


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _control_present(parent_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot stat control {name!r}") from exc


def _any_decision_control(parent_fd: int) -> bool:
    return any(_control_present(parent_fd, name) for name in _CONTROL_NAMES)


def _stable_inputs_match(
    snapshot: VerifiedCandidateSnapshot,
    *,
    task_id: str,
    goal: str,
    artifact_type: str,
    filename: str,
    content: str,
    universe: list[str],
    metadata_extra: dict[str, Any],
) -> bool:
    meta = snapshot.metadata
    if meta.get("task_id") != task_id:
        return False
    if meta.get("goal") != goal:
        return False
    if meta.get("artifact_type") != artifact_type:
        return False
    if list(meta.get("universe") or []) != list(universe):
        return False
    if list(meta.get("files") or []) != [filename]:
        return False
    existing_extra = {
        key: value for key, value in meta.items() if key not in _PROTECTED_METADATA_KEYS
    }
    if existing_extra != metadata_extra:
        return False
    expected = content.encode("utf-8")
    actual = snapshot.artifact_bytes.get(filename)
    return actual == expected


def _artifact_from_snapshot(
    snapshot: VerifiedCandidateSnapshot,
    *,
    task_id: str | None = None,
) -> CandidateArtifact:
    filename = snapshot.manifest.files[0].path if snapshot.manifest.files else ""
    meta_task = snapshot.metadata.get("task_id")
    resolved_task = task_id if task_id is not None else (
        meta_task if isinstance(meta_task, str) else ""
    )
    created = snapshot.metadata.get("created_at")
    kwargs: dict[str, Any] = {
        "candidate_id": snapshot.candidate_id,
        "task_id": resolved_task,
        "artifact_type": snapshot.manifest.artifact_type,
        "path": snapshot.candidate_dir / filename,
        "metadata_path": snapshot.candidate_dir / _METADATA_NAME,
        "status": CandidateStatus.PENDING,
        "manifest_digest": snapshot.manifest_digest,
    }
    if isinstance(created, str):
        kwargs["created_at"] = created
    return CandidateArtifact(**kwargs)


def _status_from_binding(
    binding: str,
) -> Literal["pending", "approved", "rejected"] | None:
    if binding in {"pending", "approved", "rejected"}:
        return binding  # type: ignore[return-value]
    return None


def _integrity_error_code(exc: BaseException) -> str:
    text = str(exc).lower()
    if "symlink" in text:
        return "symlink"
    if "hard link" in text or "nlink" in text:
        return "hardlink"
    if "candidate_id" in text:
        return "id_mismatch"
    if "manifest" in text:
        return "manifest_mismatch"
    if "regular" in text or "not a" in text:
        return "type_mismatch"
    return "corrupt"


class CandidatePool:
    """Stores agent outputs as inert candidate artifacts for human review."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.candidates_dir = resolve_candidates_dir(self.output_dir)

    def write_candidate(
        self,
        *,
        task_id: str,
        goal: str,
        artifact_type: str,
        filename: str,
        content: str,
        universe: list[str] | None = None,
        metadata_extra: dict[str, Any] | None = None,
    ) -> CandidateArtifact:
        candidate_id = _candidate_id(task_id=task_id, artifact_type=artifact_type, goal=goal)
        safe_filename = _validate_filename(filename)
        universe_list = list(universe or [])
        extra = dict(metadata_extra or {})
        collisions = set(extra) & _PROTECTED_METADATA_KEYS
        if collisions:
            raise CandidateIntegrityError(
                f"metadata_extra collides with protected keys: {sorted(collisions)}"
            )
        if not isinstance(content, str):
            raise CandidateIntegrityError("candidate content must be a string")
        content_bytes = content.encode("utf-8")

        with locked_candidates_root(self.output_dir, create=True) as root:
            assert_entry_is_open_fd(root.parent_fd, root.name, root.fd)

            if _control_present(root.fd, candidate_id) or self._entry_is_dir(
                root.fd, candidate_id
            ):
                try:
                    existing = self._verify_under_root(root, candidate_id)
                except CandidateMigrationRequiredError as exc:
                    raise CandidateConflictError(
                        f"candidate {candidate_id!r} exists without verified manifest"
                    ) from exc
                except CandidateIntegrityError as exc:
                    raise CandidateConflictError(
                        f"candidate {candidate_id!r} exists and is not reusable"
                    ) from exc
                if _stable_inputs_match(
                    existing,
                    task_id=task_id,
                    goal=goal,
                    artifact_type=artifact_type,
                    filename=safe_filename,
                    content=content,
                    universe=universe_list,
                    metadata_extra=extra,
                ):
                    assert_entry_is_open_fd(root.parent_fd, root.name, root.fd)
                    return _artifact_from_snapshot(existing, task_id=task_id)
                raise CandidateConflictError(
                    f"candidate {candidate_id!r} already exists with different bytes"
                )

            staging_name = f".staging-{secrets.token_hex(16)}"
            published = False
            mkdir_exclusive_at(root.fd, staging_name)
            staging_fd: int | None = None
            try:
                staging_fd = open_directory_at(root.fd, staging_name)
                assert_entry_is_open_fd(root.fd, staging_name, staging_fd)
                mkdir_exclusive_at(staging_fd, candidate_id)
                candidate_fd = open_directory_at(staging_fd, candidate_id)
                try:
                    assert_entry_is_open_fd(staging_fd, candidate_id, candidate_fd)
                    created_at = utc_now_iso()
                    metadata: dict[str, Any] = {
                        "candidate_id": candidate_id,
                        "task_id": task_id,
                        "artifact_type": artifact_type,
                        "goal": goal,
                        "universe": universe_list,
                        "status": CandidateStatus.PENDING.value,
                        "created_at": created_at,
                        "updated_at": created_at,
                        "files": [safe_filename],
                        "safety": {
                            "auto_promotion": False,
                            "requires_human_review": True,
                            "review_status": "pending",
                        },
                    }
                    for key, value in extra.items():
                        if key not in _PROTECTED_METADATA_KEYS:
                            metadata[key] = value

                    # Pretty-printed metadata for human readability; digest binds
                    # exact stored bytes via metadata_sha256 of these bytes.
                    metadata_bytes = json.dumps(
                        metadata, indent=2, sort_keys=True, ensure_ascii=False
                    ).encode("utf-8")
                    write_regular_exclusive_at(
                        candidate_fd, _METADATA_NAME, metadata_bytes
                    )
                    write_regular_exclusive_at(
                        candidate_fd, safe_filename, content_bytes
                    )

                    st = os.fstat(candidate_fd)
                    staged = OpenedDirectory(
                        fd=candidate_fd,
                        parent_fd=staging_fd,
                        name=candidate_id,
                        st_dev=st.st_dev,
                        st_ino=st.st_ino,
                    )
                    manifest, digest, _artifact_bytes, _meta, _raw = (
                        _build_manifest_from_opened(staged)
                    )
                    manifest_bytes = canonical_json_bytes(
                        manifest.model_dump(mode="json")
                    )
                    write_regular_exclusive_at(
                        candidate_fd, _MANIFEST_NAME, manifest_bytes
                    )
                    # Verify staged candidate fully before publication.
                    snapshot = _verify_from_opened(
                        staged,
                        candidate_dir=self.candidates_dir / candidate_id,
                    )
                    if snapshot.manifest_digest != digest:
                        raise CandidateIntegrityError("staged digest mismatch")
                    assert_entry_is_open_fd(staging_fd, candidate_id, candidate_fd)
                    assert_entry_is_open_fd(root.fd, staging_name, staging_fd)
                    assert_entry_is_open_fd(root.parent_fd, root.name, root.fd)

                    rename_directory_noreplace_at(
                        staging_fd, candidate_id, root.fd, candidate_id
                    )
                    os.fsync(root.fd)
                    published = True
                    assert_entry_is_open_fd(root.parent_fd, root.name, root.fd)
                finally:
                    os.close(candidate_fd)
            except Exception:
                if not published:
                    with suppress(Exception):
                        remove_entry_tree_at(root.fd, staging_name)
                raise
            else:
                with suppress(Exception):
                    remove_entry_tree_at(root.fd, staging_name)
            finally:
                if staging_fd is not None:
                    with suppress(OSError):
                        os.close(staging_fd)

            published_snap = self._verify_under_root(root, candidate_id)
            assert_entry_is_open_fd(root.parent_fd, root.name, root.fd)
            return _artifact_from_snapshot(published_snap, task_id=task_id)

    def get(self, candidate_id: str) -> VerifiedCandidateSnapshot:
        candidate_id = _validate_candidate_id(candidate_id)
        return load_verified_candidate_snapshot(
            agent_output_dir=self.output_dir, candidate_id=candidate_id
        )

    def list_candidates(self) -> list[dict[str, Any]]:
        """Legacy-shaped listing; prefer list_for_read for integrity-aware reads."""
        items: list[dict[str, Any]] = []
        for item in self.list_for_read():
            payload = item.model_dump(mode="json")
            items.append(payload)
        return items

    def list_for_read(self) -> list[CandidateReadItem]:
        # Path.exists() follows symlinks and reports a dangling symlink as
        # absent. lexists keeps that unsafe directory entry visible so the
        # no-follow opener can reject it instead of reporting an empty pool.
        if not os.path.lexists(self.candidates_dir):
            return []
        results: list[CandidateReadItem] = []
        try:
            with open_absolute_directory(self.candidates_dir, create=False) as root:
                assert_entry_is_open_fd(root.parent_fd, root.name, root.fd)
                names = sorted(os.listdir(root.fd))
                for name in names:
                    if name in _SKIP_LIST_NAMES or name.startswith(".staging-"):
                        continue
                    if name.startswith("."):
                        # Hidden control/lock files are not candidates.
                        continue
                    results.append(self._read_item_at(root, name))
                assert_entry_is_open_fd(root.parent_fd, root.name, root.fd)
        except CandidateIntegrityError:
            # A corrupt individual candidate is represented by _read_item_at(),
            # but an unsafe root invalidates the whole repository.  Propagate it
            # so API/CLI consumers cannot confuse repository failure with empty.
            raise
        # Newest-first by path mtime when available, else stable name order reverse.
        def _sort_key(item: CandidateReadItem) -> tuple[int, str]:
            path = self.candidates_dir / item.candidate_id
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                mtime = 0
            return (mtime, item.candidate_id)

        results.sort(key=_sort_key, reverse=True)
        return results

    def review(
        self,
        *,
        candidate_id: str,
        decision: Literal["approve", "reject"],
        note: str,
        expected_manifest_digest: str,
        expected_status: Literal["pending"],
    ) -> ReviewRecord:
        # Validate all CAS inputs before any filesystem create/open of the root.
        candidate_id = _validate_candidate_id(candidate_id)
        digest = _validate_digest(expected_manifest_digest)
        note = _validate_note(note)
        if decision not in {"approve", "reject"}:
            raise CandidateIntegrityError("decision must be approve or reject")
        if expected_status != "pending":
            raise CandidateIntegrityError(
                "expected_status must be the literal 'pending'"
            )

        lock_name = _APPROVED_LOCK if decision == "approve" else _REJECTED_LOCK
        opposite = _REJECTED_LOCK if decision == "approve" else _APPROVED_LOCK

        if not self.candidates_dir.exists():
            raise CandidateIntegrityError(
                f"candidate {candidate_id!r} does not exist"
            )

        with locked_candidates_root(self.output_dir, create=False) as root:
            assert_entry_is_open_fd(root.parent_fd, root.name, root.fd)
            try:
                candidate_fd = open_directory_at(root.fd, candidate_id)
            except CandidateIntegrityError as exc:
                raise CandidateIntegrityError(
                    f"candidate {candidate_id!r} does not exist or is not a directory"
                ) from exc
            try:
                assert_entry_is_open_fd(root.fd, candidate_id, candidate_fd)
                st = os.fstat(candidate_fd)
                opened = OpenedDirectory(
                    fd=candidate_fd,
                    parent_fd=root.fd,
                    name=candidate_id,
                    st_dev=st.st_dev,
                    st_ino=st.st_ino,
                )
                snapshot = _verify_from_opened(
                    opened,
                    candidate_dir=self.candidates_dir / candidate_id,
                )

                if _any_decision_control(candidate_fd):
                    raise CandidateReviewStateStaleError(
                        f"candidate {candidate_id!r} already has a final decision"
                    )
                if snapshot.approval_binding != "pending":
                    raise CandidateReviewStateStaleError(
                        f"candidate {candidate_id!r} is not pending"
                    )
                if snapshot.manifest_digest != digest:
                    raise CandidateStaleError(
                        f"candidate {candidate_id!r} manifest digest mismatch"
                    )
                # expected_status is always pending (validated); current is pending.
                assert_entry_is_open_fd(root.fd, candidate_id, candidate_fd)
                assert_entry_is_open_fd(root.parent_fd, root.name, root.fd)

                if _control_present(candidate_fd, opposite):
                    raise CandidateReviewStateStaleError(
                        f"candidate {candidate_id!r} already has a final decision"
                    )

                created_at = utc_now_iso()
                record = ReviewRecord(
                    candidate_id=candidate_id,
                    decision=decision,
                    note=note,
                    manifest_digest=digest,
                    created_at=created_at,
                )
                lock_payload = canonical_json_bytes(
                    {
                        "schema_version": "1.0",
                        "candidate_id": candidate_id,
                        "decision": decision,
                        "manifest_digest": digest,
                        "note": note,
                        "reviewer": record.reviewer,
                        "created_at": created_at,
                    }
                )
                # Exclusive no-replace publication of the decision lock.
                atomic_write_noreplace_at(candidate_fd, lock_name, lock_payload)
                assert_entry_is_open_fd(root.fd, candidate_id, candidate_fd)
                assert_entry_is_open_fd(root.parent_fd, root.name, root.fd)
                # Confirm lock bytes are the ones we wrote and opposite absent.
                written = read_regular_bytes_at(candidate_fd, lock_name)
                if written != lock_payload:
                    raise CandidateIntegrityError("decision lock bytes changed")
                if _control_present(candidate_fd, opposite):
                    raise CandidateIntegrityError(
                        "opposite decision lock appeared during review"
                    )
                return record
            finally:
                os.close(candidate_fd)

    def _entry_is_dir(self, parent_fd: int, name: str) -> bool:
        try:
            st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CandidateIntegrityError(f"cannot stat {name!r}") from exc
        return stat_mod.S_ISDIR(st.st_mode) and not stat_mod.S_ISLNK(st.st_mode)

    def _verify_under_root(
        self, root: OpenedDirectory, candidate_id: str
    ) -> VerifiedCandidateSnapshot:
        candidate_fd = open_directory_at(root.fd, candidate_id)
        try:
            assert_entry_is_open_fd(root.fd, candidate_id, candidate_fd)
            st = os.fstat(candidate_fd)
            opened = OpenedDirectory(
                fd=candidate_fd,
                parent_fd=root.fd,
                name=candidate_id,
                st_dev=st.st_dev,
                st_ino=st.st_ino,
            )
            return _verify_from_opened(
                opened, candidate_dir=self.candidates_dir / candidate_id
            )
        finally:
            os.close(candidate_fd)

    def _read_item_at(self, root: OpenedDirectory, name: str) -> CandidateReadItem:
        try:
            candidate_id = _validate_candidate_id(name)
        except CandidateIntegrityError:
            return CandidateReadItem(
                candidate_id=name,
                integrity_state="corrupt",
                integrity_error_code="invalid_id",
                approval_enabled=False,
            )
        try:
            candidate_fd = open_directory_at(root.fd, candidate_id)
        except CandidateIntegrityError:
            return CandidateReadItem(
                candidate_id=candidate_id,
                integrity_state="corrupt",
                integrity_error_code="not_directory",
                approval_enabled=False,
            )
        try:
            assert_entry_is_open_fd(root.fd, candidate_id, candidate_fd)
            st = os.fstat(candidate_fd)
            opened = OpenedDirectory(
                fd=candidate_fd,
                parent_fd=root.fd,
                name=candidate_id,
                st_dev=st.st_dev,
                st_ino=st.st_ino,
            )
            try:
                snapshot = _verify_from_opened(
                    opened, candidate_dir=self.candidates_dir / candidate_id
                )
            except CandidateMigrationRequiredError:
                return self._migration_item(opened, candidate_id)
            except CandidateIntegrityError as exc:
                return CandidateReadItem(
                    candidate_id=candidate_id,
                    integrity_state="corrupt",
                    integrity_error_code=_integrity_error_code(exc),
                    approval_enabled=False,
                )
            status = _status_from_binding(snapshot.approval_binding)
            return CandidateReadItem(
                candidate_id=snapshot.candidate_id,
                artifact_type=snapshot.manifest.artifact_type,
                goal=snapshot.manifest.goal,
                universe=list(snapshot.manifest.universe),
                status=status,
                integrity_state="verified",
                manifest_digest=snapshot.manifest_digest,
                observed_manifest_digest=None,
                approval_binding=snapshot.approval_binding,
                approval_enabled=snapshot.approval_binding == "pending",
                integrity_error_code=None,
            )
        finally:
            os.close(candidate_fd)

    def _migration_item(
        self, opened: OpenedDirectory, candidate_id: str
    ) -> CandidateReadItem:
        try:
            manifest, digest, _artifact_bytes, metadata, _raw = (
                _build_manifest_from_opened(opened)
            )
        except CandidateIntegrityError as exc:
            return CandidateReadItem(
                candidate_id=candidate_id,
                integrity_state="corrupt",
                integrity_error_code=_integrity_error_code(exc),
                approval_enabled=False,
            )
        # Observed digest is non-authoritative evidence only.
        status: Literal["pending", "approved", "rejected"] | None = "pending"
        if _control_present(opened.fd, _APPROVED_LOCK) or _control_present(
            opened.fd, _LEGACY_APPROVED_LOCK
        ):
            status = "approved"
        elif _control_present(opened.fd, _REJECTED_LOCK) or _control_present(
            opened.fd, _LEGACY_REJECTED_LOCK
        ):
            status = "rejected"
        goal = metadata.get("goal") if isinstance(metadata.get("goal"), str) else manifest.goal
        artifact_type = (
            metadata.get("artifact_type")
            if isinstance(metadata.get("artifact_type"), str)
            else manifest.artifact_type
        )
        return CandidateReadItem(
            candidate_id=candidate_id,
            artifact_type=artifact_type,
            goal=goal,
            universe=list(manifest.universe),
            status=status,
            integrity_state="migration_required",
            manifest_digest=None,
            observed_manifest_digest=digest,
            approval_binding="legacy_unbound",
            approval_enabled=False,
            integrity_error_code=None,
        )
