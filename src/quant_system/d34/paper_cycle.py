"""One idempotent scheduled paper cycle for D-34 canary sleeves only."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from quant_system.execution.paper_observation import (
    hung_observation_open_for_sleeve,
    hung_sleeve_eligible,
)
from quant_system.execution.paper_strategy_signal_service import (
    PaperStrategySignalService,
)
from quant_system.execution.paper_strategy_sleeves import (
    SignalStatus,
    StrategyExecutionPlanError,
    StrategySleeveStatus,
)
from quant_system.research.strategy_runtime import latest_session, next_session, session_open

DEFINITION_REBALANCE_SUPPORTED = True
SHANGHAI = ZoneInfo("Asia/Shanghai")
EXECUTION_SLOT = time(22, 35)


def _requires_execution(signal: Any) -> bool:
    """A frozen target needs open-time sizing even when close estimates are empty."""
    if signal.status != SignalStatus.GENERATED or signal.execution_blocked_reason is not None:
        return False
    metadata = getattr(signal, "metadata", {}) or {}
    if metadata.get("definition_digest"):
        return (
            metadata.get("ready") is True
            and metadata.get("rebalance_due") is True
            and metadata.get("rebalance_required") is True
            and isinstance(metadata.get("targets"), dict)
        )
    return bool(signal.proposed_orders)


def _sleeve_error(sleeve_id: str, stage: str, exc: Exception) -> dict[str, str]:
    # Never include arbitrary exception text (provider responses may contain secrets).
    reasons = [str(exc)]
    if isinstance(exc, ValidationError):
        reasons = [
            str((item.get("ctx") or {}).get("error", ""))
            for item in exc.errors(include_input=False, include_url=False)
        ]
    safe_codes = {
        "strategy_algorithm_source_mismatch",
        "strategy_factor_source_mismatch",
        "strategy_definition_digest_mismatch",
        "strategy_validation_source_mismatch",
    }
    code = next((reason for reason in reasons if reason in safe_codes), type(exc).__name__)
    return {"sleeve_id": sleeve_id, "stage": stage, "code": code}


def paper_cycle_windows(now: datetime) -> dict[str, Any]:
    """Describe which observation windows are open at `now`."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("d34_paper_cycle_clock_invalid")
    now = now.astimezone(SHANGHAI)
    prior_day = now.date() - timedelta(days=1)
    prior_session = latest_session(prior_day)
    current_is_session = latest_session(now.date()).date() == now.date()
    signal_window_open = (
        now.weekday() in {1, 2, 3, 4, 5}
        and time(6, 10) <= now.time() < EXECUTION_SLOT
        and prior_session.date() == prior_day
    )
    execution_window_open = current_is_session and now >= session_open(
        now.date()
    ).to_pydatetime() + timedelta(minutes=5)
    signal_date = now.date().isoformat() if signal_window_open else None
    target_date = next_session(prior_session).date().isoformat() if signal_window_open else None
    execution_date = now.date().isoformat() if execution_window_open else None
    execution_would_run_at = None
    if target_date is not None:
        stamp = datetime.combine(date.fromisoformat(target_date), EXECUTION_SLOT, tzinfo=SHANGHAI)
        execution_would_run_at = stamp.isoformat()
    return {
        "signal_window_open": signal_window_open,
        "execution_window_open": execution_window_open,
        "signal_date": signal_date,
        "target_date": target_date,
        "execution_date": execution_date,
        "execution_would_run_at": execution_would_run_at,
    }


