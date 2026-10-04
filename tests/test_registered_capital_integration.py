"""Artificial registered originals exercise the shared real family and money path."""

import math
from datetime import UTC, datetime

import exchange_calendars as xcals
import pandas as pd

from quant_system.execution import assistant_remote as remote
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.research.capital_evidence import current_candidate_quality
from quant_system.research.trials import TrialsLedger
from tests.test_assistant_remote import _settings, _tree_hash
from tests.test_registered_factor_verification import AgentCandidateFactor, _Boundary, _verify


def test_complete_registered_family_uses_real_minimum_and_funds_once(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    candidate = _verify(settings, _Boundary(tmp_path / "_runtime/d34"))
    ends = xcals.get_calendar("XNYS").sessions_in_range("2026-08-01", "2026-08-21")[-12:-1]
    for index, end in enumerate(ends, 1):
        # Independent explicitly artificial historical input windows. Failed
        # quality still supplies a real measured member, not a hand-set gate.
        returns = [0.00001 * index + 0.005 * math.sin(i + index) for i in range(240 + index)]

        class WindowBoundary(_Boundary):
            def __init__(self, *args, end_day, **kwargs):
                super().__init__(*args, **kwargs)
                self.end_day = end_day

            def fetch_ohlcv(self, symbols, **kwargs):
                frame = super().fetch_ohlcv(symbols, **kwargs)
                old = sorted(frame.timestamp.unique())
                days = xcals.get_calendar("XNYS").sessions_in_range("2024-01-01", self.end_day)[
                    -len(old) :
                ]
                mapping = dict(zip(old, pd.to_datetime(days, utc=True), strict=True))
                for key in ("timestamp", "event_ts", "available_ts"):
                    if key in frame:
                        frame[key] = frame[key].map(mapping)
                return frame

        boundary = WindowBoundary(tmp_path / "_runtime/d34", returns=returns, end_day=end)
        try:
            remote.verify_registered_factor(
                settings,
                factor_id=AgentCandidateFactor.factor_id,
                universe=["SPY", "QQQ"],
                boundary=boundary,
                now=lambda end=end: datetime(end.year, end.month, end.day, 23, tzinfo=UTC),
            )
        except remote.AssistantRemoteError as exc:
            assert exc.code in {"dsr_failed", "cost_sensitivity_failed"}
    assert len(TrialsLedger(tmp_path / "trials").list()) == 12
    book = remote.load_book(settings)
    report = current_candidate_quality(settings, candidate, book["candidates"])
    assert report["n_family_members"] == 12, report
    assert report["eligible"] is True, report
    result = remote.hang_candidate(
        settings,
        candidate_id=candidate["candidate_id"],
        expected_source_digest=candidate["source_digest"],
    )
    assert result["status"] == "hung"
    account = PaperAccountStorage(tmp_path / "api_runs").load()
    assert account.sleeve_cash[result["sleeve_id"]] == 10000
    before = _tree_hash(tmp_path)
    again = remote.hang_candidate(
        settings,
        candidate_id=candidate["candidate_id"],
        expected_source_digest=candidate["source_digest"],
    )
    assert again["already_hung"] is True
    assert _tree_hash(tmp_path) == before


def test_unrecorded_same_family_blocks_but_proven_other_universe_does_not(tmp_path, monkeypatch):
    import json

    from quant_system.research.capital_evidence import registered_population_integrity
    from quant_system.research.registered_family_evidence import read_registered_trial

    settings = _settings(tmp_path, monkeypatch)
    candidate = _verify(settings, _Boundary(tmp_path / "_runtime/d34"))
    rows = TrialsLedger(tmp_path / "trials").list()
    job = tmp_path / "_runtime/d34/jobs" / candidate["evidence_ref"]["job_id"]
    contract = read_registered_trial(tmp_path, job, rows)["contract"]
    # The original job is real within this artificial fixture; omission from a
    # proposed ledger view is a gap, not a synthetic replacement ledger write.
    before = _tree_hash(tmp_path)
    related = registered_population_integrity(tmp_path, [], ["SPY", "QQQ"], contract, [])
    unrelated = registered_population_integrity(tmp_path, [], ["AAPL", "MSFT"], contract, [])
    assert related["complete"] is False and len(related["gaps"]) == 1
    assert unrelated["complete"] is True and len(unrelated["out_of_scope"]) == 1
    assert _tree_hash(tmp_path) == before
    manifest = job / "manifest.json"
    raw = json.loads(manifest.read_text())
    raw["universe"] = ["AAPL", "MSFT"]  # Do not reseal; this is no trusted universe proof.
    manifest.write_text(json.dumps(raw))
    changed = registered_population_integrity(tmp_path, [], ["SPY", "QQQ"], contract, [])
    assert changed["complete"] is False and changed["gaps"][0]["status"] == "unknown"


def test_registered_reference_with_lost_job_is_unknown_without_any_write(tmp_path, monkeypatch):
    from quant_system.research.capital_evidence import registered_population_integrity
    from quant_system.research.registered_family_evidence import read_registered_trial

    settings = _settings(tmp_path, monkeypatch)
    candidate = _verify(settings, _Boundary(tmp_path / "_runtime/d34"))
    rows = TrialsLedger(tmp_path / "trials").list()
    job = tmp_path / "_runtime/d34/jobs" / candidate["evidence_ref"]["job_id"]
    contract = read_registered_trial(tmp_path, job, rows)["contract"]
    job.rename(job.with_name("ARTIFICIAL-missing-job-backup"))
    before = _tree_hash(tmp_path)
    census = registered_population_integrity(
        tmp_path, rows, candidate["universe"], contract, [candidate]
    )
    assert census["complete"] is False
    assert census["gaps"][0]["reason"] == "registered_candidate_job_missing"
    assert _tree_hash(tmp_path) == before
