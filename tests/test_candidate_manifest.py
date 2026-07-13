from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

from quant_system.agent.candidate_fs import (
    assert_entry_is_open_fd,
    open_absolute_directory,
    open_directory_at,
    read_regular_bytes_at,
)
from quant_system.agent.candidate_manifest import (
    CandidateIntegrityError,
    CandidateMigrationRequiredError,
    _validate_candidate_id,
    build_candidate_manifest,
    canonical_json_bytes,
    load_verified_candidate_snapshot,
    verify_candidate_directory,
)


def _candidate(root: Path) -> dict:
    root.mkdir()
    metadata = {
        "candidate_id": root.name,
        "artifact_type": "factor",
        "goal": "safe",
        "universe": ["SPY"],
        "files": ["z.py.candidate", "a.json"],
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2), encoding="utf-8"
    )
    (root / "z.py.candidate").write_bytes(b"Z\r\n")
    (root / "a.json").write_bytes(b'{"a":1}\n')
    return metadata


def _write_stored_manifest(candidate: Path) -> tuple[object, str]:
    manifest, digest, _artifact_bytes = build_candidate_manifest(candidate)
    (candidate / "manifest.v1.json").write_bytes(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    return manifest, digest


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        ".",
        "..",
        "../escape",
        "../../escape",
        "/tmp/escape",
        "nested/id",
        r"nested\id",
        " leading",
        "trailing ",
        "metadata.json",
        "manifest.v1.json",
        "UPPERCASE-ID",
        "approved.lock",
        "rejected.lock",
        "legacy-approved.lock",
        "legacy-rejected.lock",
        "reviews.jsonl",
        ".candidate-pool.lock",
    ],
)
def test_candidate_id_is_one_canonical_nonreserved_component(bad_id: str) -> None:
    with pytest.raises(CandidateIntegrityError):
        _validate_candidate_id(bad_id)


def test_manifest_binds_exact_bytes_and_sorts_posix_paths(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)

    manifest, digest, artifact_bytes = build_candidate_manifest(candidate)

    assert manifest.candidate_id == candidate.name
    assert [item.path for item in manifest.files] == ["a.json", "z.py.candidate"]
    assert manifest.files[1].size_bytes == 3
    assert artifact_bytes["z.py.candidate"] == b"Z\r\n"
    assert digest == hashlib.sha256(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    ).hexdigest()


def test_directory_metadata_and_stored_manifest_ids_must_match(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    metadata = _candidate(candidate)
    metadata["candidate_id"] = "factor-other-2"
    (candidate / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CandidateIntegrityError, match="candidate_id"):
        build_candidate_manifest(candidate)


@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape.py",
        "../../escape.py",
        "/tmp/escape.py",
        r"nested\id.py",
        "nested/id.py",
        ".",
        "..",
        "",
        "metadata.json",
        "manifest.v1.json",
        "approved.lock",
        "rejected.lock",
        "legacy-approved.lock",
        "legacy-rejected.lock",
        "reviews.jsonl",
        ".candidate-pool.lock",
        "Approved.lock",
        "Metadata.json",
        "MANIFEST.V1.JSON",
    ],
)
def test_metadata_file_paths_reject_unsafe_and_reserved(tmp_path: Path, bad_path: str) -> None:
    candidate = tmp_path / "factor-safe-1"
    metadata = _candidate(candidate)
    metadata["files"] = [bad_path]
    (candidate / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CandidateIntegrityError):
        build_candidate_manifest(candidate)


