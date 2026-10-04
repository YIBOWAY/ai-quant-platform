"""Artificial original-file scope checks; no qualification/funding claims."""

import json

import pytest

from quant_system.research import admission_consumer_checks as checks
from tests import test_admission_v2 as core


def complete_context(tmp_path):
    from quant_system.research.validation_receipts import receipt_bindings

    context = core.context.__wrapped__(tmp_path)
    run = context["validation_path"].parent
    payload = json.loads((run / "platform-result.json").read_text())
    # Explicit artificial fill economics. These are input originals for a pure
    # prerequisite test, not an engine/PG qualification or a real market result.
    payload["trades"] = [
        {
            "side": "buy",
            "quantity": 100,
            "requested_price": 100 / 1.0005,
            "fill_price": 100,
            "commission": 1,
        }
    ]
    core.write(run / "platform-result.json", payload)
    for filename, field in (
        ("qlib-replay.json", "platform_result_sha256"),
        ("signal-analysis.json", "result_sha256"),
    ):
        value = json.loads((run / filename).read_text())
        value["source"][field] = core.admission.file_sha(run / "platform-result.json")
        core.write(run / filename, value)
    validation = json.loads((run / "validation.json").read_text())
    validation["receipts"] = receipt_bindings(run)
    core.write(run / "validation.json", validation)
    context["expected_validation_sha"] = core.admission.file_sha(run / "validation.json")
    return context


