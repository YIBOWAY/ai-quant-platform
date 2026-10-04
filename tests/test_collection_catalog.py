import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import Settings
from quant_system.d34 import research_cli
from quant_system.d34.worker import D34WorkerResult
from quant_system.research import collection_catalog as catalog


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    result = Settings()
    result.data.data_dir = tmp_path
    monkeypatch.setattr(catalog, "project_book", lambda _: {"candidates": []})
    return result


def test_public_catalog_excludes_sample_performance_and_get_has_no_effects(settings, monkeypatch):
    path = settings.data.data_dir / "api_runs/backtests/sample-test/metadata.json"
    _write(
        path,
        {
            "status": "completed",
            "source": "sample",
            "run_id": "sample-test",
            "request": {
                "strategy_id": "cross_sectional_top_n",
                "factor_ids": ["momentum", "volatility"],
            },
            "metrics": {"sharpe": 19.01},
        },
    )
    monkeypatch.setattr(catalog, "RollupLlmClient", lambda **_: pytest.fail("GET called model"))
    client = TestClient(create_app(settings=settings, output_dir=settings.data.data_dir))
    before = {str(p): p.read_bytes() for p in settings.data.data_dir.rglob("*") if p.is_file()}
    response = client.get("/api/collection")
    assert response.status_code == 200
    result = response.json()
    assert result["excluded_sample_runs"] == 1
    assert len(result["items"]) == 11
    assert all(not item["evidence"] for item in result["items"])
    assert all("_source" not in item for item in result["items"])
    draft = next(item for item in result["items"] if "drift_regime" in item["id"])
    assert draft["implementation_status"] == "draft" and draft["links"] == []
    after = {str(p): p.read_bytes() for p in settings.data.data_dir.rglob("*") if p.is_file()}
    assert before == after


def test_real_strategy_run_not_assigned_to_component_factors(settings):
    _write(
        settings.data.data_dir / "api_runs/backtests/real-run/metadata.json",
        {
            "status": "completed",
            "source": "futu",
            "run_id": "real-run",
            "request": {"strategy_id": "cross_sectional_top_n", "factor_ids": ["momentum"]},
            "metrics": {"sharpe": 1.2},
        },
    )
    result = catalog.build_collection(settings)
    strategy = next(i for i in result["items"] if i["key"] == "strategy:cross_sectional_top_n")
    assert strategy["evidence"][0]["metrics"]["sharpe"] == 1.2
    assert strategy["evidence"][0]["status"] == "historical"
    assert all(not i["evidence"] for i in result["items"] if i["kind"] == "factor")


def test_factor_diagnostics_preserve_historical_scope_and_no_sample_means_unknown(settings):
    _write(
        settings.data.data_dir / "factor_lab/factor_lab_cache.json",
        {
            "source": "futu",
            "generated_at": "2026-08-17",
            "cache": {"key": {"start": "2024-01-02", "end": "2024-12-31"}},
            "cross_sectional": {
                "rows": [
                    {"factor_id": "momentum", "ic_mean": 0.02, "sample_count": 30, "coverage": 0.9},
                    {
                        "factor_id": "paper_reversal_momentum_proxy_v2",
                        "ic_mean": 0,
                        "sample_count": 0,
                        "coverage": 0,
                    },
                ]
            },
            "timing": {"rows": [{"factor_id": "momentum", "sharpe": 20}]},
        },
    )
    items = {i["key"]: i for i in catalog.build_collection(settings)["items"]}
    momentum = items["factor:momentum"]["evidence"][0]
    assert momentum["metrics"]["ic_mean"] == 0.02 and "sharpe" not in momentum["metrics"]
    assert momentum["status"] == "historical" and momentum["start"] == "2024-01-02"
    empty = items["factor:paper_reversal_momentum_proxy_v2"]["evidence"][0]
    assert empty["status"] == "unavailable" and empty["metrics"]["ic_mean"] is None


