"""Dry-run-first legacy root audit and conflict-safe candidate migration.

Audit is read-only (create=False, no locks/backups/manifests). Apply re-validates
root and candidate identities through held dirfds, backs up first, and publishes
only via Task-2/3 exclusive dirfd primitives. Legacy source trees are never mutated.
"""

from __future__ import annotations

import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from quant_system.agent.candidate_fs import (
    CandidateConflictError,
    CandidateIntegrityError,
    OpenedDirectory,
    assert_entry_is_open_fd,
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
    _build_manifest_from_opened,
    _validate_candidate_id,
    _verify_from_opened,
    canonical_json_bytes,
)
from quant_system.agent.paths import resolve_candidates_dir

__all__ = [
    "CandidateMigrationConflict",
    "CandidateMigrationItem",
    "CandidateMigrationReport",
    "apply_candidate_migration",
    "audit_candidate_roots",
]

_METADATA_NAME = "metadata.json"
_MANIFEST_NAME = "manifest.v1.json"
_APPROVED_LOCK = "approved.lock"
_REJECTED_LOCK = "rejected.lock"
_LEGACY_APPROVED_LOCK = "legacy-approved.lock"
_LEGACY_REJECTED_LOCK = "legacy-rejected.lock"
_SKIP_NAMES = frozenset({".", "..", ".candidate-pool.lock"})
_DECISION_LOCKS = frozenset(
    {
        _APPROVED_LOCK,
        _REJECTED_LOCK,
        _LEGACY_APPROVED_LOCK,
        _LEGACY_REJECTED_LOCK,
    }
)


class CandidateMigrationConflict(RuntimeError):
    """Migration would overwrite differing canonical bytes or roots overlap."""


class CandidateMigrationItem(BaseModel):
    candidate_id: str
    integrity_state: Literal["verified", "migration_required", "corrupt"]
    locations: list[Literal["legacy", "canonical"]] = Field(default_factory=list)
    source_manifest_digest: str | None = None
    canonical_manifest_digest: str | None = None
    legacy_st_dev: int | None = None
    legacy_st_ino: int | None = None
    canonical_st_dev: int | None = None
    canonical_st_ino: int | None = None
    integrity_error_code: str | None = None


class CandidateMigrationReport(BaseModel):
    legacy_dir: str
    agent_output_dir: str
    canonical_dir: str
    candidate_ids: list[str] = Field(default_factory=list)
    copyable: list[str] = Field(default_factory=list)
    identical: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    canonical_unversioned: list[str] = Field(default_factory=list)
    legacy_unbound: list[str] = Field(default_factory=list)
    items: list[CandidateMigrationItem] = Field(default_factory=list)
    applied: bool = False
    legacy_root_st_dev: int | None = None
    legacy_root_st_ino: int | None = None
    canonical_root_st_dev: int | None = None
    canonical_root_st_ino: int | None = None
    legacy_present: bool = False
    canonical_present: bool = False


def _abspath(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _paths_overlap(a: Path | str, b: Path | str) -> bool:
    a_parts = _abspath(a).parts
    b_parts = _abspath(b).parts
    if a_parts == b_parts:
        return True
    if len(a_parts) <= len(b_parts) and b_parts[: len(a_parts)] == a_parts:
        return True
    return bool(
        len(b_parts) <= len(a_parts) and a_parts[: len(b_parts)] == b_parts
    )


def _assert_planned_roots_distinct(
    legacy_dir: Path, canonical_dir: Path, backup_dir: Path | None = None
) -> None:
    pairs: list[tuple[Path, Path]] = [(legacy_dir, canonical_dir)]
    if backup_dir is not None:
        pairs.extend(
            [
                (legacy_dir, backup_dir),
                (canonical_dir, backup_dir),
            ]
        )
    for left, right in pairs:
        if _paths_overlap(left, right):
            raise CandidateMigrationConflict(
                f"migration roots overlap: {left} vs {right}"
            )


def _identity_tuple(opened: OpenedDirectory) -> tuple[int, int]:
    return (opened.st_dev, opened.st_ino)


def _path_is_dir_nofollow(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)


def _list_candidate_names(root_fd: int) -> list[str]:
    names: list[str] = []
    for name in sorted(os.listdir(root_fd)):
        if name in _SKIP_NAMES or name.startswith(".staging-") or name.startswith("."):
            continue
        names.append(name)
    return names


def _entry_is_dir(parent_fd: int, name: str) -> bool:
    try:
        st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot stat {name!r}") from exc
    return stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)


