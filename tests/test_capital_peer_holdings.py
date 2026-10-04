"""Artificial historical activity checks the real new-money peer consumer.

Only price observations are artificial. Allocation, execution/account accounting,
journals, storage, original-return verification and hang_candidate are real code.
No official simulation cycle, real data or production account is invoked.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from quant_system.d34.hung_sleeve_effect import collect_official_marks
from quant_system.execution import assistant_remote as remote
from quant_system.execution.paper_strategy_execution_service import PaperStrategyExecutionService
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategyConfig,
    StrategySignal,
    StrategySleeveMode,
)
from quant_system.research.definition_paper import definition_config_fields, definition_orders
from quant_system.research.strategy_definition import validate_definition
from tests.test_assistant_remote import _tree_hash
from tests.test_capital_evidence import definition_archive
from tests.test_definition_paper_bridge import OpenPrices
from tests.test_new_capital_consumer import candidate_with_originals


def _setup_history(tmp_path, monkeypatch, *, traded, liquidated=False, account_settings=None):
    settings, candidate = candidate_with_originals(tmp_path, monkeypatch, 12)
    if account_settings is not None:
        assert account_settings.data.data_dir == settings.data.data_dir
        settings = account_settings
    _, originals, _ = definition_archive(tmp_path / "historical_peer")
    peer = copy.deepcopy(originals[2])  # Its original curve is measurably low-correlated.
    peer.update(candidate_id="historical-held-peer", status="hung", sleeve_id="sleeve-held-peer")
    definition = validate_definition(json.loads(Path(peer["source_path"]).read_text()))
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    accounts = remote.build_paper_account_repository(tmp_path / "api_runs", settings=settings)
    account = accounts.load()
    if account is None:
        account = accounts.reset(initial_cash=1000000)
    service = PaperStrategySleeveService(storage)
    config = StrategyConfig.create(
        name="Artificial historical peer",
        **definition_config_fields(definition),
    )
    storage.save_strategy_config(config)
    sleeve = service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10000,
        sleeve_id=peer["sleeve_id"],
        metadata={
            "candidate_id": peer["candidate_id"],
            "source_digest": peer["source_digest"],
            "candidate_code_digest": peer["source_digest"],
            "definition_digest": definition.content_digest,
            "automation_source": "d34",
            "mandate_id": "remote-hang",
        },
    )
    storage.save_sleeve(sleeve)
    accounts.save(account)
    book = remote.load_book(settings)
    book["candidates"].append(peer)
    remote.save_book(settings, book)
    if traded:
        observations = [({"AAPL": 0.5}, "2026-06-26", "2026-06-29")]
        if liquidated:
            observations.append(({}, "2026-06-30", "2026-07-01"))
        for targets, signal_day, trade_day in observations:
            _execute_fixture_targets(
                storage,
                accounts,
                account,
                sleeve,
                service,
                definition,
                targets,
                signal_day,
                trade_day,
            )
        if liquidated:
            assert storage.sleeve_lots_path(sleeve.sleeve_id).is_file()
            assert not storage.load_sleeve_lots(sleeve.sleeve_id)
            assert all(
                position.source_quantity.get(f"strategy:{sleeve.sleeve_id}", 0) == 0
                for position in account.positions.values()
            )
        else:
            assert storage.load_sleeve_lots(sleeve.sleeve_id)
            assert account.positions["AAPL"].source_quantity[f"strategy:{sleeve.sleeve_id}"] > 0
        _, marks = collect_official_marks(sleeve_storage=storage)
        assert marks, "the artificial prior activity must have verified committed journals"
    service.stop_sleeve(sleeve, reason="Artificial historical stop; no automatic liquidation")
    return settings, candidate, peer, storage, accounts


def _execute_fixture_targets(
    storage, accounts, account, sleeve, service, definition, targets, signal_day, trade_day
):
    lots = storage.load_sleeve_lots(sleeve.sleeve_id)
    holdings = {}
    for lot in lots:
        holdings[lot.symbol] = holdings.get(lot.symbol, 0) + lot.quantity
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date=signal_day,
        data_as_of=signal_day,
        data_provider="futu",
        target_weights=targets,
        proposed_orders=definition_orders(
            definition=definition,
            holdings=holdings,
            cash=sleeve.cash,
            targets=targets,
            prices={"AAPL": 100.0},
            account_id=account.account_id,
        ),
        metadata={
            "definition_digest": definition.content_digest,
            "signal_date": signal_day,
            "trade_date": trade_day,
            "targets": targets,
            "ready": True,
            "rebalance_due": True,
        },
    )
    storage.append_signal(signal)
    plan = service.create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date=trade_day,
        metadata={"definition_digest": definition.content_digest},
        allow_frozen_account=True,
    )
    executor = PaperStrategyExecutionService(
        storage=storage,
        price_source=None,
        definition_open_price_source=OpenPrices({"AAPL": 100.0}),
        commission_bps=1,
        slippage_bps=5,
    )
    prepared = executor.prepare_execution(sleeve=sleeve, plan=plan, account_id=account.account_id)
    with accounts.mutation_lock(), storage.mutation_lock():
        executed = executor.commit_execution(
            account,
            sleeve=sleeve,
            plan=plan,
            prepared=prepared,
            allow_frozen_account=True,
        )
        accounts.save(account)
        storage.commit_execution_journal(
            sleeve_id=sleeve.sleeve_id, execution_id=executed.execution_id
        )
    assert executed.fills


def _allocation_count(accounts):
    return sum(row.kind == "sleeve_cash_allocated" for row in accounts.load().ledger)


@pytest.mark.parametrize("fault", ["missing", "empty_parquet"])
def test_stopped_peer_with_missing_lots_after_committed_activity_cannot_fund(
    tmp_path,
    monkeypatch,
    fault,
):
    settings, candidate, peer, storage, accounts = _setup_history(
        tmp_path, monkeypatch, traded=True
    )
    book = remote.load_book(settings)
    original_quality = remote._current_new_capital_quality(settings, candidate, book["candidates"])
    assert original_quality["eligible"] is True
    assert original_quality["concentration"]["n_hung_sleeves"] == 1
    assert original_quality["concentration"]["raw_max"] < 0.7
    lots = storage.sleeve_lots_path(peer["sleeve_id"])
    saved_lots_sha = hashlib.sha256(lots.read_bytes()).hexdigest()
    journals = list(storage.execution_journal_dir(peer["sleeve_id"]).glob("*.committed.json"))
    assert journals and lots.exists()
    # Faults are confined to these explicit artificial test originals.
    if fault == "missing":
        lots.unlink()
    else:
        storage.save_sleeve_lots(peer["sleeve_id"], [])
        assert lots.is_file()
    assert storage.load_sleeve_lots(peer["sleeve_id"]) == []
    before_count, before_tree = _allocation_count(accounts), _tree_hash(tmp_path)
    caught, result = None, None
    try:
        result = remote.hang_candidate(
            settings,
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
        )
    except remote.AssistantRemoteError as error:
        caught = error.code
    after_count, after_tree = _allocation_count(accounts), _tree_hash(tmp_path)
    probe = {
        "artificial_fixture": True,
        "fault": fault,
        "lots_sha256_before_fault": saved_lots_sha,
        "committed_journals": len(journals),
        "allocation_count_before": before_count,
        "allocation_count_after": after_count,
        "refusal": caught,
        "hang_status": (result or {}).get("status"),
        "peer_source_quantity": accounts.load()
        .positions["AAPL"]
        .source_quantity[f"strategy:{peer['sleeve_id']}"],
        "consumer_tree_unchanged": before_tree == after_tree,
    }
    (tmp_path / "peer_holdings_probe.json").write_text(json.dumps(probe, indent=2))
    assert after_count == before_count, probe
    assert caught is not None, probe
    assert after_tree == before_tree, probe


def test_stopped_never_traded_cash_peer_can_be_excluded_without_lots_file(tmp_path, monkeypatch):
    settings, candidate, peer, storage, accounts = _setup_history(
        tmp_path, monkeypatch, traded=False
    )
    assert not storage.sleeve_lots_path(peer["sleeve_id"]).exists()
    assert not storage.load_signals(peer["sleeve_id"])
    assert not storage.load_executions(peer["sleeve_id"])
    assert not list(storage.execution_journal_dir(peer["sleeve_id"]).glob("*.json"))
    assert not accounts.load().positions
    quality = remote._current_new_capital_quality(
        settings,
        candidate,
        remote.load_book(settings)["candidates"],
    )
    assert quality["eligible"] is True
    assert quality["concentration"]["n_hung_sleeves"] == 0
    before = _allocation_count(accounts)
    result = remote.hang_candidate(
        settings,
        candidate_id=candidate["candidate_id"],
        expected_source_digest=candidate["source_digest"],
    )
    assert result["status"] == "hung"
    assert _allocation_count(accounts) == before + 1


@pytest.mark.parametrize("fault", ["missing", "corrupt"])
def test_stopped_peer_account_unavailable_cannot_be_assumed_to_have_no_exposure(
    tmp_path,
    monkeypatch,
    fault,
):
    settings, candidate, peer, storage, accounts = _setup_history(
        tmp_path,
        monkeypatch,
        traded=False,
    )
    if fault == "missing":
        accounts.account_path.unlink()
    else:
        accounts.account_path.write_text("{artificial-corrupt-account")
    before = _tree_hash(tmp_path)
    with pytest.raises(remote.AssistantRemoteError, match="peer_account_unavailable"):
        remote.hang_candidate(
            settings,
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
        )
    assert _tree_hash(tmp_path) == before
    assert len(storage.list_sleeves()) == 1
    assert storage.load_sleeve(peer["sleeve_id"]).cash == 10000


def test_stopped_actual_round_trip_with_two_committed_journals_can_be_excluded(
    tmp_path,
    monkeypatch,
):
    settings, candidate, peer, storage, accounts = _setup_history(
        tmp_path,
        monkeypatch,
        traded=True,
        liquidated=True,
    )
    assert len(list(storage.execution_journal_dir(peer["sleeve_id"]).glob("*.committed.json"))) == 2
    assert storage.sleeve_lots_path(peer["sleeve_id"]).is_file()
    assert storage.load_sleeve_lots(peer["sleeve_id"]) == []
    executions = storage.load_executions(peer["sleeve_id"])
    assert [fill.side for execution in executions for fill in execution.fills] == ["buy", "sell"]
    quality = remote._current_new_capital_quality(
        settings,
        candidate,
        remote.load_book(settings)["candidates"],
    )
    assert quality["eligible"] is True and quality["concentration"]["n_hung_sleeves"] == 0
    before = _allocation_count(accounts)
    result = remote.hang_candidate(
        settings,
        candidate_id=candidate["candidate_id"],
        expected_source_digest=candidate["source_digest"],
    )
    assert result["status"] == "hung"
    assert _allocation_count(accounts) == before + 1


def test_unavailable_canonical_authority_does_not_use_healthy_file_account(
    tmp_path,
    monkeypatch,
):
    settings, candidate, peer, storage, accounts = _setup_history(
        tmp_path,
        monkeypatch,
        traded=True,
    )
    storage.save_sleeve_lots(peer["sleeve_id"], [])
    assert accounts.load().positions["AAPL"].source_quantity[f"strategy:{peer['sleeve_id']}"] == 50
    settings.paper_account = settings.paper_account.model_copy(update={"db_mode": "canonical"})
    settings.database = settings.database.model_copy(
        update={
            "enabled": True,
            "url": "postgresql://postgres@127.0.0.1:1/isolated_unavailable_peer_test",
            "connect_timeout_seconds": 1,
        }
    )
    before = _tree_hash(tmp_path)
    with pytest.raises(remote.AssistantRemoteError, match="peer_account_unavailable"):
        remote.hang_candidate(
            settings,
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
        )
    assert _tree_hash(tmp_path) == before
    assert _allocation_count(accounts) == 1
