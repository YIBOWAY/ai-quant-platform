"""Artificial complete D34 archives exercise the real read-only adapter."""

import hashlib
import json

import pytest

from quant_system.d34.research_request import digest_document
from quant_system.d34.worker import _research_request_digest
from quant_system.research.trials import ResearchTrial


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sealed(value, key="receipt_digest"):
    return {**value, key: digest_document(value)}


def snapshot(root, symbols):
    """Explicitly artificial snapshot bytes; no provider is called."""
    raw = b"artificial snapshot bytes for a provenance-only unit test"
    provider = {
        "provider": "futu",
        "symbols": {s: f"US.{s}" for s in symbols},
        "interval": "1d",
        "adjustment": "qfq",
    }
    identity = {
        "contract": "hqa.market_data_snapshot/v1",
        "provider": "futu",
        "universe": symbols,
        "symbol_codes": provider["symbols"],
        "timezone": "America/New_York",
        "calendar": "XNYS",
        "adjustment": "qfq",
        "provider_receipt_digest": digest_document(provider),
        "parquet_digest": hashlib.sha256(raw).hexdigest(),
    }
    digest = digest_document(identity)
    identifier = "snapshot-" + digest[:32]
    directory = root / "_runtime/d34/snapshots" / identifier
    write(
        directory / "manifest.json",
        {
            **identity,
            "snapshot_id": identifier,
            "snapshot_digest": digest,
            "observed_at": "2026-10-03T00:00:00+00:00",
            "provider_receipt": provider,
            "parquet_file": "ohlcv.parquet",
        },
    )
    (directory / "ohlcv.parquet").write_bytes(raw)
    return identifier, digest


@pytest.fixture
def archive(tmp_path):
    job_id = "job-artificial-0001"
    job = tmp_path / "_runtime/d34/jobs" / job_id
    dates = [f"2024-01-{day}T00:00:00+00:00" for day in ("02", "03", "04", "05")]
    returns = [0.001, -0.002, 0.003, -0.001]
    snapshot_id, snapshot_digest = snapshot(tmp_path, ["AAPL", "MSFT"])
    request = dict(
        contract="hqa.d34_research_request/v2",
        job_id=job_id,
        run_id="attempt-artificial-0001",
        resource_envelope_id="local-paper-research-v1",
        resource_policy_digest="a" * 64,
        snapshot_id=snapshot_id,
        snapshot_digest=snapshot_digest,
        snapshot_source="futu",
        provider_uri="/workspace/provider",
        universe=["AAPL", "MSFT"],
        calendar=dates,
        max_iterations=3,
        experiments_per_iteration=3,
        top_k=1,
        initial_cash=100000.0,
        budget_reservation_usd=10.0,
        objective="Artificial fixture",
        formula="$close",
    )
    request_digest = _research_request_digest(request)
    write(job / "research_request.json", request)
    experiment = "iteration-01-experiment-01"
    research = job / "research/research-artificial"
    proposal = {"operator": "momentum", "long_window": 5}
    observation = {
        "experiment_id": experiment,
        "status": "succeeded",
        "proposal": proposal,
        "returns_digest": digest_document({"values": returns, "dates": dates}),
        "return_dates_digest": digest_document(dates),
    }
    observation_sha = write(research / "experiments" / experiment / "receipt.json", observation)
    row = ResearchTrial.record(
        kind="d34_experiment",
        subject=f"momentum:{experiment}",
        universe=request["universe"],
        daily_returns=returns,
        window_start=dates[0][:10],
        window_end=dates[-1][:10],
        source=f"{job_id}:{experiment}",
        metadata={
            "run_id": f"{job_id}:{experiment}",
            "job_id": job_id,
            "request_digest": request_digest,
            "experiment_id": experiment,
            "attempt_status": "succeeded",
            "proposal_digest": digest_document(proposal),
            "experiment_receipt_digest": observation_sha,
        },
    )
    trial = {
        "experiment_id": experiment,
        "subject": row.subject,
        "proposal_digest": digest_document(proposal),
        "experiment_receipt_digest": observation_sha,
        "daily_returns": returns,
    }
    batch = sealed(
        dict(
            contract="hqa.d34_experiment_trial_batch/v1",
            job_id=job_id,
            request_digest=request_digest,
            universe=request["universe"],
            universe_digest=digest_document(request["universe"]),
            calendar_digest=digest_document(dates),
            return_dates=dates,
            experiment_count=1,
            successful_experiment_count=1,
            attempts=[{"experiment_id": experiment, "status": "succeeded"}],
            selected_experiment=experiment,
            experiments=[trial],
        )
    )
    batch_path = job / f"research/experiment-trials-{request_digest[:32]}.json"
    batch_sha = write(batch_path, batch)
    config = dict(
        contract="hqa.d34_qlib_config/v1",
        universe=request["universe"],
        start_time=dates[0],
        end_time=dates[-1],
        execution_timing="next_open",
        exchange={
            "deal_price": "$open",
            "open_cost": 0.0006,
            "close_cost": 0.0006,
            "min_cost": 0,
            "trade_unit": 1,
            "limit_threshold": None,
        },
    )
    qlib = sealed(
        dict(
            contract="hqa.d34_engine_receipt/v1",
            job_id=job_id,
            engine="qlib",
            run_id=request["run_id"],
            selected_experiment=experiment,
            snapshot_id=request["snapshot_id"],
            snapshot_digest=request["snapshot_digest"],
            universe_digest=digest_document(request["universe"]),
            calendar_digest=digest_document(dates),
            return_dates=dates,
            daily_returns=returns,
            qlib_config=config,
            qlib_config_digest=digest_document(config),
        )
    )
    qlib_sha = write(research / "qlib_receipt.json", qlib)
    result = dict(
        contract="hqa.d34_research_result/v2",
        job_id=job_id,
        run_id=request["run_id"],
        request_digest=request_digest,
        selected_experiment=experiment,
        qlib_receipt_file="qlib_receipt.json",
        qlib_receipt_digest=qlib["receipt_digest"],
        qlib_receipt_file_digest=qlib_sha,
        qlib_config_digest=digest_document(config),
        experiment_trials_path=str(batch_path),
        experiment_trials_digest=batch["receipt_digest"],
        experiment_trials_file_digest=batch_sha,
        experiment_count=1,
        successful_experiment_count=1,
    )
    write(research / "research_receipt.json", result)
    manifest = sealed(
        dict(
            contract="hqa.d34_research_evidence/v1",
            job_id=job_id,
            run_id=request["run_id"],
            research_request_digest=digest_document(request),
            qlib_raw_receipt_path=str((research / "qlib_receipt.json").relative_to(job)),
            qlib_raw_receipt_file_digest=qlib_sha,
            qlib_receipt_digest=qlib["receipt_digest"],
            cost_model={"commission_bps": 1.0, "slippage_bps": 5.0},
        ),
        key="manifest_digest",
    )
    write(job / "evidence_manifest.json", manifest)
    return tmp_path, row, job, research, batch_path