def test_duplicate_basenames_casefold_are_corrupt(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    metadata = _candidate(candidate)
    metadata["files"] = ["A.py", "a.py"]
    (candidate / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (candidate / "A.py").write_bytes(b"A")
    # On case-insensitive FS the second write hits the same entry; still corrupt by list.
    if not (candidate / "a.py").exists():
        (candidate / "a.py").write_bytes(b"a")

    with pytest.raises(CandidateIntegrityError):
        build_candidate_manifest(candidate)


def test_duplicate_exact_basenames_are_corrupt(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    metadata = _candidate(candidate)
    metadata["files"] = ["a.json", "a.json"]
    (candidate / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CandidateIntegrityError):
        build_candidate_manifest(candidate)


@pytest.mark.parametrize(
    "control_name",
    [
        "approved.lock",
        "rejected.lock",
        "legacy-approved.lock",
        "legacy-rejected.lock",
        "reviews.jsonl",
        ".candidate-pool.lock",
        "metadata.json",
        "manifest.v1.json",
    ],
)
def test_reserved_control_basenames_cannot_be_artifacts(
    tmp_path: Path, control_name: str
) -> None:
    candidate = tmp_path / "factor-safe-1"
    metadata = _candidate(candidate)
    metadata["files"] = [control_name]
    (candidate / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CandidateIntegrityError):
        build_candidate_manifest(candidate)


def test_stored_manifest_candidate_id_must_match_directory(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)
    manifest, _digest = _write_stored_manifest(candidate)
    payload = manifest.model_dump(mode="json")
    payload["candidate_id"] = "factor-other-2"
    (candidate / "manifest.v1.json").write_bytes(canonical_json_bytes(payload))

    with pytest.raises(CandidateIntegrityError, match="candidate_id"):
        verify_candidate_directory(candidate)


def test_missing_stored_manifest_is_migration_required(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)

    with pytest.raises(CandidateMigrationRequiredError):
        verify_candidate_directory(candidate)


def test_verify_accepts_matching_stored_manifest(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)
    _manifest, digest = _write_stored_manifest(candidate)

    snapshot = verify_candidate_directory(candidate)
    assert snapshot.candidate_id == "factor-safe-1"
    assert snapshot.manifest_digest == digest
    assert snapshot.artifact_bytes["z.py.candidate"] == b"Z\r\n"
    assert snapshot.approval_binding == "pending"


def test_symlinked_candidate_directory_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real-factor-safe-1"
    _candidate(real)
    link = tmp_path / "factor-safe-1"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(CandidateIntegrityError):
        build_candidate_manifest(link)


def test_symlinked_agent_output_root_rejected(tmp_path: Path) -> None:
    real_root = tmp_path / "real-agent-output"
    candidate = real_root / "agent" / "candidates" / "factor-safe-1"
    candidate.parent.mkdir(parents=True)
    _candidate(candidate)
    _write_stored_manifest(candidate)

    linked_root = tmp_path / "linked-agent-output"
    linked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(CandidateIntegrityError):
        load_verified_candidate_snapshot(
            agent_output_dir=linked_root, candidate_id="factor-safe-1"
        )


@pytest.mark.parametrize("component", ["agent", "candidates"])
def test_symlinked_agent_or_candidates_root_rejected(
    tmp_path: Path, component: str
) -> None:
    agent_output = tmp_path / "agent-output"
    if component == "agent":
        real = tmp_path / "real-agent"
        candidates = real / "candidates"
        candidates.mkdir(parents=True)
        (agent_output).mkdir()
        (agent_output / "agent").symlink_to(real, target_is_directory=True)
    else:
        agent_dir = agent_output / "agent"
        agent_dir.mkdir(parents=True)
        real = tmp_path / "real-candidates"
        real.mkdir()
        (agent_dir / "candidates").symlink_to(real, target_is_directory=True)
        candidates = real

    candidate = candidates / "factor-safe-1"
    _candidate(candidate)
    _write_stored_manifest(candidate)

    with pytest.raises(CandidateIntegrityError):
        load_verified_candidate_snapshot(
            agent_output_dir=agent_output, candidate_id="factor-safe-1"
        )


@pytest.mark.parametrize("name", ["metadata.json", "manifest.v1.json", "z.py.candidate"])
def test_symlinked_metadata_manifest_or_artifact_rejected(
    tmp_path: Path, name: str
) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)
    outside = tmp_path / "outside-bytes"
    outside.write_bytes(b"OUTSIDE-PAYLOAD")
    if name == "manifest.v1.json":
        _write_stored_manifest(candidate)
    target = candidate / name
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(outside)

    with pytest.raises(CandidateIntegrityError):
        if name == "manifest.v1.json":
            verify_candidate_directory(candidate)
        else:
            build_candidate_manifest(candidate)


def test_fifo_artifact_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    metadata = _candidate(candidate)
    (candidate / "a.json").unlink()
    os.mkfifo(candidate / "a.json")
    assert metadata["files"]

    with pytest.raises(CandidateIntegrityError):
        build_candidate_manifest(candidate)


def test_directory_artifact_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    metadata = _candidate(candidate)
    (candidate / "a.json").unlink()
    (candidate / "a.json").mkdir()
    assert metadata["files"]

    with pytest.raises(CandidateIntegrityError):
        build_candidate_manifest(candidate)


@pytest.mark.parametrize(
    "name",
    [
        "metadata.json",
        "manifest.v1.json",
        "z.py.candidate",
        "a.json",
        "approved.lock",
        "rejected.lock",
        "legacy-approved.lock",
        "legacy-rejected.lock",
    ],
)
def test_hardlink_to_outside_is_rejected(tmp_path: Path, name: str) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)
    controls = {
        "manifest.v1.json",
        "approved.lock",
        "rejected.lock",
        "legacy-approved.lock",
        "legacy-rejected.lock",
    }
    # Need a stored manifest so verify reaches control inspection.
    if name in controls and name != "manifest.v1.json":
        _write_stored_manifest(candidate)
    outside = tmp_path / f"outside-{name.replace('.', '_')}"
    outside.write_bytes(b"OUTSIDE-HARDLINK-BYTES")
    target = candidate / name
    if target.exists() or target.is_symlink():
        target.unlink()
    os.link(outside, target)

    with pytest.raises(CandidateIntegrityError):
        if name in controls:
            verify_candidate_directory(candidate)
        else:
            build_candidate_manifest(candidate)


def test_hardlinked_approval_control_never_authorizes(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)
    _write_stored_manifest(candidate)
    outside = tmp_path / "outside-approved"
    outside.write_bytes(b'{"schema_version":"1.0"}')
    os.link(outside, candidate / "approved.lock")

    with pytest.raises(CandidateIntegrityError):
        verify_candidate_directory(candidate)


def test_legacy_unbound_lock_is_readable_but_not_approved(tmp_path: Path) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)
    _write_stored_manifest(candidate)
    (candidate / "approved.lock").write_text("{}", encoding="utf-8")

    snapshot = verify_candidate_directory(candidate)
    assert snapshot.approval_binding == "legacy_unbound"


