"""Real stage/family/peer checks with the established sealed qualifier boundary.

All prices and curves here are explicit artificial fixtures. The qualification
program is sealed infrastructure; these tests never claim 500 market controls
or PG ran, and never replace a gate/statistic/family/account implementation.
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
from contextlib import contextmanager

import pytest

from quant_system.execution import assistant_remote as remote
from quant_system.research import admission_activation as activation
from quant_system.research import admission_consumer_checks as checks
from quant_system.research import admission_v2 as admission
from quant_system.research.validation_receipts import receipt_bindings
from tests import test_admission_v2 as core
from tests.test_admission_qualification_flow import recipes
from tests.test_capital_evidence import definition_archive, tree
from tests.test_capital_peer_binding import historical_peer
from tests.test_current_consumer_qualification import complete_context
from tests.test_qualification_dependency_closure import plain_dependencies


@contextmanager
def stage_case(tmp_path, monkeypatch, *, tier="T2", with_peer=True, fault=None, legacy=False):
    # Actual window code must load before the existing external-capability stub.
    importlib.import_module("quant_system.research.admission_window")
    producer = core.sealed_producer.__wrapped__(monkeypatch)
    next(producer)
    try:
        context = complete_context(tmp_path)
        settings = context["settings"]
        run = context["validation_path"].parent
        if with_peer:
            _, originals, _ = definition_archive(tmp_path / "peer-originals", n=2)
            peer = copy.deepcopy(originals[1])
            peer.update(status="hung", candidate_id="artificial-stage-peer", sleeve_id="stage-peer")
            historical_peer(settings, peer)
            book = remote.load_book(settings)
            book["candidates"].append(peer)
            remote.save_book(settings, book)
            context["book"] = book
        if tier == "T0":
            payload = json.loads((run / "platform-result.json").read_text())
            equity = 10000
            for i, row in enumerate(payload["curve"]):
                equity *= 1 - 0.003 + (0.004 if i % 2 else -0.004)
                row["equity"] = equity
            core.write(run / "platform-result.json", payload)
            for name, field in (
                ("qlib-replay.json", "platform_result_sha256"),
                ("signal-analysis.json", "result_sha256"),
            ):
                value = json.loads((run / name).read_text())
                value["source"][field] = admission.file_sha(run / "platform-result.json")
                core.write(run / name, value)
            validation = json.loads(context["validation_path"].read_text())
            validation["receipts"] = receipt_bindings(run)
            core.write(context["validation_path"], validation)
            context["expected_validation_sha"] = admission.file_sha(context["validation_path"])
        _, fresh = core.qualify(context, expected_tier=tier)
        descriptor = admission.write_receipt(run, fresh)
        job_path = tmp_path / "research_intake/jobs" / (context["protocol"]["job_id"] + ".json")
        job = json.loads(job_path.read_text())
        job.update(
            status="completed",
            results=[
                {
                    "variant": "formula",
                    "admission_v2": descriptor,
                    "validation_sha256": context["expected_validation_sha"],
                }
            ],
        )
        core.write(job_path, job)
        recipes(settings)
        actual_scope = checks.inspect_current_consumer_scope(settings, context["validation_path"])
        assert actual_scope["status"] == "ready_for_verification", actual_scope
        _, admission_peers = admission.peer_snapshot(remote.load_book(settings), settings=settings)
        assert admission_peers["digest"] == fresh["source_binding"]["peer_digest"]
        assert admission_peers["digest"] != actual_scope["peer_digest"]
        assert len(actual_scope["peers"]) == int(with_peer)
        # The second peer identity is calculated by the real authority adapter,
        # never copied from a claimed qualifier population or a hand-set digest.
        assert actual_scope["admission_peer_digest"] == admission_peers["digest"]
        population = {
            "family_digest": actual_scope["family"]["family_digest"],
            "family_n_trials": actual_scope["family"]["n_trials"],
            "original_ledger_sha256": actual_scope["trial_ledger_sha256"],
            "peer_digest": actual_scope["peer_digest"],
            "admission_peer_digest": admission_peers["digest"],
            "peer_windows": [
                {
                    "sleeve_id": peer["sleeve_id"],
                    "start": peer["dates"][0],
                    "end": peer["dates"][-1],
                    "periods": len(peer["dates"]),
                }
                for peer in actual_scope["peers"]
            ],
            "concentration_alignment": "actual_date_intersection_not_full_candidate_window",
            "control_version": "sealed-current-control",
            "n_controls": 500,
            "statistically_evaluable": 500,
            "purpose": "fixed_real_price_controls_under_current_complete_family_and_strict_peers",
        }
        # Ordinary artificial leaves satisfy the qualifier infrastructure
        # contract without claiming that F/control/PG programs ran here.
        dependencies, _ = plain_dependencies(tmp_path / "ARTIFICIAL-stage-dependencies")
        calibration = {
            "input_files": dependencies["calibration"]["input_files"],
            "current_scope": actual_scope,
            "family": actual_scope["family"],
            "peer_identity": {"digest": actual_scope["peer_digest"]},
            "n_controls": 500,
            "statistically_evaluable": 500,
            "calibration_passed": True,
        }
        details = {
            **dependencies,
            "current_control_rule": checks.CURRENT_CONTROL_RULE,
            "current_control_population": population,
            "calibration": calibration,
            "calibration_digest": checks._hash(calibration),
            "control_version": "sealed-current-control",
            "historical_family_39": {
                "purpose": "original_engine_population_provenance_only",
                "new_funding_qualification": False,
            },
        }
        if legacy:
            details = {
                "calibration_digest": "a" * 64,
                "control_version": "sealed-legacy",
                "historical_control_population": {"family_digest": "b" * 64, "family_n_trials": 39},
            }
        if fault:
            fault(details)
        scope = admission.qualification_input_context(fresh["source_binding"])
        monkeypatch.setattr(
            activation, "_scope", lambda: {"scope": admission.SCOPE, "context": scope}
        )
        monkeypatch.setattr(
            "quant_system.research.admission_qualification_flow.ensure_qualifications",
            lambda *a, **k: {"status": "registered"},
        )
        module = sys.modules["quant_system.research.admission_qualifier"]
        verify = module.verify_registered_qualification

        def sealed_capability(*args, **kwargs):
            result = verify(*args, **kwargs)
            if kwargs["kind"] == "consumer" and result["status"] == "passed":
                result["details"].update(copy.deepcopy(details))
            return result

        monkeypatch.setattr(module, "verify_registered_qualification", sealed_capability)
        yield settings, fresh, copy.deepcopy(population)
    finally:
        producer.close()


@pytest.mark.parametrize("tier,with_peer", [("T2", True), ("T0", True), ("T2", False)])
def test_real_stage_binds_current_population_without_requiring_a_winner(
    tmp_path, monkeypatch, tier, with_peer
):
    with stage_case(tmp_path, monkeypatch, tier=tier, with_peer=with_peer) as (
        settings,
        fresh,
        expected,
    ):
        before = tree(tmp_path)
        stage = activation._review_stage(settings, activation._snapshot(settings)["cohort"])
        assert stage["rows"][0]["current_qualified_tier"] == tier
        assert stage["current_stage_populations"][0]["current_family_n_trials"] == 12
        assert stage["historical_control_populations"] == []
        assert len(stage["current_control_populations"]) == 1
        actual = stage["current_control_populations"][0]
        assert all(actual.get(key) == value for key, value in expected.items())
        assert actual["admission_peer_digest"] == fresh["source_binding"]["peer_digest"]
        assert actual["peer_digest"] != actual["admission_peer_digest"]
        assert tree(tmp_path) == before


@pytest.mark.parametrize(
    "field",
    [
        "family_digest",
        "family_n_trials",
        "original_ledger_sha256",
        "admission_peer_digest",
        "peer_digest",
    ],
)
def test_real_stage_rejects_current_population_identity_mismatch(tmp_path, monkeypatch, field):
    def fault(details):
        details["current_control_population"][field] = (
            39 if field == "family_n_trials" else "f" * 64
        )

    with stage_case(tmp_path, monkeypatch, fault=fault) as (settings, _, _):
        before = tree(tmp_path)
        with pytest.raises(ValueError, match="activation_current_control"):
            activation._review_stage(settings, activation._snapshot(settings)["cohort"])
        assert tree(tmp_path) == before


@pytest.mark.parametrize(
    "fault",
    [
        "missing_population",
        "missing_rule",
        "wrong_rule",
        "missing_admission_peer",
        "numerical_peer_as_authority",
    ],
)
def test_real_stage_current_shape_cannot_fall_back_to_historical_39(tmp_path, monkeypatch, fault):
    def corrupt(details):
        # Even the presence of a valid-looking old field must not mask bad current proof.
        details["historical_control_population"] = {
            "family_digest": "b" * 64,
            "family_n_trials": 39,
        }
        if fault == "missing_population":
            details.pop("current_control_population")
        elif fault == "missing_rule":
            details.pop("current_control_rule")
        elif fault == "wrong_rule":
            details["current_control_rule"] = "unknown-current-rule"
        elif fault == "missing_admission_peer":
            details["current_control_population"].pop("admission_peer_digest")
        else:
            p = details["current_control_population"]
            p["admission_peer_digest"] = p["peer_digest"]

    with stage_case(tmp_path, monkeypatch, fault=corrupt) as (settings, _, _):
        before = tree(tmp_path)
        with pytest.raises(ValueError, match="activation_current_control"):
            activation._review_stage(settings, activation._snapshot(settings)["cohort"])
        assert tree(tmp_path) == before


def test_real_stage_keeps_explicit_old_population_as_historical(tmp_path, monkeypatch):
    with stage_case(tmp_path, monkeypatch, legacy=True) as (settings, _, _):
        before = tree(tmp_path)
        stage = activation._review_stage(settings, activation._snapshot(settings)["cohort"])
        assert stage.get("current_control_populations", []) == []
        assert len(stage["historical_control_populations"]) == 1
        old = stage["historical_control_populations"][0]
        assert old["family_n_trials"] == 39
        assert old["purpose"] == "static_code_calibration_with_frozen_historical_39_family_2_peers"
        assert old["not_current_family_false_pass_estimate"] is True
        assert tree(tmp_path) == before
