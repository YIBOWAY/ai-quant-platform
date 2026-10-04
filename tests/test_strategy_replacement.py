"""Sealed lifecycle tests: trusted gate is explicit test double; no real funds."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import pytest

from quant_system.config.settings import DataSettings, Settings
from quant_system.execution import assistant_remote
from quant_system.execution import strategy_replacement as replacement
from quant_system.execution.account import PaperAccount
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.models import ExecutionFill, OrderSide
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    SleeveLot,
    StrategyConfig,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.research import admission_v2
from quant_system.research.definition_paper import definition_config_fields
from quant_system.research.strategy_definition import StrategyDefinition


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    settings = Settings(data=DataSettings(data_dir=tmp_path))
    settings.paper_account.db_mode = "file"
    settings.safety.live_trading_enabled = False
    monkeypatch.setattr(
        replacement, "observe_paper_emergency_stop", lambda *a, **k: {"active": False}
    )
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    repo = PaperAccountStorage(tmp_path / "api_runs")
    definitions = [
        StrategyDefinition(
            kind="factor_blend",
            title=f"sealed-{n}",
            symbols=["AAPL", "MSFT"],
            top_n=1,
            history_start="2015-01-01",
            rebalance="monthly",
            factors=[{"factor_id": "momentum", "lookback": n, "direction": "higher_is_better"}],
        )
        for n in (20, 30)
    ]
    candidates = []
    for label, definition in zip(("old", "new"), definitions, strict=True):
        source = tmp_path / "strategy_library" / label / "definition.json"
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps(definition.model_dump(mode="json")))
        candidates.append(
            {
                "candidate_id": label,
                "status": "hung" if label == "old" else "verified",
                "source": "strategy_definition",
                "source_path": str(source),
                "source_digest": replacement.file_sha(source),
                "definition_digest": definition.content_digest,
                "factor_id": "definition_" + definition.content_digest[:24],
                "universe": list(definition.symbols),
                "admission_v2": {"sha256": "a" * 64},
                "performance": {"sealed_historical_result": label},
            }
        )
    old, new = candidates
    config = StrategyConfig.create(name="old", **definition_config_fields(definitions[0]))
    storage.save_strategy_config(config)
    account = PaperAccount.open_new(initial_cash=100000)
    sleeve = PaperStrategySleeveService(storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10000,
        metadata={
            "candidate_id": old["candidate_id"],
            "definition_digest": definitions[0].content_digest,
            "source_digest": old["source_digest"],
            "mandate_id": "remote-hang",
            "automation_managed": True,
            "automation_source": "d34",
        },
    )
    old["sleeve_id"] = sleeve.sleeve_id
    account.apply_fill(
        ExecutionFill(
            fill_id="sealed-fill",
            order_id="sealed-order",
            timestamp=pd.Timestamp("2026-01-02", tz="UTC"),
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10,
            fill_price=100,
            gross_value=1000,
            commission=0,
        ),
        source="strategy:" + sleeve.sleeve_id,
        kind="sleeve_execution_fill",
    )
    account.sleeve_cash[sleeve.sleeve_id] -= 1000
    sleeve.cash -= 1000
    storage.save_sleeve(sleeve)
    storage.save_sleeve_lots(
        sleeve.sleeve_id,
        [
            SleeveLot.create(
                sleeve_id=sleeve.sleeve_id,
                symbol="AAPL",
                quantity=10,
                avg_cost=100,
                source="sealed",
            )
        ],
    )
    repo.save(account)
    assistant_remote.save_book(settings, {"candidates": candidates, "requests": []})
    monkeypatch.setattr(admission_v2, "AUTHORITATIVE_ENABLED", True)
    monkeypatch.setattr(
        admission_v2,
        "authority_configured",
        lambda _settings: admission_v2.AUTHORITATIVE_ENABLED is True,
        raising=False,
    )

    def sealed_gate(
        settings, *, new_candidate, target_candidate, target_sleeve, target_config, book
    ):
        return {
            "status": "passed",
            "validated_tier": "T2",
            "capital_delta_usd": 0,
            "replacement_target": {
                "candidate_id": target_candidate["candidate_id"],
                "sleeve_id": target_sleeve.sleeve_id,
                "definition_digest": definitions[0].content_digest,
                "config_id": target_config.strategy_config_id,
                "config_version": config.version,
            },
        }

    monkeypatch.setattr(admission_v2, "verify_for_replacement", sealed_gate, raising=False)
    monkeypatch.setattr(
        admission_v2, "prepare_replacement_preflight", lambda *a, **k: None, raising=False
    )
    request = dict(
        target_candidate_id="old",
        target_sleeve_id=sleeve.sleeve_id,
        expected_old_definition_digest=definitions[0].content_digest,
        expected_old_config_version=config.version,
        new_candidate_id="new",
        expected_new_source_digest=new["source_digest"],
        expected_admission_sha256="a" * 64,
    )
    return settings, storage, repo, sleeve, config, definitions, request


def test_replacement_keeps_one_sleeve_and_all_economic_history_and_is_idempotent(scenario):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    account_before = repo.account_path.read_bytes()
    lots_before = storage.sleeve_lots_path(sleeve.sleeve_id).read_bytes()
    old_config_before = storage.strategy_config_path(config.strategy_config_id, 1).read_bytes()
    receipt = replacement.replace_verified_strategy(settings, **request)
    assert receipt["status"] == "committed" and receipt["capital_delta_usd"] == 0
    after = storage.load_sleeve(sleeve.sleeve_id)
    assert after.strategy_config_version == 2 and after.cash == 9000
    assert len(storage.list_sleeves()) == 1
    assert repo.account_path.read_bytes() == account_before
    assert storage.sleeve_lots_path(sleeve.sleeve_id).read_bytes() == lots_before
    assert (
        storage.strategy_config_path(config.strategy_config_id, 1).read_bytes() == old_config_before
    )
    book = {row["candidate_id"]: row for row in assistant_remote.load_book(settings)["candidates"]}
    assert book["old"]["status"] == "superseded"
    assert book["new"]["status"] == "hung" and book["new"]["sleeve_id"] == sleeve.sleeve_id
    assert book["old"]["performance"] == {"sealed_historical_result": "old"}
    assert (
        replacement.replace_verified_strategy(settings, **request)["replacement_id"]
        == receipt["replacement_id"]
    )
    assert storage.load_sleeve(sleeve.sleeve_id).strategy_config_version == 2


@pytest.mark.parametrize("phase", ["paused", "config_saved", "book_bound", "committed"])
def test_each_interrupted_phase_is_paused_and_explicit_recovery_never_allocates_again(
    scenario, monkeypatch, phase
):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    original = replacement._save_journal
    failed = []

    def fail_once(settings, record, current):
        if current == phase and not failed:
            failed.append(current)
            raise OSError("sealed persistence fault:" + phase)
        return original(settings, record, current)

    monkeypatch.setattr(replacement, "_save_journal", fail_once)
    before = repo.account_path.read_bytes()
    with pytest.raises(OSError, match="sealed persistence"):
        replacement.replace_verified_strategy(settings, **request)
    paused = storage.load_sleeve(sleeve.sleeve_id)
    assert paused.status == StrategySleeveStatus.PAUSED
    assert replacement.MARKER in paused.metadata
    with pytest.raises(ValueError, match="strategy_replacement_pending"):
        PaperStrategySleeveService(storage).resume_sleeve(paused)
    identity = paused.metadata[replacement.MARKER]
    result = replacement.recover_replacement(settings, identity)
    assert result["status"] == "committed"
    assert storage.load_sleeve(sleeve.sleeve_id).strategy_config_version == 2
    assert repo.account_path.read_bytes() == before
    assert replacement.recover_replacement(settings, identity)["status"] == "committed"


def test_disabled_authority_and_old_version_cas_refuse_before_any_replacement_record(
    scenario, monkeypatch
):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    before = repo.account_path.read_bytes()
    monkeypatch.setattr(admission_v2, "AUTHORITATIVE_ENABLED", False)
    with pytest.raises(ValueError, match="replacement_authority_disabled"):
        replacement.replace_verified_strategy(settings, **request)
    monkeypatch.setattr(admission_v2, "AUTHORITATIVE_ENABLED", True)
    with pytest.raises(ValueError, match="replacement_old_version_changed"):
        replacement.replace_verified_strategy(
            settings, **{**request, "expected_old_config_version": 9}
        )
    assert not (settings.data.data_dir / "api_runs/strategy_replacements").exists()
    assert storage.load_sleeve(sleeve.sleeve_id).status == StrategySleeveStatus.RUNNING
    assert repo.account_path.read_bytes() == before


def test_source_bound_authority_reference_still_requires_final_locked_gate(scenario, monkeypatch):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    before = repo.account_path.read_bytes()
    monkeypatch.setattr(admission_v2, "AUTHORITATIVE_ENABLED", False)
    monkeypatch.setattr(admission_v2, "authority_configured", lambda _settings: True)
    calls = []

    def refused(*args, **kwargs):
        calls.append(True)
        raise ValueError("sealed_final_authority_refused")

    monkeypatch.setattr(admission_v2, "verify_for_replacement", refused)
    with pytest.raises(ValueError, match="sealed_final_authority_refused"):
        replacement.replace_verified_strategy(settings, **request)
    assert calls == [True]
    assert repo.account_path.read_bytes() == before
    assert storage.load_sleeve(sleeve.sleeve_id).strategy_config_version == 1


def test_target_resolution_is_read_only_and_bound_to_actual_recipe(scenario):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    before = {str(p): p.read_bytes() for p in settings.data.data_dir.rglob("*") if p.is_file()}
    observed = replacement.inspect_replacement_target(settings, candidate_id="old")
    assert observed["replacement_target"] == {
        "candidate_id": "old",
        "sleeve_id": sleeve.sleeve_id,
        "definition_digest": definitions[0].content_digest,
        "config_id": config.strategy_config_id,
        "config_version": 1,
    }
    assert observed["definition"] == definitions[0].model_dump(mode="json")
    assert before == {
        str(p): p.read_bytes() for p in settings.data.data_dir.rglob("*") if p.is_file()
    }


def test_other_rebalance_contract_and_legacy_target_are_not_inferred(scenario):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    book = assistant_remote.load_book(settings)
    new = next(row for row in book["candidates"] if row["candidate_id"] == "new")
    changed = definitions[1].model_dump(
        mode="json", exclude={"content_digest", "source_fingerprints"}
    )
    changed["rebalance"] = "daily"
    definition = StrategyDefinition.model_validate(changed)
    Path(new["source_path"]).write_text(json.dumps(definition.model_dump(mode="json")))
    new.update(
        source_digest=replacement.file_sha(new["source_path"]),
        factor_id="definition_" + definition.content_digest[:24],
        definition_digest=definition.content_digest,
    )
    assistant_remote.save_book(settings, book)
    with pytest.raises(ValueError, match="replacement_contract_change_unsupported"):
        replacement.replace_verified_strategy(
            settings, **{**request, "expected_new_source_digest": new["source_digest"]}
        )
    book["candidates"][0]["source"] = "registered_factor"
    assistant_remote.save_book(settings, book)
    with pytest.raises(ValueError, match="replacement_requires_frozen_strategy_definition"):
        replacement.inspect_replacement_target(settings, candidate_id="old")
    assert not (settings.data.data_dir / "api_runs/strategy_replacements").exists()


def test_recovery_refuses_changed_economics_and_does_not_resume(scenario, monkeypatch):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    original = storage.save_strategy_config
    monkeypatch.setattr(
        PaperStrategySleeveStorage,
        "save_strategy_config",
        lambda *a, **k: (_ for _ in ()).throw(OSError("sealed failure")),
    )
    with pytest.raises(OSError):
        replacement.replace_verified_strategy(settings, **request)
    monkeypatch.setattr(
        PaperStrategySleeveStorage, "save_strategy_config", lambda self, c: original(c)
    )
    paused = storage.load_sleeve(sleeve.sleeve_id)
    paused.cash -= 1
    storage.save_sleeve(paused)
    with pytest.raises(ValueError, match="replacement_cash_partition_mismatch"):
        replacement.recover_replacement(settings, paused.metadata[replacement.MARKER])
    assert storage.load_sleeve(sleeve.sleeve_id).status == StrategySleeveStatus.PAUSED


def test_explicit_abort_restores_original_version_without_erasing_failed_new_config(
    scenario, monkeypatch
):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    original = replacement._save_journal
    interrupted = []

    def fail_after_book(settings, record, phase):
        if phase == "book_bound" and not interrupted:
            interrupted.append(True)
            raise OSError("sealed failure after book binding")
        return original(settings, record, phase)

    monkeypatch.setattr(replacement, "_save_journal", fail_after_book)
    account_before = repo.account_path.read_bytes()
    with pytest.raises(OSError):
        replacement.replace_verified_strategy(settings, **request)
    pending = storage.load_sleeve(sleeve.sleeve_id)
    identity = pending.metadata[replacement.MARKER]
    result = replacement.recover_replacement(settings, identity, action="abort")
    assert result["status"] == "aborted"
    assert storage.load_sleeve(sleeve.sleeve_id).strategy_config_version == 1
    assert storage.strategy_config_path(config.strategy_config_id, 2).is_file()
    book = {r["candidate_id"]: r for r in assistant_remote.load_book(settings)["candidates"]}
    assert book["old"]["status"] == "hung" and book["new"]["status"] == "verified"
    assert not book["new"].get("sleeve_id")
    assert repo.account_path.read_bytes() == account_before
    assert (
        replacement.recover_replacement(settings, identity, action="abort")["status"] == "aborted"
    )


def test_expensive_preflight_is_outside_all_locks_and_recovery_preimage_is_real(
    scenario, monkeypatch
):
    import fcntl

    settings, storage, repo, sleeve, config, definitions, request = scenario
    lock_paths = (repo.lock_path, storage.lock_path, assistant_remote._book_lock_path(settings))
    calls = []

    def prepare(settings, **context):
        for path in lock_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a+b") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle, fcntl.LOCK_UN)
        pending = context["target_sleeve"].metadata.get(replacement.MARKER)
        if pending:
            bound = replacement.inspect_replacement_recovery_target(
                settings, replacement_id=pending
            )
            assert bound["book"] == context["book"]
            assert bound["target_config"] == context["target_config"]
            assert bound["target_sleeve"] == context["target_sleeve"]
        calls.append(pending)

    sealed_verify = admission_v2.verify_for_replacement

    def locked_verify(settings, **context):
        for path in lock_paths:
            with path.open("a+b") as handle, pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return sealed_verify(settings, **context)

    monkeypatch.setattr(admission_v2, "prepare_replacement_preflight", prepare)
    monkeypatch.setattr(admission_v2, "verify_for_replacement", locked_verify)
    original = replacement._save_journal
    failures = []

    def interrupt(settings, record, phase):
        if phase == "book_bound" and not failures:
            failures.append(True)
            raise OSError("sealed interrupt")
        return original(settings, record, phase)

    monkeypatch.setattr(replacement, "_save_journal", interrupt)
    with pytest.raises(OSError):
        replacement.replace_verified_strategy(settings, **request)
    pending = storage.load_sleeve(sleeve.sleeve_id)
    result = replacement.recover_replacement(settings, pending.metadata[replacement.MARKER])
    assert result["status"] == "committed"
    assert len(calls) == 2 and calls[0] is None and calls[1] == result["replacement_id"]


def test_concurrent_identical_requests_have_one_committed_config_version(scenario):
    from concurrent.futures import ThreadPoolExecutor

    settings, storage, repo, sleeve, config, definitions, request = scenario
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(replacement.replace_verified_strategy, settings, **request)
            for _ in range(2)
        ]
        results = [future.result() for future in futures]
    assert {row["status"] for row in results} == {"committed"}
    assert len({row["replacement_id"] for row in results}) == 1
    assert [
        path.name
        for path in storage.strategy_config_dir(config.strategy_config_id).glob("config.v*.json")
    ] == ["config.v1.json", "config.v2.json"]


def test_prepared_journal_blocks_cycle_even_if_pause_write_failed(scenario, monkeypatch):
    from quant_system.d34.paper_cycle import _d34_running_sleeves

    settings, storage, repo, sleeve, config, definitions, request = scenario
    monkeypatch.setattr(
        PaperStrategySleeveStorage,
        "save_sleeve",
        lambda *a, **k: (_ for _ in ()).throw(OSError("sealed disk full")),
    )
    with pytest.raises(OSError):
        replacement.replace_verified_strategy(settings, **request)
    # Old storage may still say running, but the durable intent is a stop guard.
    assert storage.load_sleeve(sleeve.sleeve_id).status == StrategySleeveStatus.RUNNING
    assert replacement.sleeve_replacement_pending(storage, storage.load_sleeve(sleeve.sleeve_id))
    assert _d34_running_sleeves(storage) == []
    journal = next((settings.data.data_dir / "api_runs/strategy_replacements").glob("*.json"))
    document = json.loads(journal.read_text())
    document["phase"] = "committed"
    journal.write_text(json.dumps(document))
    assert _d34_running_sleeves(storage) == []


def test_a_corrupt_journal_for_another_sleeve_does_not_freeze_this_one(scenario, caplog):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    root = settings.data.data_dir / "api_runs/strategy_replacements"
    root.mkdir(parents=True, exist_ok=True)
    (root / ("replacement-" + "b" * 24 + ".json")).write_text(
        json.dumps(
            {
                "schema": replacement.SCHEMA,
                "replacement_id": "replacement-" + "b" * 24,
                "request": {"target_sleeve_id": "another-sleeve"},
                "phase": "committed",
                "journal_digest": "0" * 64,
            }
        )
    )
    (root / ("replacement-" + "c" * 24 + ".json")).write_text("not a journal at all")
    running = storage.load_sleeve(sleeve.sleeve_id)
    with caplog.at_level(logging.WARNING, logger=replacement.__name__):
        assert not replacement.sleeve_replacement_pending(storage, running)
    assert sorted(
        record.args[0] for record in caplog.records if "ignored_corrupt_record" in record.message
    ) == sorted([f"replacement-{'b' * 24}.json", f"replacement-{'c' * 24}.json"])
    assert storage.load_sleeve(sleeve.sleeve_id).strategy_config_version == 1


def test_corrupt_journal_naming_this_sleeve_still_fails_closed(scenario):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    root = settings.data.data_dir / "api_runs/strategy_replacements"
    root.mkdir(parents=True, exist_ok=True)
    running = storage.load_sleeve(sleeve.sleeve_id)
    unverified = root / ("replacement-" + "d" * 24 + ".json")
    unverified.write_text(
        json.dumps(
            {
                "schema": replacement.SCHEMA,
                "replacement_id": "replacement-" + "d" * 24,
                "request": {"target_sleeve_id": sleeve.sleeve_id},
                "phase": "committed",
                "journal_digest": "0" * 64,
            }
        )
    )
    assert replacement.sleeve_replacement_pending(storage, running)
    unverified.unlink()
    # A truncated write cannot be parsed, so the raw target field is the only
    # evidence that this sleeve owns it.
    (root / ("replacement-" + "e" * 24 + ".json")).write_text(
        '{"request": {"target_sleeve_id": "' + sleeve.sleeve_id + '", "target_can'
    )
    assert replacement.sleeve_replacement_pending(storage, running)


def test_changed_book_binding_is_journalled_and_recovery_stays_idempotent(scenario):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    identity = replacement.replace_verified_strategy(settings, **request)["replacement_id"]
    book = assistant_remote.load_book(settings)
    next(row for row in book["candidates"] if row["candidate_id"] == "old")["status"] = "verified"
    assistant_remote.save_book(settings, book)
    with pytest.raises(ValueError, match="replacement_book_cas_changed"):
        replacement.recover_replacement(settings, identity)
    record = replacement._load_journal(settings, identity)
    assert record["phase"] == "recovery_required"
    assert "replacement_book_cas_changed" in record["error"]
    assert storage.load_sleeve(sleeve.sleeve_id).strategy_config_version == 2
    with pytest.raises(ValueError, match="replacement_book_cas_changed"):
        replacement.recover_replacement(settings, identity)
    again = replacement._load_journal(settings, identity)
    assert again["phase"] == "recovery_required" and again["error"] == record["error"]


def test_old_signal_version_and_pending_execution_journal_cannot_cross_replacement(scenario):
    from quant_system.execution.paper_strategy_sleeves import StrategySignal

    settings, storage, repo, sleeve, config, definitions, request = scenario
    path = storage.execution_journal_dir(sleeve.sleeve_id) / "sealed.pending.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    with pytest.raises(ValueError, match="replacement_pending_execution_journal"):
        replacement.replace_verified_strategy(settings, **request)
    path.unlink()
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-09-18",
        data_provider="futu",
        proposed_orders=[{"symbol": "AAPL", "side": "buy"}],
    )
    replacement.replace_verified_strategy(settings, **request)
    with pytest.raises(ValueError, match="signal_config_version_mismatch"):
        PaperStrategySleeveService(storage).create_execution_plan(
            repo.load(), sleeve=storage.load_sleeve(sleeve.sleeve_id), signal=signal
        )


def test_account_transaction_exit_failure_also_freezes_the_changed_version(scenario, monkeypatch):
    from contextlib import contextmanager

    settings, storage, repo, sleeve, config, definitions, request = scenario
    original = PaperAccountStorage.mutation_lock

    @contextmanager
    def failed_commit(self, **kwargs):
        with original(self, **kwargs):
            yield
        raise OSError("sealed canonical commit failure")

    monkeypatch.setattr(PaperAccountStorage, "mutation_lock", failed_commit)
    before = repo.account_path.read_bytes()
    with pytest.raises(OSError, match="sealed canonical commit failure"):
        replacement.replace_verified_strategy(settings, **request)
    paused = storage.load_sleeve(sleeve.sleeve_id)
    assert paused.status == StrategySleeveStatus.PAUSED
    assert repo.account_path.read_bytes() == before
    monkeypatch.setattr(PaperAccountStorage, "mutation_lock", original)
    assert (
        replacement.recover_replacement(settings, paused.metadata[replacement.MARKER])["status"]
        == "committed"
    )


def test_second_aborted_replacement_recovers_after_abort_receipt_failure(scenario, monkeypatch):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    original = replacement._save_journal
    fault = {"phase": "book_bound", "fired": False}

    def fail_once(settings, record, phase):
        if phase == fault["phase"] and not fault["fired"]:
            fault["fired"] = True
            raise OSError("sealed repeated-abort fault")
        return original(settings, record, phase)

    monkeypatch.setattr(replacement, "_save_journal", fail_once)
    account_before = repo.account_path.read_bytes()
    with pytest.raises(OSError):
        replacement.replace_verified_strategy(settings, **request)
    first_id = storage.load_sleeve(sleeve.sleeve_id).metadata[replacement.MARKER]
    fault["phase"] = None
    replacement.recover_replacement(settings, first_id, action="abort")
    book = assistant_remote.load_book(settings)
    next(row for row in book["candidates"] if row["candidate_id"] == "new")["admission_v2"][
        "sha256"
    ] = "b" * 64
    assistant_remote.save_book(settings, book)
    second_request = {**request, "expected_admission_sha256": "b" * 64}
    fault.update(phase="config_saved", fired=False)
    with pytest.raises(OSError):
        replacement.replace_verified_strategy(settings, **second_request)
    second_id = storage.load_sleeve(sleeve.sleeve_id).metadata[replacement.MARKER]
    fault.update(phase="aborted", fired=False)
    with pytest.raises(OSError):
        replacement.recover_replacement(settings, second_id, action="abort")
    fault["phase"] = None
    result = replacement.recover_replacement(settings, second_id, action="abort")
    assert result["status"] == "aborted" and result["active_config_version"] == 1
    assert storage.load_sleeve(sleeve.sleeve_id).metadata["replacement_aborted_id"] == second_id
    assert (
        replacement._load_journal(settings, second_id)["old_sleeve"]["metadata"][
            "replacement_aborted_id"
        ]
        == first_id
    )
    assert storage.strategy_config_path(config.strategy_config_id, 3).is_file()
    assert repo.account_path.read_bytes() == account_before
    assert (
        replacement.inspect_replacement_target(settings, candidate_id="old")["replacement_target"][
            "config_version"
        ]
        == 1
    )


def test_committed_version_has_verified_observation_boundary_and_zero_economic_bridge(scenario):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    before = storage.load_sleeve(sleeve.sleeve_id)
    lots = storage.load_sleeve_lots(sleeve.sleeve_id)
    result = replacement.replace_verified_strategy(settings, **request)
    after = storage.load_sleeve(sleeve.sleeve_id)
    assert result["committed_at"] == after.metadata["current_version_observation_start"]
    assert result["performance_scope"] == replacement.PERFORMANCE_SCOPE_ACROSS_VERSIONS
    assert after.metadata["current_version_performance"]["status"] == "not_evaluated"
    assert replacement.replacement_transition_verified(
        storage, before_sleeve=before, after_sleeve=after, before_lots=lots, after_lots=lots
    )
    history = replacement.verified_replacement_history(storage, after)
    assert len(history) == 1 and history[0]["effective_at"] == result["committed_at"]
    assert history[0]["from_config_version"] == 1 and history[0]["to_config_version"] == 2
    changed = after.model_copy(deep=True)
    changed.cash += 1
    assert not replacement.replacement_transition_verified(
        storage, before_sleeve=before, after_sleeve=changed, before_lots=lots, after_lots=lots
    )
    changed = after.model_copy(deep=True)
    changed.metadata["arbitrary_new_metadata"] = True
    assert not replacement.replacement_transition_verified(
        storage, before_sleeve=before, after_sleeve=changed, before_lots=lots, after_lots=lots
    )


def test_unproven_transition_metadata_cannot_supply_a_timeline(scenario):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    fake = sleeve.model_copy(deep=True)
    fake.metadata["replacement_committed_id"] = "replacement-" + "a" * 24
    fake.metadata["current_version_observation_start"] = "2000-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="replacement_history"):
        replacement.verified_replacement_history(storage, fake)


def test_aborted_identity_bridge_is_verified_but_does_not_start_a_formula_window(
    scenario, monkeypatch
):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    before = storage.load_sleeve(sleeve.sleeve_id)
    lots = storage.load_sleeve_lots(sleeve.sleeve_id)
    save = replacement._save_journal
    fired = []

    def fail(settings, record, phase):
        if phase == "config_saved" and not fired:
            fired.append(True)
            raise OSError("sealed stop")
        return save(settings, record, phase)

    monkeypatch.setattr(replacement, "_save_journal", fail)
    with pytest.raises(OSError):
        replacement.replace_verified_strategy(settings, **request)
    identity = storage.load_sleeve(sleeve.sleeve_id).metadata[replacement.MARKER]
    replacement.recover_replacement(settings, identity, action="abort")
    after = storage.load_sleeve(sleeve.sleeve_id)
    assert replacement.replacement_transition_verified(
        storage, before_sleeve=before, after_sleeve=after, before_lots=lots, after_lots=lots
    )
    assert replacement.verified_replacement_history(storage, after) == []
    assert "current_version_observation_start" not in after.metadata
    changed = [lot.model_copy(deep=True) for lot in lots]
    changed[0].quantity += 1
    assert not replacement.replacement_transition_verified(
        storage, before_sleeve=before, after_sleeve=after, before_lots=lots, after_lots=changed
    )


def test_resigned_other_config_cannot_replace_the_actual_active_config_binding(scenario):
    settings, storage, repo, sleeve, config, definitions, request = scenario
    before = storage.load_sleeve(sleeve.sleeve_id)
    lots = storage.load_sleeve_lots(sleeve.sleeve_id)
    receipt = replacement.replace_verified_strategy(settings, **request)
    after = storage.load_sleeve(sleeve.sleeve_id)
    record = replacement._load_journal(settings, receipt["replacement_id"])
    record["new_config"]["strategy_config_id"] = "strategy-config-other"
    other = storage.strategy_config_path("strategy-config-other", 2)
    other.parent.mkdir(parents=True)
    other.write_text(json.dumps(record["new_config"]))
    replacement._save_journal(settings, record, "committed")
    storage.strategy_config_path(config.strategy_config_id, 2).unlink()
    assert not replacement.replacement_transition_verified(
        storage, before_sleeve=before, after_sleeve=after, before_lots=lots, after_lots=lots
    )
    with pytest.raises(ValueError, match="replacement_history"):
        replacement.verified_replacement_history(storage, after)


@pytest.fixture
def drifted_scenario(scenario, monkeypatch):
    """Artificial source drift over real lifecycle/storage code; no market claim."""
    from quant_system.research import strategy_definition as definitions_module

    settings, storage, repo, sleeve, config, definitions, request = scenario
    original_digest = definitions_module._file_digest

    def changed_digest(path):
        if str(path).endswith('/research/strategy_runtime.py'):
            return 'b' * 64
        return original_digest(path)

    monkeypatch.setattr(definitions_module, '_file_digest', changed_digest)
    current = StrategyDefinition(**definitions[1].model_dump(
        mode='json', exclude={'content_digest', 'source_fingerprints'}
    ))
    book = assistant_remote.load_book(settings)
    new = next(row for row in book['candidates'] if row['candidate_id'] == 'new')
    Path(new['source_path']).write_text(json.dumps(current.model_dump(mode='json')))
    new.update(source_digest=replacement.file_sha(new['source_path']),
               definition_digest=current.content_digest,
               factor_id='definition_' + current.content_digest[:24])
    request['expected_new_source_digest'] = new['source_digest']
    assistant_remote.save_book(settings, book)
    return scenario


def test_stale_target_can_be_inspected_without_authorizing_execution(drifted_scenario):
    from quant_system.research.strategy_definition import validate_definition

    settings, storage, repo, sleeve, config, definitions, request = drifted_scenario
    before = repo.account_path.read_bytes()
    with pytest.raises(ValueError, match='strategy_algorithm_source_mismatch'):
        storage.load_strategy_config(config.strategy_config_id, version=config.version)
    target = replacement.inspect_replacement_target(settings, candidate_id='old')
    assert target['definition'] == definitions[0].model_dump(mode='json')
    assert target['replacement_target']['definition_digest'] == definitions[0].content_digest
    with pytest.raises(ValueError, match='strategy_algorithm_source_mismatch'):
        validate_definition(target['definition'])
    assert repo.account_path.read_bytes() == before


def test_stale_target_replacement_requires_current_new_definition(drifted_scenario):
    settings, storage, repo, sleeve, config, definitions, request = drifted_scenario
    before = repo.account_path.read_bytes()
    result = replacement.replace_verified_strategy(settings, **request)
    assert result['status'] == 'committed'
    current = storage.load_strategy_config(config.strategy_config_id, version=2)
    assert current.strategy_definition['content_digest'] != definitions[0].content_digest
    assert storage.load_sleeve(sleeve.sleeve_id).strategy_config_version == 2
    assert repo.account_path.read_bytes() == before


@pytest.mark.parametrize('action', ['complete', 'abort'])
def test_stale_target_interruption_recovers_without_resuming_invalid_old_code(
    drifted_scenario, monkeypatch, action
):
    settings, storage, repo, sleeve, config, definitions, request = drifted_scenario
    before = repo.account_path.read_bytes()
    original = replacement._save_journal
    failed = []

    def fail_once(settings, record, phase):
        if phase == 'config_saved' and not failed:
            failed.append(True)
            raise OSError('sealed drift recovery fault')
        return original(settings, record, phase)

    monkeypatch.setattr(replacement, '_save_journal', fail_once)
    with pytest.raises(OSError, match='sealed drift recovery fault'):
        replacement.replace_verified_strategy(settings, **request)
    held = storage.load_sleeve(sleeve.sleeve_id)
    assert held.status == StrategySleeveStatus.PAUSED
    identity = held.metadata[replacement.MARKER]
    result = replacement.recover_replacement(settings, identity, action=action)
    assert result['status'] == ('committed' if action == 'complete' else 'aborted')
    restored = storage.load_sleeve(sleeve.sleeve_id)
    assert restored.status == (StrategySleeveStatus.RUNNING if action == 'complete'
                               else StrategySleeveStatus.PAUSED)
    assert restored.strategy_config_version == (2 if action == 'complete' else 1)
    assert repo.account_path.read_bytes() == before
    history = replacement.verified_replacement_history(storage, restored)
    assert history is not None
    if action == 'abort':
        target = replacement.inspect_replacement_target(settings, candidate_id='old')
        assert target['replacement_target']['config_version'] == 1
        # The persisted abort is idempotent and remains paused.
        again = replacement.recover_replacement(settings, identity, action='abort')
        assert again['status'] == 'aborted'


def test_stale_target_tampered_source_is_still_rejected(drifted_scenario):
    settings, storage, repo, sleeve, config, definitions, request = drifted_scenario
    book = assistant_remote.load_book(settings)
    old = next(row for row in book['candidates'] if row['candidate_id'] == 'old')
    path = Path(old['source_path'])
    path.write_text(path.read_text() + '\n')
    with pytest.raises(ValueError, match='replacement_source_changed'):
        replacement.inspect_replacement_target(settings, candidate_id='old')


def test_abort_can_restore_identity_when_new_candidate_also_became_stale(
    drifted_scenario, monkeypatch
):
    from quant_system.research import strategy_definition as module

    settings, storage, repo, sleeve, config, definitions, request = drifted_scenario
    original_save = replacement._save_journal
    failed = []

    def fail_once(settings, record, phase):
        if phase == 'config_saved' and not failed:
            failed.append(True)
            raise OSError('sealed abort source drift')
        return original_save(settings, record, phase)

    monkeypatch.setattr(replacement, '_save_journal', fail_once)
    with pytest.raises(OSError):
        replacement.replace_verified_strategy(settings, **request)
    held = storage.load_sleeve(sleeve.sleeve_id)
    identity = held.metadata[replacement.MARKER]
    original_digest = module._file_digest
    monkeypatch.setattr(module, '_file_digest', lambda p: 'c' * 64
                        if str(p).endswith('/research/strategy_runtime.py') else original_digest(p))
    with pytest.raises(ValueError, match='strategy_algorithm_source_mismatch'):
        replacement.recover_replacement(settings, identity, action='complete')
    result = replacement.recover_replacement(settings, identity, action='abort')
    assert result['status'] == 'aborted'
    assert storage.load_sleeve(sleeve.sleeve_id).status == StrategySleeveStatus.PAUSED


def test_a_new_candidate_with_algorithm_drift_never_uses_historical_permission(
    scenario, monkeypatch
):
    from quant_system.research import strategy_definition as module

    settings, storage, repo, sleeve, config, definitions, request = scenario
    original_digest = module._file_digest
    monkeypatch.setattr(module, '_file_digest', lambda p: 'c' * 64
                        if str(p).endswith('/research/strategy_runtime.py') else original_digest(p))
    before = repo.account_path.read_bytes()
    with pytest.raises(ValueError, match='strategy_algorithm_source_mismatch'):
        replacement.replace_verified_strategy(settings, **request)
    assert storage.load_sleeve(sleeve.sleeve_id).strategy_config_version == 1
    assert repo.account_path.read_bytes() == before


@pytest.mark.parametrize("field,value", [("strategy_config_id", "other-config"), ("version", 9)])
def test_frozen_config_reader_checks_path_identity(drifted_scenario, field, value):
    settings, storage, repo, sleeve, config, definitions, request = drifted_scenario
    path = storage.strategy_config_path(config.strategy_config_id, config.version)
    raw = json.loads(path.read_text())
    raw[field] = value
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="replacement_config_path_identity_mismatch"):
        replacement.inspect_replacement_target(settings, candidate_id="old")
