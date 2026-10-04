import hashlib
import json

import pytest

from quant_system.config.settings import DataSettings, Settings
from quant_system.factors.scorecard import current_source_digest
from quant_system.factors.scorecard_service import (
    import_wide_scorecard,
    read_factor_scorecards,
    refresh_factor_scorecards,
)
from quant_system.research.wide_factor_set import frozen_factor_manifest


def _json(path, payload):
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wide_run(tmp_path):
    run = tmp_path / "frozen"
    run.mkdir()
    config = frozen_factor_manifest()
    _json(run / "run-config.json", config)
    _json(
        run / "input-manifest.json",
        {"schema_version": "qs.wide_inputs/v1", "provider": "mixed_explicit"},
    )
    acceptance = {
        "formal_ready": True,
        "research_status": "partial_known_source_limits",
        "known_source_limits": ["terminal_returns_unverified"],
        "admission_authority": False,
        "monthly_coverage": [
            {"month": "2016-01", "month_end_observed": 458, "daily_row_coverage": 0.90496}
        ],
        "source_groups": {"tiingo": {"symbols": 236}, "futu": {"symbols": 460}},
        "loaded": 696,
        "skipped": 50,
    }
    factors = [
        {"factor_id": item["factor_id"], "direction": item["direction"], "horizons": {}}
        for item in config["objects"]
    ]
    card = {
        "schema_version": "factor_scorecard_v1",
        "status": "partial",
        "factors": factors,
        "methodology": {},
        "provenance": {"source_digest": current_source_digest()},
        "data_acceptance": acceptance,
        "wide_run": {
            "factor_manifest_digest": config["digest"],
            "factor_manifest_file_sha256": _sha(run / "run-config.json"),
            "input_manifest_sha256": _sha(run / "input-manifest.json"),
            "admission_authority": False,
            "mode": "formal",
            "signal_window": config["signal_window"],
        },
    }
    _json(run / "scorecard.json", card)
    _json(run / "skip-registry.json", acceptance)
    _json(
        run / "factor-coverage.json", {"factors": [{"factor_id": x["factor_id"]} for x in factors]}
    )
    for name in ("ic_daily", "quantile_daily", "long_short_daily", "correlation_daily", "audit"):
        (run / f"{name}.parquet").write_bytes(b"PAR1 fixture PAR1")
    _json(run / "output-digests.json", {p.name: _sha(p) for p in run.iterdir()})
    return run, _sha(run / "output-digests.json")


def test_import_and_refresh_keep_the_frozen_27_objects_without_provider_calls(
    tmp_path, monkeypatch
):
    run, digest = wide_run(tmp_path)
    settings = Settings(data=DataSettings(data_dir=tmp_path / "data"))
    store = tmp_path / "store"
    result = import_wide_scorecard(
        settings, run, expected_output_manifest_sha256=digest, output_dir=store
    )
    assert len(result["factors"]) == len(result["factor_catalog"]) == 27
    assert result["data_acceptance"]["loaded"] == 696
    monkeypatch.setattr(
        "quant_system.factors.scorecard_service.build_ohlcv_provider",
        lambda *a, **k: pytest.fail("provider call"),
    )
    refreshed = refresh_factor_scorecards(
        settings, {"provider": "sample", "universe_id": "etf"}, output_dir=store
    )
    assert refreshed["run"]["kind"] == "wide_universe"
    assert refreshed["run"]["run_id"] == result["run"]["run_id"]
    assert len(read_factor_scorecards(settings, output_dir=store)["factor_coverage"]) == 27
    assert not (tmp_path / "data/trials").exists()


