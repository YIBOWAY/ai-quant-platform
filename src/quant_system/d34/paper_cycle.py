"""One idempotent scheduled paper cycle for D-34 canary sleeves only."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from quant_system.execution.paper_strategy_sleeves import (
    SignalStatus,
    StrategyExecutionPlanError,
    StrategySleeveStatus,
)


def _next_weekday(value: date) -> date:
    candidate = value
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def run_d34_paper_cycle(
    *,
    now: datetime,
    sleeve_storage: Any,
    runner: Any,
) -> dict[str, int]:
    """Generate next-open work and execute it without depending on D-33 flags."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("d34_paper_cycle_clock_invalid")
    sleeves = [
        sleeve
        for sleeve in sleeve_storage.list_sleeves()
        if sleeve.metadata.get("automation_managed") is True
        and sleeve.metadata.get("automation_source") == "d34"
        and sleeve.status == StrategySleeveStatus.RUNNING
    ]
    signals_generated = 0
    executions_created = 0
    executions_processed = 0
    executions_filled = 0
    executions_blocked = 0

    signal_window_open = now.weekday() in {1, 2, 3, 4, 5} and now.time() >= time(6, 10)
    if signal_window_open:
        signal_date = now.date().isoformat()
        target_date = _next_weekday(now.date()).isoformat()
        for sleeve in sleeves:
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
                signal.status != SignalStatus.GENERATED
                or signal.execution_blocked_reason is not None
                or not signal.proposed_orders
                or sleeve_storage.latest_execution_for_signal(
                    sleeve.sleeve_id,
                    signal.signal_id,
                )
                is not None
            ):
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
                raise
            executions_created += 1

    execution_window_open = now.weekday() in {0, 1, 2, 3, 4} and now.time() >= time(
        21, 35
    )
    if execution_window_open:
        for sleeve in sleeves:
            result = runner.process_pending_executions_once(
                sleeve_id=sleeve.sleeve_id,
                target_date=now.date().isoformat(),
            )
            executions_processed += result.processed_count
            executions_filled += result.filled_count
            executions_blocked += result.blocked_count
    return {
        "sleeves_checked": len(sleeves),
        "signals_generated": signals_generated,
        "executions_created": executions_created,
        "executions_processed": executions_processed,
        "executions_filled": executions_filled,
        "executions_blocked": executions_blocked,
    }


__all__ = ["run_d34_paper_cycle"]
