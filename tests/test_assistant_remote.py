import hashlib
import json
from pathlib import Path

from quant_system.config.settings import reload_settings
from quant_system.execution.assistant_remote import (
    AssistantRemoteError,
    admit_accepted_artifacts,
    dispatch_research,
    hang_candidate,
    intake_material,
    project_book,
    quarantine_fossil_sleeves,
    reconcile_dispatched_requests,
    reconcile_remote_book,
    record_verified_candidate,
    record_verified_from_dual_engine_artifact,
)
from quant_system.execution.paper_observation import hung_sleeve_eligible
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
import pytest

_FIXTURE_FACTOR = b'''from __future__ import annotations
import pandas as pd
from quant_system.factors.base import BaseFactor

class GeneratedFactor(BaseFactor):
    factor_id = "d34_oracle"
    factor_name = "D34 Oracle"
    default_lookback = 2
    direction = "higher_is_better"
    description = "Isolation digest-bound fixture."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        return frame.groupby("symbol", sort=False)["close"].pct_change(
            self.lookback, fill_method=None
        )

D34_FACTOR = GeneratedFactor
'''


def _settings(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    return reload_settings()


def _write_fixture_factor(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "fixture_d34_oracle.py"
    path.write_bytes(_FIXTURE_FACTOR)
    return path, hashlib.sha256(_FIXTURE_FACTOR).hexdigest()


def test_dispatch_research_does_not_hang_or_invent_a_candidate(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)

    receipt = dispatch_research(
        settings,
        objective="Find a twenty-day reversal",
    )

    assert receipt["status"] == "requested"
    assert receipt["hung"] is False
    assert receipt["candidate_id"] is None
    book = project_book(settings)
    assert book["verified_count"] == 0
    assert book["hung_count"] == 0
    assert book["requests"][0]["hang_if_pass"] is False


def test_dispatch_with_enqueue_creates_one_real_job_and_caps_concurrency(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    enqueued: list[tuple[str, bool]] = []

    def fake_enqueue(objective: str, hang_if_pass: bool) -> str:
        enqueued.append((objective, hang_if_pass))
        return "request:2026-08-14:abcdef123456"

    receipt = dispatch_research(
        settings,
        objective="扩宇宙：在 20 只高流动性美股上重验横截面动量",
        enqueue_job=fake_enqueue,
    )

    assert receipt["status"] == "queued"
    assert receipt["mode"] == "d34_job"
    assert receipt["job_key"] == "request:2026-08-14:abcdef123456"
    assert receipt["hung"] is False
    assert enqueued == [("扩宇宙：在 20 只高流动性美股上重验横截面动量", False)]
    book = project_book(settings)
    assert book["requests"][0]["job_key"] == "request:2026-08-14:abcdef123456"
    assert book["requests"][0]["status"] == "queued"

    # The plan allows at most one in-flight dispatched research job.
    with pytest.raises(AssistantRemoteError) as blocked:
        dispatch_research(
            settings,
            objective="second concurrent objective",
            enqueue_job=fake_enqueue,
        )
    assert blocked.value.code == "research_job_already_active"
    assert len(enqueued) == 1

    # Book-only dispatch (no job lane wired) stays available and honest.
    fallback = dispatch_research(settings, objective="book-only opinion request")
    assert fallback["status"] == "requested"
    assert fallback["mode"] == "book_only"
    assert fallback["job_key"] is None


def test_reconcile_projects_job_lane_states_without_inventing(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    job_key = "request:2026-08-14:feedbeef0001"
    dispatch_research(
        settings,
        objective="扩宇宙：横截面动量重验",
        enqueue_job=lambda _objective, _hang: job_key,
    )

    class _Jobs:
        def __init__(self, state: str) -> None:
            self.state = state

        def list(self, *, workspace_id: str, limit: int, state):
            assert workspace_id == "default"
            if not 1 <= limit <= 100:
                raise AssertionError(f"job list limit {limit} exceeds JobAuthority max 100")
            return [{"job_key": job_key, "state": self.state}]

    changed = reconcile_dispatched_requests(settings, jobs=_Jobs("running"))
    assert changed == 1
    assert project_book(settings)["requests"][0]["status"] == "running"

    changed = reconcile_dispatched_requests(settings, jobs=_Jobs("succeeded"))
    assert changed == 1
    assert project_book(settings)["requests"][0]["status"] == "succeeded"

    # Terminal rows freeze: reconcile never resurrects or reinvents progress.
    changed = reconcile_dispatched_requests(settings, jobs=_Jobs("running"))
    assert changed == 0
    assert project_book(settings)["requests"][0]["status"] == "succeeded"


def test_record_verified_candidate_requires_source_digest_and_universe(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)

    with pytest.raises(AssistantRemoteError) as missing:
        record_verified_candidate(
            settings,
            candidate_id="candidate-no-digest",
            objective="preview verified candidate",
            source="preview_seed",
        )
    assert missing.value.code == "candidate_digest_required"

    with pytest.raises(AssistantRemoteError) as no_universe:
        record_verified_candidate(
            settings,
            candidate_id="candidate-no-universe",
            objective="preview verified candidate",
            source="preview_seed",
            source_digest=digest,
            source_path=str(path),
            factor_id="d34_oracle",
        )
    assert no_universe.value.code == "candidate_universe_required"


def test_hang_rejects_source_bytes_that_no_longer_match_digest(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    record_verified_candidate(
        settings,
        candidate_id="candidate-tampered",
        objective="digest must be rechecked at hang",
        source="preview_seed",
        source_digest=digest,
        source_path=str(path),
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
    )
    path.write_bytes(_FIXTURE_FACTOR + b"# changed\n")

    with pytest.raises(AssistantRemoteError) as mismatch:
        hang_candidate(settings, candidate_id="candidate-tampered")
    assert mismatch.value.code == "candidate_source_digest_mismatch"
    assert project_book(settings)["hung_count"] == 0


def test_hang_rejects_already_hung_demo_sleeve_without_digest(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    book_path = tmp_path / "assistant_remote" / "book.json"
    book_path.parent.mkdir(parents=True)
    book_path.write_text(
        '{"contract":"hqa.assistant_remote_book/v1","candidates":[{"candidate_id":'
        '"candidate-preview-unhung","objective":"old demo","status":"hung",'
        '"source":"preview_seed","artifact_id":null,'
        '"sleeve_id":"sleeve-1273d32417c8"}],"requests":[]}',
        encoding="utf-8",
    )

    with pytest.raises(AssistantRemoteError) as missing:
        hang_candidate(settings, candidate_id="candidate-preview-unhung")
    assert missing.value.code == "candidate_digest_required"
    assert project_book(settings)["hung_count"] == 0


def test_record_verified_candidate_does_not_launder_existing_digestless_row(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    book_path = tmp_path / "assistant_remote" / "book.json"
    book_path.parent.mkdir(parents=True)
    book_path.write_text(
        '{"contract":"hqa.assistant_remote_book/v1","candidates":[{"candidate_id":'
        '"candidate-preview-unhung","objective":"old demo","status":"hung",'
        '"source":"preview_seed","artifact_id":null,'
        '"sleeve_id":"sleeve-1273d32417c8"}],"requests":[]}',
        encoding="utf-8",
    )
    path, digest = _write_fixture_factor(tmp_path)

    with pytest.raises(AssistantRemoteError) as conflict:
        record_verified_candidate(
            settings,
            candidate_id="candidate-preview-unhung",
            objective="cannot overwrite a digest-less hung demo",
            source="preview_seed",
            source_digest=digest,
            source_path=str(path),
            factor_id="d34_oracle",
            universe=["SPY", "QQQ"],
        )
    assert conflict.value.code == "candidate_lineage_conflict"


def test_hang_rejects_verified_candidate_without_bound_digest(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    book_path = tmp_path / "assistant_remote" / "book.json"
    book_path.parent.mkdir(parents=True)
    book_path.write_text(
        '{"contract":"hqa.assistant_remote_book/v1","candidates":[{"candidate_id":'
        '"candidate-legacy","objective":"old demo","status":"verified",'
        '"source":"preview_seed","artifact_id":null,"sleeve_id":null}],"requests":[]}',
        encoding="utf-8",
    )

    with pytest.raises(AssistantRemoteError) as missing:
        hang_candidate(settings, candidate_id="candidate-legacy")
    assert missing.value.code == "candidate_digest_required"
    assert project_book(settings)["hung_count"] == 0
    assert not (tmp_path / "api_runs").exists()


def test_hang_binds_source_digest_and_does_not_mint_generic_momentum(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    with pytest.raises(AssistantRemoteError) as missing:
        hang_candidate(settings, candidate_id="candidate-missing")
    assert missing.value.code == "candidate_not_found"

    path, digest = _write_fixture_factor(tmp_path)
    record_verified_candidate(
        settings,
        candidate_id="candidate-ready-1",
        objective="preview verified candidate",
        source="preview_seed",
        source_digest=digest,
        source_path=str(path),
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="a" * 64,
    )
    hung = hang_candidate(settings, candidate_id="candidate-ready-1")
    again = hang_candidate(settings, candidate_id="candidate-ready-1")

    assert hung["status"] == "hung"
    assert hung["already_hung"] is False
    assert hung["source_digest"] == digest
    assert hung["factor_id"] == "d34_oracle"
    assert hung["universe"] == ["SPY", "QQQ"]
    assert again["already_hung"] is True
    assert again["sleeve_id"] == hung["sleeve_id"]
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = storage.load_sleeve(hung["sleeve_id"])
    config = storage.load_strategy_config(sleeve.strategy_config_id)
    assert hung_sleeve_eligible(sleeve) is True
    assert sleeve.metadata.get("candidate_code_digest") == digest
    assert sleeve.metadata.get("source_digest") == digest
    assert sleeve.metadata.get("comparison_digest") == "a" * 64
    assert sleeve.metadata.get("candidate_id") == "candidate-ready-1"
    assert config.symbols == ["SPY", "QQQ"]
    assert config.factor_ids == ["d34_oracle"]
    assert config.factor_ids != ["momentum"]
    assert config.symbols != ["AAPL", "MSFT"]
    book = project_book(settings)
    assert book["verified_count"] == 0
    assert book["hung_count"] == 1
    assert book["candidates"][0]["source_digest"] == digest
    assert book["candidates"][0]["sleeve_id"] == hung["sleeve_id"]


def test_dual_engine_artifact_backfill_is_verified_and_not_hung(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)

    record = record_verified_from_dual_engine_artifact(
        settings,
        artifact_id="artifact-test-1",
        source_path=path,
        source_digest=digest,
        comparison_digest="c" * 64,
        universe=["SPY", "QQQ"],
        objective="dual-engine accepted fixture",
        job_key="request:2026-08-15:fixture",
    )

    assert record["status"] == "verified"
    assert record["sleeve_id"] is None
    assert record["source_digest"] == digest
    assert record["factor_id"] == "d34_oracle"
    assert record["artifact_id"] == "artifact-test-1"
    assert record["job_key"] == "request:2026-08-15:fixture"
    book = project_book(settings)
    assert book["verified_count"] == 1
    assert book["hung_count"] == 0


def test_intake_fails_closed_without_formula_or_universe(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)

    with pytest.raises(AssistantRemoteError) as no_formula:
        intake_material(
            settings,
            note="Reproduce the twenty-day reversal writeup",
            universe=["SPY", "QQQ"],
        )
    assert no_formula.value.code == "intake_formula_required"

    with pytest.raises(AssistantRemoteError) as no_universe:
        intake_material(
            settings,
            note="Reproduce the twenty-day reversal writeup",
            formula="rank by 20-day return, hold top 1",
        )
    assert no_universe.value.code == "candidate_universe_required"
    assert project_book(settings)["requests"] == []


def test_intake_with_formula_and_universe_asks_and_does_not_hang(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)

    receipt = intake_material(
        settings,
        note="Reproduce the twenty-day reversal writeup",
        formula="rank by 20-day return, hold top 1",
        universe=["SPY", "QQQ", "IWM"],
        hang_if_pass=True,
    )

    assert receipt["contract"] == "hqa.assistant_remote_intake/v1"
    assert receipt["hung"] is False
    assert receipt["candidate_id"] is None
    assert receipt["hang_if_pass"] is False
    assert receipt["universe"] == ["SPY", "QQQ", "IWM"]
    assert "formula: rank by 20-day return, hold top 1" in project_book(settings)["requests"][0]["objective"]
    assert project_book(settings)["hung_count"] == 0


def test_get_book_auto_admits_accepted_cycle_receipt(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    job_root = tmp_path / "d34" / "jobs" / "job-accepted-fixture"
    research_dir = job_root / "research" / "research-fixture"
    research_dir.mkdir(parents=True)
    factor_dest = research_dir / "candidate_factor.py"
    factor_dest.write_bytes(path.read_bytes())
    rel = "jobs/job-accepted-fixture/research/research-fixture/candidate_factor.py"
    (job_root / "cycle_receipt.json").write_text(
        json.dumps(
            {
                "contract": "hqa.d34_job_outcome/v1",
                "phase": "candidate_ready",
                "comparison_accepted": True,
                "artifact_id": "artifact-accepted-fixture",
                "candidate_code_digest": digest,
                "comparison_digest": "d" * 64,
                "factor_path": rel,
                "job_id": "job-accepted-fixture",
            }
        ),
        encoding="utf-8",
    )
    (job_root / "research_request.json").write_text(
        json.dumps(
            {
                "objective": "dual-engine accepted fixture for book GET",
                "universe": ["SPY", "QQQ"],
            }
        ),
        encoding="utf-8",
    )

    book = reconcile_remote_book(settings)

    assert book["verified_count"] == 1
    assert book["hung_count"] == 0
    candidate = book["candidates"][0]
    assert candidate["status"] == "verified"
    assert candidate["sleeve_id"] is None
    assert candidate["source_digest"] == digest
    assert candidate["artifact_id"] == "artifact-accepted-fixture"
    assert admit_accepted_artifacts(settings)[0]["candidate_id"] == candidate["candidate_id"]


def test_get_book_does_not_admit_rejected_cycle_receipt(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    job_root = tmp_path / "d34" / "jobs" / "job-rejected-fixture"
    research_dir = job_root / "research" / "research-fixture"
    research_dir.mkdir(parents=True)
    (research_dir / "candidate_factor.py").write_bytes(path.read_bytes())
    (job_root / "cycle_receipt.json").write_text(
        json.dumps(
            {
                "contract": "hqa.d34_job_outcome/v1",
                "phase": "rejected",
                "comparison_accepted": False,
                "artifact_id": "artifact-rejected-fixture",
                "candidate_code_digest": digest,
                "comparison_digest": "e" * 64,
                "factor_path": "jobs/job-rejected-fixture/research/research-fixture/candidate_factor.py",
                "job_id": "job-rejected-fixture",
            }
        ),
        encoding="utf-8",
    )
    (job_root / "research_request.json").write_text(
        json.dumps({"objective": "rejected should not admit", "universe": ["SPY"]}),
        encoding="utf-8",
    )

    book = reconcile_remote_book(settings)
    assert book["verified_count"] == 0
    assert book["candidates"] == []


def test_quarantine_labels_digestless_preview_seed(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    book_path = tmp_path / "assistant_remote" / "book.json"
    book_path.parent.mkdir(parents=True)
    book_path.write_text(
        '{"contract":"hqa.assistant_remote_book/v1","candidates":[{"candidate_id":'
        '"candidate-preview-unhung","objective":"old demo","status":"hung",'
        '"source":"preview_seed","artifact_id":null,'
        '"sleeve_id":"sleeve-1273d32417c8"}],"requests":[]}',
        encoding="utf-8",
    )

    labeled = quarantine_fossil_sleeves(settings)
    book = project_book(settings)
    assert labeled["labeled_candidates"] == 1
    assert book["hung_count"] == 0
    assert book["fossil_count"] == 1
    assert book["candidates"][0]["fossil"] is True
    assert book["candidates"][0]["official_observation"] is False
