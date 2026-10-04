import json
from pathlib import Path

import pandas as pd
import pytest

from quant_system.config.settings import DataSettings, Settings
from quant_system.research import active_metrics as calculator
from quant_system.research import strategy_study_service as studies
from quant_system.research.evaluation_service import _file_hash, _hash
from quant_system.research.study_active_evidence import (
    evidence_digest,
    import_study_active_evidence,
)


def fixture_bundle(tmp_path):
    settings = Settings(data=DataSettings(data_dir=tmp_path / "data"))
    result = {
        "profile": {"id": "test", "name": "Test", "benchmark_symbol": "SPY"},
        "status": "available",
        "curve": [
            {"date": "2020-01-02", "equity": 100000.0, "benchmark": 100000.0, "peer": 100000.0},
            {"date": "2020-01-03", "equity": 101000.0, "benchmark": 100200.0, "peer": 100100.0},
            {"date": "2020-01-06", "equity": 101800.0, "benchmark": 100000.0, "peer": 100200.0},
        ],
        "metrics": {"sharpe": 0.2, "total_return": 0.018},
        "active_metrics": None,
    }
    report = {
        **studies._empty(),
        "run_id": "study-test",
        "status": "ready",
        "calculation_digest": studies.calculation_digest(),
        "results": [result],
    }
    directory = settings.data.data_dir / "strategy_studies"
    studies._write(directory / "latest.json", report)
    studies._write(directory / "runs/study-test/report.json", report)
    bundle = tmp_path / "evidence"
    (bundle / "studies").mkdir(parents=True)
    (bundle / "saved-study-snapshot.json").write_text(json.dumps(report))
    (bundle / "inputs.json").write_text(
        json.dumps(
            {
                "source_hashes": {
                    "src/quant_system/research/active_metrics.py": _file_hash(
                        Path(calculator.__file__)
                    )
                }
            }
        )
    )
    entry = {
        "profile_id": "test",
        "source_result_digest": _hash(result),
        "status": "ready",
        "evaluation_only": True,
        "new_research_trial": False,
        "initial_cash": 100000.0,
        "active_metrics": calculator.active_metrics(
            pd.DataFrame(result["curve"])
            .rename(columns={"date": "timestamp"})
            .assign(timestamp=lambda d: pd.to_datetime(d.timestamp, utc=True)),
            initial_cash=100000.0,
            benchmark_symbol="SPY",
        ),
    }
    (bundle / "studies/test.json").write_text(json.dumps(entry))
    return settings, bundle, report, entry


def test_import_projects_only_bound_statistics_without_changing_original_report_or_math(
    tmp_path, monkeypatch
):
    settings, bundle, report, _ = fixture_bundle(tmp_path)
    root = settings.data.data_dir / "strategy_studies"
    before = {
        (root / x): (root / x).read_bytes() for x in ["latest.json", "runs/study-test/report.json"]
    }
    calculation = studies.calculation_digest()
    monkeypatch.setattr(studies, "run_profile", lambda *a, **k: pytest.fail("read ran a backtest"))
    import_study_active_evidence(settings, bundle, expected_evidence_digest=evidence_digest(bundle))
    monkeypatch.setattr(
        calculator, "active_metrics", lambda *a, **k: pytest.fail("GET recalculated statistics")
    )
    shown = studies.read_studies(settings)
    assert shown["results"][0]["active_metrics"]["n_observations"] == 3
    assert shown["results"][0]["active_metrics_evidence"]["kind"] == "derived_sidecar"
    assert studies.calculation_digest() == calculation
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert report["results"][0]["active_metrics"] is None


def test_self_signed_wrong_source_result_is_rejected(tmp_path):
    settings, bundle, _, entry = fixture_bundle(tmp_path)
    entry["source_result_digest"] = "f" * 64
    (bundle / "studies/test.json").write_text(json.dumps(entry))
    with pytest.raises(ValueError, match="study_active_source_result_mismatch"):
        import_study_active_evidence(
            settings, bundle, expected_evidence_digest=evidence_digest(bundle)
        )


@pytest.mark.parametrize(
    ("section", "field"),
    [("information_ratio", "value"), ("beta_alpha", "alpha_annualized")],
)
def test_tampered_statistic_cannot_become_ready_by_resigning_evidence_digest(
    tmp_path, section, field
):
    settings, bundle, _, entry = fixture_bundle(tmp_path)
    entry["active_metrics"]["vs_benchmark"][section][field] = 42.123456789
    (bundle / "studies/test.json").write_text(json.dumps(entry))
    with pytest.raises(ValueError, match="study_active_metrics_recompute_mismatch"):
        import_study_active_evidence(
            settings, bundle, expected_evidence_digest=evidence_digest(bundle)
        )
    assert not (settings.data.data_dir / "strategy_studies/active_metrics_sidecars").exists()


@pytest.mark.parametrize("change", ["initial_cash", "benchmark", "calculator"])
def test_self_reported_calculation_inputs_do_not_override_original_contract(tmp_path, change):
    settings, bundle, _, entry = fixture_bundle(tmp_path)
    if change == "initial_cash":
        entry["initial_cash"] = 50000.0
    elif change == "benchmark":
        entry["active_metrics"]["vs_benchmark"]["benchmark_symbol"] = "QQQ"
    else:
        (bundle / "inputs.json").write_text(
            json.dumps({"source_hashes": {"src/quant_system/research/active_metrics.py": "0" * 64}})
        )
    (bundle / "studies/test.json").write_text(json.dumps(entry))
    with pytest.raises(ValueError, match="study_active_"):
        import_study_active_evidence(
            settings, bundle, expected_evidence_digest=evidence_digest(bundle)
        )


def test_changed_saved_curve_never_borrows_previous_active_statistics(tmp_path):
    settings, bundle, report, _ = fixture_bundle(tmp_path)
    import_study_active_evidence(settings, bundle, expected_evidence_digest=evidence_digest(bundle))
    report["results"][0]["curve"][0]["equity"] = 999.0
    studies._write(settings.data.data_dir / "strategy_studies/latest.json", report)
    shown = studies.read_studies(settings)
    assert shown["results"][0]["active_metrics"] is None
    assert (
        shown["results"][0]["active_metrics_evidence"]["reason"] == "source_result_digest_mismatch"
    )


def test_new_native_metrics_take_priority_over_old_derived_sidecar(tmp_path):
    settings, bundle, report, _ = fixture_bundle(tmp_path)
    import_study_active_evidence(settings, bundle, expected_evidence_digest=evidence_digest(bundle))
    report["results"][0]["active_metrics"] = {
        "status": "ready",
        "vs_benchmark": {"information_ratio": {"value": 0.9}},
    }
    studies._write(settings.data.data_dir / "strategy_studies/latest.json", report)
    shown = studies.read_studies(settings)
    assert (
        shown["results"][0]["active_metrics"]["vs_benchmark"]["information_ratio"]["value"] == 0.9
    )
    assert shown["results"][0]["active_metrics_evidence"]["kind"] == "native"


def test_corrupt_sidecar_preserves_original_metrics_and_explicitly_blanks_active_block(tmp_path):
    settings, bundle, _, _ = fixture_bundle(tmp_path)
    receipt = import_study_active_evidence(
        settings, bundle, expected_evidence_digest=evidence_digest(bundle)
    )
    Path(receipt["sidecar_path"]).write_text("{}")
    shown = studies.read_studies(settings)
    assert shown["results"][0]["metrics"]["sharpe"] == 0.2
    assert shown["results"][0]["active_metrics"] is None
    assert shown["results"][0]["active_metrics_evidence"]["status"] == "unavailable"
