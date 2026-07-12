from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.data.price_history import (
    HistoricalPriceReadError,
    read_historical_prices,
)


class _Provider:
    provider_name = "futu"

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[dict[str, object]] = []

    def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
        self.calls.append(
            {
                "symbols": symbols,
                "start": start,
                "end": end,
                "interval": interval,
            }
        )
        return self.frame.copy()


def _frame() -> pd.DataFrame:
    fetched_at = pd.Timestamp("2026-07-10T16:00:00Z")
    return pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "timestamp": pd.Timestamp("2026-07-09T00:00:00Z"),
                "close": 201.0,
                "provider": "futu",
                "interval": "1d",
                "price_adjustment": "qfq",
                "knowledge_ts": fetched_at,
            },
            {
                "symbol": "MSFT",
                "timestamp": pd.Timestamp("2026-07-08T00:00:00Z"),
                "close": 500.0,
                "provider": "futu",
                "interval": "1d",
                "price_adjustment": "qfq",
                "knowledge_ts": fetched_at,
            },
            {
                "symbol": "AAPL",
                "timestamp": pd.Timestamp("2026-07-08T00:00:00Z"),
                "close": 200.0,
                "provider": "futu",
                "interval": "1d",
                "price_adjustment": "qfq",
                "knowledge_ts": fetched_at,
            },
            {
                "symbol": "MSFT",
                "timestamp": pd.Timestamp("2026-07-09T00:00:00Z"),
                "close": 505.0,
                "provider": "futu",
                "interval": "1d",
                "price_adjustment": "qfq",
                "knowledge_ts": fetched_at,
            },
        ]
    )


def _read(frame: pd.DataFrame, **overrides):
    provider = _Provider(frame)
    builder_calls = []

    def builder(settings, *, requested):
        builder_calls.append((settings, requested))
        return provider, "futu"

    kwargs = {
        "settings": SimpleNamespace(),
        "symbols": ["msft", "AAPL"],
        "start": "2026-07-08",
        "end": "2026-07-09",
        "provider": "futu",
        "provider_builder": builder,
    }
    kwargs.update(overrides)
    snapshot = read_historical_prices(**kwargs)
    return snapshot.to_dict(), provider, builder_calls


def test_reads_all_symbols_once_and_emits_deterministic_qfq_contract() -> None:
    payload, provider, builder_calls = _read(_frame())

    assert builder_calls[0][1] == "futu"
    assert provider.calls == [
        {
            "symbols": ["MSFT", "AAPL"],
            "start": "2026-07-08",
            "end": "2026-07-09",
            "interval": "1d",
        }
    ]
    assert payload == {
        "schema_version": "1.0",
        "provider": "futu",
        "source": "futu",
        "interval": "1d",
        "adjustment": "qfq",
        "start": "2026-07-08",
        "end": "2026-07-09",
        "fetched_at": "2026-07-10T16:00:00+00:00",
        "symbols": ["MSFT", "AAPL"],
        "series": [
            {
                "symbol": "MSFT",
                "row_count": 2,
                "first_date": "2026-07-08",
                "last_date": "2026-07-09",
                "rows": [
                    {"date": "2026-07-08", "close": 500.0},
                    {"date": "2026-07-09", "close": 505.0},
                ],
            },
            {
                "symbol": "AAPL",
                "row_count": 2,
                "first_date": "2026-07-08",
                "last_date": "2026-07-09",
                "rows": [
                    {"date": "2026-07-08", "close": 200.0},
                    {"date": "2026-07-09", "close": 201.0},
                ],
            },
        ],
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "sample"},
        {"symbols": []},
        {"symbols": ["AAPL", "US.AAPL"]},
        {"symbols": ["HK.00700"]},
        {"start": "2026-07-10", "end": "2026-07-09"},
        {"start": "not-a-date"},
        {"start": "20260708"},
        {"start": "2025-01-01", "end": "2026-07-09"},
    ],
)
def test_rejects_unsafe_or_ambiguous_requests_before_provider(overrides) -> None:
    with pytest.raises(HistoricalPriceReadError) as excinfo:
        _read(_frame(), **overrides)

    assert excinfo.value.code == "historical_prices_invalid_request"


def test_historical_price_window_limit_counts_both_endpoint_dates() -> None:
    payload, provider, _builder_calls = _read(
        _frame(),
        start="2025-02-26",
        end="2026-07-10",
    )

    assert payload["start"] == "2025-02-26"
    assert provider.calls

    with pytest.raises(HistoricalPriceReadError) as excinfo:
        _read(
            _frame(),
            start="2025-02-25",
            end="2026-07-10",
        )

    assert excinfo.value.code == "historical_prices_invalid_request"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda frame: frame[frame["symbol"] != "MSFT"],
        lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
        lambda frame: frame.assign(provider="sample"),
        lambda frame: frame.assign(interval="1h"),
        lambda frame: frame.assign(price_adjustment="raw"),
        lambda frame: frame.assign(close=0.0),
        lambda frame: frame.assign(timestamp=pd.Timestamp("2026-07-10T00:00:00Z")),
    ],
)
def test_rejects_partial_or_drifted_provider_contracts(mutate) -> None:
    with pytest.raises(HistoricalPriceReadError) as excinfo:
        _read(mutate(_frame()))

    assert excinfo.value.code == "historical_prices_contract_invalid"
