"""Complete artificial original files exercise real read-only quality adapters.

Fixture receipts are artificial protocol specimens, not real market/engine proof.
No adapter, statistic, identity verifier or funding consumer is monkeypatched.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.research.capital_evidence import current_candidate_quality
from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2.active_returns import recompute_active_returns
from quant_system.research.strategy_definition import StrategyDefinition
from quant_system.research.trials import ResearchTrial, TrialsLedger
from quant_system.research.validation_receipts import receipt_bindings
from tests.gate_v2_fixtures import platform_result


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def definition_archive(root, n=12):
    from quant_system.research import validation_receipts

    candidates, rows = [], []
    for index in range(n):
        definition = StrategyDefinition(
            kind="factor_blend",
            title=f"Artificial definition {index}",
            symbols=["AAPL", "MSFT"],
            history_start="2015-01-01",
            top_n=1,
            factors=[
                {"factor_id": "momentum", "lookback": 20 + index, "direction": "higher_is_better"}
            ],
        )
        directory = root / "strategy_library" / ("strategy-" + definition.content_digest[:24])
        run = directory / "validations" / f"validation-artificial-{index}"
        source_sha = write(directory / "definition.json", definition.model_dump(mode="json"))
        returns = (
            [0.003 + 0.001 * math.sin(i) for i in range(252)]
            if index == 0
            else [0.00002 * index + 0.005 * math.sin(i + index) for i in range(252)]
        )
        payload = platform_result(
            equity_returns=returns, benchmark_returns=[0.0001] * 252, initial_cash=10000
        )
        payload.update(
            definition=definition.model_dump(mode="json"),
            definition_digest=definition.content_digest,
            source="futu",
            price_adjustment="qfq",
            frequency="daily",
            metrics={"turnover": 1.0},
            profile={
                "id": f"artificial-{index}",
                "symbols": ["AAPL", "MSFT"],
                "benchmark_symbol": "SPY",
            },
        )
        result_sha = write(run / "platform-result.json", payload)
        (run / "prices.parquet").write_bytes(b"artificial protocol fixture, no market claim")
        price_sha = hashlib.sha256((run / "prices.parquet").read_bytes()).hexdigest()
        sources = {
            name: hashlib.sha256(
                Path(validation_receipts.__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in validation_receipts._SOURCES
        }
        write(
            run / "qlib-replay.json",
            {
                "status": "available",
                "definition_digest": definition.content_digest,
                "source": {
                    "prices_sha256": price_sha,
                    "platform_result_sha256": result_sha,
                    "replay_source_sha256": sources["definition_qlib_replay.py"],
                },
            },
        )
        write(
            run / "signal-analysis.json",
            {
                "status": "available",
                "definition_digest": definition.content_digest,
                "source": {
                    "prices_sha256": price_sha,
                    "result_sha256": result_sha,
                    "validation_source_sha256": sources["strategy_signal_validation.py"],
                    "fit_metrics_source_sha256": sources["qlib_evaluation.py"],
                },
            },
        )
        validation_sha = write(
            run / "validation.json",
            {
                "status": "passed",
                "blockers": [],
                "definition_digest": definition.content_digest,
                "comparison": {"accepted": True, "comparison_digest": "c" * 64},
                "receipts": receipt_bindings(run),
            },
        )
        active = recompute_active_returns(payload["curve"], initial_cash=10000)
        candidates.append(
            {
                "candidate_id": f"artificial-{index}",
                "source": "strategy_definition",
                "source_path": str(directory / "definition.json"),
                "source_digest": source_sha,
                "definition_digest": definition.content_digest,
                "verification_receipt_digest": validation_sha,
                "comparison_digest": "c" * 64,
                "universe": ["AAPL", "MSFT"],
                "status": "verified",
                "sleeve_id": None,
                "performance": {
                    "daily_returns": active["equity_returns"],
                    "return_dates": active["dates"],
                },
            }
        )
        rows.append(
            ResearchTrial.record(
                kind="platform_backtest",
                subject=f"artificial-{index}",
                universe=["AAPL", "MSFT"],
                daily_returns=active["equity_returns"],
                source="artificial_fixture",
                window_start=active["dates"][0],
                window_end=active["dates"][-1],
                metadata={
                    "run_id": f"artificial-{index}",
                    "strategy_definition_digest": definition.content_digest,
                    "equity_curve_digest": _hash(payload["curve"]),
                },
            )
        )
    TrialsLedger(root / "trials").append_many(rows)
    return SimpleNamespace(data=SimpleNamespace(data_dir=root)), candidates, rows


def test_definition_adapter_reads_originals_and_leaves_every_byte_unchanged(tmp_path):
    settings, candidates, _ = definition_archive(tmp_path)
    before = tree(tmp_path)
    report = current_candidate_quality(settings, candidates[0], candidates)
    assert report["eligible"] is True, report
    assert report["tier"] == "T2"
    assert report["n_family_members"] == 12
    assert report["evidence_binding"]["selected_engine"] == "platform"
    assert report["funding_authority"] is False
    assert tree(tmp_path) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "candidate_returns",
        "receipt_deleted",
        "result_changed",
        "source_changed",
        "wrong_source",
        "receipt_hash",
    ],
)
def test_candidate_missing_or_altered_original_is_not_book_authority(tmp_path, mutation):
    settings, candidates, _ = definition_archive(tmp_path)
    candidate = candidates[0]
    directory = Path(candidate["source_path"]).parent
    run = next((directory / "validations").iterdir())
    if mutation == "candidate_returns":
        candidate["performance"]["daily_returns"][0] += 0.01
    elif mutation == "receipt_deleted":
        (run / "validation.json").unlink()
    elif mutation == "result_changed":
        payload = json.loads((run / "platform-result.json").read_text())
        payload["curve"][0]["equity"] += 1
        write(run / "platform-result.json", payload)
    elif mutation == "source_changed":
        Path(candidate["source_path"]).write_text("{}")
    elif mutation == "wrong_source":
        candidate["source_path"] = candidates[1]["source_path"]
    else:
        candidate["verification_receipt_digest"] = "0" * 64
    before = tree(tmp_path)
    report = current_candidate_quality(settings, candidate, candidates)
    assert report["eligible"] is False
    assert report["reasons"] == ["quality_evidence_unavailable"]
    assert tree(tmp_path) == before


def test_missing_same_family_original_is_gap_not_excluded_by_kind(tmp_path):
    settings, candidates, _ = definition_archive(tmp_path)
    run = next((Path(candidates[1]["source_path"]).parent / "validations").iterdir())
    (run / "platform-result.json").unlink()
    report = current_candidate_quality(settings, candidates[0], candidates)
    assert report["eligible"] is False
    assert report["family"]["excluded"]
    assert "family_evidence_incomplete" in report["reasons"]


@pytest.mark.parametrize("same_universe", [True, False])
def test_unresolved_d34_trial_is_a_gap_only_in_the_candidate_universe(tmp_path, same_universe):
    settings, candidates, _ = definition_archive(tmp_path)
    row = ResearchTrial.record(
        kind="d34_experiment",
        subject="Artificial missing original",
        universe=["AAPL", "MSFT"] if same_universe else ["ZZZ"],
        daily_returns=[0.0001 + 0.001 * math.sin(i) for i in range(252)],
        metadata={
            "run_id": "job-missing:experiment-1",
            "job_id": "job-missing",
            "experiment_id": "experiment-1",
        },
    )
    TrialsLedger(tmp_path / "trials").append(row)
    report = current_candidate_quality(settings, candidates[0], candidates)
    assert report["eligible"] is (not same_universe)
    collection = report["family"]["excluded" if same_universe else "out_of_scope"]
    assert any(item["trial_id"] == row.trial_id for item in collection)


def test_legacy_n1_mathematics_does_not_supply_fresh_capital(tmp_path):
    settings, candidates, _ = definition_archive(tmp_path, n=1)
    report = current_candidate_quality(settings, candidates[0], candidates)
    assert report["n_family_members"] == 1
    assert report["eligible"] is False
    assert report["tier"] == "T0"


def test_absent_ledger_is_explicit_and_never_created(tmp_path):
    settings, candidates, _ = definition_archive(tmp_path)
    (tmp_path / "trials/trials.jsonl").unlink()
    (tmp_path / "trials").rmdir()
    before = tree(tmp_path)
    report = current_candidate_quality(settings, candidates[0], candidates)
    assert report["eligible"] is False
    assert report["evidence_binding"]["trial_ledger_state"] == "absent"
    assert not (tmp_path / "trials").exists()
    assert tree(tmp_path) == before


def test_unmeasurable_hung_peer_is_not_silently_dropped(tmp_path):
    settings, candidates, _ = definition_archive(tmp_path)
    other = copy.deepcopy(candidates[1])
    other.update(status="hung", sleeve_id="sleeve-real-fixture")
    other["performance"].pop("return_dates")
    report = current_candidate_quality(settings, candidates[0], [*candidates, other])
    assert report["eligible"] is False
    assert report["reasons"] == ["quality_evidence_unavailable"]
    assert report["evidence_reason"] == "candidate_original_performance_mismatch"


def test_registered_without_original_reference_is_typed_unavailable(tmp_path):
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    report = current_candidate_quality(settings, {"source": "registered_factor"}, [])
    assert report["eligible"] is False
    assert report["evidence_reason"] == "candidate_registered_evidence_required"
    assert not list(tmp_path.iterdir())


def d34_archive(root):
    """Real producers/persistence, with an explicit artificial external runner."""
    import exchange_calendars as xcals
    import pandas as pd

    from quant_system.d34.engine_comparison import (
        ComparisonPolicy,
        EngineReceipt,
        compare_engine_receipts,
    )
    from quant_system.d34.research_driver import (
        D34ResearchRequest,
        QlibExperimentResult,
        ResearchProposal,
        execute_research_request,
    )
    from quant_system.d34.research_request import digest_document
    from quant_system.d34.worker import persist_host_d34_experiment_trials
    from tests.test_d34_family_evidence import sealed, snapshot

    provider = root / "artificial-provider"
    provider.mkdir()
    symbols = ["AAPL", "MSFT"]
    snapshot_id, snapshot_digest = snapshot(root, symbols)
    days = tuple(
        day.isoformat() + "T00:00:00+00:00"
        for day in xcals.get_calendar("XNYS")
        .sessions_in_range("2023-01-01", "2024-12-31")[:252]
        .date
    )
    outputs = []
    for job_index in range(2):
        request = D34ResearchRequest(
            contract="hqa.d34_research_request/v2",
            job_id=f"job-artificial-capital-{job_index}",
            run_id=f"attempt-artificial-capital-{job_index}",
            resource_envelope_id="local-paper-research-v1",
            resource_policy_digest="a" * 64,
            snapshot_id=snapshot_id,
            snapshot_digest=snapshot_digest,
            snapshot_source="futu",
            provider_uri=provider,
            universe=tuple(symbols),
            calendar=days,
            initial_cash=100000.0,
            objective="Explicit artificial adapter fixture",
        )
        job = root / "_runtime/d34/jobs" / request.job_id
        write(job / "research_request.json", request.model_dump(mode="json", exclude_none=True))

        def propose(_request, iteration, experiment, _history):
            return ResearchProposal(
                title="Artificial fixture",
                thesis="No market claim",
                operator="momentum",
                long_window=iteration * 3 + experiment + 2,
                rationale="Original evidence test",
            )

        def artificial_runner(req, proposal, expression, _output):
            serial = proposal.long_window
            mean = 0.003 if serial == 14 else 0.000005 * serial
            values = tuple(mean + 0.002 * math.sin(i + serial) for i in range(len(req.calendar)))
            nav = math.prod(1 + value for value in values)
            return QlibExperimentResult(
                score=float(serial),
                daily_returns=values,
                return_dates=req.calendar,
                terminal_nav=nav,
                terminal_weights={"AAPL": 0.99},
                target_weights=pd.DataFrame(
                    {"tradeable_ts": [req.calendar[1]], "symbol": ["AAPL"], "target_weight": [0.99]}
                ),
                metrics={"turnover": 1.0},
                qlib_config={
                    "contract": "hqa.d34_qlib_config/v1",
                    "expression": expression,
                    "universe": list(req.universe),
                    "start_time": req.calendar[0],
                    "end_time": req.calendar[-1],
                    "execution_timing": "next_open",
                    "exchange": {
                        "open_cost": 0.0006,
                        "close_cost": 0.0006,
                        "min_cost": 0,
                        "deal_price": "$open",
                        "trade_unit": 1,
                        "limit_threshold": None,
                    },
                },
            )

        output = execute_research_request(
            request,
            output_root=job / "research",
            proposal_provider=propose,
            experiment_runner=artificial_runner,
            cost_provider=lambda: 0.0,
            trials_root=root / "isolated-container-trials",
        )
        persist_host_d34_experiment_trials(
            data_root=root,
            batch_path=output.experiment_trials_path,
            expected_file_digest=output.experiment_trials_file_digest,
            expected_batch_digest=output.experiment_trials_digest,
            expected_job_id=request.job_id,
            expected_request_digest=request.request_digest,
            expected_universe=request.universe,
            expected_calendar_digest=digest_document(list(request.calendar)),
            expected_experiment_count=9,
        )
        outputs.append((request, job, output))
    request, job, output = outputs[-1]
    qlib = json.loads(output.qlib_receipt_path.read_text())
    platform = copy.deepcopy(qlib)
    platform.pop("receipt_digest")
    platform["engine"] = "platform"
    # Permitted independent-engine rounding difference stays explicitly separate.
    platform["daily_returns"][0] += 1e-12
    platform["terminal_nav"] = math.prod(1 + x for x in platform["daily_returns"])
    platform = sealed(platform)
    platform_path = job / "platform_raw.json"
    write(platform_path, platform)
    engines, paths = {}, {}
    for name, raw, raw_path in [
        ("qlib", qlib, output.qlib_receipt_path),
        ("platform", platform, platform_path),
    ]:
        engine = {
            key: raw[key]
            for key in [
                "engine",
                "snapshot_digest",
                "universe_digest",
                "calendar_digest",
                "target_weights_digest",
                "daily_returns",
                "return_dates",
                "terminal_nav",
                "terminal_weights",
                "receipt_digest",
            ]
        }
        paths[name] = job / f"{name}_bound.json"
        write(
            paths[name],
            sealed(
                {
                    "contract": "hqa.d34_bound_engine_receipt/v2",
                    "job_id": request.job_id,
                    "run_id": request.run_id,
                    "resource_envelope_id": request.resource_envelope_id,
                    "engine": name,
                    "raw_receipt_path": str(raw_path.relative_to(job)),
                    "raw_receipt_file_digest": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    "engine_receipt": engine,
                    "turnover_period": 1.0,
                }
            ),
        )
        engines[name] = EngineReceipt(**engine)
    comparison = compare_engine_receipts(
        qlib=engines["qlib"], platform=engines["platform"], policy=ComparisonPolicy.initial()
    )
    assert comparison.accepted
    manifest = {
        "contract": "hqa.d34_research_evidence/v1",
        "job_id": request.job_id,
        "run_id": request.run_id,
        "research_request_digest": digest_document(
            request.model_dump(mode="json", exclude_none=True)
        ),
        "candidate_code_path": str(output.factor_path.relative_to(job)),
        "candidate_code_digest": output.candidate_code_digest,
        "comparison_digest": comparison.comparison_digest,
        "cost_model": {"commission_bps": 1.0, "slippage_bps": 5.0},
    }
    for name, raw_path in [("qlib", output.qlib_receipt_path), ("platform", platform_path)]:
        manifest.update(
            {
                name + "_receipt_path": str(paths[name].relative_to(job)),
                name + "_receipt_file_digest": hashlib.sha256(paths[name].read_bytes()).hexdigest(),
                name + "_raw_receipt_path": str(raw_path.relative_to(job)),
                name + "_raw_receipt_file_digest": hashlib.sha256(
                    raw_path.read_bytes()
                ).hexdigest(),
                name + "_receipt_digest": engines[name].receipt_digest,
            }
        )
    manifest = sealed(manifest, key="manifest_digest")
    write(job / "evidence_manifest.json", manifest)
    candidate = {
        "candidate_id": "artifact-" + output.candidate_code_digest[:16],
        "source": "d34_artifact",
        "source_path": str(output.factor_path),
        "source_digest": output.candidate_code_digest,
        "factor_id": output.factor_id,
        "universe": symbols,
        "status": "verified",
        "sleeve_id": None,
        "comparison_digest": comparison.comparison_digest,
        "performance": {
            "daily_returns": platform["daily_returns"],
            "return_dates": [day[:10] for day in platform["return_dates"]],
        },
        "evidence_ref": {
            "job_id": request.job_id,
            "run_id": request.run_id,
            "manifest_digest": manifest["manifest_digest"],
            "qlib_raw_receipt_digest": qlib["receipt_digest"],
            "platform_raw_receipt_digest": platform["receipt_digest"],
        },
    }
    return SimpleNamespace(data=SimpleNamespace(data_dir=root)), candidate, job


def test_d34_original_evidence_has_positive_path_without_fictitious_intake(tmp_path):
    settings, candidate, _ = d34_archive(tmp_path)
    before = tree(tmp_path)
    report = current_candidate_quality(settings, candidate, [candidate])
    assert report["eligible"] is True, report
    assert report["tier"] == "T2"
    assert report["n_family_members"] == 18
    assert report["return_definition"] == "net_total_return"
    assert report["return_contract"]["cost_definition"]["model"] == "qlib_combined_bps"
    binding = report["evidence_binding"]
    assert binding["selected_engine"] == "qlib"
    assert binding["exposure_engine"] == "platform"
    assert binding["selected_returns_digest"] != binding["exposure_returns_digest"]
    assert not (tmp_path / "research_intake").exists()
    assert tree(tmp_path) == before


@pytest.mark.parametrize(
    "mutation",
    ["missing_ref", "wrong_job", "missing_raw", "changed_raw", "wrong_selected", "book_returns"],
)
def test_d34_original_proof_cannot_be_replaced_by_candidate_scalars(tmp_path, mutation):
    settings, candidate, job = d34_archive(tmp_path)
    if mutation == "missing_ref":
        candidate.pop("evidence_ref")
    elif mutation == "wrong_job":
        candidate["evidence_ref"]["job_id"] = "job-wrong-original"
    elif mutation == "missing_raw":
        (job / "platform_raw.json").unlink()
    elif mutation == "changed_raw":
        (job / "platform_raw.json").write_text("{}")
    elif mutation == "book_returns":
        candidate["performance"]["daily_returns"][0] += 0.01
    else:
        request = json.loads((job / "research_request.json").read_text())
        ledger = tmp_path / "trials/trials.jsonl"
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        rows = [
            row
            for row in rows
            if not (
                row["metadata"]["job_id"] == request["job_id"]
                and row["metadata"]["experiment_id"] == "iteration-03-experiment-03"
            )
        ]
        ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
    before = tree(tmp_path)
    report = current_candidate_quality(settings, candidate, [candidate])
    assert report["eligible"] is False
    assert report["reasons"] == ["quality_evidence_unavailable"]
    assert tree(tmp_path) == before