class PaperCycleDryPlanner:
    """Preview signal/orders/observation without writing sleeve or account files."""

    def __init__(self, *, account_storage: Any, sleeve_storage: Any, settings: Any) -> None:
        self.account_storage = account_storage
        self.sleeve_storage = sleeve_storage
        self.settings = settings
        self.signal_service = PaperStrategySignalService(storage=sleeve_storage, settings=settings)

    def _load_account(self) -> Any:
        load = getattr(self.account_storage, "load", None)
        if not callable(load):
            return None
        try:
            return load()
        except Exception as exc:  # noqa: BLE001 - dry-run must stay read-only
            return exc

    def preview(self, sleeve: Any, windows: dict[str, Any]) -> dict[str, Any]:
        costs = getattr(self.settings, "paper_account", None)
        commission_bps = float(getattr(costs, "commission_bps", 1.0))
        slippage_bps = float(getattr(costs, "slippage_bps", 5.0))
        item: dict[str, Any] = {
            "sleeve_id": sleeve.sleeve_id,
            "hung_eligible": hung_sleeve_eligible(sleeve),
            "would_generate_signal": False,
            "would_create_execution": False,
            "would_process_execution": False,
            "would_record_observation": False,
            "signal_date": windows.get("signal_date"),
            "target_date": windows.get("target_date"),
            "orders": [],
            "warnings": [],
            "observation": {
                "status": "none",
                "reason": "execution_window_closed",
            },
        }
        if windows.get("signal_window_open"):
            signal_date = windows["signal_date"]
            signal = None
            existing = next(
                (
                    row
                    for row in self.sleeve_storage.load_signals(sleeve.sleeve_id)
                    if row.signal_date == signal_date
                ),
                None,
            )
            if existing is None:
                account = self._load_account()
                if account is None:
                    item["warnings"].append("paper_account_missing")
                    orders = []
                elif isinstance(account, Exception):
                    item["warnings"].append(f"paper_account_unreadable:{type(account).__name__}")
                    orders = []
                else:
                    config = self.sleeve_storage.load_strategy_config(
                        sleeve.strategy_config_id,
                        version=sleeve.strategy_config_version,
                    )
                    try:
                        signal = self.signal_service.generate_daily_signal(
                            sleeve=sleeve,
                            config=config,
                            account=account,
                            signal_date=signal_date,
                            persist=False,
                            allow_frozen_account=hung_observation_open_for_sleeve(
                                self.settings, sleeve
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001 - dry-run stays a plan
                        item["warnings"].append(f"signal_preview_failed:{type(exc).__name__}")
                        orders = []
                    else:
                        item["would_generate_signal"] = True
                        item["warnings"] = [
                            *item["warnings"],
                            *list(getattr(signal, "warnings", []) or []),
                        ]
                        item["signal_status"] = str(getattr(signal.status, "value", signal.status))
                        orders = list(getattr(signal, "proposed_orders", []) or [])
            else:
                signal = existing
                item["signal_status"] = str(getattr(existing.status, "value", existing.status))
                orders = list(getattr(existing, "proposed_orders", []) or [])
                item["warnings"] = list(getattr(existing, "warnings", []) or [])
            priced = []
            for order in orders:
                notional = abs(float(order.get("notional_delta") or 0.0))
                cost = notional * (commission_bps + slippage_bps) / 10_000
                priced.append(
                    {
                        **dict(order),
                        "commission_bps": commission_bps,
                        "slippage_bps": slippage_bps,
                        "estimated_cost": cost,
                    }
                )
            item["orders"] = priced
            already = (
                self.sleeve_storage.latest_execution_for_signal(
                    sleeve.sleeve_id, getattr(existing, "signal_id", "")
                )
                if existing is not None
                else None
            )
            item["would_create_execution"] = (
                signal is not None and _requires_execution(signal) and already is None
            )
            if signal is not None and (getattr(signal, "metadata", {}) or {}).get(
                "definition_digest"
            ):
                item["target_date"] = signal.metadata.get("trade_date")
        if windows.get("execution_window_open"):
            pending = [
                {
                    "execution_id": getattr(row, "execution_id", None),
                    "target_date": getattr(row, "target_date", None),
                    "status": str(getattr(row.status, "value", row.status)),
                }
                for row in self.sleeve_storage.load_executions(sleeve.sleeve_id)
                if str(getattr(row, "target_date", "")) == windows.get("execution_date")
            ]
            item["pending_executions"] = pending
            item["would_process_execution"] = bool(pending)
            item["would_record_observation"] = bool(pending)
            item["observation"] = (
                {
                    "status": "would_record",
                    "reason": "execution_window_open",
                    "pending_count": len(pending),
                }
                if pending
                else {
                    "status": "none",
                    "reason": "no_pending_execution_for_today",
                }
            )
        elif windows.get("target_date"):
            item["observation"] = {
                "status": "none",
                "reason": "execution_window_closed",
                "would_run_at": windows.get("execution_would_run_at"),
            }
        return item


def _d34_running_sleeves(sleeve_storage: Any) -> list[Any]:
    from quant_system.execution.strategy_replacement import sleeve_replacement_pending

    return [
        sleeve
        for sleeve in sleeve_storage.list_sleeves()
        if sleeve.metadata.get("automation_managed") is True
        and sleeve.metadata.get("automation_source") == "d34"
        and sleeve.status == StrategySleeveStatus.RUNNING
        and not sleeve_replacement_pending(sleeve_storage, sleeve)
    ]


def plan_d34_paper_cycle(
    *,
    now: datetime,
    sleeve_storage: Any,
    runner: Any | None = None,
    dry_run: bool = True,
    planner: Any | None = None,
    paper_costs: Any | None = None,
) -> dict[str, Any]:
    """Read-only plan of what a cycle would do. Never writes.

    `runner` is accepted so call sites can pass the live runner and still be
    safe: dry-run must not invoke its persist methods.
    """
    del runner
    if dry_run is not True:
        raise ValueError("d34_paper_cycle_plan_requires_dry_run")
    windows = paper_cycle_windows(now)
    sleeves = _d34_running_sleeves(sleeve_storage)
    commission_bps = float(getattr(paper_costs, "commission_bps", 1.0))
    slippage_bps = float(getattr(paper_costs, "slippage_bps", 5.0))
    planned: list[dict[str, Any]] = []
    if planner is not None:
        for sleeve in sleeves:
            try:
                planned.append(planner.preview(sleeve, windows))
            except Exception as exc:  # noqa: BLE001 - one broken sleeve is not the whole plan
                planned.append(
                    {
                        **_sleeve_error(sleeve.sleeve_id, "preview", exc),
                        "status": "failed",
                        "would_write": False,
                    }
                )
    return {
        "contract": "hqa.d34_paper_cycle_plan/v1",
        "dry_run": True,
        **windows,
        "sleeves_checked": len(sleeves),
        "sleeves": planned,
        "paper_costs": {
            "commission_bps": commission_bps,
            "slippage_bps": slippage_bps,
        },
        "would_write": False,
    }


def run_d34_paper_cycle(
    *,
    now: datetime,
    sleeve_storage: Any,
    runner: Any,
) -> dict[str, Any]:
    """Generate next-open work and execute it without depending on D-33 flags."""
    windows = paper_cycle_windows(now)
    sleeves = _d34_running_sleeves(sleeve_storage)
    signals_generated = 0
    executions_created = 0
    executions_processed = 0
    executions_filled = 0
    executions_blocked = 0
    executions_missed_window = 0
    sleeve_errors: list[dict[str, str]] = []

    if windows["signal_window_open"]:
        signal_date = windows["signal_date"]
        target_date = windows["target_date"]
        for sleeve in sleeves:
            try:
                signal = next(
                    (
                        item
                        for item in sleeve_storage.load_signals(sleeve.sleeve_id)
                        if item.signal_date == signal_date
                    ),
                    None,
                )
                if signal is None:
                    signal = runner.generate_signal_once(
                        sleeve.sleeve_id,
                        signal_date=signal_date,
                    )
                    signals_generated += 1
                if (
                    not _requires_execution(signal)
                    or sleeve_storage.latest_execution_for_signal(
                        sleeve.sleeve_id,
                        signal.signal_id,
                    )
                    is not None
                ):
                    continue
            except Exception as exc:  # noqa: BLE001 - isolate without fake signals or retries
                sleeve_errors.append(_sleeve_error(sleeve.sleeve_id, "signal", exc))
                continue
            try:
                runner.create_execution_once(
                    sleeve.sleeve_id,
                    signal.signal_id,
                    target_date=target_date,
                    metadata={"automation_managed": True, "automation_source": "d34"},
                )
            except StrategyExecutionPlanError as exc:
                code = str(exc)
                if code == "execution_already_exists":
                    continue
                if code.startswith("automation_") or code == "account_frozen":
                    executions_blocked += 1
                    continue
                sleeve_errors.append(_sleeve_error(sleeve.sleeve_id, "create_execution", exc))
                continue
            except Exception as exc:  # noqa: BLE001 - preserve other sleeves, never blind retry
                sleeve_errors.append(_sleeve_error(sleeve.sleeve_id, "create_execution", exc))
                continue
            executions_created += 1

    if windows["execution_window_open"]:
        for sleeve in sleeves:
            try:
                result = runner.process_pending_executions_once(
                    sleeve_id=sleeve.sleeve_id,
                    target_date=windows["execution_date"],
                )
            except Exception as exc:  # noqa: BLE001 - journal recovery remains runner-owned
                sleeve_errors.append(_sleeve_error(sleeve.sleeve_id, "process_execution", exc))
                continue
            executions_processed += result.processed_count
            executions_filled += result.filled_count
            executions_blocked += result.blocked_count
            executions_missed_window += getattr(result, "missed_window_count", 0)
    return {
        "sleeves_checked": len(sleeves),
        "signals_generated": signals_generated,
        "executions_created": executions_created,
        "executions_processed": executions_processed,
        "executions_filled": executions_filled,
        "executions_blocked": executions_blocked,
        "executions_missed_window": executions_missed_window,
        "sleeves_failed": len({item["sleeve_id"] for item in sleeve_errors}),
        "sleeve_errors": sleeve_errors,
    }


__all__ = [
    "PaperCycleDryPlanner",
    "paper_cycle_windows",
    "plan_d34_paper_cycle",
    "run_d34_paper_cycle",
]
