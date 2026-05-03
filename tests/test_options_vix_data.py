from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quant_system.options.market_regime import compute_vix_regime
from quant_system.options.vix_data import (
    fetch_vix_history,
    fetch_yahoo_chart,
    load_vix_history,
    save_vix_history,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload or {}


def _payload(timestamps: list[int], closes: list[float | None]) -> dict:
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {"quote": [{"close": closes}]},
                }
            ],
        }
    }


def test_fetch_yahoo_chart_parses_payload() -> None:
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(
            200,
            _payload(
                [1_700_000_000, 1_700_086_400, 1_700_172_800],
                [15.0, None, 17.5],
            ),
        )

    series = fetch_yahoo_chart(
        "^VIX",
        date(2024, 11, 1),
        date(2024, 11, 30),
        http_get=fake_get,
    )
    assert "query1.finance.yahoo.com" in captured["url"]
    assert "^VIX" in captured["url"]
    assert "period1" in captured["params"]
    assert list(series.values) == [15.0, 17.5]
    assert len(series) == 2


def test_fetch_yahoo_chart_handles_non_200() -> None:
    series = fetch_yahoo_chart(
        "^VIX",
        date(2024, 1, 1),
        date(2024, 2, 1),
        http_get=lambda *a, **kw: _FakeResponse(429, None),
    )
    assert series.empty


def test_fetch_yahoo_chart_handles_yahoo_error() -> None:
    payload = {"chart": {"error": {"code": "Not Found"}, "result": None}}
    series = fetch_yahoo_chart(
        "^VIX",
        date(2024, 1, 1),
        date(2024, 2, 1),
        http_get=lambda *a, **kw: _FakeResponse(200, payload),
    )
    assert series.empty


def test_save_and_load_vix_history_round_trip(tmp_path: Path) -> None:
    idx = pd.date_range("2024-01-01", periods=4, freq="B")
    vix = pd.Series([14.0, 15.5, 16.2, 17.1], index=idx)
    vix3m = pd.Series([15.0, 16.0, 16.8, 17.4], index=idx)
    target = tmp_path / "vix_history.csv"
    save_vix_history(target, vix, vix3m)
    loaded_vix, loaded_vix3m = load_vix_history(target)
    assert list(loaded_vix.values) == pytest.approx([14.0, 15.5, 16.2, 17.1])
    assert loaded_vix3m is not None
    assert list(loaded_vix3m.values) == pytest.approx([15.0, 16.0, 16.8, 17.4])


def test_load_vix_history_missing_returns_empty(tmp_path: Path) -> None:
    vix, vix3m = load_vix_history(tmp_path / "nope.csv")
    assert vix.empty
    assert vix3m is None


def test_fetch_vix_history_calls_both_tickers() -> None:
    seen: list[str] = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append(url)
        return _FakeResponse(200, _payload([1_700_000_000], [16.0]))

    vix, vix3m = fetch_vix_history(end=date(2025, 1, 1), http_get=fake_get)
    joined = " ".join(seen)
    assert "%5EVIX" in joined or "^VIX" in joined
    assert "%5EVIX3M" in joined or "^VIX3M" in joined
    assert not vix.empty
    assert not vix3m.empty


def test_save_and_compute_regime_pipeline(tmp_path: Path) -> None:
    """Round-trip: save → load → compute_vix_regime should yield a valid regime."""
    idx = pd.date_range("2024-06-01", periods=260, freq="B")
    # Build a regime that should clearly resolve to Panic: a low-VIX baseline
    # so the rolling 75th-percentile threshold stays modest, then a sustained
    # spike across the most recent month with VIX > VIX3M (backwardation).
    base = [14.0] * (len(idx) - 22)
    spike = [32.0] * 22
    vix = pd.Series(base + spike, index=idx)
    vix3m = pd.Series([18.0] * len(idx), index=idx)
    target = tmp_path / "vix_history.csv"
    save_vix_history(target, vix, vix3m)
    loaded_vix, loaded_vix3m = load_vix_history(target)
    snapshot = compute_vix_regime(
        loaded_vix,
        loaded_vix3m,
        signal_date=loaded_vix.index.max(),
    )
    assert snapshot.volatility_regime == "Panic"
    assert snapshot.w_vix == pytest.approx(0.35)
