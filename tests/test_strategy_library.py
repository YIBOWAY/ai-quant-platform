"""Local-only strategy lifecycle; tests never allocate a real paper account."""

import json
import math
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quant_system.api.dependencies import require_mutation_security
from quant_system.api.routes import strategy_library as route
from quant_system.config.settings import load_settings
from quant_system.research import strategy_library as service
from quant_system.research.strategy_definition import definition_from_study, formula_factor_id
from quant_system.research.study_profiles import list_study_profiles


@pytest.fixture
def settings(tmp_path):
    value = load_settings()
    value.data.data_dir = tmp_path
    return value


def _definition():
    profile = next(p for p in list_study_profiles() if p["id"] == "stocks_momentum_12_2")
    return definition_from_study({"profile": profile}, history_start="2015-01-01")


def test_get_empty_does_not_create_files(settings):
    assert service.list_strategies(settings) == {"items": []}
    assert not service._root(settings).exists()


def test_immutable_save_reuses_identity_and_preserves_monthly_top5(settings):
    definition = _definition()
    first = service._save_definition(settings, definition, {"type": "study"})
    again = service._save_definition(settings, definition, {"type": "study"})
    assert first == again
    assert first["status"] == "draft"
    assert first["definition"]["rebalance"] == "monthly"
    assert first["definition"]["top_n"] == 5
    assert not (settings.data.data_dir / "api_runs").exists()


def test_changed_source_is_not_eligible_for_paper(settings, monkeypatch):
    entry = service._save_definition(settings, _definition(), {})
    source = service._directory(settings, entry["strategy_id"]) / "definition.json"
    source.write_text(source.read_text() + "\n")
    monkeypatch.setattr(
        service.assistant_remote, "hang_candidate", lambda *a, **k: pytest.fail("unexpected hang")
    )
    assert service.read_strategy(settings, entry["strategy_id"])["status"] == "stale"
    with pytest.raises(ValueError, match="validation_required"):
        service.enable_strategy(settings, entry["strategy_id"], entry["definition_digest"])


def test_source_must_be_an_available_exact_saved_study(settings):
    run_id = "study-sealed"
    directory = settings.data.data_dir / "strategy_studies" / "runs" / run_id
    directory.mkdir(parents=True)
    profile = next(p for p in list_study_profiles() if p["id"] == "stocks_momentum_12_2")
    (directory / "report.json").write_text(
        json.dumps(
            {"run_id": run_id, "results": [{"profile": profile, "status": "failed"}], "source": {}}
        )
    )
    with pytest.raises(ValueError, match="unavailable"):
        service.import_study(settings, run_id, profile["id"])
    assert service.list_strategies(settings) == {"items": []}


def test_qlib_identity_or_accounting_mismatch_is_not_a_comparison_pass():
    result = {
        "curve": [{"date": "2026-01-02", "equity": 10000}, {"date": "2026-01-05", "equity": 10000}],
        "signals": [],
        "evaluation_initial_cash": 10000,
        "trades": [],
    }
    prices = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2026-01-05"], utc=True), "symbol": ["SPY"], "close": [100.0]}
    )
    with pytest.raises(ValueError, match="calendar_mismatch"):
        service._comparison(prices, result, {"return_dates": ["2026-01-02"]}, _definition())
    result["curve"][-1]["equity"] = 99999
    with pytest.raises(ValueError, match="accounting_mismatch"):
        service._comparison(
            prices, result, {"return_dates": ["2026-01-02", "2026-01-05"]}, _definition()
        )


def test_api_mutation_is_guarded_before_import(settings, monkeypatch):
    app = FastAPI()
    app.state.services = {
        "settings": settings,
        "output_dir": settings.data.data_dir,
        "bind_address": "127.0.0.1",
    }
    app.include_router(route.router, prefix="/api")
    monkeypatch.setattr(service, "import_study", lambda *a, **k: pytest.fail("unowned import"))
    response = TestClient(app).post(
        "/api/strategy-library/import-study", json={"run_id": "study-test", "profile_id": "test"}
    )
    assert response.status_code in {401, 403}


