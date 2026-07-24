from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_system.agent.candidate_fs import locked_candidates_root
from quant_system.agent.candidate_pool import (
    CandidateConflictError,
    CandidateIntegrityError,
    CandidateMigrationRequiredError,
    CandidatePool,
    CandidatePoolScanLimitExceeded,
    CandidateReviewStateStaleError,
    CandidateStaleError,
)
from quant_system.agent.safety import SafetyGate
from quant_system.cli import app

runner = CliRunner()


def _tree_fingerprint(root: Path) -> list[tuple[str, int, bytes | None]]:
    if not root.exists():
        return []
    rows: list[tuple[str, int, bytes | None]] = []
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        st = path.lstat()
        payload = None
        if path.is_file() and not path.is_symlink():
            payload = path.read_bytes()
        rows.append((rel, st.st_mode, payload))
    return rows


def _write_unversioned_candidate(candidates_dir: Path, candidate_id: str) -> None:
    cdir = candidates_dir / candidate_id
    cdir.mkdir(parents=True)
    metadata = {
        "candidate_id": candidate_id,
        "task_id": "legacy-task",
        "artifact_type": "factor",
        "goal": "legacy goal",
        "universe": ["SPY"],
        "status": "pending",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "files": ["factor.py.candidate"],
        "safety": {
            "auto_promotion": False,
            "requires_human_review": True,
            "review_status": "pending",
        },
    }
    (cdir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )
    (cdir / "factor.py.candidate").write_text("# legacy\n", encoding="utf-8")


def _write_corrupt_candidate(candidates_dir: Path, candidate_id: str) -> None:
    cdir = candidates_dir / candidate_id
    cdir.mkdir(parents=True)
    (cdir / "metadata.json").write_text("{not-json", encoding="utf-8")


def _invoke_review_cli(
    agent_output: Path,
    candidate_id: str,
    *,
    digest: str = "0" * 64,
    decision: str = "approve",
    note: str = "cli note",
):
    return runner.invoke(
        app,
        [
            "agent",
            "review",
            "--candidate-id",
            candidate_id,
            "--decision",
            decision,
            "--note",
            note,
            "--expected-digest",
            digest,
            "--expected-status",
            "pending",
            "--agent-output-dir",
            str(agent_output),
        ],
    )


