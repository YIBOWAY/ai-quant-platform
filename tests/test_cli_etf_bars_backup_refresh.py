from __future__ import annotations

import json

from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.data.backup_bars import BackupChainResult
from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
)

runner = CliRunner()

SYMBOLS = ["EWH", "EWJ"]


def _chain_result(
    *,
    provider: str = "twelvedata",
    source: str = "twelvedata",
    adjustment: str = "splits",
    fallbacks: list[dict[str, str]] | None = None,
) -> BackupChainResult:
    snapshot = HistoricalPriceSnapshot(
        provider=provider,
        source=source,
        interval="1d",
        adjustment=adjustment,
        start="2026-08-03",
        end="2026-08-10",
        fetched_at="2026-08-10T22:00:00+00:00",
        symbols=list(SYMBOLS),
        series=[
            {
                "symbol": symbol,
                "row_count": 2,
                "first_date": "2026-08-03",
                "last_date": "2026-08-10",
                "rows": [
                    {"date": "2026-08-03", "close": 100.0},
                    {"date": "2026-08-10", "close": 101.0},
                ],
            }
            for symbol in SYMBOLS
        ],
    )
    return BackupChainResult(snapshot=snapshot, fallbacks=fallbacks or [])


def test_backup_refresh_reports_serving_lane_and_fallbacks(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_read(**kwargs):
        captured.update(kwargs)
        return _chain_result(
            fallbacks=[
                {
                    "provider": "futu",
                    "code": "opend_unavailable",
                    "message": "Futu OpenD is unavailable",
                }
            ]
        )

    monkeypatch.setattr(
        "quant_system.data.backup_bars.read_daily_bars_with_backup",
        fake_read,
    )
    result = runner.invoke(
        app,
        [
            "data",
            "etf-bars-backup-refresh",
            "--symbol",
            "EWH",
            "--symbol",
            "EWJ",
            "--start",
            "2026-08-03",
            "--end",
            "2026-08-10",
            "--cache-path",
            str(tmp_path / "bars.duckdb"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["served_by"] == "twelvedata"
    assert payload["provider"] == "twelvedata"
    assert payload["adjustment"] == "splits"
    assert payload["row_counts"] == {"EWH": 2, "EWJ": 2}
    assert payload["fallbacks"][0]["provider"] == "futu"
    # The explicit chain defaults to both verified backup lanes, in order.
    assert captured["backup_providers"] == ("twelvedata", "tiingo")
    assert captured["symbols"] == ["EWH", "EWJ"]


def test_backup_refresh_futu_primary_success_has_empty_fallbacks(monkeypatch, tmp_path) -> None:
    def fake_read(**_kwargs):
        return _chain_result(provider="futu", source="futu", adjustment="qfq")

    monkeypatch.setattr(
        "quant_system.data.backup_bars.read_daily_bars_with_backup",
        fake_read,
    )
    result = runner.invoke(
        app,
        [
            "data",
            "etf-bars-backup-refresh",
            "--start",
            "2026-08-03",
            "--end",
            "2026-08-10",
            "--cache-path",
            str(tmp_path / "bars.duckdb"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["served_by"] == "futu"
    assert payload["fallbacks"] == []


def test_backup_refresh_chain_exhaustion_fails_closed(monkeypatch, tmp_path) -> None:
    def fail(**_kwargs):
        raise HistoricalPriceReadError(
            code="historical_prices_backup_chain_exhausted",
            message="no provider in the backup chain could serve daily bars",
            provider="backup_chain",
        )

    monkeypatch.setattr(
        "quant_system.data.backup_bars.read_daily_bars_with_backup",
        fail,
    )
    result = runner.invoke(
        app,
        [
            "data",
            "etf-bars-backup-refresh",
            "--start",
            "2026-08-03",
            "--end",
            "2026-08-10",
            "--cache-path",
            str(tmp_path / "bars.duckdb"),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "historical_prices_backup_chain_exhausted"
    assert not list(tmp_path.glob("*.json"))


def test_backup_refresh_invalid_request_exits_2(monkeypatch, tmp_path) -> None:
    def fail(**_kwargs):
        raise HistoricalPriceReadError(
            code="historical_prices_invalid_request",
            message="unsupported backup provider: polygon",
        )

    monkeypatch.setattr(
        "quant_system.data.backup_bars.read_daily_bars_with_backup",
        fail,
    )
    result = runner.invoke(
        app,
        [
            "data",
            "etf-bars-backup-refresh",
            "--backup-provider",
            "polygon",
            "--start",
            "2026-08-03",
            "--end",
            "2026-08-10",
            "--cache-path",
            str(tmp_path / "bars.duckdb"),
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "historical_prices_invalid_request"
