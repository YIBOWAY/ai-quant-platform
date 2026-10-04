from __future__ import annotations

from pathlib import Path

import pytest

from quant_system.config.settings import reload_settings
from quant_system.experiments.models import ExperimentConfig, FactorBlendConfig, FactorWeight
from quant_system.experiments.runner import run_experiment
from quant_system.research.trials import (
    BACKTEST_SHAPED_ENTRY_POINTS,
    BACKTEST_SHAPED_EXEMPTIONS,
    DSR_FAMILY_MIN_PERIODS,
    ResearchTrial,
    TrialsLedger,
    enumerate_backtest_engine_callsites,
    reconcile_trial_coverage,
)


def test_backtest_shaped_entry_points_are_wired_to_the_ledger() -> None:
    import importlib
    import inspect

    assert BACKTEST_SHAPED_ENTRY_POINTS
    for dotted in BACKTEST_SHAPED_ENTRY_POINTS:
        module_name, func_name = dotted.split(":")
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        assert "TrialsLedger" in source or "ResearchTrial" in source, dotted
        assert hasattr(module, func_name), dotted


def test_skipped_tombstone_appends_but_stays_out_of_dsr_family(tmp_path: Path) -> None:
    ledger = TrialsLedger(tmp_path / "trials")
    tombstone = ResearchTrial.skipped(
        kind="factor_lab",
        subject="factor_lab_dashboard",
        universe=["QQQ"],
        reason="exploratory_dashboard_not_dsr_family",
        source="test",
        metadata={"run_id": "run-lab-1"},
    )
    ledger.append(tombstone)

    rows = ledger.list()
    assert len(rows) == 1
    assert rows[0].metadata["skipped"] is True
    assert rows[0].metadata["skip_reason"] == "exploratory_dashboard_not_dsr_family"
    assert rows[0].n_periods == 0
    assert rows[0].sharpe is None
    assert ledger.trial_sharpes() == []
    assert DSR_FAMILY_MIN_PERIODS > rows[0].n_periods


def test_trial_coverage_rejects_extra_ledger_run_ids(tmp_path: Path) -> None:
    ledger = TrialsLedger(tmp_path / "trials")
    for run_id in ("run-expected", "run-extra"):
        ledger.append(
            ResearchTrial.skipped(
                kind="factor_lab",
                subject="coverage",
                universe=["SPY"],
                reason="test_only",
                source=run_id,
                metadata={"run_id": run_id},
            )
        )

    coverage = reconcile_trial_coverage(ledger, ["run-expected"])

    assert coverage["extras"] == ["run-extra"]
    assert coverage["passed"] is False


def test_trial_coverage_rejects_duplicate_expected_run_ids(tmp_path: Path) -> None:
    ledger = TrialsLedger(tmp_path / "trials")
    ledger.append(
        ResearchTrial.skipped(
            kind="factor_lab",
            subject="coverage",
            universe=["SPY"],
            reason="test_only",
            source="run-a",
            metadata={"run_id": "run-a"},
        )
    )

    coverage = reconcile_trial_coverage(ledger, ["run-a", "run-a"])

    assert coverage["duplicate_expected_run_ids"] == ["run-a"]
    assert coverage["n_runs"] == 2
    assert coverage["n_ledger_rows"] == 1
    assert coverage["passed"] is False


