"""Artificial historical allocations exercise the real fresh-money consumer."""
import copy

import pytest

from quant_system.execution import assistant_remote as remote
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategyConfig,
    StrategySleeveMode,
)
from tests.test_assistant_remote import _tree_hash
from tests.test_capital_evidence import definition_archive
from tests.test_new_capital_consumer import candidate_with_originals


def historical_peer(settings, row):
    """Seed an explicitly historical allocation through real accounting primitives.

    This does not claim this artificial peer passed today's admission criteria.
    """
    root = settings.data.data_dir / "api_runs"
    storage = PaperStrategySleeveStorage(root)
    account_storage = PaperAccountStorage(root)
    account = account_storage.load_or_open(initial_cash=1000000)
    config = StrategyConfig.create(name="historical artificial peer", strategy_id="factor_rank")
    storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(storage).create_sleeve(
        account, config=config, mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10000, sleeve_id=row["sleeve_id"],
        metadata={"candidate_id": row["candidate_id"], "source_digest": row["source_digest"]},
    )
    storage.save_sleeve(sleeve)
    account_storage.save(account)
    return storage, sleeve


@pytest.mark.parametrize("fault", [
    "missing_dates", "bad_sleeve_id", "mismatched_lineage", "changed_returns", "wrong_status",
])
def test_new_money_cannot_ignore_an_existing_peer(tmp_path, monkeypatch, fault):
    settings, candidate = candidate_with_originals(tmp_path, monkeypatch, 12)
    _, originals, _ = definition_archive(tmp_path / "historical_peer")
    peer = copy.deepcopy(originals[6])
    peer.update(candidate_id="historical-peer", status="hung", sleeve_id="old-sleeve")
    historical_peer(settings, peer)
    if fault == "bad_sleeve_id":
        peer["sleeve_id"] = "sleeve-does-not-exist"
    elif fault == "mismatched_lineage":
        peer["source_digest"] = "b" * 64
    elif fault == "wrong_status":
        peer["status"] = "verified"
    elif fault == "changed_returns":
        peer["performance"]["daily_returns"] = [-x for x in peer["performance"]["daily_returns"]]
    else:
        peer["performance"].pop("return_dates")
    book = remote.load_book(settings)
    book["candidates"].append(peer)
    remote.save_book(settings, book)
    before = _tree_hash(tmp_path)
    with pytest.raises(remote.AssistantRemoteError) as exc:
        remote.hang_candidate(settings, candidate_id=candidate["candidate_id"],
                              expected_source_digest=candidate["source_digest"])
    expected = {
        "bad_sleeve_id": "peer_sleeve_unavailable",
        "missing_dates": "new_capital_quality_failed:quality_evidence_unavailable",
        "mismatched_lineage": "peer_sleeve_lineage_mismatch",
        "changed_returns": "new_capital_quality_failed:quality_evidence_unavailable",
        "wrong_status": "peer_book_status_mismatch",
    }[fault]
    assert exc.value.code == expected
    assert _tree_hash(tmp_path) == before
    assert next(item for item in remote.load_book(settings)["candidates"]
                if item["candidate_id"] == candidate["candidate_id"])["sleeve_id"] is None


@pytest.mark.parametrize("state, expect_peer", [("running", True), ("paused", True), ("stopped", False)])
def test_validation_and_money_use_same_current_exposure_set(tmp_path, monkeypatch, state, expect_peer):
    from quant_system.execution.paper_strategy_sleeves import StrategySleeveStatus
    from quant_system.research.capital_evidence import current_candidate_quality

    settings, candidate = candidate_with_originals(tmp_path, monkeypatch, 12)
    _, originals, _ = definition_archive(tmp_path / "historical_peer")
    peer = copy.deepcopy(originals[6])
    peer.update(candidate_id="historical-peer", status="hung", sleeve_id="old-sleeve")
    storage, sleeve = historical_peer(settings, peer)
    sleeve.status = StrategySleeveStatus(state)
    storage.save_sleeve(sleeve)
    rows = [candidate, peer]
    validation = remote._candidate_concentration(candidate, rows, settings=settings)
    current = current_candidate_quality(settings, candidate,
                                        remote._current_exposure_candidates(settings, rows))
    assert validation["applicable"] is expect_peer
    assert validation["raw_max"] == current["concentration"]["raw_max"]
    assert validation["raw_passed"] == current["concentration"]["raw_passed"]
