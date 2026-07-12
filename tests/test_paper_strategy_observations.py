from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_system.execution.account import PaperAccount
from quant_system.execution.paper_strategy_observations import (
    PaperStrategyObservationReader,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    SignalStatus,
    StrategyExecutionPlan,
    StrategySignal,
    StrategySleeve,
    StrategySleeveMode,
)


def _sleeve(sleeve_id: str = "sleeve-observed") -> StrategySleeve:
    return StrategySleeve(
        sleeve_id=sleeve_id,
        account_id="default",
        strategy_config_id="strategy-config-observed",
        strategy_config_version=3,
        mode=StrategySleeveMode.ALLOCATED,
        initial_allocated_cash=25_000.0,
        cash=25_000.0,
    )


def _signal(
    sleeve: StrategySleeve,
    *,
    signal_id: str,
    signal_date: str,
    generated_at: str,
) -> StrategySignal:
    return StrategySignal(
        signal_id=signal_id,
        sleeve_id=sleeve.sleeve_id,
        strategy_config_id=sleeve.strategy_config_id,
        strategy_config_version=sleeve.strategy_config_version,
        signal_date=signal_date,
        generated_at=generated_at,
        data_provider="futu",
        data_as_of=f"{signal_date}T20:00:00Z",
        target_weights={"AAPL": 1.0},
        proposed_orders=[],
        status=SignalStatus.GENERATED,
    )


def _execution(
    sleeve: StrategySleeve,
    signal: StrategySignal,
    *,
    execution_id: str = "strategy-exec-observed",
) -> StrategyExecutionPlan:
    return StrategyExecutionPlan(
        execution_id=execution_id,
        sleeve_id=sleeve.sleeve_id,
        account_id=sleeve.account_id,
        signal_id=signal.signal_id,
        strategy_config_id=signal.strategy_config_id,
        strategy_config_version=signal.strategy_config_version,
        execution_window="next_open",
        target_date=signal.signal_date,
        created_at="2026-07-10T13:00:00Z",
        updated_at="2026-07-10T13:00:00Z",
        status="pending",
    )


