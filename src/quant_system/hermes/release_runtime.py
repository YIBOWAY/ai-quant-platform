"""Production probes for the durable Agent v0.2 release gate.

The gate consumes observations only. This module binds those observations to
the actual clean Platform/HQA/Hermes checkouts, the live PostgreSQL schema and
runtime role, one sealed local evidence file, and a fresh loopback Hermes
capability response.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quant_system.config.settings import Settings
from quant_system.hermes.connector_liveness import (
    connector_liveness_runtime_security_is_ready_on_connection,
)
from quant_system.hermes.effective_release_gate import (
    EffectiveReleaseDecision,
    EffectiveReleaseGate,
    HermesDurableCapabilityObservation,
    LocalReleaseFlags,
    ReleaseEvidenceObservation,
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
_EVIDENCE_CONTRACT = "agent-v0.2-release-evidence/v1"
_RUNTIME_NAMES = ("platform", "hqa", "hermes")
_REQUIRED_TEST_SUITES = frozenset(
    {"platform", "hqa", "hermes_focused", "frontend"}
)
_REQUIRED_REAL_FLOWS = frozenset(
    {
        "web_chat_multi_turn",
        "hermes_restart_recovery",
        "exact_message_fork",
        "paper_factor_gate_1_2_3",
    }
)
_HEX_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleaseRuntimeProbeError(RuntimeError):
    """A runtime identity/evidence observation could not be trusted."""


def _runtime_digest_from_commit(logical_name: str, commit: str) -> str:
    if _LOGICAL_NAME_RE.fullmatch(logical_name) is None:
        raise ReleaseRuntimeProbeError("runtime logical name is invalid")
    if _HEX_COMMIT_RE.fullmatch(commit) is None:
        raise ReleaseRuntimeProbeError("runtime commit identity is invalid")
    payload = b"agent-v0.2-runtime\x00" + logical_name.encode("ascii")
    payload += b"\x00commit\x00" + commit.encode("ascii") + b"\x00"
    return hashlib.sha256(payload).hexdigest()


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
    return _runtime_digest_from_commit(logical_name, commit.decode("ascii"))


def _read_bounded_owned_file(path: Path) -> bytes:
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
        chunks: list[bytes] = []
        remaining = _MAX_EVIDENCE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > _MAX_EVIDENCE_BYTES:
            raise ReleaseRuntimeProbeError(
                "release evidence must be nonempty and bounded"
            )
        return content
    finally:
        os.close(fd)


def _json_object_without_duplicates(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseRuntimeProbeError(
                "release evidence contract contains duplicate keys"
            )
        result[key] = value
    return result


def _exact_mapping(
    value: object,
    *,
    keys: frozenset[str],
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ReleaseRuntimeProbeError(
            f"release evidence contract field {field} is invalid"
        )
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReleaseRuntimeProbeError(
            f"release evidence contract field {field} is invalid"
        )
    return value


def release_evidence_observation(path: Path) -> ReleaseEvidenceObservation:
    """Validate and bind the complete Agent v0.2 release evidence manifest."""

    content = _read_bounded_owned_file(path)
    try:
        decoded = content.decode("utf-8")
        payload = json.loads(
            decoded,
            object_pairs_hook=_json_object_without_duplicates,
        )
    except ReleaseRuntimeProbeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReleaseRuntimeProbeError(
            "release evidence contract must be valid UTF-8 JSON"
        ) from exc

    root = _exact_mapping(
        payload,
        keys=frozenset({"contract", "runtime", "tests", "real_flows", "safety"}),
        field="root",
    )
    if root["contract"] != _EVIDENCE_CONTRACT:
        raise ReleaseRuntimeProbeError(
            "release evidence contract version is invalid"
        )

    runtime = _exact_mapping(
        root["runtime"],
        keys=frozenset(_RUNTIME_NAMES),
        field="runtime",
    )
    runtime_digests: dict[str, str] = {}
    for logical_name in _RUNTIME_NAMES:
        item = _exact_mapping(
            runtime[logical_name],
            keys=frozenset({"commit", "digest"}),
            field=f"runtime.{logical_name}",
        )
        commit = item["commit"]
        digest = item["digest"]
        if not isinstance(commit, str) or _HEX_COMMIT_RE.fullmatch(commit) is None:
            raise ReleaseRuntimeProbeError(
                f"release evidence contract runtime.{logical_name}.commit is invalid"
            )
        if not isinstance(digest, str) or _HEX_DIGEST_RE.fullmatch(digest) is None:
            raise ReleaseRuntimeProbeError(
                f"release evidence contract runtime.{logical_name}.digest is invalid"
            )
        if digest != _runtime_digest_from_commit(logical_name, commit):
            raise ReleaseRuntimeProbeError(
                f"release evidence contract runtime.{logical_name} is inconsistent"
            )
        runtime_digests[logical_name] = digest

    tests = _exact_mapping(
        root["tests"],
        keys=frozenset({"passed", "suites"}),
        field="tests",
    )
    if tests["passed"] is not True or not isinstance(tests["suites"], list):
        raise ReleaseRuntimeProbeError(
            "release evidence contract tests did not pass"
        )
    suite_names: set[str] = set()
    for index, raw_suite in enumerate(tests["suites"]):
        suite = _exact_mapping(
            raw_suite,
            keys=frozenset({"name", "passed", "failed", "skipped"}),
            field=f"tests.suites[{index}]",
        )
        name = suite["name"]
        if not isinstance(name, str) or not name or name in suite_names:
            raise ReleaseRuntimeProbeError(
                "release evidence contract test suite identity is invalid"
            )
        suite_names.add(name)
        passed = _nonnegative_int(
            suite["passed"],
            field=f"tests.suites[{index}].passed",
        )
        failed = _nonnegative_int(
            suite["failed"],
            field=f"tests.suites[{index}].failed",
        )
        _nonnegative_int(
            suite["skipped"],
            field=f"tests.suites[{index}].skipped",
        )
        if passed < 1 or failed != 0:
            raise ReleaseRuntimeProbeError(
                "release evidence contract tests did not pass"
            )
    if not _REQUIRED_TEST_SUITES.issubset(suite_names):
        raise ReleaseRuntimeProbeError(
            "release evidence contract required test suites are missing"
        )

    real_flows = _exact_mapping(
        root["real_flows"],
        keys=frozenset({"passed", "flows"}),
        field="real_flows",
    )
    if (
        real_flows["passed"] is not True
        or not isinstance(real_flows["flows"], list)
    ):
        raise ReleaseRuntimeProbeError(
            "release evidence contract real flows did not pass"
        )
    flow_names: set[str] = set()
    for index, raw_flow in enumerate(real_flows["flows"]):
        flow = _exact_mapping(
            raw_flow,
            keys=frozenset({"name", "passed", "receipt_digest"}),
            field=f"real_flows.flows[{index}]",
        )
        name = flow["name"]
        receipt_digest = flow["receipt_digest"]
        if (
            not isinstance(name, str)
            or not name
            or name in flow_names
            or flow["passed"] is not True
            or not isinstance(receipt_digest, str)
            or _HEX_DIGEST_RE.fullmatch(receipt_digest) is None
        ):
            raise ReleaseRuntimeProbeError(
                "release evidence contract real flow receipt is invalid"
            )
        flow_names.add(name)
    if not _REQUIRED_REAL_FLOWS.issubset(flow_names):
        raise ReleaseRuntimeProbeError(
            "release evidence contract required real flows are missing"
        )

    safety = _exact_mapping(
        root["safety"],
        keys=frozenset(
            {"orders_created", "kill_switch", "live_trading_enabled"}
        ),
        field="safety",
    )
    if (
        _nonnegative_int(
            safety["orders_created"],
            field="safety.orders_created",
        )
        != 0
        or safety["kill_switch"] is not True
        or safety["live_trading_enabled"] is not False
    ):
        raise ReleaseRuntimeProbeError(
            "release evidence contract safety facts are unsafe"
        )

    return ReleaseEvidenceObservation(
        digest=hashlib.sha256(content).hexdigest(),
        platform_runtime_digest=runtime_digests["platform"],
        hqa_runtime_digest=runtime_digests["hqa"],
        hermes_runtime_digest=runtime_digests["hermes"],
    )


def file_sha256(path: Path) -> str:
    """Return the digest of one fully validated release evidence manifest."""

    return release_evidence_observation(path).digest


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


def restricted_runtime_security_ready(settings: Settings) -> bool:
    """Verify every Agent v0.2 write authority under the constrained login."""

    try:
        if not hermes_runtime_security_ready(settings):
            return False
        if not release_authority_runtime_security_ready(settings):
            return False
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as connection:
            return connector_liveness_runtime_security_is_ready_on_connection(
                connection
            )
    except Exception:  # noqa: BLE001 - any observation uncertainty closes writes
        return False


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
            hermes_gateway_enabled=settings.hermes_gateway.enabled,
            kill_switch_enabled=settings.safety.kill_switch,
            live_trading_enabled=settings.safety.live_trading_enabled,
        ),
        runtime_identity_probe=lambda: runtime_identity_observation(settings),
        database_schema_fingerprint_probe=lambda: schema_fingerprint(
            get_database(settings)
        ),
        release_evidence_probe=lambda: release_evidence_observation(
            settings.agent_v02_release.evidence_file
        ),
        runtime_role_readiness_probe=lambda: restricted_runtime_security_ready(
            settings
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
    "ReleaseEvidenceObservation",
    "build_effective_release_gate",
    "current_release_decision",
    "file_sha256",
    "git_runtime_digest",
    "platform_runtime_root",
    "release_evidence_observation",
    "restricted_runtime_security_ready",
    "runtime_identity_observation",
]
