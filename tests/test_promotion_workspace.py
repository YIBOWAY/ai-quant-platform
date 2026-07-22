"""Gate 3 isolated promotion workspace tests (Task 7)."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_system.agent.candidate_pool import CandidatePool
from quant_system.cli import app

runner = CliRunner()

_FINAL_BACKTEST_RECEIPT = "backtest-" + "f" * 32

_FACTOR_SRC = '''
from quant_system.factors.base import BaseFactor


class WorkspaceTestFactor(BaseFactor):
    factor_id = "workspace_test_factor"
    factor_name = "Workspace Test Factor"
    factor_version = "0.1.0-candidate"
    default_lookback = 20
    direction = "higher_is_better"
    description = "workspace promotion candidate"

    def _compute_values(self, frame):
        return frame["close"] * 0.0
'''

_CHANGED_FACTOR = _FACTOR_SRC.replace(
    "workspace_test_factor", "changed_workspace_factor"
).replace("WorkspaceTestFactor", "ChangedWorkspaceFactor")

_EMPTY_INIT = '''"""Code-reviewed, promoted factor library (Gate-3 output of D-20).

Each module under this package holds exactly one human-reviewed, git-committed
factor promoted from an approved candidate. This file is REGENERATED
deterministically by ``agent promote-candidate`` (sorted imports) -- do not
edit by hand. ``PROMOTED_FACTORS`` is the single source the registry factory
reads. It starts empty; promotions append.
"""

from __future__ import annotations

from quant_system.factors.base import BaseFactor

PROMOTED_FACTORS: tuple[type[BaseFactor], ...] = ()

__all__ = ["PROMOTED_FACTORS"]
'''


def test_historical_promotion_manifest_v1_0_remains_readable() -> None:
    from quant_system.agent.promotion_workspace import PromotionManifestV1

    manifest = PromotionManifestV1.model_validate(
        {
            "schema_version": "1.0",
            "promotion_id": "promo-historical",
            "base_commit": "a" * 40,
            "candidate_id": "candidate-historical",
            "candidate_digest": "b" * 64,
            "scoped_paths": ["src/factor.py"],
            "files": [
                {
                    "path": "src/factor.py",
                    "mode": "100644",
                    "sha256": "c" * 64,
                }
            ],
            "patch_sha256": "d" * 64,
        }
    )

    assert manifest.schema_version == "1.0"
    assert manifest.final_backtest_receipt_id is None


def _git(repo: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        shell=False,
    )
    return completed.stdout


def _git_bytes(repo: Path, *args: str, check: bool = True) -> bytes:
    completed = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        check=check,
        capture_output=True,
        text=False,
        shell=False,
    )
    return completed.stdout


def _fingerprint(path: Path) -> tuple[int, str] | None:
    if not path.exists():
        return None
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _tree_fingerprint(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            rel = str(path.relative_to(root))
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "platform-repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "gate3@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Gate3 Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    lib = repo / "src" / "quant_system" / "factors" / "library" / "promoted"
    lib.mkdir(parents=True)
    (lib / "__init__.py").write_text(_EMPTY_INIT, encoding="utf-8")
    tests = repo / "tests" / "factors"
    tests.mkdir(parents=True)
    (tests / ".gitkeep").write_text("", encoding="utf-8")
    (repo / "README.md").write_text("fixture repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    # Pin commit timestamps so two fixture repos with identical trees share one
    # base SHA; promotion_id is derived from base_commit and must stay stable.
    fixed_git_env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "1700000000 +0000",
        "GIT_COMMITTER_DATE": "1700000000 +0000",
    }
    subprocess.run(
        ["git", "commit", "-m", "base"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=fixed_git_env,
    )
    return repo


def _write_approved_candidate(agent_output: Path, source: str = _FACTOR_SRC) -> tuple[str, str]:
    pool = CandidatePool(agent_output)
    artifact = pool.write_candidate(
        task_id="gate3-task",
        goal="workspace-test-factor",
        artifact_type="factor",
        filename="factor.py.candidate",
        content=source,
    )
    pool.review(
        candidate_id=artifact.candidate_id,
        decision="approve",
        note="approve for gate3 workspace tests",
        expected_manifest_digest=artifact.manifest_digest,
        expected_status="pending",
    )
    return artifact.candidate_id, artifact.manifest_digest


def _approved_candidate(tmp_path: Path) -> tuple[Path, str, str]:
    agent_output = tmp_path / "agent-output"
    candidate_id, digest = _write_approved_candidate(agent_output)
    return agent_output, candidate_id, digest


def _prepare_kwargs(tmp_path: Path, repo: Path, agent_output: Path, candidate_id: str, digest: str):
    return {
        "repo_dir": repo,
        "agent_output_dir": agent_output,
        "candidate_id": candidate_id,
        "expected_candidate_digest": digest,
        "final_backtest_receipt_id": _FINAL_BACKTEST_RECEIPT,
        "base_commit": _git(repo, "rev-parse", "HEAD").strip(),
        "promotion_root": tmp_path / "promotion-state",
        "worktree_root": tmp_path / "worktrees",
    }


def test_legacy_pending_manifest_stays_read_only_after_patch_commit(
    tmp_path: Path,
) -> None:
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        cleanup_promotion_workspace,
        prepare_promotion_workspace,
        promotion_status,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = prepare_promotion_workspace(**kwargs)

    # Reproduce a historical, pre-final-receipt record while preserving the
    # exact persisted manifest/state digest contract.
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "1.0"
    manifest.pop("final_backtest_receipt_id")
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    result.manifest_path.write_bytes(manifest_bytes)

    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    state["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    result.state_path.write_text(
        json.dumps(state, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    scoped = manifest["scoped_paths"]
    _git(result.worktree_path, "add", "--", *scoped)
    _git(result.worktree_path, "commit", "-m", "historical human promotion")
    _git(
        result.worktree_path,
        "branch",
        f"codex/promotion-{result.promotion_id}",
        "HEAD",
    )

    status = promotion_status(
        promotion_id=result.promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
    )
    assert status["status"] == "awaiting_human_commit"
    assert status["reviewed_commit"] is None
    assert "schema 1.0" in status["reason"]
    persisted = json.loads(result.state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "awaiting_human_commit"
    assert persisted["reviewed_commit"] is None

    with pytest.raises(PromotionWorkspaceError, match="schema 1.0.*read-only"):
        cleanup_promotion_workspace(
            promotion_id=result.promotion_id,
            agent_output_dir=agent_output,
            promotion_root=kwargs["promotion_root"],
            worktree_root=kwargs["worktree_root"],
            repo_dir=repo,
            abandon=False,
        )
    assert result.worktree_path.exists()


def test_prepare_persists_final_receipt_in_manifest_identity_and_status(
    tmp_path: Path,
) -> None:
    from quant_system.agent.promotion_workspace import (
        prepare_promotion_workspace,
        promotion_status,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)

    result = prepare_promotion_workspace(**kwargs)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    status = promotion_status(
        promotion_id=result.promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
    )

    assert manifest["schema_version"] == "1.1"
    assert manifest["final_backtest_receipt_id"] == _FINAL_BACKTEST_RECEIPT
    assert status["final_backtest_receipt_id"] == _FINAL_BACKTEST_RECEIPT

    other = prepare_promotion_workspace(
        **{
            **kwargs,
            "final_backtest_receipt_id": "backtest-" + "e" * 32,
        }
    )
    assert other.promotion_id != result.promotion_id


def test_managed_root_normalizes_only_macos_system_alias_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_system.agent import promotion_workspace as pw

    real_realpath = pw.os.path.realpath

    def simulated_realpath(path: str | os.PathLike[str]) -> str:
        if os.fspath(path) == "/var":
            return "/private/var"
        return real_realpath(path)

    monkeypatch.setattr(pw.os.path, "realpath", simulated_realpath)
    assert pw._normalize_trusted_root_alias(
        Path("/var/folders/example/gate3")
    ) == Path("/private/var/folders/example/gate3")

    outside = tmp_path / "outside"
    outside.mkdir()
    user_alias = tmp_path / "user-alias"
    user_alias.symlink_to(outside, target_is_directory=True)
    normalized = pw._normalize_trusted_root_alias(user_alias / "gate3")
    assert normalized == user_alias / "gate3"
    assert normalized != outside / "gate3"


def test_promotion_uses_detached_worktree_and_ignores_unrelated_main_dirty(
    tmp_path: Path,
) -> None:
    from quant_system.agent.promotion_workspace import prepare_promotion_workspace

    repo = _git_repo(tmp_path)
    (repo / "unrelated.txt").write_text("user dirty\n", encoding="utf-8")
    fingerprint = _fingerprint(repo / "unrelated.txt")
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)

    result = prepare_promotion_workspace(
        **_prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    )

    assert result.worktree_path != repo
    assert result.patch_path.read_bytes().startswith(b"diff --git ")
    assert _fingerprint(repo / "unrelated.txt") == fingerprint
    assert _git(repo, "status", "--short") == " M unrelated.txt\n" or _git(
        repo, "status", "--short"
    ) == "?? unrelated.txt\n" or "unrelated.txt" in _git(repo, "status", "--short")
    # Untracked vs modified: file was never committed, so untracked is correct.
    assert "unrelated.txt" in _git(repo, "status", "--short")
    assert _git(result.worktree_path, "log", "-1", "--format=%H").strip() == result.base_commit
    assert _git(result.worktree_path, "rev-parse", "HEAD").strip() == result.base_commit


def test_promotion_refuses_changed_candidate_or_existing_scoped_target(
    tmp_path: Path,
) -> None:
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        prepare_promotion_workspace,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    candidate = agent_output / "agent" / "candidates" / candidate_id
    (candidate / "factor.py.candidate").write_text(_CHANGED_FACTOR, encoding="utf-8")
    with pytest.raises(PromotionWorkspaceError, match="candidate"):
        prepare_promotion_workspace(
            **_prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
        )


def test_promotion_refuses_base_commit_mismatch(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        prepare_promotion_workspace,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "extra.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "extra.txt")
    _git(repo, "commit", "-m", "advance")
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    kwargs["base_commit"] = base
    with pytest.raises(PromotionWorkspaceError, match="base"):
        prepare_promotion_workspace(**kwargs)


def test_promotion_refuses_existing_scoped_target_at_base(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        prepare_promotion_workspace,
    )

    repo = _git_repo(tmp_path)
    target = (
        repo
        / "src"
        / "quant_system"
        / "factors"
        / "library"
        / "promoted"
        / "workspace_test_factor.py"
    )
    target.write_text("# already promoted\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "preexisting factor")
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    with pytest.raises(PromotionWorkspaceError, match="already exists|scoped|target"):
        prepare_promotion_workspace(
            **_prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
        )


def test_promotion_refuses_dirty_scoped_path_in_main_worktree(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        prepare_promotion_workspace,
    )

    repo = _git_repo(tmp_path)
    init_path = (
        repo / "src" / "quant_system" / "factors" / "library" / "promoted" / "__init__.py"
    )
    init_path.write_text(init_path.read_text(encoding="utf-8") + "# dirty\n", encoding="utf-8")
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    with pytest.raises(PromotionWorkspaceError, match="dirty|scoped|worktree"):
        prepare_promotion_workspace(
            **_prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
        )
    assert "# dirty" in init_path.read_text(encoding="utf-8")


def test_prepare_is_idempotent_and_creates_no_commit(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import prepare_promotion_workspace

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    first = prepare_promotion_workspace(**kwargs)
    second = prepare_promotion_workspace(**kwargs)
    assert first.promotion_id == second.promotion_id
    assert first.patch_path.read_bytes() == second.patch_path.read_bytes()
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
    assert _git(first.worktree_path, "rev-parse", "HEAD").strip() == first.base_commit
    # No branches created by prepare.
    branches = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    assert "codex/promotion-" not in branches


def test_prepare_rolls_back_final_worktree_if_record_publication_fails_after_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_system.agent import promotion_workspace as pw

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)

    def fail_record_identity(_path: Path) -> tuple[int, int]:
        raise RuntimeError("injected record publication failure")

    monkeypatch.setattr(pw, "_dir_identity", fail_record_identity)

    with pytest.raises(RuntimeError, match="record publication"):
        pw.prepare_promotion_workspace(**kwargs)

    managed_children = list(kwargs["worktree_root"].iterdir())
    assert managed_children == []
    registered = _git(repo, "worktree", "list", "--porcelain")
    assert registered.count("worktree ") == 1
    promotion_dirs = [
        path for path in kwargs["promotion_root"].iterdir() if path.is_dir()
    ]
    assert promotion_dirs == []


def test_patch_manifest_deterministic_across_roots_and_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_system.agent import candidate_pool as pool_mod
    from quant_system.agent import models as models_mod
    from quant_system.agent import promotion_workspace as pw

    # Candidate metadata/locks bind utc_now_iso() (datetime.now), not time.time.
    # Freeze both so identical factor bytes yield identical digests across roots.
    fixed_iso = "2024-01-01T00:00:00Z"
    monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
    monkeypatch.setattr(models_mod, "utc_now_iso", lambda: fixed_iso)
    monkeypatch.setattr(pool_mod, "utc_now_iso", lambda: fixed_iso)

    results = []
    for label in ("a", "b"):
        root = tmp_path / label
        root.mkdir()
        repo = _git_repo(root)
        agent_output = root / "agent-output"
        # Same deterministic candidate bytes under both roots via pool write of fixed content.
        candidate_id, digest = _write_approved_candidate(agent_output, _FACTOR_SRC)
        result = pw.prepare_promotion_workspace(
            repo_dir=repo,
            agent_output_dir=agent_output,
            candidate_id=candidate_id,
            expected_candidate_digest=digest,
            final_backtest_receipt_id=_FINAL_BACKTEST_RECEIPT,
            base_commit=_git(repo, "rev-parse", "HEAD").strip(),
            promotion_root=root / "promo",
            worktree_root=root / "wt",
        )
        results.append(result)

    assert results[0].promotion_id == results[1].promotion_id
    assert results[0].patch_path.read_bytes() == results[1].patch_path.read_bytes()
    assert results[0].manifest_path.read_bytes() == results[1].manifest_path.read_bytes()
    manifest = json.loads(results[0].manifest_path.read_text(encoding="utf-8"))
    for key in ("worktree", "worktree_path", "promotion_root", "created_at", "timestamp"):
        assert key not in manifest
    # Module must stay clock-free for prepare outputs.
    source = Path(pw.__file__).read_text(encoding="utf-8")
    assert "datetime" not in source
    assert "date.today" not in source


def test_scoped_patch_three_paths_and_replay_matches_manifest(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import prepare_promotion_workspace

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    result = prepare_promotion_workspace(
        **_prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    )
    patch = result.patch_path.read_bytes()
    assert patch.count(b"diff --git ") == 3
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    scoped = manifest["scoped_paths"]
    assert len(scoped) == 3
    assert scoped[0].endswith("workspace_test_factor.py")
    assert scoped[1].endswith("__init__.py")
    assert scoped[2].endswith("test_workspace_test_factor.py")
    assert hashlib.sha256(patch).hexdigest() == manifest["patch_sha256"]

    # Replay into a second clean checkout at the base commit.
    replay = tmp_path / "replay-checkout"
    _git(repo, "worktree", "add", "--detach", str(replay), result.base_commit)
    subprocess.run(
        ["git", "-C", str(replay), "apply", "--check", "--binary"],
        input=patch,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(replay), "apply", "--binary"],
        input=patch,
        check=True,
        capture_output=True,
    )
    for entry in manifest["files"]:
        path = replay / entry["path"]
        payload = path.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        primary = result.worktree_path / entry["path"]
        assert primary.read_bytes() == payload
    _git(repo, "worktree", "remove", "--force", str(replay))


def test_cleanup_refuses_uncommitted_and_detached_until_named_branch(
    tmp_path: Path,
) -> None:
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        cleanup_promotion_workspace,
        prepare_promotion_workspace,
        promotion_status,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = prepare_promotion_workspace(**kwargs)
    worktree = result.worktree_path
    promotion_id = result.promotion_id
    prepared_status = promotion_status(
        promotion_id=promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
    )
    prepared_manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert prepared_status == {
        "promotion_id": promotion_id,
        "status": "awaiting_human_commit",
        "reviewed_commit": None,
        "reason": "worktree is not clean",
        "manifest_sha256": hashlib.sha256(result.manifest_path.read_bytes()).hexdigest(),
        "patch_sha256": prepared_manifest["patch_sha256"],
        "candidate_id": candidate_id,
        "candidate_digest": digest,
        "final_backtest_receipt_id": _FINAL_BACKTEST_RECEIPT,
        "base_commit": prepared_manifest["base_commit"],
        "scoped_paths": prepared_manifest["scoped_paths"],
    }

    with pytest.raises(PromotionWorkspaceError, match="uncommitted|reviewed|awaiting"):
        cleanup_promotion_workspace(
            promotion_id=promotion_id,
            agent_output_dir=agent_output,
            promotion_root=kwargs["promotion_root"],
            worktree_root=kwargs["worktree_root"],
            repo_dir=repo,
            abandon=False,
        )
    assert worktree.exists()

    # Human commits on detached HEAD without a named branch — still refuse.
    scoped = json.loads(result.manifest_path.read_text(encoding="utf-8"))["scoped_paths"]
    _git(worktree, "add", "--", *scoped)
    _git(worktree, "commit", "-m", "human promotion")
    with pytest.raises(PromotionWorkspaceError, match="branch|detached|named"):
        cleanup_promotion_workspace(
            promotion_id=promotion_id,
            agent_output_dir=agent_output,
            promotion_root=kwargs["promotion_root"],
            worktree_root=kwargs["worktree_root"],
            repo_dir=repo,
            abandon=False,
        )
    status = promotion_status(
        promotion_id=promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
    )
    assert status["status"] != "reviewed"

    # Named branch containing the commit unlocks reviewed cleanup.
    branch = f"codex/promotion-{promotion_id}"
    _git(worktree, "branch", branch, "HEAD")
    status = promotion_status(
        promotion_id=promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
    )
    assert status["status"] == "reviewed"
    assert status.get("reviewed_commit")
    cleanup_promotion_workspace(
        promotion_id=promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
        abandon=False,
    )
    assert not worktree.exists()
    state = json.loads(
        (kwargs["promotion_root"] / promotion_id / "state.json").read_text(encoding="utf-8")
    )
    assert state["status"] in {"cleaned", "reviewed_cleaned", "complete"}


def test_cleanup_without_abandon_never_falls_back_to_force_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_system.agent import promotion_workspace as pw

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = pw.prepare_promotion_workspace(**kwargs)
    scoped = json.loads(result.manifest_path.read_text(encoding="utf-8"))[
        "scoped_paths"
    ]
    _git(result.worktree_path, "add", "--", *scoped)
    _git(result.worktree_path, "commit", "-m", "human promotion")
    _git(
        result.worktree_path,
        "branch",
        f"codex/promotion-{result.promotion_id}",
        "HEAD",
    )

    original_git_text = pw._git_text
    remove_attempts: list[tuple[str, ...]] = []

    def fail_normal_remove(
        git_repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("worktree", "remove") and str(result.worktree_path) in args:
            remove_attempts.append(args)
            if "--force" in args:
                return subprocess.CompletedProcess(
                    ["git", *args], returncode=0, stdout="", stderr=""
                )
            return subprocess.CompletedProcess(
                ["git", *args],
                returncode=1,
                stdout="",
                stderr="injected normal removal failure",
            )
        return original_git_text(git_repo, *args, check=check)

    monkeypatch.setattr(pw, "_git_text", fail_normal_remove)

    with pytest.raises(pw.PromotionWorkspaceError, match="remov"):
        pw.cleanup_promotion_workspace(
            promotion_id=result.promotion_id,
            agent_output_dir=agent_output,
            promotion_root=kwargs["promotion_root"],
            worktree_root=kwargs["worktree_root"],
            repo_dir=repo,
            abandon=False,
        )

    assert result.worktree_path.exists()
    assert remove_attempts
    assert all("--force" not in attempt for attempt in remove_attempts)


def test_abandon_cleanup_force_removes_but_keeps_audit(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import (
        cleanup_promotion_workspace,
        prepare_promotion_workspace,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = prepare_promotion_workspace(**kwargs)
    patch_fp = _fingerprint(result.patch_path)
    manifest_fp = _fingerprint(result.manifest_path)
    cleanup_promotion_workspace(
        promotion_id=result.promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
        abandon=True,
    )
    assert not result.worktree_path.exists()
    assert _fingerprint(result.patch_path) == patch_fp
    assert _fingerprint(result.manifest_path) == manifest_fp
    state = json.loads(
        (kwargs["promotion_root"] / result.promotion_id / "state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["status"] == "abandoned"


def test_abandoned_promotion_can_reprepare_with_new_audit_id(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import (
        cleanup_promotion_workspace,
        prepare_promotion_workspace,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    first = prepare_promotion_workspace(**kwargs)
    first_manifest = first.manifest_path.read_bytes()
    first_patch = first.patch_path.read_bytes()
    cleanup_promotion_workspace(
        promotion_id=first.promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
        abandon=True,
    )

    second = prepare_promotion_workspace(**kwargs)

    assert second.promotion_id != first.promotion_id
    assert second.promotion_id.startswith(first.promotion_id + "-r")
    assert second.worktree_path.is_dir()
    first_state = json.loads(first.state_path.read_text(encoding="utf-8"))
    assert first_state["status"] == "abandoned"
    assert first.manifest_path.read_bytes() == first_manifest
    assert first.patch_path.read_bytes() == first_patch
    second_state = json.loads(second.state_path.read_text(encoding="utf-8"))
    assert second_state["status"] == "awaiting_human_commit"


@pytest.mark.parametrize("abandon", [False, True])
def test_cleanup_recovers_when_terminal_state_write_fails_after_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, abandon: bool
) -> None:
    from quant_system.agent import promotion_workspace as pw

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = pw.prepare_promotion_workspace(**kwargs)
    if not abandon:
        scoped = json.loads(result.manifest_path.read_text(encoding="utf-8"))[
            "scoped_paths"
        ]
        _git(result.worktree_path, "add", "--", *scoped)
        _git(result.worktree_path, "commit", "-m", "human promotion")
        _git(
            result.worktree_path,
            "branch",
            f"codex/promotion-{result.promotion_id}",
            "HEAD",
        )

    original_write = pw._write_bytes_replace
    terminal = "abandoned" if abandon else "cleaned"
    failed_once = False

    def fail_first_terminal_write(path: Path, payload: bytes) -> None:
        nonlocal failed_once
        decoded = json.loads(payload)
        if decoded.get("status") == terminal and not failed_once:
            failed_once = True
            raise OSError("injected terminal state write failure")
        original_write(path, payload)

    monkeypatch.setattr(pw, "_write_bytes_replace", fail_first_terminal_write)

    with pytest.raises(OSError, match="terminal state write failure"):
        pw.cleanup_promotion_workspace(
            promotion_id=result.promotion_id,
            agent_output_dir=agent_output,
            promotion_root=kwargs["promotion_root"],
            worktree_root=kwargs["worktree_root"],
            repo_dir=repo,
            abandon=abandon,
        )

    assert not result.worktree_path.exists()
    pending = json.loads(result.state_path.read_text(encoding="utf-8"))
    assert pending["status"] == ("abandon_pending" if abandon else "cleanup_pending")

    recovered = pw.cleanup_promotion_workspace(
        promotion_id=result.promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
        abandon=abandon,
    )

    assert recovered["status"] == terminal
    persisted = json.loads(result.state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == terminal


def test_status_rejects_tampered_worktree_commit(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import (
        prepare_promotion_workspace,
        promotion_status,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = prepare_promotion_workspace(**kwargs)
    worktree = result.worktree_path
    # Tamper after patch creation.
    factor = worktree / "src/quant_system/factors/library/promoted/workspace_test_factor.py"
    factor.write_text(factor.read_text(encoding="utf-8") + "\n# tamper\n", encoding="utf-8")
    scoped = json.loads(result.manifest_path.read_text(encoding="utf-8"))["scoped_paths"]
    _git(worktree, "add", "--", *scoped)
    _git(worktree, "commit", "-m", "tampered")
    _git(worktree, "branch", f"codex/promotion-{result.promotion_id}", "HEAD")
    status = promotion_status(
        promotion_id=result.promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
    )
    assert status["status"] != "reviewed"
    assert "patch" in status.get("reason", "").lower() or status["status"] in {
        "awaiting_human_commit",
        "invalid",
        "mismatch",
    }


def test_status_rejects_tampered_uncommitted_prepared_patch(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        prepare_promotion_workspace,
        promotion_status,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = prepare_promotion_workspace(**kwargs)
    result.patch_path.write_bytes(result.patch_path.read_bytes() + b"# tamper\n")

    with pytest.raises(PromotionWorkspaceError, match="patch digest"):
        promotion_status(
            promotion_id=result.promotion_id,
            agent_output_dir=agent_output,
            promotion_root=kwargs["promotion_root"],
            worktree_root=kwargs["worktree_root"],
            repo_dir=repo,
        )


def test_status_rejects_tampered_uncommitted_prepared_file(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        prepare_promotion_workspace,
        promotion_status,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = prepare_promotion_workspace(**kwargs)
    factor = (
        result.worktree_path
        / "src/quant_system/factors/library/promoted/workspace_test_factor.py"
    )
    factor.write_text(
        factor.read_text(encoding="utf-8") + "\n# uncommitted tamper\n",
        encoding="utf-8",
    )

    with pytest.raises(PromotionWorkspaceError, match="differs from scoped patch"):
        promotion_status(
            promotion_id=result.promotion_id,
            agent_output_dir=agent_output,
            promotion_root=kwargs["promotion_root"],
            worktree_root=kwargs["worktree_root"],
            repo_dir=repo,
        )


def test_status_uses_commit_range_patch_not_empty_worktree_diff(tmp_path: Path) -> None:
    from quant_system.agent.promotion_workspace import (
        prepare_promotion_workspace,
        promotion_status,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = prepare_promotion_workspace(**kwargs)
    worktree = result.worktree_path
    scoped = json.loads(result.manifest_path.read_text(encoding="utf-8"))["scoped_paths"]
    _git(worktree, "add", "--", *scoped)
    _git(worktree, "commit", "-m", "human promotion")
    _git(worktree, "branch", f"codex/promotion-{result.promotion_id}", "HEAD")
    # Working tree diff is empty after commit; status must still accept via BASE..HEAD.
    assert _git_bytes(worktree, "diff", "--", *scoped) == b""
    status = promotion_status(
        promotion_id=result.promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
    )
    assert status["status"] == "reviewed"


def test_status_marks_a_previously_reviewed_promotion_invalidated_on_recheck_failure(
    tmp_path: Path,
) -> None:
    from quant_system.agent.promotion_workspace import (
        prepare_promotion_workspace,
        promotion_status,
    )

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = prepare_promotion_workspace(**kwargs)
    scoped = json.loads(result.manifest_path.read_text(encoding="utf-8"))[
        "scoped_paths"
    ]
    _git(result.worktree_path, "add", "--", *scoped)
    _git(result.worktree_path, "commit", "-m", "human promotion")
    _git(
        result.worktree_path,
        "branch",
        f"codex/promotion-{result.promotion_id}",
        "HEAD",
    )
    reviewed = promotion_status(
        promotion_id=result.promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
    )
    reviewed_commit = reviewed["reviewed_commit"]
    assert reviewed["status"] == "reviewed"

    (result.worktree_path / "post-review.txt").write_text(
        "new unreviewed content\n", encoding="utf-8"
    )
    invalidated = promotion_status(
        promotion_id=result.promotion_id,
        agent_output_dir=agent_output,
        promotion_root=kwargs["promotion_root"],
        worktree_root=kwargs["worktree_root"],
        repo_dir=repo,
    )

    assert invalidated["status"] == "review_invalidated"
    assert invalidated["reviewed_commit"] == reviewed_commit
    assert "clean" in invalidated["reason"]
    persisted = json.loads(result.state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "review_invalidated"
    assert persisted["reviewed_commit"] == reviewed_commit


def test_status_and_cleanup_serialize_the_full_promotion_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_system.agent import promotion_workspace as pw

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = pw.prepare_promotion_workspace(**kwargs)
    scoped = json.loads(result.manifest_path.read_text(encoding="utf-8"))[
        "scoped_paths"
    ]
    _git(result.worktree_path, "add", "--", *scoped)
    _git(result.worktree_path, "commit", "-m", "human promotion")
    _git(
        result.worktree_path,
        "branch",
        f"codex/promotion-{result.promotion_id}",
        "HEAD",
    )

    first_review_ready = threading.Event()
    release_first_review = threading.Event()
    cleanup_done = threading.Event()
    call_lock = threading.Lock()
    calls = 0
    original_evaluate = pw._evaluate_reviewed_commit

    def pause_first_review(**review_kwargs):
        nonlocal calls
        evaluated = original_evaluate(**review_kwargs)
        with call_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_review_ready.set()
            release_first_review.wait(timeout=5)
        return evaluated

    monkeypatch.setattr(pw, "_evaluate_reviewed_commit", pause_first_review)
    failures: list[BaseException] = []

    def read_status() -> None:
        try:
            pw.promotion_status(
                promotion_id=result.promotion_id,
                agent_output_dir=agent_output,
                promotion_root=kwargs["promotion_root"],
                worktree_root=kwargs["worktree_root"],
                repo_dir=repo,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    def cleanup() -> None:
        try:
            pw.cleanup_promotion_workspace(
                promotion_id=result.promotion_id,
                agent_output_dir=agent_output,
                promotion_root=kwargs["promotion_root"],
                worktree_root=kwargs["worktree_root"],
                repo_dir=repo,
                abandon=False,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)
        finally:
            cleanup_done.set()

    status_thread = threading.Thread(target=read_status)
    cleanup_thread = threading.Thread(target=cleanup)
    status_thread.start()
    assert first_review_ready.wait(timeout=5)
    cleanup_thread.start()
    cleanup_finished_before_status_write = cleanup_done.wait(timeout=0.5)
    release_first_review.set()
    status_thread.join(timeout=5)
    cleanup_thread.join(timeout=5)

    assert not cleanup_finished_before_status_write
    assert not status_thread.is_alive()
    assert not cleanup_thread.is_alive()
    assert failures == []
    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    assert state["status"] == "cleaned"
    assert not result.worktree_path.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "main_repo",
        "other_repo",
        "outside_dir",
        "symlink_child",
        "nested_child",
        "wrong_promotion_id",
        "wrong_manifest_digest",
        "wrong_repo_identity",
    ],
)
@pytest.mark.parametrize("abandon", [False, True])
def test_status_cleanup_refuse_state_injection(
    tmp_path: Path, mutation: str, abandon: bool
) -> None:
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        cleanup_promotion_workspace,
        prepare_promotion_workspace,
        promotion_status,
    )

    repo = _git_repo(tmp_path)
    other_repo = _git_repo(tmp_path / "other")
    outside = tmp_path / "outside-tree"
    outside.mkdir()
    (outside / "secret.txt").write_text("keep\n", encoding="utf-8")
    outside_fp = _fingerprint(outside / "secret.txt")
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    kwargs = _prepare_kwargs(tmp_path, repo, agent_output, candidate_id, digest)
    result = prepare_promotion_workspace(**kwargs)
    promotion_id = result.promotion_id
    state_path = kwargs["promotion_root"] / promotion_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    main_fp = _tree_fingerprint(repo)
    other_fp = _tree_fingerprint(other_repo)
    patch_fp = _fingerprint(result.patch_path)
    manifest_fp = _fingerprint(result.manifest_path)
    cand_fp = _tree_fingerprint(agent_output / "agent" / "candidates")
    worktree_list_before = _git(repo, "worktree", "list", "--porcelain")

    if mutation == "main_repo":
        state["worktree_path"] = str(repo)
    elif mutation == "other_repo":
        state["worktree_path"] = str(other_repo)
    elif mutation == "outside_dir":
        state["worktree_path"] = str(outside)
    elif mutation == "symlink_child":
        link = kwargs["worktree_root"] / f"link-{promotion_id}"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(result.worktree_path, target_is_directory=True)
        state["worktree_path"] = str(link)
    elif mutation == "nested_child":
        nested = kwargs["worktree_root"] / "nested" / promotion_id
        nested.parent.mkdir(parents=True, exist_ok=True)
        state["worktree_path"] = str(nested)
    elif mutation == "wrong_promotion_id":
        state["promotion_id"] = "promo-not-the-real-id"
    elif mutation == "wrong_manifest_digest":
        state["manifest_sha256"] = "0" * 64
    elif mutation == "wrong_repo_identity":
        state["repo_st_ino"] = state["repo_st_ino"] + 99999
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(PromotionWorkspaceError):
        promotion_status(
            promotion_id=promotion_id,
            agent_output_dir=agent_output,
            promotion_root=kwargs["promotion_root"],
            worktree_root=kwargs["worktree_root"],
            repo_dir=repo,
        )
    with pytest.raises(PromotionWorkspaceError):
        cleanup_promotion_workspace(
            promotion_id=promotion_id,
            agent_output_dir=agent_output,
            promotion_root=kwargs["promotion_root"],
            worktree_root=kwargs["worktree_root"],
            repo_dir=repo,
            abandon=abandon,
        )

    assert _tree_fingerprint(repo) == main_fp
    assert _tree_fingerprint(other_repo) == other_fp
    assert _fingerprint(outside / "secret.txt") == outside_fp
    assert _fingerprint(result.patch_path) == patch_fp
    assert _fingerprint(result.manifest_path) == manifest_fp
    assert _tree_fingerprint(agent_output / "agent" / "candidates") == cand_fp
    assert _git(repo, "worktree", "list", "--porcelain") == worktree_list_before
    assert result.worktree_path.exists()


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "../x", "a/b", "a\\b", "/abs", "promo/../x"],
)
def test_invalid_promotion_id_refused_before_lookup(tmp_path: Path, bad_id: str) -> None:
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        cleanup_promotion_workspace,
        promotion_status,
    )

    repo = _git_repo(tmp_path)
    agent_output = tmp_path / "agent-output"
    agent_output.mkdir()
    promo_root = tmp_path / "promo"
    promo_root.mkdir()
    with pytest.raises(PromotionWorkspaceError, match="promotion_id|invalid"):
        promotion_status(
            promotion_id=bad_id,
            agent_output_dir=agent_output,
            promotion_root=promo_root,
            worktree_root=tmp_path / "wt",
            repo_dir=repo,
        )
    with pytest.raises(PromotionWorkspaceError, match="promotion_id|invalid"):
        cleanup_promotion_workspace(
            promotion_id=bad_id,
            agent_output_dir=agent_output,
            promotion_root=promo_root,
            worktree_root=tmp_path / "wt",
            repo_dir=repo,
            abandon=True,
        )
    assert list(promo_root.iterdir()) == []


def test_cli_help_contracts() -> None:
    prep = runner.invoke(app, ["agent", "promote-candidate", "--help"])
    assert prep.exit_code == 0
    assert "--candidate-id" in prep.output
    assert "--expected-digest" in prep.output
    assert "--final-backtest-receipt" in prep.output
    assert "--base-commit" in prep.output
    assert "--library-dir" not in prep.output
    assert "--tests-dir" not in prep.output
    assert "--agent-output-dir" not in prep.output
    assert "--worktree" not in prep.output

    status = runner.invoke(app, ["agent", "promotion-status", "--help"])
    assert status.exit_code == 0
    assert "--promotion-id" in status.output
    assert "--candidate-id" not in status.output
    assert "--base-commit" not in status.output
    assert "--abandon" not in status.output

    cleanup = runner.invoke(app, ["agent", "cleanup-promotion", "--help"])
    assert cleanup.exit_code == 0
    assert "--promotion-id" in cleanup.output
    assert "--abandon" in cleanup.output
    assert "--candidate-id" not in cleanup.output
    assert "--base-commit" not in cleanup.output


@pytest.mark.parametrize(
    "omit",
    [
        "--candidate-id",
        "--expected-digest",
        "--final-backtest-receipt",
        "--base-commit",
    ],
)
def test_cli_missing_required_exits_2_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, omit: str
) -> None:
    from quant_system.agent import promotion_workspace as pw

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    promo_root = agent_output / "agent" / "promotions"
    promo_root.mkdir(parents=True)
    base = _git(repo, "rev-parse", "HEAD").strip()

    monkeypatch.setattr(pw, "resolve_platform_repo", lambda: repo)
    monkeypatch.setattr(pw, "resolve_managed_worktree_root", lambda: worktree_root)
    monkeypatch.setenv("QS_AGENT_OUTPUT_DIR", str(agent_output))

    cand_fp = _tree_fingerprint(agent_output / "agent" / "candidates")
    repo_fp = _tree_fingerprint(repo)
    promo_fp = _tree_fingerprint(promo_root)
    wt_fp = _tree_fingerprint(worktree_root)

    args = ["agent", "promote-candidate"]
    if omit != "--candidate-id":
        args.extend(["--candidate-id", candidate_id])
    if omit != "--expected-digest":
        args.extend(["--expected-digest", digest])
    if omit != "--final-backtest-receipt":
        args.extend(["--final-backtest-receipt", _FINAL_BACKTEST_RECEIPT])
    if omit != "--base-commit":
        args.extend(["--base-commit", base])

    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert _tree_fingerprint(agent_output / "agent" / "candidates") == cand_fp
    assert _tree_fingerprint(repo) == repo_fp
    assert _tree_fingerprint(promo_root) == promo_fp
    assert _tree_fingerprint(worktree_root) == wt_fp


def test_cli_prepare_success_stdout_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_system.agent import promotion_workspace as pw

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    worktree_root = tmp_path / "worktrees"
    base = _git(repo, "rev-parse", "HEAD").strip()
    monkeypatch.setattr(pw, "resolve_platform_repo", lambda: repo)
    monkeypatch.setattr(pw, "resolve_managed_worktree_root", lambda: worktree_root)
    monkeypatch.setenv("QS_AGENT_OUTPUT_DIR", str(agent_output))

    # Direct prepare for byte comparison.
    direct = pw.prepare_promotion_workspace(
        repo_dir=repo,
        agent_output_dir=agent_output,
        candidate_id=candidate_id,
        expected_candidate_digest=digest,
        final_backtest_receipt_id=_FINAL_BACKTEST_RECEIPT,
        base_commit=base,
        promotion_root=agent_output / "agent" / "promotions",
        worktree_root=worktree_root,
    )
    # Idempotent second call via CLI.
    result = runner.invoke(
        app,
        [
            "agent",
            "promote-candidate",
            "--candidate-id",
            candidate_id,
            "--expected-digest",
            digest,
            "--final-backtest-receipt",
            _FINAL_BACKTEST_RECEIPT,
            "--base-commit",
            base,
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == {"promotion_id", "worktree", "patch", "manifest"}
    assert Path(payload["worktree"]) != repo
    assert Path(payload["patch"]).read_bytes() == direct.patch_path.read_bytes()
    assert Path(payload["manifest"]).read_bytes() == direct.manifest_path.read_bytes()
    assert "codex/promotion-" in result.stderr or "git diff" in result.stderr


def test_cli_human_instructions_name_actual_worktree_and_safe_quant_system_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_system.agent import promotion_workspace as pw

    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    worktree_root = tmp_path / "worktrees"
    base = _git(repo, "rev-parse", "HEAD").strip()
    monkeypatch.setattr(pw, "resolve_platform_repo", lambda: repo)
    monkeypatch.setattr(pw, "resolve_managed_worktree_root", lambda: worktree_root)
    monkeypatch.setenv("QS_AGENT_OUTPUT_DIR", str(agent_output))

    result = runner.invoke(
        app,
        [
            "agent",
            "promote-candidate",
            "--candidate-id",
            candidate_id,
            "--expected-digest",
            digest,
            "--final-backtest-receipt",
            _FINAL_BACKTEST_RECEIPT,
            "--base-commit",
            base,
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    promotion_id = payload["promotion_id"]
    assert payload["worktree"] in result.stderr
    assert (
        f"quant-system agent promotion-status --promotion-id {promotion_id}"
        in result.stderr
    )
    assert (
        f"quant-system agent cleanup-promotion --promotion-id {promotion_id}"
        in result.stderr
    )
    assert (
        f"quant-system agent cleanup-promotion --promotion-id {promotion_id} --abandon"
        in result.stderr
    )
    assert "quant-system agent promote-candidate" in result.stderr
    assert (
        f"--final-backtest-receipt {_FINAL_BACKTEST_RECEIPT}"
        in result.stderr
    )
    assert "re-prepare" in result.stderr.lower()
    assert "then run: agent " not in result.stderr


def test_cli_source_calls_only_prepare_not_materializer() -> None:
    cli_path = Path(__file__).resolve().parents[1] / "src" / "quant_system" / "cli.py"
    source = cli_path.read_text(encoding="utf-8")
    # Materializer must not be imported or invoked; the command name itself is
    # agent_promote_candidate and is allowed.
    assert "from quant_system.agent.promote import" not in source
    assert re.search(r"(?<!agent_)promote_candidate\s*\(", source) is None
    tree = ast.parse(source)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "agent_promote_candidate":
            fn = node
            break
    assert fn is not None
    called = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.append(node.func.attr)
    assert "prepare_promotion_workspace" in called
    assert "promote_candidate" not in called


def test_promote_module_still_git_free() -> None:
    promote_path = (
        Path(__file__).resolve().parents[1] / "src" / "quant_system" / "agent" / "promote.py"
    )
    source = promote_path.read_text(encoding="utf-8")
    assert "subprocess" not in source
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots.isdisjoint({"subprocess", "git", "os", "sys"})
