"""Real temporary journals/archive writers; only market/LLM boundaries are artificial."""

import json
import os
import subprocess
import sys

import pytest

from quant_system.config.settings import Settings
from quant_system.research import paper_evaluation as evaluation
from tests.test_paper_evaluation import TestOnlyModel, _files, _one_committed_fill, _price_patch


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    settings = Settings()
    settings.data.data_dir = tmp_path
    storage = _one_committed_fill(settings)
    _price_patch(monkeypatch)
    return settings, storage


def packets(settings):
    return list((settings.data.data_dir / "paper_evaluations/facts/packets").glob("*.json"))


def test_original_facts_and_sources_are_durable_before_model_is_called(prepared):
    from quant_system.research.paper_fact_archive import read_fact_archive

    settings, storage = prepared
    before = _files(storage.root_dir)

    class InspectingModel(TestOnlyModel):
        def _chat_json(self, messages):
            assert len(packets(settings)) == 1
            packet = json.loads(packets(settings)[0].read_text())
            assert packet["facts"] == json.loads(messages[1]["content"])
            assert any(r["role"] == "committed_journal" for r in packet["source_references"])
            assert any(r["role"] == "signal" for r in packet["source_references"])
            assert all(".env" not in r["path"] for r in packet["source_references"])
            return super()._chat_json(messages)

    result = evaluation.refresh_paper_evaluation(settings, client=InspectingModel())
    assert result["facts_status"] == "partial"
    assert result["interpretation_status"] == "available"
    packet = read_fact_archive(settings.data.data_dir / "paper_evaluations", result["fact_archive"])
    assert packet["facts"] == result["facts"]
    assert result["facts"]["prediction_decay"]["status"] == "unavailable"
    assert before == _files(storage.root_dir)


def test_frozen_config_original_is_retained_and_missing_config_is_explicit(prepared):
    import hashlib

    from quant_system.execution.paper_strategy_sleeves import StrategyConfig
    from quant_system.research.paper_fact_archive import read_fact_archive

    settings, storage = prepared
    before = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel())
    missing = read_fact_archive(
        settings.data.data_dir / "paper_evaluations", before["fact_archive"]
    )
    assert missing["source_completeness"] == "incomplete"
    assert any(
        r["role"] == "config" and r["status"] == "missing" for r in missing["source_references"]
    )
    config = StrategyConfig.create(
        strategy_config_id="strategy-test",
        name="Artificial config",
        strategy_id="cross_sectional_top_n",
        symbols=["SPY"],
    )
    path = storage.save_strategy_config(config)
    after = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel())
    packet = read_fact_archive(settings.data.data_dir / "paper_evaluations", after["fact_archive"])
    assert packet["source_completeness"] == "complete"
    assert any(
        r["role"] == "config" and r["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        for r in packet["source_references"]
    )


def test_model_failure_or_baseexception_never_removes_saved_facts(prepared):
    settings, _ = prepared
    first = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel(error=True))
    assert first["facts_status"] == "partial"
    assert first["interpretation_status"] == "failed"
    assert len(packets(settings)) == 1
    saved = packets(settings)[0].read_bytes()
    assert evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel()) == first
    assert packets(settings)[0].read_bytes() == saved


def test_process_exit_inside_external_model_preserves_original_packet(tmp_path):
    code = """
import os
from pathlib import Path
from quant_system.config.settings import Settings
from quant_system.research import paper_evaluation as e
from tests.test_paper_evaluation import _one_committed_fill, TestOnlyPriceProvider, TestOnlyModel
s=Settings();s.data.data_dir=Path(os.environ['PAPER_ARCHIVE_TEST_ROOT'])
_one_committed_fill(s)
e.build_ohlcv_provider=lambda *a,**k:(TestOnlyPriceProvider(),'futu')
class Exit(TestOnlyModel):
 def _chat_json(self,messages): os._exit(42)
e.refresh_paper_evaluation(s,client=Exit())
"""
    env = {**os.environ, "PAPER_ARCHIVE_TEST_ROOT": str(tmp_path)}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, check=False)
    assert result.returncode == 42, result.stderr.decode()
    settings = Settings()
    settings.data.data_dir = tmp_path
    assert len(packets(settings)) == 1
    packet = json.loads(packets(settings)[0].read_text())
    assert packet["facts"]["period"]["observation_count"] == 1
    assert packet["facts"]["metrics"]["commission_usd"] == 1


@pytest.mark.parametrize("target", ["packet", "blob"])
def test_corrupt_packet_or_preserved_source_blob_is_not_trusted_on_get(prepared, target):
    settings, _ = prepared
    result = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel())
    if target == "packet":
        path = packets(settings)[0]
    else:
        packet = json.loads(packets(settings)[0].read_text())
        reference = next(r for r in packet["source_references"] if r["role"] == "committed_journal")
        path = settings.data.data_dir / "paper_evaluations/facts/blobs" / reference["sha256"]
    path.write_bytes(path.read_bytes() + b"changed")
    assert evaluation.read_paper_evaluation(settings)["status"] == "failed"
    assert result["fact_archive"]


def test_new_live_source_bytes_do_not_invalidate_a_saved_historical_packet(prepared):
    settings, storage = prepared
    result = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel())
    source = storage.sleeve_signals_path("sleeve-test")
    source.write_bytes(source.read_bytes() + b"\n")
    assert evaluation.read_paper_evaluation(settings) == result


