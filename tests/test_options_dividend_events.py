from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.options.data_refresh import refresh_dividend_events
from quant_system.options.dividend_events import load_dividend_events

_UNIVERSE_CSV = "\n".join(
    [
        "ticker,name,sector,exchange,source",
        "AAPL,Apple Inc.,Information Technology,US,both",
        "BRK.B,Berkshire Hathaway,Financials,US,sp500",
        "NODIV,No Dividend Corp,Technology,US,sp500",
        "FAIL,Broken Corp,Financials,US,sp500",
    ]
)


def _write_universe(path: Path) -> None:
    path.write_text(_UNIVERSE_CSV + "\n", encoding="utf-8")


def _fake_yfinance(calendar_by_ticker: dict, dividends_by_ticker: dict):
    def Ticker(ticker: str):  # noqa: N802
        if ticker == "FAIL":
            raise RuntimeError("yfinance unavailable for FAIL")
        return SimpleNamespace(
            calendar=calendar_by_ticker.get(ticker),
            dividends=dividends_by_ticker.get(ticker, pd.Series(dtype=float)),
        )

    return SimpleNamespace(Ticker=Ticker)


def _install_fake_yfinance(monkeypatch) -> dict:
    recent_ex = date.today() + timedelta(days=20)
    recent_div = date.today() - timedelta(days=30)
    fake = _fake_yfinance(
        calendar_by_ticker={
            "AAPL": {"Ex-Dividend Date": recent_ex},
            "BRK-B": {"Ex-Dividend Date": recent_ex},
        },
        dividends_by_ticker={
            "AAPL": pd.Series([0.55], index=pd.to_datetime([recent_div.isoformat()])),
            "BRK-B": pd.Series([1.25], index=pd.to_datetime([recent_div.isoformat()])),
        },
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    return {"recent_ex": recent_ex}


def test_refresh_dividend_events_writes_events_and_no_dividend_assertions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_path = tmp_path / "universe.csv"
    _write_universe(universe_path)
    output_path = tmp_path / "dividend_events.csv"
    dates = _install_fake_yfinance(monkeypatch)

    result = refresh_dividend_events(
        output_path,
        universe_path=universe_path,
        source="public",
    )

    assert result["kind"] == "dividends"
    assert result["source"] == "yfinance"
    assert result["status"] == "refreshed"
    assert result["row_count"] == 3
    assert "FAIL" in result["warning"]

    events = load_dividend_events(output_path)
    assert events["AAPL"] == (dates["recent_ex"], 0.55)
    # The yfinance alias BRK-B is persisted under the canonical BRK.B ticker.
    assert events["BRK.B"] == (dates["recent_ex"], 1.25)
    # No dividends in 400 days and no calendar ex-date: explicit assertion.
    assert events["NODIV"] == (None, 0.0)
    # The failed ticker keeps no row at all (honest absence).
    assert "FAIL" not in events


def test_refresh_dividend_events_treats_old_dividends_as_no_dividend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "ticker,name,sector,exchange,source\nSTALE,Stale Corp,Financials,US,sp500\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "dividend_events.csv"
    fake = _fake_yfinance(
        calendar_by_ticker={"STALE": {}},
        dividends_by_ticker={
            "STALE": pd.Series([0.80], index=pd.to_datetime(["2020-01-15"])),
        },
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    result = refresh_dividend_events(
        output_path,
        universe_path=universe_path,
        source="yfinance",
    )

    assert result["row_count"] == 1
    assert load_dividend_events(output_path) == {"STALE": (None, 0.0)}


def test_refresh_dividend_events_fetches_tickers_concurrently(
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
        return SimpleNamespace(calendar={}, dividends=pd.Series(dtype=float))

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=ticker))

    result = refresh_dividend_events(
        tmp_path / "dividend_events.csv",
        universe_path=universe_path,
        source="yfinance",
    )

    assert result["row_count"] == 2
    assert set(entered) == {"AAA", "BBB"}


def test_refresh_dividend_events_keeps_existing_when_all_tickers_fail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "ticker,name,sector,exchange,source\nFAIL,Broken Corp,Financials,US,sp500\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "dividend_events.csv"
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance({}, {}))

    with pytest.raises(RuntimeError, match="returned no rows"):
        refresh_dividend_events(
            output_path,
            universe_path=universe_path,
            source="yfinance",
        )
    assert not output_path.exists()

    output_path.write_text(
        "ticker,ex_dividend_date,dividend_per_share,source,fetched_at\n"
        "FAIL,2026-03-01,0.40,yfinance,2026-01-01T00:00:00+00:00\n",
        encoding="utf-8",
    )
    result = refresh_dividend_events(
        output_path,
        universe_path=universe_path,
        source="yfinance",
    )
    assert result["status"] == "kept_existing"
    assert result["row_count"] == 1


def test_refresh_dividend_events_rejects_unknown_source(tmp_path: Path) -> None:
    universe_path = tmp_path / "universe.csv"
    _write_universe(universe_path)

    with pytest.raises(ValueError, match="source must be"):
        refresh_dividend_events(
            tmp_path / "dividend_events.csv",
            universe_path=universe_path,
            source="robinhood",
        )


def test_refresh_dividend_events_sample_source_never_calls_yfinance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    universe_path = tmp_path / "universe.csv"
    _write_universe(universe_path)
    output_path = tmp_path / "dividend_events.csv"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("sample dividend refresh must not touch yfinance")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=forbidden))

    result = refresh_dividend_events(
        output_path,
        universe_path=universe_path,
        source="sample",
    )

    assert result["source"] == "sample"
    assert result["row_count"] == 4
    events = load_dividend_events(output_path)
    assert set(events) == {"AAPL", "BRK.B", "NODIV", "FAIL"}
    assert all(event == (None, 0.0) for event in events.values())


def test_load_dividend_events_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_dividend_events(tmp_path / "missing.csv") == {}


def test_load_dividend_events_requires_columns(tmp_path: Path) -> None:
    path = tmp_path / "dividend_events.csv"
    path.write_text("ticker,amount\nAAPL,0.55\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing columns"):
        load_dividend_events(path)
