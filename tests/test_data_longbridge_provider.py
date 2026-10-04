from __future__ import annotations

import os
import signal
import sys
import time

import exchange_calendars
import pandas as pd
import pytest

from quant_system.data.providers import longbridge as lb


@pytest.fixture(autouse=True)
def no_transport_delay(monkeypatch):
    monkeypatch.setattr(lb, "_MIN_REQUEST_INTERVAL", 0)


@pytest.fixture
def transport(monkeypatch):
    calls = []
    client = lb.LongbridgeClient()
    monkeypatch.setattr(client, "_resolve_executable", lambda: "/fake/longbridge")

    def run(argv, environment):
        calls.append((argv, environment))
        return b'{"result": "ok"}', b"", 0

    monkeypatch.setattr(client, "_run", run)
    return client, calls


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("NVDA", "NVDA.US"),
        ("US", "US.US"),
        ("US.AAPL", "AAPL.US"),
        ("BRK.B", "BRK.B.US"),
        ("HK.00700", "700.HK"),
        ("00700.HK", "700.HK"),
        ("000001.SZ", "000001.SZ"),
        ("600519.SH", "600519.SH"),
        ("D05.SG", "D05.SG"),
        (".VIX.US", ".VIX.US"),
        ("AAPL260619C200000.US", "AAPL260619C200000.US"),
    ],
)
def test_normalize_symbol(given, expected):
    assert lb.normalize_longbridge_symbol(given) == expected


@pytest.mark.parametrize(
    "symbol",
    [
        "--help",
        "AAPL;env",
        "$(env)",
        "AAPL/US",
        "../AAPL",
        "AAPL US",
        "",
        "BTCUSD.HAS",
        "00000.HK",
        "AAPL.HK",
        "123.SZ",
        "123",
        None,
    ],
)
def test_reject_invalid_symbol(symbol):
    with pytest.raises(lb.LongbridgeProviderError, match="symbol"):
        lb.normalize_longbridge_symbol(symbol)


def test_transport_maps_only_explicit_read_operations_and_filters_environment(
    transport, monkeypatch
):
    client, calls = transport
    monkeypatch.setenv("LONGPORT_STAGING", "1")
    monkeypatch.setenv("LONGBRIDGE_HTTP_URL", "https://unexpected.invalid")
    monkeypatch.setenv("LONGPORT_ACCESS_TOKEN", "do-not-leak")
    payload = client.request("financial_statement", "US.NVDA", kind="CF", report="qf")
    assert payload == {"result": "ok"}
    assert calls[0][0] == [
        "/fake/longbridge",
        "financial-statement",
        "NVDA.US",
        "--kind",
        "CF",
        "--report",
        "qf",
        "--format",
        "json",
    ]
    assert all(not key.startswith(("LONGPORT", "LONGBRIDGE")) for key in calls[0][1])
    client.request("segments", "NVDA.US", report="af")
    assert "--history" in calls[1][0]
    client.request("segments", "NVDA.US")
    assert "--history" not in calls[2][0]


@pytest.mark.parametrize(
    ("operation", "params"),
    [
        ("order", {}),
        ("positions", {}),
        ("auth", {}),
        ("quote", {"url": "https://bad"}),
        ("quote", {"count": 1}),
        ("history", {"start": "2024-01-02"}),
        ("history", {"start": "2024-01-02", "end": "2024-01-05", "count": 1000}),
        ("history", {"start": "2024-01-05", "end": "2024-01-02"}),
        ("kline", {"count": 1001}),
        ("kline", {"count": True}),
        ("kline", {"period": "1m"}),
        ("kline", {"adjust": "qfq"}),
        ("financial_statement", {"kind": "ALL"}),
        ("financial_statement", {"report": ["qf"]}),
        ("calc_index", {"fields": "pe,--verbose"}),
        ("calc_index", {"fields": ["pe", "pe"]}),
        ("news", {"expiry": "2026-01-02"}),
    ],
)
def test_unlisted_operations_flags_and_values_never_start_process(transport, operation, params):
    client, calls = transport
    with pytest.raises(lb.LongbridgeProviderError) as error:
        client.request(operation, "AAPL", **params)
    assert error.value.code == "invalid_params"
    assert not calls