def resolver(root, row):
    from quant_system.research.d34_family_evidence import D34FamilyEvidenceResolver

    return D34FamilyEvidenceResolver(root, trusted_trials=[row])


def test_complete_original_selected_trial_resolves_without_writer_or_benchmark(archive):
    root, row, *_ = archive
    before = {str(p): p.read_bytes() for p in root.rglob("*.json")}
    instance = resolver(root, row)
    payload = instance(row)
    assert payload is not None and not instance.failures
    assert payload["family_contract"]["return_definition"] == "net_total_return"
    assert payload["family_contract"]["benchmark"] == {"symbol": None, "method": "none"}
    assert all(set(mark) == {"date", "equity"} for mark in payload["curve"])
    assert payload["curve"][0]["equity"] == pytest.approx(100100)
    assert before == {str(p): p.read_bytes() for p in root.rglob("*.json")}


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_batch",
        "wrong_job",
        "changed_batch",
        "wrong_calendar",
        "modified_cost",
        "missing_cost",
        "wrong_observation",
        "wrong_trial",
        "unselected_no_own_cost",
        "changed_snapshot",
    ],
)
def test_missing_misbound_or_modified_originals_never_create_family_member(archive, mutation):
    root, row, job, research, batch_path = archive
    if mutation == "missing_batch":
        batch_path.unlink()
    elif mutation == "wrong_job":
        value = json.loads((job / "research_request.json").read_text())
        value["job_id"] = "job-wrong-0001"
        write(job / "research_request.json", value)
    elif mutation == "changed_batch":
        batch_path.write_text(batch_path.read_text() + " ")
    elif mutation == "wrong_calendar":
        row = row.model_copy(update={"window_start": "2020-01-01"})
    elif mutation in {"modified_cost", "missing_cost"}:
        path = job / "evidence_manifest.json"
        value = json.loads(path.read_text())
        value.pop("manifest_digest")
        if mutation == "modified_cost":
            value["cost_model"]["slippage_bps"] = 8.0
        else:
            value.pop("cost_model")
        write(path, sealed(value, "manifest_digest"))
    elif mutation == "wrong_observation":
        path = next((research / "experiments").glob("*/receipt.json"))
        path.write_text(path.read_text() + " ")
    elif mutation == "wrong_trial":
        row = row.model_copy(update={"total_return": 0.123})
    elif mutation == "changed_snapshot":
        path = next((root / "_runtime/d34/snapshots").glob("*/ohlcv.parquet"))
        path.write_bytes(b"changed artificial snapshot")
    else:
        row = row.model_copy(update={"metadata": {**row.metadata, "experiment_id": "other"}})
    instance = resolver(root, row)
    assert instance(row) is None
    assert instance.failures[row.trial_id].startswith("d34_family_")


