"""Read-only configuration browsing must not grant historical execution rights."""

import json

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from tests.test_api_paper_strategy_sleeves import _config_payload
from tests.test_definition_paper_bridge import config_for, definition
from tests.test_paper_strategy_signals import make_config


def snapshot(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_config_catalog_retains_historical_source_mismatch_without_enabling_it(
    tmp_path, monkeypatch,
):
    from quant_system.research import strategy_definition

    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    historical = config_for(definition())
    current = make_config()
    storage.save_strategy_config(historical)
    storage.save_strategy_config(current)
    original = strategy_definition.current_source_fingerprints
    monkeypatch.setattr(
        strategy_definition, "current_source_fingerprints",
        lambda value: {**original(value), "synthetic_source_change": "different"},
    )
    before = snapshot(storage.root_dir)
    response = TestClient(create_app(output_dir=tmp_path)).get("/api/paper/strategy-configs")

    assert response.status_code == 200
    rows = {row["strategy_config_id"]: row for row in response.json()["configs"]}
    assert rows[current.strategy_config_id]["source_status"] == "compatible"
    assert rows[historical.strategy_config_id]["source_status"] == "historical_mismatch"
    assert rows[historical.strategy_config_id]["source_error"] == (
        "strategy_algorithm_source_mismatch"
    )
    assert rows[historical.strategy_config_id]["metadata"] == historical.metadata
    assert response.json()["unavailable_configs"] == []
    with pytest.raises(ValueError, match="strategy_algorithm_source_mismatch"):
        storage.load_strategy_config(historical.strategy_config_id)
    with pytest.raises(ValueError, match="strategy_algorithm_source_mismatch"):
        storage.list_strategy_configs()
    assert snapshot(storage.root_dir) == before


@pytest.mark.parametrize("failure", [
    "missing_config", "corrupt_config", "missing_metadata", "corrupt_metadata",
    "metadata_identity", "config_identity", "invalid_version", "tampered_digest",
])
def test_config_catalog_exposes_unreadable_entry_and_keeps_good_siblings(tmp_path, failure):
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    broken = config_for(definition())
    current = make_config()
    storage.save_strategy_config(broken)
    storage.save_strategy_config(current)
    path = storage.strategy_config_path(broken.strategy_config_id, broken.version)
    metadata = storage.strategy_config_metadata_path(broken.strategy_config_id)
    if failure == "missing_config":
        path.unlink()
    elif failure == "corrupt_config":
        path.write_text("{broken")
    elif failure == "missing_metadata":
        metadata.unlink()
    elif failure == "corrupt_metadata":
        metadata.write_text("[]")
    elif failure == "metadata_identity":
        data = json.loads(metadata.read_text())
        data["strategy_config_id"] = current.strategy_config_id
        metadata.write_text(json.dumps(data))
    elif failure == "invalid_version":
        data = json.loads(metadata.read_text())
        data["latest_version"] = "../config"
        metadata.write_text(json.dumps(data))
    else:
        data = json.loads(path.read_text())
        if failure == "config_identity":
            data["strategy_config_id"] = current.strategy_config_id
        else:
            data["strategy_definition"]["content_digest"] = "0" * 64
        path.write_text(json.dumps(data))
    before = snapshot(storage.root_dir)

    response = TestClient(create_app(output_dir=tmp_path)).get("/api/paper/strategy-configs")

    assert response.status_code == 200
    assert [row["strategy_config_id"] for row in response.json()["configs"]] == [
        current.strategy_config_id,
    ]
    unavailable = response.json()["unavailable_configs"]
    assert len(unavailable) == 1
    assert unavailable[0]["strategy_config_id"] == broken.strategy_config_id
    assert unavailable[0]["reason"]
    assert snapshot(storage.root_dir) == before


def test_config_creation_checks_names_without_requiring_old_source_to_execute(
    tmp_path, monkeypatch,
):
    from quant_system.research import strategy_definition

    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    historical = config_for(definition())
    storage.save_strategy_config(historical)
    original_path = storage.strategy_config_path(historical.strategy_config_id, 1)
    original_bytes = original_path.read_bytes()
    original = strategy_definition.current_source_fingerprints
    monkeypatch.setattr(strategy_definition, "current_source_fingerprints", lambda value: {
        **original(value), "synthetic_source_change": "different",
    })
    client = TestClient(create_app(output_dir=tmp_path))
    duplicate = client.post(
        "/api/paper/strategy-configs", json=_config_payload(name=historical.name),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "strategy_config_name_conflict"
    created = client.post("/api/paper/strategy-configs", json=_config_payload(name="New config"))
    assert created.status_code == 200
    assert original_path.read_bytes() == original_bytes
    with pytest.raises(ValueError, match="strategy_algorithm_source_mismatch"):
        storage.load_strategy_config(historical.strategy_config_id)


def test_config_creation_reports_unreadable_names_without_guessing(tmp_path):
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    config = make_config()
    storage.save_strategy_config(config)
    storage.strategy_config_path(config.strategy_config_id, config.version).unlink()
    response = TestClient(create_app(output_dir=tmp_path)).post(
        "/api/paper/strategy-configs", json=_config_payload(name="New config"),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "strategy_config_catalog_incomplete"
