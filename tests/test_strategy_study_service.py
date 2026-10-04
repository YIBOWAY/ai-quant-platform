"""Sealed orchestration tests; no market provider, model, or account writes."""

import json
import subprocess
from datetime import UTC, datetime

import pandas as pd
import pytest

from quant_system.config.settings import load_settings
from quant_system.research import strategy_study_service as service
from quant_system.research.study_signal_diagnostics import monthly_pairs


def test_monthly_labels_use_entry_opens_and_do_not_bridge_a_missing_month():
    prices = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2021-12-01", "2022-01-03", "2022-03-01"], utc=True),
            "symbol": ["AAA"] * 3,
            "open": [100, 110, 150],
            "close": [999] * 3,
        }
    )
    signals = [
        {"signal_date": s, "trade_date": t, "scores": [{"symbol": "AAA", "score": 2}]}
        for s, t in [
            ("2021-11-30", "2021-12-01"),
            ("2021-12-31", "2022-01-03"),
            ("2022-02-28", "2022-03-01"),
        ]
    ]
    pairs = monthly_pairs(prices, {"signals": signals})
    assert len(pairs) == 1
    assert pairs.iloc[0].label == pytest.approx(0.1)
    assert pairs.iloc[0].label_end == "2022-01-03"
    assert pairs.iloc[0].datetime == "2021-11-30"


def test_discovery_input_uses_only_training_metrics():
    result = {
        "profile": {"id": "stocks_momentum_12_2"},
        "status": "available",
        "metrics": {"sharpe": 999},
        "splits": {"train": {"metrics": {"sharpe": 0.3}}, "test": {"metrics": {"sharpe": 999}}},
        "signal_diagnostics": {
            "splits": {"train": {"rank_ic": 0.02, "samples": 12}, "test": {"rank_ic": 999}}
        },
    }
    facts = service._training_facts([result], ["AAA"])
    assert facts["training_end"] == "2021-12-31"
    assert facts["factor_statistics"][0]["sharpe"] == 0.3
    assert facts["factor_statistics"][0]["rank_ic"] == 0.02
    assert "999" not in json.dumps(facts)


def _training(scores):
    return {
        "status": "available",
        "signals": [
            {
                "signal_date": "2021-01-31",
                "scores": [
                    {"symbol": s, "score": v}
                    for s, v in zip(["AAA", "BBB", "CCC"], scores, strict=True)
                ],
            }
        ],
    }


def test_formula_check_rejects_missing_constant_and_equivalent_rankings():
    assert service._signal_rejection(_training([None] * 3), [])[0]
    assert service._signal_rejection(_training([2] * 3), [])[0]
    reason, ranks = service._signal_rejection(_training([1, 2, 3]), [])
    assert reason is None
    assert service._signal_rejection(_training([20, 40, 60]), [ranks])[0]
    assert service._signal_rejection(_training([3, 2, 1]), [ranks])[0] is None


def test_get_is_read_only_and_invalidates_changed_math(tmp_path, monkeypatch):
    settings = load_settings()
    settings.data.data_dir = tmp_path
    assert service.read_studies(settings)["status"] == "not_started"
    assert not service._root(settings).exists()
    path = service._root(settings) / "latest.json"
    service._write(path, {**service._empty(), "status": "ready", "calculation_digest": "old"})
    before = path.read_bytes()
    monkeypatch.setattr(service, "calculation_digest", lambda: "new")
    assert service.read_studies(settings)["status"] == "stale"
    assert path.read_bytes() == before


def test_first_run_preserves_completed_studies_when_qlib_fails(tmp_path, monkeypatch):
    settings = load_settings()
    settings.data.data_dir = tmp_path
    profile = {"id": "test", "name": "test", "symbols": ["AAA"], "benchmark_symbol": "QQQ"}
    prices = pd.DataFrame(
        {"symbol": ["AAA"], "timestamp": pd.to_datetime(["2021-01-04"], utc=True)}
    )
    monkeypatch.setattr(service, "list_study_profiles", lambda: [profile])
    monkeypatch.setattr(service, "_collect_prices", lambda *a: (prices, {"data_end": "2021-01-04"}))
    monkeypatch.setattr(
        service,
        "run_profile",
        lambda *a, **k: {"status": "available", "profile": profile, "metrics": {"sharpe": 0.3}},
    )

    def fail(*args):
        raise RuntimeError("container_failed")

    monkeypatch.setattr(service, "_diagnostics", fail)
    monkeypatch.setattr(service, "_discover", lambda *a: pytest.fail("unexpected model call"))
    result = service.run_studies(settings)
    assert result["status"] == "partial"
    assert result["results"][0]["metrics"]["sharpe"] == 0.3
    assert (service._root(settings) / "runs" / result["run_id"] / "protocol.json").is_file()
    assert not (tmp_path / "agent_run").exists()