def test_fresh_resolution_detects_file_changes_after_first_success(archive):
    root, row, job, *_ = archive
    instance = resolver(root, row)
    assert instance(row) is not None
    path = job / "research_request.json"
    path.write_text(path.read_text() + " ")
    # Cosmetic request bytes still reproduce its content digest, but a cached
    # original proof must not be reused as if the bytes were unchanged.
    again = instance(row)
    assert again is not None
    assert (
        again["family_evidence"]["files"][str(path)]
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )


def test_caller_cannot_substitute_a_different_trusted_trial(archive):
    root, row, *_ = archive
    instance = resolver(root, row)
    changed = row.model_copy(update={"metadata": {**row.metadata, "request_digest": "c" * 64}})
    assert instance(changed) is None


def test_trusted_dictionary_is_copied_before_caller_mutates_nested_metadata(archive):
    root, row, *_ = archive
    raw = row.model_dump(mode="json")
    instance = resolver(root, raw)
    raw["metadata"]["request_digest"] = "0" * 64
    assert instance(raw) is None
    assert instance.failures[row.trial_id] == "d34_family_trial_not_trusted"


def test_legacy_backfill_without_batch_identity_remains_explicit_unknown(tmp_path):
    row = ResearchTrial.record(
        kind="d34_experiment",
        subject="old-fixture",
        universe=["AAPL"],
        daily_returns=[0.01, -0.01],
        metadata={"backfilled": True, "full_job_id": "job-old-0001"},
    )
    instance = resolver(tmp_path, row)
    assert instance(row) is None
    assert instance.failures[row.trial_id] == "d34_family_trial_identity_missing"


