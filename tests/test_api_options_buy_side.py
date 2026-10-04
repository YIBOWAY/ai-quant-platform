from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import Settings
from quant_system.data.providers.futu import FutuProviderError


def _chain() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "US.AAPL20260619C100000",
                "underlying": "US.AAPL",
                "option_type": "CALL",
                "expiry": "2026-06-19",
                "strike": 100.0,
                "bid": 5.0,
                "ask": 5.4,
                "implied_volatility": 0.25,
                "delta": 0.56,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 800,
                "volume": 100,
                "option_expiry_date_distance": 30,
                "update_time": "2026-05-20 15:59:00",
            },
            {
                "symbol": "US.AAPL20260619C110000",
                "underlying": "US.AAPL",
                "option_type": "CALL",
                "expiry": "2026-06-19",
                "strike": 110.0,
                "bid": 1.3,
                "ask": 1.5,
                "implied_volatility": 0.24,
                "delta": 0.24,
                "gamma": 0.02,
                "theta": -0.04,
                "vega": 0.12,
                "open_interest": 500,
                "volume": 80,
                "option_expiry_date_distance": 30,
                "update_time": "2026-05-20 15:59:00",
            },
            {
                "symbol": "US.AAPL20260619P100000",
                "underlying": "US.AAPL",
                "option_type": "PUT",
                "expiry": "2026-06-19",
                "strike": 100.0,
                "bid": 4.6,
                "ask": 4.9,
                "implied_volatility": 0.25,
                "delta": -0.45,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 900,
                "volume": 100,
                "option_expiry_date_distance": 30,
                "update_time": "2026-05-20 15:59:00",
            },
        ]
    )


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-04-01", periods=40, freq="B", tz="UTC"),
            "close": [100.0 + index * 0.2 for index in range(40)],
        }
    )


def _snapshot() -> dict[str, object]:
    return {
        "symbol": "US.AAPL",
        "last": 100.0,
        "update_time": "2026-05-20 15:59:00",
    }


def _session_chain(*, put_quote_time: str = "2026-08-21 15:59:00") -> pd.DataFrame:
    frame = _chain().copy()
    frame["underlying"] = "US.AAPL"
    frame["expiry"] = "2026-09-18"
    frame["symbol"] = frame["symbol"].str.replace("20260619", "20260918", regex=False)
    frame["option_expiry_date_distance"] = 28
    frame["update_time"] = "2026-08-21 15:59:00"
    frame.loc[frame["option_type"] == "PUT", "update_time"] = put_quote_time
    return frame


def _install_market_truth(monkeypatch) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 5, 20),
    )

    def fake_chain(
        self,
        underlying,
        *,
        start_expiration,
        end_expiration,
        option_type="CALL",
    ):
        assert option_type == "ALL"
        return _chain()

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        fake_chain,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )
    monkeypatch.setattr(
        "quant_system.options.buy_side_market_data.compute_iv_rank",
        lambda ticker, current_iv, *, history_dir, measure, as_of_session: 35.0,
        raising=False,
    )


def test_api_buy_side_assistant_returns_recommendations(tmp_path, monkeypatch) -> None:
    snapshot_calls = 0

    def fake_snapshot(self, symbol):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return _snapshot()

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        fake_snapshot,
    )
    _install_market_truth(monkeypatch)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "max_loss_budget": 800.0,
            "provider": "futu",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AAPL"
    assert payload["recommendations"]
    assert payload["recommendations"][0]["rank"] == 1
    assert payload["recommendations"][0]["legs"]
    assert payload["recommendations"][0]["net_debit"] is not None
    assert payload["recommendations"][0]["scenario_summary"]["probability_not_calculated"] is True
    assert payload["recommendations"][0]["scenario_approximation_reliability"] == "high"
    assert payload["thesis"]["iv_rank"] == 35.0
    assert payload["thesis"]["iv_measure"] == "atm30_straddle_iv_v1"
    assert payload["thesis"]["historical_volatility"] > 0
    assert snapshot_calls == 1
    assert "safety" in payload
    assert payload["safety"]["live_trading_enabled"] is False


