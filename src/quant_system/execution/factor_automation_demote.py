"""Recoverable demotion state machine for automated paper sleeves."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Set

from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategySleeve,
    StrategySleeveStatus,
)

_REQUEST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


class FactorAutomationDemoteError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class FactorAutomationDemoteService:
    def __init__(self, storage) -> None:
        self.storage = storage
        self.sleeves = PaperStrategySleeveService(storage)

    @staticmethod
    def _require_auto(sleeve: StrategySleeve) -> tuple[str, str]:
        factor_id = sleeve.metadata.get("factor_id")
        manifest_digest = sleeve.metadata.get("manifest_digest")
        if (
            sleeve.metadata.get("automation_managed") is not True
            or type(factor_id) is not str
            or not factor_id
            or type(manifest_digest) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", manifest_digest)
        ):
            raise FactorAutomationDemoteError("not_automation_managed")
        return factor_id, manifest_digest

    def demote(
        self,
        sleeve: StrategySleeve,
        *,
        request_id: str,
        reason: str,
    ) -> StrategySleeve:
        if _REQUEST_RE.fullmatch(request_id) is None or not reason.strip():
            raise FactorAutomationDemoteError("invalid_demote_request")
        factor_id, manifest_digest = self._require_auto(sleeve)
        with self.storage.mutation_lock():
            existing = self.storage.load_demoted_state(sleeve.sleeve_id)
            if existing is not None:
                if (
                    existing.get("request_id") == request_id
                    and existing.get("reason") == reason
                    and existing.get("factor_id") == factor_id
                    and existing.get("manifest_digest") == manifest_digest
                ):
                    return self.storage.load_sleeve(sleeve.sleeve_id)
                raise FactorAutomationDemoteError("demote_idempotency_conflict")
            sleeve = self.sleeves.quarantine_sleeve(sleeve, reason=reason)
            self.storage.save_demoted_state(
                sleeve.sleeve_id,
                {
                    "schema_version": 1,
                    "request_id": request_id,
                    "sleeve_id": sleeve.sleeve_id,
                    "factor_id": factor_id,
                    "manifest_digest": manifest_digest,
                    "reason": reason,
                    "status": StrategySleeveStatus.QUARANTINED_HOLD.value,
                },
            )
            return sleeve

    def complete(
        self,
        sleeve: StrategySleeve,
        *,
        outcome: StrategySleeveStatus,
    ) -> StrategySleeve:
        self._require_auto(sleeve)
        with self.storage.mutation_lock():
            marker = self.storage.load_demoted_state(sleeve.sleeve_id)
            if marker is None or marker.get("status") != "quarantined_hold":
                raise FactorAutomationDemoteError("quarantine_marker_missing")
            lots = self.storage.load_sleeve_lots(sleeve.sleeve_id)
            if outcome == StrategySleeveStatus.FLATTENED and lots:
                raise FactorAutomationDemoteError("flatten_positions_remaining")
            sleeve = self.sleeves.complete_demote(sleeve, outcome=outcome)
            marker["status"] = StrategySleeveStatus.DEMOTED_COMPLETE.value
            marker["outcome"] = outcome.value
            self.storage.save_demoted_state(sleeve.sleeve_id, marker)
            return sleeve

    def quarantine_missing_factors(
        self,
        *,
        registered_factor_ids: Set[str],
    ) -> list[StrategySleeve]:
        changed: list[StrategySleeve] = []
        for sleeve in self.storage.list_sleeves():
            if sleeve.metadata.get("automation_managed") is not True:
                continue
            factor_id = sleeve.metadata.get("factor_id")
            if type(factor_id) is not str or factor_id in registered_factor_ids:
                continue
            if sleeve.status in {
                StrategySleeveStatus.QUARANTINED_HOLD,
                StrategySleeveStatus.DEMOTED_COMPLETE,
            }:
                continue
            manifest = str(sleeve.metadata.get("manifest_digest", ""))
            request_id = "factor-missing:" + hashlib.sha256(
                f"{sleeve.sleeve_id}:{manifest}".encode()
            ).hexdigest()
            changed.append(
                self.demote(
                    sleeve,
                    request_id=request_id,
                    reason="factor_missing",
                )
            )
        return changed


__all__ = [
    "FactorAutomationDemoteError",
    "FactorAutomationDemoteService",
]