def test_real_producer_batch_host_ledger_and_readonly_resolver_preserve_each_trial(tmp_path):
    """Only the external market runner is artificial; every persistence seam is real."""
    import pandas as pd

    from quant_system.d34.research_driver import (
        D34ResearchRequest,
        QlibExperimentResult,
        ResearchProposal,
        execute_research_request,
    )
    from quant_system.d34.worker import persist_host_d34_experiment_trials
    from quant_system.research.gate_v2.family import project_family_v2
    from quant_system.research.trials import TrialsLedger

    provider = tmp_path / "provider"
    provider.mkdir()
    days = [
        "02",
        "03",
        "04",
        "05",
        "08",
        "09",
        "10",
        "11",
        "12",
        "16",
        "17",
        "18",
        "19",
        "22",
        "23",
        "24",
        "25",
        "26",
        "29",
        "30",
        "31",
    ]
    snapshot_id, snapshot_digest = snapshot(tmp_path, ["AAPL", "MSFT"])
    request = D34ResearchRequest(
        contract="hqa.d34_research_request/v2",
        job_id="job-producer-fixture",
        run_id="attempt-producer-fixture",
        resource_envelope_id="local-paper-research-v1",
        resource_policy_digest="a" * 64,
        snapshot_id=snapshot_id,
        snapshot_digest=snapshot_digest,
        snapshot_source="futu",
        provider_uri=provider,
        universe=("AAPL", "MSFT"),
        calendar=tuple(f"2024-01-{day}T00:00:00+00:00" for day in days),
        initial_cash=100000.0,
        objective="Clearly artificial persistence integration",
    )
    job = tmp_path / "_runtime/d34/jobs" / request.job_id
    write(job / "research_request.json", request.model_dump(mode="json", exclude_none=True))
    calls = []

    def propose(_request, iteration, experiment, _history):
        return ResearchProposal(
            title="Artificial fixture",
            thesis="No market claim",
            operator="momentum",
            long_window=iteration * 3 + experiment + 2,
            rationale="Exercise real experiment persistence",
        )

    def artificial_market_runner(req, proposal, expression, output):
        calls.append(proposal.long_window)
        if len(calls) == 1:
            raise ValueError("intentional_artificial_failure")
        rate = 0.0007 if len(calls) == 2 else 0.0006
        values = tuple((i % 5 - 2) * 0.001 + len(calls) * 0.00001 for i in range(len(req.calendar)))
        nav = 1.0
        for value in values:
            nav *= 1 + value
        config = dict(
            contract="hqa.d34_qlib_config/v1",
            expression=expression,
            universe=list(req.universe),
            start_time=req.calendar[0],
            end_time=req.calendar[-1],
            execution_timing="next_open",
            exchange={
                "open_cost": rate,
                "close_cost": rate,
                "min_cost": 0,
                "deal_price": "$open",
                "trade_unit": 1,
                "limit_threshold": None,
            },
        )
        return QlibExperimentResult(
            score=float(len(calls)),
            daily_returns=values,
            return_dates=req.calendar,
            terminal_nav=nav,
            terminal_weights={"AAPL": 0.99},
            target_weights=pd.DataFrame(
                {"tradeable_ts": [req.calendar[1]], "symbol": ["AAPL"], "target_weight": [0.99]}
            ),
            metrics={"sharpe": 0.1},
            qlib_config=config,
        )

    output = execute_research_request(
        request,
        output_root=job / "research",
        proposal_provider=propose,
        experiment_runner=artificial_market_runner,
        cost_provider=lambda: 0.0,
        trials_root=tmp_path / "container-only-trials",
    )
    assert len(calls) == 9
    persisted = persist_host_d34_experiment_trials(
        data_root=tmp_path,
        batch_path=output.experiment_trials_path,
        expected_file_digest=output.experiment_trials_file_digest,
        expected_batch_digest=output.experiment_trials_digest,
        expected_job_id=request.job_id,
        expected_request_digest=request.request_digest,
        expected_universe=request.universe,
        expected_calendar_digest=digest_document(list(request.calendar)),
        expected_experiment_count=9,
    )
    assert persisted["completed_experiment_count"] == 9
    rows = TrialsLedger(tmp_path / "trials").list()
    successful = [row for row in rows if row.metadata.get("attempt_status") == "succeeded"]
    assert len(rows) == 9 and len(successful) == 8
    from quant_system.research.d34_family_evidence import D34FamilyEvidenceResolver

    instance = D34FamilyEvidenceResolver(tmp_path, trusted_trials=rows)
    payloads = [instance(row) for row in successful]
    assert all(payload is not None for payload in payloads), instance.failures
    costs = [payload["family_contract"]["cost_definition"]["one_way_bps"] for payload in payloads]
    assert sorted(costs) == [6.0] * 7 + [7.0]
    for payload in payloads:
        assert len(payload["family_evidence"]["selection_history"]["all_attempt_ids"]) == 9
    six = next(
        payload["family_contract"]
        for payload in payloads
        if payload["family_contract"]["cost_definition"]["one_way_bps"] == 6.0
    )
    family = project_family_v2(
        trials_rows=successful,
        universe_digest=successful[0].universe_digest,
        curve_resolver=instance,
        compatibility_contract=six,
    )
    assert family["n_trials"] == 7
    assert family["out_of_scope"][0]["reason"] == "incompatible_cost_definition"
    attempt = next(
        (job / "research").glob("experiment-trial-attempts-*/iteration-01-experiment-01.json")
    )
    failed = json.loads(attempt.read_text())
    assert failed["failure_type"] == "ValueError"
    assert failed["failure_reason"] == "intentional_artificial_failure"
    ledger_path = tmp_path / "trials/trials.jsonl"
    before_ledger, before_batch = (
        ledger_path.read_bytes(),
        output.experiment_trials_path.read_bytes(),
    )
    replay = execute_research_request(
        request,
        output_root=job / "research",
        proposal_provider=propose,
        experiment_runner=artificial_market_runner,
        cost_provider=lambda: 0.0,
        trials_root=tmp_path / "container-only-trials",
    )
    assert len(calls) == 9
    assert replay.experiment_trials_path.read_bytes() == before_batch
    assert ledger_path.read_bytes() == before_ledger
    victim = successful[0]
    observed = output.output_dir / "experiments" / victim.metadata["experiment_id"] / "receipt.json"
    saved = json.loads(observed.read_text())
    saved["evaluation_contract"]["qlib_config"]["exchange"]["open_cost"] = 0
    write(observed, saved)
    assert instance(victim) is None
    assert instance.failures[victim.trial_id] == "d34_family_experiment_original_mismatch"


