"""Dry-run-first candidate root audit and conflict-safe migration tests."""

from __future__ import annotations

import ast
import json
import shutil
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_system.agent.candidate_migration import (
    CandidateMigrationConflict,
    apply_candidate_migration,
    audit_candidate_roots,
)
from quant_system.agent.candidate_pool import CandidateIntegrityError, CandidatePool
from quant_system.agent.paths import resolve_agent_output_dir, resolve_candidates_dir
from quant_system.cli import app

runner = CliRunner()


def _tree_fingerprint(root: Path) -> list[tuple[str, int, int, int, bytes | None]]:
    """Inode/type/path/byte fingerprint (no-follow)."""
    if not root.exists():
        return []
    rows: list[tuple[str, int, int, int, bytes | None]] = []
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        st = path.lstat()
        payload = None
        if stat.S_ISREG(st.st_mode) and not path.is_symlink():
            payload = path.read_bytes()
        rows.append((rel, st.st_mode, st.st_dev, st.st_ino, payload))
    return rows


def _write_legacy_candidate(
    root: Path,
    candidate_id: str,
    content: bytes,
    *,
    approved: bool = False,
    rejected: bool = False,
) -> Path:
    cdir = root / candidate_id
    cdir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "candidate_id": candidate_id,
        "task_id": "legacy-task",
        "artifact_type": "factor",
        "goal": "legacy goal",
        "universe": ["SPY"],
        "status": "approved" if approved else ("rejected" if rejected else "pending"),
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "files": ["factor.py.candidate"],
        "safety": {
            "auto_promotion": False,
            "requires_human_review": True,
            "review_status": "approved" if approved else "pending",
        },
    }
    (cdir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )
    (cdir / "factor.py.candidate").write_bytes(content)
    if approved:
        (cdir / "approved.lock").write_text("{}", encoding="utf-8")
    if rejected:
        (cdir / "rejected.lock").write_text("{}", encoding="utf-8")
    return cdir