def _control_present(parent_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot stat {name!r}") from exc


def _observe_candidate(
    parent: OpenedDirectory,
    name: str,
    *,
    location: Literal["legacy", "canonical"],
) -> CandidateMigrationItem:
    try:
        candidate_id = _validate_candidate_id(name)
    except CandidateIntegrityError:
        return CandidateMigrationItem(
            candidate_id=name,
            integrity_state="corrupt",
            locations=[location],
            integrity_error_code="invalid_id",
        )

    if not _entry_is_dir(parent.fd, candidate_id):
        return CandidateMigrationItem(
            candidate_id=candidate_id,
            integrity_state="corrupt",
            locations=[location],
            integrity_error_code="not_directory",
        )

    try:
        cand_fd = open_directory_at(parent.fd, candidate_id)
    except CandidateIntegrityError:
        return CandidateMigrationItem(
            candidate_id=candidate_id,
            integrity_state="corrupt",
            locations=[location],
            integrity_error_code="open_failed",
        )

    try:
        assert_entry_is_open_fd(parent.fd, candidate_id, cand_fd)
        st = os.fstat(cand_fd)
        opened = OpenedDirectory(
            fd=cand_fd,
            parent_fd=parent.fd,
            name=candidate_id,
            st_dev=st.st_dev,
            st_ino=st.st_ino,
        )
        item = CandidateMigrationItem(
            candidate_id=candidate_id,
            integrity_state="migration_required",
            locations=[location],
        )
        if location == "legacy":
            item.legacy_st_dev = st.st_dev
            item.legacy_st_ino = st.st_ino
        else:
            item.canonical_st_dev = st.st_dev
            item.canonical_st_ino = st.st_ino

        try:
            snapshot = _verify_from_opened(
                opened, candidate_dir=Path("/__migration__") / candidate_id
            )
            item.integrity_state = "verified"
            digest = snapshot.manifest_digest
            if location == "legacy":
                item.source_manifest_digest = digest
            else:
                item.canonical_manifest_digest = digest
            if snapshot.approval_binding == "legacy_unbound":
                # Tracked at report aggregation time via lock presence too.
                pass
            return item
        except CandidateMigrationRequiredError:
            pass
        except CandidateIntegrityError:
            item.integrity_state = "corrupt"
            item.integrity_error_code = "corrupt"
            return item

        # Readable without stored manifest: migration_required if rebuild works.
        try:
            manifest, digest, _artifacts, _meta, _raw = _build_manifest_from_opened(
                opened
            )
            item.integrity_state = "migration_required"
            if location == "legacy":
                item.source_manifest_digest = digest
            else:
                item.canonical_manifest_digest = digest
            del manifest
            return item
        except CandidateIntegrityError:
            item.integrity_state = "corrupt"
            item.integrity_error_code = "corrupt"
            return item
    finally:
        os.close(cand_fd)


def _merge_items(
    left: CandidateMigrationItem | None, right: CandidateMigrationItem
) -> CandidateMigrationItem:
    if left is None:
        return right
    locations = list(dict.fromkeys([*left.locations, *right.locations]))
    # Prefer corrupt over others when either side is corrupt.
    if left.integrity_state == "corrupt" or right.integrity_state == "corrupt":
        state: Literal["verified", "migration_required", "corrupt"] = "corrupt"
        err = left.integrity_error_code or right.integrity_error_code
    elif (
        left.integrity_state == "migration_required"
        or right.integrity_state == "migration_required"
    ):
        # Both sides: if one verified and other migration_required, keep per-side digests.
        # Overall item state for dual-location is derived later for listing; store
        # migration_required only if both lack verified? Keep the "worse" of the two
        # for the combined row when locations differ — use migration_required if any
        # side needs migration and none is corrupt; verified only if both verified
        # with same digest handled at classification.
        if left.integrity_state == "verified" and right.integrity_state == "verified":
            state = "verified"
        else:
            state = "migration_required"
        err = None
    else:
        state = "verified"
        err = None

    return CandidateMigrationItem(
        candidate_id=left.candidate_id,
        integrity_state=state,
        locations=locations,  # type: ignore[arg-type]
        source_manifest_digest=left.source_manifest_digest
        or right.source_manifest_digest,
        canonical_manifest_digest=left.canonical_manifest_digest
        or right.canonical_manifest_digest,
        legacy_st_dev=left.legacy_st_dev
        if left.legacy_st_dev is not None
        else right.legacy_st_dev,
        legacy_st_ino=left.legacy_st_ino
        if left.legacy_st_ino is not None
        else right.legacy_st_ino,
        canonical_st_dev=left.canonical_st_dev
        if left.canonical_st_dev is not None
        else right.canonical_st_dev,
        canonical_st_ino=left.canonical_st_ino
        if left.canonical_st_ino is not None
        else right.canonical_st_ino,
        integrity_error_code=err,
    )


def _scan_root(
    root_path: Path, *, location: Literal["legacy", "canonical"]
) -> tuple[OpenedDirectory | None, dict[str, CandidateMigrationItem], tuple[int, int] | None]:
    try:
        root_stat = os.lstat(root_path)
    except FileNotFoundError:
        return None, {}, None
    except OSError as exc:
        raise CandidateIntegrityError(
            f"cannot inspect {location} candidate root"
        ) from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise CandidateIntegrityError(
            f"{location} candidate root is not a safe directory"
        )

    # open_absolute_directory is a context manager; for audit we need to scan
    # inside the with-block and return plain data only.
    items: dict[str, CandidateMigrationItem] = {}
    identity: tuple[int, int] | None = None
    with open_absolute_directory(root_path, create=False) as opened:
        assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
        identity = _identity_tuple(opened)
        for name in _list_candidate_names(opened.fd):
            observed = _observe_candidate(opened, name, location=location)
            items[observed.candidate_id] = observed
        assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
    return None, items, identity


def _current_root_identity(path: Path, *, label: str) -> tuple[int, int] | None:
    try:
        root_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot inspect {label} root") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise CandidateIntegrityError(f"{label} root is not a safe directory")
    with open_absolute_directory(path, create=False) as opened:
        assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
        return _identity_tuple(opened)


def _validate_reported_root_state(
    path: Path,
    *,
    label: str,
    expected_present: bool,
    expected_dev: int | None,
    expected_ino: int | None,
) -> None:
    if expected_present != (expected_dev is not None and expected_ino is not None):
        raise CandidateIntegrityError(f"invalid {label} root identity in report")
    current = _current_root_identity(path, label=label)
    if not expected_present:
        if current is not None:
            raise CandidateIntegrityError(f"{label} root appeared after audit")
        return
    if current != (expected_dev, expected_ino):
        raise CandidateIntegrityError(f"{label} root identity drift")


def audit_candidate_roots(
    *, legacy_dir: str | Path, agent_output_dir: str | Path
) -> CandidateMigrationReport:
    """Read-only audit of legacy vs canonical candidate roots."""
    legacy_path = _abspath(legacy_dir)
    agent_path = _abspath(agent_output_dir)
    canonical_path = resolve_candidates_dir(agent_path)

    # Planned path overlap between legacy and canonical must fail closed.
    if _paths_overlap(legacy_path, canonical_path):
        raise CandidateMigrationConflict(
            f"legacy and canonical roots overlap: {legacy_path} vs {canonical_path}"
        )

    _legacy_opened, legacy_items, legacy_ident = _scan_root(
        legacy_path, location="legacy"
    )
    _canon_opened, canonical_items, canon_ident = _scan_root(
        canonical_path, location="canonical"
    )
    del _legacy_opened, _canon_opened

    # Held-FD identity overlap if both present and same inode.
    if (
        legacy_ident is not None
        and canon_ident is not None
        and legacy_ident == canon_ident
    ):
        raise CandidateMigrationConflict(
            "legacy and canonical roots share the same directory identity"
        )

    merged: dict[str, CandidateMigrationItem] = {}
    for cid, item in legacy_items.items():
        merged[cid] = item
    for cid, item in canonical_items.items():
        merged[cid] = _merge_items(merged.get(cid), item)

    copyable: list[str] = []
    identical: list[str] = []
    conflicts: list[str] = []
    canonical_unversioned: list[str] = []
    legacy_unbound: list[str] = []

    for cid in sorted(merged):
        item = merged[cid]
        in_legacy = "legacy" in item.locations
        in_canonical = "canonical" in item.locations

        if item.integrity_state == "corrupt":
            if in_legacy and in_canonical:
                conflicts.append(cid)
            continue

        if in_legacy and not in_canonical:
            if (
                item.integrity_state in {"migration_required", "verified"}
                and item.source_manifest_digest is not None
            ):
                copyable.append(cid)
        elif in_canonical and not in_legacy:
            if item.integrity_state == "migration_required":
                canonical_unversioned.append(cid)
        elif in_legacy and in_canonical:
            src = item.source_manifest_digest
            dst = item.canonical_manifest_digest
            # Rebuild digest for unversioned canonical may live in canonical_manifest_digest
            # only when migration_required rebuild succeeded.
            if src is not None and dst is not None and src == dst:
                identical.append(cid)
            else:
                # Differing digests, missing digest on either side, or unreadable.
                conflicts.append(cid)

    # Detect legacy-format decision evidence on either side for reporting.
    # Re-open briefly only when roots exist to note unbound locks (read-only).
    if legacy_ident is not None:
        with open_absolute_directory(legacy_path, create=False) as opened:
            for cid in list(copyable) + list(identical) + list(conflicts):
                if cid not in legacy_items:
                    continue
                if legacy_items[cid].integrity_state == "corrupt":
                    continue
                try:
                    _validate_candidate_id(cid)
                except CandidateIntegrityError:
                    continue
                if not _entry_is_dir(opened.fd, cid):
                    continue
                fd = open_directory_at(opened.fd, cid)
                try:
                    has_decision = (
                        _control_present(fd, _APPROVED_LOCK)
                        or _control_present(fd, _REJECTED_LOCK)
                        or _control_present(fd, _LEGACY_APPROVED_LOCK)
                        or _control_present(fd, _LEGACY_REJECTED_LOCK)
                    )
                    if has_decision and cid not in legacy_unbound:
                        legacy_unbound.append(cid)
                finally:
                    os.close(fd)

    return CandidateMigrationReport(
        legacy_dir=str(legacy_path),
        agent_output_dir=str(agent_path),
        canonical_dir=str(canonical_path),
        candidate_ids=sorted(merged),
        copyable=sorted(copyable),
        identical=sorted(identical),
        conflicts=sorted(conflicts),
        canonical_unversioned=sorted(canonical_unversioned),
        legacy_unbound=sorted(legacy_unbound),
        items=[merged[cid] for cid in sorted(merged)],
        applied=False,
        legacy_root_st_dev=legacy_ident[0] if legacy_ident else None,
        legacy_root_st_ino=legacy_ident[1] if legacy_ident else None,
        canonical_root_st_dev=canon_ident[0] if canon_ident else None,
        canonical_root_st_ino=canon_ident[1] if canon_ident else None,
        legacy_present=legacy_ident is not None,
        canonical_present=canon_ident is not None,
    )


def _copy_regular_entries(
    source_fd: int,
    dest_fd: int,
    *,
    rename_decisions: bool,
) -> None:
    for name in sorted(os.listdir(source_fd)):
        if name in _SKIP_NAMES:
            continue
        try:
            st = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        except OSError as exc:
            raise CandidateIntegrityError(f"cannot stat source entry {name!r}") from exc
        if stat.S_ISLNK(st.st_mode):
            raise CandidateIntegrityError(f"source entry {name!r} is a symlink")
        if not stat.S_ISREG(st.st_mode):
            # Skip subdirectories; candidates are flat.
            continue
        dest_name = name
        if rename_decisions:
            if name == _APPROVED_LOCK:
                dest_name = _LEGACY_APPROVED_LOCK
            elif name == _REJECTED_LOCK:
                dest_name = _LEGACY_REJECTED_LOCK
        # Never copy a stored manifest from legacy into staging as authority;
        # apply rebuilds manifest after copy. If source has manifest, copy as
        # bytes only when not renaming for publish staging of unversioned? For
        # legacy→canonical publish we rebuild. For backup we want exact bytes.
        payload = read_regular_bytes_at(source_fd, name)
        write_regular_exclusive_at(dest_fd, dest_name, payload)


def _list_regular_payloads(source_fd: int) -> dict[str, bytes]:
    """Return name→bytes for every regular, non-symlink entry under source_fd."""
    payloads: dict[str, bytes] = {}
    for name in sorted(os.listdir(source_fd)):
        if name in _SKIP_NAMES:
            continue
        try:
            st = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        except OSError as exc:
            raise CandidateIntegrityError(f"cannot stat source entry {name!r}") from exc
        if stat.S_ISLNK(st.st_mode):
            raise CandidateIntegrityError(f"source entry {name!r} is a symlink")
        if not stat.S_ISREG(st.st_mode):
            continue
        payloads[name] = read_regular_bytes_at(source_fd, name)
    return payloads


def _backup_matches_source(
    backup_fd: int, source_payloads: dict[str, bytes]
) -> bool:
    """True only when backup has exactly the same regular-file set and bytes."""
    seen: set[str] = set()
    for name in os.listdir(backup_fd):
        if name in _SKIP_NAMES:
            continue
        try:
            st = os.stat(name, dir_fd=backup_fd, follow_symlinks=False)
        except OSError:
            return False
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            return False
        if name not in source_payloads:
            return False
        try:
            if read_regular_bytes_at(backup_fd, name) != source_payloads[name]:
                return False
        except CandidateIntegrityError:
            return False
        seen.add(name)
    return seen == set(source_payloads)


def _stage_verified_backup(
    bucket_fd: int,
    *,
    candidate_id: str,
    source_fd: int,
    source_payloads: dict[str, bytes],
) -> None:
    """Exclusive-stage a complete backup, verify bytes, then noreplace-publish."""
    staging_name = f".staging-backup-{secrets.token_hex(16)}"
    mkdir_exclusive_at(bucket_fd, staging_name)
    staging_fd: int | None = None
    published = False
    try:
        staging_fd = open_directory_at(bucket_fd, staging_name)
        assert_entry_is_open_fd(bucket_fd, staging_name, staging_fd)
        _copy_regular_entries(source_fd, staging_fd, rename_decisions=False)
        os.fsync(staging_fd)
        if not _backup_matches_source(staging_fd, source_payloads):
            raise CandidateIntegrityError(
                f"staged backup for {candidate_id!r} does not match source"
            )
        assert_entry_is_open_fd(bucket_fd, staging_name, staging_fd)
        rename_directory_noreplace_at(
            bucket_fd, staging_name, bucket_fd, candidate_id
        )
        os.fsync(bucket_fd)
        published = True
    except Exception:
        if not published:
            with suppress(Exception):
                remove_entry_tree_at(bucket_fd, staging_name)
        raise
    finally:
        if staging_fd is not None:
            with suppress(OSError):
                os.close(staging_fd)

    # Final held-fd verify of the published backup before callers may mutate source trees.
    final_fd = open_directory_at(bucket_fd, candidate_id)
    try:
        assert_entry_is_open_fd(bucket_fd, candidate_id, final_fd)
        if not _backup_matches_source(final_fd, source_payloads):
            raise CandidateIntegrityError(
                f"published backup for {candidate_id!r} incomplete or drifted"
            )
        os.fsync(final_fd)
    finally:
        os.close(final_fd)


def _backup_candidate_tree(
    backup_root: OpenedDirectory,
    *,
    bucket: str,
    candidate_id: str,
    source_fd: int,
) -> None:
    """Copy all regular files from source into backup/bucket/id after verify.

    Never trusts a pre-existing backup directory by name alone. A complete,
    byte-matching tree is an idempotent no-op; an incomplete/mismatched tree is
    removed and replaced via exclusive staging + noreplace rename only after
    the staged copy verifies against the held source FD.
    """
    _validate_candidate_id(candidate_id)
    source_payloads = _list_regular_payloads(source_fd)

    if not _entry_is_dir(backup_root.fd, bucket):
        with suppress(CandidateConflictError):
            mkdir_exclusive_at(backup_root.fd, bucket)
    bucket_fd = open_directory_at(backup_root.fd, bucket)
    try:
        assert_entry_is_open_fd(backup_root.fd, bucket, bucket_fd)
        if _entry_is_dir(bucket_fd, candidate_id):
            existing_fd = open_directory_at(bucket_fd, candidate_id)
            try:
                assert_entry_is_open_fd(bucket_fd, candidate_id, existing_fd)
                if _backup_matches_source(existing_fd, source_payloads):
                    # Complete, fsynced-matching backup: idempotent no-op.
                    return
            finally:
                os.close(existing_fd)
            # Incomplete or drifted backup must not authorize publish; restage.
            remove_entry_tree_at(bucket_fd, candidate_id)

        _stage_verified_backup(
            bucket_fd,
            candidate_id=candidate_id,
            source_fd=source_fd,
            source_payloads=source_payloads,
        )
        os.fsync(bucket_fd)
    finally:
        os.close(bucket_fd)
    os.fsync(backup_root.fd)


def _reobserve(
    parent: OpenedDirectory, candidate_id: str, *, location: Literal["legacy", "canonical"]
) -> CandidateMigrationItem:
    return _observe_candidate(parent, candidate_id, location=location)


def _publish_from_legacy(
    *,
    legacy_root: OpenedDirectory,
    canonical_root: OpenedDirectory,
    backup_root: OpenedDirectory,
    candidate_id: str,
    expected_digest: str,
    expected_dev: int,
    expected_ino: int,
    candidates_dir: Path,
) -> None:
    candidate_id = _validate_candidate_id(candidate_id)
    if not _entry_is_dir(legacy_root.fd, candidate_id):
        raise CandidateIntegrityError(f"legacy candidate {candidate_id!r} missing")

    src_fd = open_directory_at(legacy_root.fd, candidate_id)
    try:
        assert_entry_is_open_fd(legacy_root.fd, candidate_id, src_fd)
        st = os.fstat(src_fd)
        if (st.st_dev, st.st_ino) != (expected_dev, expected_ino):
            raise CandidateIntegrityError(
                f"legacy candidate {candidate_id!r} identity drift"
            )
        opened = OpenedDirectory(
            fd=src_fd,
            parent_fd=legacy_root.fd,
            name=candidate_id,
            st_dev=st.st_dev,
            st_ino=st.st_ino,
        )
        try:
            _manifest, digest, _a, _m, _r = _build_manifest_from_opened(opened)
        except CandidateIntegrityError:
            # verified legacy with stored manifest still ok
            snap = _verify_from_opened(
                opened, candidate_dir=candidates_dir / candidate_id
            )
            digest = snap.manifest_digest
        if digest != expected_digest:
            raise CandidateIntegrityError(
                f"legacy candidate {candidate_id!r} digest drift"
            )

        # Destination exists?
        if _entry_is_dir(canonical_root.fd, candidate_id):
            existing = _reobserve(
                canonical_root, candidate_id, location="canonical"
            )
            if (
                existing.integrity_state != "corrupt"
                and existing.canonical_manifest_digest == expected_digest
            ):
                return  # identical no-op
            raise CandidateMigrationConflict(
                f"canonical candidate {candidate_id!r} already exists with different bytes"
            )

        _backup_candidate_tree(
            backup_root,
            bucket="legacy",
            candidate_id=candidate_id,
            source_fd=src_fd,
        )

        staging_name = f".staging-{secrets.token_hex(16)}"
        published = False
        mkdir_exclusive_at(canonical_root.fd, staging_name)
        staging_fd: int | None = None
        try:
            staging_fd = open_directory_at(canonical_root.fd, staging_name)
            assert_entry_is_open_fd(canonical_root.fd, staging_name, staging_fd)
            mkdir_exclusive_at(staging_fd, candidate_id)
            cand_fd = open_directory_at(staging_fd, candidate_id)
            try:
                assert_entry_is_open_fd(staging_fd, candidate_id, cand_fd)
                # Re-check source identity immediately before copy.
                assert_entry_is_open_fd(legacy_root.fd, candidate_id, src_fd)
                st_now = os.fstat(src_fd)
                if (st_now.st_dev, st_now.st_ino) != (expected_dev, expected_ino):
                    raise CandidateIntegrityError(
                        f"legacy candidate {candidate_id!r} identity drift before copy"
                    )
                _copy_regular_entries(src_fd, cand_fd, rename_decisions=True)
                # Drop any copied manifest; rebuild authoritative v1.
                if _control_present(cand_fd, _MANIFEST_NAME):
                    os.unlink(_MANIFEST_NAME, dir_fd=cand_fd)

                st_c = os.fstat(cand_fd)
                staged = OpenedDirectory(
                    fd=cand_fd,
                    parent_fd=staging_fd,
                    name=candidate_id,
                    st_dev=st_c.st_dev,
                    st_ino=st_c.st_ino,
                )
                manifest, new_digest, _ab, _meta, _raw = _build_manifest_from_opened(
                    staged
                )
                if new_digest != expected_digest:
                    raise CandidateIntegrityError(
                        f"staged digest mismatch for {candidate_id!r}"
                    )
                manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
                write_regular_exclusive_at(cand_fd, _MANIFEST_NAME, manifest_bytes)
                verified = _verify_from_opened(
                    staged, candidate_dir=candidates_dir / candidate_id
                )
                if verified.manifest_digest != expected_digest:
                    raise CandidateIntegrityError("published digest mismatch")
                assert_entry_is_open_fd(staging_fd, candidate_id, cand_fd)
                assert_entry_is_open_fd(canonical_root.fd, staging_name, staging_fd)
                assert_entry_is_open_fd(
                    canonical_root.parent_fd, canonical_root.name, canonical_root.fd
                )
                # Final source identity check before publish.
                assert_entry_is_open_fd(legacy_root.fd, candidate_id, src_fd)
                rename_directory_noreplace_at(
                    staging_fd, candidate_id, canonical_root.fd, candidate_id
                )
                os.fsync(canonical_root.fd)
                published = True
            finally:
                os.close(cand_fd)
        except Exception:
            if not published:
                with suppress(Exception):
                    remove_entry_tree_at(canonical_root.fd, staging_name)
            raise
        else:
            with suppress(Exception):
                remove_entry_tree_at(canonical_root.fd, staging_name)
        finally:
            if staging_fd is not None:
                with suppress(OSError):
                    os.close(staging_fd)
    finally:
        os.close(src_fd)


def _version_canonical_unversioned(
    *,
    canonical_root: OpenedDirectory,
    backup_root: OpenedDirectory,
    candidate_id: str,
    expected_digest: str,
    expected_dev: int,
    expected_ino: int,
    candidates_dir: Path,
) -> None:
    candidate_id = _validate_candidate_id(candidate_id)
    if not _entry_is_dir(canonical_root.fd, candidate_id):
        raise CandidateIntegrityError(f"canonical candidate {candidate_id!r} missing")

    cand_fd = open_directory_at(canonical_root.fd, candidate_id)
    try:
        assert_entry_is_open_fd(canonical_root.fd, candidate_id, cand_fd)
        st = os.fstat(cand_fd)
        if (st.st_dev, st.st_ino) != (expected_dev, expected_ino):
            raise CandidateIntegrityError(
                f"canonical candidate {candidate_id!r} identity drift"
            )
        opened = OpenedDirectory(
            fd=cand_fd,
            parent_fd=canonical_root.fd,
            name=candidate_id,
            st_dev=st.st_dev,
            st_ino=st.st_ino,
        )

        # Already versioned?
        if _control_present(cand_fd, _MANIFEST_NAME):
            snap = _verify_from_opened(
                opened, candidate_dir=candidates_dir / candidate_id
            )
            if snap.manifest_digest == expected_digest:
                return
            raise CandidateMigrationConflict(
                f"canonical candidate {candidate_id!r} has unexpected manifest"
            )

        manifest, digest, _a, _m, _r = _build_manifest_from_opened(opened)
        if digest != expected_digest:
            raise CandidateIntegrityError(
                f"canonical candidate {candidate_id!r} digest drift"
            )

        _backup_candidate_tree(
            backup_root,
            bucket="canonical",
            candidate_id=candidate_id,
            source_fd=cand_fd,
        )

        # Re-verify identity and bytes under lock after backup.
        assert_entry_is_open_fd(canonical_root.fd, candidate_id, cand_fd)
        st2 = os.fstat(cand_fd)
        if (st2.st_dev, st2.st_ino) != (expected_dev, expected_ino):
            raise CandidateIntegrityError(
                f"canonical candidate {candidate_id!r} identity drift after backup"
            )
        manifest2, digest2, _a2, _m2, _r2 = _build_manifest_from_opened(opened)
        if digest2 != expected_digest:
            raise CandidateIntegrityError(
                f"canonical candidate {candidate_id!r} digest drift after backup"
            )
        del manifest2

        # Move legacy-format decisions to unbound evidence (same-dirfd no-replace).
        for src_name, dst_name in (
            (_APPROVED_LOCK, _LEGACY_APPROVED_LOCK),
            (_REJECTED_LOCK, _LEGACY_REJECTED_LOCK),
        ):
            if _control_present(cand_fd, src_name) and not _control_present(
                cand_fd, dst_name
            ):
                payload = read_regular_bytes_at(cand_fd, src_name)
                write_regular_exclusive_at(cand_fd, dst_name, payload)
                os.unlink(src_name, dir_fd=cand_fd)
                os.fsync(cand_fd)

        manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
        try:
            write_regular_exclusive_at(cand_fd, _MANIFEST_NAME, manifest_bytes)
        except CandidateConflictError:
            existing = read_regular_bytes_at(cand_fd, _MANIFEST_NAME)
            if existing != manifest_bytes:
                raise CandidateMigrationConflict(
                    f"manifest race on {candidate_id!r}"
                ) from None
        assert_entry_is_open_fd(canonical_root.fd, candidate_id, cand_fd)
        verified = _verify_from_opened(
            opened, candidate_dir=candidates_dir / candidate_id
        )
        if verified.manifest_digest != expected_digest:
            raise CandidateIntegrityError("post-version digest mismatch")
    finally:
        os.close(cand_fd)


def apply_candidate_migration(
    report: CandidateMigrationReport, backup_dir: str | Path
) -> CandidateMigrationReport:
    """Apply a previously audited migration; refuse on drift or conflicts."""
    legacy_path = _abspath(report.legacy_dir)
    agent_path = _abspath(report.agent_output_dir)
    canonical_path = _abspath(report.canonical_dir)
    backup_path = _abspath(backup_dir)

    if resolve_candidates_dir(agent_path) != canonical_path:
        raise CandidateIntegrityError(
            "report canonical_dir does not match agent_output_dir"
        )

    _assert_planned_roots_distinct(legacy_path, canonical_path, backup_path)

    # Validate even a no-op report. Otherwise an empty audit can be replayed
    # after a root appears (or becomes a symlink) and falsely return applied.
    _validate_reported_root_state(
        legacy_path,
        label="legacy",
        expected_present=report.legacy_present,
        expected_dev=report.legacy_root_st_dev,
        expected_ino=report.legacy_root_st_ino,
    )
    _validate_reported_root_state(
        canonical_path,
        label="canonical",
        expected_present=report.canonical_present,
        expected_dev=report.canonical_root_st_dev,
        expected_ino=report.canonical_root_st_ino,
    )

    intrinsic_conflicts = sorted(
        item.candidate_id
        for item in report.items
        if {"legacy", "canonical"}.issubset(item.locations)
        and (
            item.integrity_state == "corrupt"
            or item.source_manifest_digest is None
            or item.canonical_manifest_digest is None
            or item.source_manifest_digest != item.canonical_manifest_digest
        )
    )
    conflicts = sorted(set(report.conflicts) | set(intrinsic_conflicts))
    if conflicts:
        raise CandidateMigrationConflict(
            f"refusing apply with conflicts: {conflicts}"
        )

    # Nothing to write: pure no-op without creating backup/canonical roots.
    if not report.copyable and not report.canonical_unversioned:
        return report.model_copy(update={"applied": True})

    expected_legacy = (
        (report.legacy_root_st_dev, report.legacy_root_st_ino)
        if report.legacy_present
        and report.legacy_root_st_dev is not None
        and report.legacy_root_st_ino is not None
        else None
    )
    expected_canonical = (
        (report.canonical_root_st_dev, report.canonical_root_st_ino)
        if report.canonical_present
        and report.canonical_root_st_dev is not None
        and report.canonical_root_st_ino is not None
        else None
    )

    items_by_id = {item.candidate_id: item for item in report.items}

    # Open/create backup only after planned-path validation.
    # Re-check overlap with safely opened FDs when roots exist.
    with open_absolute_directory(backup_path, create=True) as backup_root:
        assert_entry_is_open_fd(
            backup_root.parent_fd, backup_root.name, backup_root.fd
        )
        backup_ident = _identity_tuple(backup_root)

        # Reopen legacy if needed.
        legacy_cm = None
        legacy_root: OpenedDirectory | None = None
        if report.copyable or report.identical:
            if not report.legacy_present or expected_legacy is None:
                if report.copyable:
                    raise CandidateIntegrityError(
                        "legacy root missing but copyable entries present"
                    )
            else:
                legacy_cm = open_absolute_directory(legacy_path, create=False)
                legacy_root = legacy_cm.__enter__()
                try:
                    assert_entry_is_open_fd(
                        legacy_root.parent_fd, legacy_root.name, legacy_root.fd
                    )
                    if _identity_tuple(legacy_root) != expected_legacy:
                        raise CandidateIntegrityError("legacy root identity drift")
                    if _identity_tuple(legacy_root) == backup_ident:
                        raise CandidateMigrationConflict(
                            "backup root identity collides with legacy"
                        )
                except Exception:
                    legacy_cm.__exit__(None, None, None)
                    raise

        try:
            # Probe canonical root identity *before* pool-lock acquisition so a
            # replaced root fails closed without creating .candidate-pool.lock.
            create_canonical = expected_canonical is None
            if expected_canonical is not None:
                if not _path_is_dir_nofollow(canonical_path):
                    raise CandidateIntegrityError(
                        "canonical root missing after audit observed it"
                    )
                with open_absolute_directory(canonical_path, create=False) as probe:
                    assert_entry_is_open_fd(
                        probe.parent_fd, probe.name, probe.fd
                    )
                    if _identity_tuple(probe) != expected_canonical:
                        raise CandidateIntegrityError(
                            "canonical root identity drift"
                        )
                    if _identity_tuple(probe) == backup_ident:
                        raise CandidateMigrationConflict(
                            "backup root identity collides with canonical"
                        )
                    if legacy_root is not None and _identity_tuple(probe) == (
                        _identity_tuple(legacy_root)
                    ):
                        raise CandidateMigrationConflict(
                            "canonical root identity collides with legacy"
                        )

            # Canonical under pool lock; create only when audit saw it absent.
            with locked_candidates_root(
                agent_path, create=create_canonical
            ) as canonical_root:
                assert_entry_is_open_fd(
                    canonical_root.parent_fd, canonical_root.name, canonical_root.fd
                )
                canon_ident = _identity_tuple(canonical_root)
                if expected_canonical is not None and canon_ident != expected_canonical:
                    # Allow create path when audit saw absent canonical (None expected).
                    raise CandidateIntegrityError("canonical root identity drift")
                if canon_ident == backup_ident:
                    raise CandidateMigrationConflict(
                        "backup root identity collides with canonical"
                    )
                if legacy_root is not None and canon_ident == _identity_tuple(
                    legacy_root
                ):
                    raise CandidateMigrationConflict(
                        "canonical root identity collides with legacy"
                    )

                # Re-validate planned absolute paths still non-overlapping via real
                # lexical abspath (backup now exists).
                _assert_planned_roots_distinct(
                    legacy_path, canonical_path, backup_path
                )

                for cid in report.copyable:
                    item = items_by_id[cid]
                    if item.source_manifest_digest is None:
                        raise CandidateIntegrityError(
                            f"copyable {cid!r} missing source digest"
                        )
                    if item.legacy_st_dev is None or item.legacy_st_ino is None:
                        raise CandidateIntegrityError(
                            f"copyable {cid!r} missing legacy identity"
                        )
                    if legacy_root is None:
                        raise CandidateIntegrityError("legacy root not open")
                    _publish_from_legacy(
                        legacy_root=legacy_root,
                        canonical_root=canonical_root,
                        backup_root=backup_root,
                        candidate_id=cid,
                        expected_digest=item.source_manifest_digest,
                        expected_dev=item.legacy_st_dev,
                        expected_ino=item.legacy_st_ino,
                        candidates_dir=canonical_path,
                    )

                for cid in report.canonical_unversioned:
                    item = items_by_id[cid]
                    digest = item.canonical_manifest_digest
                    if digest is None:
                        raise CandidateIntegrityError(
                            f"unversioned {cid!r} missing digest"
                        )
                    if item.canonical_st_dev is None or item.canonical_st_ino is None:
                        raise CandidateIntegrityError(
                            f"unversioned {cid!r} missing identity"
                        )
                    _version_canonical_unversioned(
                        canonical_root=canonical_root,
                        backup_root=backup_root,
                        candidate_id=cid,
                        expected_digest=digest,
                        expected_dev=item.canonical_st_dev,
                        expected_ino=item.canonical_st_ino,
                        candidates_dir=canonical_path,
                    )

                assert_entry_is_open_fd(
                    canonical_root.parent_fd, canonical_root.name, canonical_root.fd
                )
        finally:
            if legacy_cm is not None:
                legacy_cm.__exit__(None, None, None)

        assert_entry_is_open_fd(
            backup_root.parent_fd, backup_root.name, backup_root.fd
        )

    # Return a fresh audit reflecting post-apply state.
    refreshed = audit_candidate_roots(
        legacy_dir=legacy_path, agent_output_dir=agent_path
    )
    return refreshed.model_copy(update={"applied": True})
