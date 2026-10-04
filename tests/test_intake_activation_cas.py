"""Sealed activation checks bind the actual candidate receipt before cash writes."""

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from quant_system.execution import assistant_remote as remote
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.research import strategy_library as library
from quant_system.research.validation_receipts import file_sha, verify_validation_receipt
from tests.test_definition_paper_bridge import _settings, definition, record_fundable_definition
from tests.test_validation_receipts import sealed_validation


def binding(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "quant_system.research.definition_paper.definition_schedule_available", lambda: True
    )
    settings = _settings(tmp_path, monkeypatch)
    recipe = definition()
    candidate = record_fundable_definition(tmp_path, settings, recipe)
    validations = Path(candidate["source_path"]).parent / "validations"
    path = next(
        path for path in validations.glob("*/validation.json")
        if file_sha(path) == candidate["verification_receipt_digest"]
    )
    value = json.loads(path.read_text())
    evaluation = {"evaluation_id": "evaluation-sealed", "start": "2020-01-01", "end": "2026-09-08"}
    value["evaluation"] = evaluation
    path.write_text(json.dumps(value))
    candidate["verification_receipt_digest"] = file_sha(path)
    book = remote.load_book(settings)
    book["candidates"][0].update(candidate)
    remote.save_book(settings, book)
    expected = {
        "validation_sha256": file_sha(path),
        "candidate_id": candidate["candidate_id"],
        "evaluation": evaluation,
    }
    entry = {
        **expected,
        "definition_digest": recipe.content_digest,
        "source_sha256": candidate["source_digest"],
    }
    (Path(candidate["source_path"]).parent / "entry.json").write_text(json.dumps(entry))
    return settings, candidate, expected


def test_activation_receipt_drift_rejected_before_account_repository(tmp_path, monkeypatch):
    settings, candidate, expected = binding(tmp_path, monkeypatch)
    entry = json.loads((Path(candidate["source_path"]).parent / "entry.json").read_text())
    entry["candidate_id"] = "another-legal-evaluation-candidate"
    (Path(candidate["source_path"]).parent / "entry.json").write_text(json.dumps(entry))
    monkeypatch.setattr(
        remote,
        "build_paper_account_repository",
        lambda *a, **k: pytest.fail("account boundary entered"),
    )
    with pytest.raises(remote.AssistantRemoteError, match="strategy_activation_receipt_changed"):
        remote.hang_candidate(
            settings,
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
            expected_receipt=expected,
        )


@pytest.mark.parametrize("field", ["validation_sha256", "candidate_id", "evaluation"])
def test_activation_receipt_rechecked_inside_cash_sleeve_book_locks(tmp_path, monkeypatch, field):
    settings, candidate, expected = binding(tmp_path, monkeypatch)
    original_lock = remote._book_mutation_lock
    entered = []

    @contextmanager
    def change_on_book_lock(current_settings, **kwargs):
        with original_lock(current_settings, **kwargs):
            entered.append("inside-book-lock")
            entry = json.loads((Path(candidate["source_path"]).parent / "entry.json").read_text())
            entry[field] = {"evaluation_id": "different"} if field == "evaluation" else "f" * 64
            (Path(candidate["source_path"]).parent / "entry.json").write_text(json.dumps(entry))
            yield

    monkeypatch.setattr(remote, "_book_mutation_lock", change_on_book_lock)
    with pytest.raises(remote.AssistantRemoteError, match="strategy_activation_receipt_changed"):
        remote.hang_candidate(
            settings,
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
            expected_receipt=expected,
        )
    assert entered == ["inside-book-lock"]
    assert PaperStrategySleeveStorage(tmp_path / "api_runs").list_sleeves() == []
    assert (
        remote.build_paper_account_repository(tmp_path / "api_runs", settings=settings).load()
        is None
    )
    assert remote.load_book(settings)["candidates"][0]["status"] == "verified"


def test_library_holds_validation_lock_and_forwards_expected_receipt(tmp_path, monkeypatch):
    settings, candidate, expected = binding(tmp_path, monkeypatch)
    strategy_id = "strategy-" + "a" * 24
    directory = library._directory(settings, strategy_id)
    directory.mkdir(parents=True)
    entry = {
        **expected,
        "source_sha256": candidate["source_digest"],
        "definition_digest": candidate["definition_digest"],
        "status": "validated",
    }
    monkeypatch.setattr(library, "read_strategy", lambda *_: entry)
    called = []

    def hang(_settings, **kwargs):
        called.append(kwargs)
        with (directory / "validation.lock").open("a+") as lock, pytest.raises(BlockingIOError):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    monkeypatch.setattr(remote, "hang_candidate", hang)
    library.enable_strategy(
        settings, strategy_id, candidate["definition_digest"], expected_receipt=expected
    )
    assert called[0]["expected_receipt"] == expected


def test_rejected_baseline_still_requires_full_bound_computation(tmp_path):
    path, _ = sealed_validation(tmp_path, "a" * 64, "b" * 64)
    value = json.loads(path.read_text())
    value.update(status="failed", blockers=["dsr_failed"])
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        verify_validation_receipt(path, expected_sha=file_sha(path), definition_digest="a" * 64)
    verified = verify_validation_receipt(
        path, expected_sha=file_sha(path), definition_digest="a" * 64, require_admission=False
    )
    assert verified["blockers"] == ["dsr_failed"]
    value["receipts"]["sources"]["definition_qlib_replay.py"] = "c" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="inputs_or_code_changed"):
        verify_validation_receipt(
            path, expected_sha=file_sha(path), definition_digest="a" * 64, require_admission=False
        )