@pytest.mark.parametrize(
    ("out", "err", "rc", "code"),
    [
        (b"", b"301607 bearer SUPERSECRET", 1, "quota_exceeded"),
        (b"", b"301604 token SUPERSECRET", 1, "permission_denied"),
        (b"", b"429002 retry after 0.2 SUPERSECRET", 1, "rate_limited"),
        (b"", b"timeout SUPERSECRET", 1, "timeout"),
        (b"not-json SUPERSECRET", b"", 0, "invalid_json"),
        (b"[]", b"", 0, "empty"),
        (b'{"data":[]}', b"", 0, "empty"),
        (b'{"code":301604,"message":"SUPERSECRET"}', b"", 0, "permission_denied"),
        (b'{"error":{"code":301607,"message":"SUPERSECRET"}}', b"", 0, "quota_exceeded"),
    ],
)
def test_transport_safe_failures(transport, monkeypatch, out, err, rc, code):
    client, _ = transport
    monkeypatch.setattr(client, "_run", lambda *_: (out, err, rc))
    with pytest.raises(lb.LongbridgeProviderError) as error:
        client.request("quote", "AAPL")
    assert error.value.code == code
    assert "SUPERSECRET" not in str(error.value)


def test_missing_cli_fails_without_running(monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _: None)
    with pytest.raises(lb.LongbridgeProviderError) as error:
        lb.LongbridgeClient(executable="/not-installed/longbridge").request("quote", "AAPL")
    assert error.value.code == "not_installed"


def test_option_operations_are_read_only_and_expiry_maps_to_date(transport):
    client, calls = transport
    client.request("option_chain", "AAPL", expiry="2026-09-18")
    assert calls[0][0] == [
        "/fake/longbridge",
        "option",
        "chain",
        "AAPL.US",
        "--date",
        "2026-09-18",
        "--format",
        "json",
    ]
    client.request("option_quote", "AAPL260918C200000.US")
    assert calls[1][0][1:4] == ["option", "quote", "AAPL260918C200000.US"]


@pytest.mark.parametrize("symbol", ["AAPL.US", "AAPL261332C200000.US", "700.HK"])
def test_option_quote_rejects_noncontracts_and_invalid_expiry(transport, symbol):
    client, calls = transport
    with pytest.raises(lb.LongbridgeProviderError) as error:
        client.request("option_quote", symbol)
    assert error.value.code == "invalid_symbol"
    assert not calls


def test_subprocess_timeout_kills_process_group_and_bounds_runtime(monkeypatch):
    groups = []
    real_killpg = os.killpg

    def killpg(pid, sig):
        groups.append((pid, sig))
        return real_killpg(pid, sig)

    monkeypatch.setattr(lb.os, "killpg", killpg)
    before = time.monotonic()
    with pytest.raises(lb.LongbridgeProviderError) as error:
        lb.LongbridgeClient(timeout_seconds=0.2)._run(
            [sys.executable, "-c", "import os,time; os.fork(); time.sleep(20)"],
            dict(os.environ),
        )
    assert error.value.code == "timeout"
    assert time.monotonic() - before < 3
    assert len(groups) == 1
    assert groups[0][1] == signal.SIGKILL
    with pytest.raises(ProcessLookupError):
        os.kill(groups[0][0], 0)


def test_output_is_bounded(monkeypatch):
    monkeypatch.setattr(lb, "_MAX_STDOUT", 1024)
    with pytest.raises(lb.LongbridgeProviderError) as error:
        lb.LongbridgeClient(timeout_seconds=2)._run(
            [sys.executable, "-c", "print('x' * 10000)"],
            dict(os.environ),
        )
    assert error.value.code == "output_too_large"


def _bar(day, **overrides):
    result = {
        "time": f"{day}T05:00:00Z",
        "open": "10",
        "high": "12",
        "low": "9",
        "close": "11",
        "volume": "100",
    }
    result.update(overrides)
    return result


class BarClient:
    def __init__(self, transform=lambda rows: rows):
        self.calls = []
        self.transform = transform

    def request(self, operation, symbol, **params):
        self.calls.append((operation, symbol, params))
        calendar = exchange_calendars.get_calendar("XNYS", start="2019-01-01", end="2027-01-01")
        sessions = calendar.sessions_in_range(params["start"], params["end"])
        return self.transform([_bar(day.date().isoformat()) for day in sessions])


