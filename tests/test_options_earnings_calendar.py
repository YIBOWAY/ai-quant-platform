from __future__ import annotations

from datetime import date
from pathlib import Path

from quant_system.options.earnings_calendar import EarningsCalendar


def test_earnings_calendar_returns_next_date(tmp_path: Path) -> None:
    path = tmp_path / "earnings.csv"
    path.write_text(
        "\n".join(
            [
                "ticker,earnings_date",
                "AAPL,2026-04-30",
                "AAPL,2026-05-10",
                "MSFT,2026-05-20",
            ]
        ),
        encoding="utf-8",
    )

    calendar = EarningsCalendar.load(path)

    assert calendar.next_earnings("aapl", date(2026, 5, 3)) == date(2026, 5, 10)
    assert calendar.next_earnings("MSFT", date(2026, 5, 3)) == date(2026, 5, 20)


def test_earnings_calendar_window_check(tmp_path: Path) -> None:
    path = tmp_path / "earnings.csv"
    path.write_text("ticker,earnings_date\nSPY,2026-05-10\n", encoding="utf-8")
    calendar = EarningsCalendar.load(path)

    assert calendar.is_within("SPY", date(2026, 5, 3), days=7) is True
    assert calendar.is_within("SPY", date(2026, 5, 3), days=6) is False
    assert calendar.is_within("QQQ", date(2026, 5, 3), days=7) is False


def test_earnings_calendar_missing_file_is_empty(tmp_path: Path) -> None:
    calendar = EarningsCalendar.load(tmp_path / "missing.csv")

    assert calendar.next_earnings("AAPL", date(2026, 5, 3)) is None