def _research_record(settings):
    job = settings.data.data_dir / "_runtime/d34/jobs/job-example"
    path = job / "research/research-example/candidate_factor.py"
    source = 'raise RuntimeError("must not execute")\nfactor_id = "factor-one"\n'
    path.parent.mkdir(parents=True)
    path.write_text(source)
    snapshot_digest = "b" * 64
    _write(
        job.parent.parent / "snapshots/snapshot-one/manifest.json",
        {
            "provider": "futu",
            "snapshot_digest": snapshot_digest,
        },
    )
    raw_paths = {}
    digests = {}
    for engine in ("qlib", "platform"):
        raw = {
            "engine": engine,
            "snapshot_id": "snapshot-one",
            "snapshot_digest": snapshot_digest,
            "return_dates": ["2024-01-02", "2024-01-03"],
            "metrics": {
                "sharpe": 1.1 if engine == "qlib" else 1.2,
                "max_drawdown": -0.2 if engine == "qlib" else 0.2,
            },
        }
        if engine == "qlib":
            raw["qlib_config"] = {"proposal": {"thesis": "long-short hypothesis"}, "top_k": 1}
        digests[engine] = catalog._digest(raw)
        raw_paths[engine] = (
            path.parent / "qlib_receipt.json"
            if engine == "qlib"
            else (job / "platform-replay/replay-one/receipt.json")
        )
        _write(raw_paths[engine], {**raw, "receipt_digest": digests[engine]})
    comparison = {
        "accepted": True,
        "qlib_receipt_digest": digests["qlib"],
        "platform_receipt_digest": digests["platform"],
        "daily_return_correlation": 0.999,
        "terminal_nav_difference_bps": 12,
    }
    comparison_digest = catalog._digest(comparison)
    recovery = {
        "candidate_code_digest": catalog._sha(source.encode()),
        "comparison": {**comparison, "comparison_digest": comparison_digest},
    }
    _write(
        job / "terminal_recovery.json", {**recovery, "recovery_digest": catalog._digest(recovery)}
    )
    return {
        "candidate_id": "artifact-example",
        "factor_id": "factor-one",
        "source_path": str(path),
        "source_digest": catalog._sha(source.encode()),
        "comparison_digest": comparison_digest,
        "status": "hung",
        "description_note": "历史DSR更正未通过，保留既有状态。",
    }, raw_paths


def test_research_uses_each_digest_bound_engine_and_never_executes_source(settings, monkeypatch):
    record, paths = _research_record(settings)
    monkeypatch.setattr(catalog, "project_book", lambda _: {"candidates": [record]})
    item = catalog.build_collection(settings)["items"][0]
    assert item["implementation_status"] == "implemented"
    assert item["simulation_status"] == "hung" and item["comparison"]["status"] == "accepted"
    assert [e["metrics"]["sharpe"] for e in item["evidence"]] == [1.1, 1.2]
    assert [e["metrics"]["max_drawdown"] for e in item["evidence"]] == [0.2, 0.2]
    assert item["notes"] == [record["description_note"]]
    explained = catalog._catalog(
        settings, settings.data.data_dir / "api_runs", settings.data.data_dir
    )["items"][0]
    assert "proposal" not in explained["_parameters"]
    assert "target_weight_builder_source" in explained["_parameters"]
    corrupted = json.loads(paths["qlib"].read_text())
    corrupted["metrics"]["sharpe"] = 999
    _write(paths["qlib"], corrupted)
    item = catalog.build_collection(settings)["items"][0]
    assert item["evidence"] == [] and item["comparison"]["status"] == "unavailable"
    source = record["source_path"]
    from pathlib import Path

    Path(source).write_text("factor_id='changed'")
    item = catalog.build_collection(settings)["items"][0]
    assert item["source_digest"] is None and item["implementation_status"] == "source_unavailable"


class LocalTestModel:
    model = "grok-4.6"
    reasoning_effort = "xhigh"

    def __init__(self):
        self.calls = []

    def _chat_json(self, messages):
        self.calls.append(messages)
        return {
            "summary": "这个因子根据过去一段时间的价格涨幅排序，可作为比较股票强弱的一个输入。",
            "logic": ["按股票分别比较窗口前后的收盘价。"],
            "usage": ["作为横截面选股的一个信号。"],
            "limitations": ["单个因子数值不是完整交易策略。"],
        }


def test_intro_uses_actual_code_and_parameters_and_invalidates_on_parameter_change(settings):
    item = catalog._catalog(settings, settings.data.data_dir / "api_runs", settings.data.data_dir)[
        "items"
    ][0]
    model = LocalTestModel()
    first = catalog.generate_introduction(settings, item, client=model)
    assert first["status"] == "ready" and first["model"] == "grok-4.6"
    assert first["reasoning_effort"] == "xhigh"
    supplied = json.loads(model.calls[0][1]["content"])
    assert "target_weights" in supplied["source_code"]
    assert supplied["parameters"]["top_n"] == 3
    catalog.generate_introduction(settings, item, client=model)
    assert len(model.calls) == 1
    item["_parameters"]["top_n"] = 5
    assert catalog._load_intro(settings, item)["status"] == "source_changed"
    second = catalog.generate_introduction(settings, item, client=model)
    assert len(model.calls) == 2 and second["input_digest"] != first["input_digest"]


