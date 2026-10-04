"""Artificial sealed panels for receipt binding; not evidence of market returns."""

import json
from pathlib import Path
from types import SimpleNamespace

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from quant_system.research import external_intake as intake
from quant_system.research import intake_factor_evaluation as bridge
from quant_system.research.intake_evaluation import digest, file_hash
from quant_system.research.strategy_definition import StrategyDefinition, formula_factor_id


def proposal():
    return intake.Proposal.model_validate(
        {
            "schema_version": 1,
            "proposal_id": "sealed-scorecard",
            "source_urls": ["https://example.org/sealed-fixture"],
            "source_title": "artificial",
            "published_at": None,
            "retrieved_at": "2025-04-01T00:00:00Z",
            "hypothesis": "Artificial test only",
            "adaptation_note": "Not real market data",
            "expression": "$close/Ref($close,5)-1",
            "baseline_factor_ids": ["momentum"],
            "increment_objective": {
                "metric": "sharpe",
                "minimum_improvement": 0.1,
                "max_regressions": {},
            },
        }
    )


def frozen_job(tmp_path):
    p = proposal()
    identifier = formula_factor_id(p.expression)
    symbols = [f"S{i}" for i in range(12)]
    factors = [{"factor_id": "momentum", "lookback": 20, "direction": "higher_is_better"}]
    new = {
        "factor_id": identifier,
        "expression": p.expression,
        "lookback": 6,
        "direction": "higher_is_better",
    }
    plans = []
    for variant, components in (("baseline", factors), ("augmented", [*factors, new])):
        definition = StrategyDefinition(
            kind="factor_blend",
            title="artificial",
            symbols=symbols,
            history_start="2024-11-01",
            factors=components,
        )
        plans.append(
            {
                "variant": variant,
                "activation_eligible": variant == "augmented",
                "history_start": definition.history_start,
                "strategy_id": "strategy-" + definition.content_digest[:24],
                "definition_digest": definition.content_digest,
                "payload": definition.model_dump(mode="json", exclude={"history_start"}),
                "origin": {"start": "2024-12-01", "end": "2025-03-31"},
            }
        )
    job = {
        "job_id": "intake-" + "b" * 24,
        "proposal_id": p.proposal_id,
        "proposal": p.model_dump(mode="json"),
        "payload_sha256": intake._sha(p.model_dump(mode="json")),
        "plans": plans,
        "plans_sha256": intake._sha(plans),
        "formula_factor_id": identifier,
        "results": [],
        "created_at": "2025-04-01T00:00:00Z",
    }
    job["research_design"] = bridge.freeze_research_design(p, plans)
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    directory = tmp_path / "research_intake" / "evaluations" / job["job_id"]
    directory.mkdir(parents=True)
    days = xcals.get_calendar("XNYS").sessions_in_range("2024-11-01", "2025-03-31")
    rng = np.random.default_rng(3101)
    rows = []
    for symbol in [*symbols, "SPY"]:
        prices = 100 * np.exp(np.cumsum(rng.normal(0.0001, 0.015, len(days))))
        for day, price in zip(days, prices, strict=True):
            rows.append(
                {
                    "timestamp": day,
                    "symbol": symbol,
                    "open": price * 0.999,
                    "high": price * 1.01,
                    "low": price * 0.99,
                    "close": price,
                    "volume": 100000.0,
                    "provider": "futu",
                    "price_adjustment": "qfq",
                    "evidence_kind": "artificial_sealed_fixture",
                }
            )
    path = directory / "prices.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    evaluation = {
        "job_id": job["job_id"],
        "plans_sha256": job["plans_sha256"],
        "prices_path": str(path),
        "prices_sha256": file_hash(path),
        "start": "2024-12-01",
        "end": "2025-03-31",
        "cash": 10000,
    }
    evaluation["evaluation_id"] = "evaluation-" + digest(evaluation)
    job["evaluation"] = evaluation
    return settings, job


@pytest.fixture
def evaluated(tmp_path):
    settings, job = frozen_job(tmp_path)
    job["factor_evaluation"] = bridge.ensure_factor_evaluation(settings, job)
    return settings, job


