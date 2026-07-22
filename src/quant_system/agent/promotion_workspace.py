"""Isolated Gate-3 promotion workspace: detached worktree + scoped patch.

Public Gate 3 prepare materializes an approved candidate into a persistent
detached review worktree, never touching the user's dirty main worktree and
never creating a branch, commit, merge, or push. Humans inspect the scoped
binary patch, create a named branch, commit, then run status/cleanup.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from quant_system.agent.candidate_fs import (
    open_absolute_directory,
    read_regular_bytes_at,
)
from quant_system.agent.candidate_manifest import (
    CandidateIntegrityError,
    VerifiedCandidateSnapshot,
    canonical_json_bytes,
)
from quant_system.agent.candidate_pool import CandidatePool
from quant_system.agent.paths import PLATFORM_REPO_ROOT, resolve_agent_output_dir
from quant_system.agent.promote import (
    PromotionError,
    _extract_factor_class,
    promote_candidate,
)

__all__ = [
    "DEFAULT_MANAGED_WORKTREE_ROOT",
    "PromotionManifestV1",
    "PromotionWorkspaceError",
    "PromotionWorkspaceResult",
    "cleanup_promotion_workspace",
    "prepare_promotion_workspace",
    "promotion_status",
    "resolve_managed_worktree_root",
    "resolve_platform_repo",
    "validate_promotion_id",
]

_PROMOTED_REL = Path("src/quant_system/factors/library/promoted")
_TESTS_REL = Path("tests/factors")
_GIT_FILE_MODE = "100644"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FINAL_BACKTEST_RECEIPT_ID = re.compile(r"^backtest-[0-9a-f]{32}$")
_SAFE_PROMOTION_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,120}$")
_LOCK_NAME = ".promotion-workspace.lock"
_MANIFEST_NAME = "manifest.v1.json"
_STATE_NAME = "state.json"
_PATCH_NAME = "scoped.patch"

DEFAULT_MANAGED_WORKTREE_ROOT = (
    Path(tempfile.gettempdir()) / "ai-quant-platform-gate3-worktrees"
)


class PromotionWorkspaceError(RuntimeError):
    """Gate 3 workspace prepare/status/cleanup refused."""


class PromotionFileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    mode: str
    sha256: str


class PromotionManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "1.1"] = "1.1"
    promotion_id: str
    base_commit: str
    candidate_id: str
    candidate_digest: str
    final_backtest_receipt_id: str | None = None
    scoped_paths: list[str]
    files: list[PromotionFileEntry]
    patch_sha256: str

    @model_validator(mode="after")
    def validate_receipt_schema(self) -> PromotionManifestV1:
        if self.schema_version == "1.0":
            if self.final_backtest_receipt_id is not None:
                raise ValueError("schema 1.0 must not contain a final receipt")
            return self
        if (
            not isinstance(self.final_backtest_receipt_id, str)
            or _FINAL_BACKTEST_RECEIPT_ID.fullmatch(
                self.final_backtest_receipt_id
            )
            is None
        ):
            raise ValueError("schema 1.1 requires a valid final backtest receipt")
        return self


class PromotionStateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    promotion_id: str
    manifest_sha256: str
    repo_st_dev: int
    repo_st_ino: int
    managed_root_st_dev: int
    managed_root_st_ino: int
    worktree_path: str
    status: Literal[
        "awaiting_human_commit",
        "reviewed",
        "review_invalidated",
        "cleanup_pending",
        "abandon_pending",
        "cleaned",
        "abandoned",
    ]
    reviewed_commit: str | None = None


class PromotionWorkspaceResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    promotion_id: str
    base_commit: str
    worktree_path: Path
    patch_path: Path
    manifest_path: Path
    state_path: Path
    scoped_paths: list[str]


def _gate3_transition_refusal(manifest: PromotionManifestV1) -> str | None:
    """Return why this persisted manifest may be observed but never mutated."""
    receipt_id = manifest.final_backtest_receipt_id
    if manifest.schema_version != "1.1":
        return (
            f"legacy promotion manifest schema {manifest.schema_version} is read-only; "
            "Gate 3 transitions require schema 1.1 with a final backtest receipt"
        )
    if (
        not isinstance(receipt_id, str)
        or _FINAL_BACKTEST_RECEIPT_ID.fullmatch(receipt_id) is None
    ):
        return "promotion manifest has no valid final backtest receipt"
    return None


def resolve_platform_repo() -> Path:
    return PLATFORM_REPO_ROOT


def _normalize_trusted_root_alias(path: Path) -> Path:
    """Normalize only root-owned macOS /tmp and /var compatibility aliases."""
    absolute = Path(os.path.abspath(path))
    parts = absolute.parts
    if len(parts) >= 2:
        alias_targets = {
            "tmp": Path("/private/tmp"),
            "var": Path("/private/var"),
        }
        expected_target = alias_targets.get(parts[1])
        if expected_target is not None:
            alias = Path(os.sep) / parts[1]
            if Path(os.path.realpath(alias)) == expected_target:
                return expected_target.joinpath(*parts[2:])
    return absolute


def resolve_managed_worktree_root() -> Path:
    return _normalize_trusted_root_alias(DEFAULT_MANAGED_WORKTREE_ROOT)


def validate_promotion_id(value: str) -> str:
    if not isinstance(value, str) or _SAFE_PROMOTION_ID.fullmatch(value) is None:
        raise PromotionWorkspaceError(f"invalid promotion_id: {value!r}")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise PromotionWorkspaceError(f"invalid promotion_id: {value!r}")
    if Path(value).is_absolute() or Path(value).name != value:
        raise PromotionWorkspaceError(f"invalid promotion_id: {value!r}")
    return value


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _dir_identity(path: Path) -> tuple[int, int]:
    st = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(st.st_mode):
        raise PromotionWorkspaceError(f"not a directory: {path}")
    return int(st.st_dev), int(st.st_ino)


def _git_text(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        shell=False,
    )


def _git_bytes(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        check=check,
        capture_output=True,
        text=False,
        shell=False,
    )


def _require_git_ok(
    completed: subprocess.CompletedProcess[Any], *, context: str
) -> None:
    if completed.returncode != 0:
        err = completed.stderr
        err_text = (
            err.decode("utf-8", errors="replace")
            if isinstance(err, bytes)
            else err or ""
        )
        raise PromotionWorkspaceError(f"{context}: {err_text.strip() or 'git failed'}")


@contextmanager
def _promotion_root_lock(promotion_root: Path) -> Iterator[None]:
    promotion_root.mkdir(parents=True, exist_ok=True)
    lock_path = promotion_root / _LOCK_NAME
    fd = os.open(os.fspath(lock_path), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _resolve_base_commit(repo: Path, base_commit: str) -> str:
    if not isinstance(base_commit, str) or not base_commit.strip():
        raise PromotionWorkspaceError("base commit is required")
    completed = _git_text(
        repo, "rev-parse", "--verify", f"{base_commit}^{{commit}}", check=False
    )
    if completed.returncode != 0:
        raise PromotionWorkspaceError(f"base commit is not a valid commit: {base_commit!r}")
    return completed.stdout.strip()


def _main_head(repo: Path) -> str:
    completed = _git_text(repo, "rev-parse", "HEAD", check=False)
    _require_git_ok(completed, context="resolve main HEAD")
    return completed.stdout.strip()


def _require_head_equals_base(repo: Path, base: str) -> None:
    head = _main_head(repo)
    if head != base:
        raise PromotionWorkspaceError(
            f"base commit mismatch: main HEAD {head} != base {base}"
        )


def _scoped_paths_for(factor_id: str) -> list[str]:
    factor = str(_PROMOTED_REL / f"{factor_id}.py")
    init = str(_PROMOTED_REL / "__init__.py")
    test = str(_TESTS_REL / f"test_{factor_id}.py")
    return [factor, init, test]


def _path_exists_at_commit(repo: Path, commit: str, rel_path: str) -> bool:
    completed = _git_text(
        repo, "cat-file", "-e", f"{commit}:{rel_path}", check=False
    )
    return completed.returncode == 0


def _refuse_existing_targets(repo: Path, base: str, scoped: list[str]) -> None:
    factor_rel, init_rel, test_rel = scoped
    if not _path_exists_at_commit(repo, base, init_rel):
        raise PromotionWorkspaceError(
            f"promoted package init missing at base commit: {init_rel}"
        )
    if _path_exists_at_commit(repo, base, factor_rel):
        raise PromotionWorkspaceError(
            f"scoped target already exists at base commit: {factor_rel}"
        )
    if _path_exists_at_commit(repo, base, test_rel):
        raise PromotionWorkspaceError(
            f"scoped target already exists at base commit: {test_rel}"
        )


def _refuse_dirty_scoped(repo: Path, scoped: list[str]) -> None:
    completed = _git_text(
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *scoped,
        check=False,
    )
    _require_git_ok(completed, context="scoped status")
    if completed.stdout.strip():
        raise PromotionWorkspaceError(
            "main worktree has dirty or untracked scoped paths; "
            f"clean them before Gate 3 prepare:\n{completed.stdout}"
        )


def _load_verified_approved(
    *,
    agent_output_dir: Path,
    candidate_id: str,
    expected_candidate_digest: str,
) -> VerifiedCandidateSnapshot:
    if not isinstance(expected_candidate_digest, str) or _HEX64.fullmatch(
        expected_candidate_digest
    ) is None:
        raise PromotionWorkspaceError("expected candidate digest must be 64-char hex")
    try:
        snapshot = CandidatePool(agent_output_dir).get(candidate_id)
    except CandidateIntegrityError as exc:
        raise PromotionWorkspaceError(f"candidate cannot be verified: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - map all pool failures closed
        raise PromotionWorkspaceError(f"candidate cannot be verified: {exc}") from exc
    if snapshot.manifest_digest != expected_candidate_digest:
        raise PromotionWorkspaceError(
            f"candidate digest mismatch: expected {expected_candidate_digest}, "
            f"got {snapshot.manifest_digest}"
        )
    if snapshot.approval_binding != "approved":
        raise PromotionWorkspaceError(
            f"candidate {candidate_id!r} is not approved "
            f"(approval_binding={snapshot.approval_binding!r})"
        )
    return snapshot


def _factor_id_from_snapshot(snapshot: VerifiedCandidateSnapshot) -> str:
    source_bytes = snapshot.artifact_bytes.get("factor.py.candidate")
    if source_bytes is None:
        raise PromotionWorkspaceError("candidate has no factor.py.candidate")
    try:
        source = source_bytes.decode("utf-8", errors="strict")
        _class_name, factor_id = _extract_factor_class(source, snapshot.candidate_id)
    except (PromotionError, UnicodeDecodeError) as exc:
        raise PromotionWorkspaceError(str(exc)) from exc
    return factor_id


def _worktree_add_detach(repo: Path, worktree: Path, base: str) -> None:
    worktree.parent.mkdir(parents=True, exist_ok=True)
    if worktree.exists() or worktree.is_symlink():
        raise PromotionWorkspaceError(f"worktree path already exists: {worktree}")
    completed = _git_text(
        repo, "worktree", "add", "--detach", os.fspath(worktree), base, check=False
    )
    _require_git_ok(completed, context="git worktree add")


def _worktree_remove(repo: Path, worktree: Path, *, force: bool = False) -> None:
    if not worktree.exists() and not worktree.is_symlink():
        # Still try to prune registration if needed.
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(os.fspath(worktree))
        _git_text(repo, *args, check=False)
        _git_text(repo, "worktree", "prune", check=False)
        return
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(os.fspath(worktree))
    completed = _git_text(repo, *args, check=False)
    _require_git_ok(completed, context="git worktree remove")
    _git_text(repo, "worktree", "prune", check=False)


def _worktree_move(repo: Path, src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        raise PromotionWorkspaceError(f"destination worktree exists: {dst}")
    completed = _git_text(
        repo, "worktree", "move", os.fspath(src), os.fspath(dst), check=False
    )
    _require_git_ok(completed, context="git worktree move")


def _materialize_in_worktree(
    worktree: Path, snapshot: VerifiedCandidateSnapshot, expected_digest: str
) -> None:
    library_dir = worktree / _PROMOTED_REL
    tests_dir = worktree / _TESTS_REL
    try:
        promote_candidate(
            snapshot,
            expected_candidate_digest=expected_digest,
            library_dir=library_dir,
            tests_dir=tests_dir,
        )
    except PromotionError as exc:
        raise PromotionWorkspaceError(str(exc)) from exc


def _intent_to_add_new_files(worktree: Path, factor_rel: str, test_rel: str) -> None:
    completed = _git_text(
        worktree,
        "add",
        "--intent-to-add",
        "--",
        factor_rel,
        test_rel,
        check=False,
    )
    _require_git_ok(completed, context="git add --intent-to-add")
    cached = _git_text(worktree, "diff", "--cached", "--name-only", check=False)
    _require_git_ok(cached, context="git diff --cached")
    if cached.stdout.strip():
        raise PromotionWorkspaceError(
            "intent-to-add left staged content; refusing non-empty cached diff"
        )


def _capture_scoped_patch(worktree: Path, scoped: list[str]) -> bytes:
    completed = _git_bytes(
        worktree,
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-textconv",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--",
        *scoped,
        check=False,
    )
    _require_git_ok(completed, context="git diff scoped patch")
    patch = completed.stdout
    if not patch.startswith(b"diff --git "):
        raise PromotionWorkspaceError("scoped patch is empty or not a git diff")
    return patch


def _verify_post_materialization(
    worktree: Path, base: str, scoped: list[str], patch: bytes
) -> None:
    head = _git_text(worktree, "rev-parse", "HEAD", check=False)
    _require_git_ok(head, context="worktree HEAD")
    if head.stdout.strip() != base:
        raise PromotionWorkspaceError("worktree HEAD drifted from base commit")

    name_status = _git_text(
        worktree, "diff", "--name-status", "--", *scoped, check=False
    )
    _require_git_ok(name_status, context="name-status")
    lines = [line for line in name_status.stdout.splitlines() if line.strip()]
    expected = {
        f"A\t{scoped[0]}",
        f"M\t{scoped[1]}",
        f"A\t{scoped[2]}",
    }
    if set(lines) != expected:
        raise PromotionWorkspaceError(
            f"scoped name-status mismatch: {lines!r} expected {sorted(expected)!r}"
        )

    porcelain = _git_text(
        worktree, "status", "--porcelain=v1", "--untracked-files=all", check=False
    )
    _require_git_ok(porcelain, context="worktree status")
    status_paths: list[str] = []
    for line in porcelain.stdout.splitlines():
        if not line.strip():
            continue
        # porcelain: XY PATH or XY ORIG -> PATH
        body = line[3:] if len(line) > 3 else ""
        if " -> " in body:
            body = body.split(" -> ", 1)[1]
        status_paths.append(body)
    if set(status_paths) != set(scoped):
        raise PromotionWorkspaceError(
            f"worktree has unexpected paths in status: {status_paths!r}"
        )

    if b"new file mode" not in patch:
        raise PromotionWorkspaceError("patch missing new file mode entries")
    if b"/dev/null" not in patch:
        raise PromotionWorkspaceError("patch missing /dev/null entries for new files")
    for rel in (scoped[0], scoped[2]):
        marker = f"b/{rel}".encode()
        if marker not in patch:
            raise PromotionWorkspaceError(f"patch missing new file path {rel}")


def _file_entries(worktree: Path, scoped: list[str]) -> list[PromotionFileEntry]:
    entries: list[PromotionFileEntry] = []
    for rel in scoped:
        path = worktree / rel
        try:
            observed = path.lstat()
        except OSError as exc:
            raise PromotionWorkspaceError(f"expected regular file at {rel}") from exc
        if not stat.S_ISREG(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
            raise PromotionWorkspaceError(f"expected regular file at {rel}")
        if stat.S_IMODE(observed.st_mode) & 0o111:
            raise PromotionWorkspaceError(f"unexpected executable mode at {rel}")
        payload = _read_nofollow_regular(path)
        entries.append(
            PromotionFileEntry(
                path=rel,
                mode=_GIT_FILE_MODE,
                sha256=_sha256_hex(payload),
            )
        )
    return entries


def _replay_and_verify(
    repo: Path,
    base: str,
    patch: bytes,
    scoped: list[str],
    entries: list[PromotionFileEntry],
    worktree_root: Path,
) -> None:
    replay = worktree_root / f".replay-{secrets.token_hex(12)}"
    try:
        _worktree_add_detach(repo, replay, base)
        check = subprocess.run(
            ["git", "-C", os.fspath(replay), "apply", "--check", "--binary"],
            input=patch,
            check=False,
            capture_output=True,
            shell=False,
        )
        _require_git_ok(check, context="git apply --check")
        apply = subprocess.run(
            ["git", "-C", os.fspath(replay), "apply", "--binary"],
            input=patch,
            check=False,
            capture_output=True,
            shell=False,
        )
        _require_git_ok(apply, context="git apply")
        porcelain = _git_text(
            replay, "status", "--porcelain=v1", "--untracked-files=all", check=False
        )
        _require_git_ok(porcelain, context="replay status")
        status_paths: list[str] = []
        for line in porcelain.stdout.splitlines():
            if not line.strip():
                continue
            body = line[3:] if len(line) > 3 else ""
            if " -> " in body:
                body = body.split(" -> ", 1)[1]
            status_paths.append(body)
        # After apply without intent-to-add, new files are untracked (??) and
        # init is modified ( M). Paths must still be exactly the scoped set.
        if set(status_paths) != set(scoped):
            raise PromotionWorkspaceError(
                f"replay changed unexpected paths: {status_paths!r}"
            )
        for entry in entries:
            payload = (replay / entry.path).read_bytes()
            if _sha256_hex(payload) != entry.sha256:
                raise PromotionWorkspaceError(
                    f"replay digest mismatch for {entry.path}"
                )
    finally:
        _worktree_remove(repo, replay, force=True)


def _derive_promotion_id(
    *,
    candidate_id: str,
    candidate_digest: str,
    final_backtest_receipt_id: str,
    base_commit: str,
    scoped_paths: list[str],
    files: list[PromotionFileEntry],
    patch_sha256: str,
) -> str:
    payload = {
        "base_commit": base_commit,
        "candidate_digest": candidate_digest,
        "candidate_id": candidate_id,
        "final_backtest_receipt_id": final_backtest_receipt_id,
        "files": [entry.model_dump(mode="json") for entry in files],
        "patch_sha256": patch_sha256,
        "scoped_paths": scoped_paths,
    }
    digest = _sha256_hex(canonical_json_bytes(payload))
    return validate_promotion_id(f"promo-{digest[:32]}")


def _select_prepare_promotion_id(
    *,
    base_promotion_id: str,
    promotion_root: Path,
    worktree_root: Path,
    repo_dir: Path,
) -> str:
    """Reuse active prepares; allocate a new audit identity after abandon."""
    attempt = 1
    while True:
        promotion_id = (
            base_promotion_id
            if attempt == 1
            else validate_promotion_id(f"{base_promotion_id}-r{attempt}")
        )
        promotion_dir = promotion_root / promotion_id
        if not promotion_dir.exists() and not promotion_dir.is_symlink():
            return promotion_id
        _manifest, state, _manifest_path, _state_path, _patch_path = (
            _load_validated_promotion(
                promotion_id=promotion_id,
                promotion_root=promotion_root,
                worktree_root=worktree_root,
                repo_dir=repo_dir,
            )
        )
        if state.status == "abandoned":
            attempt += 1
            continue
        if state.status in {"abandon_pending", "cleanup_pending"}:
            raise PromotionWorkspaceError(
                f"promotion {promotion_id} has pending cleanup; rerun cleanup-promotion"
            )
        if state.status == "cleaned":
            raise PromotionWorkspaceError(
                f"promotion {promotion_id} is already reviewed and cleaned"
            )
        return promotion_id


def _write_bytes_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    fd = os.open(os.fspath(path), flags, 0o644)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)


def _write_bytes_replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{secrets.token_hex(8)}")
    fd = os.open(
        os.fspath(tmp),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o644,
    )
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(os.fspath(tmp), os.fspath(path))


def _human_instructions(
    promotion_id: str,
    scoped: list[str],
    final_backtest_receipt_id: str,
) -> str:
    paths = " ".join(shlex.quote(path) for path in scoped)
    branch = f"codex/promotion-{promotion_id}"
    worktree = resolve_managed_worktree_root() / promotion_id
    return (
        "GATE 3 — human-only next steps (system will not commit):\n"
        f"  1. cd -- {shlex.quote(str(worktree))}\n"
        f"  2. inspect: git diff --binary --full-index -- {paths}\n"
        f"  3. create named branch: git switch -c {branch}\n"
        f"  4. stage only scoped paths: git add -- {paths}\n"
        f"  5. review staged diff: git diff --cached --binary --full-index -- {paths}\n"
        f"  6. commit on the named branch, then run: quant-system agent promotion-status "
        f"--promotion-id {promotion_id}\n"
        f"  7. after reviewed status, run: quant-system agent cleanup-promotion "
        f"--promotion-id {promotion_id}\n"
        "  8. To discard this worktree and re-prepare, explicitly run: "
        f"quant-system agent cleanup-promotion --promotion-id {promotion_id} "
        "--abandon; then re-run the original quant-system agent promote-candidate "
        "command with the exact original candidate-id, expected-digest, and "
        f"base-commit, plus --final-backtest-receipt {final_backtest_receipt_id}. "
        "--abandon is destructive.\n"
    )


def prepare_promotion_workspace(
    *,
    repo_dir: Path,
    agent_output_dir: Path | str,
    candidate_id: str,
    expected_candidate_digest: str,
    final_backtest_receipt_id: str,
    base_commit: str,
    promotion_root: Path,
    worktree_root: Path,
) -> PromotionWorkspaceResult:
    """Prepare an isolated Gate 3 review worktree and immutable scoped patch."""
    repo_dir = Path(repo_dir)
    agent_output_dir = Path(agent_output_dir)
    promotion_root = _normalize_trusted_root_alias(Path(promotion_root))
    worktree_root = _normalize_trusted_root_alias(Path(worktree_root))

    if _FINAL_BACKTEST_RECEIPT_ID.fullmatch(final_backtest_receipt_id) is None:
        raise PromotionWorkspaceError("invalid final backtest receipt ID")

    if not repo_dir.is_dir():
        raise PromotionWorkspaceError(f"repo_dir does not exist: {repo_dir}")

    base = _resolve_base_commit(repo_dir, base_commit)
    _require_head_equals_base(repo_dir, base)

    snapshot = _load_verified_approved(
        agent_output_dir=agent_output_dir,
        candidate_id=candidate_id,
        expected_candidate_digest=expected_candidate_digest,
    )
    factor_id = _factor_id_from_snapshot(snapshot)
    scoped = _scoped_paths_for(factor_id)
    _refuse_existing_targets(repo_dir, base, scoped)
    _refuse_dirty_scoped(repo_dir, scoped)

    staging: Path | None = None
    final_worktree: Path | None = None
    final_worktree_moved = False
    records_published = False

    with _promotion_root_lock(promotion_root):
        _require_head_equals_base(repo_dir, base)
        _refuse_dirty_scoped(repo_dir, scoped)
        snapshot = _load_verified_approved(
            agent_output_dir=agent_output_dir,
            candidate_id=candidate_id,
            expected_candidate_digest=expected_candidate_digest,
        )
        # Factor id must still match.
        if _factor_id_from_snapshot(snapshot) != factor_id:
            raise PromotionWorkspaceError("candidate factor_id changed under lock")

        worktree_root.mkdir(parents=True, exist_ok=True)
        staging = worktree_root / f".staging-{secrets.token_hex(12)}"
        try:
            _worktree_add_detach(repo_dir, staging, base)
            _materialize_in_worktree(staging, snapshot, expected_candidate_digest)
            _intent_to_add_new_files(staging, scoped[0], scoped[2])
            patch = _capture_scoped_patch(staging, scoped)
            _verify_post_materialization(staging, base, scoped, patch)
            entries = _file_entries(staging, scoped)
            _replay_and_verify(
                repo_dir, base, patch, scoped, entries, worktree_root
            )

            # Final candidate re-verify before publishing immutable state.
            snapshot = _load_verified_approved(
                agent_output_dir=agent_output_dir,
                candidate_id=candidate_id,
                expected_candidate_digest=expected_candidate_digest,
            )
            if snapshot.manifest_digest != expected_candidate_digest:
                raise PromotionWorkspaceError("candidate digest drifted before publish")

            patch_sha = _sha256_hex(patch)
            base_promotion_id = _derive_promotion_id(
                candidate_id=candidate_id,
                candidate_digest=expected_candidate_digest,
                final_backtest_receipt_id=final_backtest_receipt_id,
                base_commit=base,
                scoped_paths=scoped,
                files=entries,
                patch_sha256=patch_sha,
            )
            promotion_id = _select_prepare_promotion_id(
                base_promotion_id=base_promotion_id,
                promotion_root=promotion_root,
                worktree_root=worktree_root,
                repo_dir=repo_dir,
            )
            promotion_dir = promotion_root / promotion_id
            patch_path = promotion_dir / _PATCH_NAME
            manifest_path = promotion_dir / _MANIFEST_NAME
            state_path = promotion_dir / _STATE_NAME
            final_worktree = worktree_root / promotion_id

            manifest = PromotionManifestV1(
                promotion_id=promotion_id,
                base_commit=base,
                candidate_id=candidate_id,
                candidate_digest=expected_candidate_digest,
                final_backtest_receipt_id=final_backtest_receipt_id,
                scoped_paths=scoped,
                files=entries,
                patch_sha256=patch_sha,
            )
            manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
            manifest_sha = _sha256_hex(manifest_bytes)

            if promotion_dir.exists():
                existing_manifest = _read_nofollow_regular(manifest_path)
                if existing_manifest != manifest_bytes:
                    raise PromotionWorkspaceError(
                        f"promotion_id {promotion_id} exists with different manifest"
                    )
                existing_patch = _read_nofollow_regular(patch_path)
                if existing_patch != patch:
                    raise PromotionWorkspaceError(
                        f"promotion_id {promotion_id} exists with different patch"
                    )
                # Idempotent: drop staging and return existing durable paths.
                _worktree_remove(repo_dir, staging, force=True)
                staging = None
                if not final_worktree.is_dir() or final_worktree.is_symlink():
                    raise PromotionWorkspaceError(
                        f"existing promotion {promotion_id} missing managed worktree"
                    )
                return PromotionWorkspaceResult(
                    promotion_id=promotion_id,
                    base_commit=base,
                    worktree_path=final_worktree.resolve()
                    if final_worktree.exists()
                    else final_worktree,
                    patch_path=patch_path,
                    manifest_path=manifest_path,
                    state_path=state_path,
                    scoped_paths=scoped,
                )

            # Publish worktree under promotion_id, then immutable records.
            _worktree_move(repo_dir, staging, final_worktree)
            staging = None
            final_worktree_moved = True

            repo_dev, repo_ino = _dir_identity(repo_dir)
            managed_dev, managed_ino = _dir_identity(worktree_root)
            state = PromotionStateV1(
                promotion_id=promotion_id,
                manifest_sha256=manifest_sha,
                repo_st_dev=repo_dev,
                repo_st_ino=repo_ino,
                managed_root_st_dev=managed_dev,
                managed_root_st_ino=managed_ino,
                worktree_path=str(final_worktree),
                status="awaiting_human_commit",
                reviewed_commit=None,
            )

            promotion_dir.mkdir(parents=False, exist_ok=False)
            try:
                _write_bytes_exclusive(patch_path, patch)
                _write_bytes_exclusive(manifest_path, manifest_bytes)
                _write_bytes_exclusive(
                    state_path, canonical_json_bytes(state.model_dump(mode="json"))
                )
                records_published = True
            except Exception:
                # Best-effort rollback of partial promotion dir + worktree.
                for path in (patch_path, manifest_path, state_path):
                    if path.exists():
                        path.unlink()
                if promotion_dir.exists():
                    promotion_dir.rmdir()
                raise

            return PromotionWorkspaceResult(
                promotion_id=promotion_id,
                base_commit=base,
                worktree_path=final_worktree,
                patch_path=patch_path,
                manifest_path=manifest_path,
                state_path=state_path,
                scoped_paths=scoped,
            )
        except Exception:
            if staging is not None and (staging.exists() or staging.is_symlink()):
                _worktree_remove(repo_dir, staging, force=True)
            if (
                final_worktree_moved
                and not records_published
                and final_worktree is not None
            ):
                _worktree_remove(repo_dir, final_worktree, force=True)
            raise


def _read_nofollow_regular(path: Path) -> bytes:
    """Read a regular file without following the final component if symlink."""
    parent = path.parent
    name = path.name
    if name in {"", ".", ".."} or "/" in name or "\\" in name:
        raise PromotionWorkspaceError(f"unsafe path component: {name!r}")
    try:
        with open_absolute_directory(parent, create=False) as opened:
            return read_regular_bytes_at(opened.fd, name)
    except Exception as exc:  # noqa: BLE001
        raise PromotionWorkspaceError(f"cannot safely read {path}: {exc}") from exc


def _parse_worktree_list(repo: Path) -> dict[str, dict[str, str]]:
    completed = _git_bytes(
        repo, "worktree", "list", "--porcelain", "-z", check=False
    )
    _require_git_ok(completed, context="git worktree list")
    raw = completed.stdout.split(b"\0")
    entries: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    current_path: str | None = None
    for part in raw:
        if not part:
            if current_path is not None:
                entries[current_path] = current
            current = {}
            current_path = None
            continue
        text = part.decode("utf-8", errors="replace")
        if text.startswith("worktree "):
            if current_path is not None:
                entries[current_path] = current
            current_path = text[len("worktree ") :]
            current = {"worktree": current_path}
        elif text.startswith("HEAD "):
            current["HEAD"] = text[len("HEAD ") :]
        elif text.startswith("branch "):
            current["branch"] = text[len("branch ") :]
        elif text == "detached":
            current["detached"] = "1"
        else:
            key = text.split(" ", 1)[0]
            current[key] = text[len(key) + 1 :] if " " in text else ""
    if current_path is not None:
        entries[current_path] = current
    return entries


def _load_validated_promotion(
    *,
    promotion_id: str,
    promotion_root: Path,
    worktree_root: Path,
    repo_dir: Path,
) -> tuple[PromotionManifestV1, PromotionStateV1, Path, Path, Path]:
    promotion_id = validate_promotion_id(promotion_id)
    promotion_root = _normalize_trusted_root_alias(Path(promotion_root))
    worktree_root = _normalize_trusted_root_alias(Path(worktree_root))
    repo_dir = Path(repo_dir)

    promotion_dir = promotion_root / promotion_id
    if promotion_dir.is_symlink() or not promotion_dir.is_dir():
        raise PromotionWorkspaceError(
            f"promotion directory missing or unsafe: {promotion_id}"
        )

    manifest_path = promotion_dir / _MANIFEST_NAME
    state_path = promotion_dir / _STATE_NAME
    patch_path = promotion_dir / _PATCH_NAME
    for path in (manifest_path, state_path, patch_path):
        if path.is_symlink() or not path.is_file():
            raise PromotionWorkspaceError(f"missing or unsafe promotion file: {path.name}")

    try:
        manifest_bytes = _read_nofollow_regular(manifest_path)
        manifest = PromotionManifestV1.model_validate(
            json.loads(manifest_bytes.decode("utf-8"))
        )
    except PromotionWorkspaceError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PromotionWorkspaceError(f"invalid promotion manifest: {exc}") from exc
    if manifest.promotion_id != promotion_id:
        raise PromotionWorkspaceError("manifest promotion_id mismatch")

    try:
        state = PromotionStateV1.model_validate(
            json.loads(_read_nofollow_regular(state_path).decode("utf-8"))
        )
    except PromotionWorkspaceError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PromotionWorkspaceError(f"invalid promotion state: {exc}") from exc

    if state.promotion_id != promotion_id:
        raise PromotionWorkspaceError("state promotion_id mismatch")
    manifest_sha = _sha256_hex(manifest_bytes)
    if state.manifest_sha256 != manifest_sha:
        raise PromotionWorkspaceError("state manifest digest mismatch")

    repo_dev, repo_ino = _dir_identity(repo_dir)
    if state.repo_st_dev != repo_dev or state.repo_st_ino != repo_ino:
        raise PromotionWorkspaceError("state repo identity mismatch")

    managed_dev, managed_ino = _dir_identity(worktree_root)
    if state.managed_root_st_dev != managed_dev or state.managed_root_st_ino != managed_ino:
        raise PromotionWorkspaceError("state managed-root identity mismatch")

    expected_worktree = worktree_root / promotion_id
    if Path(state.worktree_path) != expected_worktree:
        raise PromotionWorkspaceError("state worktree path is not managed direct child")
    if expected_worktree.is_symlink():
        raise PromotionWorkspaceError("managed worktree path is a symlink")
    # Nested rather than direct child already excluded by construction; double-check.
    if expected_worktree.parent.resolve() != worktree_root.resolve():
        raise PromotionWorkspaceError("worktree is not a direct child of managed root")

    active_states = {"awaiting_human_commit", "reviewed", "review_invalidated"}
    transition_states = {"cleanup_pending", "abandon_pending"}
    if state.status not in active_states:
        # cleaned/abandoned still allow status read of records, but not worktree ops
        # unless still present. Require registration when worktree is expected.
        pass

    validate_worktree = state.status in active_states or (
        state.status in transition_states and expected_worktree.exists()
    )
    if validate_worktree:
        if not expected_worktree.is_dir():
            raise PromotionWorkspaceError("managed worktree is missing")
        registered = _parse_worktree_list(repo_dir)
        # Compare path strings carefully; git may normalize.
        abs_expected = str(expected_worktree)
        abs_expected_resolved = str(expected_worktree.resolve())
        match = None
        for path, meta in registered.items():
            if path in {abs_expected, abs_expected_resolved} or Path(path) == expected_worktree:
                match = meta
                break
            try:
                if Path(path).resolve() == expected_worktree.resolve():
                    match = meta
                    break
            except OSError:
                continue
        if match is None:
            raise PromotionWorkspaceError(
                "worktree is not registered in git worktree list for platform repo"
            )

    return manifest, state, manifest_path, state_path, patch_path


def _committed_patch_bytes(
    worktree: Path, base_commit: str, scoped: list[str]
) -> bytes:
    completed = _git_bytes(
        worktree,
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-textconv",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        f"{base_commit}..HEAD",
        "--",
        *scoped,
        check=False,
    )
    _require_git_ok(completed, context="committed patch")
    return completed.stdout


def _verify_prepared_workspace(
    *,
    worktree: Path,
    manifest: PromotionManifestV1,
    prepared_patch: bytes,
) -> None:
    """Re-attest the uncommitted review workspace at status time."""
    if _sha256_hex(prepared_patch) != manifest.patch_sha256:
        raise PromotionWorkspaceError("prepared patch digest mismatch")
    _verify_post_materialization(
        worktree,
        manifest.base_commit,
        manifest.scoped_paths,
        prepared_patch,
    )
    observed_patch = _capture_scoped_patch(worktree, manifest.scoped_paths)
    if observed_patch != prepared_patch:
        raise PromotionWorkspaceError("prepared worktree differs from scoped patch")
    observed_files = _file_entries(worktree, manifest.scoped_paths)
    if observed_files != manifest.files:
        raise PromotionWorkspaceError("prepared worktree file evidence mismatch")


def _evaluate_reviewed_commit(
    *,
    repo_dir: Path,
    worktree: Path,
    manifest: PromotionManifestV1,
    patch_path: Path,
    agent_output_dir: Path,
) -> tuple[bool, str | None, str]:
    """Return (ok, reviewed_commit, reason)."""
    try:
        _require_head_equals_base(repo_dir, manifest.base_commit)
    except PromotionWorkspaceError as exc:
        return False, None, str(exc)

    porcelain = _git_text(
        worktree, "status", "--porcelain=v1", "--untracked-files=all", check=False
    )
    if porcelain.returncode != 0:
        return False, None, "cannot read worktree status"
    if porcelain.stdout.strip():
        return False, None, "worktree is not clean"

    head = _git_text(worktree, "rev-parse", "HEAD", check=False)
    if head.returncode != 0:
        return False, None, "cannot resolve worktree HEAD"
    head_sha = head.stdout.strip()
    if head_sha == manifest.base_commit:
        return False, None, "uncommitted: worktree HEAD still equals base"

    count = _git_text(
        worktree, "rev-list", "--count", f"{manifest.base_commit}..HEAD", check=False
    )
    if count.returncode != 0 or count.stdout.strip() != "1":
        return False, None, "worktree HEAD is not exactly one commit beyond base"

    parent = _git_text(worktree, "rev-parse", "HEAD^", check=False)
    if parent.returncode != 0 or parent.stdout.strip() != manifest.base_commit:
        return False, None, "commit parent is not the recorded base"

    # Named local branch must contain HEAD.
    refs = _git_text(
        worktree, "for-each-ref", "--contains", "HEAD", "refs/heads", check=False
    )
    if refs.returncode != 0 or not refs.stdout.strip():
        return False, None, "detached or unreferenced commit: no named local branch contains HEAD"

    # Path set via diff-tree.
    diff_tree = _git_text(
        worktree,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        "HEAD",
        check=False,
    )
    if diff_tree.returncode != 0:
        return False, None, "diff-tree failed"
    paths = [line for line in diff_tree.stdout.splitlines() if line.strip()]
    if set(paths) != set(manifest.scoped_paths):
        return False, None, f"commit path set mismatch: {paths!r}"

    # Per-file mode/bytes/digest vs manifest.
    for entry in manifest.files:
        ls = _git_text(worktree, "ls-tree", "HEAD", "--", entry.path, check=False)
        if ls.returncode != 0 or not ls.stdout.strip():
            return False, None, f"missing blob for {entry.path}"
        # format: <mode> <type> <sha>\t<path>
        meta = ls.stdout.strip().split("\t", 1)[0].split()
        if len(meta) < 3 or meta[0] != entry.mode:
            return False, None, f"mode mismatch for {entry.path}"
        blob = _git_bytes(worktree, "show", f"HEAD:{entry.path}", check=False)
        if blob.returncode != 0:
            return False, None, f"cannot read blob for {entry.path}"
        if _sha256_hex(blob.stdout) != entry.sha256:
            return False, None, f"blob digest mismatch for {entry.path}"

    try:
        _load_verified_approved(
            agent_output_dir=agent_output_dir,
            candidate_id=manifest.candidate_id,
            expected_candidate_digest=manifest.candidate_digest,
        )
    except PromotionWorkspaceError as exc:
        return False, None, f"candidate: {exc}"

    committed_patch = _committed_patch_bytes(
        worktree, manifest.base_commit, manifest.scoped_paths
    )
    if _sha256_hex(committed_patch) != manifest.patch_sha256:
        return False, None, "committed patch differs from reviewed patch"
    prepared = _read_nofollow_regular(patch_path)
    if committed_patch != prepared:
        return False, None, "committed patch bytes are not the prepared patch"

    return True, head_sha, "reviewed"


def promotion_status(
    *,
    promotion_id: str,
    agent_output_dir: Path | str,
    promotion_root: Path,
    worktree_root: Path,
    repo_dir: Path,
) -> dict[str, Any]:
    """Inspect promotion lifecycle; never removes the persistent worktree."""
    promotion_id = validate_promotion_id(promotion_id)
    promotion_root = _normalize_trusted_root_alias(Path(promotion_root))
    worktree_root = _normalize_trusted_root_alias(Path(worktree_root))
    with _promotion_root_lock(promotion_root):
        return _promotion_status_locked(
            promotion_id=promotion_id,
            agent_output_dir=agent_output_dir,
            promotion_root=promotion_root,
            worktree_root=worktree_root,
            repo_dir=repo_dir,
        )


def _promotion_status_locked(
    *,
    promotion_id: str,
    agent_output_dir: Path | str,
    promotion_root: Path,
    worktree_root: Path,
    repo_dir: Path,
) -> dict[str, Any]:
    agent_output_dir = Path(agent_output_dir)
    promotion_root = _normalize_trusted_root_alias(Path(promotion_root))
    worktree_root = _normalize_trusted_root_alias(Path(worktree_root))
    manifest, state, _manifest_path, state_path, patch_path = _load_validated_promotion(
        promotion_id=promotion_id,
        promotion_root=promotion_root,
        worktree_root=worktree_root,
        repo_dir=repo_dir,
    )
    worktree = worktree_root / promotion_id

    def payload(*, status: str, reviewed_commit: str | None, reason: str) -> dict[str, Any]:
        return {
            "promotion_id": promotion_id,
            "status": status,
            "reviewed_commit": reviewed_commit,
            "reason": reason,
            "manifest_sha256": state.manifest_sha256,
            "patch_sha256": manifest.patch_sha256,
            "candidate_id": manifest.candidate_id,
            "candidate_digest": manifest.candidate_digest,
            "final_backtest_receipt_id": manifest.final_backtest_receipt_id,
            "base_commit": manifest.base_commit,
            "scoped_paths": manifest.scoped_paths,
        }

    transition_refusal = _gate3_transition_refusal(manifest)
    if transition_refusal is not None:
        return payload(
            status=state.status,
            reviewed_commit=state.reviewed_commit,
            reason=transition_refusal,
        )

    if state.status in {"abandoned", "cleaned"}:
        return payload(
            status=state.status,
            reviewed_commit=state.reviewed_commit,
            reason=f"terminal state {state.status}",
        )
    if state.status in {"cleanup_pending", "abandon_pending"}:
        return payload(
            status=state.status,
            reviewed_commit=state.reviewed_commit,
            reason="cleanup transition is recoverable; rerun cleanup-promotion",
        )

    if state.status == "awaiting_human_commit" and state.reviewed_commit is None:
        prepared_patch = _read_nofollow_regular(patch_path)
        porcelain = _git_text(
            worktree,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            check=False,
        )
        _require_git_ok(porcelain, context="worktree status")
        if porcelain.stdout.strip():
            _verify_prepared_workspace(
                worktree=worktree,
                manifest=manifest,
                prepared_patch=prepared_patch,
            )

    ok, reviewed_commit, reason = _evaluate_reviewed_commit(
        repo_dir=repo_dir,
        worktree=worktree,
        manifest=manifest,
        patch_path=patch_path,
        agent_output_dir=agent_output_dir,
    )
    if ok and reviewed_commit is not None:
        state = state.model_copy(
            update={"status": "reviewed", "reviewed_commit": reviewed_commit}
        )
        _write_bytes_replace(
            state_path, canonical_json_bytes(state.model_dump(mode="json"))
        )
        return payload(
            status="reviewed",
            reviewed_commit=reviewed_commit,
            reason=reason,
        )
    if state.reviewed_commit is not None:
        state = state.model_copy(update={"status": "review_invalidated"})
        _write_bytes_replace(
            state_path, canonical_json_bytes(state.model_dump(mode="json"))
        )
        return payload(
            status="review_invalidated",
            reviewed_commit=state.reviewed_commit,
            reason=reason,
        )
    return payload(
        status=state.status,
        reviewed_commit=state.reviewed_commit,
        reason=reason,
    )


def cleanup_promotion_workspace(
    *,
    promotion_id: str,
    agent_output_dir: Path | str,
    promotion_root: Path,
    worktree_root: Path,
    repo_dir: Path,
    abandon: bool = False,
) -> dict[str, Any]:
    """Remove the managed review worktree only with reviewed evidence or --abandon."""
    promotion_id = validate_promotion_id(promotion_id)
    promotion_root = _normalize_trusted_root_alias(Path(promotion_root))
    worktree_root = _normalize_trusted_root_alias(Path(worktree_root))
    with _promotion_root_lock(promotion_root):
        return _cleanup_promotion_workspace_locked(
            promotion_id=promotion_id,
            agent_output_dir=agent_output_dir,
            promotion_root=promotion_root,
            worktree_root=worktree_root,
            repo_dir=repo_dir,
            abandon=abandon,
        )


def _cleanup_promotion_workspace_locked(
    *,
    promotion_id: str,
    agent_output_dir: Path | str,
    promotion_root: Path,
    worktree_root: Path,
    repo_dir: Path,
    abandon: bool,
) -> dict[str, Any]:
    agent_output_dir = Path(agent_output_dir)
    promotion_root = _normalize_trusted_root_alias(Path(promotion_root))
    worktree_root = _normalize_trusted_root_alias(Path(worktree_root))
    manifest, state, _manifest_path, state_path, patch_path = _load_validated_promotion(
        promotion_id=promotion_id,
        promotion_root=promotion_root,
        worktree_root=worktree_root,
        repo_dir=repo_dir,
    )
    worktree = worktree_root / promotion_id

    transition_refusal = _gate3_transition_refusal(manifest)
    if transition_refusal is not None:
        raise PromotionWorkspaceError(f"cleanup refused: {transition_refusal}")

    if state.status == "cleaned":
        return {
            "promotion_id": promotion_id,
            "status": "cleaned",
            "reviewed_commit": state.reviewed_commit,
        }
    if state.status == "abandoned" and not worktree.exists():
        return {
            "promotion_id": promotion_id,
            "status": "abandoned",
            "reviewed_commit": None,
        }

    if state.status == "abandon_pending":
        if worktree.exists() or worktree.is_symlink():
            _worktree_remove(repo_dir, worktree, force=True)
        state = state.model_copy(
            update={"status": "abandoned", "reviewed_commit": None}
        )
        _write_bytes_replace(
            state_path, canonical_json_bytes(state.model_dump(mode="json"))
        )
        return {
            "promotion_id": promotion_id,
            "status": "abandoned",
            "reviewed_commit": None,
        }

    if state.status == "cleanup_pending" and not worktree.exists():
        state = state.model_copy(update={"status": "cleaned"})
        _write_bytes_replace(
            state_path, canonical_json_bytes(state.model_dump(mode="json"))
        )
        return {
            "promotion_id": promotion_id,
            "status": "cleaned",
            "reviewed_commit": state.reviewed_commit,
        }

    if abandon:
        state = state.model_copy(
            update={"status": "abandon_pending", "reviewed_commit": None}
        )
        _write_bytes_replace(
            state_path, canonical_json_bytes(state.model_dump(mode="json"))
        )
        if worktree.exists() or worktree.is_symlink():
            _worktree_remove(repo_dir, worktree, force=True)
        state = state.model_copy(
            update={"status": "abandoned", "reviewed_commit": None}
        )
        _write_bytes_replace(
            state_path, canonical_json_bytes(state.model_dump(mode="json"))
        )
        return {
            "promotion_id": promotion_id,
            "status": "abandoned",
            "reviewed_commit": None,
        }

    ok, reviewed_commit, reason = _evaluate_reviewed_commit(
        repo_dir=repo_dir,
        worktree=worktree,
        manifest=manifest,
        patch_path=patch_path,
        agent_output_dir=agent_output_dir,
    )
    if not ok or reviewed_commit is None:
        raise PromotionWorkspaceError(
            f"cleanup refused without durable reviewed commit: {reason}"
        )

    if state.status == "cleanup_pending" and state.reviewed_commit != reviewed_commit:
        raise PromotionWorkspaceError(
            "cleanup refused because reviewed commit changed during recovery"
        )

    state = state.model_copy(
        update={"status": "cleanup_pending", "reviewed_commit": reviewed_commit}
    )
    _write_bytes_replace(
        state_path, canonical_json_bytes(state.model_dump(mode="json"))
    )
    _worktree_remove(repo_dir, worktree, force=False)
    state = state.model_copy(
        update={"status": "cleaned", "reviewed_commit": reviewed_commit}
    )
    _write_bytes_replace(
        state_path, canonical_json_bytes(state.model_dump(mode="json"))
    )
    return {
        "promotion_id": promotion_id,
        "status": "cleaned",
        "reviewed_commit": reviewed_commit,
    }


def prepare_cli_payload(result: PromotionWorkspaceResult) -> dict[str, str]:
    return {
        "promotion_id": result.promotion_id,
        "worktree": str(result.worktree_path),
        "patch": str(result.patch_path),
        "manifest": str(result.manifest_path),
    }


def default_promotion_root(agent_output_dir: Path | str | None = None) -> Path:
    root = resolve_agent_output_dir(agent_output_dir)
    return Path(root) / "agent" / "promotions"
