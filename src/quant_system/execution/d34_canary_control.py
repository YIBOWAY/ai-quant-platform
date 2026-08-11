"""Owner controls for D-34 paper canaries.

The local sleeve is changed before the registry row.  That ordering is
intentional: an interrupted operation may need reconciliation, but it cannot
leave a supposedly stopped canary able to submit new paper orders.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategySleeveStatus,
)
from quant_system.hermes.d34_registry_authority import (
    D34Canary,
    RegistryAuthorityError,
    RegistryAuthorityPort,
)


class D34CanaryControlError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)


def _value(canary: D34Canary | Mapping[str, object], field: str) -> Any:
    if isinstance(canary, Mapping):
        return canary[field]
    return getattr(canary, field)


class D34CanaryController:
    """Converge registry state and the real paper sleeve without flattening."""

    _TARGETS = {"pause": "paused", "demote": "demoted", "rollback": "rolled_back"}

    def __init__(self, *, registry: RegistryAuthorityPort, sleeve_storage: Any) -> None:
        self.registry = registry
        self.sleeve_storage = sleeve_storage
        self.sleeves = PaperStrategySleeveService(sleeve_storage)

    def _apply_sleeve_action(
        self,
        canary: D34Canary | Mapping[str, object],
        *,
        action: str,
        reason: str,
    ) -> None:
        sleeve_id = str(_value(canary, "sleeve_id"))
        artifact_id = str(_value(canary, "artifact_id"))
        try:
            with self.sleeve_storage.mutation_lock():
                sleeve = self.sleeve_storage.load_sleeve(sleeve_id)
                if (
                    sleeve.metadata.get("automation_source") != "d34"
                    or sleeve.metadata.get("artifact_id") != artifact_id
                    or sleeve.metadata.get("promotion_scope") != "paper_only"
                ):
                    raise D34CanaryControlError("d34_canary_lineage_invalid")
                if action == "pause":
                    if sleeve.status != StrategySleeveStatus.PAUSED:
                        self.sleeves.pause_sleeve(sleeve)
                elif sleeve.status != StrategySleeveStatus.QUARANTINED_HOLD:
                    self.sleeves.quarantine_sleeve(sleeve, reason=reason)
        except D34CanaryControlError:
            raise
        except FileNotFoundError as exc:
            raise D34CanaryControlError("d34_canary_sleeve_missing") from exc
        except (OSError, TimeoutError, ValueError) as exc:
            raise D34CanaryControlError("d34_canary_sleeve_conflict") from exc

    def transition(
        self,
        *,
        canary_id: str,
        action: str,
        expected_version: int,
        reason: str,
    ) -> D34Canary | Mapping[str, object]:
        if (
            action not in self._TARGETS
            or not canary_id.startswith("canary-")
            or expected_version < 1
            or not 1 <= len(reason.strip()) <= 1000
        ):
            raise D34CanaryControlError("d34_canary_control_validation")
        current = self.registry.get_canary(canary_id)
        observed_version = int(_value(current, "version"))
        target = self._TARGETS[action]
        idempotent_replay = (
            str(_value(current, "status")) == target
            and observed_version == expected_version + 1
        )
        if observed_version != expected_version and not idempotent_replay:
            raise D34CanaryControlError("d34_canary_control_conflict")

        self._apply_sleeve_action(current, action=action, reason=reason.strip())
        if idempotent_replay:
            return current
        try:
            return self.registry.transition_canary(
                canary_id=canary_id,
                action=action,
                expected_version=expected_version,
                reason=reason.strip(),
            )
        except RegistryAuthorityError as exc:
            if exc.code == "d34_registry_conflict":
                observed = self.registry.get_canary(canary_id)
                if (
                    str(_value(observed, "status")) == target
                    and int(_value(observed, "version")) == expected_version + 1
                ):
                    return observed
            raise

    def rollback_all(self, *, workspace_id: str, reason: str) -> dict[str, object]:
        if not workspace_id or not 1 <= len(reason.strip()) <= 1000:
            raise D34CanaryControlError("d34_canary_control_validation")
        active = [
            canary
            for canary in self.registry.list_canaries(workspace_id=workspace_id, limit=100)
            if str(_value(canary, "status")) in {"provisioning", "running", "paused"}
        ]
        canary_ids: list[str] = []
        for canary in sorted(active, key=lambda item: str(_value(item, "canary_id"))):
            canary_id = str(_value(canary, "canary_id"))
            self.transition(
                canary_id=canary_id,
                action="rollback",
                expected_version=int(_value(canary, "version")),
                reason=reason.strip(),
            )
            canary_ids.append(canary_id)
        return {"transitioned": len(canary_ids), "canary_ids": canary_ids}


__all__ = ["D34CanaryControlError", "D34CanaryController"]