def test_reuses_real_scorecard_and_keeps_factor_and_portfolio_meanings(evaluated):
    settings, job = evaluated
    card = job["factor_evaluation"]["summary"]
    assert card["status"] in {"ready", "partial"}
    assert set(card["horizons"]) == {"1", "5", "21"}
    assert card["horizons"]["1"]["ic"]["n_days"] > 50
    assert card["horizons"]["1"]["quantiles"]["n_days"] > 50
    assert card["stability"]["status"] == "ready"
    assert {y["year"] for y in card["stability"]["by_year"]} == {2024, 2025}
    assert card["redundancy"]["n_peers"] == 1
    assert card["performance_scope"] == "factor_prediction_and_group_labels_not_portfolio_profit"
    receipt = bridge._read_receipt(settings, job)
    assert receipt["identity"]["prices_sha256"] == job["evaluation"]["prices_sha256"]
    assert receipt["admission_authority"] is False
    assert bridge.ensure_factor_evaluation(settings, job) == job["factor_evaluation"]


@pytest.mark.parametrize("tamper", ["prices", "plan", "receipt", "artifact"])
def test_changed_input_identity_or_artifact_never_reuses_scores(evaluated, tamper):
    settings, job = evaluated
    if tamper == "prices":
        Path(job["evaluation"]["prices_path"]).write_bytes(b"changed fixture")
    elif tamper == "plan":
        job["plans_sha256"] = "0" * 64
    elif tamper == "receipt":
        Path(job["factor_evaluation"]["path"]).write_text("{}")
    else:
        (Path(job["factor_evaluation"]["path"]).parent / "factor_values.parquet").write_bytes(
            b"changed"
        )
    with pytest.raises(ValueError, match="changed"):
        bridge.ensure_factor_evaluation(settings, job)


def test_missing_real_field_is_not_evaluated_and_never_becomes_a_proxy(tmp_path):
    settings, job = frozen_job(tmp_path)
    path = Path(job["evaluation"]["prices_path"])
    pd.read_parquet(path).drop(columns="open").to_parquet(path, index=False)
    job["evaluation"]["prices_sha256"] = file_hash(path)
    job["evaluation"].pop("evaluation_id")
    job["evaluation"]["evaluation_id"] = "evaluation-" + digest(job["evaluation"])
    result = bridge.ensure_factor_evaluation(settings, job)
    assert result["summary"]["status"] == "not_evaluated"
    assert result["summary"]["horizons"] == {}


def test_read_projects_verified_receipt_and_tamper_without_writes(evaluated):
    settings, job = evaluated
    directory = settings.data.data_dir / "research_intake" / "jobs"
    directory.mkdir()
    (directory / (job["job_id"] + ".json")).write_text(json.dumps(job))
    before = {str(p): p.read_bytes() for p in settings.data.data_dir.rglob("*") if p.is_file()}
    result = bridge.research_evidence_for_strategy(settings, job["plans"][1]["strategy_id"])
    assert result["job_id"] == job["job_id"] and result["variant"] == "augmented"
    assert result["factor_evaluation"]["horizons"]
    assert before == {
        str(p): p.read_bytes() for p in settings.data.data_dir.rglob("*") if p.is_file()
    }
    Path(job["factor_evaluation"]["path"]).write_text("{}")
    result = bridge.research_evidence_for_strategy(settings, job["plans"][1]["strategy_id"])
    assert result["factor_evaluation"]["reason"] == "factor_receipt_integrity_failed"
    assert "horizons" not in result["factor_evaluation"]


def test_missing_historic_scorecard_and_undeclared_method_remain_explicit(tmp_path):
    _, job = frozen_job(tmp_path)
    chain = bridge.evaluation_chain(job)
    assert chain["factor_evaluation"]["status"] == "not_evaluated"
    design = chain["research_design"]
    assert design["source_method_status"] == "original_method_not_verified"
    assert {"symbols", "rebalance", "top_n"}.issubset(design["inherited_defaults"])
    assert design["data_needs"][0]["reason"] == "original_method_contract_not_supplied"
    p = proposal().model_copy(
        update={"strategy_spec": intake.StrategySpec(rebalance="weekly", top_n=3)}
    )
    explicit = bridge.freeze_research_design(p, job["plans"])
    assert "rebalance" not in explicit["inherited_defaults"]
    assert "symbols" in explicit["inherited_defaults"]


