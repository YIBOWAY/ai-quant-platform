from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from urllib.error import URLError

from quant_system.options.data_refresh import (
    _next_earnings_date,
    fetch_screener_events,
    refresh_earnings_calendar,
    refresh_options_universe,
    refresh_vix_history,
)


def test_single_symbol_events_keep_missing_evidence_distinct_from_zero_dividend(monkeypatch):
    import pandas as pd

    instruments = {
        "DELL": SimpleNamespace(calendar={"Earnings Date": [date(2026, 11, 28)]}),
        "ZERO": SimpleNamespace(calendar={}, dividends=pd.Series(dtype=float)),
        "MISSING": SimpleNamespace(),
    }
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=instruments.__getitem__))
    assert fetch_screener_events("DELL", earnings=True, dividends=False) == (
        date(2026, 11, 28), None,
    )
    assert fetch_screener_events("ZERO", earnings=False, dividends=True) == (None, (None, 0.0))
    assert fetch_screener_events("MISSING", earnings=True, dividends=True) == (None, None)


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


def test_nasdaq_earnings_maps_brk_provider_alias_to_canonical_ticker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,name,sector,exchange,source",
                "BRK.B,Berkshire Hathaway,Financials,NYSE,sector_leader",
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "earnings.csv"

    def fake_urlopen(request, timeout=30):  # noqa: ANN001
        rows = [{"symbol": "BRK.B"}] if "2026-06-03" in request.full_url else []
        return _FakeResponse({"data": {"rows": rows}})

    monkeypatch.setattr("quant_system.options.data_refresh.urlopen", fake_urlopen)

    result = refresh_earnings_calendar(
        universe_path=universe_path,
        output_path=output_path,
        source="nasdaq",
        today=date(2026, 5, 31),
    )

    assert result["row_count"] == 1
    assert "BRK.B,2026-06-03" in output_path.read_text(encoding="utf-8")


def test_next_earnings_date_reads_yfinance_list_calendar() -> None:
    class Ticker:
        def __init__(self, _symbol: str) -> None:
            self.calendar = {"Earnings Date": [date(2026, 10, 30)]}

    module = type("Module", (), {"Ticker": Ticker})
    assert _next_earnings_date(module, "AAPL") == "2026-10-30"


def test_yfinance_earnings_uses_brk_dash_alias_but_persists_canonical_ticker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,name,sector,exchange,source",
                "BRK.B,Berkshire Hathaway,Financials,NYSE,sector_leader",
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "earnings.csv"
    requested: list[str] = []

    class Ticker:
        def __init__(self, symbol: str) -> None:
            requested.append(symbol)
            self.calendar = {"Earnings Date": [date(2026, 11, 8)]}

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=Ticker))

    result = refresh_earnings_calendar(
        universe_path=universe_path,
        output_path=output_path,
        source="yfinance",
    )

    assert requested == ["BRK-B"]
    assert result["row_count"] == 1
    assert "BRK.B,2026-11-08" in output_path.read_text(encoding="utf-8")


def test_yfinance_earnings_fetches_tickers_concurrently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "ticker,name,sector,exchange,source\n"
        "AAA,Alpha,Technology,US,sp500\n"
        "BBB,Beta,Technology,US,sp500\n",
        encoding="utf-8",
    )
    entered: list[str] = []
    lock = Lock()
    both_entered = Event()

    def ticker(symbol: str):
        with lock:
            entered.append(symbol)
            if len(entered) == 2:
                both_entered.set()
        if not both_entered.wait(0.5):
            raise RuntimeError("ticker fetches ran sequentially")
        return SimpleNamespace(calendar={"Earnings Date": [date(2026, 11, 8)]})

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=ticker))

    result = refresh_earnings_calendar(
        universe_path=universe_path,
        output_path=tmp_path / "earnings.csv",
        source="yfinance",
    )

    assert result["row_count"] == 2
    assert set(entered) == {"AAA", "BBB"}


