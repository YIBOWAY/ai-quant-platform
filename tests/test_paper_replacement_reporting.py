"""Sealed report-contract tests; no real cycles, market data, model or account calls."""

from __future__ import annotations

import json

import pytest

from quant_system.config.settings import Settings
from quant_system.d34 import hung_sleeve_effect as effect
from quant_system.research import paper_evaluation
from tests.test_paper_evaluation import _one_committed_fill
from tests.test_strategy_replacement import scenario  # noqa: F401


def test_old_fills_remain_readable_only_through_a_verified_neutral_transition(
    tmp_path, monkeypatch
):
    settings = Settings()
    settings.data.data_dir = tmp_path
    storage = _one_committed_fill(settings)
    current = storage.load_sleeve("sleeve-test")
    original = current.model_copy(deep=True)
    current.strategy_config_version = 2
    current.metadata = {**current.metadata, "candidate_id": "new-candidate"}
    storage.save_sleeve(current)
    # Exact coordinator verification is tested separately; this double tests
    # historical-fill version matching and the report's fixed helper seam.
    called = []

    def bridge(**kwargs):
        called.append(kwargs)
        return kwargs["before_sleeve"] == original and kwargs["after_sleeve"] == current

    monkeypatch.setattr(effect, "_verified_replacement_transition", bridge)
    before = storage.execution_journal_committed_path("sleeve-test", "execution-test").read_bytes()
    _, marks = effect.collect_official_marks(sleeve_storage=storage)
    assert len(marks) == 1 and marks[0]["date"] == "2026-08-19"
    assert len(called) == 1
    assert (
        storage.execution_journal_committed_path("sleeve-test", "execution-test").read_bytes()
        == before
    )


@pytest.mark.parametrize("change", ["unlogged_version", "cash", "lots", "wrong_fill_version"])
def test_report_does_not_hide_unknown_or_economic_changes(tmp_path, monkeypatch, change):
    settings = Settings()
    settings.data.data_dir = tmp_path
    storage = _one_committed_fill(settings)
    current = storage.load_sleeve("sleeve-test")
    if change == "unlogged_version":
        current.strategy_config_version = 2
    elif change == "cash":
        current.cash += 1
    elif change == "lots":
        lots = storage.load_sleeve_lots(current.sleeve_id)
        lots[0].quantity += 1
        storage.save_sleeve_lots(current.sleeve_id, lots)
    else:
        path = storage.execution_journal_committed_path("sleeve-test", "execution-test")
        document = json.loads(path.read_text())
        document["before_execution"]["strategy_config_version"] = 999
        path.write_text(json.dumps(document))
    storage.save_sleeve(current)
    monkeypatch.setattr(effect, "_verified_replacement_transition", lambda **kw: False)
    with pytest.raises(ValueError, match="committed_effect_state_unavailable"):
        effect.collect_official_marks(sleeve_storage=storage)


def test_new_formula_does_not_inherit_old_version_performance(tmp_path, monkeypatch):
    settings = Settings()
    settings.data.data_dir = tmp_path
    storage = _one_committed_fill(settings)
    current = storage.load_sleeve("sleeve-test")
    current.strategy_config_version = 2
    current.metadata["candidate_id"] = "new-candidate"
    timeline = [
        {
            "from_config_version": 1,
            "to_config_version": 2,
            "from_candidate_id": "candidate-test",
            "to_candidate_id": "new-candidate",
            "effective_at": "2026-08-20T00:00:00+00:00",
            "replacement_id": "sealed",
        }
    ]
    monkeypatch.setattr(paper_evaluation, "_verified_version_history", lambda *a: timeline)
    value = paper_evaluation._version_performance_scope(
        storage, current, storage.load_signals(current.sleeve_id)
    )
    assert value["performance_scope"] == "cumulative_sleeve_history_across_versions"
    assert value["current_version_signal_count"] == 0
    assert value["current_version_performance"]["status"] == "not_evaluated"
    assert "return_pct" not in value["current_version_performance"]
    timeline[0]["to_candidate_id"] = "unrelated"
    with pytest.raises(ValueError, match="replacement_version_history_mismatch"):
        paper_evaluation._version_performance_scope(storage, current, [])


