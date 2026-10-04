from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import OptionsRadarSettings, Settings
from quant_system.data.providers.futu import FutuProviderError
from quant_system.data.schema import normalize_ohlcv_dataframe


def test_screener_resolves_missing_events_and_passes_cached_dividend(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from quant_system.api.routes import options as options_route
    from quant_system.options.models import OptionsScreenerConfig

    earnings_path = tmp_path / "earnings.csv"
    earnings_path.write_text("ticker,earnings_date\nDELL,2026-09-02\n")
    dividend_path = tmp_path / "dividends.csv"
    dividend_path.write_text("ticker,ex_dividend_date,dividend_per_share\nDELL,2026-10-20,0.525\n")
    captured = {}
    calls = []

    def live_events(ticker, *, earnings, dividends):
        calls.append((ticker, earnings, dividends))
        return date(2026, 11, 28), None

    def screen(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(model_dump=lambda **_: {})

    monkeypatch.setattr(options_route, "fetch_screener_events", live_events, raising=False)
    monkeypatch.setattr(options_route, "run_options_screener", screen)
    monkeypatch.setattr(options_route, "_server_market_session", lambda: date(2026, 9, 4))
    settings = Settings(options_radar=OptionsRadarSettings(
        earnings_calendar_path=earnings_path,
        dividend_events_path=dividend_path,
        vix_history_path=tmp_path / "vix.csv",
    ))

    options_route.options_screener(
        OptionsScreenerConfig(ticker="DELL", strategy_type="covered_call"), settings,
    )

    assert calls == [("DELL", True, False)]
    assert captured["earnings_calendar"].next_earnings("DELL", date(2026, 9, 4)) == date(
        2026, 11, 28,
    )
    assert captured["dividend_event"] == (date(2026, 10, 20), 0.525)
    assert earnings_path.read_text() == "ticker,earnings_date\nDELL,2026-09-02\n"


def _history() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2026-01-02", "2026-05-01", freq="B", tz="UTC")
    for index, timestamp in enumerate(dates):
        price = 220.0 + index * 0.2
        rows.append(
            {
                "symbol": "AAPL",
                "timestamp": timestamp,
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 1000,
                "event_ts": timestamp,
                "knowledge_ts": timestamp,
            }
        )
    return normalize_ohlcv_dataframe(pd.DataFrame(rows), provider="futu", interval="1d")


def _option_quotes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "US.AAPL260619P250000",
                "underlying": "US.AAPL",
                "option_type": "PUT",
                "expiry": "2026-06-19",
                "strike": 250.0,
                "bid": 2.0,
                "ask": 2.2,
                "volume": 100,
                "open_interest": 500,
                "implied_volatility": 0.45,
                "delta": -0.25,
                "update_time": "2026-05-01 15:59:00",
            }
        ]
    )


@pytest.mark.parametrize(
    ("now", "expected_session"),
    (
        (
            datetime(2026, 8, 25, 9, 29, tzinfo=ZoneInfo("America/New_York")),
            date(2026, 8, 24),
        ),
        (
            datetime(2026, 8, 25, 9, 30, tzinfo=ZoneInfo("America/New_York")),
            date(2026, 8, 25),
        ),
    ),
)
def test_server_market_session_uses_options_open_boundary(
    now: datetime,
    expected_session: date,
) -> None:
    from quant_system.api.routes import options as options_route

    assert options_route._server_market_session(now=now) == expected_session


