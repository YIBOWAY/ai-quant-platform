import json

import pytest

from quant_system.config.settings import Settings
from quant_system.data.providers.longbridge import LongbridgeProviderError
from quant_system.research import company_research as company
from quant_system.research import data_source_checks as service


@pytest.fixture
def settings(tmp_path, monkeypatch):
    value = Settings()
    value.data.data_dir = tmp_path
    monkeypatch.setattr(service, "_installed", lambda: (True, "longbridge 0.28.5"))
    return value


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"status": "available", "checks": "not_a_list"},
        {"status": "available", "checks": [], "default_provider": "sample"},
        {"status": "available", "checks": [], "checked_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_corrupt_cache_never_becomes_readiness_or_500(settings, payload):
    path = company._root(settings) / "capabilities/current.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))
    result = service.read_checks(settings)
    assert result["status"] == "failed"
    assert result["default_provider"] == "futu"
    assert isinstance(result["checks"], list)


def test_nonempty_but_invalid_market_data_does_not_pass(settings):
    class InvalidClient:
        def request(self, op, symbol, **params):
            if op == "financial_statement":
                return {"currency": "USD", "report": "qf", "list": [{"fields": []}]}
            return [{"symbol": "WRONG.US", "last_done": "0", "timestamp": None}]

    result = service.collect_checks(
        settings, "700.HK", client=InvalidClient(), quote_reader=lambda *_: {"last": None}
    )
    assert result["status"] == "failed"
    assert all(row["status"] == "unavailable" for row in result["checks"])


def test_empty_differs_from_malformed(settings):
    class Empty:
        def request(self, *_args, **_kwargs):
            return []

    result = service.collect_checks(
        settings,
        "700.HK",
        client=Empty(),
        quote_reader=lambda *_: {"symbol": "700.HK", "last": 100},
    )
    by_key = {r["key"]: r for r in result["checks"]}
    assert by_key["futu_quote"]["status"] == "available"
    assert by_key["longbridge_quote"]["status"] == "empty"


def test_recent_checks_actual_ohlcv_and_completed_date_coverage():
    rows = [
        {
            "time": f"2024-01-{day:02}T05:00:00Z",
            "open": "10",
            "high": "12",
            "low": "9",
            "close": "11",
            "volume": "100",
        }
        for day in (2, 3, 4, 5)
    ]
    service._valid_recent(rows, "AAPL.US", now="2024-01-05T22:00:00Z")
    with pytest.raises(LongbridgeProviderError):
        service._valid_recent(rows[:1] + rows[-1:], "AAPL.US", now="2024-01-05T22:00:00Z")
    with pytest.raises(LongbridgeProviderError):
        service._valid_recent(rows, "AAPL.US", now="2024-02-05T22:00:00Z")