def test_same_id_same_manifest_is_noop_but_different_bytes_conflict(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    first = pool.write_candidate(
        task_id="stable-task",
        goal="stable goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# exact\n",
    )
    before = first.path.stat().st_mtime_ns
    second = pool.write_candidate(
        task_id="stable-task",
        goal="stable goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# exact\n",
    )
    assert second.manifest_digest == first.manifest_digest
    assert second.path.stat().st_mtime_ns == before

    with pytest.raises(CandidateConflictError):
        pool.write_candidate(
            task_id="stable-task",
            goal="stable goal",
            artifact_type="factor",
            filename="factor.py.candidate",
            content="# changed\n",
        )
    assert first.path.read_text(encoding="utf-8") == "# exact\n"


def test_candidate_write_rejects_oversized_source_before_filesystem_side_effects(
    tmp_path,
) -> None:
    pool = CandidatePool(tmp_path / "output")

    with pytest.raises(CandidateIntegrityError, match="candidate artifact exceeds"):
        pool.write_candidate(
            task_id="oversized-task",
            goal="oversized",
            artifact_type="factor",
            filename="factor.py.candidate",
            content="x" * (1024 * 1024 + 1),
        )

    assert not pool.candidates_dir.exists()


def test_same_id_retry_rejects_metadata_extra_drift(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    first = pool.write_candidate(
        task_id="metadata-stable-task",
        goal="metadata stable goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# exact\n",
        metadata_extra={"source_file_name": "first.py"},
    )

    with pytest.raises(CandidateConflictError):
        pool.write_candidate(
            task_id="metadata-stable-task",
            goal="metadata stable goal",
            artifact_type="factor",
            filename="factor.py.candidate",
            content="# exact\n",
            metadata_extra={"source_file_name": "second.py"},
        )

    metadata = json.loads(first.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_file_name"] == "first.py"


def test_review_requires_current_digest_and_legacy_lock_never_allows(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="review-task",
        goal="review goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# review\n",
    )
    with pytest.raises(CandidateStaleError):
        pool.review(
            candidate_id=artifact.candidate_id,
            decision="approve",
            note="wrong revision",
            expected_manifest_digest="0" * 64,
            expected_status="pending",
        )
    assert not (artifact.path.parent / "approved.lock").exists()

    (artifact.path.parent / "approved.lock").write_text("{}", encoding="utf-8")
    assert pool.get(artifact.candidate_id).approval_binding == "legacy_unbound"
    assert SafetyGate(tmp_path).allow_promotion(artifact.candidate_id) is False


@pytest.mark.parametrize(
    "case",
    [
        "parent",
        "absolute",
        "metadata.json",
        "manifest.v1.json",
        "approved.lock",
        "rejected.lock",
        "reviews.jsonl",
        "nested/metadata.json",
    ],
)
def test_write_rejects_unsafe_or_reserved_filename_before_any_side_effect(tmp_path, case) -> None:
    filename = {
        "parent": "../escaped.py",
        "absolute": str(tmp_path / "absolute-escaped.py"),
    }.get(case, case)
    pool = CandidatePool(tmp_path / "output")

    with pytest.raises(CandidateIntegrityError):
        pool.write_candidate(
            task_id="unsafe-path",
            goal="must not write",
            artifact_type="factor",
            filename=filename,
            content="# escaped\n",
        )

    assert not any(tmp_path.iterdir())
    assert not pool.candidates_dir.exists()


def test_unversioned_and_corrupt_items_remain_visible_but_never_authorize(
    tmp_path,
) -> None:
    pool = CandidatePool(tmp_path / "output")
    _write_unversioned_candidate(pool.candidates_dir, "legacy-pending")
    _write_corrupt_candidate(pool.candidates_dir, "broken")

    items = {item.candidate_id: item for item in pool.list_for_read()}

    legacy = items["legacy-pending"]
    assert legacy.integrity_state == "migration_required"
    assert legacy.manifest_digest is None
    assert len(legacy.observed_manifest_digest or "") == 64
    assert legacy.approval_enabled is False
    assert items["broken"].integrity_state == "corrupt"
    assert items["broken"].artifact_type is None
    assert items["broken"].status is None
    assert items["broken"].approval_binding is None
    with pytest.raises(CandidateMigrationRequiredError):
        pool.review(
            candidate_id="legacy-pending",
            decision="approve",
            note="observed digest is not authority",
            expected_manifest_digest=legacy.observed_manifest_digest or "",
            expected_status="pending",
        )


def test_candidate_sort_never_follows_a_corrupt_symlink_mtime(tmp_path) -> None:
    pool = CandidatePool(tmp_path / "output")
    artifact = pool.write_candidate(
        task_id="sort-safe-task",
        goal="sort without following corrupt entries",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# safe\n",
    )
    external = tmp_path / "external-target"
    external.mkdir()
    corrupt_link = pool.candidates_dir / "evil-link"
    corrupt_link.symlink_to(external, target_is_directory=True)
    now = time.time_ns()
    os.utime(artifact.path, ns=(now, now))
    os.utime(corrupt_link, ns=(now - 2_000_000_000, now - 2_000_000_000), follow_symlinks=False)
    os.utime(external, ns=(now + 2_000_000_000, now + 2_000_000_000))

    items = pool.list_for_read()

    assert [item.candidate_id for item in items[:2]] == [
        artifact.candidate_id,
        "evil-link",
    ]
    assert items[1].integrity_state == "corrupt"


def test_list_refuses_unsafe_candidate_root_instead_of_reporting_empty(
    tmp_path: Path,
) -> None:
    agent_output = tmp_path / "agent-output"
    pool = CandidatePool(agent_output)
    pool.candidates_dir.parent.mkdir(parents=True)
    external = tmp_path / "external-candidates"
    external.mkdir()
    pool.candidates_dir.symlink_to(external, target_is_directory=True)

    with pytest.raises(CandidateIntegrityError, match="symlink|unsafe|directory"):
        pool.list_for_read()


def test_list_refuses_dangling_candidate_root_symlink_instead_of_empty(
    tmp_path: Path,
) -> None:
    pool = CandidatePool(tmp_path / "agent-output")
    pool.candidates_dir.parent.mkdir(parents=True)
    pool.candidates_dir.symlink_to(tmp_path / "missing-target", target_is_directory=True)

    with pytest.raises(CandidateIntegrityError, match="symlink|unsafe|directory"):
        pool.list_for_read()


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "../outside", "../../outside", "/tmp/outside", "a/b", r"a\b", "approved.lock"],
)
def test_get_review_safety_api_and_cli_share_candidate_id_rejection_with_zero_writes(
    tmp_path, bad_id
) -> None:
    agent_output = tmp_path / "agent-output"
    outside = tmp_path / "outside"
    before = _tree_fingerprint(tmp_path)

    with pytest.raises(CandidateIntegrityError):
        CandidatePool(agent_output).get(bad_id)
    with pytest.raises(CandidateIntegrityError):
        CandidatePool(agent_output).review(
            candidate_id=bad_id,
            decision="approve",
            note="must fail before IO",
            expected_manifest_digest="0" * 64,
            expected_status="pending",
        )
    assert SafetyGate(agent_output).allow_promotion(bad_id) is False
    assert _invoke_review_cli(agent_output, bad_id).exit_code != 0
    assert _tree_fingerprint(tmp_path) == before
    assert not outside.exists()


@pytest.mark.parametrize(
    "first_decision,second_decision",
    [
        ("approve", "reject"),
        ("reject", "approve"),
        ("approve", "approve"),
        ("reject", "reject"),
    ],
)
def test_concurrent_and_retry_reviews_never_flip_final_decision(
    tmp_path, first_decision, second_decision
) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id=f"race-{first_decision}-{second_decision}",
        goal="race goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# race\n",
    )
    digest = artifact.manifest_digest
    assert digest is not None

    barrier = threading.Barrier(2)
    results: list[object] = []
    lock = threading.Lock()

    def _worker(decision: str) -> None:
        barrier.wait(timeout=5)
        try:
            record = pool.review(
                candidate_id=artifact.candidate_id,
                decision=decision,  # type: ignore[arg-type]
                note=f"decision-{decision}",
                expected_manifest_digest=digest,
                expected_status="pending",
            )
            with lock:
                results.append(record)
        except Exception as exc:  # noqa: BLE001 - collect either outcome
            with lock:
                results.append(exc)

    t1 = threading.Thread(target=_worker, args=(first_decision,))
    t2 = threading.Thread(target=_worker, args=(second_decision,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], CandidateReviewStateStaleError)

    candidate_dir = artifact.path.parent
    approved = candidate_dir / "approved.lock"
    rejected = candidate_dir / "rejected.lock"
    assert approved.exists() ^ rejected.exists()
    winner = approved if approved.exists() else rejected
    winner_bytes = winner.read_bytes()

    # Retries never overwrite, delete, or flip the final decision.
    for decision in (first_decision, second_decision, "approve", "reject"):
        with pytest.raises(CandidateReviewStateStaleError):
            pool.review(
                candidate_id=artifact.candidate_id,
                decision=decision,  # type: ignore[arg-type]
                note="retry after final",
                expected_manifest_digest=digest,
                expected_status="pending",
            )
        assert winner.read_bytes() == winner_bytes
        assert approved.exists() == (winner == approved)
        assert rejected.exists() == (winner == rejected)