def test_complete_original_family_uses_real_common_quality_and_no_peer_state(tmp_path):
    c = complete_context(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = checks.inspect_current_consumer_scope(c["settings"], c["validation_path"])
    assert result["status"] == "ready_for_verification", result
    assert result["family"]["n_trials"] == 12 and result["family"]["excluded"] == []
    assert result["minimum_quality"]["schema"] == "new_paper_capital_minimum_quality/v1"
    assert result["concentration"]["raw_status"] == "not_applicable"
    assert result["concentration"]["raw_reason"] == "no_peers"
    assert result["controls_run"] == 0 and result["postgres"] == "not_run"
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_same_universe_missing_member_blocks_but_unrelated_universe_does_not(tmp_path):
    c = complete_context(tmp_path)
    ledger = tmp_path / "trials/trials.jsonl"
    before = checks.inspect_current_consumer_scope(c["settings"], c["validation_path"])
    from tests.gate_v2_fixtures import trial_row

    row = trial_row(trial_id="unrelated", universe=["ELSEWHERE"])
    with ledger.open("a") as h:
        h.write(json.dumps(row.model_dump(mode="json")) + "\n")
    other = checks.inspect_current_consumer_scope(c["settings"], c["validation_path"])
    assert other["family"]["family_digest"] == before["family"]["family_digest"]
    (tmp_path / "strategy_library/family-0/validations/test/platform-result.json").unlink()
    missing = checks.inspect_current_consumer_scope(c["settings"], c["validation_path"])
    assert missing["status"] == "not_evaluated"
    assert missing["reason"] == "current_family_evidence_incomplete"
    assert len(missing["family"]["excluded"]) == 1


def test_missing_family_prevents_pg_and_control_work_in_real_verifier(tmp_path, monkeypatch):
    c = complete_context(tmp_path)
    (tmp_path / "strategy_library/family-0/validations/test/platform-result.json").unlink()
    monkeypatch.setattr(
        checks, "_fixed_consumer_tests", lambda *a, **k: pytest.fail("PG must not run")
    )
    monkeypatch.setattr(
        checks, "_load_context", lambda *a, **k: pytest.fail("old500 must not load")
    )
    from quant_system.research.admission_v2 import SCOPE, code_identity

    result = checks.verify_consumer_checks(
        c["settings"],
        scope=SCOPE,
        code_digest=code_identity()["digest"],
        evidence={
            "current_control_rule": checks.CURRENT_CONTROL_RULE,
            "validation_path": str(c["validation_path"]),
            "random_root": "unused",
            "data_root": "unused",
            "peer_snapshot_path": "unused",
        },
    )
    assert result["reason"] == "current_family_evidence_incomplete"
    assert result["current_scope"]["controls_run"] == 0
    assert all(x["status"] == "not_evaluated" for x in result["checks"].values())


def test_old_control_contract_never_becomes_current_qualification(tmp_path, monkeypatch):
    c = complete_context(tmp_path)
    monkeypatch.setattr(
        checks, "_fixed_consumer_tests", lambda *a, **k: pytest.fail("PG must not run")
    )
    monkeypatch.setattr(checks, "_load_context", lambda *a, **k: pytest.fail("old500 must not run"))
    from quant_system.research.admission_v2 import SCOPE, code_identity

    result = checks.verify_consumer_checks(
        c["settings"],
        scope=SCOPE,
        code_digest=code_identity()["digest"],
        evidence={
            "validation_path": str(c["validation_path"]),
            "random_root": "unused",
            "data_root": "unused",
            "peer_snapshot_path": "unused",
        },
    )
    assert result["reason"] == "current_control_contract_required"
    assert all(x["status"] == "not_evaluated" for x in result["checks"].values())


def test_current_family_with_missing_peer_originals_never_abstains(tmp_path):
    c = complete_context(tmp_path)
    core.write(
        tmp_path / "assistant_remote/book.json",
        {
            "contract": "hqa.assistant_remote_book/v1",
            "candidates": [
                {
                    "candidate_id": "wrong",
                    "sleeve_id": "wrong",
                    "status": "hung",
                    "source": "strategy_definition",
                    "source_path": str(tmp_path / "missing.json"),
                    "source_digest": "0" * 64,
                }
            ],
        },
    )
    result = checks.inspect_current_consumer_scope(c["settings"], c["validation_path"])
    assert result["status"] == "not_evaluated"
    assert result["reason"] is not None


def test_scalar_turnover_claim_cannot_replace_original_fills(tmp_path):
    c = complete_context(tmp_path)
    p = c["validation_path"].parent / "platform-result.json"
    v = json.loads(p.read_text())
    v["trades"][0]["commission"] = 2
    core.write(p, v)
    result = checks.inspect_current_consumer_scope(c["settings"], c["validation_path"])
    assert result["status"] == "not_evaluated"


def test_missing_F_artifact_stops_before_postgres_or_old_controls(tmp_path, monkeypatch):
    c = complete_context(tmp_path)
    monkeypatch.setattr(
        checks, "_fixed_consumer_tests", lambda *a, **k: pytest.fail("PG must not run")
    )
    monkeypatch.setattr(
        checks, "_load_context", lambda *a, **k: pytest.fail("controls must not run")
    )
    from quant_system.research.admission_v2 import SCOPE, code_identity

    result = checks.verify_consumer_checks(
        c["settings"],
        scope=SCOPE,
        code_digest=code_identity()["digest"],
        evidence={
            "current_control_rule": checks.CURRENT_CONTROL_RULE,
            "validation_path": str(c["validation_path"]),
            "random_root": "unused",
            "data_root": "unused",
            "peer_snapshot_path": "unused",
        },
    )
    assert result["semantic_calibration"]["status"] == "not_evaluated"
    assert result["reason"] == "semantic_calibration_descriptor_required"
    assert all(item["status"] == "not_evaluated" for item in result["checks"].values())


def test_declared_failed_F_cannot_be_relabelled_a_pass(tmp_path):
    descriptor = {}
    for name, value in {
        "summary": {
            "schema": "admission_semantics_synthetic_calibration_result/v1",
            "status": "failed",
        },
        "contract": {},
        "addendum": {},
    }.items():
        path = tmp_path / (name + ".json")
        core.write(path, value)
        descriptor[name] = {"path": str(path), "sha256": checks._sha(path)}
    result = checks.verify_semantic_calibration(descriptor)
    assert result["status"] == "not_evaluated"
    assert result["reason"] == "semantic_calibration_not_passed"


def test_control_trace_is_context_local_and_not_an_authority_input():
    with checks.collect_control_execution_trace() as first:
        checks._CONTROL_WORK.get().append({"confirmed_variant_engine_runs": 1})
        with checks.collect_control_execution_trace() as second:
            assert second == []
        assert first == [{"confirmed_variant_engine_runs": 1}]
    assert checks._CONTROL_WORK.get() is None


def _physical_peer(c, tmp_path, *, stopped=False, book_status="hung"):
    from quant_system.execution.paper_strategy_sleeves import StrategySleeveStatus
    from tests.test_capital_peer_binding import historical_peer

    peer = {
        "candidate_id": "physical-peer", "sleeve_id": "physical-sleeve",
        "status": book_status, "source_digest": "a" * 64,
        # Deliberately missing research originals: a stopped empty sleeve is
        # excluded by physical exposure, an active sleeve may not disappear.
    }
    from quant_system.config.settings import DataSettings, Settings

    c["settings"] = Settings(data=DataSettings(data_dir=tmp_path))
    storage, sleeve = historical_peer(c["settings"], peer)
    if stopped:
        sleeve.status = StrategySleeveStatus.STOPPED
        storage.save_sleeve(sleeve)
    core.write(tmp_path / "assistant_remote/book.json", {
        "contract": "hqa.assistant_remote_book/v1", "candidates": [peer],
    })
    return storage, sleeve


def test_stopped_empty_peer_uses_physical_projection_and_pins_originals(tmp_path):
    c = complete_context(tmp_path)
    storage, sleeve = _physical_peer(c, tmp_path, stopped=True)
    result = checks.inspect_current_consumer_scope(c["settings"], c["validation_path"])
    assert result["status"] == "ready_for_verification", result
    assert result["peers"] == []
    assert str(storage.sleeve_path(sleeve.sleeve_id)) in result["input_files"]
    assert result["physical_peer_sources"][str(storage.sleeve_lots_path(sleeve.sleeve_id))] is False


def test_bound_active_peer_with_changed_book_status_cannot_disappear(tmp_path):
    c = complete_context(tmp_path)
    _physical_peer(c, tmp_path, book_status="verified")
    result = checks.inspect_current_consumer_scope(c["settings"], c["validation_path"])
    assert result["status"] == "not_evaluated", result
    assert result["reason"] == "peer_book_status_mismatch"


def test_new_lot_in_stopped_peer_invalidates_previous_no_exposure_scope(tmp_path):
    from quant_system.execution.paper_strategy_sleeves import SleeveLot

    c = complete_context(tmp_path)
    storage, sleeve = _physical_peer(c, tmp_path, stopped=True)
    before = checks.inspect_current_consumer_scope(c["settings"], c["validation_path"])
    assert before["status"] == "ready_for_verification", before
    storage.save_sleeve_lots(sleeve.sleeve_id, [SleeveLot.create(
        sleeve_id=sleeve.sleeve_id, symbol="SPY", quantity=1, avg_cost=100,
        source="artificial-scope-counterexample",
    )])
    after = checks.inspect_current_consumer_scope(c["settings"], c["validation_path"])
    assert after["status"] == "not_evaluated"
    assert after["scope_digest"] != before["scope_digest"]


def _control_originals(tmp_path):
    from quant_system.backtest.models import BacktestConfig

    root = tmp_path / "control"
    config = root / "variant-0000/config.json"
    core.write(config, BacktestConfig().model_dump(mode="json"))
    profile = {"source": "futu", "price_adjustment": "qfq", "frequency": "daily",
               "profile": {"benchmark_symbol": "SPY"}}
    core.write(root / "saved-study-snapshot.json", {"results": [profile]})
    files = {str(p): checks._sha(p) for p in root.rglob("*.json")}
    return root, profile, files


@pytest.mark.parametrize("field,value", [
    ("benchmark", {"symbol": "QQQ", "method": "net_buy_and_hold"}),
    ("frequency", "monthly"),
    ("cost_definition", {"model": "proportional_bps", "commission_bps": 2,
                         "slippage_bps": 5, "cash_interest": 0}),
    ("market_data_contract", {"provider": "other", "price_adjustment": "qfq",
                              "currency": "USD", "bar": "1d"}),
])
def test_control_original_contract_is_not_relabelled_as_candidate(tmp_path, field, value):
    root, profile, files = _control_originals(tmp_path)
    own = checks._current_control_contract(root, profile, files)
    candidate = json.loads(json.dumps(own))
    candidate[field] = value
    with pytest.raises(ValueError, match="current_control_compatibility_mismatch"):
        checks._require_control_compatibility(candidate, own)
    assert checks._require_control_compatibility(own, own) == own


@pytest.mark.parametrize("missing", ["frequency", "source", "benchmark_symbol", "commission_bps"])
def test_control_contract_missing_original_fields_are_not_defaulted(tmp_path, missing):
    root, profile, files = _control_originals(tmp_path)
    if missing == "commission_bps":
        path = root / "variant-0000/config.json"
        value = json.loads(path.read_text())
        value.pop(missing)
        core.write(path, value)
        files[str(path)] = checks._sha(path)
    elif missing == "benchmark_symbol":
        profile["profile"].pop(missing)
    else:
        profile.pop(missing)
    path = root / "saved-study-snapshot.json"
    core.write(path, {"results": [profile]})
    files[str(path)] = checks._sha(path)
    with pytest.raises((ValueError, KeyError)):
        checks._current_control_contract(root, profile, files)


def test_resealed_F_plan_cannot_change_registered_pre_sampling_identity(tmp_path):
    # A fully self-consistent descriptor SHA is still not the frozen plan.
    descriptor = {}
    for name, value in {
        "summary": {"schema": "admission_semantics_synthetic_calibration_result/v1",
                    "status": "passed"},
        "contract": {"scope": "changed", "seeds": {"main_null": 42}},
        "addendum": {},
    }.items():
        path = tmp_path / (name + ".json")
        core.write(path, value)
        descriptor[name] = {"path": str(path), "sha256": checks._sha(path)}
    result = checks.verify_semantic_calibration(descriptor)
    assert result["status"] == "not_evaluated"
    assert result["reason"] == "semantic_calibration_frozen_contract_mismatch"