def test_approved_lock_requires_matching_id_and_digest(tmp_path: Path) -> None:
    """Structured locks with wrong ID or unbound digest must not authorize."""
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)
    _manifest, digest = _write_stored_manifest(candidate)

    # Wrong candidate_id + zero digest must not report approved.
    (candidate / "approved.lock").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "candidate_id": "factor-other-2",
                "manifest_digest": "0" * 64,
                "note": "unbound",
            }
        ),
        encoding="utf-8",
    )
    snapshot = verify_candidate_directory(candidate)
    assert snapshot.approval_binding == "legacy_unbound"
    assert snapshot.review_record is None
    assert snapshot.manifest_digest == digest

    # Correct ID but wrong digest still unbound.
    (candidate / "approved.lock").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "candidate_id": "factor-safe-1",
                "manifest_digest": "a" * 64,
                "note": "stale",
            }
        ),
        encoding="utf-8",
    )
    snapshot = verify_candidate_directory(candidate)
    assert snapshot.approval_binding == "legacy_unbound"

    # Non-hex / uppercase digest is not a bound lock.
    (candidate / "approved.lock").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "candidate_id": "factor-safe-1",
                "manifest_digest": "A" * 64,
                "note": "bad-hex",
            }
        ),
        encoding="utf-8",
    )
    snapshot = verify_candidate_directory(candidate)
    assert snapshot.approval_binding == "legacy_unbound"

    # Matching ID + exact current digest authorizes.
    (candidate / "approved.lock").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "candidate_id": "factor-safe-1",
                "manifest_digest": digest,
                "note": "ok",
            }
        ),
        encoding="utf-8",
    )
    snapshot = verify_candidate_directory(candidate)
    assert snapshot.approval_binding == "approved"
    assert snapshot.review_record is not None
    assert snapshot.review_record.candidate_id == "factor-safe-1"
    assert snapshot.review_record.decision == "approve"


