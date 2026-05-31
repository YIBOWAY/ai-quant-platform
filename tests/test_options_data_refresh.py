from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from quant_system.options.data_refresh import refresh_earnings_calendar


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_public_earnings_refresh_uses_nasdaq_calendar(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,name,sector,exchange,source",
                "AVGO,Broadcom,Information Technology,US,both",
                "MSFT,Microsoft,Information Technology,US,both",
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "earnings.csv"

    def fake_urlopen(request, timeout=30):  # noqa: ANN001
        url = request.full_url
        rows = []
        if "2026-06-03" in url:
            rows = [
                {
                    "symbol": "AVGO",
                    "time": "time-after-hours",
                    "name": "Broadcom Inc.",
                }
            ]
        return _FakeResponse({"data": {"rows": rows}})

    monkeypatch.setattr("quant_system.options.data_refresh.urlopen", fake_urlopen)

    result = refresh_earnings_calendar(
        universe_path=universe_path,
        output_path=output_path,
        source="public",
        top=2,
        today=date(2026, 5, 31),
    )

    assert result["source"] == "nasdaq"
    assert result["row_count"] == 1
    assert "AVGO,2026-06-03" in output_path.read_text(encoding="utf-8")


def test_public_earnings_refresh_does_not_overwrite_existing_with_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,name,sector,exchange,source",
                "AVGO,Broadcom,Information Technology,US,both",
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "earnings.csv"
    output_path.write_text(
        "ticker,earnings_date\nAVGO,2026-06-03\n",
        encoding="utf-8",
    )

    def fake_urlopen(request, timeout=30):  # noqa: ANN001
        return _FakeResponse({"data": {"rows": []}})

    monkeypatch.setattr("quant_system.options.data_refresh.urlopen", fake_urlopen)

    result = refresh_earnings_calendar(
        universe_path=universe_path,
        output_path=output_path,
        source="public",
        top=1,
        today=date(2026, 5, 31),
    )

    assert result["status"] == "kept_existing"
    assert result["row_count"] == 1
    assert "AVGO,2026-06-03" in output_path.read_text(encoding="utf-8")
