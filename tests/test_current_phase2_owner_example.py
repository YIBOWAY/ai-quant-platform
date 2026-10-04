"""Sealed orchestration tests; no provider, engine, qualification or funds run here."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/current_phase2_owner_example.py"
spec = importlib.util.spec_from_file_location("current_owner_example", SCRIPT)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def proposal():
    return example.make_proposal(
        {
            "proposal": {
                "expression": example.EXPRESSION,
                "proposal_id": "original-four-stock-engineering",
                "source_urls": ["https://example.com/retained-source-description"],
            }
        },
        retrieved_at="2026-09-20T10:00:00+00:00",
    )


def test_new_variant_is_explicit_24_stock_monthly_not_old_identity():
    value = proposal()
    assert value["proposal_id"] != "original-four-stock-engineering"
    assert value["expression"] == example.EXPRESSION
    assert value["strategy_spec"]["symbols"] == example.CONTROL_SYMBOLS
    assert value["strategy_spec"]["rebalance"] == "monthly"
    assert value["strategy_spec"]["top_n"] == 5
    assert "new engineering variant" in value["adaptation_note"]
    assert value["published_at"] is None


def test_native_submit_uses_frozen_snapshot_without_fetch_and_without_funding(
    tmp_path, monkeypatch
):
    from quant_system.research import admission_v2
    from quant_system.research import external_intake as intake
    from quant_system.research import strategy_library as library

    monkeypatch.setattr(intake, "_now", lambda: datetime(2026, 9, 20, 10, tzinfo=UTC))

    def forbidden(*args, **kwargs):
        raise AssertionError("provider must not run")

    monkeypatch.setattr(library, "_collect_prices", forbidden)
    settings = example.isolated_settings(tmp_path / "attempt")
    frozen = tmp_path / "frozen.parquet"
    frozen.write_bytes(b"sealed snapshot bytes, not a real price or engine claim")
    manifest = {"requested_start": "2018-01-01", "requested_end": "2026-09-19"}
    job, evaluation = example.prepare_native_job(
        settings,
        proposal(),
        frozen,
        manifest,
        {"test_only": True},
        expected_code=admission_v2.code_identity()["digest"],
    )
    assert job["admission_protocol"]["mode"] == "parallel"
    assert job["policy_snapshot"]["auto_enable"] is False
    loaded = intake._load_job(settings, job["job_id"])
    assert intake._prepare_evaluation(settings, loaded) == evaluation
    assert Path(evaluation["prices_path"]).read_bytes() == frozen.read_bytes()
    assert not (settings.data.data_dir / "api_runs").exists()
    assert not (settings.data.data_dir / "trials").exists()
    assert not settings.database.enabled
    assert not settings.safety.live_trading_enabled


def test_source_drift_refuses_before_creating_native_queue(tmp_path):
    settings = example.isolated_settings(tmp_path / "attempt")
    with pytest.raises(ValueError, match="owner_example_code_changed"):
        example.prepare_native_job(
            settings, proposal(), tmp_path / "missing.parquet", {}, {}, expected_code="0" * 64
        )
    assert not (settings.data.data_dir / "research_intake").exists()


def test_post_stage_submission_refuses_changed_policy_without_rewriting_it(tmp_path):
    from quant_system.research import admission_v2
    from quant_system.research import external_intake as intake

    settings = example.isolated_settings(tmp_path / "attempt")
    policy_path = settings.data.data_dir / "research_intake/policy.json"
    example.write_json(
        policy_path, intake.IntakePolicy(enabled=True, auto_enable=True).model_dump()
    )
    before = policy_path.read_bytes()
    with pytest.raises(ValueError, match="owner_example_policy_must_remain_research_only"):
        example.prepare_native_job(
            settings,
            proposal(),
            tmp_path / "missing.parquet",
            {},
            {},
            expected_code=admission_v2.code_identity()["digest"],
            initialize=False,
        )
    assert policy_path.read_bytes() == before
    assert not (settings.data.data_dir / "research_intake/jobs").exists()


@pytest.mark.parametrize("status", ["blocked", "ready"])
def test_stage_without_actual_activation_never_submits_the_second_job(
    tmp_path, monkeypatch, status
):
    import sys
    import types

    # Sealed fixed-check double only. No passed JSON is trusted in production.
    module = types.ModuleType("quant_system.research.admission_activation")
    module.review_and_activate = lambda *a, **k: {"status": status, "reasons": ["sealed_only"]}
    monkeypatch.setitem(sys.modules, module.__name__, module)
    settings = example.isolated_settings(tmp_path / "attempt")
    value = example.review_stage_and_prepare_new(
        settings,
        historical_inventory=tmp_path / "unused",
        proposal=proposal(),
        prices_path=tmp_path / "unused",
        manifest={},
        provenance={},
        expected_code="unused",
    )
    assert value == {"stage": {"status": status, "reasons": ["sealed_only"]}}
    assert not settings.data.data_dir.exists()


def test_native_weekend_window_is_preserved_without_rewriting_protocol(tmp_path, monkeypatch):
    from quant_system.research import admission_v2
    from quant_system.research import external_intake as intake

    monkeypatch.setattr(intake, "_now", lambda: datetime(2026, 9, 21, 10, tzinfo=UTC))
    settings = example.isolated_settings(tmp_path / "attempt")
    frozen = tmp_path / "frozen.parquet"
    frozen.write_bytes(b"sealed snapshot, no real price or engine claim")
    job, evaluation = example.prepare_native_job(
        settings,
        proposal(),
        frozen,
        {"requested_start": "2018-01-01", "requested_end": "2026-09-19"},
        {},
        expected_code=admission_v2.code_identity()["digest"],
    )
    saved = intake._load_job(settings, job["job_id"])
    assert job == saved
    assert saved["plans"][0]["origin"]["end"] == "2026-09-20"
    assert evaluation["end"] == "2026-09-20"
    assert saved["admission_protocol"]["mode"] == "parallel"
    assert Path(evaluation["prices_path"]).read_bytes() == frozen.read_bytes()


def test_native_new_trading_session_is_refused_without_rewriting_protocol(tmp_path, monkeypatch):
    from quant_system.research import admission_v2
    from quant_system.research import external_intake as intake

    monkeypatch.setattr(intake, "_now", lambda: datetime(2026, 9, 22, 10, tzinfo=UTC))
    settings = example.isolated_settings(tmp_path / "attempt")
    with pytest.raises(ValueError, match="owner_example_native_requested_window_changed"):
        example.prepare_native_job(
            settings,
            proposal(),
            tmp_path / "not_read.parquet",
            {"requested_start": "2018-01-01", "requested_end": "2026-09-19"},
            {},
            expected_code=admission_v2.code_identity()["digest"],
        )
    files = list((settings.data.data_dir / "research_intake/jobs").glob("*.json"))
    assert len(files) == 1
    job = json.loads(files[0].read_text())
    assert job["plans"][0]["origin"]["end"] == "2026-09-21"
    assert job["admission_protocol"]["mode"] == "parallel"
    assert not (settings.data.data_dir / "research_intake/evaluations").exists()


def test_reference_copy_rechecks_digest_and_never_creates_sleeves(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    reference = original / "report.json"
    reference.write_text('{"historical_reference": true}')
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    example.write_json(
        snapshot / "snapshot-provenance.json",
        {
            "files": {
                "strategy_studies/runs/old/report.json": {
                    "original_path": str(reference),
                    "sha256": example.sha(reference),
                }
            },
        },
    )
    settings = example.isolated_settings(tmp_path / "attempt")
    example.install_family_references(settings, snapshot)
    copied = settings.data.data_dir / "strategy_studies/runs/old/report.json"
    assert copied.read_bytes() == reference.read_bytes()
    assert not copied.is_symlink()
    assert not (settings.data.data_dir / "api_runs").exists()
    reference.write_text("{}")
    with pytest.raises(ValueError, match="owner_example_family_source_changed"):
        example.install_family_references(example.isolated_settings(tmp_path / "other"), snapshot)


def test_failure_receipt_and_payload_closure_preserve_unknown(tmp_path):
    receipt = {"status": "failed", "admission_outcome": "unknown", "error": "fixed failure"}
    example.finish_receipt(tmp_path, receipt)
    assert json.loads((tmp_path / "receipt.json").read_text())["status"] == "failed"
    manifest = json.loads((tmp_path / "artifact-manifest.json").read_text())
    assert manifest["files"]["receipt.json"] == example.sha(tmp_path / "receipt.json")


def test_wrong_python_refuses_before_owner_creation_and_names_project_command(
    tmp_path, monkeypatch
):
    import sys

    monkeypatch.setattr(sys, "version_info", (3, 12, 13, "final", 0))
    with pytest.raises(RuntimeError, match="owner_example_requires_python_3_11") as error:
        example.run_example(
            candidate_path=tmp_path / "not_read.json",
            manifest_path=tmp_path / "not_read_manifest.json",
            recipes_path=tmp_path / "not_read_recipes.json",
            expected_code="must_not_reach_source_check",
        )
    assert ".venv/bin/python" in str(error.value)
    assert "PYTHONPATH=" in str(error.value)
    assert "current_phase2_owner_example.py" in str(error.value)
    assert list(tmp_path.iterdir()) == []


def test_current_snapshot_preserves_complete_trial_bytes_and_archived_inputs(tmp_path):
    source = tmp_path / "source"
    example.write_json(source / "assistant_remote/book.json", {"candidates": [], "requests": []})
    ledger = source / "trials/trials.jsonl"
    ledger.parent.mkdir()
    ledger.write_text('{"artificial_trial": 1}\n{"artificial_trial": 2}\n')
    artifact = source / "strategy_library/example/validations/run/platform-result.json"
    example.write_json(artifact, {"artificial_archive": True})
    settings = example.isolated_settings(tmp_path / "isolated")
    result = example.snapshot_current_owner(source, settings)
    assert result["trial_rows"] == 2
    assert result["formal_hashes_before"] == result["formal_hashes_after"]
    assert (settings.data.data_dir / "trials/trials.jsonl").read_bytes() == ledger.read_bytes()
    assert (
        settings.data.data_dir / artifact.relative_to(source)
    ).read_bytes() == artifact.read_bytes()
    assert not (settings.data.data_dir / "research_intake").exists()


def test_source_change_refuses_snapshot_before_any_isolated_research(tmp_path, monkeypatch):
    source = tmp_path / "source"
    example.write_json(source / "assistant_remote/book.json", {"candidates": [], "requests": []})
    ledger = source / "trials/trials.jsonl"
    ledger.parent.mkdir()
    ledger.write_text('{"artificial_trial": 1}\n')
    original = example.shutil.copyfile

    def change_after_copy(src, dest):
        result = original(src, dest)
        if src == ledger:
            ledger.write_text('{"artificial_trial": 2}\n')
        return result

    monkeypatch.setattr(example.shutil, "copyfile", change_after_copy)
    settings = example.isolated_settings(tmp_path / "isolated")
    with pytest.raises(ValueError, match="owner_snapshot_source_changed"):
        example.snapshot_current_owner(source, settings)
    assert not (settings.data.data_dir / "research_intake").exists()


def test_current_snapshot_rebinds_book_python_sources_outside_library(tmp_path):
    source = tmp_path / "source"
    factor = source / "_runtime/d34/jobs/example/research/candidate_factor.py"
    factor.parent.mkdir(parents=True)
    factor.write_text("# artificial source bytes; never executed\n")
    example.write_json(
        source / "assistant_remote/book.json",
        {
            "candidates": [
                {
                    "candidate_id": "artificial-peer",
                    "status": "hung",
                    "source_path": str(factor),
                    "source_digest": example.sha(factor),
                }
            ],
            "requests": [],
        },
    )
    ledger = source / "trials/trials.jsonl"
    ledger.parent.mkdir()
    ledger.write_text("")
    settings = example.isolated_settings(tmp_path / "isolated")
    result = example.snapshot_current_owner(source, settings)
    relative = str(factor.relative_to(source))
    assert result["files"][relative]["sha256"] == example.sha(factor)
    copied = settings.data.data_dir / relative
    assert copied.read_bytes() == factor.read_bytes()
    book = json.loads((settings.data.data_dir / "assistant_remote/book.json").read_text())
    assert book["candidates"][0]["source_path"] == str(copied)
    assert not (settings.data.data_dir / "research_intake").exists()