def test_api_buy_side_assistant_accepts_scenario_grid_inputs(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: _snapshot(),
    )
    _install_market_truth(monkeypatch)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "max_loss_budget": 800.0,
            "provider": "futu",
            "scenario_spot_changes": [-15, 0, 15],
            "scenario_iv_changes": [-10, 0],
            "scenario_days_passed": [0, 14],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["thesis"]["scenario_spot_changes"] == [-15.0, 0.0, 15.0]
    assert payload["thesis"]["scenario_iv_changes"] == [-10.0, 0.0]
    assert payload["thesis"]["scenario_days_passed"] == [0, 14]


def test_api_buy_side_rejects_client_supplied_market_truth(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "provider": "futu",
            "iv_rank": 99.0,
            "historical_volatility": 0.01,
        },
    )

    assert response.status_code == 422


def test_api_buy_side_rejects_client_spot_before_provider_calls(
    tmp_path,
    monkeypatch,
) -> None:
    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("client spot must fail before provider calls")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        forbidden,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        forbidden,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "provider": "futu",
            "spot_price": 1000.0,
        },
    )

    assert response.status_code == 422
    assert calls == 0


def test_api_buy_side_rejects_client_as_of_before_provider_calls(
    tmp_path,
    monkeypatch,
) -> None:
    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("client as-of must fail before provider calls")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        forbidden,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        forbidden,
    )
    client = TestClient(
        create_app(settings=Settings(), output_dir=tmp_path),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
            "as_of_date": "2026-05-20",
        },
    )

    assert response.status_code == 422
    assert calls == 0


def test_api_buy_side_stale_underlying_is_typed_unavailable_before_chain_fetch(
    tmp_path,
    monkeypatch,
) -> None:
    chain_calls = 0
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 8, 21),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {
            "symbol": "US.AAPL",
            "last": 100.0,
            "update_time": "2026-07-02 15:59:00",
        },
    )

    def forbidden_chain(*_args, **_kwargs):
        nonlocal chain_calls
        chain_calls += 1
        raise AssertionError("stale underlying must stop before option-chain fetch")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        forbidden_chain,
    )
    client = TestClient(
        create_app(settings=Settings(), output_dir=tmp_path),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "buy_side_market_data_unavailable"
    assert "underlying_quote_stale" in response.json()["detail"]["message"]
    assert chain_calls == 0


def test_api_buy_side_mixed_session_atm_pair_is_typed_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 8, 21),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {
            "symbol": "US.AAPL",
            "last": 100.0,
            "update_time": "2026-08-21 15:59:00",
        },
    )
    mixed = _session_chain(put_quote_time="2026-07-02 15:59:00")
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, **kwargs: mixed,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )
    monkeypatch.setattr(
        "quant_system.options.buy_side_market_data.compute_iv_rank",
        lambda ticker, current_iv, *, history_dir, measure, as_of_session: 35.0,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "buy_side_market_data_unavailable"
    assert "option_quote_stale" in response.json()["detail"]["message"]


def test_api_buy_side_fifty_day_old_chain_has_zero_recommendations(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 8, 21),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {
            "symbol": "US.AAPL",
            "last": 100.0,
            "update_time": "2026-08-21 15:59:00",
        },
    )
    stale = _session_chain(put_quote_time="2026-07-02 15:59:00")
    stale["update_time"] = "2026-07-02 15:59:00"
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, **kwargs: stale,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    assert "option_quote_stale" in response.json()["detail"]["message"]
    assert "recommendations" not in response.json()