def test_api_validation_does_not_start_another_strategy(settings, monkeypatch):
    app = FastAPI()
    app.state.services = {
        "settings": settings,
        "output_dir": settings.data.data_dir,
        "bind_address": "127.0.0.1",
    }
    app.include_router(route.router, prefix="/api")
    app.dependency_overrides[require_mutation_security] = lambda: None
    entry = service._save_definition(settings, _definition(), {})
    monkeypatch.setattr(route, "_ACTIVE", "another-strategy")
    monkeypatch.setattr(
        service, "validate_strategy", lambda *a, **k: pytest.fail("duplicate validation")
    )
    route._LOCK.acquire()
    try:
        response = TestClient(app).post(
            f"/api/strategy-library/{entry['strategy_id']}/validate",
            json={"expected_digest": entry["definition_digest"]},
        )
        assert response.status_code == 409
    finally:
        route._LOCK.release()


def test_api_compose_accepts_default_and_explicit_kind_without_starting_research(
    settings, monkeypatch,
):
    app = FastAPI()
    app.state.services = {
        "settings": settings, "output_dir": settings.data.data_dir,
        "bind_address": "127.0.0.1",
    }
    app.include_router(route.router, prefix="/api")
    app.dependency_overrides[require_mutation_security] = lambda: None

    def forbidden(*_args, **_kwargs):
        pytest.fail("saving a composed strategy started research or paper execution")

    for method in ("_collect_prices", "_docker", "validate_strategy", "enable_strategy"):
        monkeypatch.setattr(service, method, forbidden)
    monkeypatch.setattr(service.assistant_remote, "hang_candidate", forbidden)
    monkeypatch.setattr(service.assistant_remote, "record_verified_candidate", forbidden)
    expression = "-($close/Ref($close,5))"
    payload = {
        "title": "密封每周双因子组合", "symbols": ["AAPL", "MSFT", "NVDA"],
        "benchmark_symbol": "SPY", "rebalance": "weekly", "top_n": 2,
        "normalization": "rank", "max_weight_per_symbol": 0.3,
        "target_gross_exposure": 0.6, "min_order_value": 10,
        "factors": [
            {"factor_id": "momentum", "expression": None, "lookback": 21,
             "direction": "higher_is_better", "weight": 0.5},
            {"factor_id": formula_factor_id(expression), "expression": expression,
             "lookback": 6, "direction": "higher_is_better", "weight": 0.5},
        ],
    }
    with TestClient(app) as client:
        implicit = client.post("/api/strategy-library/compose", json=payload)
        explicit = client.post(
            "/api/strategy-library/compose", json={**payload, "kind": "factor_blend"},
        )
    assert implicit.status_code == explicit.status_code == 200
    first, second = implicit.json(), explicit.json()
    assert first["strategy_id"] == second["strategy_id"]
    assert first["definition_digest"] == second["definition_digest"]
    assert first["status"] == second["status"] == "draft"
    assert first["validation"] is None
    assert first["candidate_id"] is None and first["sleeve_id"] is None
    definition = first["definition"]
    assert definition["kind"] == "factor_blend"
    for key in ("symbols", "benchmark_symbol", "rebalance", "top_n", "normalization",
                "max_weight_per_symbol", "target_gross_exposure", "min_order_value"):
        assert definition[key] == payload[key]
    assert [item["lookback"] for item in definition["factors"]] == [21, 6]
    assert [item["weight"] for item in definition["factors"]] == [0.5, 0.5]
    saved = service._directory(settings, first["strategy_id"]) / "definition.json"
    assert json.loads(saved.read_text()) == definition
    assert list(service._root(settings).glob("strategy-*/entry.json")) == [
        saved.parent / "entry.json",
    ]
    assert not (saved.parent / "validations").exists()


