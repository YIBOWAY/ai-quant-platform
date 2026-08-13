from pathlib import Path

from quant_system.config.settings import reload_settings
from quant_system.execution.assistant_remote import (
    AssistantRemoteError,
    dispatch_research,
    hang_candidate,
    project_book,
    record_verified_candidate,
)
from quant_system.execution.paper_observation import hung_sleeve_eligible
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
import pytest


def _settings(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    return reload_settings()


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


def test_hang_requires_verified_candidate_then_creates_hung_sleeve(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    with pytest.raises(AssistantRemoteError) as missing:
        hang_candidate(settings, candidate_id="candidate-missing")
    assert missing.value.code == "candidate_not_found"

    record_verified_candidate(
        settings,
        candidate_id="candidate-ready-1",
        objective="preview verified candidate",
        source="preview_seed",
    )
    hung = hang_candidate(settings, candidate_id="candidate-ready-1")
    again = hang_candidate(settings, candidate_id="candidate-ready-1")

    assert hung["status"] == "hung"
    assert hung["already_hung"] is False
    assert again["already_hung"] is True
    assert again["sleeve_id"] == hung["sleeve_id"]
    sleeve = PaperStrategySleeveStorage(tmp_path / "api_runs").load_sleeve(hung["sleeve_id"])
    assert hung_sleeve_eligible(sleeve) is True
    book = project_book(settings)
    assert book["verified_count"] == 0
    assert book["hung_count"] == 1
