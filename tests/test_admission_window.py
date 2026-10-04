"""Artificial isolated panels only: these tests make no market-performance claim."""

import copy
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.research import admission_window as window


@pytest.fixture
def artificial_source(tmp_path):
    from quant_system.research import admission_v2 as admission
    from quant_system.research.external_intake import _sha
    from quant_system.research.intake_evaluation import digest
    from quant_system.research.strategy_definition import StrategyDefinition
    from quant_system.research.validation_receipts import receipt_bindings

    owner = tmp_path / "owner"
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=owner))
    definition = StrategyDefinition(
        kind="factor_blend",
        title="ARTIFICIAL UNIT FIXTURE ONLY",
        symbols=window.CONTROL_SYMBOLS,
        top_n=5,
        rebalance="monthly",
        history_start=window.HISTORY_START,
        factors=[{"factor_id": "momentum", "lookback": 20, "direction": "higher_is_better"}],
    ).model_dump(mode="json")
    strategy_id = "strategy-" + definition["content_digest"][:24]
    run = owner / "strategy_library" / strategy_id / "validations/validation-artificial"
    run.mkdir(parents=True)

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    write(run.parent.parent / "definition.json", definition)
    dates = window._sessions("2026-09-25")
    frame = pd.MultiIndex.from_product(
        [dates, [*window.CONTROL_SYMBOLS, "SPY"]], names=["timestamp", "symbol"]
    ).to_frame(index=False)
    frame = frame.assign(
        open=100.0,
        close=100.0,
        high=101.0,
        low=99.0,
        volume=1000.0,
        provider="futu",
        interval="1d",
        event_ts=frame.timestamp,
        knowledge_ts=frame.timestamp,
        price_adjustment="qfq",
    )
    frame.to_parquet(run / "prices.parquet", index=False)
    prices_sha = admission.file_sha(run / "prices.parquet")
    job_id = "intake-" + "e" * 24
    proposal = {"baseline_factor_ids": [], "fixture": "ARTIFICIAL ONLY"}
    protocol = admission.freeze_protocol(job_id, _sha(proposal))
    plans = [
        {
            "variant": "formula",
            "definition_digest": definition["content_digest"],
            "strategy_id": strategy_id,
            "payload": {k: v for k, v in definition.items() if k != "history_start"},
            "history_start": definition["history_start"],
            "activation_eligible": True,
            "origin": {"admission_protocol_digest": protocol["protocol_digest"]},
        }
    ]
    frozen = owner / "research_intake/evaluations" / job_id / "prices.parquet"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes((run / "prices.parquet").read_bytes())
    evaluation = {
        "prices_sha256": prices_sha,
        "prices_path": str(frozen),
        "plans_sha256": _sha(plans),
        "job_id": job_id,
        "start": "2018-01-01",
        "end": "2026-09-25",
        "symbols": [*window.CONTROL_SYMBOLS, "SPY"],
        "cash": 10000,
        "commission_bps": 1,
        "slippage_bps": 5,
    }
    evaluation["evaluation_id"] = "evaluation-" + digest(evaluation)
    write(frozen.with_name("snapshot.json"), evaluation)
    job = {
        "job_id": job_id,
        "proposal": proposal,
        "payload_sha256": _sha(proposal),
        "plans": plans,
        "plans_sha256": _sha(plans),
        "evaluation": evaluation,
        "admission_protocol": protocol,
        "status": "running",
        "results": [],
    }
    job_path = owner / "research_intake/jobs" / (job_id + ".json")
    write(job_path, job)
    curve = [
        {"date": d.date().isoformat(), "equity": 10000.0, "benchmark": 10000.0}
        for d in dates
        if d >= pd.Timestamp("2018-01-01", tz="UTC")
    ]
    write(
        run / "platform-result.json",
        {
            "definition_digest": definition["content_digest"],
            "curve": curve,
            "profile": {"symbols": window.CONTROL_SYMBOLS, "benchmark_symbol": "SPY"},
            "source": "futu",
            "price_adjustment": "qfq",
        },
    )
    sources = receipt_bindings.__globals__["_SOURCES"]
    from pathlib import Path

    import quant_system.research.validation_receipts as receipt_module

    source_sha = {
        name: admission.file_sha(Path(receipt_module.__file__).parent / name) for name in sources
    }
    for name, field, source_field, source_file in [
        (
            "qlib-replay.json",
            "platform_result_sha256",
            "replay_source_sha256",
            "definition_qlib_replay.py",
        ),
        (
            "signal-analysis.json",
            "result_sha256",
            "validation_source_sha256",
            "strategy_signal_validation.py",
        ),
    ]:
        write(
            run / name,
            {
                "definition_digest": definition["content_digest"],
                "status": "available",
                "source": {
                    "prices_sha256": prices_sha,
                    field: admission.file_sha(run / "platform-result.json"),
                    source_field: source_sha[source_file],
                    "fit_metrics_source_sha256": source_sha["qlib_evaluation.py"],
                },
            },
        )
    write(
        run / "validation.json",
        {
            "status": "failed",
            "definition_digest": definition["content_digest"],
            "comparison": {"accepted": True},
            "receipts": receipt_bindings(run),
            "evaluation": evaluation,
            "evaluation_calendar_digest": window._hash([r["date"] for r in curve]),
        },
    )
    return settings, run / "validation.json", job_path