def test_observation_reader_returns_empty_without_materializing_storage(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")

    payload = PaperStrategyObservationReader(
        storage,
        now=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    ).read()

    assert payload == {
        "schema_version": 1,
        "snapshot_at": "2026-07-12T00:00:00Z",
        "read_status": "empty",
        "query": {
            "from_date": None,
            "to_date": None,
            "signal_id": None,
            "limit": 200,
        },
        "returned_count": 0,
        "truncated": False,
        "ops_quality": {
            "pending_sleeve_count": 0,
            "pending_journal_count": 0,
            "corrupt_journal_count": 0,
            "recovery_required_count": 0,
        },
        "observations": [],
        "errors": [],
    }
    assert storage.root_dir.exists() is False


def test_observation_reader_uses_injected_utc_snapshot_time(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    reader = PaperStrategyObservationReader(
        storage,
        now=lambda: datetime(2026, 7, 12, 9, 8, 7, tzinfo=UTC),
    )

    payload = reader.read(to_date="2026-07-10")

    assert payload["snapshot_at"] == "2026-07-12T09:08:07Z"
    assert payload["query"]["to_date"] == "2026-07-10"


def test_observation_reader_filters_and_orders_causally_linked_facts(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    later = _signal(
        sleeve,
        signal_id="signal-later",
        signal_date="2026-07-10",
        generated_at="2026-07-10T12:00:00Z",
    )
    earlier = _signal(
        sleeve,
        signal_id="signal-earlier",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    outside = _signal(
        sleeve,
        signal_id="signal-outside",
        signal_date="2026-07-09",
        generated_at="2026-07-09T12:00:00Z",
    )
    storage.save_sleeve(sleeve)
    for signal in [later, outside, earlier]:
        storage.append_signal(signal)
    storage.save_executions(sleeve.sleeve_id, [_execution(sleeve, later)])

    payload = PaperStrategyObservationReader(storage).read(
        from_date="2026-07-10",
        to_date="2026-07-10",
    )

    assert payload["read_status"] == "available"
    assert payload["query"]["from_date"] == "2026-07-10"
    assert payload["query"]["to_date"] == "2026-07-10"
    assert payload["returned_count"] == 2
    assert payload["truncated"] is False
    assert [item["signal"]["signal_id"] for item in payload["observations"]] == [
        "signal-earlier",
        "signal-later",
    ]
    assert payload["observations"][0]["executions"] == []
    assert payload["observations"][1]["executions"] == [
        {
            "execution_id": "strategy-exec-observed",
            "signal_id": "signal-later",
            "sleeve_id": sleeve.sleeve_id,
            "account_id": "default",
            "strategy_config_id": sleeve.strategy_config_id,
            "strategy_config_version": 3,
            "execution_window": "next_open",
            "target_date": "2026-07-10",
            "created_at": "2026-07-10T13:00:00Z",
            "updated_at": "2026-07-10T13:00:00Z",
            "status": "pending",
            "blocked_reason": None,
        }
    ]


def test_observation_reader_bounds_output_and_reports_truncation(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    storage.save_sleeve(sleeve)
    for index in range(3):
        storage.append_signal(
            _signal(
                sleeve,
                signal_id=f"signal-{index}",
                signal_date="2026-07-10",
                generated_at=f"2026-07-10T1{index}:00:00Z",
            )
        )

    payload = PaperStrategyObservationReader(storage).read(limit=2)

    assert payload["read_status"] == "available"
    assert payload["returned_count"] == 2
    assert payload["truncated"] is True
    assert [item["signal"]["signal_id"] for item in payload["observations"]] == [
        "signal-0",
        "signal-1",
    ]


@pytest.mark.parametrize("limit", [0, 501])
def test_observation_reader_rejects_unbounded_limits(tmp_path, limit) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")

    with pytest.raises(ValueError, match="limit must be between 1 and 500"):
        PaperStrategyObservationReader(storage).read(limit=limit)

    assert storage.root_dir.exists() is False


@pytest.mark.parametrize(
    ("from_date", "to_date", "message"),
    [
        ("2026/07/10", None, "from_date must be an ISO date"),
        (None, "July 10", "to_date must be an ISO date"),
        ("2026-07-11", "2026-07-10", "from_date must not be after to_date"),
    ],
)
def test_observation_reader_rejects_invalid_date_bounds(
    tmp_path,
    from_date,
    to_date,
    message,
) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")

    with pytest.raises(ValueError, match=message):
        PaperStrategyObservationReader(storage).read(
            from_date=from_date,
            to_date=to_date,
        )

    assert storage.root_dir.exists() is False


def test_observation_reader_degrades_on_duplicate_signal_identity(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    first = _sleeve("sleeve-first")
    second = _sleeve("sleeve-second").model_copy(
        update={"strategy_config_id": "strategy-config-second"}
    )
    storage.save_sleeve(first)
    storage.save_sleeve(second)
    storage.append_signal(
        _signal(
            first,
            signal_id="signal-duplicate",
            signal_date="2026-07-10",
            generated_at="2026-07-10T11:00:00Z",
        )
    )
    storage.append_signal(
        _signal(
            second,
            signal_id="signal-duplicate",
            signal_date="2026-07-10",
            generated_at="2026-07-10T12:00:00Z",
        )
    )

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["returned_count"] == 0
    assert payload["truncated"] is False
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "duplicate_signal_id",
            "message": "duplicate strategy signal identity detected",
            "signal_id": "signal-duplicate",
        }
    ]


def test_observation_reader_degrades_on_multiple_executions_for_one_signal(
    tmp_path,
) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    signal = _signal(
        sleeve,
        signal_id="signal-one-action",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    storage.save_sleeve(sleeve)
    storage.append_signal(signal)
    storage.save_executions(
        sleeve.sleeve_id,
        [
            _execution(sleeve, signal, execution_id="strategy-exec-first"),
            _execution(sleeve, signal, execution_id="strategy-exec-second"),
        ],
    )

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "multiple_executions_for_signal",
            "message": "multiple strategy executions reference one signal",
            "signal_id": signal.signal_id,
        }
    ]


def test_observation_reader_degrades_on_orphan_execution_reference(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    missing_signal = _signal(
        sleeve,
        signal_id="signal-missing",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    execution = _execution(sleeve, missing_signal)
    storage.save_sleeve(sleeve)
    storage.save_executions(sleeve.sleeve_id, [execution])

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "orphan_execution_signal",
            "message": "strategy execution references a missing signal",
            "execution_id": execution.execution_id,
            "signal_id": missing_signal.signal_id,
        }
    ]


def test_observation_reader_degrades_on_inconsistent_execution_relationship(
    tmp_path,
) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    signal = _signal(
        sleeve,
        signal_id="signal-linked",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    execution = _execution(sleeve, signal).model_copy(update={"account_id": "another-account"})
    storage.save_sleeve(sleeve)
    storage.append_signal(signal)
    storage.save_executions(sleeve.sleeve_id, [execution])

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "inconsistent_execution_relationship",
            "message": "strategy execution identity does not match its signal and sleeve",
            "execution_id": execution.execution_id,
            "signal_id": signal.signal_id,
        }
    ]


def test_observation_reader_degrades_when_execution_predates_linked_signal(
    tmp_path,
) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    signal = _signal(
        sleeve,
        signal_id="signal-created-after-execution",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    execution = _execution(sleeve, signal).model_copy(
        update={
            "created_at": "2026-07-09T13:00:00Z",
            "updated_at": "2026-07-09T13:01:00Z",
        }
    )
    storage.save_sleeve(sleeve)
    storage.append_signal(signal)
    storage.save_executions(sleeve.sleeve_id, [execution])
    source_paths = (
        storage.sleeve_path(sleeve.sleeve_id),
        storage.sleeve_signals_path(sleeve.sleeve_id),
        storage.sleeve_executions_path(sleeve.sleeve_id),
    )
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in source_paths}

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["returned_count"] == 0
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "inconsistent_execution_relationship",
            "message": "strategy execution identity does not match its signal and sleeve",
            "execution_id": execution.execution_id,
            "signal_id": signal.signal_id,
        }
    ]
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in source_paths} == before