def test_no_transition_keeps_existing_report_shape(tmp_path, monkeypatch):
    settings = Settings()
    settings.data.data_dir = tmp_path
    storage = _one_committed_fill(settings)
    current = storage.load_sleeve("sleeve-test")
    monkeypatch.setattr(paper_evaluation, "_verified_version_history", lambda *a: [])
    assert paper_evaluation._version_performance_scope(storage, current, []) == {}


def test_real_lifecycle_journal_bridges_saved_fills_without_rewriting_them(scenario):  # noqa: F811
    """Real file lifecycle and history verifier; admission math remains fixture-sealed."""
    from quant_system.execution import strategy_replacement as replacement
    from quant_system.execution.paper_strategy_sleeves import (
        StrategyExecutionFill,
        StrategyExecutionPlan,
        StrategyExecutionStatus,
        StrategySignal,
    )

    settings, storage, repo, sleeve, config, definitions, request = scenario
    sleeve.created_at = "2026-08-18T00:00:00+00:00"
    storage.save_sleeve(sleeve)
    before = sleeve.model_copy(deep=True, update={"cash": 10000.0})
    signal = StrategySignal(
        signal_id="sealed-history",
        sleeve_id=sleeve.sleeve_id,
        strategy_config_id=config.strategy_config_id,
        strategy_config_version=1,
        signal_date="2026-08-18",
        data_provider="futu",
        target_weights={"AAPL": 0.1},
    )
    pending = StrategyExecutionPlan(
        execution_id="sealed-history",
        sleeve_id=sleeve.sleeve_id,
        account_id="default",
        signal_id=signal.signal_id,
        strategy_config_id=config.strategy_config_id,
        strategy_config_version=1,
        target_date="2026-08-19",
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
    )
    fill = StrategyExecutionFill(
        fill_id="sealed-history",
        symbol="AAPL",
        side="buy",
        quantity=10,
        price=100,
        gross_value=1000,
        price_kind="futu_snapshot",
        metadata={"commission": 0.0},
    )
    filled = pending.model_copy(update={"status": StrategyExecutionStatus.FILLED, "fills": [fill]})
    account = repo.load()
    lots = storage.load_sleeve_lots(sleeve.sleeve_id)
    journal = {
        "journal_version": 1,
        "created_at": "2026-08-19T00:00:00+00:00",
        "account_id": "default",
        "sleeve_id": sleeve.sleeve_id,
        "execution_id": filled.execution_id,
        "before_account": account.model_dump(mode="json"),
        "after_account": account.model_dump(mode="json"),
        "before_sleeve": before.model_dump(mode="json"),
        "after_sleeve": sleeve.model_dump(mode="json"),
        "before_lots": [],
        "after_lots": [lot.model_dump(mode="json") for lot in lots],
        "before_execution": pending.model_dump(mode="json"),
        "after_execution": filled.model_dump(mode="json"),
    }
    storage.append_signal(signal)
    storage.save_executions(sleeve.sleeve_id, [filled])
    storage.save_execution_journal_pending(
        sleeve_id=sleeve.sleeve_id, execution_id=filled.execution_id, payload=journal
    )
    storage.commit_execution_journal(sleeve_id=sleeve.sleeve_id, execution_id=filled.execution_id)
    journal_path = storage.execution_journal_committed_path(sleeve.sleeve_id, filled.execution_id)
    original = journal_path.read_bytes()
    assert len(effect.collect_official_marks(sleeve_storage=storage)[1]) == 1
    replaced = replacement.replace_verified_strategy(settings, **request)
    assert replaced["status"] == "committed"
    current = storage.load_sleeve(sleeve.sleeve_id)
    assert current.strategy_config_version == 2
    assert len(effect.collect_official_marks(sleeve_storage=storage)[1]) == 1
    scope = paper_evaluation._version_performance_scope(storage, current, [signal])
    assert scope["current_version_signal_count"] == 0
    assert scope["current_version_performance"]["status"] == "not_evaluated"
    assert journal_path.read_bytes() == original
    current.metadata["unrecorded_change"] = "not in the committed transition"
    storage.save_sleeve(current)
    with pytest.raises(ValueError, match="committed_effect_state_unavailable"):
        effect.collect_official_marks(sleeve_storage=storage)