def _saved_family(settings):
    result = {
        "profile": {"id": "sealed-factor", "symbols": ["AAA"], "rules": ["fixed rule"]},
        "status": "available", "source": "futu", "price_adjustment": "qfq",
        "curve": [
            {"date": f"2026-01-{day:02d}", "equity": equity}
            for day, equity in zip(
                range(1, 7), [100_000, 101_000, 99_900, 102_000, 103_000, 101_500], strict=True,
            )
        ],
    }
    report = {"source": {"prices_sha256": "a" * 64}, "results": [result]}
    path = settings.data.data_dir / "strategy_studies" / "runs" / "study-sealed" / "report.json"
    service._write(path, report)
    return path, report


def test_content_addressed_family_reuses_stored_statistics_across_float_summation(
    settings, monkeypatch,
):
    _saved_family(settings)
    service._record_study_family(settings, ["AAA"])
    ledger = service.TrialsLedger(settings.data.data_dir / "trials")
    before = ledger.path.read_bytes()
    _float_noise(monkeypatch)
    service._record_study_family(settings, ["AAA"])
    assert ledger.path.read_bytes() == before
    assert len(ledger.list()) == 1


@pytest.mark.parametrize("change", ["curve", "rule", "prices"])
def test_changed_family_evidence_is_a_new_trial(settings, change):
    path, report = _saved_family(settings)
    service._record_study_family(settings, ["AAA"])
    if change == "curve":
        report["results"][0]["curve"][2]["equity"] += 500
    elif change == "rule":
        report["results"][0]["profile"]["rules"] = ["different fixed rule"]
    else:
        report["source"]["prices_sha256"] = "b" * 64
    service._write(path, report)
    service._record_study_family(settings, ["AAA"])
    rows = service.TrialsLedger(settings.data.data_dir / "trials").list()
    assert len(rows) == 2 and rows[0].trial_id != rows[1].trial_id


def test_same_content_id_with_different_definition_remains_a_conflict(settings):
    path, report = _saved_family(settings)
    service._record_study_family(settings, ["AAA"])
    ledger = service.TrialsLedger(settings.data.data_dir / "trials")
    before = ledger.path.read_bytes()
    report["results"][0]["definition_digest"] = "different-definition"
    service._write(path, report)
    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        service._record_study_family(settings, ["AAA"])
    assert ledger.path.read_bytes() == before


def test_a_claimed_content_id_cannot_be_reused_for_a_different_curve(settings):
    _, report = _saved_family(settings)
    service._record_study_family(settings, ["AAA"])
    ledger = service.TrialsLedger(settings.data.data_dir / "trials")
    run_id = ledger.list()[0].metadata["run_id"]
    result = report["results"][0]
    # Keep initial/final equity and dates, but change the real return path.
    result["curve"][2]["equity"] += 1
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        service._record_trial(settings, result, run_id, ["AAA"], study_prices_digest="a" * 64)
    assert ledger.path.read_bytes() == before


def test_uncertified_validation_run_still_rejects_statistical_conflicts(settings, monkeypatch):
    _, report = _saved_family(settings)
    result = report["results"][0]
    service._record_trial(settings, result, "definition-validation-sealed", ["AAA"])
    original_record = service.ResearchTrial.record

    def changed(**kwargs):
        return original_record(**kwargs).model_copy(update={"sharpe": 99.0})

    monkeypatch.setattr(service.ResearchTrial, "record", changed)
    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        service._record_trial(settings, result, "definition-validation-sealed", ["AAA"])