def test_missing_symbol_is_recorded_not_substituted(tmp_path, monkeypatch):
    settings = load_settings()
    settings.data.data_dir = tmp_path

    class Provider:
        def fetch_ohlcv(self, symbols, **kwargs):
            if symbols == ["BBB"]:
                raise RuntimeError("provider unavailable")
            return pd.DataFrame(
                {
                    "symbol": ["AAA"],
                    "timestamp": pd.to_datetime(["2021-01-04"], utc=True),
                    "open": [10.0],
                    "provider": ["futu"],
                    "price_adjustment": ["qfq"],
                }
            )

    monkeypatch.setattr(service, "build_ohlcv_provider", lambda *a, **k: (Provider(), "futu"))
    frame, source = service._collect_prices(settings, ["AAA", "BBB"], "2021-01-04")
    assert set(frame.symbol) == {"AAA"}
    assert source["unavailable_symbols"] == {"BBB": "RuntimeError"}

    # A verified identical request may reuse AAA; a different end must fetch it.
    class Unavailable:
        def fetch_ohlcv(self, *a, **k):
            raise RuntimeError("offline")

    monkeypatch.setattr(service, "build_ohlcv_provider", lambda *a, **k: (Unavailable(), "futu"))
    assert len(service._collect_prices(settings, ["AAA"], "2021-01-04")[0]) == 1
    with pytest.raises(ValueError, match="no_real_prices"):
        service._collect_prices(settings, ["AAA"], "2021-01-05")


def test_data_only_refresh_retains_but_dates_previous_hypotheses(tmp_path, monkeypatch):
    settings = load_settings()
    settings.data.data_dir = tmp_path
    profile = {"id": "test", "name": "test", "symbols": ["AAA"], "benchmark_symbol": "QQQ"}
    prices = pd.DataFrame(
        {"symbol": ["AAA"], "timestamp": pd.to_datetime(["2021-01-04"], utc=True)}
    )
    monkeypatch.setattr(service, "list_study_profiles", lambda: [profile])
    monkeypatch.setattr(service, "_collect_prices", lambda *a: (prices, {"data_end": "2021-01-04"}))
    monkeypatch.setattr(
        service, "run_profile", lambda *a, **k: {"profile": profile, "status": "available"}
    )
    monkeypatch.setattr(service, "_diagnostics", lambda *a: None)
    monkeypatch.setattr(service, "_discover", lambda *a: pytest.fail("unexpected model call"))
    service._write(
        service._root(settings) / "latest.json",
        {
            **service._empty(),
            "status": "ready",
            "calculation_digest": "previous",
            "discovery": {"status": "frozen", "proposals": [{"id": "saved"}]},
        },
    )
    result = service.run_studies(settings)
    assert result["status"] == "ready"
    assert result["discovery"]["proposals"] == [{"id": "saved"}]
    assert result["discovery"]["evaluation_status"] == "stale"


def test_docker_uses_local_stack_executable_without_interactive_path(tmp_path, monkeypatch):
    executable = tmp_path / "docker"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    monkeypatch.setenv("QS_LOCAL_DOCKER_BIN", str(executable))
    commands = []
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda command, **kw: commands.append(command) or subprocess.CompletedProcess(command, 0),
    )
    service._docker(tmp_path, "quant_system.research.study_signal_diagnostics", [])
    assert commands[0][0] == str(executable)


