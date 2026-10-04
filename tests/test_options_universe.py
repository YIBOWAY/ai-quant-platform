from __future__ import annotations

from pathlib import Path

import pytest

from quant_system.options.radar import CURATED_RECOMMENDATION_TICKERS
from quant_system.options.universe import OptionsUniverse


def test_options_universe_loads_and_deduplicates_by_ticker(tmp_path: Path) -> None:
    path = tmp_path / "universe.csv"
    path.write_text(
        "\n".join(
            [
                "ticker,name,sector,exchange,source",
                "AAPL,Apple Inc.,Technology,NASDAQ,sp500",
                "MSFT,Microsoft Corp.,Technology,NASDAQ,both",
                "AAPL,Apple Inc.,Technology,NASDAQ,nasdaq100",
            ]
        ),
        encoding="utf-8",
    )

    entries = OptionsUniverse.load(path)

    assert [entry.ticker for entry in entries] == ["AAPL", "MSFT"]
    assert entries[0].source == "both"


def test_options_universe_top_n_preserves_file_priority(tmp_path: Path) -> None:
    path = tmp_path / "universe.csv"
    path.write_text(
        "\n".join(
            [
                "ticker,name,sector,exchange,source",
                "MSFT,Microsoft Corp.,Technology,NASDAQ,both",
                "AAPL,Apple Inc.,Technology,NASDAQ,both",
                "NVDA,NVIDIA Corp.,Technology,NASDAQ,both",
            ]
        ),
        encoding="utf-8",
    )

    entries = OptionsUniverse.load(path, top_n=2)

    assert [entry.ticker for entry in entries] == ["MSFT", "AAPL"]


def test_options_universe_rejects_unknown_source(tmp_path: Path) -> None:
    path = tmp_path / "universe.csv"
    path.write_text(
        "\n".join(
            [
                "ticker,name,sector,exchange,source",
                "AAPL,Apple Inc.,Technology,NASDAQ,unknown",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown universe source"):
        OptionsUniverse.load(path)


def test_curated_wheel_universe_is_the_exact_owner_list() -> None:
    entries = OptionsUniverse.load(Path("data/options_universe/curated_wheel.csv"))

    assert tuple(entry.ticker for entry in entries) == CURATED_RECOMMENDATION_TICKERS

    expected = {
        "SPY",
        "QQQ",
        "AAPL",
        "MSFT",
        "NVDA",
        "GOOGL",
        "AMZN",
        "META",
        "TSLA",
        "SOXX",
        "SMH",
        "IGV",
        "XLY",
        "XLP",
        "XLF",
        "XLV",
        "XLE",
        "AVGO",
        "AMD",
        "TSM",
        "MU",
        "SNDK",
        "CRM",
        "ORCL",
        "COST",
        "KO",
        "MCD",
        "JPM",
        "GS",
        "BRK.B",
        "LLY",
        "UNH",
        "XOM",
        "CVX",
    }

    assert len(entries) == 34
    assert {entry.ticker for entry in entries} == expected
    assert len({entry.ticker for entry in entries}) == len(entries)
    assert {entry.source for entry in entries} == {
        "core_etf",
        "m7",
        "sector_etf",
        "sector_leader",
    }
