from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

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
            (item for item in self.executions.get(sleeve_id, []) if item.signal_id == signal_id),
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


def _tree_digest(root) -> str:
    import hashlib

    hasher = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        hasher.update(path.relative_to(root).as_posix().encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def test_dry_run_planner_does_not_change_account_or_sleeve_files(tmp_path, monkeypatch) -> None:
    from quant_system.config.settings import load_settings
    from quant_system.d34.paper_cycle import PaperCycleDryPlanner, plan_d34_paper_cycle
    from quant_system.execution.account import PaperAccount
    from quant_system.execution.account_storage import PaperAccountStorage
    from quant_system.execution.paper_strategy_sleeve_storage import (
        PaperStrategySleeveStorage,
    )
    from quant_system.execution.paper_strategy_sleeves import (
        StrategyConfig,
        StrategySleeve,
        StrategySleeveMode,
        StrategySleeveStatus,
    )

    def unavailable_history(*_args, **_kwargs):
        raise RuntimeError("sealed fixture: history unavailable")

    monkeypatch.setattr(
        "quant_system.execution.paper_strategy_signal_service.build_ohlcv_provider",
        unavailable_history,
    )
    api_runs = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs)
    sleeve_storage = PaperStrategySleeveStorage(api_runs)
    account = PaperAccount.open_new(initial_cash=10_000)
    account_storage.save(account)
    config = StrategyConfig.create(
        name="dry",
        description="dry-run digest fixture",
        strategy_id="cross_sectional_top_n",
        universe_id="custom",
        symbols=["SPY"],
        factor_ids=["momentum"],
        weights={"momentum": 1.0},
        lookback=20,
        top_n=1,
        rebalance_frequency="daily",
        max_weight_per_symbol=1.0,
        min_order_value=100.0,
        data_provider="futu",
        execution_timing="next_open",
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "promotion_scope": "paper_only",
            "source_digest": "ab" * 32,
        },
    )
    sleeve_storage.save_strategy_config(config)
    sleeve = StrategySleeve.create(
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        account_id=account.account_id,
        allocated_cash=10_000,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "promotion_scope": "paper_only",
            "source_digest": "ab" * 32,
            "candidate_code_digest": "ab" * 32,
        },
    )
    sleeve.status = StrategySleeveStatus.RUNNING
    sleeve_storage.save_sleeve(sleeve)
    before = _tree_digest(api_runs)

    planner = PaperCycleDryPlanner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=load_settings(),
    )
    plan = plan_d34_paper_cycle(
        now=datetime(2026, 8, 19, 6, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
        sleeve_storage=sleeve_storage,
        runner=None,
        dry_run=True,
        planner=planner,
        paper_costs=load_settings().paper_account,
    )
    after = _tree_digest(api_runs)

    assert before == after
    assert plan["would_write"] is False
    assert plan["signal_window_open"] is True
    assert plan["execution_window_open"] is False


def test_dry_run_preview_records_account_read_errors_instead_of_raising() -> None:
    from quant_system.d34.paper_cycle import PaperCycleDryPlanner

    class BrokenAccount:
        def load(self):
            raise RuntimeError("database recently failed")

    planner = PaperCycleDryPlanner(
        account_storage=BrokenAccount(),
        sleeve_storage=Storage(),
        settings=SimpleNamespace(
            paper_account=SimpleNamespace(commission_bps=1.0, slippage_bps=5.0),
        ),
    )
    sleeve = Storage().sleeves[0]
    sleeve.strategy_config_id = "cfg"
    sleeve.strategy_config_version = 1
    item = planner.preview(
        sleeve,
        {
            "signal_window_open": True,
            "execution_window_open": False,
            "signal_date": "2026-08-19",
            "target_date": "2026-08-19",
        },
    )
    assert item["would_generate_signal"] is False
    assert any(str(w).startswith("paper_account_unreadable") for w in item["warnings"])


def test_saturday_plan_opens_signal_only_and_targets_monday() -> None:
    from quant_system.d34.paper_cycle import plan_d34_paper_cycle

    storage = Storage()
    local = ZoneInfo("Asia/Shanghai")
    writes: list[str] = []

    class ForbiddenRunner:
        def generate_signal_once(self, *args, **kwargs):
            writes.append("generate")
            raise AssertionError("dry-run must not persist signals")

        def create_execution_once(self, *args, **kwargs):
            writes.append("create")
            raise AssertionError("dry-run must not persist executions")

        def process_pending_executions_once(self, *args, **kwargs):
            writes.append("process")
            raise AssertionError("dry-run must not process fills")

    plan = plan_d34_paper_cycle(
        now=datetime(2026, 8, 22, 22, 25, tzinfo=local),
        sleeve_storage=storage,
        runner=ForbiddenRunner(),
        dry_run=True,
    )

    assert writes == []
    assert plan["signal_window_open"] is True
    assert plan["execution_window_open"] is False
    assert plan["signal_date"] == "2026-08-22"
    assert plan["target_date"] == "2026-08-24"
    assert plan["execution_would_run_at"].startswith("2026-08-24")


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


@pytest.mark.parametrize(
    ("metadata", "orders", "expected"),
    [
        ({}, [], False),  # Legacy empty estimates remain a no-op.
        ({}, [{"symbol": "SPY", "notional_delta": 100}], True),
        ({"targets": {"SPY": 1.0}}, [], True),
        ({"targets": {}}, [], True),  # Explicit cash target still checks the open.
        ({"targets": None}, [], False),
        ({"targets": None}, [{"symbol": "SPY", "notional_delta": 100}], False),
        ({"targets": {}, "rebalance_due": False}, [], False),
        ({"targets": {}, "rebalance_required": False}, [], False),
        ({"targets": {}, "ready": False}, [], False),
    ],
)
def test_cycle_and_dry_preview_share_definition_scheduling(metadata, orders, expected):
    from quant_system.d34.paper_cycle import PaperCycleDryPlanner

    storage = Storage()
    runner = Runner(storage)
    signal = runner.generate_signal_once("sleeve-d34", signal_date="2026-09-09")
    signal.proposed_orders = orders
    signal.warnings = []
    signal.metadata = (
        {
            "definition_digest": "ab" * 32,
            "ready": True,
            "rebalance_due": True,
            "rebalance_required": True,
            "trade_date": "2026-09-09",
            **metadata,
        }
        if metadata
        else {}
    )
    planner = PaperCycleDryPlanner(
        account_storage=None,
        sleeve_storage=storage,
        settings=SimpleNamespace(),
    )
    preview = planner.preview(
        storage.sleeves[0],
        {
            "signal_window_open": True,
            "execution_window_open": False,
            "signal_date": "2026-09-09",
            "target_date": "2026-09-09",
        },
    )
    assert preview["would_create_execution"] is expected
    assert storage.executions == {}
    for repeat in range(2):
        result = run_d34_paper_cycle(
            now=datetime(2026, 9, 9, 6, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
            sleeve_storage=storage,
            runner=runner,
        )
        assert result["executions_created"] == int(expected and repeat == 0)
    assert len(storage.executions.get("sleeve-d34", [])) == int(expected)


@pytest.mark.parametrize("stage", ["signal", "create_execution", "process_execution"])
def test_single_sleeve_failure_does_not_abort_healthy_sleeve(stage):
    storage = Storage()
    storage.sleeves = [
        SimpleNamespace(
            sleeve_id=sleeve_id,
            status=StrategySleeveStatus.RUNNING,
            metadata={"automation_managed": True, "automation_source": "d34"},
        )
        for sleeve_id in ["broken", "healthy"]
    ]

    class IsolatedRunner(Runner):
        def generate_signal_once(self, sleeve_id, **kwargs):
            if sleeve_id == "broken" and stage == "signal":
                raise ValueError("strategy_algorithm_source_mismatch")
            return super().generate_signal_once(sleeve_id, **kwargs)

        def create_execution_once(self, sleeve_id, *args, **kwargs):
            if sleeve_id == "broken" and stage == "create_execution":
                raise RuntimeError("secret provider detail must not enter receipt")
            return super().create_execution_once(sleeve_id, *args, **kwargs)

        def process_pending_executions_once(self, *, sleeve_id, target_date):
            if sleeve_id == "broken" and stage == "process_execution":
                raise ValueError("strategy_algorithm_source_mismatch")
            return super().process_pending_executions_once(
                sleeve_id=sleeve_id,
                target_date=target_date,
            )

    runner = IsolatedRunner(storage)
    now = datetime(2026, 9, 11, 22, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    if stage != "process_execution":
        now = now.replace(hour=6, minute=15)
    result = run_d34_paper_cycle(now=now, sleeve_storage=storage, runner=runner)
    assert result["sleeves_failed"] == 1
    assert result["sleeve_errors"] == [
        {
            "sleeve_id": "broken",
            "stage": stage,
            "code": "RuntimeError"
            if stage == "create_execution"
            else "strategy_algorithm_source_mismatch",
        }
    ]
    if stage == "process_execution":
        assert runner.processed == [("healthy", "2026-09-11")]
        assert result["executions_filled"] == 1
    else:
        assert len(storage.executions["healthy"]) == 1


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-11-02T22:25:00+08:00",
        "2026-12-01T22:25:00+08:00",
        "2026-09-07T22:35:00+08:00",  # Labor Day is not an XNYS session.
    ],
)
def test_execution_never_runs_before_open_or_on_exchange_holiday(stamp):
    from quant_system.d34.paper_cycle import paper_cycle_windows

    now = datetime.fromisoformat(stamp)
    storage = Storage()
    runner = Runner(storage)
    assert paper_cycle_windows(now)["execution_window_open"] is False
    result = run_d34_paper_cycle(now=now, sleeve_storage=storage, runner=runner)
    assert runner.processed == []
    assert result["executions_processed"] == 0


def test_equivalent_utc_clock_uses_shanghai_calendar():
    from datetime import UTC

    from quant_system.d34.paper_cycle import paper_cycle_windows

    local = datetime(2026, 11, 2, 22, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert paper_cycle_windows(local) == paper_cycle_windows(local.astimezone(UTC))
    assert paper_cycle_windows(local)["execution_window_open"] is True


def test_natural_evening_slot_does_not_make_up_a_missing_morning_signal():
    storage = Storage()
    runner = Runner(storage)
    result = run_d34_paper_cycle(
        now=datetime(2026, 9, 11, 22, 35, tzinfo=ZoneInfo("Asia/Shanghai")),
        sleeve_storage=storage,
        runner=runner,
    )
    assert result["signals_generated"] == 0
    assert result["executions_created"] == 0
    assert storage.signals == {}
    assert storage.executions == {}


def test_friday_close_signal_targets_tuesday_after_monday_holiday():
    from quant_system.d34.paper_cycle import paper_cycle_windows

    window = paper_cycle_windows(
        datetime(
            2026,
            9,
            5,
            6,
            15,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
    )
    assert window["signal_window_open"] is True
    assert window["target_date"] == "2026-09-08"
    assert window["execution_would_run_at"] == "2026-09-08T22:35:00+08:00"


def test_dry_plan_continues_after_one_sleeve_preview_error():
    from quant_system.d34.paper_cycle import plan_d34_paper_cycle

    storage = Storage()
    healthy = SimpleNamespace(
        sleeve_id="healthy",
        status=StrategySleeveStatus.RUNNING,
        metadata={"automation_managed": True, "automation_source": "d34"},
    )
    storage.sleeves.append(healthy)

    class Planner:
        def preview(self, sleeve, windows):
            if sleeve.sleeve_id == "sleeve-d34":
                raise ValueError("strategy_algorithm_source_mismatch")
            return {"sleeve_id": sleeve.sleeve_id, "would_write": False}

    plan = plan_d34_paper_cycle(
        now=datetime(2026, 9, 11, 6, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
        sleeve_storage=storage,
        planner=Planner(),
    )
    assert plan["sleeves"][0]["status"] == "failed"
    assert plan["sleeves"][1]["sleeve_id"] == "healthy"
    assert plan["would_write"] is False


def test_source_mismatch_inside_real_config_validation_keeps_its_safe_code(monkeypatch):
    from pydantic import ValidationError

    from quant_system.d34.paper_cycle import _sleeve_error
    from quant_system.execution.paper_strategy_sleeves import StrategyConfig
    from tests.test_definition_paper_bridge import config_for, definition

    config = config_for(definition())
    monkeypatch.setattr(
        "quant_system.research.strategy_definition.current_source_fingerprints",
        lambda _: {},
    )
    with pytest.raises(ValidationError) as error:
        StrategyConfig.model_validate(config.model_dump(mode="json"))
    assert _sleeve_error("broken", "signal", error.value) == {
        "sleeve_id": "broken",
        "stage": "signal",
        "code": "strategy_algorithm_source_mismatch",
    }


def test_paper_cycle_signal_outcomes_collect_provider_error_codes() -> None:
    from quant_system.d34.cli import _paper_cycle_signal_outcomes

    storage = Storage()
    storage.signals["sleeve-d34"] = [
        SimpleNamespace(
            signal_date="2026-09-15",
            status=SignalStatus.DATA_UNAVAILABLE,
            metadata={"provider_error": {"code": "provider_unavailable"}},
        ),
        SimpleNamespace(
            signal_date="2026-09-15",
            status=SignalStatus.DATA_UNAVAILABLE,
            metadata={"provider_error": {"code": "provider_timeout"}},
        ),
        SimpleNamespace(
            signal_date="2026-09-14",
            status=SignalStatus.DATA_UNAVAILABLE,
            metadata={"provider_error": {"code": "stale_other_day"}},
        ),
    ]
    outcomes = _paper_cycle_signal_outcomes(storage, signal_date="2026-09-15")
    assert outcomes["data_unavailable"] == 2
    assert outcomes["provider_error_codes"] == ["provider_timeout", "provider_unavailable"]


def test_paper_cycle_signal_outcomes_default_empty_provider_error_codes() -> None:
    from quant_system.d34.cli import _paper_cycle_signal_outcomes

    storage = Storage()
    outcomes = _paper_cycle_signal_outcomes(storage, signal_date="2026-09-15")
    assert outcomes["generated"] == 0
    assert outcomes["provider_error_codes"] == []


def test_cycle_aggregates_missed_window_counts_and_defaults_to_zero():
    local = ZoneInfo("Asia/Shanghai")

    class SweepingRunner(Runner):
        def process_pending_executions_once(self, *, sleeve_id, target_date):
            self.processed.append((sleeve_id, target_date))
            return SimpleNamespace(
                processed_count=0,
                filled_count=0,
                blocked_count=0,
                missed_window_count=1,
            )

    storage = Storage()
    swept = run_d34_paper_cycle(
        now=datetime(2026, 9, 11, 22, 35, tzinfo=local),
        sleeve_storage=storage,
        runner=SweepingRunner(storage),
    )
    assert swept["executions_missed_window"] == 1
    assert swept["executions_processed"] == 0

    # A runner without the new field (older adapter) still cycles cleanly.
    storage = Storage()
    plain = run_d34_paper_cycle(
        now=datetime(2026, 9, 11, 22, 35, tzinfo=local),
        sleeve_storage=storage,
        runner=Runner(storage),
    )
    assert plain["executions_missed_window"] == 0