def test_failed_import_records_error_and_preserves_selected_run(tmp_path):
    run, digest = wide_run(tmp_path)
    settings = Settings(data=DataSettings(data_dir=tmp_path / "data"))
    store = tmp_path / "store"
    imported = import_wide_scorecard(
        settings, run, expected_output_manifest_sha256=digest, output_dir=store
    )
    (run / "scorecard.json").write_text("{}")
    with pytest.raises(ValueError, match="wide_output_digest_mismatch"):
        import_wide_scorecard(
            settings, run, expected_output_manifest_sha256=digest, output_dir=store
        )
    result = read_factor_scorecards(settings, output_dir=store)
    assert result["run"]["run_id"] == imported["run"]["run_id"]
    assert result["operation"]["status"] == "failed"
    assert result["error"] == "wide_output_digest_mismatch"


def test_corrupt_selected_wide_run_never_falls_back_to_legacy(tmp_path):
    run, digest = wide_run(tmp_path)
    settings = Settings(data=DataSettings(data_dir=tmp_path / "data"))
    store = tmp_path / "store"
    imported = import_wide_scorecard(
        settings, run, expected_output_manifest_sha256=digest, output_dir=store
    )
    _json(store / "latest.json", {"status": "ready", "factors": [{"factor_id": "old_etf"}]})
    from pathlib import Path

    (Path(imported["run"]["run_dir"]) / "scorecard.json").write_text("{}")
    result = read_factor_scorecards(settings, output_dir=store)
    assert result["status"] == "unavailable"
    assert result["reason"] == "wide_output_digest_mismatch"
    assert result["factors"] == []


def test_extra_rejection_marker_makes_the_bundle_ineligible_for_import(tmp_path):
    run, digest = wide_run(tmp_path)
    (run / "NOT_FOR_PUBLICATION.md").write_text("Failed evidence; retain for diagnosis.")
    settings = Settings(data=DataSettings(data_dir=tmp_path / "data"))
    with pytest.raises(ValueError, match="wide_output_not_closed"):
        import_wide_scorecard(
            settings, run, expected_output_manifest_sha256=digest, output_dir=tmp_path / "store"
        )


def test_lost_wide_selection_does_not_restart_legacy_provider_refresh(tmp_path, monkeypatch):
    run, digest = wide_run(tmp_path)
    settings = Settings(data=DataSettings(data_dir=tmp_path / "data"))
    store = tmp_path / "store"
    import_wide_scorecard(settings, run, expected_output_manifest_sha256=digest, output_dir=store)
    (store / "wide-selection.json").unlink()
    monkeypatch.setattr(
        "quant_system.factors.scorecard_service.build_ohlcv_provider",
        lambda *a, **k: pytest.fail("provider fallback"),
    )
    result = refresh_factor_scorecards(settings, output_dir=store)
    assert result["status"] == "unavailable"
    assert result["reason"] == "wide_selection_invalid"


def test_api_preserves_wide_evidence_fields_and_refresh_cannot_change_universe(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from quant_system.api.dependencies import require_mutation_security
    from quant_system.api.server import create_app

    run, digest = wide_run(tmp_path)
    settings = Settings(data=DataSettings(data_dir=tmp_path / "data"))
    import_wide_scorecard(
        settings,
        run,
        expected_output_manifest_sha256=digest,
        output_dir=tmp_path / "factor_scorecards",
    )
    app = create_app(settings=settings, output_dir=tmp_path)
    app.dependency_overrides[require_mutation_security] = lambda: None
    monkeypatch.setattr(
        "quant_system.factors.scorecard_service.build_ohlcv_provider",
        lambda *a, **k: pytest.fail("provider call"),
    )
    client = TestClient(app)
    response = client.get("/api/factor-scorecards")
    assert response.status_code == 200
    payload = response.json()
    assert payload["wide_run"]["admission_authority"] is False
    assert payload["data_acceptance"]["skipped"] == 50
    assert len(payload["factor_catalog"]) == len(payload["factor_coverage"]) == 27
    assert (
        client.post(
            "/api/factor-scorecards/refresh", json={"provider": "sample", "universe_id": "etf"}
        ).status_code
        == 202
    )
    after = client.get("/api/factor-scorecards").json()
    assert after["run"]["run_id"] == payload["run"]["run_id"]
    assert after["operation"]["status"] == "completed"