def test_algorithm_change_is_diagnosed_and_does_not_reuse_old_qualification(tmp_path, monkeypatch):
    settings, job = frozen_job(tmp_path)
    from quant_system.research import strategy_definition

    original = strategy_definition.current_source_fingerprints

    def changed(definition):
        return {**original(definition), "research/strategy_runtime.py": "f" * 64}

    monkeypatch.setattr(strategy_definition, "current_source_fingerprints", changed)
    result = bridge.ensure_factor_evaluation(settings, job)
    assert result["summary"]["status"] == "not_evaluated"
    assert result["summary"]["reason"] == "strategy_algorithm_source_mismatch"
    assert bridge.evaluation_chain(job)["admission"]["factor_scorecard_grants_authority"] is False


def test_changed_pair_definition_cannot_claim_increment_for_frozen_job(tmp_path):
    _, job = frozen_job(tmp_path)
    from quant_system.research.intake_evaluation import compare_increment

    for plan in job["plans"]:
        job["results"].append(
            {
                "variant": plan["variant"],
                "definition_digest": plan["definition_digest"],
                "evaluation": job["evaluation"],
                "evaluation_calendar_digest": "same_calendar",
                "validation": {
                    "definition_digest": plan["definition_digest"],
                    "start": "2024-12-01",
                    "end": "2025-03-31",
                    "comparison": {"accepted": True},
                    "platform_metrics": {"sharpe": 1 if plan["variant"] == "baseline" else 2},
                },
            }
        )
    assert compare_increment(job)["passed"] is True
    job["results"][1]["validation"]["definition_digest"] = "unrelated_definition"
    assert compare_increment(job)["reason"] == "intake_pair_not_comparable"


def test_replacement_revalidates_new_baseline_and_preserves_old_identity(tmp_path, monkeypatch):
    _, job = frozen_job(tmp_path)
    from quant_system.research import strategy_definition

    original = strategy_definition.current_source_fingerprints
    old = StrategyDefinition(history_start="2024-11-01", **job["plans"][0]["payload"])
    target = {
        "definition": old.model_dump(mode="json"),
        "source_sha256": "a" * 64,
        "replacement_target": {
            "candidate_id": "old-candidate",
            "definition_digest": old.content_digest,
        },
    }
    old_bytes = json.dumps(target, sort_keys=True)
    monkeypatch.setattr(
        strategy_definition,
        "current_source_fingerprints",
        lambda definition: {
            **original(definition),
            "research/strategy_runtime.py": "a" * 64,
        },
    )
    plans, _ = intake._replacement_plans(proposal(), job["job_id"], job["payload_sha256"], target)
    assert json.dumps(target, sort_keys=True) == old_bytes
    assert plans[0]["definition_digest"] != old.content_digest
    assert plans[0]["payload"]["factors"] == old.model_dump(mode="json")["factors"]
    assert plans[0]["origin"]["baseline_revalidation"]["historical_validation_reused"] is False
    assert (
        plans[0]["origin"]["baseline_revalidation"]["original_definition_digest"]
        == old.content_digest
    )
    assert plans[0]["origin"]["replacement_target"] == target["replacement_target"]
    for plan in plans:
        strategy_definition.validate_definition(
            StrategyDefinition(
                history_start=plan["history_start"],
                **plan["payload"],
            )
        )


def test_replacement_cannot_ignore_a_changed_factor_implementation(tmp_path, monkeypatch):
    _, job = frozen_job(tmp_path)
    from quant_system.research import strategy_definition

    target = {
        "definition": StrategyDefinition(
            history_start="2024-11-01",
            **job["plans"][0]["payload"],
        ).model_dump(mode="json"),
        "replacement_target": {"candidate_id": "old"},
    }
    original = strategy_definition._factor_identity
    monkeypatch.setattr(
        strategy_definition, "_factor_identity", lambda *a, **k: (original(*a, **k)[0], "b" * 64)
    )
    with pytest.raises(ValueError, match="source"):
        intake._replacement_plans(proposal(), job["job_id"], job["payload_sha256"], target)


