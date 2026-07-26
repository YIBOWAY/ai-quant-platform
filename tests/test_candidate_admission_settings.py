from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from quant_system.config.settings import CandidateAdmissionSettings, Settings


def test_candidate_admission_defaults_off() -> None:
    candidate = CandidateAdmissionSettings()

    assert candidate.enabled is False
    assert candidate.ttl_seconds == 900
    assert candidate.ttl_seconds <= 7200
    assert isinstance(candidate.preflight_evidence_file, Path)
    assert isinstance(candidate.final_evidence_file, Path)
    assert Settings().candidate_admission.enabled is False


def test_candidate_admission_ttl_accepts_operator_flow_window() -> None:
    assert CandidateAdmissionSettings(ttl_seconds=7200).ttl_seconds == 7200


def test_candidate_admission_ttl_cannot_exceed_7200_seconds() -> None:
    try:
        CandidateAdmissionSettings(ttl_seconds=7201)
    except ValidationError as exc:
        assert "ttl_seconds" in str(exc)
    else:
        raise AssertionError("candidate admission TTL must be capped at 7200 seconds")
