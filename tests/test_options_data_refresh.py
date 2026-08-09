from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.error import URLError

from quant_system.options.data_refresh import (
    refresh_earnings_calendar,
    refresh_options_universe,
)


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


def test_universe_refresh_keeps_existing_after_ssl_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "universe.csv"
    path.write_text(
        "\n".join(
            [
                "ticker,name,sector,exchange,source",
                "AAPL,Apple Inc.,Information Technology,US,both",
                "MSFT,Microsoft Corporation,Information Technology,US,both",
            ]
        ),
        encoding="utf-8",
    )
    original = path.read_text(encoding="utf-8")
    attempts = {"count": 0}

    def failing_urlopen(request, timeout=30):  # noqa: ANN001
        attempts["count"] += 1
        raise URLError("SSL: UNEXPECTED_EOF_WHILE_READING")

    monkeypatch.setattr("quant_system.options.data_refresh.urlopen", failing_urlopen)
    monkeypatch.setattr("quant_system.options.data_refresh.time.sleep", lambda _seconds: None)

    result = refresh_options_universe(path, source="github")

    assert result["status"] == "kept_existing"
    assert result["row_count"] == 2
    assert "warning" in result
    assert path.read_text(encoding="utf-8") == original
    assert attempts["count"] >= 3


def test_universe_remote_csv_retries_then_succeeds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "universe.csv"
    calls = {"count": 0}

    class _CsvResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def __enter__(self) -> _CsvResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.text.encode("utf-8")

    def flaky_urlopen(request, timeout=30):  # noqa: ANN001
        url = request.full_url
        calls["count"] += 1
        fails = calls.setdefault(url, 0)
        if fails < 2:
            calls[url] = fails + 1
            raise URLError("SSL: UNEXPECTED_EOF_WHILE_READING")
        if "s-and-p-500" in url:
            return _CsvResponse(
                "Symbol,Security,GICS Sector\n"
                "AAPL,Apple Inc.,Information Technology\n"
            )
        return _CsvResponse(
            "Ticker,Company,GICS_Sector\n"
            "MSFT,Microsoft Corporation,Information Technology\n"
        )

    monkeypatch.setattr("quant_system.options.data_refresh.urlopen", flaky_urlopen)
    monkeypatch.setattr("quant_system.options.data_refresh.time.sleep", lambda _seconds: None)

    result = refresh_options_universe(path, source="github")

    assert result["status"] == "refreshed"
    assert result["row_count"] == 2
    text = path.read_text(encoding="utf-8")
    assert "AAPL" in text
    assert "MSFT" in text
    # two CSV downloads, each fails twice then succeeds => 3 + 3 calls
    assert calls["count"] == 6


def test_universe_refresh_raises_when_ssl_fails_and_no_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "missing_universe.csv"

    def failing_urlopen(request, timeout=30):  # noqa: ANN001
        raise URLError("SSL: UNEXPECTED_EOF_WHILE_READING")

    monkeypatch.setattr("quant_system.options.data_refresh.urlopen", failing_urlopen)
    monkeypatch.setattr("quant_system.options.data_refresh.time.sleep", lambda _seconds: None)

    try:
        refresh_options_universe(path, source="github")
        raise AssertionError("expected URLError")
    except URLError as exc:
        assert "UNEXPECTED_EOF" in str(exc)