def hypothesis_card(required_fields=None):
    import hashlib

    body = {name: "Existing source card 原方法" for name in bridge.CARD_FIELDS}
    body.update(required_fields=required_fields or ["close"], data_need_ids=[])
    sha = hashlib.sha256(
        json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return {"schema_version": "hqa.hypothesis_card/v2", **body, "hypothesis_digest": sha}


def test_native_hypothesis_card_digest_and_material_redaction(tmp_path):
    _, job = frozen_job(tmp_path)
    body = proposal().model_dump(mode="json")
    body["hypothesis_card"] = hypothesis_card()
    p = intake.Proposal.model_validate(body)
    job["research_design"] = bridge.freeze_research_design(p, job["plans"])
    assert job["research_design"]["hypothesis_card"] == body["hypothesis_card"]
    assert job["research_design"]["materials_status"] == "ready_for_local_test"
    assert "Existing source card" not in json.dumps(bridge.evaluation_chain(job))
    assert "Existing source card" in json.dumps(bridge.evaluation_chain(job, include_material=True))
    body["hypothesis_card"]["mechanism"] = "changed after digest"
    with pytest.raises(ValueError, match="digest_changed"):
        intake.Proposal.model_validate(body)


def test_missing_nonprice_fields_do_not_require_or_run_a_price_proxy(tmp_path, monkeypatch):
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    intake.root(settings).mkdir()
    intake._write(
        intake.root(settings) / "policy.json", intake.IntakePolicy(enabled=True).model_dump()
    )
    body = proposal().model_dump(mode="json")
    body.update(
        hypothesis_card=hypothesis_card(["book_to_market", "filing_available_at"]),
        expression="$book_to_market",
    )

    def must_not_compile(*args, **kwargs):
        raise AssertionError("unsupported source method must not enter the executable compiler")

    monkeypatch.setattr(intake, "_plans", must_not_compile)
    result = intake.submit(settings, body)
    assert result["status"] == "waiting_data"
    job = intake._load_job(settings, result["job_id"])
    assert job["plans"] == [] and "admission_protocol" not in job
    assert job["proposal"]["expression"] == "$book_to_market"
    assert job["research_design"]["data_needs"][0]["fields"] == [
        "book_to_market",
        "filing_available_at",
    ]
    assert intake.run_once(settings) == {"status": "empty", "processed": 0}
    assert intake.reconcile(settings, result["job_id"])["status"] == "waiting_data"
    assert intake.submit(settings, body)["duplicate"] is True
    assert bridge.evaluation_chain(job)["disposition"]["action"] == "build_data"


def test_null_and_partial_strategy_fields_expose_actual_inheritance(tmp_path):
    _, job = frozen_job(tmp_path)
    p = proposal().model_copy(
        update={
            "strategy_spec": intake.StrategySpec(symbols=None, factor_weights={"momentum": 0.4}),
        }
    )
    design = bridge.freeze_research_design(p, job["plans"])
    assert "symbols" in design["inherited_defaults"]
    assert "momentum" not in design["inherited_factor_weights"]
    assert job["formula_factor_id"] in design["inherited_factor_weights"]
    p = proposal().model_copy(update={"strategy_spec": intake.StrategySpec(factor_weights={})})
    assert "factor_weights" in bridge.freeze_research_design(p, job["plans"])["inherited_defaults"]


@pytest.mark.parametrize(
    "tamper",
    ["design", "evaluation", "missing_prices", "missing_artifacts", "self_reported_horizons"],
)
def test_read_receipt_rejects_changed_context_or_unsupported_success(evaluated, tamper):
    settings, job = evaluated
    path = Path(job["factor_evaluation"]["path"])
    if tamper == "design":
        job["research_design"]["portfolio"]["top_n"] = 99
    elif tamper == "evaluation":
        job["evaluation"]["end"] = "2026-01-01"
    elif tamper == "missing_prices":
        Path(job["evaluation"]["prices_path"]).unlink()
    else:
        receipt = json.loads(path.read_text())
        if tamper == "missing_artifacts":
            receipt["artifacts"] = {}
        else:
            receipt["summary"]["horizons"]["1"]["ic"]["rank_ic_mean"] = 0.99999
        path.write_text(json.dumps(receipt))
        job["factor_evaluation"]["sha256"] = file_hash(path)
    with pytest.raises((ValueError, OSError)):
        bridge._read_receipt(settings, job)


def test_fixed_local_rejection_is_archived_without_condemning_paper_or_direction(tmp_path):
    _, job = frozen_job(tmp_path)
    job["factor_evaluation"] = {"summary": {"status": "partial"}}
    job["results"] = [{"variant": "augmented", "validation": {"blockers": ["dsr_failed"]}}]
    decision = bridge.evaluation_chain(job)["disposition"]
    assert decision["action"] == "archive_hypothesis"
    assert decision["original_paper_conclusion"] == "not_evaluated"
    assert decision["resubmission_authorized"] is False
    assert decision["direction_conclusion"].startswith("not_evaluated")


def test_cli_and_ui_share_read_only_integrity_failure(evaluated):
    settings, job = evaluated
    path = Path(job["factor_evaluation"]["path"])
    path.write_text("{}")
    summary = intake._summary(job, settings=settings)["evaluation_chain"]
    assert summary["factor_evaluation"]["status"] == "not_evaluated"
    assert summary["factor_evaluation"]["reason"] == "factor_receipt_integrity_failed"
    assert summary["disposition"]["action"] == "build_data"
    assert "hypothesis" not in summary["research_design"]


@pytest.mark.parametrize("status", ["not_evaluated", "invented_success"])
def test_unknown_or_unmeasured_receipt_cannot_display_metrics(evaluated, status):
    settings, job = evaluated
    path = Path(job["factor_evaluation"]["path"])
    value = json.loads(path.read_text())
    value["summary"]["status"] = status
    value["artifacts"] = {}
    path.write_text(json.dumps(value))
    job["factor_evaluation"]["sha256"] = file_hash(path)
    with pytest.raises(ValueError):
        bridge._read_receipt(settings, job)


@pytest.mark.parametrize("tamper", ["cached_metrics", "validation_bytes", "raw_prices"])
def test_verified_chain_uses_original_validation_and_identical_market_input(tmp_path, tamper):
    import shutil

    from quant_system.research.evaluation_service import _view
    from quant_system.research.strategy_library_cli import _validation
    from quant_system.research.validation_receipts import receipt_bindings
    from tests.test_validation_receipts import sealed_validation

    settings, job = frozen_job(tmp_path)
    for plan in job["plans"]:
        run_id = "validation-" + ("a" if plan["variant"] == "baseline" else "b") * 32
        directory = (
            settings.data.data_dir
            / "strategy_library"
            / plan["strategy_id"]
            / "validations"
            / run_id
        )
        path, _ = sealed_validation(directory, plan["definition_digest"], "c" * 64)
        shutil.copyfile(job["evaluation"]["prices_path"], directory / "prices.parquet")
        for name in ["qlib-replay.json", "signal-analysis.json"]:
            artifact = json.loads((directory / name).read_text())
            artifact["source"]["prices_sha256"] = job["evaluation"]["prices_sha256"]
            (directory / name).write_text(json.dumps(artifact))
        raw = json.loads(path.read_text())
        raw.update(
            run_id=run_id,
            evaluation=job["evaluation"],
            evaluation_calendar_digest="same",
            start=job["evaluation"]["start"],
            end=job["evaluation"]["end"],
            receipts=receipt_bindings(directory),
            platform_metrics={"sharpe": 1 if plan["variant"] == "baseline" else 2},
        )
        raw["active_metrics"] = {
            "alpha_t": [{"date": str(index), "alpha": index / 1000} for index in range(401)]
        }
        path.write_text(json.dumps(raw))
        assert _validation(raw) != _validation(_view(raw))
        job["results"].append(
            {
                "variant": plan["variant"],
                "strategy_id": plan["strategy_id"],
                "definition_digest": plan["definition_digest"],
                "status": "validated",
                "evaluation": job["evaluation"],
                "evaluation_calendar_digest": "same",
                "validation": _validation(_view(raw)),
                "validation_sha256": file_hash(path),
            }
        )
    chain = bridge.verified_evaluation_chain(settings, job)
    assert chain["portfolio_increment"]["passed"] is True
    final = job["results"][1]
    directory = (
        settings.data.data_dir
        / "strategy_library"
        / final["strategy_id"]
        / "validations"
        / final["validation"]["run_id"]
    )
    if tamper == "cached_metrics":
        final["validation"]["platform_metrics"]["sharpe"] = 999
    elif tamper == "validation_bytes":
        (directory / "validation.json").write_text("{}")
    else:
        (directory / "prices.parquet").write_bytes(b"changed artificial fixture")
    chain = bridge.verified_evaluation_chain(settings, job)
    assert chain["portfolio_increment"]["status"] == "unavailable"
    assert chain["admission"]["variants"][1]["status"] == "not_evaluated"
    assert chain["evidence_issues"][0]["variant"] == "augmented"