def _verified_validation(settings):
    definition = _definition()
    entry = service._save_definition(settings, definition, {"type": "study"})
    directory = service._directory(settings, entry["strategy_id"])
    run = directory / "validations" / ("validation-" + "a" * 32)
    run.mkdir(parents=True)
    _, report = _saved_family(settings)
    result = report["results"][0]
    result.update(definition_digest=definition.content_digest, evaluation_initial_cash=10_000,
                  start=result["curve"][0]["date"], end=result["curve"][-1]["date"])
    for point in result["curve"]:
        point["equity"] /= 10
    pd.DataFrame({"symbol": ["AAA"], "close": [100.0]}).to_parquet(run / "prices.parquet")
    service._write(run / "platform-result.json", result)
    file_prices_digest = service._file_hash(run / "prices.parquet")
    prices_digest = service._prices_content_digest(pd.read_parquet(run / "prices.parquet"))
    result_digest = service._file_hash(run / "platform-result.json")
    sources = {
        name: service._file_hash(Path(service.__file__).with_name(name))
        for name in (
            "definition_qlib_replay.py", "strategy_signal_validation.py", "qlib_evaluation.py",
        )
    }
    service._write(run / "qlib-replay.json", {
        "status": "available", "definition_digest": definition.content_digest,
        "source": {"prices_sha256": file_prices_digest, "platform_result_sha256": result_digest,
                   "replay_source_sha256": sources["definition_qlib_replay.py"]},
    })
    service._write(run / "signal-analysis.json", {
        "status": "available", "definition_digest": definition.content_digest,
        "source": {"prices_sha256": file_prices_digest, "result_sha256": result_digest,
                   "validation_source_sha256": sources["strategy_signal_validation.py"],
                   "fit_metrics_source_sha256": sources["qlib_evaluation.py"]},
    })
    validation = {
        "status": "passed", "definition_digest": definition.content_digest,
        "run_id": run.name, "blockers": [],
        "comparison": {"accepted": True, "comparison_digest": "c" * 64},
        "receipts": service.receipt_bindings(run),
    }
    service._write(run / "validation.json", validation)
    entry.update(
        validation=validation, validation_sha256=service._file_hash(run / "validation.json"),
    )
    service._write(directory / "entry.json", entry)
    run_id = "definition-validation-" + service._hash({
        "definition": definition.content_digest, "prices": prices_digest,
        "start": result["start"], "end": result["end"], "cash": 10_000,
    })
    return result, run_id, prices_digest, run, directory


def _float_noise(monkeypatch):
    original = service.ResearchTrial.record

    def changed(**kwargs):
        trial = original(**kwargs)
        return trial.model_copy(update={
            key: math.nextafter(getattr(trial, key), math.inf)
            for key in ("sharpe", "sharpe_annual", "skewness", "kurtosis")
        })

    monkeypatch.setattr(service.ResearchTrial, "record", changed)


@pytest.mark.parametrize("legacy", [True, False])
def test_definition_trial_exact_curve_is_idempotent_without_double_counting(
    settings, monkeypatch, legacy,
):
    result, run_id, prices_digest, _, _ = _verified_validation(settings)
    first_kwargs = {} if legacy else {"validation_prices_digest": prices_digest}
    service._record_trial(settings, result, run_id, ["AAA"], **first_kwargs)
    ledger = service.TrialsLedger(settings.data.data_dir / "trials")
    before = ledger.path.read_bytes()
    _float_noise(monkeypatch)
    service._record_trial(settings, result, run_id, ["AAA"], validation_prices_digest=prices_digest)
    assert ledger.path.read_bytes() == before and len(ledger.list()) == 1


@pytest.mark.parametrize("legacy", [True, False])
def test_definition_trial_rejects_different_curve_even_with_same_endpoints(settings, legacy):
    result, run_id, prices_digest, _, _ = _verified_validation(settings)
    first_kwargs = {} if legacy else {"validation_prices_digest": prices_digest}
    service._record_trial(settings, result, run_id, ["AAA"], **first_kwargs)
    ledger = service.TrialsLedger(settings.data.data_dir / "trials")
    before = ledger.path.read_bytes()
    result["curve"][2]["equity"] += 1
    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        service._record_trial(
            settings, result, run_id, ["AAA"], validation_prices_digest=prices_digest,
        )
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("damage", ["missing_receipt", "changed_file", "other_strategy"])
def test_legacy_definition_trial_requires_same_strategy_verified_receipt(settings, damage):
    result, run_id, prices_digest, run, directory = _verified_validation(settings)
    service._record_trial(settings, result, run_id, ["AAA"])
    if damage == "changed_file":
        service._write(run / "platform-result.json", {**result, "unexpected_change": True})
    else:
        entry = json.loads((directory / "entry.json").read_text())
        if damage == "missing_receipt":
            entry.pop("validation_sha256")
        else:
            entry["strategy_id"] = "strategy-" + "b" * 24
        service._write(directory / "entry.json", entry)
    ledger = service.TrialsLedger(settings.data.data_dir / "trials")
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        service._record_trial(
            settings, result, run_id, ["AAA"], validation_prices_digest=prices_digest,
        )
    assert ledger.path.read_bytes() == before


