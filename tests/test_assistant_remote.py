import hashlib
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
