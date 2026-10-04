"""Real file-account transactions on explicitly artificial original receipts."""
import pytest

from quant_system.execution import assistant_remote as remote
from quant_system.execution.account_storage import PaperAccountStorage
from tests.test_assistant_remote import _settings, _tree_hash
from tests.test_capital_evidence import definition_archive


def candidate_with_originals(tmp_path, monkeypatch, n):
    settings = _settings(tmp_path, monkeypatch)
    _, candidates, _ = definition_archive(tmp_path, n=n)
    original = candidates[0]
    candidate = remote.record_verified_candidate(
        settings, candidate_id=original["candidate_id"], objective="artificial quality consumer",
        source="strategy_definition", source_path=original["source_path"],
        source_digest=original["source_digest"],
        factor_id="definition_" + original["definition_digest"][:24],
        universe=original["universe"], comparison_digest=original["comparison_digest"],
        verification_receipt_digest=original["verification_receipt_digest"],
        daily_returns=original["performance"]["daily_returns"],
        return_dates=original["performance"]["return_dates"], turnover_period=1.0,
    )
    return settings, candidate


def test_one_member_psr_cannot_allocate_new_money(tmp_path, monkeypatch):
    settings, candidate = candidate_with_originals(tmp_path, monkeypatch, 1)
    assert candidate["dsr"]["passed"] is True  # Legal historical PSR mathematics.
    before = _tree_hash(tmp_path)
    with pytest.raises(remote.AssistantRemoteError, match="new_capital_quality_failed"):
        remote.hang_candidate(settings, candidate_id=candidate["candidate_id"],
                              expected_source_digest=candidate["source_digest"])
    assert _tree_hash(tmp_path) == before


def test_full_original_family_funds_once_and_recovery_keeps_old_allocation(tmp_path, monkeypatch):
    settings, candidate = candidate_with_originals(tmp_path, monkeypatch, 12)
    result = remote.hang_candidate(settings, candidate_id=candidate["candidate_id"],
                                   expected_source_digest=candidate["source_digest"])
    assert result["status"] == "hung"
    account = PaperAccountStorage(tmp_path / "api_runs").load()
    assert account.sleeve_cash[result["sleeve_id"]] == 10000
    first = _tree_hash(tmp_path)
    repeated = remote.hang_candidate(settings, candidate_id=candidate["candidate_id"],
                                     expected_source_digest=candidate["source_digest"])
    assert repeated["already_hung"] is True
    assert _tree_hash(tmp_path) == first


@pytest.mark.parametrize("fault", ["missing_receipt", "tampered_result", "new_family_gap"])
def test_changed_current_evidence_rejects_without_new_money(tmp_path, monkeypatch, fault):
    import json
    from pathlib import Path

    from quant_system.research.trials import ResearchTrial, TrialsLedger

    settings, candidate = candidate_with_originals(tmp_path, monkeypatch, 12)
    run = next((Path(candidate["source_path"]).parent / "validations").iterdir())
    if fault == "missing_receipt":
        (run / "validation.json").unlink()
    elif fault == "tampered_result":
        target = run / "platform-result.json"
        payload = json.loads(target.read_text())
        payload["curve"][3]["equity"] += 50
        target.write_text(json.dumps(payload))
    else:
        TrialsLedger(tmp_path / "trials").append(ResearchTrial.record(
            kind="platform_backtest", subject="new relevant artificial trial without receipt",
            universe=candidate["universe"], daily_returns=[.001, -.002] * 126,
            source="explicit_artificial", window_start="2024-01-01", window_end="2024-12-31",
        ))
    before = _tree_hash(tmp_path)
    with pytest.raises(remote.AssistantRemoteError):
        remote.hang_candidate(settings, candidate_id=candidate["candidate_id"],
                              expected_source_digest=candidate["source_digest"])
    assert PaperAccountStorage(tmp_path / "api_runs").load() is None
    assert _tree_hash(tmp_path) == before


def test_already_funded_recovery_does_not_need_a_new_family_qualification(tmp_path, monkeypatch):
    settings, candidate = candidate_with_originals(tmp_path, monkeypatch, 12)
    first = remote.hang_candidate(settings, candidate_id=candidate["candidate_id"],
                                  expected_source_digest=candidate["source_digest"])
    # Simulate unavailable current family evidence, not a rewrite of its history.
    ledger = tmp_path / "trials" / "trials.jsonl"
    ledger.rename(ledger.with_suffix(".unavailable"))
    before = _tree_hash(tmp_path)
    recovered = remote.hang_candidate(settings, candidate_id=candidate["candidate_id"],
                                      expected_source_digest=candidate["source_digest"])
    assert recovered["already_hung"] is True
    assert recovered["sleeve_id"] == first["sleeve_id"]
    assert _tree_hash(tmp_path) == before


def test_evidence_changes_between_preflight_and_locked_consumer_reject(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from quant_system.research.trials import ResearchTrial, TrialsLedger

    settings, candidate = candidate_with_originals(tmp_path, monkeypatch, 12)
    original_lock = remote._book_mutation_lock
    expected = None

    @contextmanager
    def concurrent_trial(settings):
        nonlocal expected
        # Only the concurrency boundary is instrumented. The adapter, gates,
        # account and lock bodies all execute their real implementation.
        with original_lock(settings):
            TrialsLedger(tmp_path / "trials").append(ResearchTrial.record(
                kind="platform_backtest", subject="concurrent artificial missing evidence",
                universe=candidate["universe"], daily_returns=[.001, -.002] * 126,
                source="explicit_artificial", window_start="2024-01-01", window_end="2024-12-31",
            ))
            expected = _tree_hash(tmp_path)
            yield

    monkeypatch.setattr(remote, "_book_mutation_lock", concurrent_trial)
    with pytest.raises(remote.AssistantRemoteError, match="new_capital_quality_failed"):
        remote.hang_candidate(settings, candidate_id=candidate["candidate_id"],
                              expected_source_digest=candidate["source_digest"])
    assert PaperAccountStorage(tmp_path / "api_runs").load() is None
    assert expected is not None and _tree_hash(tmp_path) == expected