def test_api_buy_side_missing_candidate_greek_is_typed_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 8, 21),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {
            "symbol": "US.AAPL",
            "last": 100.0,
            "update_time": "2026-08-21 15:59:00",
        },
    )
    missing_greek = _session_chain()
    missing_greek.loc[missing_greek["option_type"] == "CALL", "gamma"] = None
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, **kwargs: missing_greek,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )
    monkeypatch.setattr(
        "quant_system.options.buy_side_market_data.compute_iv_rank",
        lambda ticker, current_iv, *, history_dir, measure, as_of_session: 35.0,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "buy_side_market_data_unavailable"
    assert "candidate_greeks_missing" in response.json()["detail"]["message"]


def test_api_buy_side_rejects_option_rows_from_another_underlying(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 8, 21),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {
            "symbol": "US.AAPL",
            "last": 100.0,
            "update_time": "2026-08-21 15:59:00",
        },
    )
    wrong_underlying = _session_chain()
    wrong_underlying["underlying"] = "US.MSFT"
    wrong_underlying["symbol"] = wrong_underlying["symbol"].str.replace("AAPL", "MSFT", regex=False)
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, **kwargs: wrong_underlying,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    assert "option_symbol_mismatch" in response.json()["detail"]["message"]


def test_api_buy_side_rejects_contract_symbol_prefix_collision(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: _snapshot(),
    )
    collision = _chain().copy()
    collision["symbol"] = collision["symbol"].str.replace(
        "US.AAPL",
        "US.AAPLX",
        regex=False,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, **kwargs: collision,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )
    monkeypatch.setattr(
        "quant_system.options.buy_side_market_data.compute_iv_rank",
        lambda ticker, current_iv, *, history_dir, measure, as_of_session: 35.0,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 5, 20),
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "buy_side_market_data_unavailable"
    assert "option_symbol_mismatch" in response.json()["detail"]["message"]
    assert "recommendations" not in response.json()


def test_api_buy_side_ignores_unrelated_unusable_row_when_valid_set_remains(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: _snapshot(),
    )
    unusable = {
        **_chain().iloc[0].to_dict(),
        "symbol": "US.AAPL20260619C150000",
        "strike": 150.0,
        "bid": 0.0,
        "ask": 0.0,
        "open_interest": 0,
        "volume": 0,
        "gamma": None,
    }
    complete_chain = pd.DataFrame([*_chain().to_dict(orient="records"), unusable])
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, **kwargs: complete_chain,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )
    monkeypatch.setattr(
        "quant_system.options.buy_side_market_data.compute_iv_rank",
        lambda ticker, current_iv, *, history_dir, measure, as_of_session: 35.0,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 5, 20),
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["recommendations"]
    assert all(
        leg["symbol"] != "US.AAPL20260619C150000"
        for item in response.json()["recommendations"]
        for leg in item["legs"]
    )


def test_api_buy_side_empty_scenario_grid_is_422_before_provider_calls(
    tmp_path,
    monkeypatch,
) -> None:
    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("invalid scenario must fail before provider calls")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        forbidden,
    )
    client = TestClient(
        create_app(settings=Settings(), output_dir=tmp_path),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
            "scenario_spot_changes": [],
        },
    )

    assert response.status_code == 422
    assert calls == 0