def test_monthly_population_crosses_a_new_month_without_fixed_105_count():
    september = window.control_population(window.window_context("2026-09-24"))
    october = window.control_population(window.window_context("2026-10-01"))
    assert len(september) == len(october) == 500
    assert len(september[0]["schedule"]) == 105
    assert len(october[0]["schedule"]) == 106
    assert october[0]["schedule"][-1]["signal_date"] == "2026-09-30"
    assert october[0]["schedule"][-1]["trade_date"] == "2026-10-01"


def test_running_source_freezes_without_terminal_job_or_mutable_job_sha(
    artificial_source, tmp_path
):
    settings, validation, job_path = artificial_source
    frozen = window.freeze_window(settings, validation_path=validation, output=tmp_path / "window")
    job = json.loads(job_path.read_text())
    job.update(status="failed", updated_at="2099-01-01", results=[{"phase": "done"}])
    job_path.write_text(json.dumps(job))
    prices, manifest = window.read_window(frozen["manifest_path"], frozen["manifest_sha256"])
    assert len(prices) == 73750
    assert manifest["context"]["end"] == "2026-09-25"
    assert str(job_path) not in manifest["source"]["files"]
    assert manifest["source"]["immutable_job_digest"]


@pytest.mark.parametrize("mutation", ["seed", "selection", "missing", "duplicate", "scope"])
def test_self_declared_population_never_replaces_fixed_rng(mutation):
    context = window.window_context("2026-09-25")
    population, method = window.control_population(context), copy.deepcopy(window.METHOD)
    if mutation == "seed":
        method["seed"] += 1
    elif mutation == "selection":
        population[0]["schedule"][0]["targets"] = {"AAPL": 1.0}
    elif mutation == "missing":
        population.pop()
    elif mutation == "duplicate":
        population[-1] = copy.deepcopy(population[0])
    else:
        context["slippage_bps"] = 0
    with pytest.raises(ValueError, match="window_(control|context)"):
        window.verify_control_population(context, population, method=method)


@pytest.mark.parametrize("mutation", ["producer", "core", "price", "job", "snapshot"])
def test_resigned_manifest_cannot_hide_changed_originals(artificial_source, tmp_path, mutation):
    settings, validation, job_path = artificial_source
    frozen = window.freeze_window(settings, validation_path=validation, output=tmp_path / "window")
    from pathlib import Path

    path = Path(frozen["manifest_path"])
    manifest = json.loads(path.read_text())
    if mutation == "producer":
        manifest["producer_sources"]["src/quant_system/research/admission_window.py"] = "a" * 64
    elif mutation == "core":
        manifest["code_digest"] = "a" * 64
    elif mutation == "price":
        frame = pd.read_parquet(path.parent / "prices.parquet")
        frame.loc[0, "open"] = 100.5
        frame.to_parquet(path.parent / "prices.parquet", index=False)
        manifest["artifacts"]["prices.parquet"]["sha256"] = window._sha(
            path.parent / "prices.parquet"
        )
    elif mutation == "job":
        job = json.loads(job_path.read_text())
        job["proposal"]["fixture"] = "CHANGED ARTIFICIAL PROPOSAL"
        job_path.write_text(json.dumps(job))
    else:
        prices = json.loads(validation.read_text())["evaluation"]["prices_path"]
        Path(prices).with_name("snapshot.json").write_text("{}")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        window.read_window(path, window._sha(path))


def test_future_window_without_its_trading_days_is_rejected(artificial_source):
    _, validation, _ = artificial_source
    frame = pd.read_parquet(validation.parent / "prices.parquet")
    with pytest.raises(ValueError, match="window_calendar_or_universe_mismatch"):
        window._audit_frame(frame, "2026-10-01")