def test_migration_never_overwrites_conflicting_canonical_candidate(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(legacy, "candidate-1", b"legacy\n", approved=True)
    _write_legacy_candidate(canonical, "candidate-1", b"canonical\n", approved=False)

    report = audit_candidate_roots(
        legacy_dir=legacy,
        agent_output_dir=agent_output,
    )

    assert report.conflicts == ["candidate-1"]
    assert report.copyable == []
    before = (canonical / "candidate-1" / "factor.py.candidate").read_bytes()
    with pytest.raises(CandidateMigrationConflict):
        apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    assert (canonical / "candidate-1" / "factor.py.candidate").read_bytes() == before


def test_migration_never_mutates_legacy_source_tree(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    _write_legacy_candidate(legacy, "candidate-1", b"legacy\n", approved=True)
    before = _tree_fingerprint(legacy)

    report = audit_candidate_roots(
        legacy_dir=legacy,
        agent_output_dir=agent_output,
    )
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")

    assert _tree_fingerprint(legacy) == before


def test_legacy_approval_is_preserved_as_evidence_but_not_authority(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(legacy, "candidate-1", b"same\n", approved=True)
    report = audit_candidate_roots(
        legacy_dir=legacy,
        agent_output_dir=agent_output,
    )
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    snapshot = CandidatePool(agent_output).get("candidate-1")
    assert snapshot.approval_binding == "legacy_unbound"
    assert (snapshot.candidate_dir / "legacy-approved.lock").exists()
    assert not (canonical / "candidate-1" / "approved.lock").exists()


def test_existing_canonical_candidate_gets_manifest_without_byte_or_authority_change(
    tmp_path,
) -> None:
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(canonical, "candidate-1", b"pending\n", approved=False)
    source = canonical / "candidate-1" / "factor.py.candidate"
    metadata = canonical / "candidate-1" / "metadata.json"
    before = (source.read_bytes(), metadata.read_bytes())

    report = audit_candidate_roots(
        legacy_dir=tmp_path / "missing-legacy",
        agent_output_dir=agent_output,
    )

    assert report.canonical_unversioned == ["candidate-1"]
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    assert (source.read_bytes(), metadata.read_bytes()) == before
    assert (canonical / "candidate-1" / "manifest.v1.json").is_file()
    assert CandidatePool(agent_output).get(
        "candidate-1"
    ).approval_binding == "pending"


def test_dry_run_against_absent_roots_leaves_tmp_empty(tmp_path) -> None:
    before = _tree_fingerprint(tmp_path)
    report = audit_candidate_roots(
        legacy_dir=tmp_path / "missing-legacy",
        agent_output_dir=tmp_path / "missing-agent",
    )
    assert report.copyable == []
    assert report.conflicts == []
    assert report.canonical_unversioned == []
    assert report.identical == []
    assert _tree_fingerprint(tmp_path) == before
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../outside",
        "/tmp/absolute",
        "a/b",
        r"a\b",
        ".",
        "..",
        "approved.lock",
        "manifest.v1.json",
        "metadata.json",
    ],
)
def test_invalid_candidate_directory_names_rejected_without_writes(
    tmp_path, bad_id: str
) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    backup = tmp_path / "backup"
    # Plant an invalid entry name under legacy when the name is a single path component.
    legacy.mkdir()
    if "/" not in bad_id and "\\" not in bad_id and not bad_id.startswith("/"):
        target = legacy / bad_id
        try:
            target.mkdir(parents=True)
            (target / "metadata.json").write_text("{}", encoding="utf-8")
        except OSError:
            # Absolute or multi-component names are not plantable as single entries.
            pass
    else:
        # Create a decoy so the root exists; invalid names come from listing only.
        _write_legacy_candidate(legacy, "valid-id", b"x\n")

    before_legacy = _tree_fingerprint(legacy)

    report = audit_candidate_roots(legacy_dir=legacy, agent_output_dir=agent_output)
    # Invalid IDs must never be copyable.
    assert bad_id not in report.copyable
    assert all("/" not in cid and "\\" not in cid for cid in report.copyable)

    if report.copyable:
        apply_candidate_migration(report, backup_dir=backup)
    elif report.conflicts or report.canonical_unversioned:
        pass
    else:
        # Nothing to apply; ensure apply with empty actions is fine when no conflicts
        if not report.conflicts:
            apply_candidate_migration(report, backup_dir=backup)

    assert _tree_fingerprint(legacy) == before_legacy
    # Invalid-only trees must not create canonical candidates or backup entries.
    if not report.copyable and not report.canonical_unversioned:
        assert not (agent_output / "agent" / "candidates").exists()
        assert not backup.exists()


def test_integrity_states_are_mutually_exclusive(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"

    _write_legacy_candidate(legacy, "legacy-only", b"leg\n")
    _write_legacy_candidate(canonical, "needs-manifest", b"pending\n")
    corrupt = canonical / "corrupt-id"
    corrupt.mkdir(parents=True)
    (corrupt / "metadata.json").write_text("{not-json", encoding="utf-8")

    # Verified candidate via pool write
    pool = CandidatePool(agent_output)
    artifact = pool.write_candidate(
        task_id="ok-task",
        goal="ok goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# ok\n",
    )

    report = audit_candidate_roots(legacy_dir=legacy, agent_output_dir=agent_output)
    by_id = {item.candidate_id: item for item in report.items}
    for item in report.items:
        states = {
            s
            for s in ("verified", "migration_required", "corrupt")
            if s == item.integrity_state
        }
        assert len(states) == 1

    assert by_id["legacy-only"].integrity_state == "migration_required"
    assert by_id["needs-manifest"].integrity_state == "migration_required"
    assert by_id["corrupt-id"].integrity_state == "corrupt"
    assert by_id[artifact.candidate_id].integrity_state == "verified"
    assert "legacy-only" in report.copyable
    assert "needs-manifest" in report.canonical_unversioned


@pytest.mark.parametrize(
    "layout",
    [
        "legacy_eq_canonical",
        "backup_eq_legacy",
        "backup_inside_legacy",
        "legacy_inside_backup",
        "canonical_inside_legacy",
        "legacy_inside_canonical",
        "backup_inside_canonical",
        "canonical_inside_backup",
    ],
)
def test_root_overlap_fails_before_any_creation(tmp_path, layout: str) -> None:
    base = tmp_path / "base"
    base.mkdir()
    legacy = base / "legacy"
    agent_output = base / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    backup = base / "backup"

    _write_legacy_candidate(legacy, "candidate-1", b"data\n")
    # Ensure agent-output tree exists separately unless layout forces overlap.
    if layout not in {
        "legacy_eq_canonical",
        "canonical_inside_legacy",
        "legacy_inside_canonical",
    }:
        _write_legacy_candidate(canonical, "other-1", b"other\n")

    if layout == "legacy_eq_canonical":
        # Point agent_output such that canonical == legacy
        # resolve_candidates_dir(agent) = agent/agent/candidates — craft equality:
        # Use legacy as the candidates dir by setting agent_output so
        # agent_output/agent/candidates == legacy.
        agent_output = legacy.parent  # .../legacy's parent
        # Wait: resolve_candidates_dir = agent_output / "agent" / "candidates"
        # So set agent_output such that agent_output/agent/candidates == legacy path.
        # If legacy = base/legacy, we need agent_output/agent/candidates = base/legacy
        # That means agent_output/agent = base and candidates named legacy — not equal.
        # Instead: make legacy = base/agent/candidates and agent_output = base.
        shutil.rmtree(legacy)
        agent_output = base / "ao"
        canonical = agent_output / "agent" / "candidates"
        legacy = canonical
        _write_legacy_candidate(legacy, "candidate-1", b"data\n")
        backup = base / "backup"
    elif layout == "backup_eq_legacy":
        backup = legacy
    elif layout == "backup_inside_legacy":
        backup = legacy / "nested-backup"
    elif layout == "legacy_inside_backup":
        backup = base / "backup"
        # Move legacy under backup for planned paths: re-home
        shutil.rmtree(legacy)
        backup.mkdir()
        legacy = backup / "legacy-nested"
        _write_legacy_candidate(legacy, "candidate-1", b"data\n")
    elif layout == "canonical_inside_legacy":
        shutil.rmtree(legacy)
        legacy = base / "legacy"
        agent_output = legacy / "nested-agent"
        canonical = agent_output / "agent" / "candidates"
        _write_legacy_candidate(legacy, "candidate-1", b"data\n")
        _write_legacy_candidate(canonical, "other-1", b"other\n")
        backup = base / "backup"
    elif layout == "legacy_inside_canonical":
        agent_output = base / "ao"
        canonical = agent_output / "agent" / "candidates"
        legacy = canonical / "legacy-nested"
        _write_legacy_candidate(legacy, "candidate-1", b"data\n")
        backup = base / "backup"
    elif layout == "backup_inside_canonical":
        backup = canonical / "nested-backup"
    elif layout == "canonical_inside_backup":
        backup = base / "backup"
        agent_output = backup / "nested-agent"
        canonical = agent_output / "agent" / "candidates"
        shutil.rmtree(base / "agent-output", ignore_errors=True)
        _write_legacy_candidate(canonical, "other-1", b"other\n")
        # legacy stays at base/legacy from initial setup — recreate if needed
        if not (base / "legacy").exists():
            _write_legacy_candidate(base / "legacy", "candidate-1", b"data\n")
        legacy = base / "legacy"

    before = {
        "legacy": _tree_fingerprint(legacy) if legacy.exists() else [],
        "canonical": _tree_fingerprint(canonical) if canonical.exists() else [],
        "backup": _tree_fingerprint(backup) if backup.exists() else [],
        "base": _tree_fingerprint(base),
    }

    # Legacy/canonical overlap fails at audit; backup overlap fails at apply.
    if layout in {
        "legacy_eq_canonical",
        "canonical_inside_legacy",
        "legacy_inside_canonical",
    }:
        with pytest.raises((CandidateIntegrityError, CandidateMigrationConflict)):
            audit_candidate_roots(legacy_dir=legacy, agent_output_dir=agent_output)
    else:
        report = audit_candidate_roots(
            legacy_dir=legacy, agent_output_dir=agent_output
        )
        with pytest.raises((CandidateIntegrityError, CandidateMigrationConflict)):
            apply_candidate_migration(report, backup_dir=backup)

    assert (
        _tree_fingerprint(legacy) if legacy.exists() else []
    ) == before["legacy"]
    if canonical.exists():
        assert _tree_fingerprint(canonical) == before["canonical"]
    if backup.exists():
        assert _tree_fingerprint(backup) == before["backup"]


def test_apply_detects_legacy_root_identity_drift(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    _write_legacy_candidate(legacy, "candidate-1", b"legacy\n")
    report = audit_candidate_roots(legacy_dir=legacy, agent_output_dir=agent_output)

    # Replace legacy root after audit.
    shutil.rmtree(legacy)
    replacement = tmp_path / "replacement-outside"
    _write_legacy_candidate(replacement, "candidate-1", b"replacement\n")
    replacement.rename(legacy)
    before_repl = _tree_fingerprint(legacy)

    with pytest.raises((CandidateIntegrityError, CandidateMigrationConflict)):
        apply_candidate_migration(report, backup_dir=tmp_path / "backup")

    assert _tree_fingerprint(legacy) == before_repl
    # Canonical must not receive the replacement bytes.
    canonical = agent_output / "agent" / "candidates" / "candidate-1"
    assert not canonical.exists()


def test_apply_detects_canonical_candidate_identity_drift(tmp_path) -> None:
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(canonical, "candidate-1", b"pending\n")
    report = audit_candidate_roots(
        legacy_dir=tmp_path / "missing-legacy",
        agent_output_dir=agent_output,
    )
    assert report.canonical_unversioned == ["candidate-1"]

    # Replace candidate entry after audit.
    cdir = canonical / "candidate-1"
    outside = tmp_path / "outside-cand"
    _write_legacy_candidate(outside, "candidate-1", b"swapped\n")
    shutil.rmtree(cdir)
    (outside / "candidate-1").rename(cdir)
    before = _tree_fingerprint(cdir)

    with pytest.raises((CandidateIntegrityError, CandidateMigrationConflict)):
        apply_candidate_migration(report, backup_dir=tmp_path / "backup")

    assert _tree_fingerprint(cdir) == before
    assert not (cdir / "manifest.v1.json").exists()


def test_apply_detects_canonical_root_identity_drift(tmp_path) -> None:
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(canonical, "candidate-1", b"pending\n")
    report = audit_candidate_roots(
        legacy_dir=tmp_path / "missing-legacy",
        agent_output_dir=agent_output,
    )
    assert report.canonical_unversioned == ["candidate-1"]
    assert report.canonical_present

    # Replace entire canonical candidates root after audit (new inode).
    outside = tmp_path / "replacement-canonical-root"
    _write_legacy_candidate(outside, "candidate-1", b"pending\n")
    shutil.rmtree(canonical)
    outside.rename(canonical)
    before_repl = _tree_fingerprint(canonical)

    with pytest.raises((CandidateIntegrityError, CandidateMigrationConflict)):
        apply_candidate_migration(report, backup_dir=tmp_path / "backup")

    assert _tree_fingerprint(canonical) == before_repl
    assert not (canonical / "candidate-1" / "manifest.v1.json").exists()


def test_apply_detects_pool_lock_swap_after_audit(tmp_path) -> None:
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(canonical, "candidate-1", b"pending\n")
    # Plant a regular pool lock so apply re-opens an existing entry.
    lock_path = canonical / ".candidate-pool.lock"
    lock_path.write_bytes(b"lock-v1\n")
    report = audit_candidate_roots(
        legacy_dir=tmp_path / "missing-legacy",
        agent_output_dir=agent_output,
    )
    assert report.canonical_unversioned == ["candidate-1"]

    # Swap the pool lock for a symlink after audit (identity / type drift).
    outside_target = tmp_path / "outside-lock-target"
    outside_target.write_bytes(b"evil\n")
    lock_path.unlink()
    lock_path.symlink_to(outside_target)
    before_canonical = _tree_fingerprint(canonical)

    with pytest.raises((CandidateIntegrityError, CandidateMigrationConflict)):
        apply_candidate_migration(report, backup_dir=tmp_path / "backup")

    assert _tree_fingerprint(canonical) == before_canonical
    assert not (canonical / "candidate-1" / "manifest.v1.json").exists()
    assert lock_path.is_symlink()


def test_incomplete_backup_is_not_treated_as_complete(tmp_path) -> None:
    """A partial backup left by a mid-copy crash must not skip re-backup/publish."""
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    backup = tmp_path / "backup"
    _write_legacy_candidate(legacy, "candidate-1", b"full-payload\n", approved=True)
    report = audit_candidate_roots(legacy_dir=legacy, agent_output_dir=agent_output)
    assert report.copyable == ["candidate-1"]

    # Plant an incomplete backup tree that would previously short-circuit.
    incomplete = backup / "legacy" / "candidate-1"
    incomplete.mkdir(parents=True)
    (incomplete / "metadata.json").write_text('{"partial": true}', encoding="utf-8")
    # Missing factor.py.candidate and approved.lock — incomplete vs source.
    before_legacy = _tree_fingerprint(legacy)

    apply_candidate_migration(report, backup_dir=backup)

    assert _tree_fingerprint(legacy) == before_legacy
    # Backup must be completed to match all source regular files.
    complete_backup = backup / "legacy" / "candidate-1"
    assert (complete_backup / "factor.py.candidate").read_bytes() == b"full-payload\n"
    assert (complete_backup / "metadata.json").is_file()
    assert (complete_backup / "approved.lock").is_file()
    # And publish must still occur after verified complete backup.
    snap = CandidatePool(agent_output).get("candidate-1")
    assert snap.artifact_bytes["factor.py.candidate"] == b"full-payload\n"
    assert snap.approval_binding == "legacy_unbound"


def test_complete_matching_backup_is_idempotent_noop_for_backup(tmp_path) -> None:
    """A complete, byte-matching backup may be reused without rewrite."""
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    backup = tmp_path / "backup"
    _write_legacy_candidate(legacy, "candidate-1", b"payload\n")
    report = audit_candidate_roots(legacy_dir=legacy, agent_output_dir=agent_output)

    # Plant a complete backup that matches source bytes exactly.
    complete = backup / "legacy" / "candidate-1"
    complete.mkdir(parents=True)
    for name in ("metadata.json", "factor.py.candidate"):
        (complete / name).write_bytes((legacy / "candidate-1" / name).read_bytes())
    before_backup = _tree_fingerprint(complete)

    apply_candidate_migration(report, backup_dir=backup)

    assert _tree_fingerprint(complete) == before_backup
    assert CandidatePool(agent_output).get("candidate-1").artifact_bytes[
        "factor.py.candidate"
    ] == b"payload\n"


def test_apply_is_noop_on_identical_rerun(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    _write_legacy_candidate(legacy, "candidate-1", b"same\n")
    report = audit_candidate_roots(legacy_dir=legacy, agent_output_dir=agent_output)
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    after_first = _tree_fingerprint(agent_output / "agent" / "candidates")
    legacy_fp = _tree_fingerprint(legacy)

    report2 = audit_candidate_roots(legacy_dir=legacy, agent_output_dir=agent_output)
    assert report2.copyable == []
    assert "candidate-1" in report2.identical
    apply_candidate_migration(report2, backup_dir=tmp_path / "backup2")

    assert _tree_fingerprint(agent_output / "agent" / "candidates") == after_first
    assert _tree_fingerprint(legacy) == legacy_fp


def test_migration_source_has_no_path_bypasses() -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "quant_system"
        / "agent"
        / "candidate_migration.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_attrs = {
        ("Path", "open"),
        ("Path", "mkdir"),
    }
    forbidden_names = {"tempfile"}
    forbidden_shutil = {"copy", "copy2", "copyfile", "copytree", "move"}
    forbidden_os = {"replace", "rename"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            pair = (node.value.id, node.attr)
            assert pair not in forbidden_attrs, f"forbidden {pair}"
            if node.value.id == "shutil":
                assert node.attr not in forbidden_shutil, f"forbidden shutil.{node.attr}"
            if node.value.id == "os" and node.attr in forbidden_os:
                # os.unlink / os.mkdir via dir_fd are allowed; replace/rename are not.
                raise AssertionError(f"forbidden os.{node.attr}")
        if isinstance(node, ast.Name) and node.id in forbidden_names:
            raise AssertionError(f"forbidden name {node.id}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_names
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_names


def test_migrate_candidates_cli_dry_run_defaults_and_env_root(
    tmp_path, monkeypatch
) -> None:
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(canonical, "candidate-cli", b"cli\n")
    monkeypatch.setenv("QS_AGENT_OUTPUT_DIR", str(agent_output))

    outside = tmp_path / "outside-cwd"
    outside.mkdir()
    monkeypatch.chdir(outside)

    result = runner.invoke(app, ["agent", "migrate-candidates"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    expected_canonical = str(resolve_candidates_dir(resolve_agent_output_dir(agent_output)))
    assert payload["canonical_dir"] == expected_canonical
    assert "candidate-cli" in payload["canonical_unversioned"]
    # Dry-run must not add manifest.
    assert not (canonical / "candidate-cli" / "manifest.v1.json").exists()
    assert not (outside / "agent").exists()


def test_migrate_candidates_cli_apply_requires_backup_dir(tmp_path, monkeypatch) -> None:
    agent_output = tmp_path / "agent-output"
    _write_legacy_candidate(
        agent_output / "agent" / "candidates", "candidate-1", b"x\n"
    )
    monkeypatch.setenv("QS_AGENT_OUTPUT_DIR", str(agent_output))
    result = runner.invoke(app, ["agent", "migrate-candidates", "--apply"])
    assert result.exit_code != 0


def test_copyable_legacy_candidate_lands_in_canonical(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    _write_legacy_candidate(legacy, "candidate-copy", b"payload\n")
    report = audit_candidate_roots(legacy_dir=legacy, agent_output_dir=agent_output)
    assert report.copyable == ["candidate-copy"]
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    snap = CandidatePool(agent_output).get("candidate-copy")
    assert snap.artifact_bytes["factor.py.candidate"] == b"payload\n"
    assert snap.approval_binding == "pending"
    assert (tmp_path / "backup").exists()
