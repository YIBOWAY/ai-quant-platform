"""Fail-closed composition of the effective Agent v0.2 release gate.

Local settings are *deny-only*: turning either flag off immediately closes the
effective gate, while turning both on grants nothing without independently
observed runtime identities, PostgreSQL security/schema readiness, a fresh
grounded Hermes durable capability probe, an active release stamp, and an
exactly bound open public cutover.

Rollback methods intentionally do not live behind this gate. Callers use
``ReleaseAuthority.close_public_cutover`` / ``close_release_stamp`` directly,
so loss of readiness can never trap an unsafe open flag.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from quant_system.hermes.compatibility_contract import (
    load_hermes_compatibility_contract,
)
from quant_system.hermes.release_authority import (
    PublicCutoverRecord,
    ReleaseAuthorityError,
    ReleaseStampRecord,
)

_DIGEST_LENGTH = 64
_COMPATIBILITY = load_hermes_compatibility_contract()
_REQUIRED_FEATURES = _COMPATIBILITY.required_bool_features
_REQUIRED_DURABLE = _COMPATIBILITY.required_durable


class ReleaseAuthorityReadPort(Protocol):
    def active_release_stamp(
        self,
        workspace_id: str,
    ) -> ReleaseStampRecord | None: ...

    def open_public_cutover(
        self,
        workspace_id: str,
    ) -> PublicCutoverRecord | None: ...

    def current_event_cursor(self, workspace_id: str) -> int: ...


@dataclass(frozen=True)
class LocalReleaseFlags:
    mutation_enabled: bool
    composer_open: bool
    hermes_gateway_enabled: bool
    kill_switch_enabled: bool
    live_trading_enabled: bool


@dataclass(frozen=True)
class RuntimeIdentityObservation:
    platform_runtime_digest: str
    hqa_runtime_digest: str
    hermes_runtime_digest: str


@dataclass(frozen=True)
class ReleaseEvidenceObservation:
    """Validated evidence identity and its three runtime bindings."""

    digest: str
    platform_runtime_digest: str
    hqa_runtime_digest: str
    hermes_runtime_digest: str


@dataclass(frozen=True)
class HermesDurableCapabilityObservation:
    runtime_digest: str
    observed_at: datetime
    payload: Mapping[str, object]


@dataclass(frozen=True)
class EffectiveReleaseDecision:
    workspace_id: str
    ready: bool
    release_authorized: bool
    public_write_authorized: bool
    chat_write_ready: bool
    blockers: tuple[str, ...]
    checked_at: datetime
    release_stamp_id: str | None
    release_digest: str | None
    public_cutover_id: str | None
    cutover_digest: str | None
    event_cursor: int
    local_mutation_requested: bool
    local_composer_requested: bool

    def to_public_dict(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "ready": self.ready,
            "release_authorized": self.release_authorized,
            "public_write_authorized": self.public_write_authorized,
            "chat_write_ready": self.chat_write_ready,
            "blockers": list(self.blockers),
            "checked_at": self.checked_at.astimezone(UTC).isoformat().replace(
                "+00:00", "Z"
            ),
            "release_stamp_id": self.release_stamp_id,
            "release_digest": self.release_digest,
            "public_cutover_id": self.public_cutover_id,
            "cutover_digest": self.cutover_digest,
            "event_cursor": self.event_cursor,
            "local_mutation_requested": self.local_mutation_requested,
            "local_composer_requested": self.local_composer_requested,
        }


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_LENGTH
        and all(char in "0123456789abcdef" for char in value)
    )


class EffectiveReleaseGate:
    """Compose independent facts into one reusable release decision."""

    def __init__(
        self,
        *,
        authority: ReleaseAuthorityReadPort,
        local_flags_probe: Callable[[], LocalReleaseFlags],
        runtime_identity_probe: Callable[[], RuntimeIdentityObservation],
        database_schema_fingerprint_probe: Callable[[], str],
        release_evidence_probe: Callable[[], ReleaseEvidenceObservation],
        runtime_role_readiness_probe: Callable[[], bool],
        authority_schema_readiness_probe: Callable[[], bool],
        hermes_capability_probe: Callable[
            [], HermesDurableCapabilityObservation
        ],
        now: Callable[[], datetime] | None = None,
        capability_max_age: timedelta = timedelta(seconds=30),
        capability_future_skew: timedelta = timedelta(seconds=5),
    ) -> None:
        if not timedelta(seconds=1) <= capability_max_age <= timedelta(minutes=5):
            raise ValueError("capability_max_age must be between 1s and 5m")
        if not timedelta(0) <= capability_future_skew <= timedelta(seconds=30):
            raise ValueError("capability_future_skew must be between 0s and 30s")
        self._authority = authority
        self._local_flags_probe = local_flags_probe
        self._runtime_identity_probe = runtime_identity_probe
        self._schema_fingerprint_probe = database_schema_fingerprint_probe
        self._release_evidence_probe = release_evidence_probe
        self._runtime_role_readiness_probe = runtime_role_readiness_probe
        self._authority_schema_readiness_probe = authority_schema_readiness_probe
        self._hermes_capability_probe = hermes_capability_probe
        self._now = now or (lambda: datetime.now(UTC))
        self._capability_max_age = capability_max_age
        self._capability_future_skew = capability_future_skew

    @staticmethod
    def _append(blockers: list[str], blocker: str) -> None:
        if blocker not in blockers:
            blockers.append(blocker)

    def _check_capabilities(
        self,
        observation: HermesDurableCapabilityObservation,
        *,
        stamp: ReleaseStampRecord | None,
        clock: datetime,
        blockers: list[str],
    ) -> None:
        if not _is_digest(observation.runtime_digest):
            self._append(blockers, "hermes_runtime_identity_unavailable")
        elif (
            stamp is not None
            and observation.runtime_digest != stamp.hermes_runtime_digest
        ):
            self._append(blockers, "hermes_runtime_identity_mismatch")

        observed_at = observation.observed_at
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            self._append(blockers, "hermes_durable_capability_clock_invalid")
        else:
            observed_at = observed_at.astimezone(UTC)
            if observed_at > clock + self._capability_future_skew:
                self._append(blockers, "hermes_durable_capability_clock_invalid")
            elif clock - observed_at > self._capability_max_age:
                self._append(blockers, "hermes_durable_capability_stale")

        payload = observation.payload
        contract_version = payload.get("contract_version")
        if (
            isinstance(contract_version, bool)
            or not isinstance(contract_version, int)
            or contract_version < _COMPATIBILITY.hermes_contract_version_min
        ):
            self._append(blockers, "hermes_durable_contract_unavailable")

        features = payload.get("features")
        for name in _REQUIRED_FEATURES:
            if not isinstance(features, Mapping) or features.get(name) is not True:
                self._append(blockers, f"hermes_feature_{name}_unready")

        durable = payload.get("durable")
        for name in _REQUIRED_DURABLE:
            fact = durable.get(name) if isinstance(durable, Mapping) else None
            if (
                not isinstance(fact, Mapping)
                or fact.get("supported") is not True
                or fact.get("grounded") is not True
                or fact.get("evidence")
                != _COMPATIBILITY.durable_evidence_template.format(
                    capability=name
                )
            ):
                self._append(blockers, f"hermes_durable_{name}_unready")

        managed_contract = payload.get("managed_session_contract")
        if (
            not isinstance(managed_contract, Mapping)
            or managed_contract.get("history_authority")
            != _COMPATIBILITY.required_exact_features[
                "managed_run_history_authority"
            ]
        ):
            self._append(
                blockers,
                "hermes_managed_session_history_authority_unready",
            )
        if (
            not isinstance(managed_contract, Mapping)
            or managed_contract.get("fork_mode")
            != _COMPATIBILITY.required_exact_features[
                "managed_session_fork_mode"
            ]
        ):
            self._append(
                blockers,
                "hermes_managed_session_fork_mode_unready",
            )

    def evaluate(self, workspace_id: str) -> EffectiveReleaseDecision:
        clock = self._now()
        if clock.tzinfo is None or clock.utcoffset() is None:
            raise ValueError("gate clock must be timezone-aware")
        clock = clock.astimezone(UTC)
        blockers: list[str] = []

        try:
            flags = self._local_flags_probe()
        except Exception:  # noqa: BLE001 - a failed probe is a closed gate
            flags = LocalReleaseFlags(
                mutation_enabled=False,
                composer_open=False,
                hermes_gateway_enabled=False,
                kill_switch_enabled=False,
                live_trading_enabled=True,
            )
            self._append(blockers, "local_release_flags_unavailable")
        if flags.mutation_enabled is not True:
            self._append(blockers, "local_mutation_disabled")
        if flags.composer_open is not True:
            self._append(blockers, "local_composer_closed")
        if flags.hermes_gateway_enabled is not True:
            self._append(blockers, "hermes_gateway_disabled")
        if flags.kill_switch_enabled is not True:
            self._append(blockers, "trading_kill_switch_disabled")
        if flags.live_trading_enabled is not False:
            self._append(blockers, "live_trading_enabled")

        try:
            authority_schema_ready = self._authority_schema_readiness_probe()
        except Exception:  # noqa: BLE001 - a failed probe is a closed gate
            authority_schema_ready = False
        if authority_schema_ready is not True:
            self._append(blockers, "release_authority_schema_unready")

        try:
            runtime_role_ready = self._runtime_role_readiness_probe()
        except Exception:  # noqa: BLE001 - a failed probe is a closed gate
            runtime_role_ready = False
        if runtime_role_ready is not True:
            self._append(blockers, "restricted_runtime_role_unready")

        try:
            current_schema = self._schema_fingerprint_probe()
        except Exception:  # noqa: BLE001 - a failed probe is a closed gate
            current_schema = "<unavailable>"
        if not _is_digest(current_schema):
            self._append(blockers, "database_schema_fingerprint_unavailable")

        try:
            evidence = self._release_evidence_probe()
        except Exception:  # noqa: BLE001 - a failed probe is a closed gate
            evidence = None
        if not isinstance(evidence, ReleaseEvidenceObservation):
            evidence = None
        current_evidence = (
            evidence.digest if evidence is not None else "<unavailable>"
        )
        evidence_runtime_fields = (
            (
                "platform",
                (
                    evidence.platform_runtime_digest
                    if evidence is not None
                    else None
                ),
            ),
            (
                "hqa",
                evidence.hqa_runtime_digest if evidence is not None else None,
            ),
            (
                "hermes",
                (
                    evidence.hermes_runtime_digest
                    if evidence is not None
                    else None
                ),
            ),
        )
        if not _is_digest(current_evidence) or any(
            not _is_digest(value) for _, value in evidence_runtime_fields
        ):
            self._append(blockers, "release_evidence_digest_unavailable")

        try:
            identities = self._runtime_identity_probe()
        except Exception:  # noqa: BLE001 - a failed probe is a closed gate
            identities = None
            self._append(blockers, "runtime_identity_observation_unavailable")
        if identities is not None and evidence is not None:
            evidence_runtime_bindings = (
                (
                    "platform",
                    evidence.platform_runtime_digest,
                    identities.platform_runtime_digest,
                ),
                (
                    "hqa",
                    evidence.hqa_runtime_digest,
                    identities.hqa_runtime_digest,
                ),
                (
                    "hermes",
                    evidence.hermes_runtime_digest,
                    identities.hermes_runtime_digest,
                ),
            )
            for name, claimed, observed in evidence_runtime_bindings:
                if _is_digest(claimed) and claimed != observed:
                    self._append(
                        blockers,
                        f"release_evidence_{name}_runtime_mismatch",
                    )

        try:
            stamp = self._authority.active_release_stamp(workspace_id)
        except (ReleaseAuthorityError, Exception):  # noqa: BLE001
            stamp = None
            self._append(blockers, "release_authority_unavailable")
        if stamp is None:
            self._append(blockers, "active_release_stamp_missing")

        if stamp is not None:
            if stamp.status != "active" or stamp.route != "/hermes":
                self._append(blockers, "active_release_stamp_invalid")
            if (
                _is_digest(current_schema)
                and current_schema != stamp.database_schema_fingerprint
            ):
                self._append(blockers, "database_schema_fingerprint_mismatch")
            if (
                _is_digest(current_evidence)
                and current_evidence != stamp.evidence_digest
            ):
                self._append(blockers, "release_evidence_digest_mismatch")
            if identities is not None:
                identity_fields = (
                    (
                        "platform",
                        identities.platform_runtime_digest,
                        stamp.platform_runtime_digest,
                    ),
                    ("hqa", identities.hqa_runtime_digest, stamp.hqa_runtime_digest),
                    (
                        "hermes",
                        identities.hermes_runtime_digest,
                        stamp.hermes_runtime_digest,
                    ),
                )
                for name, observed, expected in identity_fields:
                    if not _is_digest(observed):
                        self._append(
                            blockers, f"{name}_runtime_identity_unavailable"
                        )
                    elif observed != expected:
                        self._append(
                            blockers, f"{name}_runtime_identity_mismatch"
                        )

        try:
            capability = self._hermes_capability_probe()
        except Exception:  # noqa: BLE001 - a failed probe is a closed gate
            capability = None
            self._append(blockers, "hermes_durable_capability_unavailable")
        if capability is not None:
            self._check_capabilities(
                capability,
                stamp=stamp,
                clock=clock,
                blockers=blockers,
            )

        try:
            cutover = self._authority.open_public_cutover(workspace_id)
        except (ReleaseAuthorityError, Exception):  # noqa: BLE001
            cutover = None
            self._append(blockers, "release_authority_unavailable")
        if cutover is None:
            self._append(blockers, "open_public_cutover_missing")
        elif (
            stamp is None
            or cutover.status != "open"
            or cutover.route != "/hermes"
            or cutover.workspace_id != stamp.workspace_id
            or cutover.stamp_id != stamp.stamp_id
            or cutover.release_digest != stamp.release_digest
        ):
            self._append(blockers, "public_cutover_release_binding_mismatch")

        try:
            cursor = self._authority.current_event_cursor(workspace_id)
        except (ReleaseAuthorityError, Exception):  # noqa: BLE001
            cursor = 0
            self._append(blockers, "release_event_cursor_unavailable")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            cursor = 0
            self._append(blockers, "release_event_cursor_invalid")

        ready = not blockers
        return EffectiveReleaseDecision(
            workspace_id=workspace_id,
            ready=ready,
            release_authorized=ready,
            public_write_authorized=ready,
            chat_write_ready=ready,
            blockers=tuple(blockers),
            checked_at=clock,
            release_stamp_id=stamp.stamp_id if stamp is not None else None,
            release_digest=stamp.release_digest if stamp is not None else None,
            public_cutover_id=cutover.cutover_id if cutover is not None else None,
            cutover_digest=cutover.cutover_digest if cutover is not None else None,
            event_cursor=cursor,
            local_mutation_requested=flags.mutation_enabled is True,
            local_composer_requested=flags.composer_open is True,
        )


__all__ = [
    "EffectiveReleaseDecision",
    "EffectiveReleaseGate",
    "HermesDurableCapabilityObservation",
    "LocalReleaseFlags",
    "ReleaseEvidenceObservation",
    "ReleaseAuthorityReadPort",
    "RuntimeIdentityObservation",
]