def test_pool_lock_symlink_fifo_hardlink_fail_closed(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    candidates = agent / "agent" / "candidates"
    candidates.mkdir(parents=True)
    outside = tmp_path / "outside-lock"
    outside.write_bytes(b"outside-lock-bytes")

    # Symlink lock
    (candidates / ".candidate-pool.lock").symlink_to(outside)
    pool = CandidatePool(agent)
    with pytest.raises(CandidateIntegrityError):
        pool.write_candidate(
            task_id="lock-symlink",
            goal="g",
            artifact_type="factor",
            filename="factor.py.candidate",
            content="# x\n",
        )
    assert outside.read_bytes() == b"outside-lock-bytes"
    assert not any(candidates.glob("factor-*"))

    (candidates / ".candidate-pool.lock").unlink()

    # FIFO lock
    os.mkfifo(candidates / ".candidate-pool.lock")
    with pytest.raises(CandidateIntegrityError):
        pool.write_candidate(
            task_id="lock-fifo",
            goal="g",
            artifact_type="factor",
            filename="factor.py.candidate",
            content="# x\n",
        )
    assert outside.read_bytes() == b"outside-lock-bytes"
    os.unlink(candidates / ".candidate-pool.lock")

    # Hardlink-to-outside lock
    os.link(outside, candidates / ".candidate-pool.lock")
    with pytest.raises(CandidateIntegrityError):
        pool.write_candidate(
            task_id="lock-hardlink",
            goal="g",
            artifact_type="factor",
            filename="factor.py.candidate",
            content="# x\n",
        )
    assert outside.read_bytes() == b"outside-lock-bytes"
    assert candidates.joinpath(".candidate-pool.lock").stat().st_nlink >= 2


def test_candidates_root_swap_after_open_fails_closed(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    pool = CandidatePool(agent)
    artifact = pool.write_candidate(
        task_id="root-swap",
        goal="root swap",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# root\n",
    )
    candidates = pool.candidates_dir
    replacement = tmp_path / "replacement-candidates"
    replacement.mkdir()
    (replacement / "evil").mkdir()
    (replacement / "evil" / "metadata.json").write_text("{}", encoding="utf-8")
    outside_bytes = b"replacement-marker"
    (replacement / "marker").write_bytes(outside_bytes)

    original = candidates.rename(tmp_path / "original-candidates")
    replacement.rename(candidates)

    # Review against swapped root must fail closed; replacement untouched.
    with pytest.raises((CandidateIntegrityError, CandidateStaleError, OSError)):
        pool.review(
            candidate_id=artifact.candidate_id,
            decision="approve",
            note="after swap",
            expected_manifest_digest=artifact.manifest_digest or ("0" * 64),
            expected_status="pending",
        )
    assert (candidates / "marker").read_bytes() == outside_bytes
    assert not (candidates / "evil" / "approved.lock").exists()
    # Restore for cleanliness
    candidates.rename(replacement)
    original.rename(candidates)


def test_candidate_entry_swap_before_review_publish_fails_closed(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    pool = CandidatePool(agent)
    artifact = pool.write_candidate(
        task_id="cand-swap",
        goal="cand swap",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# cand\n",
    )
    candidate_dir = artifact.path.parent
    original = candidate_dir.rename(tmp_path / "original-candidate")
    replacement = candidate_dir
    replacement.mkdir()
    (replacement / "metadata.json").write_text(
        json.dumps(
            {
                "candidate_id": artifact.candidate_id,
                "artifact_type": "factor",
                "goal": "evil",
                "universe": [],
                "files": ["factor.py.candidate"],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (replacement / "factor.py.candidate").write_text("# evil\n", encoding="utf-8")
    outside = tmp_path / "outside-target"
    outside.write_bytes(b"outside-candidate")

    with pytest.raises(
        (
            CandidateIntegrityError,
            CandidateMigrationRequiredError,
            CandidateStaleError,
        )
    ):
        pool.review(
            candidate_id=artifact.candidate_id,
            decision="approve",
            note="swapped candidate",
            expected_manifest_digest=artifact.manifest_digest or ("0" * 64),
            expected_status="pending",
        )
    assert not (replacement / "approved.lock").exists()
    assert not (replacement / "rejected.lock").exists()
    assert outside.read_bytes() == b"outside-candidate"
    # Original still has no decision lock.
    assert not (original / "approved.lock").exists()


def test_interrupted_create_leaves_no_partial_final_candidate(tmp_path, monkeypatch) -> None:
    pool = CandidatePool(tmp_path)
    from quant_system.agent import candidate_pool as pool_mod

    def boom(*args, **kwargs):
        raise RuntimeError("publish interrupted")

    monkeypatch.setattr(pool_mod, "rename_directory_noreplace_at", boom)
    with pytest.raises(RuntimeError, match="publish interrupted"):
        pool.write_candidate(
            task_id="partial-task",
            goal="partial goal",
            artifact_type="factor",
            filename="factor.py.candidate",
            content="# partial\n",
        )
    candidates = pool.candidates_dir
    if candidates.exists():
        # No final candidate directory without staging prefix.
        for child in candidates.iterdir():
            assert child.name.startswith(".") or child.name == ".candidate-pool.lock"
            assert not child.name.startswith("factor-")


def test_structured_approve_authorizes_and_metadata_stays_immutable(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="auth-task",
        goal="auth goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# auth\n",
    )
    meta_before = artifact.metadata_path.read_bytes()
    record = pool.review(
        candidate_id=artifact.candidate_id,
        decision="approve",
        note="looks good",
        expected_manifest_digest=artifact.manifest_digest or "",
        expected_status="pending",
    )
    assert record.manifest_digest == artifact.manifest_digest
    lock = json.loads((artifact.path.parent / "approved.lock").read_text(encoding="utf-8"))
    assert lock["schema_version"] == "1.0"
    assert lock["manifest_digest"] == artifact.manifest_digest
    assert lock["decision"] == "approve"
    assert artifact.metadata_path.read_bytes() == meta_before
    assert SafetyGate(tmp_path).allow_promotion(artifact.candidate_id) is True
    items = pool.list_for_read()
    assert items[0].status == "approved"
    assert items[0].manifest_digest == artifact.manifest_digest


def test_candidate_read_limit_rejects_partial_repository_before_verification(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    for index in range(2):
        pool.write_candidate(
            task_id=f"bounded-read-{index}",
            goal=f"bounded read {index}",
            artifact_type="factor",
            filename=f"factor_{index}.py.candidate",
            content=f"# bounded {index}\n",
        )

    assert len(pool.list_for_read(max_entries=2)) == 2
    with pytest.raises(CandidatePoolScanLimitExceeded):
        pool.list_for_read(max_entries=1)
    with pytest.raises(CandidateIntegrityError, match="positive integer"):
        pool.list_for_read(max_entries=0)


def test_candidate_read_limit_bounds_dirfd_scan_before_sorting(
    tmp_path, monkeypatch
) -> None:
    pool = CandidatePool(tmp_path)
    for index in range(4):
        pool.write_candidate(
            task_id=f"bounded-scan-{index}",
            goal=f"bounded scan {index}",
            artifact_type="factor",
            filename=f"factor_{index}.py.candidate",
            content=f"# bounded scan {index}\n",
        )

    from quant_system.agent import candidate_pool as pool_mod

    real_scandir = os.scandir
    real_sorted = sorted
    visible_seen: list[str] = []
    sorted_sizes: list[int] = []

    class CountingScandir:
        def __init__(self, path) -> None:
            self._entries = real_scandir(path)

        def __enter__(self):
            self._entries.__enter__()
            return self

        def __exit__(self, *args):
            return self._entries.__exit__(*args)

        def __iter__(self):
            for entry in self._entries:
                name = entry.name
                if not name.startswith("."):
                    visible_seen.append(name)
                    assert len(visible_seen) <= 2
                yield entry

    def reject_unbounded_listdir(_path):
        raise AssertionError("bounded candidate reads must not materialize os.listdir")

    def assert_bounded_sort(values, *args, **kwargs):
        materialized = list(values)
        sorted_sizes.append(len(materialized))
        assert len(materialized) <= 2
        return real_sorted(materialized, *args, **kwargs)

    monkeypatch.setattr(pool_mod.os, "listdir", reject_unbounded_listdir)
    monkeypatch.setattr(pool_mod.os, "scandir", CountingScandir)
    monkeypatch.setattr(pool_mod, "sorted", assert_bounded_sort, raising=False)

    with pytest.raises(CandidatePoolScanLimitExceeded):
        pool.list_for_read(max_entries=1)

    assert len(visible_seen) == 2
    assert sorted_sizes == [2]


def test_candidate_read_limit_bounds_hidden_and_staging_dirents(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    pool.candidates_dir.mkdir(parents=True)
    for index in range(40):
        (pool.candidates_dir / f".staging-stale-{index:02d}").mkdir()

    with pytest.raises(CandidatePoolScanLimitExceeded):
        pool.list_for_read(max_entries=1)


def test_metadata_extra_cannot_override_protected_keys(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    with pytest.raises(CandidateIntegrityError):
        pool.write_candidate(
            task_id="meta-task",
            goal="meta goal",
            artifact_type="factor",
            filename="factor.py.candidate",
            content="# meta\n",
            metadata_extra={"status": "approved", "candidate_id": "other"},
        )


def test_safety_gate_requires_agent_output_not_candidates_dir(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="gate-task",
        goal="gate goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# gate\n",
    )
    pool.review(
        candidate_id=artifact.candidate_id,
        decision="approve",
        note="ok",
        expected_manifest_digest=artifact.manifest_digest or "",
        expected_status="pending",
    )
    assert SafetyGate(tmp_path).allow_promotion(artifact.candidate_id) is True
    # Passing candidates dir as if it were agent root must not authorize.
    assert SafetyGate(pool.candidates_dir).allow_promotion(artifact.candidate_id) is False


def test_static_regression_no_safetygate_candidates_dir_construction() -> None:
    """Candidate consumers must not construct SafetyGate from candidates_dir."""
    root = Path(__file__).resolve().parents[1] / "src" / "quant_system"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "SafetyGate(" not in text:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if "SafetyGate(" not in stripped or stripped.startswith("#"):
                continue
            # Allow the class definition file's docs only via name patterns.
            lowered = stripped.lower()
            if "candidates_dir" in lowered or '/ "agent" / "candidates"' in stripped:
                offenders.append(f"{path}:{i}:{stripped}")
            if ' / "agent" / "candidates"' in stripped and "SafetyGate" in stripped:
                offenders.append(f"{path}:{i}:{stripped}")
    assert offenders == []


def test_locked_candidates_root_holds_exclusive_lock(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    entered = threading.Event()
    release = threading.Event()
    second_entered = threading.Event()

    def holder() -> None:
        with locked_candidates_root(agent, create=True):
            entered.set()
            release.wait(timeout=5)

    t = threading.Thread(target=holder)
    t.start()
    assert entered.wait(timeout=5)

    def contender() -> None:
        with locked_candidates_root(agent, create=True):
            second_entered.set()

    t2 = threading.Thread(target=contender)
    t2.start()
    time.sleep(0.2)
    assert not second_entered.is_set()
    release.set()
    t.join(timeout=5)
    t2.join(timeout=5)
    assert second_entered.is_set()
