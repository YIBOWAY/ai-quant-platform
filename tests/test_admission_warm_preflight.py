"""No expensive qualification program may run while money/book locks are held."""

import sys
from contextlib import contextmanager

import pytest

from quant_system.execution import assistant_remote as remote
from quant_system.research import admission_consumer_checks as checks
from quant_system.research import admission_v2 as admission
from tests import test_admission_v2_consumers as fixtures


@pytest.fixture
def context(tmp_path):
    return fixtures.context.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def sealed_producer(monkeypatch):
    yield from fixtures.sealed_producer.__wrapped__(monkeypatch)


def test_cold_locked_and_ui_paths_require_preflight_without_executing_program(context, monkeypatch):
    settings, entry, candidate = fixtures.fundable_consumer(context, monkeypatch)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    admission._WARM_QUALIFICATIONS.clear()
    monkeypatch.setattr(
        sys.modules["quant_system.research.admission_qualifier"],
        "verify_registered_qualification",
        lambda *a, **k: pytest.fail("cold locked producer"),
    )
    with pytest.raises(ValueError, match="qualification_preflight_required"):
        admission.verify_locked_new_capital(
            settings,
            candidate["admission_v2"],
            definition_digest=candidate["definition_digest"],
            validation_sha256=candidate["verification_receipt_digest"],
            source_sha256=candidate["source_digest"],
            book=remote.load_book(settings),
        )
    projected = remote._project_activation_eligibility(settings, candidate, [candidate])
    assert projected == {
        "eligible": True,
        "reason": "preflight_on_enable",
        "protocol": admission.PROTOCOL_VERSION,
    }
    assert not (settings.data.data_dir / "api_runs").exists()


def test_cold_projection_refuses_missing_or_expired_registration(context, monkeypatch):
    """The read-only projection must not advertise authority it cannot recheck."""
    import json
    from pathlib import Path

    from quant_system.research.admission_qualification_flow import _root

    settings, entry, candidate = fixtures.fundable_consumer(context, monkeypatch)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    admission._WARM_QUALIFICATIONS.clear()
    monkeypatch.setattr(
        sys.modules["quant_system.research.admission_qualifier"],
        "verify_registered_qualification",
        lambda *a, **k: pytest.fail("projection invoked a producer"),
    )
    index = Path(_root(settings)) / "qualifications.json"
    document = json.loads(index.read_text())
    assert document["entries"]
    for refs in document["entries"].values():
        refs[next(iter(refs))] = {**refs[next(iter(refs))], "sha256": "0" * 64}
        break
    index.write_text(json.dumps(document))
    expired = remote._project_activation_eligibility(settings, candidate, [candidate])
    assert expired["eligible"] is False
    assert expired["reason"] == "admission_v2_qualification_changed"

    document = json.loads(index.read_text())
    for refs in document["entries"].values():
        refs.pop(next(iter(refs)))
        break
    index.write_text(json.dumps(document))
    missing = remote._project_activation_eligibility(settings, candidate, [candidate])
    assert missing["eligible"] is False
    assert missing["reason"] == "admission_v2_qualification_changed"
    assert not (settings.data.data_dir / "api_runs").exists()


@pytest.mark.parametrize("evict_inside_lock", [False, True])
def test_money_lock_only_consumes_exact_process_warm_proof(context, monkeypatch, evict_inside_lock):
    settings, entry, candidate = fixtures.fundable_consumer(context, monkeypatch)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    module = sys.modules["quant_system.research.admission_qualifier"]
    original_verify, original_lock = (
        module.verify_registered_qualification,
        remote._book_mutation_lock,
    )
    state = {"locked": False, "outside_calls": 0}

    def no_locked_heavy(*args, **kwargs):
        assert not state["locked"], "subprocess or full calibration entered money lock"
        pytest.fail("sealed consumer test unexpectedly invoked a heavy program")

    monkeypatch.setattr(checks, "run_full_control", no_locked_heavy)
    monkeypatch.setattr(checks.subprocess, "run", no_locked_heavy)

    def verify(*args, **kwargs):
        assert not state["locked"], "qualification verifier entered money lock"
        state["outside_calls"] += 1
        return original_verify(*args, **kwargs)

    @contextmanager
    def lock(settings, **kwargs):
        with original_lock(settings, **kwargs):
            state["locked"] = True
            if evict_inside_lock:
                admission._WARM_QUALIFICATIONS.clear()
            try:
                yield
            finally:
                state["locked"] = False

    monkeypatch.setattr(module, "verify_registered_qualification", verify)
    monkeypatch.setattr(remote, "_book_mutation_lock", lock)
    kwargs = dict(
        candidate_id=candidate["candidate_id"], expected_source_digest=candidate["source_digest"]
    )
    if evict_inside_lock:
        with pytest.raises(remote.AssistantRemoteError, match="qualification_preflight_required"):
            remote.hang_candidate(settings, **kwargs)
        assert (
            remote.build_paper_account_repository(
                settings.data.data_dir / "api_runs", settings=settings
            ).load()
            is None
        )
    else:
        assert remote.hang_candidate(settings, **kwargs)["status"] == "hung"
    assert state["outside_calls"] > 0


def test_candidate_publication_preflights_before_book_lock(context, monkeypatch):
    settings, _, candidate = fixtures.fundable_consumer(context, monkeypatch)
    module = sys.modules["quant_system.research.admission_qualifier"]
    original_verify, original_lock = (
        module.verify_registered_qualification,
        remote._book_mutation_lock,
    )
    state = {"locked": False, "calls": 0}

    def verify(*args, **kwargs):
        assert not state["locked"], "qualification entered candidate book lock"
        state["calls"] += 1
        return original_verify(*args, **kwargs)

    @contextmanager
    def lock(settings, **kwargs):
        with original_lock(settings, **kwargs):
            state["locked"] = True
            try:
                yield
            finally:
                state["locked"] = False

    monkeypatch.setattr(module, "verify_registered_qualification", verify)
    monkeypatch.setattr(remote, "_book_mutation_lock", lock)
    repeated = remote.record_verified_candidate(
        settings,
        candidate_id=candidate["candidate_id"],
        objective="sealed repeated candidate",
        source="strategy_definition",
        source_path=candidate["source_path"],
        source_digest=candidate["source_digest"],
        factor_id=candidate["factor_id"],
        universe=candidate["universe"],
        comparison_digest=candidate["comparison_digest"],
        verification_receipt_digest=candidate["verification_receipt_digest"],
        daily_returns=candidate["performance"]["daily_returns"],
        return_dates=candidate["performance"]["return_dates"],
        admission_ref=candidate["admission_v2"],
    )
    assert repeated["candidate_id"] == candidate["candidate_id"] and state["calls"] > 0
