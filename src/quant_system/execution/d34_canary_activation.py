"""Crash-recoverable activation of a real D-34 paper canary sleeve."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from quant_system.d34.artifact_factor import load_d34_paper_factor_registry
from quant_system.d34.research_driver import D34_TARGET_GROSS_EXPOSURE
from quant_system.execution.factor_automation_safety import admit_auto_sleeve
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategyConfig,
    StrategySleeve,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.hermes.d34_registry_authority import (
    D34Artifact,
    ProvisionCanaryCommand,
    RegistryAuthorityPort,
)


class D34CanaryActivationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class D34CanaryActivationRequest:
    artifact: D34Artifact
    factor_id: str
    artifact_code_path: Path
    universe: tuple[str, ...]
    provider: str
    nav: Decimal
    account_updated_at: str
    prices: Mapping[str, float]
    price_metadata: Mapping[str, Mapping[str, str | None]]


def _ids(artifact_id: str) -> tuple[str, str]:
    token = hashlib.sha256(artifact_id.encode("utf-8")).hexdigest()[:20]
    return f"strategy-config-d34-{token}", f"sleeve-d34-{token}"


def _same_config(left: StrategyConfig, right: StrategyConfig) -> bool:
    left_value, right_value = left.model_dump(mode="json"), right.model_dump(mode="json")
    for field in ("created_at", "updated_at"):
        left_value.pop(field, None)
        right_value.pop(field, None)
    return left_value == right_value


def _expected_config(
    request: D34CanaryActivationRequest,
    *,
    strategy_config_id: str,
    lookback: int,
) -> StrategyConfig:
    artifact = request.artifact
    metadata = {
        "automation_managed": True,
        "automation_source": "d34",
        "artifact_id": artifact.artifact_id,
        "mandate_id": artifact.mandate_id,
        "workspace_id": artifact.workspace_id,
        "factor_id": request.factor_id,
        "artifact_code_path": str(request.artifact_code_path.resolve()),
        "candidate_code_digest": artifact.candidate_code_digest,
        "policy_digest": artifact.policy_digest,
        "comparison_digest": artifact.comparison_digest,
        "promotion_scope": "paper_only",
        "reviewer": "auto",
        "research_lookback": lookback,
        "research_risk_degree": D34_TARGET_GROSS_EXPOSURE,
        "research_top_k": 1,
    }
    return StrategyConfig.create(
        strategy_config_id=strategy_config_id,
        name=f"D-34 paper canary · {request.factor_id}",
        description="Digest-bound D-34 Artifact Registry paper canary.",
        strategy_id="cross_sectional_top_n",
        universe_id=f"d34:{artifact.artifact_id}",
        symbols=list(request.universe),
        factor_ids=[request.factor_id],
        weights={request.factor_id: 1.0},
        lookback=lookback,
        top_n=1,
        rebalance_frequency="daily",
        max_weight_per_symbol=D34_TARGET_GROSS_EXPOSURE,
        min_order_value=100.0,
        data_provider=request.provider,
        execution_timing="next_open",
        tags=["d34", "automation", "paper_only", "canary"],
        metadata=metadata,
    )


def _validate(request: D34CanaryActivationRequest) -> int:
    artifact = request.artifact
    if (
        artifact.qualification_scope != "paper_only"
        or artifact.status not in {"qualified", "canary_active"}
        or request.provider != "futu"
        or not request.universe
        or len(set(request.universe)) != len(request.universe)
        or any(symbol != symbol.upper() or not symbol for symbol in request.universe)
        or request.nav <= 0
        or any(
            not math.isfinite(float(value)) or float(value) <= 0
            for value in request.prices.values()
        )
    ):
        raise D34CanaryActivationError("d34_canary_request_invalid")
    try:
        factor_registry = load_d34_paper_factor_registry(
            code_path=request.artifact_code_path,
            expected_code_digest=artifact.candidate_code_digest,
            expected_factor_id=request.factor_id,
        )
    except ValueError as exc:
        raise D34CanaryActivationError(str(exc)) from exc
    return factor_registry.create(request.factor_id).lookback


def activate_d34_paper_canary(
    request: D34CanaryActivationRequest,
    *,
    account_storage: Any,
    sleeve_storage: Any,
    registry: RegistryAuthorityPort,
) -> tuple[StrategySleeve, object]:
    """Create the file/account sleeve once, then converge the DB canary."""
    lookback = _validate(request)
    config_id, sleeve_id = _ids(request.artifact.artifact_id)
    expected_config = _expected_config(
        request,
        strategy_config_id=config_id,
        lookback=lookback,
    )
    service = PaperStrategySleeveService(sleeve_storage)

    with account_storage.mutation_lock(), sleeve_storage.mutation_lock():
        account = account_storage.load()
        if account is None:
            raise D34CanaryActivationError("paper_account_missing")
        sleeve_storage.reconcile_pending_sleeves(account)
        try:
            existing = sleeve_storage.load_sleeve(sleeve_id)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            try:
                observed_config = sleeve_storage.load_strategy_config(config_id)
            except FileNotFoundError as exc:
                raise D34CanaryActivationError(
                    "existing_d34_sleeve_lineage_invalid"
                ) from exc
            if (
                not _same_config(observed_config, expected_config)
                or existing.metadata.get("artifact_id") != request.artifact.artifact_id
                or account.sleeve_cash.get(sleeve_id) != existing.cash
            ):
                raise D34CanaryActivationError("existing_d34_sleeve_lineage_invalid")
            sleeve = existing
        else:
            if request.account_updated_at != account.updated_at:
                raise D34CanaryActivationError("paper_account_valuation_stale")
            admission = admit_auto_sleeve(
                nav=float(request.nav),
                existing_sleeves=sleeve_storage.list_sleeves(),
                factor_id=request.factor_id,
                manifest_digest=request.artifact.candidate_code_digest,
                automation_policy_digest=request.artifact.policy_digest,
            )
            metadata = {
                **admission.metadata,
                **expected_config.metadata,
                "automation_source": "d34",
                "artifact_id": request.artifact.artifact_id,
                "mandate_id": request.artifact.mandate_id,
                "d34_activation_state": "awaiting_registry",
            }
            sleeve_storage.save_strategy_config(expected_config)
            sleeve = service.create_sleeve(
                account,
                config=expected_config,
                mode=StrategySleeveMode.ALLOCATED,
                allocated_cash=admission.allocated_cash,
                metadata=metadata,
                sleeve_id=sleeve_id,
            )
            paused_at = datetime.now(UTC).isoformat()
            sleeve.status = StrategySleeveStatus.PAUSED
            sleeve.paused_at = paused_at
            sleeve.updated_at = paused_at
            sleeve_storage.save_pending_sleeve(sleeve)
            try:
                account_storage.save(
                    account,
                    prices=dict(request.prices),
                    price_metadata={
                        symbol: dict(value)
                        for symbol, value in request.price_metadata.items()
                    },
                )
            except Exception:
                sleeve_storage.discard_pending_sleeve(sleeve_id)
                raise
            sleeve_storage.finalize_pending_sleeve(sleeve_id)

    canary = registry.provision_canary(
        ProvisionCanaryCommand(
            artifact_id=request.artifact.artifact_id,
            sleeve_id=sleeve.sleeve_id,
            nav=request.nav,
            allocated_cash=Decimal(str(sleeve.initial_allocated_cash)),
            workspace_id=request.artifact.workspace_id,
        )
    )
    with sleeve_storage.mutation_lock():
        current = sleeve_storage.load_sleeve(sleeve.sleeve_id)
        if current.metadata.get("d34_activation_state") == "awaiting_registry":
            current.metadata["d34_activation_state"] = "active"
            sleeve = service.resume_sleeve(current)
        else:
            sleeve = current
    return sleeve, canary


__all__ = [
    "D34CanaryActivationError",
    "D34CanaryActivationRequest",
    "activate_d34_paper_canary",
]
