"""Artificial isolated records only; no market or natural-cycle claims."""

from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.paper_strategy_sleeves import (
    StrategySignal,
    StrategySleeve,
    StrategySleeveMode,
)
from quant_system.research.paper_runtime_status import read_paper_runtime_status
from tests.test_definition_paper_bridge import config_for, definition


def _fixture(tmp_path):
    config = config_for(definition())
    storage = PaperStrategySleeveStorage(tmp_path)
    sleeve = StrategySleeve.create(
        config=config, mode=StrategySleeveMode.ALLOCATED, allocated_cash=10_000,
    )
    sleeve.metadata["definition_digest"] = config.strategy_definition["content_digest"]
    storage.save_strategy_config(config)
    storage.save_sleeve(sleeve)
    return storage, sleeve, config


def _files(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_enabled_cash_sleeve_does_not_imply_signals_fills_or_performance(tmp_path):
    storage, sleeve, _ = _fixture(tmp_path)
    before = _files(tmp_path)
    result = read_paper_runtime_status(storage, sleeve)
    assert result["enabled"] is True
    assert result["execution_ready"] is True
    assert result["configuration"]["status"] == "compatible"
    assert result["signal"]["status"] == "not_generated"
    assert result["fills"]["count"] == 0
    assert result["valuation"] == {"status": "cash_only", "reason": "no_committed_fills"}
    assert _files(tmp_path) == before


def test_current_source_change_blocks_even_with_a_saved_generated_signal(tmp_path, monkeypatch):
    from quant_system.research import strategy_definition

    storage, sleeve, config = _fixture(tmp_path)
    signal = StrategySignal(
        signal_id="signal-artificial", sleeve_id=sleeve.sleeve_id,
        strategy_config_id=config.strategy_config_id, strategy_config_version=config.version,
        signal_date="2026-09-21", data_provider="isolated_test", target_weights={},
        proposed_orders=[], warnings=[], status="generated",
        metadata={"definition_digest": config.strategy_definition["content_digest"]},
    )
    storage.append_signal(signal)
    before = _files(tmp_path)
    original = strategy_definition.current_source_fingerprints
    with monkeypatch.context() as patch:
        patch.setattr(strategy_definition, "current_source_fingerprints",
                      lambda value: {**original(value), "synthetic_source_change": "different"})
        blocked = read_paper_runtime_status(storage, sleeve)
    assert blocked["configuration"]["reason"] == "strategy_algorithm_source_mismatch"
    assert blocked["enabled"] is True  # lifecycle flag survives; see execution_ready
    assert blocked["execution_ready"] is False
    assert blocked["signal"]["status"] == "blocked"
    assert blocked["signal"]["signal_id"] == "signal-artificial"
    assert blocked["fills"]["count"] == 0
    # The read cannot persist a fake failure or alter the old signal. Restoring
    # the original strict loader recovers the original evidence without a write.
    restored = read_paper_runtime_status(storage, sleeve)
    assert restored["signal"]["status"] == "generated"
    assert _files(tmp_path) == before


def test_signal_identity_mismatch_is_blocked_without_rejecting_valid_hold(tmp_path):
    storage, sleeve, config = _fixture(tmp_path)
    signal = StrategySignal(
        signal_id="signal-artificial", sleeve_id=sleeve.sleeve_id,
        strategy_config_id=config.strategy_config_id, strategy_config_version=config.version,
        signal_date="2026-09-21", data_provider="isolated_test", target_weights={},
        proposed_orders=[], warnings=[], status="generated",
        metadata={"definition_digest": "wrong", "rebalance_due": False},
    )
    storage.append_signal(signal)
    assert read_paper_runtime_status(storage, sleeve)["signal"]["reason"] == (
        "strategy_definition_signal_binding_mismatch"
    )
    signal.signal_id = "signal-correct-hold"
    signal.generated_at = "2099-01-01T00:00:00+00:00"
    signal.metadata["definition_digest"] = config.strategy_definition["content_digest"]
    storage.append_signal(signal)
    assert read_paper_runtime_status(storage, sleeve)["signal"]["status"] == "generated"


def test_unknown_committed_history_is_not_projected_as_zero(tmp_path):
    storage, sleeve, _ = _fixture(tmp_path)
    sleeve.cash -= 1
    storage.save_sleeve(sleeve)
    result = read_paper_runtime_status(storage, sleeve)
    assert result["fills"]["status"] == "unavailable"
    assert result["fills"]["count"] is None
    assert result["valuation"]["status"] != "cash_only"


def test_missing_config_fails_closed_without_creating_any_file(tmp_path):
    storage, sleeve, config = _fixture(tmp_path)
    storage.strategy_config_path(config.strategy_config_id, config.version).unlink()
    before = _files(tmp_path)
    result = read_paper_runtime_status(storage, sleeve)
    assert result["signal"]["status"] == "blocked"
    assert result["configuration"]["reason"] == "strategy_config_missing"
    assert _files(tmp_path) == before


def test_strategy_get_projection_binds_sleeve_by_candidate_and_is_read_only(tmp_path):
    from quant_system.api.routes.strategy_library import _project_research_evidence
    from quant_system.config.settings import load_settings

    settings = load_settings()
    settings.data.data_dir = tmp_path
    storage, sleeve, _ = _fixture(tmp_path / "api_runs")
    sleeve.metadata["candidate_id"] = "candidate-a"
    storage.save_sleeve(sleeve)
    items = [
        {"strategy_id": "strategy-" + "a" * 24, "candidate_id": "candidate-a", "status": "stale"},
        {"strategy_id": "strategy-" + "b" * 24, "candidate_id": "candidate-b", "status": "draft"},
    ]
    before = _files(tmp_path)
    result = _project_research_evidence(settings, tmp_path, items)
    assert result[0]["status"] == "stale"
    assert result[0]["sleeve_id"] == sleeve.sleeve_id
    assert result[0]["paper_runtime"]["fills"]["count"] == 0
    assert "paper_runtime" not in result[1]
    assert _files(tmp_path) == before


def test_waiting_data_stays_material_not_a_strategy_and_corruption_is_visible(tmp_path):
    import json
    from types import SimpleNamespace

    from quant_system.api.routes.strategy_library import list_strategies
    from quant_system.research import external_intake as intake
    from tests.test_intake_factor_evaluation import hypothesis_card, proposal

    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    intake.root(settings).mkdir()
    intake._write(
        intake.root(settings) / "policy.json", intake.IntakePolicy(enabled=True).model_dump(),
    )
    body = proposal().model_dump(mode="json")
    body.update(hypothesis_card=hypothesis_card(["book_to_market", "filing_available_at"]),
                expression="$book_to_market")
    submitted = intake.submit(settings, body)
    before = _files(tmp_path)
    result = list_strategies(settings, tmp_path)
    assert result["items"] == []
    material = result["data_needs"][0]
    assert material["expression"] == "$book_to_market"
    assert material["executable_strategy_count"] == 0
    assert material["research_design"]["data_needs"][0]["fields"] == [
        "book_to_market", "filing_available_at",
    ]
    assert "strategy_id" not in material and "definition" not in material
    assert _files(tmp_path) == before
    path = intake._job_path(settings, submitted["job_id"])
    damaged = json.loads(path.read_text())
    damaged["proposal"]["expression"] = "$close"
    path.write_text(json.dumps(damaged))
    result = list_strategies(settings, tmp_path)
    assert "data_needs" not in result
    assert result["data_needs_error"] == "waiting_research_materials_unavailable"