def test_validation_failure_record_survives_entry_refresh(settings, monkeypatch):
    entry = service._save_definition(
        settings, _definition(), {"type": "study", "run_id": "study-sealed"},
    )

    def failed_input(*args):
        raise ValueError("sealed_saved_input_unavailable")

    monkeypatch.setattr(service, "_load_report", failed_input)
    failed = service.validate_strategy(settings, entry["strategy_id"], entry["definition_digest"])
    directory = service._directory(settings, entry["strategy_id"])
    paths = list((directory / "validations").glob("*/failure.json"))
    assert len(paths) == 1
    before = paths[0].read_bytes()
    failure = json.loads(before)
    assert failure["error"] == "sealed_saved_input_unavailable"
    assert failure["definition_digest"] == entry["definition_digest"]
    assert failure["recorded_at"]
    service._write(directory / "entry.json", {**failed, "error": None})
    assert paths[0].read_bytes() == before


def _rewritten_prices(source, destination, *, close=None):
    """Same frame content, different parquet bytes, as a writer upgrade would leave."""
    prices = pd.read_parquet(source)
    if close is not None:
        prices.loc[prices.index[-1], "close"] = close
    prices.to_parquet(destination, index=False, compression="gzip", compression_level=1)
    return destination


def test_same_numbers_in_different_parquet_bytes_are_one_identity(tmp_path):
    prices = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-05", "2026-01-06"], utc=True),
            "symbol": ["AAA", "AAA"],
            "close": [100.0, 101.5],
        }
    )
    first, second = tmp_path / "first.parquet", tmp_path / "second.parquet"
    prices.to_parquet(first, index=False)
    _rewritten_prices(first, second)
    assert service._file_hash(first) != service._file_hash(second)
    assert service._prices_content_digest(
        pd.read_parquet(first)
    ) == service._prices_content_digest(pd.read_parquet(second))
    changed = _rewritten_prices(first, tmp_path / "changed.parquet", close=101.6)
    assert service._prices_content_digest(
        pd.read_parquet(changed)
    ) != service._prices_content_digest(pd.read_parquet(second))
    reordered = pd.read_parquet(second)[["close", "symbol", "timestamp"]]
    assert service._prices_content_digest(reordered) == service._prices_content_digest(
        pd.read_parquet(second)
    )


def test_rewritten_validation_prices_keep_one_trial_without_double_counting(settings, tmp_path):
    result, run_id, prices_digest, run, _ = _verified_validation(settings)
    service._record_trial(settings, result, run_id, ["AAA"], validation_prices_digest=prices_digest)
    ledger = service.TrialsLedger(settings.data.data_dir / "trials")
    before = ledger.path.read_bytes()
    rewritten = _rewritten_prices(run / "prices.parquet", tmp_path / "rewritten.parquet")
    assert service._file_hash(rewritten) != service._file_hash(run / "prices.parquet")
    rewritten_digest = service._prices_content_digest(pd.read_parquet(rewritten))
    assert rewritten_digest == prices_digest
    # The file-bound identity would have recorded a second trial for one computation.
    assert "definition-validation-" + service._hash(
        {
            "definition": result["definition_digest"],
            "prices": service._file_hash(rewritten),
            "start": result["start"],
            "end": result["end"],
            "cash": 10_000,
        }
    ) != run_id
    assert service._validation_trial_identity(
        result["definition_digest"], pd.read_parquet(rewritten), result
    ) == run_id.removeprefix("definition-validation-")
    service._record_trial(
        settings, result, run_id, ["AAA"], validation_prices_digest=rewritten_digest
    )
    assert ledger.path.read_bytes() == before and len(ledger.list()) == 1