def test_source_change_creates_new_fact_packet_even_when_performance_unchanged(prepared):
    settings, storage = prepared
    first = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel())
    old_bytes = packets(settings)[0].read_bytes()
    path = storage.sleeve_signals_path("sleeve-test")
    path.write_bytes(path.read_bytes() + b"\n")
    second = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel())
    assert first["facts"] == second["facts"]
    assert first["fact_archive"]["fact_id"] != second["fact_archive"]["fact_id"]
    assert len(packets(settings)) == 2
    assert old_bytes in [p.read_bytes() for p in packets(settings)]


def test_archive_failure_stops_model_and_does_not_mutate_paper(prepared):
    settings, storage = prepared
    before = _files(storage.root_dir)
    directory = settings.data.data_dir / "paper_evaluations"
    directory.mkdir()
    (directory / "facts").write_text("artificial obstructing file")
    model = TestOnlyModel()
    result = evaluation.refresh_paper_evaluation(settings, client=model)
    assert result["status"] == "failed"
    assert result["facts_status"] == "unavailable"
    assert result["interpretation_status"] == "not_requested"
    assert model.calls == 0
    assert before == _files(storage.root_dir)


def test_paper_source_changed_during_price_read_does_not_create_verified_packet(
    prepared, monkeypatch
):
    from tests.test_paper_evaluation import TestOnlyPriceProvider

    settings, storage = prepared

    class ChangingPrices(TestOnlyPriceProvider):
        def fetch_ohlcv(self, *args, **kwargs):
            path = storage.sleeve_signals_path("sleeve-test")
            path.write_bytes(path.read_bytes() + b"\n")
            return super().fetch_ohlcv(*args, **kwargs)

    monkeypatch.setattr(
        evaluation, "build_ohlcv_provider", lambda *a, **k: (ChangingPrices(), "futu")
    )
    model = TestOnlyModel()
    result = evaluation.refresh_paper_evaluation(settings, client=model)
    assert result["facts_status"] == "unavailable" and model.calls == 0
    assert packets(settings) == []


def test_old_document_without_archive_remains_readable_and_is_not_migrated(prepared):
    settings, _ = prepared
    result = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel())
    for key in ("fact_archive", "facts_status", "interpretation_status"):
        result.pop(key)
    path = settings.data.data_dir / "paper_evaluations/latest.json"
    path.write_text(json.dumps(result))
    before = path.read_bytes()
    shown = evaluation.read_paper_evaluation(settings)
    assert shown["fact_archive_status"] == "legacy_not_separately_archived"
    assert shown["facts"] == result["facts"]
    assert before == path.read_bytes()


def test_replacement_journal_changes_facts_and_is_part_of_source_identity(prepared):
    from quant_system.research.paper_fact_archive import capture_paper_sources

    settings, _ = prepared
    old_source = capture_paper_sources(settings)
    old_facts = evaluation.build_paper_facts(settings)
    path = settings.data.data_dir / "api_runs/strategy_replacements/replacement-artificial.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    new_facts = evaluation.build_paper_facts(settings)
    new_source = capture_paper_sources(settings)
    assert old_facts != new_facts
    assert old_source["digest"] != new_source["digest"]
    assert any(row["path"] == str(path) for row in new_source["references"])


def test_replacement_old_and_new_definition_and_config_bytes_are_referenced(prepared):
    from quant_system.research.paper_fact_archive import capture_paper_sources

    settings, storage = prepared
    definitions = []
    for name in ("old", "new"):
        path = settings.data.data_dir / "strategy_library" / name / "definition.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"artificial_original_definition": name}))
        definitions.append(path)
    old_config, new_config = (
        {"strategy_config_id": "history-config", "version": v} for v in (1, 2)
    )
    for config in (old_config, new_config):
        path = storage.strategy_config_path(config["strategy_config_id"], config["version"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config))
    record = {
        "phase": "committed",
        "request": {"target_sleeve_id": "sleeve-test"},
        "old_config": old_config,
        "new_config": new_config,
        "old_candidate": {"source_path": str(definitions[0])},
        "new_candidate": {"source_path": str(definitions[1])},
    }
    path = settings.data.data_dir / "api_runs/strategy_replacements/replacement-artificial.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    source = capture_paper_sources(settings)
    expected = [
        *definitions,
        *(
            storage.strategy_config_path(c["strategy_config_id"], c["version"])
            for c in (old_config, new_config)
        ),
    ]
    assert all(
        any(row["path"] == str(p) and row["status"] == "available" for row in source["references"])
        for p in expected
    )
    definitions[0].write_text('{"artificial_original_definition":"changed"}')
    assert capture_paper_sources(settings)["digest"] != source["digest"]


def test_parallel_identical_fact_captures_share_first_packet_timestamp(prepared):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from quant_system.research.paper_fact_archive import (
        capture_paper_sources,
        persist_fact_archive,
        read_fact_archive,
    )

    settings, storage = prepared
    path = next(storage.execution_journal_dir("sleeve-test").glob("*.committed.json"))
    path.write_bytes(path.read_bytes() + b" " * (8 * 1024 * 1024))
    facts = evaluation.build_paper_facts(settings)
    sources = capture_paper_sources(settings)
    barrier = threading.Barrier(6)

    def persist(_):
        barrier.wait()
        return persist_fact_archive(settings.data.data_dir / "paper_evaluations", facts, sources)

    with ThreadPoolExecutor(max_workers=6) as pool:
        refs = list(pool.map(persist, range(6)))
    assert len({json.dumps(ref, sort_keys=True) for ref in refs}) == 1
    assert len(packets(settings)) == 1
    assert (
        read_fact_archive(settings.data.data_dir / "paper_evaluations", refs[0])["facts"] == facts
    )
