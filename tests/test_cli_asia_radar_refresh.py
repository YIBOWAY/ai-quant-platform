from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.data.price_history import HistoricalPriceReadError

runner = CliRunner()


def _overview(as_of: str = "2026-08-07") -> dict:
    return {
        "schema_version": "1.1",
        "provider": "futu",
        "as_of": as_of,
        "timezone": "America/New_York",
        "fetched_at": f"{as_of}T21:30:00+00:00",
        "provenance": "futu",
        "methodology": {"k_shape": "daily YTD cross-sectional top-three / bottom-three baskets"},
        "markets": [
            {
                "symbol": symbol,
                "returns": {"ytd_pct": float(index)},
            }
            for index, symbol in enumerate(
                [
                    "EWY",
                    "EWT",
                    "EWJ",
                    "ASHR",
                    "INDA",
                    "EIDO",
                    "EWH",
                    "EWS",
                    "THD",
                    "EWM",
                    "EWA",
                    "EPHE",
                ],
                start=1,
            )
        ],
        "k_shape": {"winners": [], "laggards": [], "series": []},
    }


def test_asia_radar_refresh_persists_daily_snapshot(monkeypatch, tmp_path) -> None:
    def fake_overview(**_kwargs):
        return _overview()

    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_asia_radar_overview",
        fake_overview,
    )
    result = runner.invoke(
        app,
        [
            "data",
            "asia-radar-refresh",
            "--snapshot-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["as_of"] == "2026-08-07"
    assert payload["market_count"] == 12
    assert payload["provenance"] == "futu"
    snapshot_path = Path(payload["snapshot_path"])
    assert snapshot_path.exists()
    persisted = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert persisted["provider"] == "futu"
    assert persisted["timezone"] == "America/New_York"


def test_asia_radar_refresh_fail_closed_on_provider_error(monkeypatch, tmp_path) -> None:
    def fail(**_kwargs):
        raise HistoricalPriceReadError(
            code="historical_prices_provider_error",
            provider="futu",
            provider_code="opend_unavailable",
            message="Futu OpenD is unavailable",
        )

    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_asia_radar_overview",
        fail,
    )
    result = runner.invoke(
        app,
        [
            "data",
            "asia-radar-refresh",
            "--snapshot-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert payload["error"]["provider_code"] == "opend_unavailable"
    assert not list(tmp_path.glob("*.json"))


def test_asia_radar_refresh_no_snapshot_flag_skips_write(monkeypatch, tmp_path) -> None:
    def fake_overview(**_kwargs):
        return _overview()

    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_asia_radar_overview",
        fake_overview,
    )
    result = runner.invoke(
        app,
        [
            "data",
            "asia-radar-refresh",
            "--snapshot-dir",
            str(tmp_path),
            "--no-write-snapshot",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["snapshot_path"] is None
    assert not list(tmp_path.glob("*.json"))
