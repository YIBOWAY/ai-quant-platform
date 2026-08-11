from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from quant_system.d34.paper_cycle import run_d34_paper_cycle
from quant_system.execution.paper_strategy_sleeves import SignalStatus, StrategySleeveStatus


class Storage:
    def __init__(self) -> None:
        self.sleeves = [
            SimpleNamespace(
                sleeve_id="sleeve-d34",
                status=StrategySleeveStatus.RUNNING,
                metadata={"automation_managed": True, "automation_source": "d34"},
            ),
            SimpleNamespace(
                sleeve_id="sleeve-d33",
                status=StrategySleeveStatus.RUNNING,
                metadata={"automation_managed": True, "automation_source": "d33"},
            ),
        ]
        self.signals: dict[str, list[object]] = {}
        self.executions: dict[str, list[object]] = {}

    def list_sleeves(self):
        return list(self.sleeves)

    def load_signals(self, sleeve_id):
        return list(self.signals.get(sleeve_id, []))

    def latest_execution_for_signal(self, sleeve_id, signal_id):
        return next(
            (
                item
                for item in self.executions.get(sleeve_id, [])
                if item.signal_id == signal_id
            ),
            None,
        )


class Runner:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.processed: list[tuple[str, str]] = []

    def generate_signal_once(self, sleeve_id, *, signal_date):
        signal = SimpleNamespace(
            sleeve_id=sleeve_id,
            signal_id=f"signal-{signal_date}",
            signal_date=signal_date,
            status=SignalStatus.GENERATED,
            execution_blocked_reason=None,
            proposed_orders=[{"symbol": "SPY", "notional_delta": 100.0}],
        )
        self.storage.signals.setdefault(sleeve_id, []).append(signal)
        return signal

    def create_execution_once(self, sleeve_id, signal_id, *, target_date, metadata):
        execution = SimpleNamespace(
            sleeve_id=sleeve_id,
            signal_id=signal_id,
            target_date=target_date,
            metadata=metadata,
        )
        self.storage.executions.setdefault(sleeve_id, []).append(execution)
        return execution

    def process_pending_executions_once(self, *, sleeve_id, target_date):
        self.processed.append((sleeve_id, target_date))
        return SimpleNamespace(
            processed_count=1,
            filled_count=1,
            blocked_count=0,
        )


def test_d34_cycle_generates_and_executes_only_d34_sleeves_without_d33_flags() -> None:
    storage = Storage()
    runner = Runner(storage)
    local = ZoneInfo("Asia/Shanghai")

    first = run_d34_paper_cycle(
        now=datetime(2026, 6, 27, 6, 15, tzinfo=local),
        sleeve_storage=storage,
        runner=runner,
    )
    replay = run_d34_paper_cycle(
        now=datetime(2026, 6, 27, 6, 15, tzinfo=local),
        sleeve_storage=storage,
        runner=runner,
    )
    executed = run_d34_paper_cycle(
        now=datetime(2026, 6, 29, 21, 40, tzinfo=local),
        sleeve_storage=storage,
        runner=runner,
    )

    assert first["sleeves_checked"] == 1
    assert first["signals_generated"] == 1
    assert first["executions_created"] == 1
    assert replay["signals_generated"] == 0
    assert replay["executions_created"] == 0
    assert storage.signals.get("sleeve-d33", []) == []
    assert storage.executions["sleeve-d34"][0].target_date == "2026-06-29"
    assert executed["executions_processed"] == 1
    assert executed["executions_filled"] == 1
    assert runner.processed == [("sleeve-d34", "2026-06-29")]
