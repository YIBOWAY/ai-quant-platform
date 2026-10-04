"""Read actual definition/validation files without executing or rewriting research."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import Settings
from quant_system.research import collection_catalog as catalog
from quant_system.research import evaluation_service, strategy_library
from quant_system.research.strategy_definition import StrategyDefinition
from quant_system.research.validation_receipts import file_sha, receipt_bindings


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    settings = Settings()
    settings.data.data_dir = tmp_path
    definition = StrategyDefinition(
        kind="formula",
        title="周频五日反转",
        symbols=("AAA", "BBB"),
        benchmark_symbol="SPY",
        history_start="2015-01-01",
        rebalance="weekly",
        top_n=1,
        formula={"expression": "-Mean($close/Ref($close,1)-1,5)"},
    )
    entry = strategy_library._save_definition(settings, definition, {})
    directory = tmp_path / "strategy_library" / entry["strategy_id"]
    run = directory / "validations" / ("validation-" + "a" * 32)
    run.mkdir(parents=True)
    (run / "prices.parquet").write_bytes(b"sealed price bytes; not executed")
    write = strategy_library._write
    platform = {
        "status": "available",
        "source": "futu",
        "price_adjustment": "qfq",
        "definition_digest": definition.content_digest,
        "definition": definition.model_dump(mode="json"),
        "start": "2024-01-02",
        "end": "2024-12-31",
        "metrics": {"sharpe": 0.8, "total_return": 0.2},
    }
    write(run / "platform-result.json", platform)
    sources = {
        name: file_sha(Path(strategy_library.__file__).with_name(name))
        for name in (
            "definition_qlib_replay.py",
            "strategy_signal_validation.py",
            "qlib_evaluation.py",
        )
    }
    source = {
        "prices_sha256": file_sha(run / "prices.parquet"),
        "platform_result_sha256": file_sha(run / "platform-result.json"),
        "replay_source_sha256": sources["definition_qlib_replay.py"],
    }
    write(
        run / "qlib-replay.json",
        {
            "status": "available",
            "definition_digest": definition.content_digest,
            "source": source,
            "metrics": {"sharpe": 0.81, "total_return": 0.201},
        },
    )
    write(
        run / "signal-analysis.json",
        {
            "status": "available",
            "definition_digest": definition.content_digest,
            "source": {
                "prices_sha256": source["prices_sha256"],
                "result_sha256": source["platform_result_sha256"],
                "validation_source_sha256": sources["strategy_signal_validation.py"],
                "fit_metrics_source_sha256": sources["qlib_evaluation.py"],
            },
        },
    )
    validation = {
        "status": "passed",
        "definition_digest": definition.content_digest,
        "run_id": run.name,
        "validated_at": "2024-12-31",
        "start": platform["start"],
        "end": platform["end"],
        "blockers": [],
        "comparison": {"accepted": True, "comparison_digest": "c" * 64},
        "receipts": receipt_bindings(run),
    }
    write(run / "validation.json", validation)
    record = {
        "candidate_id": "strategy-" + file_sha(run / "validation.json")[:24],
        "source": "strategy_definition",
        "source_path": str(directory / "definition.json"),
        "source_digest": entry["source_sha256"],
        "factor_id": "definition_" + definition.content_digest[:24],
        "universe": list(definition.symbols),
        "status": "verified",
        "display_name_zh": "重复旧名",
        "verification_receipt_digest": file_sha(run / "validation.json"),
        "comparison_digest": "c" * 64,
    }
    monkeypatch.setattr(catalog, "project_book", lambda _: {"candidates": [record]})
    monkeypatch.setattr(
        evaluation_service,
        "build_ohlcv_provider",
        lambda *a, **kw: pytest.fail("read fetched data"),
    )
    return settings, record, run


def test_definition_collection_binds_name_rule_and_own_engine_metrics(evidence):
    settings, record, run = evidence
    before = {str(p): p.read_bytes() for p in settings.data.data_dir.rglob("*") if p.is_file()}
    item = catalog.build_collection(settings)["items"][0]
    assert item["implementation_status"] == "implemented"
    assert item["name"] == "周频五日反转"
    assert "每周" in item["description"] and "1" in item["description"]
    assert [row["metrics"]["sharpe"] for row in item["evidence"]] == [0.81, 0.8]
    assert item["source_digest"] == record["source_digest"]
    assert any("strategy-library?strategy=" in link["href"] for link in item["links"])
    assert before == {
        str(p): p.read_bytes() for p in settings.data.data_dir.rglob("*") if p.is_file()
    }


def test_strategy_evaluation_get_is_exact_read_and_post_cannot_run_wrong_protocol(evidence):
    settings, record, _ = evidence
    client = TestClient(create_app(settings=settings, output_dir=settings.data.data_dir))
    response = client.get(
        "/api/research-evaluation", params={"key": "research:" + record["candidate_id"]}
    )
    assert response.status_code == 200
    assert response.json()["source"]["mode"] == "strategy_definition"
    assert response.json()["source"]["candidate_id"] == record["candidate_id"]
    assert response.json()["source"]["evidence"][1]["metrics"]["sharpe"] == 0.8
    with pytest.raises(ValueError, match="strategy_definition_requires_own_validation"):
        evaluation_service.refresh_evaluation(settings, "research:" + record["candidate_id"])


@pytest.mark.parametrize("damage", ["metrics", "identity", "receipt", "universe"])
def test_wrong_identity_or_tampered_results_never_supply_metrics(evidence, damage):
    settings, record, run = evidence
    if damage == "metrics":
        raw = json.loads((run / "platform-result.json").read_text())
        raw["metrics"]["sharpe"] = 999
        strategy_library._write(run / "platform-result.json", raw)
    elif damage == "identity":
        record["factor_id"] = "definition_" + "0" * 24
    elif damage == "receipt":
        record["verification_receipt_digest"] = "e" * 64
    else:
        record["universe"].reverse()
    item = catalog.build_collection(settings)["items"][0]
    assert not item["evidence"]
    assert item["comparison"]["status"] == "unavailable"


def test_old_unbound_receipt_keeps_rule_without_inventing_metrics(evidence):
    settings, record, _ = evidence
    record.pop("verification_receipt_digest")
    item = catalog.build_collection(settings)["items"][0]
    assert item["name"] == "周频五日反转"
    assert item["implementation_status"] == "implemented"
    assert not item["evidence"]


def test_legacy_schema_keeps_bound_title_but_does_not_invent_required_history(evidence):
    settings, record, _ = evidence
    path = Path(record["source_path"])
    raw = json.loads(path.read_text())
    raw.pop("history_start")
    strategy_library._write(path, raw)
    record["source_digest"] = file_sha(path)
    item = catalog.build_collection(settings)["items"][0]
    assert item["name"] == "周频五日反转"
    assert item["implementation_status"] == "source_unavailable"
    assert not item["evidence"]
    assert "history_start" not in json.loads(path.read_text())


def test_reading_historical_evidence_never_weakens_current_activation_check(evidence, monkeypatch):
    from quant_system.research import definition_catalog, validation_receipts

    settings, record, run = evidence
    original = validation_receipts.receipt_bindings
    monkeypatch.setattr(
        validation_receipts,
        "receipt_bindings",
        lambda directory: {**original(directory), "sources": {"new_executor": "changed"}},
    )
    monkeypatch.setattr(definition_catalog, "current_source_fingerprints", lambda definition: {})
    item = catalog.build_collection(settings)["items"][0]
    assert all(row["status"] == "historical" for row in item["evidence"])
    assert any("当前执行代码与冻结版本不同" in note for note in item["notes"])
    with pytest.raises(ValueError, match="inputs_or_code_changed"):
        validation_receipts.verify_validation_receipt(
            run / "validation.json",
            expected_sha=record["verification_receipt_digest"],
            definition_digest=json.loads((run / "validation.json").read_text())[
                "definition_digest"
            ],
        )


def test_definition_refresh_api_does_not_launch_legacy_factor_evaluation(evidence, monkeypatch):
    from quant_system.api.dependencies import require_mutation_security
    from quant_system.api.routes import research_evaluation as route

    settings, record, _ = evidence
    monkeypatch.setattr(route, "refresh_evaluation", lambda *a: pytest.fail("wrong protocol"))
    app = create_app(settings=settings, output_dir=settings.data.data_dir)
    app.dependency_overrides[require_mutation_security] = lambda: None
    response = TestClient(app).post(
        "/api/research-evaluation/refresh", json={"key": "research:" + record["candidate_id"]}
    )
    assert response.status_code == 409
    assert "自己的持仓与调仓规则" in response.json()["detail"]