def test_control_artifact_verifier_refuses_incomplete_batch_before_any_replay(
    artificial_source, tmp_path
):
    settings, validation, _ = artificial_source
    frozen = window.freeze_window(settings, validation_path=validation, output=tmp_path / "window")
    controls = tmp_path / "incomplete-controls"
    controls.mkdir()
    with pytest.raises(ValueError, match="window_control_population_incomplete"):
        window.verify_control_artifacts(
            frozen["manifest_path"], frozen["manifest_sha256"], controls
        )


@pytest.fixture
def artificial_control(artificial_source, tmp_path):
    """One real engine run on labelled constant artificial prices, never a market run."""
    _, validation, _ = artificial_source
    prices = pd.read_parquet(validation.parent / "prices.parquet")
    context = window.window_context("2026-09-25")
    frame = window._engine_frame(prices, context)
    schedule = window.control_population(context)[0]["schedule"]
    dates = sorted(set(frame.timestamp))
    profile = {
        "profile": {"peer_symbols": window.CONTROL_SYMBOLS},
        "start": context["start"],
        "end": context["end"],
        "curve": [{"date": d.date().isoformat(), "benchmark": 100000.0} for d in dates],
    }
    identity = {"fixture": "ARTIFICIAL UNIT ONLY", "seed": window.SEED}
    output = tmp_path / "artificial-single-control"
    output.mkdir()
    window._driver().run_variant(
        0, frame, window._schedule(schedule), schedule, profile, output, identity
    )
    return output / "variant-0000", {
        "index": 0,
        "frame": frame,
        "schedule": schedule,
        "profile": profile,
        "identity": identity,
    }


def test_actual_artificial_engine_replay_agrees_and_performs_no_writes(artificial_control):
    directory, args = artificial_control
    before = {p.name: window._sha(p) for p in directory.iterdir()}
    verified = window.verify_control_variant(directory, **args)
    assert verified["status"] == "completed"
    assert before == {p.name: window._sha(p) for p in directory.iterdir()}


def test_resigned_equity_cannot_replace_actual_engine_replay(artificial_control):
    directory, args = artificial_control
    path = directory / "equity_curve.parquet"
    frame = pd.read_parquet(path)
    frame.loc[0, "equity"] += 10.0
    frame.to_parquet(path, index=False)
    receipt_path = directory / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["files"][path.name] = window._sha(path)
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="window_control_engine_replay_mismatch:equity_curve"):
        window.verify_control_variant(directory, **args)


def test_self_reported_cash_in_receipt_is_checked_against_engine(artificial_control):
    directory, args = artificial_control
    receipt_path = directory / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["minimum_cash"] = 1000000000
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="window_control_recomputed_result_changed"):
        window.verify_control_variant(directory, **args)


def test_window_namespace_allowed_but_trading_state_and_overwrites_refused(
    artificial_source, tmp_path
):
    settings, validation, _ = artificial_source
    identity = window.window_identity(settings, validation)
    allowed = (
        settings.data.data_dir / "research_intake/admission_v2/windows" / identity["window_id"]
    )
    result = window.freeze_window(settings, validation_path=validation, output=allowed)
    assert result["window_id"] == identity["window_id"]
    with pytest.raises(ValueError, match="window_output_already_exists"):
        window.freeze_window(settings, validation_path=validation, output=allowed)
    for name in ("trials", "assistant_remote", "strategy_library/new-version"):
        target = settings.data.data_dir / name
        with pytest.raises(ValueError, match="window_output_not_research_namespace"):
            window.freeze_window(settings, validation_path=validation, output=target)
        assert not target.exists()


def test_nested_control_output_is_rejected_before_family_or_engine_work(
    artificial_source, tmp_path
):
    settings, validation, _ = artificial_source
    frozen = window.freeze_window(settings, validation_path=validation, output=tmp_path / "input")
    with pytest.raises(ValueError, match="window_control_output_overlaps_input"):
        window.produce_controls(
            frozen["manifest_path"],
            frozen["manifest_sha256"],
            tmp_path / "not_read_or_loaded.jsonl",
            tmp_path / "input/controls",
        )
    assert not (tmp_path / "input/controls").exists()