@pytest.mark.parametrize("mutation", ["same_total_different_sharpe", "same_moments_reordered"])
def test_coherent_batch_reseal_cannot_replace_original_return_path(tmp_path, mutation):
    import math

    from quant_system.research.d34_family_evidence import D34FamilyEvidenceResolver
    from quant_system.research.trials import TrialsLedger, performance_from_daily_returns

    test_real_producer_batch_host_ledger_and_readonly_resolver_preserve_each_trial(tmp_path)
    ledger = TrialsLedger(tmp_path / "trials")
    rows = ledger.list()
    victim = [r for r in rows if r.metadata.get("attempt_status") == "succeeded"][1]
    job = tmp_path / "_runtime/d34/jobs" / victim.metadata["job_id"]
    batch_path = next((job / "research").glob("experiment-trials-*.json"))
    result_path = next((job / "research").glob("*/research_receipt.json"))
    original_path = (
        result_path.parent / "experiments" / victim.metadata["experiment_id"] / "receipt.json"
    )
    before = {path: path.read_bytes() for path in (original_path, ledger.path)}
    instance = D34FamilyEvidenceResolver(tmp_path, trusted_trials=rows)
    assert instance(victim) is not None
    batch = json.loads(batch_path.read_text())
    item = next(
        r for r in batch["experiments"] if r["experiment_id"] == victim.metadata["experiment_id"]
    )
    old = item["daily_returns"]
    changed = list(reversed(old))
    if mutation == "same_total_different_sharpe":
        changed = list(old)
        changed[0] += 0.1
        changed[-1] = (1 + old[-1]) * (1 + old[0]) / (1 + changed[0]) - 1
    else:
        first, second = performance_from_daily_returns(old), performance_from_daily_returns(changed)
        for key in ("sharpe_period", "skewness", "kurtosis"):
            assert math.isclose(first[key], second[key], rel_tol=1e-12, abs_tol=1e-12)
    assert math.isclose(
        math.prod(1 + v for v in old), math.prod(1 + v for v in changed), rel_tol=1e-12
    )
    item["daily_returns"] = changed
    batch.pop("receipt_digest")
    batch = sealed(batch)
    file_sha = write(batch_path, batch)
    result = json.loads(result_path.read_text())
    result.update(
        experiment_trials_digest=batch["receipt_digest"], experiment_trials_file_digest=file_sha
    )
    write(result_path, result)
    assert instance(victim) is None
    assert instance.failures[victim.trial_id] == "d34_family_returns_binding_mismatch"
    assert before == {path: path.read_bytes() for path in before}


def test_original_receipt_without_return_path_pin_remains_unknown_even_if_totals_match(archive):
    root, row, _job, research, batch_path = archive
    path = research / "experiments" / row.metadata["experiment_id"] / "receipt.json"
    observation = json.loads(path.read_text())
    observation.pop("returns_digest")
    observation.pop("return_dates_digest")
    observation_sha = write(path, observation)
    row = row.model_copy(
        update={"metadata": {**row.metadata, "experiment_receipt_digest": observation_sha}}
    )
    batch = json.loads(batch_path.read_text())
    batch["experiments"][0]["experiment_receipt_digest"] = observation_sha
    batch.pop("receipt_digest")
    batch = sealed(batch)
    batch_sha = write(batch_path, batch)
    result_path = research / "research_receipt.json"
    result = json.loads(result_path.read_text())
    result.update(
        experiment_trials_digest=batch["receipt_digest"], experiment_trials_file_digest=batch_sha
    )
    write(result_path, result)
    instance = resolver(root, row)
    assert instance(row) is None
    assert instance.failures[row.trial_id] == "d34_family_returns_binding_missing"