def test_public_earnings_falls_back_to_yfinance_when_nasdaq_is_sparse(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_lines = ["ticker,name,sector,exchange,source"]
    universe_lines.extend(
        f"T{index:02d},Name {index},Information Technology,US,both"
        for index in range(20)
    )
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text("\n".join(universe_lines) + "\n", encoding="utf-8")
    output_path = tmp_path / "earnings.csv"

    monkeypatch.setattr(
        "quant_system.options.data_refresh._fetch_nasdaq_earnings_rows",
        lambda *args, **kwargs: [{"ticker": "T00", "earnings_date": "2026-06-03"}],
    )
    monkeypatch.setattr(
        "quant_system.options.data_refresh._fetch_yfinance_earnings_rows",
        lambda entries: [
            {"ticker": entry.ticker, "earnings_date": "2026-10-15"} for entry in entries
        ],
    )

    result = refresh_earnings_calendar(
        universe_path=universe_path,
        output_path=output_path,
        source="public",
        today=date(2026, 5, 31),
    )

    assert result["source"] == "yfinance"
    assert result["row_count"] == 20
    assert result["status"] == "refreshed"
    text = output_path.read_text(encoding="utf-8")
    assert text.count("\n") == 21
    assert "T19,2026-10-15" in text


def test_public_earnings_falls_back_to_yfinance_when_nasdaq_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,name,sector,exchange,source",
                "AAPL,Apple,Information Technology,US,both",
                "MSFT,Microsoft,Information Technology,US,both",
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "earnings.csv"

    def boom(*_args, **_kwargs):
        raise RuntimeError("Nasdaq earnings calendar did not return any usable responses")

    monkeypatch.setattr(
        "quant_system.options.data_refresh._fetch_nasdaq_earnings_rows",
        boom,
    )
    monkeypatch.setattr(
        "quant_system.options.data_refresh._fetch_yfinance_earnings_rows",
        lambda entries: [
            {"ticker": entry.ticker, "earnings_date": "2026-11-01"} for entry in entries
        ],
    )

    result = refresh_earnings_calendar(
        universe_path=universe_path,
        output_path=output_path,
        source="public",
        today=date(2026, 5, 31),
    )

    assert result["source"] == "yfinance"
    assert result["row_count"] == 2
    assert "AAPL,2026-11-01" in output_path.read_text(encoding="utf-8")


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
    monkeypatch.setattr(
        "quant_system.options.data_refresh._fetch_yfinance_earnings_rows",
        lambda _entries: [],
    )

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


def test_public_earnings_merges_sparse_refresh_into_richer_existing_calendar(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_lines = ["ticker,name,sector,exchange,source"]
    universe_lines.extend(
        f"T{index:02d},Name {index},Information Technology,US,both"
        for index in range(20)
    )
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text("\n".join(universe_lines) + "\n", encoding="utf-8")
    output_path = tmp_path / "earnings.csv"
    existing = ["ticker,earnings_date"] + [
        f"T{index:02d},2026-10-{(index % 28) + 1:02d}" for index in range(80)
    ]
    output_path.write_text("\n".join(existing) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "quant_system.options.data_refresh._fetch_nasdaq_earnings_rows",
        lambda *args, **kwargs: [{"ticker": "T00", "earnings_date": "2026-06-03"}],
    )
    monkeypatch.setattr(
        "quant_system.options.data_refresh._fetch_yfinance_earnings_rows",
        lambda _entries: [],
    )

    result = refresh_earnings_calendar(
        universe_path=universe_path,
        output_path=output_path,
        source="public",
        today=date(2026, 5, 31),
    )
    assert result["status"] == "refreshed"
    assert result["row_count"] == 80
    refreshed = output_path.read_text(encoding="utf-8")
    assert refreshed.count("\n") == 81
    assert "T00,2026-06-03" in refreshed
    assert "T79,2026-10-24" in refreshed


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


def test_refresh_vix_kept_existing_warns_when_last_row_is_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import pandas as pd

    from quant_system.options.vix_data import save_vix_history

    path = tmp_path / "vix.csv"
    idx = pd.date_range("2025-12-01", periods=20, freq="B")
    save_vix_history(path, pd.Series(15.0, index=idx), pd.Series(17.0, index=idx))
    before = path.read_bytes()

    monkeypatch.setattr(
        "quant_system.options.data_refresh.fetch_vix_history",
        lambda **kwargs: (pd.Series(dtype="float64"), None),
    )
    result = refresh_vix_history(path, source="public", end=date(2026, 8, 19))
    assert result["status"] == "kept_existing"
    assert "warning" in result
    assert "stale" in str(result["warning"]).lower()
    assert path.read_bytes() == before