def test_failed_refresh_retains_archived_discovery_and_original_provenance(tmp_path, monkeypatch):
    settings = load_settings()
    settings.data.data_dir = tmp_path
    prior = {
        **service._empty(),
        "status": "ready",
        "run_id": "study-original",
        "updated_at": "2026-09-07T09:21:12+00:00",
        "calculation_digest": "old",
        "source": {"prices_sha256": "old-prices"},
        "discovery": {
            "status": "frozen",
            "generated_at": "2026-09-07T09:19:23+00:00",
            "proposals": [{"id": "saved"}],
            "results": [],
        },
    }
    service._write(service._root(settings) / "runs" / "study-original" / "report.json", prior)
    service._write(
        service._root(settings) / "latest.json", {**service._empty(), "status": "partial"}
    )
    profile = {"id": "test", "name": "test", "symbols": ["AAA"], "benchmark_symbol": "QQQ"}
    prices = pd.DataFrame(
        {"symbol": ["AAA"], "timestamp": pd.to_datetime(["2021-01-04"], utc=True)}
    )
    monkeypatch.setattr(service, "list_study_profiles", lambda: [profile])
    monkeypatch.setattr(service, "_collect_prices", lambda *a: (prices, {"data_end": "2021-01-04"}))
    monkeypatch.setattr(
        service, "run_profile", lambda *a, **k: {"profile": profile, "status": "available"}
    )

    def fail(*args):
        raise FileNotFoundError(2, "No such file or directory", "docker")

    monkeypatch.setattr(service, "_diagnostics", fail)
    monkeypatch.setattr(service, "_discover", lambda *a: pytest.fail("unexpected model call"))
    result = service.run_studies(settings, include_discovery=True)
    assert result["status"] == "partial"
    assert result["discovery"]["proposals"] == [{"id": "saved"}]
    assert result["discovery"]["origin_run_id"] == "study-original"
    assert result["discovery"]["generated_at"] == prior["discovery"]["generated_at"]
    assert result["discovery"]["evaluated_at"] == prior["updated_at"]
    assert result["discovery"]["evaluation_status"] == "stale"
    assert result["stages"]["signal_diagnostics"]["status"] == "failed"
    assert "Qlib" in result["error"] and "docker" in result["error"]


def test_summary_recovers_archived_discovery_read_only(tmp_path):
    settings = load_settings()
    settings.data.data_dir = tmp_path
    report = {
        **service._empty(),
        "run_id": "study-old",
        "status": "ready",
        "updated_at": "2026-09-07T09:21:12+00:00",
        "calculation_digest": service.calculation_digest(),
        "discovery": {"status": "frozen", "proposals": [{"id": "saved"}]},
    }
    service._write(service._root(settings) / "runs" / "study-old" / "report.json", report)
    latest = service._root(settings) / "latest.json"
    service._write(latest, {**service._empty(), "status": "partial"})
    before = latest.read_bytes()
    assert service.read_studies(settings)["discovery"]["origin_run_id"] == "study-old"
    assert latest.read_bytes() == before


def test_old_discovery_time_uses_its_origin_report_completion_without_writes(tmp_path):
    settings = load_settings()
    settings.data.data_dir = tmp_path
    generated = "2026-09-09T03:10:04.436481+00:00"
    incorrect = "2026-09-09T03:09:56.983387+00:00"
    completed = "2026-09-09T03:11:46.075112+00:00"
    original = {
        **service._empty(),
        "run_id": "study-origin",
        "status": "ready",
        "updated_at": completed,
        "calculation_digest": service.calculation_digest(),
        "discovery": {
            "status": "frozen",
            "proposals": [{"id": "saved"}],
            "origin_run_id": "study-origin",
            "generated_at": generated,
            "evaluated_at": incorrect,
        },
    }
    path = service._root(settings) / "runs" / "study-origin" / "report.json"
    service._write(path, original)
    inherited = {**original, "run_id": "study-newer", "updated_at": "2026-09-10T06:00:00+00:00"}
    latest = service._root(settings) / "latest.json"
    service._write(latest, inherited)
    before = {p: p.read_bytes() for p in (path, latest)}
    for projected in (
        service.read_studies(settings),
        service.read_studies(settings, "study-origin"),
    ):
        assert projected["discovery"]["evaluated_at"] == completed
        assert projected["discovery"]["generated_at"] == generated
        assert projected["discovery"]["origin_run_id"] == "study-origin"
    assert all(p.read_bytes() == content for p, content in before.items())


def test_new_discovery_records_completion_after_generation(tmp_path, monkeypatch):
    settings = load_settings()
    settings.data.data_dir = tmp_path
    profile = {"id": "test", "name": "test", "symbols": ["AAA"], "benchmark_symbol": "QQQ"}
    prices = pd.DataFrame(
        {"symbol": ["AAA"], "timestamp": pd.to_datetime(["2021-01-04"], utc=True)}
    )
    monkeypatch.setattr(service, "list_study_profiles", lambda: [profile])
    monkeypatch.setattr(service, "_collect_prices", lambda *a: (prices, {"data_end": "2021-01-04"}))
    monkeypatch.setattr(
        service, "run_profile", lambda *a, **k: {"profile": profile, "status": "available"}
    )
    monkeypatch.setattr(service, "_diagnostics", lambda *a: None)
    monkeypatch.setattr(
        service,
        "_discover",
        lambda *a: {
            "status": "frozen",
            "generated_at": datetime.now(UTC).isoformat(),
            "proposals": [{"id": "saved"}],
            "results": [],
        },
    )
    result = service.run_studies(settings, include_discovery=True)
    discovery = result["discovery"]
    assert discovery["generated_at"] <= discovery["evaluated_at"] <= result["updated_at"]


