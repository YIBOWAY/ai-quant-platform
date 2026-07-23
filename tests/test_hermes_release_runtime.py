from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from quant_system.hermes.release_runtime import (
    ReleaseRuntimeProbeError,
    file_sha256,
    git_runtime_digest,
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
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Agent v0.2 Test")
    _git(repo, "config", "user.email", "agent-v02@example.invalid")
    (repo / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "runtime.py")
    _git(repo, "commit", "-qm", "runtime")
    return repo


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
        json.dumps({"status": "passed", "orders": 0}, sort_keys=True),
        encoding="utf-8",
    )

    first = file_sha256(evidence)
    evidence.write_text(
        json.dumps({"status": "failed", "orders": 0}, sort_keys=True),
        encoding="utf-8",
    )
    second = file_sha256(evidence)

    assert len(first) == 64
    assert first != second


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
