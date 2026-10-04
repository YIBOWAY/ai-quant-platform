from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from quant_system.d34.observation_calendar import (
    ABSENT_YESTERDAY_LABEL_ZH,
    collect_filled_nights,
    collect_recorded_nights,
    reconcile_observation_nights,
)

SH = ZoneInfo("Asia/Shanghai")
HUNG_AT = datetime(2026, 8, 18, 15, 44, tzinfo=SH)


def test_aug_18_is_absent_when_no_hung_sleeve_record_exists() -> None:
    report = reconcile_observation_nights(
        hung_at=HUNG_AT,
        now=datetime(2026, 8, 19, 4, 46, tzinfo=SH),
        recorded_nights=[],
    )

    assert report["yesterday"]["date"] == "2026-08-18"
    assert report["yesterday"]["status"] == "absent"
    assert report["yesterday"]["label_zh"] == ABSENT_YESTERDAY_LABEL_ZH
    assert report["yesterday"]["counts_as_observation_day"] is False
    assert report["yesterday"]["is_no_signal"] is False
    assert report["yesterday"]["reason"] is None
    assert "2026-08-18" in report["absent_nights"]
    assert report["observation_day_count"] == 0
    assert "2026-08-18" not in report["recorded_nights"]


def test_unexpired_night_is_not_absence() -> None:
    report = reconcile_observation_nights(
        hung_at=HUNG_AT,
        now=datetime(2026, 8, 19, 4, 46, tzinfo=SH),
        recorded_nights=[],
    )

    assert "2026-08-19" in report["pending_nights"]
    assert "2026-08-19" not in report["absent_nights"]
    assert "2026-08-19" not in report["expected_nights"]


def test_recorded_night_is_not_shown_as_absence() -> None:
    report = reconcile_observation_nights(
        hung_at=HUNG_AT,
        now=datetime(2026, 8, 19, 4, 46, tzinfo=SH),
        recorded_nights=["2026-08-18"],
        filled_nights=["2026-08-18"],
    )

    assert report["yesterday"]["status"] == "recorded"
    assert report["yesterday"]["label_zh"] != ABSENT_YESTERDAY_LABEL_ZH
    assert report["yesterday"]["counts_as_observation_day"] is True
    assert "2026-08-18" not in report["absent_nights"]
    assert report["observation_day_count"] == 1


def test_data_unavailable_night_counts_as_run_but_surfaces_signal_failure() -> None:
    report = reconcile_observation_nights(
        hung_at=HUNG_AT,
        now=datetime(2026, 8, 20, 10, 0, tzinfo=SH),
        recorded_nights=["2026-08-19"],
        data_unavailable_nights=["2026-08-19"],
    )

    assert report["yesterday"] == {
        "date": "2026-08-19",
        "status": "data_unavailable",
        "label_zh": "昨日观察：已运行，但信号数据不可用",
        "counts_as_observation_day": False,
        "is_no_signal": False,
        "reason": "signal_data_unavailable",
    }
    assert report["observation_day_count"] == 0
    assert report["calendar_run_day_count"] == 1
    assert report["data_unavailable_day_count"] == 1
    assert report["filled_day_count"] == 0
    assert "2026-08-19" not in report["absent_nights"]


def test_sunday_yesterday_is_not_absence() -> None:
    report = reconcile_observation_nights(
        hung_at=HUNG_AT,
        now=datetime(2026, 8, 24, 10, 0, tzinfo=SH),
        recorded_nights=["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-22"],
    )

    assert report["yesterday"]["date"] == "2026-08-23"
    assert report["yesterday"]["status"] == "not_scheduled"
    assert report["yesterday"]["label_zh"] != ABSENT_YESTERDAY_LABEL_ZH
    assert report["yesterday"]["counts_as_observation_day"] is False


def test_absence_is_not_classified_as_no_signal() -> None:
    report = reconcile_observation_nights(
        hung_at=HUNG_AT,
        now=datetime(2026, 8, 19, 4, 46, tzinfo=SH),
        recorded_nights=[],
    )
    assert report["yesterday"]["is_no_signal"] is False
    assert report["yesterday"]["status"] != "no_signal"


def test_collect_recorded_nights_ignores_fossils_and_account_inventory() -> None:
    hung = SimpleNamespace(
        sleeve_id="sleeve-hung",
        metadata={"automation_source": "d34", "fossil": False},
    )
    fossil = SimpleNamespace(
        sleeve_id="sleeve-fossil",
        metadata={"automation_source": "d34", "fossil": True, "official_observation": False},
    )

    class Storage:
        def load_signals(self, sleeve_id):
            if sleeve_id == "sleeve-hung":
                return []
            return [SimpleNamespace(signal_date="2026-08-18")]

        def load_executions(self, sleeve_id):
            return []

        def load_account_inventory(self):
            raise AssertionError("calendar must not read account inventory")

    nights = collect_recorded_nights(
        sleeves=[hung, fossil],
        storage=Storage(),
        account_positions=[{"symbol": "NVDA", "quantity": 10}],
    )
    assert nights == []


def test_signal_without_fill_is_a_run_not_a_performance_observation():
    report = reconcile_observation_nights(
        hung_at=HUNG_AT,
        now=datetime(2026, 8, 20, 10, 0, tzinfo=SH),
        recorded_nights=["2026-08-19"],
    )
    assert report["yesterday"]["status"] == "recorded"
    assert "已入账" not in report["yesterday"]["label_zh"]
    assert report["yesterday"]["counts_as_observation_day"] is False
    assert report["calendar_run_day_count"] == 1
    assert report["filled_day_count"] == 0
    assert report["observation_day_count"] == 0


def test_market_holiday_without_prior_session_is_not_a_missing_cycle():
    report = reconcile_observation_nights(
        hung_at=HUNG_AT,
        now=datetime(2026, 9, 8, 10, 0, tzinfo=SH),
        recorded_nights=[],
    )
    assert report["yesterday"]["status"] == "not_scheduled"
    assert "2026-09-07" not in report["expected_nights"]


def test_execution_slot_update_does_not_rewrite_historical_due_time():
    old = reconcile_observation_nights(
        hung_at=HUNG_AT,
        now=datetime(2026, 9, 10, 22, 30, tzinfo=SH),
        recorded_nights=[],
    )
    new = reconcile_observation_nights(
        hung_at=HUNG_AT,
        now=datetime(2026, 9, 11, 22, 30, tzinfo=SH),
        recorded_nights=[],
    )
    assert "2026-09-10" in old["expected_nights"]
    assert "2026-09-11" in new["pending_nights"]


def test_filled_dates_require_fills_not_just_a_processed_execution():
    sleeve = SimpleNamespace(sleeve_id="actual", metadata={})
    executions = [
        SimpleNamespace(status="blocked", target_date="2026-09-01", fills=[]),
        SimpleNamespace(status="skipped", target_date="2026-09-02", fills=[]),
        SimpleNamespace(status="filled", target_date="2026-09-03", fills=[]),
        SimpleNamespace(status="filled", target_date="2026-09-04", fills=[object()]),
    ]
    storage = SimpleNamespace(load_executions=lambda _identifier: executions)
    assert collect_filled_nights(sleeves=[sleeve], storage=storage) == ["2026-09-04"]