def test_api_buy_side_past_target_date_is_422_before_provider_calls(
    tmp_path,
    monkeypatch,
) -> None:
    calls = 0
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 8, 21),
    )

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("past target date must fail before provider calls")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        forbidden,
    )
    client = TestClient(
        create_app(settings=Settings(), output_dir=tmp_path),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-20",
            "provider": "futu",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_buy_side_target_date"
    assert calls == 0


def test_api_buy_side_bullish_target_not_above_spot_is_422_before_chain(
    tmp_path,
    monkeypatch,
) -> None:
    chain_calls = 0
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 5, 20),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: _snapshot(),
    )

    def forbidden_chain(*_args, **_kwargs):
        nonlocal chain_calls
        chain_calls += 1
        raise AssertionError("invalid bullish target must stop before chain fetch")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        forbidden_chain,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 90.0,
            "target_date": "2026-08-21",
            "provider": "futu",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_buy_side_target_price"
    assert chain_calls == 0


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {"scenario_days_passed": [-1]},
        {"preferred_dte_range": [-1, 30]},
        {"preferred_dte_range": [60, 30]},
        {"preferred_dte_range": [0, 0]},
        {"preferred_dte_range": [5, 761]},
        {"scenario_spot_changes": [1e308]},
        {"scenario_iv_changes": [1e308]},
        {
            "user_scenarios": [
                {
                    "label": "bull",
                    "probability": 0.2,
                    "spot_change_pct": 10,
                    "iv_change_vol_points": 5,
                    "days_passed": 7,
                },
                {
                    "label": "base",
                    "probability": 0.2,
                    "spot_change_pct": 0,
                    "iv_change_vol_points": 0,
                    "days_passed": 7,
                },
            ]
        },
    ],
)
def test_api_buy_side_invalid_scenario_contract_is_422_before_provider(
    tmp_path,
    monkeypatch,
    invalid_payload,
) -> None:
    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("invalid scenario must fail before provider")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        forbidden,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
            **invalid_payload,
        },
    )

    assert response.status_code == 422
    assert calls == 0


@pytest.mark.parametrize(
    "nonfinite_fields",
    [
        '"spot_change_pct":Infinity,"iv_change_vol_points":0',
        '"spot_change_pct":0,"iv_change_vol_points":NaN',
    ],
)
def test_api_buy_side_nonfinite_nested_scenario_is_422_before_provider(
    tmp_path,
    monkeypatch,
    nonfinite_fields: str,
) -> None:
    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("nonfinite scenario must fail before provider")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        forbidden,
    )
    client = TestClient(
        create_app(settings=Settings(), output_dir=tmp_path),
        raise_server_exceptions=False,
    )
    raw_body = (
        '{"ticker":"AAPL",'
        '"view_type":"short_term_conservative_bullish",'
        '"target_price":112,"target_date":"2026-12-18",'
        '"provider":"futu","user_scenarios":['
        '{"label":"nonfinite","probability":1,'
        f'{nonfinite_fields},"days_passed":7}}]}}'
    )

    response = client.post(
        "/api/options/buy-side/assistant",
        content=raw_body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert calls == 0


def test_api_buy_side_scenario_beyond_leg_dte_is_422(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: _snapshot(),
    )
    _install_market_truth(monkeypatch)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "provider": "futu",
            "scenario_days_passed": [60],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_buy_side_scenario"


@pytest.mark.parametrize("missing", ["iv_rank", "historical_volatility"])
def test_api_buy_side_market_truth_missing_is_visible_503(
    tmp_path,
    monkeypatch,
    missing: str,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: _snapshot(),
    )
    _install_market_truth(monkeypatch)
    if missing == "iv_rank":
        monkeypatch.setattr(
            "quant_system.options.buy_side_market_data.compute_iv_rank",
            lambda ticker, current_iv, *, history_dir, measure, as_of_session: None,
        )
    else:
        monkeypatch.setattr(
            "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
            lambda self, symbols, *, start, end, interval="1d": _history().head(1),
        )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "buy_side_volatility_data_unavailable"
    assert missing in response.json()["detail"]["message"]


def test_api_buy_side_normalizes_futu_percent_iv_before_rank_and_scoring(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 5, 20),
    )
    percent_chain = _chain().copy()
    percent_chain["implied_volatility"] *= 100
    percent_chain.attrs["implied_volatility_unit"] = "percent"
    observed_iv: list[float] = []
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: _snapshot(),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, **kwargs: percent_chain,
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )

    def fake_rank(ticker, current_iv, *, history_dir, measure, as_of_session):
        assert measure == "atm30_straddle_iv_v1"
        assert as_of_session == date(2026, 5, 20)
        observed_iv.append(current_iv)
        return 35.0

    monkeypatch.setattr(
        "quant_system.options.buy_side_market_data.compute_iv_rank",
        fake_rank,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "provider": "futu",
        },
    )

    assert response.status_code == 200, response.text
    assert observed_iv == pytest.approx([0.25])
    assert all(
        leg["implied_volatility"] < 1
        for item in response.json()["recommendations"]
        for leg in item["legs"]
    )