def test_candidates_root_rename_after_open_never_reads_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_output = tmp_path / "agent-output"
    candidates = agent_output / "agent" / "candidates"
    candidates.mkdir(parents=True)
    original = candidates / "factor-safe-1"
    _candidate(original)
    _write_stored_manifest(original)

    replacement_root = tmp_path / "replacement-candidates"
    replacement_root.mkdir()
    evil = replacement_root / "factor-safe-1"
    _candidate(evil)
    (evil / "z.py.candidate").write_bytes(b"EVIL-ROOT")
    (evil / "a.json").write_bytes(b"EVIL-ROOT")
    # rebuild metadata to keep ids aligned so only bytes differ
    meta = json.loads((evil / "metadata.json").read_text(encoding="utf-8"))
    (evil / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _write_stored_manifest(evil)

    real_open_directory_at = open_directory_at
    swapped = {"done": False}

    def swap_candidates_root(parent_fd: int, name: str) -> int:
        fd = real_open_directory_at(parent_fd, name)
        if name == "candidates" and not swapped["done"]:
            swapped["done"] = True
            os.rename(candidates, tmp_path / "candidates-moved")
            os.rename(replacement_root, candidates)
        return fd

    monkeypatch.setattr(
        "quant_system.agent.candidate_manifest.open_directory_at",
        swap_candidates_root,
    )
    monkeypatch.setattr(
        "quant_system.agent.candidate_fs.open_directory_at",
        swap_candidates_root,
    )

    with pytest.raises(CandidateIntegrityError):
        load_verified_candidate_snapshot(
            agent_output_dir=agent_output, candidate_id="factor-safe-1"
        )

    # Replacement bytes must never be returned; original moved tree keeps payload.
    moved = tmp_path / "candidates-moved" / "factor-safe-1" / "z.py.candidate"
    assert moved.read_bytes() == b"Z\r\n"
    assert (candidates / "factor-safe-1" / "z.py.candidate").read_bytes() == b"EVIL-ROOT"


def test_candidate_directory_rename_after_open_never_reads_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)
    original_payload = (candidate / "z.py.candidate").read_bytes()

    replacement = tmp_path / "replacement-factor"
    _candidate(replacement)
    (replacement / "z.py.candidate").write_bytes(b"EVIL-CAND")
    (replacement / "a.json").write_bytes(b"EVIL-CAND")
    meta = json.loads((replacement / "metadata.json").read_text(encoding="utf-8"))
    meta["candidate_id"] = "factor-safe-1"
    (replacement / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    real_open_directory_at = open_directory_at
    swapped = {"done": False}

    def swap_candidate_dir(parent_fd: int, name: str) -> int:
        fd = real_open_directory_at(parent_fd, name)
        if name == "factor-safe-1" and not swapped["done"]:
            swapped["done"] = True
            os.rename(candidate, tmp_path / "factor-safe-1-moved")
            os.rename(replacement, candidate)
        return fd

    monkeypatch.setattr(
        "quant_system.agent.candidate_manifest.open_directory_at",
        swap_candidate_dir,
    )
    monkeypatch.setattr(
        "quant_system.agent.candidate_fs.open_directory_at",
        swap_candidate_dir,
    )

    with pytest.raises(CandidateIntegrityError):
        build_candidate_manifest(candidate)

    assert (tmp_path / "factor-safe-1-moved" / "z.py.candidate").read_bytes() == original_payload
    assert (candidate / "z.py.candidate").read_bytes() == b"EVIL-CAND"


def test_held_directory_identity_matches_parent_entry_before_return(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)

    with open_absolute_directory(candidate, create=False) as opened:
        assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
        st = os.fstat(opened.fd)
        assert (st.st_dev, st.st_ino) == (opened.st_dev, opened.st_ino)
        entry = os.stat(opened.name, dir_fd=opened.parent_fd, follow_symlinks=False)
        assert (entry.st_dev, entry.st_ino) == (opened.st_dev, opened.st_ino)
        # Read via held fd only
        payload = read_regular_bytes_at(opened.fd, "z.py.candidate")
        assert payload == b"Z\r\n"


def test_barrier_candidate_swap_never_returns_replacement_bytes(tmp_path: Path) -> None:
    """Barrier-synchronized rename after FDs are open must not leak replacement bytes."""
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)
    original = (candidate / "z.py.candidate").read_bytes()

    replacement = tmp_path / "replacement-factor"
    _candidate(replacement)
    (replacement / "z.py.candidate").write_bytes(b"EVIL-BARRIER")
    (replacement / "a.json").write_bytes(b"EVIL-BARRIER")
    meta = json.loads((replacement / "metadata.json").read_text(encoding="utf-8"))
    meta["candidate_id"] = "factor-safe-1"
    (replacement / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    barrier = threading.Barrier(2)
    result: dict[str, object] = {}
    error: dict[str, BaseException] = {}

    def reader() -> None:
        try:
            with open_absolute_directory(candidate, create=False) as opened:
                barrier.wait(timeout=5)
                barrier.wait(timeout=5)
                # After the swap the parent entry must not match the held inode.
                try:
                    assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
                except CandidateIntegrityError as exc:
                    error["identity"] = exc
                # Held fd must still yield original bytes — never replacement.
                result["bytes"] = read_regular_bytes_at(opened.fd, "z.py.candidate")
        except CandidateIntegrityError as exc:
            # Context exit re-checks identity and fails closed after the swap.
            error["exit_identity"] = exc
        except BaseException as exc:  # pragma: no cover - unexpected
            error["reader"] = exc

    def swapper() -> None:
        barrier.wait(timeout=5)
        os.rename(candidate, tmp_path / "factor-safe-1-moved")
        os.rename(replacement, candidate)
        barrier.wait(timeout=5)

    t1 = threading.Thread(target=reader)
    t2 = threading.Thread(target=swapper)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert "reader" not in error
    assert result.get("bytes") == original
    assert result.get("bytes") != b"EVIL-BARRIER"
    # After the swap the parent entry no longer matches the held original inode.
    assert "identity" in error or "exit_identity" in error


def test_barrier_candidates_root_swap_never_returns_replacement_bytes(
    tmp_path: Path,
) -> None:
    """Concurrent candidates-root rename must not leak replacement bytes via held FDs."""
    agent_output = tmp_path / "agent-output"
    candidates = agent_output / "agent" / "candidates"
    candidates.mkdir(parents=True)
    original_cand = candidates / "factor-safe-1"
    _candidate(original_cand)
    _write_stored_manifest(original_cand)
    original = (original_cand / "z.py.candidate").read_bytes()

    replacement_root = tmp_path / "replacement-candidates"
    replacement_root.mkdir()
    evil = replacement_root / "factor-safe-1"
    _candidate(evil)
    (evil / "z.py.candidate").write_bytes(b"EVIL-ROOT-BARRIER")
    (evil / "a.json").write_bytes(b"EVIL-ROOT-BARRIER")
    meta = json.loads((evil / "metadata.json").read_text(encoding="utf-8"))
    (evil / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _write_stored_manifest(evil)

    barrier = threading.Barrier(2)
    result: dict[str, object] = {}
    error: dict[str, BaseException] = {}

    def reader() -> None:
        try:
            with open_absolute_directory(agent_output, create=False) as agent_opened:
                agent_fd = open_directory_at(agent_opened.fd, "agent")
                try:
                    assert_entry_is_open_fd(agent_opened.fd, "agent", agent_fd)
                    candidates_fd = open_directory_at(agent_fd, "candidates")
                    try:
                        assert_entry_is_open_fd(agent_fd, "candidates", candidates_fd)
                        barrier.wait(timeout=5)
                        barrier.wait(timeout=5)
                        # After the swap agent/"candidates" must not match held inode.
                        try:
                            assert_entry_is_open_fd(
                                agent_fd, "candidates", candidates_fd
                            )
                        except CandidateIntegrityError as exc:
                            error["identity"] = exc
                        # Reads relative to the held candidates FD stay original.
                        candidate_fd = open_directory_at(
                            candidates_fd, "factor-safe-1"
                        )
                        try:
                            result["bytes"] = read_regular_bytes_at(
                                candidate_fd, "z.py.candidate"
                            )
                        finally:
                            os.close(candidate_fd)
                    finally:
                        os.close(candidates_fd)
                finally:
                    os.close(agent_fd)
        except CandidateIntegrityError as exc:
            error["exit_identity"] = exc
        except BaseException as exc:  # pragma: no cover - unexpected
            error["reader"] = exc

    def swapper() -> None:
        barrier.wait(timeout=5)
        os.rename(candidates, tmp_path / "candidates-moved")
        os.rename(replacement_root, candidates)
        barrier.wait(timeout=5)

    t1 = threading.Thread(target=reader)
    t2 = threading.Thread(target=swapper)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert "reader" not in error
    assert result.get("bytes") == original
    assert result.get("bytes") != b"EVIL-ROOT-BARRIER"
    assert "identity" in error or "exit_identity" in error
    # Path-visible replacement exists; held-FD path never returned its bytes.
    assert (candidates / "factor-safe-1" / "z.py.candidate").read_bytes() == (
        b"EVIL-ROOT-BARRIER"
    )


def test_valid_candidate_id_accepted() -> None:
    assert _validate_candidate_id("factor-safe-1") == "factor-safe-1"
    assert _validate_candidate_id("a") == "a"
    assert _validate_candidate_id("x_y-1") == "x_y-1"


def test_load_verified_snapshot_through_agent_output_dir(tmp_path: Path) -> None:
    agent_output = tmp_path / "agent-output"
    candidate = agent_output / "agent" / "candidates" / "factor-safe-1"
    candidate.parent.mkdir(parents=True)
    _candidate(candidate)
    _manifest, digest = _write_stored_manifest(candidate)

    snapshot = load_verified_candidate_snapshot(
        agent_output_dir=agent_output, candidate_id="factor-safe-1"
    )
    assert snapshot.manifest_digest == digest
    assert snapshot.candidate_dir == candidate
    assert snapshot.artifact_bytes["a.json"] == b'{"a":1}\n'