def test_intro_failure_persists_visible_sanitized_error_and_unknown_keys_do_not_call(settings):
    class FailingModel(LocalTestModel):
        def _chat_json(self, _messages):
            raise RuntimeError("HTTP 502 private token and body")

    key = "factor:momentum"
    result = catalog.generate_catalog_introductions(settings, keys=[key], client=FailingModel())
    assert result == [{"key": key, "status": "failed", "error": "模型服务 HTTP 502"}]
    item = next(i for i in catalog.build_collection(settings)["items"] if i["key"] == key)
    assert item["intro"]["status"] == "failed"
    assert "private" not in json.dumps(item)
    with pytest.raises(ValueError, match="unknown_collection_key"):
        catalog.generate_catalog_introductions(
            settings, keys=["factor:missing"], client=FailingModel()
        )


def test_explicit_batch_keeps_each_source_bound_and_rejects_wrong_identity(settings):
    class BatchModel(LocalTestModel):
        def _chat_json(self, messages):
            self.calls.append(messages)
            facts = json.loads(messages[1]["content"])["items"]
            assert len(facts) == 4
            return {
                "items": [
                    {
                        "key": item["key"],
                        "summary": "这段测试说明绑定当前实现，不代表其他因子的信号或业绩。",
                        "logic": [item["name"] + "的实际逻辑"],
                        "usage": ["研究使用"],
                        "limitations": ["未验证的部分保持未知"],
                    }
                    for item in reversed(facts)
                ]
            }

    keys = ["factor:" + key for key in ("momentum", "volatility", "liquidity", "rsi")]
    client = BatchModel()
    results = catalog.generate_catalog_introductions(settings, keys=keys, client=client)
    assert len(client.calls) == 1 and all(row["status"] == "ready" for row in results)
    items = {item["key"]: item for item in catalog.build_collection(settings)["items"]}
    for key in keys:
        assert items[key]["intro"]["logic"] == [items[key]["name"] + "的实际逻辑"]
    catalog.generate_catalog_introductions(settings, keys=keys, client=client)
    assert len(client.calls) == 1


def test_draft_payload_cannot_execute_resident_placeholder():
    from quant_system.backtest.pipeline import _resolve_strategy_id
    from quant_system.strategies.registry import build_default_strategy_registry

    draft = build_default_strategy_registry().get("drift_regime_reversal_top_n_v1")
    assert draft.default_payload["strategy_id"] == draft.id
    assert draft.default_payload["factor_ids"] == ["drift_regime_reversal_edge_v1"]
    with pytest.raises(ValueError, match="not runnable"):
        _resolve_strategy_id(draft.default_payload["strategy_id"])


def test_replication_intro_includes_actual_score_and_portfolio_helpers(settings):
    items = catalog._catalog(settings, settings.data.data_dir / "api_runs", settings.data.data_dir)[
        "items"
    ]
    item = next(row for row in items if row["key"] == "strategy:reversal_momentum")
    assert "def _signal_frame" in item["_source"]
    assert "def _long_short_returns" in item["_source"]
    assert "def _zscore" in item["_source"]


def test_completed_worker_intro_failure_does_not_change_success_or_run_before_projection(
    settings,
    monkeypatch,
    capsys,
):
    calls = []
    monkeypatch.setattr(research_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        research_cli, "_project_terminal_research_results", lambda _: calls.append("project") or {}
    )
    monkeypatch.setattr(
        research_cli,
        "build_local_research_worker",
        lambda **_: SimpleNamespace(
            run_once=lambda: (
                calls.append("research")
                or D34WorkerResult(
                    status="candidate_ready", code="verified_candidate_not_hung", job_id="job-one"
                )
            )
        ),
    )

    def fail(_settings, job_id):
        calls.append("intro")
        assert job_id == "job-one"
        raise RuntimeError("unavailable")

    monkeypatch.setattr(catalog, "generate_completed_job_introduction", fail)
    assert research_cli.main([]) == 0
    assert calls == ["project", "research", "project", "intro"]
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "candidate_ready"
    assert result["introductions"] == [{"status": "failed", "error": "RuntimeError"}]