def test_full_core_change_gets_new_key_even_when_producer_files_are_identical(monkeypatch):
    """Simulate only the environment's bound core identity, not the window implementation."""
    from quant_system.research import admission_v2 as admission

    context = window.window_context("2026-09-25")
    sources = window._producer_sources()
    before = window._window_id(context, "a" * 64, sources)
    current = admission.code_identity()
    changed_files = {**current["files"], "research/admission_consumer_checks.py": "b" * 64}
    monkeypatch.setattr(
        admission,
        "code_identity",
        lambda: {"files": changed_files, "digest": window._hash(changed_files)},
    )
    assert window._producer_sources() == sources
    assert window._window_id(context, "a" * 64, sources) != before


def test_last_byte_check_includes_every_frozen_input_artifact(artificial_source, tmp_path):
    from pathlib import Path

    settings, validation, _ = artificial_source
    frozen = window.freeze_window(settings, validation_path=validation, output=tmp_path / "input")
    manifest_path = Path(frozen["manifest_path"])
    _, manifest = window.read_window(manifest_path, frozen["manifest_sha256"])
    files = window._window_artifact_hashes(manifest_path, manifest)
    audit = manifest_path.parent / "source-audit.json"
    assert set(files) == {str(manifest_path.parent / name) for name in manifest["artifacts"]}
    assert files[str(audit)] == window._sha(audit)
    audit.write_text(audit.read_text() + "\n")
    assert any(window._sha(path) != digest for path, digest in files.items())


def test_baseline_and_augmented_share_window_despite_distinct_definitions(artificial_source):
    """Two fully bound artificial receipts, with the same prices and actual core identity."""
    import shutil
    from pathlib import Path

    from quant_system.research.external_intake import _sha
    from quant_system.research.intake_evaluation import digest
    from quant_system.research.strategy_definition import StrategyDefinition
    from quant_system.research.validation_receipts import receipt_bindings

    settings, baseline_path, job_path = artificial_source
    original = json.loads((baseline_path.parent.parent.parent / "definition.json").read_text())
    augmented = StrategyDefinition(
        **{
            **original,
            "title": "ARTIFICIAL AUGMENTED UNIT FIXTURE",
            "content_digest": "",
            "factors": [{"factor_id": "momentum", "lookback": 30, "direction": "higher_is_better"}],
        }
    ).model_dump(mode="json")
    augmented_id = "strategy-" + augmented["content_digest"][:24]
    augmented_path = (
        settings.data.data_dir
        / "strategy_library"
        / augmented_id
        / "validations/validation-artificial-augmented/validation.json"
    )
    shutil.copytree(baseline_path.parent, augmented_path.parent)
    (augmented_path.parent.parent.parent / "definition.json").write_text(json.dumps(augmented))
    job = json.loads(job_path.read_text())
    baseline_plan = {**job["plans"][0], "variant": "baseline", "activation_eligible": False}
    augmented_plan = {
        **baseline_plan,
        "variant": "augmented",
        "activation_eligible": True,
        "definition_digest": augmented["content_digest"],
        "strategy_id": augmented_id,
        "payload": {k: v for k, v in augmented.items() if k != "history_start"},
    }
    job["plans"] = [baseline_plan, augmented_plan]
    job["plans_sha256"] = _sha(job["plans"])
    evaluation = {k: v for k, v in job["evaluation"].items() if k != "evaluation_id"}
    evaluation["plans_sha256"] = job["plans_sha256"]
    evaluation["evaluation_id"] = "evaluation-" + digest(evaluation)
    job["evaluation"] = evaluation
    job_path.write_text(json.dumps(job))
    Path(evaluation["prices_path"]).with_name("snapshot.json").write_text(json.dumps(evaluation))
    for path, definition in [(baseline_path, original), (augmented_path, augmented)]:
        platform_path = path.parent / "platform-result.json"
        platform = json.loads(platform_path.read_text())
        platform["definition_digest"] = definition["content_digest"]
        platform_path.write_text(json.dumps(platform))
        for name, field in [
            ("qlib-replay.json", "platform_result_sha256"),
            ("signal-analysis.json", "result_sha256"),
        ]:
            evidence_path = path.parent / name
            evidence = json.loads(evidence_path.read_text())
            evidence["definition_digest"] = definition["content_digest"]
            evidence["source"][field] = window._sha(platform_path)
            evidence_path.write_text(json.dumps(evidence))
        validation = json.loads(path.read_text())
        validation.update(
            definition_digest=definition["content_digest"],
            evaluation=evaluation,
            receipts=receipt_bindings(path.parent),
        )
        path.write_text(json.dumps(validation))
    assert original["content_digest"] != augmented["content_digest"]
    assert window.window_identity(settings, baseline_path) == window.window_identity(
        settings, augmented_path
    )
