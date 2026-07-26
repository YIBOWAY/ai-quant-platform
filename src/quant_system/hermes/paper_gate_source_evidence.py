"""Bounded, digest-verified source evidence for a durable paper Gate 1.

The browser never supplies a path.  The caller first loads the exact
owner/workspace/gate row from PostgreSQL, then passes that row's immutable path
and SHA-256 here.  Every path component is opened without following symlinks,
the leaf must be a regular ``.py`` file, and bytes are returned only when their
digest exactly matches the Gate challenge.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

_DIGEST_LENGTH = 64
_MAX_PATH_BYTES = 4096
_MAX_SOURCE_BYTES = 1_048_576


class PaperGateSourceEvidenceError(RuntimeError):
    """Stable, body-free failure for the owner-only Gate 1 evidence route."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PaperGateSourceEvidence:
    source_file_ref: str
    reviewed_source_sha256: str
    observed_source_sha256: str
    byte_length: int
    source_utf8: str

    def to_public_dict(
        self,
        *,
        gate_id: str,
        workspace_id: str,
    ) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "gate_id": gate_id,
            "workspace_id": workspace_id,
            "source_file_ref": self.source_file_ref,
            "reviewed_source_sha256": self.reviewed_source_sha256,
            "observed_source_sha256": self.observed_source_sha256,
            "byte_length": self.byte_length,
            "media_type": "text/x-python; charset=utf-8",
            "source_utf8": self.source_utf8,
        }


def _canonical_local_path(source_file_ref: str) -> Path:
    if (
        type(source_file_ref) is not str
        or not source_file_ref.startswith("/")
        or not source_file_ref.isprintable()
        or "\x00" in source_file_ref
        or len(source_file_ref.encode("utf-8")) > _MAX_PATH_BYTES
    ):
        raise PaperGateSourceEvidenceError(
            "paper_gate_source_invalid",
            "Gate 1 source reference is not a bounded absolute path",
        )
    absolute = Path(os.path.abspath(source_file_ref))
    if absolute.suffix != ".py":
        raise PaperGateSourceEvidenceError(
            "paper_gate_source_invalid",
            "Gate 1 source must be a Python source file",
        )

    # macOS exposes /tmp and /var as fixed root-owned aliases. Normalize only
    # those aliases before the no-follow directory walk below.
    parts = absolute.parts
    if len(parts) >= 2 and parts[1] in {"tmp", "var"}:
        alias = Path("/") / parts[1]
        expected = Path("/private") / parts[1]
        if Path(os.path.realpath(alias)) == expected:
            absolute = expected.joinpath(*parts[2:])
    return absolute


def _read_no_follow(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)

    parent_fd = os.open("/", flags | directory)
    try:
        for component in path.parts[1:-1]:
            next_fd = os.open(
                component,
                flags | directory | nofollow,
                dir_fd=parent_fd,
            )
            os.close(parent_fd)
            parent_fd = next_fd
        leaf_fd = os.open(path.name, flags | nofollow, dir_fd=parent_fd)
        try:
            info = os.fstat(leaf_fd)
            if not stat.S_ISREG(info.st_mode):
                raise PaperGateSourceEvidenceError(
                    "paper_gate_source_invalid",
                    "Gate 1 source is not a regular file",
                )
            if info.st_size < 1 or info.st_size > _MAX_SOURCE_BYTES:
                raise PaperGateSourceEvidenceError(
                    "paper_gate_source_invalid",
                    "Gate 1 source exceeds the review size limit",
                )
            chunks: list[bytes] = []
            remaining = _MAX_SOURCE_BYTES + 1
            while remaining > 0:
                chunk = os.read(leaf_fd, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if not payload or len(payload) > _MAX_SOURCE_BYTES:
                raise PaperGateSourceEvidenceError(
                    "paper_gate_source_invalid",
                    "Gate 1 source exceeds the review size limit",
                )
            return payload
        finally:
            os.close(leaf_fd)
    except PaperGateSourceEvidenceError:
        raise
    except OSError as exc:
        raise PaperGateSourceEvidenceError(
            "paper_gate_source_unavailable",
            "Gate 1 source cannot be opened without following symlinks",
        ) from exc
    finally:
        os.close(parent_fd)


def read_verified_gate1_source(
    *,
    source_file_ref: str,
    reviewed_source_sha256: str,
) -> PaperGateSourceEvidence:
    """Read one exact Gate 1 source only when its stored SHA-256 still matches."""

    if (
        type(reviewed_source_sha256) is not str
        or len(reviewed_source_sha256) != _DIGEST_LENGTH
        or any(character not in "0123456789abcdef" for character in reviewed_source_sha256)
    ):
        raise PaperGateSourceEvidenceError(
            "paper_gate_source_invalid",
            "Gate 1 reviewed source digest is invalid",
        )
    path = _canonical_local_path(source_file_ref)
    payload = _read_no_follow(path)
    observed = hashlib.sha256(payload).hexdigest()
    if observed != reviewed_source_sha256:
        raise PaperGateSourceEvidenceError(
            "paper_gate_source_digest_mismatch",
            "Gate 1 source bytes no longer match the reviewed SHA-256",
        )
    try:
        source_utf8 = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PaperGateSourceEvidenceError(
            "paper_gate_source_not_utf8",
            "Gate 1 Python source is not valid UTF-8",
        ) from exc
    if "\x00" in source_utf8:
        raise PaperGateSourceEvidenceError(
            "paper_gate_source_not_utf8",
            "Gate 1 Python source contains a NUL byte",
        )
    return PaperGateSourceEvidence(
        source_file_ref=source_file_ref,
        reviewed_source_sha256=reviewed_source_sha256,
        observed_source_sha256=observed,
        byte_length=len(payload),
        source_utf8=source_utf8,
    )


__all__ = [
    "PaperGateSourceEvidence",
    "PaperGateSourceEvidenceError",
    "read_verified_gate1_source",
]
