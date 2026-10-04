"""Explicit artificial D34 protocol specimens for isolated transaction tests.

These are not market backtests or producer attestations. They provide complete
original-file bindings to exercise the real evidence, statistics and financial
consumers. Only intended transaction fixtures call this helper; bad evidence tests
must not invoke it at hang time to repair their subject.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from quant_system.d34.engine_comparison import (
    ComparisonPolicy,
    EngineReceipt,
    compare_engine_receipts,
)
from quant_system.d34.research_request import digest_document
from quant_system.d34.worker import _research_request_digest
from quant_system.execution.assistant_remote import CandidateEvidenceRef
from quant_system.options.seller_score import is_us_market_session
from quant_system.research.trials import ResearchTrial, TrialsLedger


def _write_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, f"artificial fixture collision: {path}"
    else:
        path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _write(path, document):
    return _write_bytes(path, json.dumps(document, sort_keys=True, allow_nan=False).encode())


def _sealed(document, key="receipt_digest"):
    return {**document, key: digest_document(document)}


def _calendar(n):
    days, current = [], date(2025, 1, 2)
    while len(days) < n:
        if is_us_market_session(current):
            days.append(current.isoformat() + "T00:00:00+00:00")
        current += timedelta(days=1)
    return days


def _snapshot(root, symbols):
    raw = b"EXPLICIT ARTIFICIAL PROTOCOL FIXTURE; NOT MARKET DATA"
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
    folder = root / "_runtime/d34/snapshots" / identifier
    _write(
        folder / "manifest.json",
        {
            **identity,
            "snapshot_id": identifier,
            "snapshot_digest": digest,
            "provider_receipt": provider,
            "observed_at": "2026-10-03T00:00:00+00:00",
            "parquet_file": "ohlcv.parquet",
        },
    )
    _write_bytes(folder / "ohlcv.parquet", raw)
    return identifier, digest


def d34_candidate_kwargs(
    settings,
    *,
    candidate_id,
    source_path,
    source_digest,
    factor_id,
    universe,
    daily_returns,
    return_dates=None,
    turnover_period=None,
    top_n=None,
    strategy_id=None,
    objective="Artificial transaction fixture",
    primary_request=None,
    primary_source_path=None,
    include_specimen=False,
):
    """Build bound originals and return kwargs for real record_verified_candidate.

    Input return values are kept exactly in both engines. Supplied dates and
    turnover are not repaired; omitted dates get explicit artificial XNYS dates
    for existing transaction fixtures. In particular None turnover stays None.
    The returned canonical source path has the original bytes/digest; callers
    testing subsequent source corruption must modify that returned path.
    """
    root = Path(settings.data.data_dir).resolve()
    source = Path(source_path).read_bytes()
    assert hashlib.sha256(source).hexdigest() == source_digest
    values = list(daily_returns)
    assert values, "use the original evidence-missing fixture for an empty return series"
    days = list(return_dates) if return_dates is not None else _calendar(len(values))
    assert len(days) == len(values)
    symbols = list(universe)
    identity = digest_document(
        {
            "candidate": candidate_id,
            "source": source_digest,
            "factor_id": factor_id,
            "symbols": symbols,
            "returns": values,
            "dates": days,
            "turnover": turnover_period,
            "top_n": top_n,
            "strategy_id": strategy_id,
        }
    )
    snapshot_id, snapshot_digest = _snapshot(root, symbols)
    rows, selected, specimen = [], None, None
    for cohort in range(2):
        job_id = f"job-artificial-{identity[:24]}-{cohort}"
        run_id = f"attempt-artificial-{identity[:24]}-{cohort}"
        job = root / "_runtime/d34/jobs" / job_id
        research = job / "research/research-artificial"
        request = {
            "contract": "hqa.d34_research_request/v2",
            "job_id": job_id,
            "run_id": run_id,
            "resource_envelope_id": "local-paper-research-v1",
            "resource_policy_digest": "a" * 64,
            "snapshot_id": snapshot_id,
            "snapshot_digest": snapshot_digest,
            "snapshot_source": "futu",
            "provider_uri": "/artificial/no-provider",
            "universe": symbols,
            "calendar": days,
            "max_iterations": 3,
            "experiments_per_iteration": 3,
            "top_k": top_n if top_n is not None else 1,
            "initial_cash": 100000.0,
            "budget_reservation_usd": 0,
            "objective": "Artificial protocol specimen; no research was run",
        }
        if cohort == 0 and primary_request is not None:
            request.update(primary_request)
            assert request["universe"] == symbols and request["calendar"] == days
            assert request["snapshot_id"] == snapshot_id
            assert request["snapshot_digest"] == snapshot_digest
            job_id, run_id = request["job_id"], request["run_id"]
            job = root / "_runtime/d34/jobs" / job_id
            research = (
                Path(primary_source_path).parent
                if primary_source_path
                else (job / "research/research-artificial")
            )
            assert research.resolve().is_relative_to(job / "research")
        request_digest = _research_request_digest(request)
        request_path = job / "research_request.json"
        if cohort == 0 and primary_request is not None and request_path.exists():
            # Explicit fixture preparation, before any evidence is certified.
            # Preserve every supplied old request field; only missing protocol
            # fields are added, never rewriting an original production request.
            old_request = json.loads(request_path.read_text())
            assert all(request.get(k) == v for k, v in old_request.items())
            request_path.write_text(json.dumps(request, sort_keys=True, allow_nan=False))
        else:
            _write(request_path, request)
        canonical_source = (
            Path(primary_source_path)
            if cohort == 0 and primary_source_path
            else (research / "candidate_factor.py")
        )
        _write_bytes(canonical_source, source)
        config = {
            "contract": "hqa.d34_qlib_config/v1",
            "expression": "ARTIFICIAL_SPECIMEN",
            "universe": symbols,
            "start_time": days[0],
            "end_time": days[-1],
            "execution_timing": "next_open",
            "exchange": {
                "open_cost": 0.0006,
                "close_cost": 0.0006,
                "min_cost": 0,
                "deal_price": "$open",
                "trade_unit": 1,
                "limit_threshold": None,
            },
        }
        trials, attempts = [], []
        experiment_count = (
            1
            if request.get("formula")
            else (request["max_iterations"] * request["experiments_per_iteration"])
        )
        for index in range(experiment_count):
            experiment = f"iteration-{index // 3 + 1:02}-experiment-{index % 3 + 1:02}"
            sample = (
                values
                if cohort == 0 and index == experiment_count - 1
                else [0.005 * math.sin(i * 0.73 + index + cohort * 9) for i in range(len(values))]
            )
            evaluation = {
                "schema": "hqa.d34_experiment_evaluation/v1",
                "return_definition": "net_total_return",
                "frequency": "daily",
                "initial_cash": request["initial_cash"],
                "request_digest": request_digest,
                "snapshot_id": snapshot_id,
                "snapshot_digest": snapshot_digest,
                "snapshot_source": "futu",
                "universe_digest": digest_document(symbols),
                "calendar_digest": digest_document(days),
                "qlib_config": config,
                "qlib_config_digest": digest_document(config),
                "implementation": {
                    "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "runner_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                },
            }
            proposal = {
                "operator": "artificial_protocol_specimen",
                "serial": index,
                "claim": "not produced by a market runner",
            }
            observation = {
                "experiment_id": experiment,
                "status": "succeeded",
                "proposal": proposal,
                "returns_digest": digest_document({"values": sample, "dates": days}),
                "return_dates_digest": digest_document(days),
                "evaluation_contract": evaluation,
            }
            observation_sha = _write(
                research / "experiments" / experiment / "receipt.json", observation
            )
            subject = "artificial:" + experiment
            item = {
                "experiment_id": experiment,
                "subject": subject,
                "proposal_digest": digest_document(proposal),
                "experiment_receipt_digest": observation_sha,
                "daily_returns": sample,
                "evaluation_contract": evaluation,
            }
            trials.append(item)
            attempts.append({"experiment_id": experiment, "status": "succeeded"})
            rows.append(
                ResearchTrial.record(
                    kind="d34_experiment",
                    subject=subject,
                    universe=symbols,
                    daily_returns=sample,
                    window_start=days[0][:10],
                    window_end=days[-1][:10],
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
            )
        selected_trial = trials[-1]
        batch = _sealed(
            {
                "contract": "hqa.d34_experiment_trial_batch/v1",
                "job_id": job_id,
                "request_digest": request_digest,
                "universe": symbols,
                "universe_digest": digest_document(symbols),
                "calendar_digest": digest_document(days),
                "return_dates": days,
                "experiment_count": experiment_count,
                "successful_experiment_count": experiment_count,
                "attempts": attempts,
                "selected_experiment": selected_trial["experiment_id"],
                "experiments": trials,
            }
        )
        batch_path = job / f"research/experiment-trials-{request_digest[:32]}.json"
        batch_sha = _write(batch_path, batch)
        selected_values = selected_trial["daily_returns"]
        raw_common = {
            "contract": "hqa.d34_engine_receipt/v1",
            "job_id": job_id,
            "run_id": run_id,
            "factor_id": factor_id,
            "candidate_code_digest": source_digest,
            "snapshot_id": snapshot_id,
            "snapshot_digest": snapshot_digest,
            "universe_digest": digest_document(symbols),
            "calendar_digest": digest_document(days),
            "target_weights_digest": digest_document({"artificial": symbols}),
            "daily_returns": selected_values,
            "return_dates": days,
            "terminal_nav": math.prod(1 + x for x in selected_values),
            "terminal_weights": {symbols[0]: 0.99},
            "metrics": {"turnover": turnover_period},
            "qlib_config": config,
            "qlib_config_digest": digest_document(config),
            "selected_experiment": selected_trial["experiment_id"],
        }
        engines, raw_docs, paths = {}, {}, {}
        for name in ("qlib", "platform"):
            raw = _sealed({**raw_common, "engine": name})
            raw_path = research / f"{name}_receipt.json"
            raw_sha = _write(raw_path, raw)
            engine = {
                key: raw[key]
                for key in (
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
                )
            }
            bound = _sealed(
                {
                    "contract": "hqa.d34_bound_engine_receipt/v2",
                    "job_id": job_id,
                    "run_id": run_id,
                    "resource_envelope_id": request["resource_envelope_id"],
                    "engine": name,
                    "raw_receipt_path": str(raw_path.relative_to(job)),
                    "raw_receipt_file_digest": raw_sha,
                    "engine_receipt": engine,
                    "turnover_period": turnover_period,
                }
            )
            bound_path = job / f"{name}_bound.json"
            bound_sha = _write(bound_path, bound)
            engines[name] = EngineReceipt(**engine)
            raw_docs[name] = raw
            paths[name] = (raw_path, raw_sha, bound_path, bound_sha)
        comparison = compare_engine_receipts(
            qlib=engines["qlib"], platform=engines["platform"], policy=ComparisonPolicy.initial()
        )
        assert comparison.accepted
        manifest = {
            "contract": "hqa.d34_research_evidence/v1",
            "job_id": job_id,
            "run_id": run_id,
            "research_request_digest": digest_document(request),
            "candidate_code_path": str(canonical_source.relative_to(job)),
            "candidate_code_digest": source_digest,
            "comparison_digest": comparison.comparison_digest,
            "cost_model": {"commission_bps": 1.0, "slippage_bps": 5.0},
        }
        for name, (raw_path, raw_sha, bound_path, bound_sha) in paths.items():
            manifest.update(
                {
                    name + "_receipt_path": str(bound_path.relative_to(job)),
                    name + "_receipt_file_digest": bound_sha,
                    name + "_raw_receipt_path": str(raw_path.relative_to(job)),
                    name + "_raw_receipt_file_digest": raw_sha,
                    name + "_receipt_digest": engines[name].receipt_digest,
                }
            )
        manifest = _sealed(manifest, key="manifest_digest")
        _write(job / "evidence_manifest.json", manifest)
        _write(
            research / "research_receipt.json",
            {
                "contract": "hqa.d34_research_result/v2",
                "job_id": job_id,
                "run_id": run_id,
                "request_digest": request_digest,
                "selected_experiment": selected_trial["experiment_id"],
                "qlib_receipt_file": "qlib_receipt.json",
                "qlib_receipt_digest": engines["qlib"].receipt_digest,
                "qlib_receipt_file_digest": paths["qlib"][1],
                "qlib_config_digest": digest_document(config),
                "experiment_trials_path": str(batch_path),
                "experiment_trials_digest": batch["receipt_digest"],
                "experiment_trials_file_digest": batch_sha,
                "experiment_count": experiment_count,
                "successful_experiment_count": experiment_count,
            },
        )
        if cohort == 0:
            selected = dict(
                candidate_id=candidate_id,
                objective=objective,
                source="d34_artifact",
                source_path=str(canonical_source),
                source_digest=source_digest,
                factor_id=factor_id,
                universe=symbols,
                comparison_digest=comparison.comparison_digest,
                daily_returns=values,
                return_dates=days,
                turnover_period=turnover_period,
                evidence_ref=CandidateEvidenceRef(
                    job_id=job_id,
                    run_id=run_id,
                    manifest_digest=manifest["manifest_digest"],
                    qlib_raw_receipt_digest=engines["qlib"].receipt_digest,
                    platform_raw_receipt_digest=engines["platform"].receipt_digest,
                ),
            )
            specimen = {
                "request": request,
                "comparison": asdict(comparison),
                "manifest_fields": {k: v for k, v in manifest.items() if k != "manifest_digest"},
                "qlib_engine": asdict(engines["qlib"]),
                "platform_engine": asdict(engines["platform"]),
                "qlib_raw_path": paths["qlib"][0],
                "platform_raw_path": paths["platform"][0],
                "qlib_bound_path": paths["qlib"][2],
                "platform_bound_path": paths["platform"][2],
                "qlib_config_digest": digest_document(config),
                "factor_path": canonical_source,
            }
    TrialsLedger(root / "trials").append_many(rows)
    if top_n is not None:
        selected["top_n"] = top_n
    if strategy_id is not None:
        selected["strategy_id"] = strategy_id
    return {**specimen, "candidate_kwargs": selected} if include_specimen else selected


def prepare_bound_chat_specimen(
    settings,
    *,
    job_root,
    request_doc,
    factor_path,
    daily_returns,
    return_dates=None,
    turnover_period=None,
):
    """Prepare full originals under the existing artificial chat job's identity.

    The caller keeps its request/operation/input binding and uses these actual
    engine/comparison fields when sealing the terminal recovery, cycle and final
    evidence manifest. No chat job is created by this helper. Do not use the
    temporary candidate_kwargs evidence_ref after the caller seals its final
    enriched manifest; the real chat consumer derives that final reference.
    """
    root = Path(settings.data.data_dir).resolve()
    job_root, factor_path = Path(job_root).resolve(), Path(factor_path).resolve()
    assert job_root == root / "_runtime/d34/jobs" / request_doc["job_id"]
    assert factor_path.is_relative_to(job_root / "research")
    source = factor_path.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    match = re.search(r"factor_id\s*=\s*['\"]([a-z][a-z0-9_-]*)['\"]", source.decode())
    assert match, "fixture factor must keep its declared source identity"
    days = list(return_dates) if return_dates is not None else _calendar(len(daily_returns))
    snapshot_id, snapshot_digest = _snapshot(root, list(request_doc["universe"]))
    prepared = {**request_doc}
    for key, value in {
        "snapshot_id": snapshot_id,
        "snapshot_digest": snapshot_digest,
        "calendar": days,
    }.items():
        assert key not in prepared or prepared[key] == value
        prepared[key] = value
    return d34_candidate_kwargs(
        settings,
        candidate_id="artifact-" + digest[:16],
        source_path=factor_path,
        source_digest=digest,
        factor_id=match.group(1),
        universe=prepared["universe"],
        daily_returns=daily_returns,
        return_dates=days,
        turnover_period=turnover_period,
        top_n=prepared.get("top_k"),
        objective=prepared["objective"],
        primary_request=prepared,
        primary_source_path=factor_path,
        include_specimen=True,
    )