def test_options_chain_returns_futu_contracts(tmp_path, monkeypatch) -> None:
    def fake_fetch(self, underlying, *, expiration, option_type="ALL"):
        return _option_quotes()

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes",
        fake_fetch,
    )
    settings = Settings(
        options_radar=OptionsRadarSettings(vix_history_path=tmp_path / "missing_vix.csv")
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(
        "/api/options/chain",
        params={"ticker": "AAPL", "expiration": "2026-06-19", "provider": "futu"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "futu"
    assert payload["contracts"][0]["symbol"] == "US.AAPL260619P250000"
    assert payload["safety"]["live_trading_enabled"] is False


def test_options_screener_returns_candidates_with_stale_unselected_atm_rows(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.api.routes import options as options_route
    from quant_system.options import screener as screener_module

    captured: dict[str, object] = {}
    original_run = options_route.run_options_screener
    original_server_market_session = options_route._server_market_session

    class PinnedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            pinned = datetime(2026, 5, 4, 4, 21, tzinfo=ZoneInfo("UTC"))
            return pinned.astimezone(tz) if tz is not None else pinned.replace(tzinfo=None)

    def capture_run(**kwargs):
        captured.update(kwargs)
        return original_run(**kwargs)

    monkeypatch.setattr(options_route, "run_options_screener", capture_run)
    monkeypatch.setattr(screener_module, "datetime", PinnedDateTime)
    monkeypatch.setattr(
        options_route,
        "_server_market_session",
        lambda: original_server_market_session(
            now=datetime(2026, 5, 4, 0, 20, tzinfo=ZoneInfo("America/New_York"))
        ),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_expirations",
        lambda self, underlying: pd.DataFrame(
            [{"strike_time": "2026-06-19", "option_expiry_date_distance": 48}]
        ),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes",
        lambda self, underlying, *, expiration, option_type="ALL": _option_quotes(),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, **kwargs: pd.DataFrame(
            [
                {
                    "symbol": "US.AAPL260531C250000",
                    "underlying": "US.AAPL",
                    "option_type": "CALL",
                    "expiry": "2026-05-31",
                    "strike": 250.0,
                    "bid": 30.0,
                    "ask": 30.2,
                    "implied_volatility": 0.30,
                    "update_time": "2026-04-30 15:59:00",
                },
                {
                    "symbol": "US.AAPL260531P250000",
                    "underlying": "US.AAPL",
                    "option_type": "PUT",
                    "expiry": "2026-05-31",
                    "strike": 250.0,
                    "bid": 0.8,
                    "ask": 1.0,
                    "implied_volatility": 0.30,
                    "update_time": "2026-04-30 15:59:00",
                },
                {
                    "symbol": "US.AAPL260531C280000",
                    "underlying": "US.AAPL",
                    "option_type": "CALL",
                    "expiry": "2026-05-31",
                    "strike": 280.0,
                    "bid": 5.0,
                    "ask": 5.2,
                    "implied_volatility": 0.30,
                    "update_time": "2026-05-01 15:59:00",
                },
                {
                    "symbol": "US.AAPL260531P280000",
                    "underlying": "US.AAPL",
                    "option_type": "PUT",
                    "expiry": "2026-05-31",
                    "strike": 280.0,
                    "bid": 4.8,
                    "ask": 5.0,
                    "implied_volatility": 0.30,
                    "update_time": "2026-05-01 15:59:00",
                },
            ]
        ),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {
            "symbol": "US.AAPL",
            "last": 280.0,
            "prev_close": 279.0,
            "volume": 1_000_000,
            "update_time": "2026-05-04 00:20:00",
        },
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=tmp_path / "scans",
            vix_history_path=tmp_path / "missing_vix.csv",
            earnings_calendar_path=tmp_path / "earnings.csv",
        )
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/options/screener",
        json={
            "ticker": "AAPL",
            "strategy_type": "sell_put",
            "min_iv": 0.2,
            "max_delta": 0.35,
            "min_premium": 1.0,
            "max_spread_pct": 0.2,
            "provider": "futu",
            "history_start": "2026-01-02",
            "history_end": "2026-05-01",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["provider"] == "futu"
    assert payload["expiration"] is None
    assert payload["scanned_expirations"] == ["2026-06-19"]
    assert payload["expiration_count"] == 1
    assert payload["underlying_price"] == 280.0
    assert payload["candidates"][0]["rating"] == "Strong"
    assert payload["safety"]["paper_trading"] is True
    assert captured["risk_free_rate"] == settings.options_radar.risk_free_rate
    assert captured["iv_history_dir"] == settings.options_radar.output_dir / "iv_history"
    assert captured["earnings_calendar"].dates_by_ticker == {}
    assert captured["is_etf"] is False


def test_options_screener_drops_contract_identity_mismatch_rows(
    tmp_path,
    monkeypatch,
) -> None:
    # Incident shape: the symbol encodes 2026-01-01 CALL strike 999 while the
    # declared fields claim 2026-05-31 PUT strike 95. The contradictory row
    # must never reach the visible output, even though its quotes are clean.
    from quant_system.api.routes import options as options_route

    def fake_quotes(self, underlying, *, expiration, option_type="ALL"):
        contradictory = pd.DataFrame(
            [
                {
                    "symbol": "US.AAPL260101C999000",
                    "underlying": "US.AAPL",
                    "option_type": "PUT",
                    "expiry": "2026-05-31",
                    "strike": 95.0,
                    "bid": 2.0,
                    "ask": 2.2,
                    "volume": 100,
                    "open_interest": 500,
                    "implied_volatility": 0.45,
                    "delta": -0.25,
                    "update_time": "2026-05-01 15:59:00",
                }
            ]
        )
        return pd.concat([_option_quotes(), contradictory], ignore_index=True)

    monkeypatch.setattr(options_route, "_server_market_session", lambda: date(2026, 5, 1))
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_expirations",
        lambda self, underlying: pd.DataFrame(
            [{"strike_time": "2026-06-19", "option_expiry_date_distance": 48}]
        ),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes",
        fake_quotes,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, **kwargs: pd.DataFrame(
            [
                {
                    "symbol": "US.AAPL260531C280000",
                    "underlying": "US.AAPL",
                    "option_type": "CALL",
                    "expiry": "2026-05-31",
                    "strike": 280.0,
                    "bid": 5.0,
                    "ask": 5.2,
                    "implied_volatility": 0.30,
                    "update_time": "2026-05-01 15:59:00",
                },
                {
                    "symbol": "US.AAPL260531P280000",
                    "underlying": "US.AAPL",
                    "option_type": "PUT",
                    "expiry": "2026-05-31",
                    "strike": 280.0,
                    "bid": 4.8,
                    "ask": 5.0,
                    "implied_volatility": 0.30,
                    "update_time": "2026-05-01 15:59:00",
                },
            ]
        ),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {
            "symbol": "US.AAPL",
            "last": 280.0,
            "update_time": "2026-05-01 15:59:00",
        },
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=tmp_path / "scans",
            vix_history_path=tmp_path / "missing_vix.csv",
            earnings_calendar_path=tmp_path / "earnings.csv",
        )
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/options/screener",
        json={
            "ticker": "AAPL",
            "strategy_type": "sell_put",
            "min_iv": 0.2,
            "max_delta": 0.35,
            "min_premium": 1.0,
            "max_spread_pct": 0.2,
            "provider": "futu",
            "history_start": "2026-01-02",
            "history_end": "2026-05-01",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [candidate["symbol"] for candidate in payload["candidates"]] == ["US.AAPL260619P250000"]
    assert any(
        "1 provider row(s) failed contract identity checks" in line
        for line in payload["assumptions"]
    )


def test_options_screener_rejects_non_futu_provider(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/options/chain",
        params={"ticker": "AAPL", "expiration": "2026-06-19", "provider": "sample"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_options_provider"


def test_options_route_maps_futu_error(tmp_path, monkeypatch) -> None:
    def fake_fetch(self, underlying, *, expiration, option_type="ALL"):
        raise FutuProviderError("permission_denied", "missing options permission")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes",
        fake_fetch,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/options/chain",
        params={"ticker": "AAPL", "expiration": "2026-06-19", "provider": "futu"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


def test_options_screener_returns_400_when_dte_window_has_no_expiration(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_expirations",
        lambda self, underlying: pd.DataFrame(
            [{"strike_time": "2026-06-19", "option_expiry_date_distance": 48}]
        ),
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/screener",
        json={
            "ticker": "AAPL",
            "strategy_type": "sell_put",
            "min_dte": 1,
            "max_dte": 7,
            "provider": "futu",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_options_screen"
