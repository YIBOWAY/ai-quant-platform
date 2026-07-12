from __future__ import annotations

import json
from types import SimpleNamespace

from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.data.price_history import HistoricalPriceReadError

runner = CliRunner()


def _payload() -> dict:
    return {
        "schema_version": "1.0",
        "provider": "futu",
        "source": "futu",
        "interval": "1d",
        "adjustment": "qfq",
        "start": "2026-07-01",
        "end": "2026-07-10",
        "fetched_at": "2026-07-10T16:00:00+00:00",
        "symbols": ["AAPL", "SPY"],
        "series": [],
    }


def test_data_prices_emits_one_parseable_json_document(monkeypatch) -> None:
    calls = []
    payload = _payload()

    def read_prices(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(to_dict=lambda: payload)

    monkeypatch.setattr("quant_system.cli.read_historical_prices", read_prices)
    result = runner.invoke(
        app,
        [
            "data",
            "prices",
            "--symbol",
            "AAPL",
            "--symbol",
            "SPY",
            "--start",
            "2026-07-01",
            "--end",
            "2026-07-10",
            "--provider",
            "futu",
            "--adjustment",
            "qfq",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == payload
    assert len(calls) == 1
    assert calls[0]["symbols"] == ["AAPL", "SPY"]
    assert calls[0]["provider"] == "futu"
    assert calls[0]["adjustment"] == "qfq"
    assert calls[0]["interval"] == "1d"


def test_data_prices_known_failure_is_json_and_nonzero(monkeypatch) -> None:
    def fail(**_kwargs):
        raise HistoricalPriceReadError(
            code="historical_prices_provider_error",
            provider="futu",
            provider_code="opend_unavailable",
            message="Futu OpenD is unavailable",
        )

    monkeypatch.setattr("quant_system.cli.read_historical_prices", fail)
    result = runner.invoke(
        app,
        [
            "data",
            "prices",
            "--symbol",
            "AAPL",
            "--start",
            "2026-07-01",
            "--end",
            "2026-07-10",
            "--provider",
            "futu",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "error": {
            "code": "historical_prices_provider_error",
            "provider": "futu",
            "provider_code": "opend_unavailable",
            "message": "Futu OpenD is unavailable",
        }
    }


def test_data_prices_invalid_request_uses_exit_two(monkeypatch) -> None:
    def fail(**_kwargs):
        raise HistoricalPriceReadError(
            code="historical_prices_invalid_request",
            provider="futu",
            message="explicit provider=futu is required",
        )

    monkeypatch.setattr("quant_system.cli.read_historical_prices", fail)
    result = runner.invoke(
        app,
        [
            "data",
            "prices",
            "--symbol",
            "AAPL",
            "--start",
            "2026-07-01",
            "--end",
            "2026-07-10",
        ],
    )

    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["code"] == (
        "historical_prices_invalid_request"
    )


def test_data_prices_invalid_settings_are_stable_json(monkeypatch) -> None:
    def fail_settings():
        raise ValueError("invalid local settings")

    monkeypatch.setattr("quant_system.cli.load_settings", fail_settings)
    result = runner.invoke(
        app,
        [
            "data",
            "prices",
            "--symbol",
            "AAPL",
            "--start",
            "2026-07-01",
            "--end",
            "2026-07-10",
            "--provider",
            "futu",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == {
        "code": "historical_prices_configuration_error",
        "provider": "futu",
        "provider_code": "ValueError",
        "message": "platform settings are invalid for historical price reads",
    }