def test_profile_detail_keeps_history_filters_exact_signal_and_reconciles(tmp_path):
    settings = load_settings()
    settings.data.data_dir = tmp_path
    directory = service._root(settings) / "runs" / "study-test"
    directory.mkdir(parents=True)
    prices = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2021-01-04", "2021-02-01"], utc=True),
            "symbol": ["AAA"] * 2,
            "close": [12.0, 13.0],
        }
    )
    prices.to_parquet(directory / "prices.parquet", index=False)
    signals = [
        {
            "signal_date": "2020-12-31",
            "trade_date": "2021-01-04",
            "scores": [{"symbol": "AAA", "score": 2}],
            "targets": {"AAA": 1},
        },
        {
            "signal_date": "2021-01-29",
            "trade_date": "2021-02-01",
            "scores": [{"symbol": "AAA", "score": 3}],
            "targets": {},
        },
    ]
    trades = [
        {
            "date": "2021-01-04",
            "symbol": "AAA",
            "side": "buy",
            "quantity": 10,
            "fill_price": 10,
            "commission": 1,
        },
        {
            "date": "2021-02-01",
            "symbol": "AAA",
            "side": "sell",
            "quantity": 10,
            "fill_price": 13,
            "commission": 1,
        },
    ]
    report = {
        **service._empty(),
        "run_id": "study-test",
        "status": "ready",
        "calculation_digest": service.calculation_digest(),
        "source": {
            "provider": "futu",
            "prices_sha256": service._file_hash(directory / "prices.parquet"),
        },
        "results": [
            {
                "profile": {"id": "test"},
                "status": "available",
                "signals": signals,
                "trades": trades,
                "curve": [
                    {"date": "2021-01-04", "equity": 100019},
                    {"date": "2021-02-01", "equity": 100028},
                ],
            }
        ],
    }
    service._write(directory / "report.json", report)
    detail = service.read_study_profile(settings, "study-test", "test", signal_date="2020-12-31")
    assert detail["signal_dates"] == ["2020-12-31", "2021-01-29"]
    assert detail["signals"] == signals[:1] and detail["trades"] == trades[:1]
    assert detail["reconciliation"]["status"] == "matched"
    assert detail["reconciliation"]["cash"] == 99899
    assert detail["reconciliation"]["market_value"] == 120
    assert service.read_study_profile(settings, "study-test", "test")["trades"] == trades
    with pytest.raises(KeyError):
        service.read_study_profile(settings, "study-test", "test", signal_date="2020-01-01")
    with pytest.raises(ValueError):
        service.read_study_profile(settings, "../escape", "test")


def test_recover_only_saved_diagnostics_without_data_or_model_work(tmp_path, monkeypatch):
    settings = load_settings()
    settings.data.data_dir = tmp_path
    directory = service._root(settings) / "runs" / "study-saved"
    directory.mkdir(parents=True)
    pd.DataFrame({"symbol": ["AAA"]}).to_parquet(directory / "prices.parquet", index=False)
    report = {
        **service._empty(),
        "status": "partial",
        "run_id": "study-saved",
        "updated_at": "2026-09-09T01:50:18+00:00",
        "calculation_digest": "original-math",
        "source": {"prices_sha256": service._file_hash(directory / "prices.parquet")},
        "error": "研究未完整完成：FileNotFoundError",
        "results": [{"profile": {"id": "test"}, "status": "available", "metrics": {"sharpe": 0.3}}],
    }
    service._write(directory / "report.json", report)
    service._write(service._root(settings) / "latest.json", report)
    monkeypatch.setattr(service, "_collect_prices", lambda *a: pytest.fail("unexpected fetch"))
    monkeypatch.setattr(service, "run_profile", lambda *a, **k: pytest.fail("unexpected backtest"))
    monkeypatch.setattr(service, "_discover", lambda *a: pytest.fail("unexpected model"))
    monkeypatch.setattr(
        service,
        "_diagnostics",
        lambda d, p, r: r[0].update(signal_diagnostics={"engine": "Qlib calc_ic"}),
    )
    recovered = service.recover_study_diagnostics(settings, "study-saved")
    assert recovered["run_id"] == "study-saved"
    assert recovered["results"][0]["metrics"] == {"sharpe": 0.3}
    assert recovered["results"][0]["signal_diagnostics"]["engine"] == "Qlib calc_ic"
    assert recovered["calculation_digest"] == "original-math"
    assert recovered["error"] is None
    assert recovered["recovery"]["previous_updated_at"] == report["updated_at"]