def test_daily_bars_have_forward_provenance_and_fetch_time():
    client = BarClient()
    result = lb.LongbridgeMarketDataProvider(client).fetch_ohlcv(
        ["AAPL"],
        start="2024-01-02",
        end="2024-01-05",
    )
    assert len(result) == 4
    assert set(result.provider) == {"longbridge"}
    assert set(result.price_adjustment) == {"forward"}
    assert set(result.symbol) == {"AAPL"}
    assert result.timestamp.iloc[0] == pd.Timestamp("2024-01-02", tz="UTC")
    assert result.knowledge_ts.min() > result.timestamp.max()
    assert client.calls[0][2]["adjust"] == "forward"


def test_long_history_is_partitioned_and_all_sessions_returned():
    client = BarClient()
    result = lb.LongbridgeMarketDataProvider(client).fetch_ohlcv(
        ["AAPL"],
        start="2020-01-02",
        end="2024-12-31",
    )
    calendar = exchange_calendars.get_calendar("XNYS", start="2019-01-01", end="2027-01-01")
    assert len(result) == len(calendar.sessions_in_range("2020-01-02", "2024-12-31"))
    assert len(result) > 1000
    assert len(client.calls) == 2
    assert not result.duplicated(["symbol", "timestamp"]).any()


@pytest.mark.parametrize(
    ("transform", "code"),
    [
        (lambda rows: rows[-1:], "incomplete_data"),
        (lambda rows: rows[:1] + rows[2:], "incomplete_data"),
        (lambda rows: [], "empty"),
        (lambda rows: rows + rows[:1], "invalid_data"),
        (lambda rows: [{**row, "close": "NaN"} for row in rows], "invalid_data"),
        (lambda rows: [{**row, "high": "8"} for row in rows], "invalid_data"),
        (lambda rows: [{**row, "volume": "-1"} for row in rows], "invalid_data"),
        (lambda rows: [{**row, "symbol": "MSFT.US"} for row in rows], "invalid_data"),
        (lambda rows: [{**row, "provider": "futu"} for row in rows], "invalid_data"),
        (lambda rows: [{**row, "price_adjustment": "qfq"} for row in rows], "invalid_data"),
    ],
)
def test_daily_data_fail_closed(transform, code):
    client = BarClient(transform)
    with pytest.raises(lb.LongbridgeProviderError) as error:
        lb.LongbridgeMarketDataProvider(client).fetch_ohlcv(
            ["AAPL"],
            start="2024-01-02",
            end="2024-01-05",
        )
    assert error.value.code == code
    assert len(client.calls) == 1


def test_history_permission_failure_never_replaced_by_latest_kline():
    class Denied:
        def __init__(self):
            self.calls = []

        def request(self, operation, *_args, **_kwargs):
            self.calls.append(operation)
            raise lb.LongbridgeProviderError("permission_denied")

    client = Denied()
    with pytest.raises(lb.LongbridgeProviderError) as error:
        lb.LongbridgeMarketDataProvider(client).fetch_ohlcv(
            ["AAPL"],
            start="2024-01-02",
            end="2024-01-05",
        )
    assert error.value.code == "permission_denied"
    assert client.calls == ["history"]


def test_only_completed_sessions_are_requested(monkeypatch):
    monkeypatch.setattr(lb, "_now_utc", lambda: pd.Timestamp("2024-01-05T15:00:00Z"))
    client = BarClient()
    result = lb.LongbridgeMarketDataProvider(client).fetch_ohlcv(
        ["AAPL"],
        start="2024-01-02",
        end="2024-01-08",
    )
    assert result.timestamp.max() == pd.Timestamp("2024-01-04", tz="UTC")
    assert client.calls[0][2]["end"] == "2024-01-04"


def test_unclosed_extra_bar_is_rejected(monkeypatch):
    monkeypatch.setattr(lb, "_now_utc", lambda: pd.Timestamp("2024-01-05T15:00:00Z"))
    client = BarClient(lambda rows: rows + [_bar("2024-01-05")])
    with pytest.raises(lb.LongbridgeProviderError) as error:
        lb.LongbridgeMarketDataProvider(client).fetch_ohlcv(
            ["AAPL"],
            start="2024-01-02",
            end="2024-01-05",
        )
    assert error.value.code == "invalid_data"


def test_hong_kong_timestamp_uses_exchange_session_date():
    class HKClient:
        def request(self, *_args, **_kwargs):
            return [_bar("2024-01-01", time="2024-01-01T16:00:00Z")]

    result = lb.LongbridgeMarketDataProvider(HKClient()).fetch_ohlcv(
        ["00700.HK"],
        start="2024-01-02",
        end="2024-01-02",
    )
    assert result.timestamp.iloc[0] == pd.Timestamp("2024-01-02", tz="UTC")
