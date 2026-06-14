from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def _write_metadata(api_runs: Path, dirname: str, run_id: str, metadata: dict) -> None:
    run_dir = api_runs / dirname / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps({"run_id": run_id, **metadata}, sort_keys=True),
        encoding="utf-8",
    )


def test_recent_runs_aggregates_run_kinds_newest_first(tmp_path) -> None:
    api_runs = tmp_path / "api_runs"
    _write_metadata(
        api_runs,
        "backtests",
        "backtest-20260601T010000Z-aaaaaaaa",
        {"source": "tiingo", "metrics": {"sharpe": 1.2}},
    )
    _write_metadata(
        api_runs,
        "factors",
        "factor-20260603T010000Z-bbbbbbbb",
        {"source": "futu", "row_count": 42},
    )
    _write_metadata(
        api_runs,
        "paper",
        "paper-20260602T010000Z-cccccccc",
        {"source": "futu", "trade_count": 3},
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/runs/recent?limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert [item["kind"] for item in payload["runs"]] == ["factor", "paper"]
    assert [item["run_id"] for item in payload["runs"]] == [
        "factor-20260603T010000Z-bbbbbbbb",
        "paper-20260602T010000Z-cccccccc",
    ]
    assert payload["runs"][0]["source"] == "futu"
    assert payload["runs"][0]["summary"]["row_count"] == 42