def test_observation_reader_degrades_when_execution_update_predates_creation(
    tmp_path,
) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    signal = _signal(
        sleeve,
        signal_id="signal-execution-update-before-create",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    execution = _execution(sleeve, signal).model_copy(
        update={
            "created_at": "2026-07-10T13:00:00Z",
            "updated_at": "2026-07-10T12:59:59Z",
        }
    )
    storage.save_sleeve(sleeve)
    storage.append_signal(signal)
    storage.save_executions(sleeve.sleeve_id, [execution])
    source_paths = (
        storage.sleeve_path(sleeve.sleeve_id),
        storage.sleeve_signals_path(sleeve.sleeve_id),
        storage.sleeve_executions_path(sleeve.sleeve_id),
    )
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in source_paths}

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["returned_count"] == 0
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "inconsistent_execution_relationship",
            "message": "strategy execution identity does not match its signal and sleeve",
            "execution_id": execution.execution_id,
            "signal_id": signal.signal_id,
        }
    ]
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in source_paths} == before


def test_observation_reader_accepts_equal_execution_timeline_instants(
    tmp_path,
) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    signal = _signal(
        sleeve,
        signal_id="signal-equal-execution-instants",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    execution = _execution(sleeve, signal).model_copy(
        update={
            "created_at": "2026-07-10T13:00:00+02:00",
            "updated_at": "2026-07-10T06:00:00-05:00",
        }
    )
    storage.save_sleeve(sleeve)
    storage.append_signal(signal)
    storage.save_executions(sleeve.sleeve_id, [execution])

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "available"
    assert payload["returned_count"] == 1
    assert payload["errors"] == []
    assert payload["observations"][0]["executions"][0]["execution_id"] == (execution.execution_id)


def test_observation_reader_degrades_without_repairing_corrupt_data(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    storage.save_sleeve(sleeve)
    signals_path = storage.sleeve_signals_path(sleeve.sleeve_id)
    signals_path.write_bytes(b"{not-json\n")
    before = (signals_path.read_bytes(), signals_path.stat().st_mtime_ns)

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["returned_count"] == 0
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "strategy_observation_data_unreadable",
            "message": "strategy observation data is unreadable",
        }
    ]
    assert (signals_path.read_bytes(), signals_path.stat().st_mtime_ns) == before


