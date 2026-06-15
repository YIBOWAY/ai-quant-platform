import json

import pandas as pd
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import ApiKeySettings, Settings
from quant_system.data.providers.sample import SampleOHLCVProvider


def _write_experiment_fixture(output_dir, experiment_id: str) -> None:
    experiment_dir = output_dir / "experiments" / experiment_id
    experiment_dir.mkdir(parents=True)

    (experiment_dir / "experiment_config.json").write_text(
        json.dumps(
            {
                "experiment_name": "e2e-sweep",
                "symbols": ["SPY", "QQQ"],
                "start": "2024-01-02",
                "end": "2024-02-15",
                "initial_cash": 100000,
                "commission_bps": 1,
                "slippage_bps": 5,
                "sweep": {"lookback": [3, 5], "top_n": [1, 2]},
                "walk_forward": {
                    "enabled": True,
                    "train_bars": 12,
                    "validation_bars": 5,
                    "step_bars": 5,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (experiment_dir / "agent_summary.json").write_text(
        json.dumps(
            {
                "experiment_id": experiment_id,
                "best_run_id": "run-lb5-top1",
                "notes": ["Research-only summary.", "No automatic deployment."],
                "safety": {
                    "live_trading": False,
                    "paper_trading": False,
                    "auto_promotion": False,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "run_id": "run-lb3-top1",
                "lookback": 3,
                "top_n": 1,
                "sharpe": 0.9,
                "total_return": 0.03,
                "max_drawdown": -0.02,
                "turnover": 1.4,
            },
            {
                "run_id": "run-lb5-top1",
                "lookback": 5,
                "top_n": 1,
                "sharpe": 1.4,
                "total_return": 0.05,
                "max_drawdown": -0.015,
                "turnover": 1.1,
            },
        ]
    ).to_parquet(experiment_dir / "experiment_runs.parquet", index=False)
    pd.DataFrame(
        [
            {
                "run_id": "run-lb5-top1",
                "fold_id": "fold-1",
                "train_start": "2024-01-02",
                "train_end": "2024-01-19",
                "validation_start": "2024-01-22",
                "validation_end": "2024-01-26",
                "sharpe": 1.2,
                "total_return": 0.02,
            }
        ]
    ).to_parquet(experiment_dir / "walk_forward_folds.parquet", index=False)


def test_experiment_list_includes_best_run_id(tmp_path) -> None:
    _write_experiment_fixture(tmp_path, "experiment-api-test")
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/experiments")

    assert response.status_code == 200
    payload = response.json()
    assert payload["experiments"][0]["id"] == "experiment-api-test"
    assert payload["experiments"][0]["best_run_id"] == "run-lb5-top1"


def test_experiment_detail_reads_phase4_artifact_names(tmp_path) -> None:
    _write_experiment_fixture(tmp_path, "experiment-api-test")
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/experiments/experiment-api-test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["experiment_config"]["experiment_name"] == "e2e-sweep"
    assert payload["agent_summary"]["best_run_id"] == "run-lb5-top1"
    assert [run["run_id"] for run in payload["runs"]] == ["run-lb3-top1", "run-lb5-top1"]
    assert payload["folds"][0]["fold_id"] == "fold-1"


def test_experiment_run_api_creates_reviewable_experiment(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/experiments/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "lookbacks": [3, 5],
            "top_ns": [1, 2],
            "initial_cash": 100000,
            "commission_bps": 1,
            "slippage_bps": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["experiment_id"]
    assert payload["run_count"] == 4
    assert payload["best_run_id"]
    assert payload["safety"]["live_trading_enabled"] is False

    list_response = client.get("/api/experiments")
    assert list_response.status_code == 200
    assert payload["experiment_id"] in {
        item["id"] for item in list_response.json()["experiments"]
    }

    detail_response = client.get(f"/api/experiments/{payload['experiment_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert len(detail["runs"]) == 4
    assert detail["agent_summary"]["best_run_id"] == payload["best_run_id"]


def test_experiment_run_does_not_create_per_run_duckdb(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/experiments/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "lookbacks": [3],
            "top_ns": [1],
        },
    )

    assert response.status_code == 200
    assert list(tmp_path.rglob("*.duckdb")) == []


def test_experiment_run_explicit_unavailable_provider_returns_400(tmp_path) -> None:
    settings = Settings(api_keys=ApiKeySettings(tiingo_api_token=None))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/experiments/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "tiingo",
            "lookbacks": [3],
            "top_ns": [1],
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "provider_unavailable"
    assert detail["provider"] == "tiingo"
    assert "missing token" in detail["message"]
    assert not list((tmp_path / "experiments").glob("*"))


def test_experiment_run_uses_selected_provider_and_persists_source(
    tmp_path,
    monkeypatch,
) -> None:
    class FakeTiingoProvider:
        provider_name = "tiingo"

        def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
            frame = SampleOHLCVProvider().fetch_ohlcv(
                symbols,
                start=start,
                end=end,
                interval=interval,
            )
            frame["provider"] = self.provider_name
            return frame

    def fake_build_provider(_settings, *, requested=None):
        assert requested == "tiingo"
        return FakeTiingoProvider(), "tiingo"

    monkeypatch.setattr(
        "quant_system.api.routes.experiments.build_ohlcv_provider",
        fake_build_provider,
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/experiments/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "tiingo",
            "lookbacks": [3],
            "top_ns": [1],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "tiingo"
    assert payload["source"] == "tiingo"
    detail = client.get(f"/api/experiments/{payload['experiment_id']}").json()
    assert detail["agent_summary"]["data"]["source"] == "tiingo"
