"""Production probes for the durable Agent v0.2 release gate.

The gate consumes observations only. This module binds those observations to
the actual clean Platform/HQA/Hermes checkouts, the live PostgreSQL schema and
runtime role, one sealed local evidence file, and a fresh loopback Hermes
capability response.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quant_system.config.settings import Settings
from quant_system.hermes.effective_release_gate import (
    EffectiveReleaseDecision,
    EffectiveReleaseGate,
    HermesDurableCapabilityObservation,
    LocalReleaseFlags,
    RuntimeIdentityObservation,
)
from quant_system.hermes.gateway_client import HermesApiReadClient
from quant_system.hermes.release_authority import (
    ReleaseAuthority,
    release_authority_runtime_security_ready,
    release_authority_schema_ready,
)
from quant_system.hermes.session_registry import hermes_runtime_security_ready
from quant_system.storage.database import get_database, schema_fingerprint

_LOGICAL_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_MAX_EVIDENCE_BYTES = 4 * 1024 * 1024


class ReleaseRuntimeProbeError(RuntimeError):
    """A runtime identity/evidence observation could not be trusted."""


def _run_git(root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseRuntimeProbeError(
            "runtime root is not a readable Git checkout"
        ) from exc
    if len(completed.stdout) > 1024 * 1024:
        raise ReleaseRuntimeProbeError("Git runtime observation is oversized")
    return completed.stdout


def git_runtime_digest(root: Path, *, logical_name: str) -> str:
    """Hash one logical runtime name plus its exact clean Git commit."""

    if _LOGICAL_NAME_RE.fullmatch(logical_name) is None:
        raise ReleaseRuntimeProbeError("runtime logical name is invalid")
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        raise ReleaseRuntimeProbeError("runtime root is unavailable")
    commit = _run_git(path, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if not re.fullmatch(rb"[0-9a-f]{40,64}", commit):
        raise ReleaseRuntimeProbeError("runtime commit identity is invalid")
    dirty = _run_git(
        path,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    if dirty:
        raise ReleaseRuntimeProbeError(
            "runtime checkout must be clean before release admission"
        )
    payload = b"agent-v0.2-runtime\x00" + logical_name.encode("ascii")
    payload += b"\x00commit\x00" + commit + b"\x00"
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    """Hash one bounded owner-controlled regular file without following links."""

    target = Path(path).expanduser()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise ReleaseRuntimeProbeError(
            "release evidence must be a readable regular file"
        ) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ReleaseRuntimeProbeError(
                "release evidence must be a readable regular file"
            )
        if info.st_size < 1 or info.st_size > _MAX_EVIDENCE_BYTES:
            raise ReleaseRuntimeProbeError(
                "release evidence must be nonempty and bounded"
            )
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise ReleaseRuntimeProbeError(
                "release evidence must be owned by the current user"
            )
        if stat.S_IMODE(info.st_mode) & 0o022:
            raise ReleaseRuntimeProbeError(
                "release evidence must not be group/world writable"
            )
        digest = hashlib.sha256()
        remaining = _MAX_EVIDENCE_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        if remaining <= 0 and os.read(fd, 1):
            raise ReleaseRuntimeProbeError(
                "release evidence must be nonempty and bounded"
            )
        return digest.hexdigest()
    finally:
        os.close(fd)


def platform_runtime_root() -> Path:
    return Path(__file__).resolve().parents[3]


def runtime_identity_observation(settings: Settings) -> RuntimeIdentityObservation:
    return RuntimeIdentityObservation(
        platform_runtime_digest=git_runtime_digest(
            platform_runtime_root(),
            logical_name="platform",
        ),
        hqa_runtime_digest=git_runtime_digest(
            settings.intent_payload.hqa_root,
            logical_name="hqa",
        ),
        hermes_runtime_digest=git_runtime_digest(
            settings.hermes_gateway.runtime_root,
            logical_name="hermes",
        ),
    )


def build_effective_release_gate(
    settings: Settings,
    *,
    gateway_client: HermesApiReadClient | None = None,
    now: Callable[[], datetime] | None = None,
) -> EffectiveReleaseGate:
    clock = now or (lambda: datetime.now(UTC))
    client = gateway_client or HermesApiReadClient(settings.hermes_gateway)

    def _capability() -> HermesDurableCapabilityObservation:
        payload = client.capabilities()
        hermes_digest = git_runtime_digest(
            settings.hermes_gateway.runtime_root,
            logical_name="hermes",
        )
        return HermesDurableCapabilityObservation(
            runtime_digest=hermes_digest,
            observed_at=clock(),
            payload=payload,
        )

    return EffectiveReleaseGate(
        authority=ReleaseAuthority(settings),
        local_flags_probe=lambda: LocalReleaseFlags(
            mutation_enabled=settings.local_mutation.enabled,
            composer_open=settings.local_mutation.composer_open,
        ),
        runtime_identity_probe=lambda: runtime_identity_observation(settings),
        database_schema_fingerprint_probe=lambda: schema_fingerprint(
            get_database(settings)
        ),
        release_evidence_digest_probe=lambda: file_sha256(
            settings.agent_v02_release.evidence_file
        ),
        runtime_role_readiness_probe=lambda: (
            hermes_runtime_security_ready(settings)
            and release_authority_runtime_security_ready(settings)
        ),
        authority_schema_readiness_probe=lambda: release_authority_schema_ready(
            settings
        ),
        hermes_capability_probe=_capability,
        now=clock,
        capability_max_age=timedelta(
            seconds=settings.agent_v02_release.capability_max_age_seconds
        ),
    )


def current_release_decision(
    settings: Settings,
    *,
    gateway_client: HermesApiReadClient | None = None,
    now: Callable[[], datetime] | None = None,
) -> EffectiveReleaseDecision:
    return build_effective_release_gate(
        settings,
        gateway_client=gateway_client,
        now=now,
    ).evaluate(settings.agent_v02_release.workspace_id)


__all__ = [
    "ReleaseRuntimeProbeError",
    "build_effective_release_gate",
    "current_release_decision",
    "file_sha256",
    "git_runtime_digest",
    "platform_runtime_root",
    "runtime_identity_observation",
]