def test_observation_reader_degrades_when_action_coverage_quality_is_incomplete(
    tmp_path,
) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    pending_journal = storage.execution_journal_pending_path(
        "sleeve-pending",
        "strategy-exec-pending",
    )
    pending_journal.parent.mkdir(parents=True, exist_ok=True)
    pending_journal.write_bytes(b"{not-parsed-by-observer")
    before = (pending_journal.read_bytes(), pending_journal.stat().st_mtime_ns)

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["ops_quality"]["pending_journal_count"] == 1
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "strategy_observation_quality_incomplete",
            "message": "strategy action coverage has unresolved recovery state",
        }
    ]
    assert (pending_journal.read_bytes(), pending_journal.stat().st_mtime_ns) == before


def test_observation_reader_degrades_without_repairing_malformed_committed_journal(
    tmp_path,
) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve("sleeve-malformed-committed-journal")
    storage.save_sleeve(sleeve)
    committed_journal = storage.execution_journal_committed_path(
        sleeve.sleeve_id,
        "strategy-exec-malformed-committed",
    )
    committed_journal.parent.mkdir(parents=True, exist_ok=True)
    committed_journal.write_bytes(b"{not-json")
    before = (
        committed_journal.read_bytes(),
        committed_journal.stat().st_mtime_ns,
    )

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["ops_quality"]["corrupt_journal_count"] == 1
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "committed_execution_journal_unreadable",
            "message": "committed strategy execution journal is unreadable",
        }
    ]
    assert (
        committed_journal.read_bytes(),
        committed_journal.stat().st_mtime_ns,
    ) == before


def test_observation_reader_degrades_on_orphan_committed_execution_journal(
    tmp_path,
) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve("sleeve-orphan-committed-journal")
    signal = _signal(
        sleeve,
        signal_id="signal-orphan-committed-journal",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    orphan_execution = _execution(
        sleeve,
        signal,
        execution_id="strategy-exec-orphan-committed",
    )
    account = PaperAccount.open_new(initial_cash=100_000.0)
    storage.save_sleeve(sleeve)
    storage.append_signal(signal)
    storage.save_execution_journal_pending(
        sleeve_id=sleeve.sleeve_id,
        execution_id=orphan_execution.execution_id,
        payload={
            "journal_version": 1,
            "created_at": "2026-07-10T13:00:00Z",
            "account_id": account.account_id,
            "sleeve_id": sleeve.sleeve_id,
            "execution_id": orphan_execution.execution_id,
            "before_account": account.model_dump(mode="json"),
            "after_account": account.model_dump(mode="json"),
            "before_sleeve": sleeve.model_dump(mode="json"),
            "after_sleeve": sleeve.model_dump(mode="json"),
            "before_lots": [],
            "after_lots": [],
            "before_execution": orphan_execution.model_dump(mode="json"),
            "after_execution": orphan_execution.model_dump(mode="json"),
        },
    )
    committed_journal = storage.commit_execution_journal(
        sleeve_id=sleeve.sleeve_id,
        execution_id=orphan_execution.execution_id,
    )
    before = (
        committed_journal.read_bytes(),
        committed_journal.stat().st_mtime_ns,
    )

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["ops_quality"]["corrupt_journal_count"] == 1
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "orphan_committed_execution_journal",
            "message": ("committed strategy execution journal has no canonical execution"),
            "execution_id": orphan_execution.execution_id,
        }
    ]
    assert (
        committed_journal.read_bytes(),
        committed_journal.stat().st_mtime_ns,
    ) == before


