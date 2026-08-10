"""Crash-recoverable activation of one paper-only automated factor."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from quant_system.config.settings import Settings
from quant_system.execution.factor_automation_authority import (
    FactorAutomationEventReceipt,
    FactorAutomationEventRequest,
    FactorAutomationLineage,
    append_factor_automation_event,
)
from quant_system.execution.factor_automation_demote import (
    FactorAutomationDemoteService,
)
from quant_system.execution.factor_automation_safety import (
    admit_auto_sleeve,
    evaluate_auto_sleeve_health,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategyConfig,
    StrategySleeve,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.factors.registry import build_factor_registry

_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")
_AUTOMATION_RE = re.compile(r"automation-[0-9a-f]{16,64}\Z")
_PROMOTION_RE = re.compile(r"promo-[0-9a-f]{32}(?:-r[2-9][0-9]*)?\Z")
_FACTOR_PATH_RE = re.compile(
    r"src/quant_system/factors/library/promoted/([a-z0-9_]+)\.py\Z"
)


class FactorAutomationActivationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AutomaticLandAuthorizationRequest:
    automation_id: str
    promotion_id: str
    automation_policy_digest: str
    intake_contract_digest: str
    gate1_digest: str
    gate2_digest: str
    workspace_id: str = "local-default"


@dataclass(frozen=True)
class AccountValuation:
    account_id: str
    account_updated_at: str
    nav: float
    prices: Mapping[str, float]
    price_metadata: Mapping[str, Mapping[str, str | None]]


@dataclass(frozen=True)
class AutomaticSleeveRequest:
    lineage: FactorAutomationLineage
    promotion_id: str
    universe: tuple[str, ...]
    provider: str
    workspace_id: str = "local-default"


EventWriter = Callable[
    [Settings, FactorAutomationEventRequest],
    FactorAutomationEventReceipt,
]


def _require_enabled(settings: Settings) -> None:
    if (
        settings.factor_automation.mode is not True
        or settings.factor_automation.auto_land is not True
    ):
        raise FactorAutomationActivationError("factor_automation_disabled")


def _factor_id_from_status(status: Mapping[str, Any]) -> str:
    paths = status.get("scoped_paths")
    if not isinstance(paths, list):
        raise FactorAutomationActivationError("promotion_status_invalid")
    factors = []
    for path in paths:
        if not isinstance(path, str):
            raise FactorAutomationActivationError("promotion_status_invalid")
        match = _FACTOR_PATH_RE.fullmatch(path)
        if match is not None and match.group(1) != "__init__":
            factors.append(match.group(1))
    if len(factors) != 1:
        raise FactorAutomationActivationError("promotion_factor_invalid")
    return factors[0]


def authorize_automatic_land(
    settings: Settings,
    request: AutomaticLandAuthorizationRequest,
    *,
    promotion_status: Mapping[str, Any],
    event_writer: EventWriter = append_factor_automation_event,
) -> tuple[FactorAutomationLineage, FactorAutomationEventReceipt]:
    """Consume daily quota only after the exact Gate-3 commit is reviewed."""

    _require_enabled(settings)
    if (
        _AUTOMATION_RE.fullmatch(request.automation_id) is None
        or _PROMOTION_RE.fullmatch(request.promotion_id) is None
        or any(
            _DIGEST_RE.fullmatch(value) is None
            for value in (
                request.automation_policy_digest,
                request.intake_contract_digest,
                request.gate1_digest,
                request.gate2_digest,
            )
        )
        or promotion_status.get("promotion_id") != request.promotion_id
        or promotion_status.get("status") not in {"reviewed", "landed"}
    ):
        raise FactorAutomationActivationError("promotion_status_invalid")
    candidate_id = promotion_status.get("candidate_id")
    candidate_digest = promotion_status.get("candidate_digest")
    manifest_digest = promotion_status.get("manifest_sha256")
    gate3_digest = promotion_status.get("patch_sha256")
    commit_sha = promotion_status.get("reviewed_commit")
    if (
        not isinstance(candidate_id, str)
        or _DIGEST_RE.fullmatch(str(candidate_digest)) is None
        or _DIGEST_RE.fullmatch(str(manifest_digest)) is None
        or _DIGEST_RE.fullmatch(str(gate3_digest)) is None
        or _COMMIT_RE.fullmatch(str(commit_sha)) is None
    ):
        raise FactorAutomationActivationError("promotion_status_invalid")
    lineage = FactorAutomationLineage(
        automation_id=request.automation_id,
        candidate_id=candidate_id,
        candidate_digest=str(candidate_digest),
        factor_id=_factor_id_from_status(promotion_status),
        manifest_digest=str(manifest_digest),
        automation_policy_digest=request.automation_policy_digest,
        intake_contract_digest=request.intake_contract_digest,
        gate1_digest=request.gate1_digest,
        gate2_digest=request.gate2_digest,
        gate3_digest=str(gate3_digest),
        commit_sha=str(commit_sha),
    )
    receipt = event_writer(
        settings,
        FactorAutomationEventRequest(
            event_id=f"promotion:{request.promotion_id}",
            workspace_id=request.workspace_id,
            event_type="promotion_committed",
            lineage=lineage,
            lifecycle_state="running",
            details={
                "promotion_id": request.promotion_id,
                "final_backtest_receipt_id": promotion_status.get(
                    "final_backtest_receipt_id"
                ),
            },
        ),
    )
    return lineage, receipt


def _deterministic_ids(automation_id: str) -> tuple[str, str]:
    token = hashlib.sha256(automation_id.encode("utf-8")).hexdigest()[:16]
    return f"strategy-config-auto-{token}", f"sleeve-auto-{token}"


def _verify_resident_factor(lineage: FactorAutomationLineage) -> None:
    paper = build_factor_registry(purpose="paper")
    live = build_factor_registry(purpose="live")
    qualification = paper.promoted_qualifications().get(lineage.factor_id)
    if (
        lineage.factor_id not in paper.factor_ids()
        or lineage.factor_id in live.factor_ids()
        or qualification
        != {
            "promotion_scope": "paper_only",
            "reviewer": "auto",
            "automation_policy_digest": lineage.automation_policy_digest,
            "intake_contract_digest": lineage.intake_contract_digest,
        }
    ):
        raise FactorAutomationActivationError("resident_qualification_invalid")


def _expected_config(
    request: AutomaticSleeveRequest,
    *,
    strategy_config_id: str,
) -> StrategyConfig:
    lineage = request.lineage
    metadata = {
        "automation_managed": True,
        "automation_id": lineage.automation_id,
        "candidate_id": lineage.candidate_id,
        "candidate_digest": lineage.candidate_digest,
        "manifest_digest": lineage.manifest_digest,
        "automation_policy_digest": lineage.automation_policy_digest,
        "intake_contract_digest": lineage.intake_contract_digest,
        "promotion_scope": "paper_only",
        "reviewer": "auto",
        "commit_sha": lineage.commit_sha,
    }
    return StrategyConfig.create(
        strategy_config_id=strategy_config_id,
        name=f"Auto paper · {lineage.factor_id}",
        description="Machine-qualified paper-only factor sleeve.",
        strategy_id="cross_sectional_top_n",
        universe_id=f"automation:{lineage.automation_id}",
        symbols=list(request.universe),
        factor_ids=[lineage.factor_id],
        weights={lineage.factor_id: 1.0},
        lookback=20,
        top_n=max(1, len(request.universe)),
        rebalance_frequency="daily",
        max_weight_per_symbol=0.40,
        min_order_value=100.0,
        data_provider=request.provider,
        execution_timing="next_open",
        tags=["automation", "paper_only"],
        metadata=metadata,
    )


def _same_config(existing: StrategyConfig, expected: StrategyConfig) -> bool:
    existing_payload = existing.model_dump(mode="json")
    expected_payload = expected.model_dump(mode="json")
    for field in ("created_at", "updated_at"):
        existing_payload.pop(field, None)
        expected_payload.pop(field, None)
    return existing_payload == expected_payload


def create_automatic_paper_sleeve(
    settings: Settings,
    request: AutomaticSleeveRequest,
    *,
    valuation: AccountValuation,
    account_storage: Any,
    sleeve_storage: Any,
    event_writer: EventWriter = append_factor_automation_event,
) -> tuple[StrategySleeve, FactorAutomationEventReceipt]:
    """Create one allocated sleeve exactly once, then append its audit event."""

    _require_enabled(settings)
    if (
        _PROMOTION_RE.fullmatch(request.promotion_id) is None
        or request.provider not in {"futu", "tiingo"}
        or not request.universe
        or len(set(request.universe)) != len(request.universe)
        or any(not symbol or symbol != symbol.upper() for symbol in request.universe)
    ):
        raise FactorAutomationActivationError("sleeve_request_invalid")
    _verify_resident_factor(request.lineage)
    config_id, sleeve_id = _deterministic_ids(request.lineage.automation_id)
    expected_config = _expected_config(request, strategy_config_id=config_id)
    service = PaperStrategySleeveService(sleeve_storage)

    with account_storage.mutation_lock(), sleeve_storage.mutation_lock():
        account = account_storage.load()
        if account is None:
            raise FactorAutomationActivationError("paper_account_missing")
        sleeve_storage.reconcile_pending_sleeves(account)
        if (
            valuation.account_id != account.account_id
            or valuation.account_updated_at != account.updated_at
        ):
            raise FactorAutomationActivationError("account_valuation_stale")
        try:
            existing = sleeve_storage.load_sleeve(sleeve_id)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            try:
                existing_config = sleeve_storage.load_strategy_config(config_id)
            except FileNotFoundError as exc:
                raise FactorAutomationActivationError(
                    "existing_sleeve_lineage_invalid"
                ) from exc
            if (
                not _same_config(existing_config, expected_config)
                or existing.metadata.get("automation_id")
                != request.lineage.automation_id
                or account.sleeve_cash.get(sleeve_id) != existing.cash
            ):
                raise FactorAutomationActivationError(
                    "existing_sleeve_lineage_invalid"
                )
            sleeve = existing
        else:
            admission = admit_auto_sleeve(
                nav=valuation.nav,
                existing_sleeves=sleeve_storage.list_sleeves(),
                factor_id=request.lineage.factor_id,
                manifest_digest=request.lineage.manifest_digest,
                automation_policy_digest=(
                    request.lineage.automation_policy_digest
                ),
            )
            metadata = {
                **admission.metadata,
                **expected_config.metadata,
                "gate1_digest": request.lineage.gate1_digest,
                "gate2_digest": request.lineage.gate2_digest,
                "gate3_digest": request.lineage.gate3_digest,
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
            sleeve_storage.save_pending_sleeve(sleeve)
            try:
                account_storage.save(
                    account,
                    prices=dict(valuation.prices),
                    price_metadata={
                        symbol: dict(metadata)
                        for symbol, metadata in valuation.price_metadata.items()
                    },
                )
            except Exception:
                sleeve_storage.discard_pending_sleeve(sleeve_id)
                raise
            sleeve_storage.finalize_pending_sleeve(sleeve_id)

    receipt = event_writer(
        settings,
        FactorAutomationEventRequest(
            event_id=f"sleeve:{sleeve_id}",
            workspace_id=request.workspace_id,
            event_type="sleeve_created",
            lineage=request.lineage,
            lifecycle_state="running",
            sleeve_id=sleeve_id,
            details={
                "promotion_id": request.promotion_id,
                "strategy_config_id": config_id,
                "allocated_cash": sleeve.initial_allocated_cash,
                "universe": list(request.universe),
                "provider": request.provider,
            },
        ),
    )
    return sleeve, receipt


def _lineage_from_sleeve(sleeve: StrategySleeve) -> FactorAutomationLineage:
    values = {
        "automation_id": sleeve.metadata.get("automation_id"),
        "candidate_id": sleeve.metadata.get("candidate_id"),
        "candidate_digest": sleeve.metadata.get("candidate_digest"),
        "factor_id": sleeve.metadata.get("factor_id"),
        "manifest_digest": sleeve.metadata.get("manifest_digest"),
        "automation_policy_digest": sleeve.metadata.get(
            "automation_policy_digest"
        ),
        "intake_contract_digest": sleeve.metadata.get("intake_contract_digest"),
        "gate1_digest": sleeve.metadata.get("gate1_digest"),
        "gate2_digest": sleeve.metadata.get("gate2_digest"),
        "gate3_digest": sleeve.metadata.get("gate3_digest"),
        "commit_sha": sleeve.metadata.get("commit_sha"),
    }
    if any(not isinstance(value, str) for value in values.values()):
        raise FactorAutomationActivationError("sleeve_lineage_invalid")
    return FactorAutomationLineage(**values)  # type: ignore[arg-type]


def maintain_automatic_paper_sleeves(
    settings: Settings,
    *,
    valuation: AccountValuation,
    account_storage: Any,
    sleeve_storage: Any,
    workspace_id: str = "local-default",
    event_writer: EventWriter = append_factor_automation_event,
) -> dict[str, int]:
    """Apply machine pause/quarantine rules and append their durable events."""

    _require_enabled(settings)
    account = account_storage.load()
    if account is None:
        raise FactorAutomationActivationError("paper_account_missing")
    if (
        valuation.account_id != account.account_id
        or valuation.account_updated_at != account.updated_at
    ):
        raise FactorAutomationActivationError("account_valuation_stale")
    registered = set(build_factor_registry(purpose="paper").factor_ids())
    paused = 0
    quarantined = 0
    checked = 0
    day = date.today().isoformat()

    for observed in sleeve_storage.list_sleeves():
        if observed.metadata.get("automation_managed") is not True:
            continue
        checked += 1
        lineage = _lineage_from_sleeve(observed)
        if lineage.factor_id not in registered:
            request_id = "factor-missing:" + hashlib.sha256(
                f"{observed.sleeve_id}:{lineage.manifest_digest}".encode()
            ).hexdigest()
            event_writer(
                settings,
                FactorAutomationEventRequest(
                    event_id=f"demote:{observed.sleeve_id}:factor-missing",
                    workspace_id=workspace_id,
                    event_type="demote_started",
                    lineage=lineage,
                    lifecycle_state="quarantined_hold",
                    sleeve_id=observed.sleeve_id,
                    details={"reason": "factor_missing", "request_id": request_id},
                ),
            )
            current = FactorAutomationDemoteService(sleeve_storage).demote(
                observed,
                request_id=request_id,
                reason="factor_missing",
            )
            event_writer(
                settings,
                FactorAutomationEventRequest(
                    event_id=f"quarantine:{observed.sleeve_id}:factor-missing",
                    workspace_id=workspace_id,
                    event_type="quarantined_hold",
                    lineage=lineage,
                    lifecycle_state="quarantined_hold",
                    sleeve_id=observed.sleeve_id,
                    details={"reason": "factor_missing", "request_id": request_id},
                ),
            )
            if current.status == StrategySleeveStatus.QUARANTINED_HOLD:
                quarantined += 1
            continue
        if observed.status != StrategySleeveStatus.RUNNING:
            continue

        with sleeve_storage.mutation_lock():
            current = sleeve_storage.load_sleeve(observed.sleeve_id)
            if current.status != StrategySleeveStatus.RUNNING:
                continue
            lots = sleeve_storage.load_sleeve_lots(current.sleeve_id)
            equity = current.cash + sum(
                lot.quantity
                * float(valuation.prices.get(lot.symbol.upper(), lot.avg_cost))
                for lot in lots
            )
            prior_day = current.metadata.get("automation_health_day")
            if prior_day == day:
                day_start = float(
                    current.metadata.get("automation_day_start_equity", equity)
                )
            else:
                day_start = equity
            peak = max(
                float(current.metadata.get("automation_peak_equity", equity)),
                equity,
            )
            breaches = evaluate_auto_sleeve_health(
                equity=equity,
                peak_equity=peak,
                daily_pnl=equity - day_start,
            )
            current.metadata.update(
                {
                    "automation_health_day": day,
                    "automation_day_start_equity": day_start,
                    "automation_peak_equity": peak,
                    "automation_last_equity": equity,
                }
            )
            if breaches:
                event_writer(
                    settings,
                    FactorAutomationEventRequest(
                        event_id=f"pause:{current.sleeve_id}:{day}",
                        workspace_id=workspace_id,
                        event_type="sleeve_paused",
                        lineage=lineage,
                        lifecycle_state="paused",
                        sleeve_id=current.sleeve_id,
                        details={
                            "reasons": list(breaches),
                            "equity": equity,
                            "peak_equity": peak,
                            "daily_pnl": equity - day_start,
                        },
                    ),
                )
                PaperStrategySleeveService(sleeve_storage).pause_sleeve(current)
                paused += 1
            else:
                sleeve_storage.save_sleeve(current)
    return {"checked": checked, "paused": paused, "quarantined": quarantined}


__all__ = [
    "AccountValuation",
    "AutomaticLandAuthorizationRequest",
    "AutomaticSleeveRequest",
    "FactorAutomationActivationError",
    "authorize_automatic_land",
    "create_automatic_paper_sleeve",
    "maintain_automatic_paper_sleeves",
]