def test_buy_side_iv_rank_reference_prefers_near_30_dte_pair() -> None:
    from datetime import date

    from quant_system.options.buy_side_market_data import (
        buy_side_atm_implied_volatility,
    )

    chain = pd.DataFrame(
        [
            {
                "option_type": option_type,
                "expiry": expiry,
                "strike": 100.0,
                "implied_volatility": iv,
            }
            for expiry, iv in (("2026-06-03", 0.90), ("2026-06-19", 0.30))
            for option_type in ("CALL", "PUT")
        ]
    )

    value = buy_side_atm_implied_volatility(
        chain,
        spot_price=100.0,
        as_of=date(2026, 5, 20),
    )

    assert value == pytest.approx(0.30)


@pytest.mark.parametrize("invalid_iv", [float("inf"), 0.0, -0.1])
def test_buy_side_iv_rank_reference_rejects_invalid_iv(invalid_iv: float) -> None:
    from datetime import date

    from quant_system.options.buy_side_market_data import (
        buy_side_atm_implied_volatility,
    )

    chain = pd.DataFrame(
        [
            {
                "option_type": option_type,
                "expiry": "2026-06-19",
                "strike": 100.0,
                "implied_volatility": invalid_iv,
            }
            for option_type in ("CALL", "PUT")
        ]
    )

    with pytest.raises(ValueError, match="buy_side_volatility_data_unavailable"):
        buy_side_atm_implied_volatility(
            chain,
            spot_price=100.0,
            as_of=date(2026, 5, 20),
        )


def test_api_buy_side_contract_is_documented(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()
    operation = openapi["paths"]["/api/options/buy-side/assistant"]["post"]

    request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert request_ref.endswith("/BuySideAssistantRequest")
    assert response_ref.endswith("/BuySideAssistantResponse")
    assert "422" in operation["responses"]
    assert "404" in operation["responses"]
    assert "503" in operation["responses"]
    public_fields = openapi["components"]["schemas"]["BuySideAssistantRequest"]["properties"]
    assert "spot_price" not in public_fields
    assert "iv_rank" not in public_fields
    assert "historical_volatility" not in public_fields
    assert "as_of_date" not in public_fields


def test_api_buy_side_assistant_rejects_non_futu_provider(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "provider": "sample",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_options_provider"


def test_api_buy_side_assistant_maps_missing_chain_to_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options._server_market_session",
        lambda: date(2026, 5, 20),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: _snapshot(),
    )

    def fake_fetch(self, underlying, *, start_expiration, end_expiration, option_type="CALL"):
        raise FutuProviderError("no_data", "no option chain available")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        fake_fetch,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "provider": "futu",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "no_data"


def test_api_buy_side_assistant_maps_opend_unavailable_to_503(
    tmp_path,
    monkeypatch,
) -> None:
    def fake_snapshot(self, symbol):
        raise FutuProviderError("opend_unavailable", "OpenD is not reachable")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        fake_snapshot,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-12-18",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "opend_unavailable"


def test_api_buy_side_assistant_maps_rate_limit_to_503(
    tmp_path,
    monkeypatch,
) -> None:
    def fake_snapshot(self, symbol):
        raise FutuProviderError("rate_limited", "Futu quote rate limit")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        fake_snapshot,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "SPY",
            "view_type": "short_term_conservative_bullish",
            "target_price": 520.0,
            "target_date": "2026-12-18",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rate_limited"


def test_api_buy_side_assistant_invalid_thesis_returns_422(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_date": "2026-08-21",
            "provider": "futu",
        },
    )

    assert response.status_code == 422