def test_experiment_run_appends_one_trial_per_combination(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    result = run_experiment(
        ExperimentConfig(
            experiment_name="op0k-experiment",
            symbols=["SPY", "QQQ"],
            start="2024-01-02",
            end="2024-02-15",
            factor_blend=FactorBlendConfig(factors=[FactorWeight(factor_id="momentum")]),
            sweep={"lookback": [3, 5], "top_n": [1]},
        ),
        output_dir=tmp_path / "out",
    )
    ledger = TrialsLedger(Path(settings.data.data_dir) / "trials")
    rows = ledger.list()
    assert result.run_count == 2
    assert len(rows) == result.run_count
    assert {row.kind for row in rows} == {"experiment"}
    run_ids = [str(row.metadata["run_id"]) for row in rows]
    coverage = reconcile_trial_coverage(ledger, run_ids)
    assert coverage["passed"] is True
    assert coverage["n_runs"] == result.run_count
    assert coverage["n_ledger"] == result.run_count


def test_repeated_experiment_sweeps_use_distinct_trial_run_ids(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    reload_settings()
    config = ExperimentConfig(
        experiment_name="op0k-repeat",
        symbols=["SPY", "QQQ"],
        start="2024-01-02",
        end="2024-02-15",
        factor_blend=FactorBlendConfig(factors=[FactorWeight(factor_id="momentum")]),
        sweep={"lookback": [3, 5], "top_n": [1]},
    )

    first = run_experiment(config, output_dir=tmp_path / "out")
    second = run_experiment(config, output_dir=tmp_path / "out")

    assert first.experiment_id != second.experiment_id
    rows = TrialsLedger(tmp_path / "data" / "trials").list()
    assert len(rows) == first.run_count + second.run_count == 4
    assert len({str(row.metadata["run_id"]) for row in rows}) == 4


def test_factor_lab_recompute_writes_tombstone_cache_hit_does_not(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    from quant_system.factors.lab import build_factor_lab_dashboard

    first = build_factor_lab_dashboard(
        settings=settings,
        output_dir=tmp_path / "out",
        provider="sample",
        universe_id="etf",
        symbol="QQQ",
        start="2024-01-02",
        end="2024-03-29",
        lookback=3,
        force_refresh=True,
    )
    ledger = TrialsLedger(Path(settings.data.data_dir) / "trials")
    rows = ledger.list()
    assert first["cache"]["status"] == "recomputed"
    assert len(rows) == 1
    assert rows[0].kind == "factor_lab"
    assert rows[0].metadata["skipped"] is True
    assert rows[0].metadata["skip_reason"] == "exploratory_dashboard_not_dsr_family"
    run_id = str(rows[0].metadata["run_id"])
    assert reconcile_trial_coverage(ledger, [run_id])["passed"] is True

    cached = build_factor_lab_dashboard(
        settings=settings,
        output_dir=tmp_path / "out",
        provider="sample",
        universe_id="etf",
        symbol="QQQ",
        start="2024-01-02",
        end="2024-03-29",
        lookback=3,
    )
    assert cached["cache"]["status"] == "cached"
    assert len(ledger.list()) == 1


def test_factor_lab_force_refreshes_record_distinct_attempts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    from quant_system.factors.lab import build_factor_lab_dashboard

    kwargs = {
        "settings": settings,
        "output_dir": tmp_path / "out",
        "provider": "sample",
        "universe_id": "etf",
        "symbol": "QQQ",
        "start": "2024-01-02",
        "end": "2024-03-29",
        "lookback": 3,
        "force_refresh": True,
    }
    build_factor_lab_dashboard(**kwargs)
    build_factor_lab_dashboard(**kwargs)

    rows = TrialsLedger(tmp_path / "data" / "trials").list()
    assert len(rows) == 2
    assert len({str(row.metadata["run_id"]) for row in rows}) == 2


def test_strategy_replication_appends_trial(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    from quant_system.replication.reversal_momentum import (
        build_reversal_momentum_replication,
    )
    from tests.test_reversal_momentum_replication import _frame

    result = build_reversal_momentum_replication(_frame(), initial_cash=1.0, top_n=1)
    assert result["metrics"]["observation_months"] >= 2
    ledger = TrialsLedger(Path(settings.data.data_dir) / "trials")
    rows = ledger.list()
    assert len(rows) == 1
    assert rows[0].kind == "strategy_replication"
    assert rows[0].metadata.get("skipped") is not True
    assert rows[0].n_periods >= 1
    assert reconcile_trial_coverage(ledger, [str(rows[0].metadata["run_id"])])["passed"]


def test_prediction_market_timeseries_appends_trial_or_tombstone(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    from quant_system.prediction_market.collector import seed_sample_history_dataset
    from quant_system.prediction_market.storage import PredictionMarketSnapshotStore
    from quant_system.prediction_market.timeseries_backtest import (
        PredictionMarketTimeseriesBacktestConfig,
        run_prediction_market_timeseries_backtest,
    )

    seed_sample_history_dataset(tmp_path / "pm")
    store = PredictionMarketSnapshotStore(tmp_path / "pm")
    run_prediction_market_timeseries_backtest(
        store=store,
        config=PredictionMarketTimeseriesBacktestConfig(
            provider="sample",
            min_edge_bps=200,
            capital_limit=1000,
            max_markets=10,
            max_legs=3,
            fee_bps=0,
            display_size_multiplier=1.0,
        ),
    )
    ledger = TrialsLedger(Path(settings.data.data_dir) / "trials")
    rows = ledger.list()
    assert len(rows) == 1
    assert rows[0].kind == "prediction_market"
    assert reconcile_trial_coverage(ledger, [str(rows[0].metadata["run_id"])])["passed"]


def test_prediction_market_quasi_backtest_appends_trial_or_tombstone(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    settings = reload_settings()
    from quant_system.prediction_market.backtest import (
        PredictionMarketBacktestConfig,
        run_prediction_market_quasi_backtest,
    )
    from quant_system.prediction_market.data.sample_provider import (
        SamplePredictionMarketProvider,
    )

    run_prediction_market_quasi_backtest(
        provider=SamplePredictionMarketProvider(),
        config=PredictionMarketBacktestConfig(
            min_edge_bps=200,
            capital_limit=1000,
            max_legs=3,
            max_markets=10,
            fee_bps=0,
        ),
    )
    ledger = TrialsLedger(Path(settings.data.data_dir) / "trials")
    rows = ledger.list()
    assert len(rows) == 1
    assert rows[0].kind == "prediction_market"
    assert reconcile_trial_coverage(ledger, [str(rows[0].metadata["run_id"])])["passed"]


def test_trial_coverage_can_be_scoped_to_one_job(tmp_path: Path) -> None:
    """A job-scoped census must ignore unrelated history (production wiring needs it)."""
    ledger = TrialsLedger(tmp_path / "trials")
    for run_id, job_id in (
        ("job-a:iteration-01-experiment-01", "job-a"),
        ("job-a:iteration-01-experiment-02", "job-a"),
        ("job-b:iteration-01-experiment-01", "job-b"),
    ):
        ledger.append(
            ResearchTrial.skipped(
                kind="d34_experiment",
                subject="coverage",
                universe=["SPY"],
                reason="test_only",
                source="test",
                metadata={"run_id": run_id, "job_id": job_id},
            )
        )
    scoped = reconcile_trial_coverage(
        ledger,
        ["job-a:iteration-01-experiment-01", "job-a:iteration-01-experiment-02"],
        scope_metadata={"job_id": "job-a"},
    )
    assert scoped["passed"] is True
    assert scoped["n_runs"] == 2
    assert scoped["n_ledger"] == 2
    unscoped = reconcile_trial_coverage(
        ledger,
        ["job-a:iteration-01-experiment-01", "job-a:iteration-01-experiment-02"],
    )
    assert unscoped["passed"] is False
    assert unscoped["extras"] == ["job-b:iteration-01-experiment-01"]


def test_backtest_engine_seam_audit_detects_another_function_in_covered_module(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "quant_system"
    package_root.mkdir()
    (package_root / "same_module.py").write_text(
        """
def covered_entry():
    return BacktestEngine({})


def newly_added_entry():
    return BacktestEngine({})
""",
        encoding="utf-8",
    )

    callsites = enumerate_backtest_engine_callsites(package_root)

    assert callsites - {"quant_system.same_module:covered_entry"} == {
        "quant_system.same_module:newly_added_entry"
    }


def test_every_backtest_engine_callsite_is_enumerated_or_exempted() -> None:
    """Every exact constructor seam has a ledger entry or recorded exemption."""
    import importlib

    import quant_system

    root = Path(quant_system.__file__).resolve().parent
    engine_callsites = enumerate_backtest_engine_callsites(root)
    covered = set(BACKTEST_SHAPED_ENTRY_POINTS)
    exempt = set(BACKTEST_SHAPED_EXEMPTIONS)
    uncovered = engine_callsites - covered - exempt
    assert not uncovered, f"BacktestEngine callsites with no ledger story: {uncovered}"
    for dotted in BACKTEST_SHAPED_EXEMPTIONS:
        reason = BACKTEST_SHAPED_EXEMPTIONS[dotted]
        assert isinstance(reason, str) and len(reason) >= 40, dotted
        module_name, func_name = dotted.split(":")
        module = importlib.import_module(module_name)
        assert hasattr(module, func_name), dotted


def test_purpose_study_records_net_result_immediately_and_future_admission_does_not_count_twice(
    tmp_path,
    monkeypatch,
):
    import pandas as pd

    from quant_system.config.settings import Settings
    from quant_system.research import strategy_library
    from quant_system.research import strategy_study_service as studies

    settings = Settings()
    settings.data.data_dir = tmp_path
    profile = {
        "id": "ledger-fixture",
        "name": "Ledger fixture",
        "symbols": ["AAA"],
        "benchmark_symbol": "QQQ",
    }
    prices = pd.DataFrame(
        {"symbol": ["AAA"], "timestamp": pd.to_datetime(["2024-01-02"], utc=True)}
    )
    curve = [
        {
            "date": day.strftime("%Y-%m-%d"),
            "equity": 100000 + index * 13 + index % 3,
            "peer": 1_000_000,
            "benchmark": 900_000,
        }
        for index, day in enumerate(pd.date_range("2024-01-02", periods=25, freq="B"))
    ]
    net = {
        "status": "available",
        "profile": profile,
        "source": "futu",
        "price_adjustment": "qfq",
        "curve": curve,
        "metrics": {"sharpe": 0.5},
        "gross_metrics": {"sharpe": 99},
        "start": curve[0]["date"],
        "end": curve[-1]["date"],
    }
    monkeypatch.setattr(studies, "list_study_profiles", lambda: [profile])
    monkeypatch.setattr(
        studies, "_collect_prices", lambda *a: (prices, {"data_end": curve[-1]["date"]})
    )
    monkeypatch.setattr(studies, "run_profile", lambda *a, **k: net)
    monkeypatch.setattr(studies, "_diagnostics", lambda *a: None)
    report = studies.run_studies(settings)
    assert report["status"] == "ready"
    ledger = TrialsLedger(tmp_path / "trials")
    assert len(ledger.list()) == 1
    assert ledger.list()[0].total_return == pytest.approx(curve[-1]["equity"] / 100000 - 1)
    strategy_library._record_study_family(settings, ["AAA"])
    studies.run_studies(settings)
    assert len(ledger.list()) == 1


def test_reference_owner_records_each_net_hypothesis_but_not_benchmark_or_monthly_gross(
    tmp_path,
    monkeypatch,
):
    import pandas as pd

    from quant_system.config.settings import Settings
    from quant_system.research import evaluation_service as evaluation
    from quant_system.research import reference_backtests

    settings = Settings()
    settings.data.data_dir = tmp_path
    prices = pd.DataFrame(
        {"symbol": ["QQQ"], "timestamp": pd.to_datetime(["2024-01-02"], utc=True)}
    )
    features = pd.DataFrame(
        {"momentum": [1.0]},
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-02", tz="UTC"), "QQQ")], names=["datetime", "instrument"]
        ),
    )
    dates = pd.date_range("2024-01-02", periods=25, freq="B").strftime("%Y-%m-%d").tolist()
    one = {
        "key": "factor:momentum",
        "status": "available",
        "frequency": "daily",
        "source": "futu",
        "price_adjustment": "qfq",
        "daily_returns": [0.001, -0.002, 0.003, 0.004, -0.005] * 5,
        "return_dates": dates,
        "benchmark_daily_returns": [0.2] * 25,
    }
    monkeypatch.setattr(evaluation, "source_digest", lambda: "code")
    monkeypatch.setattr(
        evaluation,
        "prepare_prices",
        lambda *a: (prices, {"data_end": dates[-1], "prices_sha256": "price"}),
    )
    monkeypatch.setattr(reference_backtests, "compute_reference_features", lambda *a: features)
    monkeypatch.setattr(
        reference_backtests,
        "build_reference_backtests",
        lambda *a, **k: {
            "rows": [
                one,
                {"key": "strategy:monthly", "status": "available", "frequency": "monthly"},
                {"key": "strategy:draft", "status": "unavailable"},
            ],
            "benchmark": {"sharpe": 99},
        },
    )
    monkeypatch.setattr(evaluation, "_run_qlib", lambda *a: {"status": "ready", "comparisons": []})
    evaluation.refresh_evaluation(settings)
    rows = TrialsLedger(tmp_path / "trials").list()
    assert len(rows) == 3
    assert sum(not row.metadata.get("skipped", False) for row in rows) == 1
    assert next(row for row in rows if not row.metadata.get("skipped")).n_periods == 25


def test_rolling_trial_accounting_counts_enhanced_net_portfolio_once_and_audits_controls(tmp_path):
    from quant_system.config.settings import Settings
    from quant_system.research.evaluation_service import _record_evaluation_portfolios

    settings = Settings()
    settings.data.data_dir = tmp_path
    net = {
        "status": "available",
        "source": "futu",
        "price_adjustment": "qfq",
        "frequency": "daily",
        "daily_returns": [0.01, -0.005, 0.002],
        "return_dates": ["2024-01-02", "2024-01-03", "2024-01-04"],
    }
    case = {
        "baseline_features": ["momentum", "volatility", "liquidity"],
        "augmented_features": ["momentum", "volatility", "liquidity", "rsi"],
        "baseline": net,
        "augmented": net,
    }
    report = {
        "run_id": "first-run",
        "input_digest": "frozen-input",
        "source": {"universe": ["AAA"]},
        "rolling": {
            "baseline": net,
            "methodology": {"model": "ridge"},
            "comparisons": [case, case],
        },
    }
    _record_evaluation_portfolios(settings, report, rolling=True)
    report["run_id"] = "second-run"
    report["input_digest"] = "new-refresh-capture-digest"
    report["source"]["captured_at"] = "2030-01-01"
    _record_evaluation_portfolios(settings, report, rolling=True)
    rows = TrialsLedger(tmp_path / "trials").list()
    assert len(rows) == 2
    assert sum(row.metadata.get("skipped", False) for row in rows) == 1
    net["daily_returns"] = [0.9, 0.9, 0.9]
    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        _record_evaluation_portfolios(settings, report, rolling=True)
    assert len(TrialsLedger(tmp_path / "trials").list()) == 2


def test_discovery_rejected_training_results_are_recorded_before_they_disappear(
    tmp_path, monkeypatch
):
    import pandas as pd

    from quant_system.config.settings import Settings
    from quant_system.research import strategy_study_service as studies

    settings = Settings()
    settings.data.data_dir = tmp_path
    directory = tmp_path / "study-test"
    directory.mkdir()
    prices = pd.DataFrame(
        {"symbol": ["AAA"], "timestamp": pd.to_datetime(["2026-09-10"], utc=True)}
    )
    prices.to_parquet(directory / "prices.parquet")
    monkeypatch.setattr(studies, "_diagnostics", lambda *a, **k: None)
    monkeypatch.setattr(
        studies,
        "_training_facts",
        lambda *a, **k: {
            "training_end": "2026-09-10",
            "universe": ["AAA"],
            "factor_statistics": [],
        },
    )

    def proposals(path, *a, **k):
        studies._write(
            path / "proposals.json",
            {
                "status": "frozen",
                "proposals": [
                    {"id": "one", "status": "frozen", "expression": "$close", "title": "Test"}
                ],
            },
        )

    monkeypatch.setattr(studies, "_docker", proposals)
    net = {
        "status": "available",
        "source": "futu",
        "price_adjustment": "qfq",
        "profile": {"id": "rdagent:one", "symbols": ["AAA"]},
        "curve": [
            {"date": "2024-01-02", "equity": 100000},
            {"date": "2024-01-03", "equity": 99000},
        ],
        "start": "2024-01-02",
        "end": "2024-01-03",
    }
    monkeypatch.setattr(studies, "run_formula_profile", lambda *a, **k: net)
    monkeypatch.setattr(studies, "_signal_rejection", lambda *a: ("rejected in training", None))
    result = studies._discover(settings, directory, prices, [])
    assert result["results"] == [] and result["proposals"][0]["status"] == "rejected"
    rows = TrialsLedger(tmp_path / "trials").list()
    assert len(rows) == 1 and rows[0].total_return == pytest.approx(-0.01)


def test_trial_write_failure_stops_research_owner_before_qlib(monkeypatch, tmp_path):
    from quant_system.config.settings import Settings
    from quant_system.research.strategy_study_service import _record_study_result

    settings = Settings()
    settings.data.data_dir = tmp_path
    monkeypatch.setattr(
        TrialsLedger, "append", lambda *a: (_ for _ in ()).throw(OSError("write failed"))
    )
    with pytest.raises(OSError, match="write failed"):
        _record_study_result(
            settings,
            {"status": "failed", "profile": {"id": "test", "symbols": ["AAA"]}},
            "prices",
            attempt_id="attempt",
        )