def test_observation_reader_degrades_on_non_finite_signal_payload(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    signal = _signal(
        sleeve,
        signal_id="signal-non-finite",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    ).model_copy(update={"target_weights": {"AAPL": float("nan")}})
    storage.save_sleeve(sleeve)
    storage.append_signal(signal)

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["observations"] == []
    assert payload["errors"][0]["code"] == "strategy_observation_data_unreadable"


def test_observation_reader_degrades_on_reused_execution_identity(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    first = _signal(
        sleeve,
        signal_id="signal-first-execution",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    second = _signal(
        sleeve,
        signal_id="signal-second-execution",
        signal_date="2026-07-10",
        generated_at="2026-07-10T12:00:00Z",
    )
    storage.save_sleeve(sleeve)
    storage.append_signal(first)
    storage.append_signal(second)
    storage.save_executions(
        sleeve.sleeve_id,
        [
            _execution(sleeve, first, execution_id="strategy-exec-reused"),
            _execution(sleeve, second, execution_id="strategy-exec-reused"),
        ],
    )

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["observations"] == []
    assert payload["errors"] == [
        {
            "code": "duplicate_execution_id",
            "message": "duplicate strategy execution identity detected",
            "execution_id": "strategy-exec-reused",
        }
    ]


def test_observation_reader_degrades_when_sleeve_directory_identity_is_wrong(
    tmp_path,
) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve("sleeve-physical-identity")
    signal = _signal(
        sleeve,
        signal_id="signal-physical-identity",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    storage.save_sleeve(sleeve)
    storage.append_signal(signal)
    original = storage.sleeve_dir(sleeve.sleeve_id)
    original.rename(storage.sleeves_dir / "wrong-directory")

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["observations"] == []
    assert payload["errors"][0]["code"] == "inconsistent_sleeve_directory_identity"


def test_observation_reader_degrades_on_orphan_activity_files(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    orphan_dir = storage.sleeves_dir / "orphan"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "signals.jsonl").write_text("{}\n", encoding="utf-8")

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["observations"] == []
    assert payload["errors"][0]["code"] == "orphan_strategy_activity_files"


def test_observation_reader_degrades_on_noncanonical_signal_date(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    signal = _signal(
        sleeve,
        signal_id="signal-compact-date",
        signal_date="20260710",
        generated_at="2026-07-10T11:00:00Z",
    ).model_copy(update={"data_as_of": None})
    storage.save_sleeve(sleeve)
    storage.append_signal(signal)

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["observations"] == []
    assert payload["errors"][0]["code"] == "strategy_observation_data_unreadable"


def test_observation_reader_orders_aware_offsets_by_instant(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    earlier_instant = _signal(
        sleeve,
        signal_id="signal-offset-earlier",
        signal_date="2026-07-10",
        generated_at="2026-07-10T12:00:00+02:00",
    )
    later_instant = _signal(
        sleeve,
        signal_id="signal-utc-later",
        signal_date="2026-07-10",
        generated_at="2026-07-10T11:00:00Z",
    )
    storage.save_sleeve(sleeve)
    storage.append_signal(later_instant)
    storage.append_signal(earlier_instant)

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "available"
    assert [row["signal"]["signal_id"] for row in payload["observations"]] == [
        "signal-offset-earlier",
        "signal-utc-later",
    ]


def test_observation_reader_degrades_on_invalid_signal_time_identity(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = _sleeve()
    signal = _signal(
        sleeve,
        signal_id="signal-invalid-date",
        signal_date="not-a-date",
        generated_at="not-a-timestamp",
    )
    storage.save_sleeve(sleeve)
    storage.append_signal(signal)

    payload = PaperStrategyObservationReader(storage).read()

    assert payload["read_status"] == "degraded"
    assert payload["observations"] == []
    assert payload["errors"][0]["code"] == "strategy_observation_data_unreadable"
