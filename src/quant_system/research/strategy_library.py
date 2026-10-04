"""Saved strategy recipes and explicit validation before canonical paper admission."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pandas as pd
from pydantic import ValidationError

from quant_system.config.settings import Settings
from quant_system.d34.engine_comparison import (
    ComparisonPolicy,
    EngineReceipt,
    compare_engine_receipts,
)
from quant_system.execution import assistant_remote
from quant_system.execution.strategy_replacement import (
    LEGACY_PERFORMANCE_SCOPE_ACROSS_VERSIONS,
    PERFORMANCE_SCOPE_ACROSS_VERSIONS,
)
from quant_system.factors.registry import build_factor_registry
from quant_system.research.evaluation_service import _file_hash, _hash, _view, _write
from quant_system.research.strategy_definition import (
    StrategyDefinition,
    definition_from_backtest,
    definition_from_study,
    formula_factor_id,
    validate_definition,
)
from quant_system.research.strategy_runtime import evaluate_definition
from quant_system.research.strategy_study_service import (
    _collect_prices,
    _docker,
    _run_directory,
    read_studies,
)
from quant_system.research.study_reconciliation import reconcile_saved_study
from quant_system.research.trials import ResearchTrial, TrialsLedger, evaluate_candidate_dsr
from quant_system.research.validation_receipts import receipt_bindings, verify_validation_receipt

_ID = re.compile(r"strategy-[0-9a-f]{24}\Z")


def _root(settings):
    return settings.data.data_dir / "strategy_library"


def _load_report(settings, run_id):
    directory = _run_directory(settings, run_id)
    report = json.loads((directory / "report.json").read_text())
    if report.get("run_id") != run_id:
        raise ValueError("strategy_origin_run_mismatch")
    return report, directory


def _directory(settings, strategy_id):
    if not _ID.fullmatch(strategy_id):
        raise ValueError("strategy_id_invalid")
    return _root(settings) / strategy_id


def read_strategy(settings: Settings, strategy_id: str) -> dict:
    directory = _directory(settings, strategy_id)
    value = json.loads((directory / "entry.json").read_text())
    try:
        definition = validate_definition(value["definition"])
        if _file_hash(directory / "definition.json") != value["source_sha256"]:
            raise ValueError("strategy_source_file_changed")
        if definition.content_digest != value["definition_digest"]:
            raise ValueError("strategy_definition_changed")
    except ValueError as exc:
        error = (
            "strategy_definition_schema_changed" if isinstance(exc, ValidationError) else str(exc)
        )
        return {**_view(value), "status": "stale", "error": error}
    if value.get("status") == "validated":
        try:
            validation = value["validation"]
            if not re.fullmatch(r"validation-[0-9a-f]{32}", validation["run_id"]):
                raise ValueError("strategy_validation_id_invalid")
            admission_receipt = _read_admission(settings, value)
            authoritative = (
                admission_receipt is not None and admission_receipt["mode"] == "authoritative"
            )
            if authoritative and admission_receipt.get("validated_tier") != "T2":
                raise ValueError("admission_v2_unfunded_tier")
            verify_validation_receipt(
                directory / "validations" / validation["run_id"] / "validation.json",
                expected_sha=value.get("validation_sha256"),
                definition_digest=definition.content_digest,
                require_admission=not authoritative,
            )
        except (ValueError, OSError, KeyError, TypeError):
            value.update(
                status="validation_failed", error="strategy_validation_receipt_requires_refresh"
            )
    if value.get("candidate_id"):
        candidate = next(
            (
                c
                for c in assistant_remote.load_book(settings)["candidates"]
                if c.get("candidate_id") == value["candidate_id"]
            ),
            None,
        )
        if candidate and candidate.get("status") == "hung":
            value.update(status="paper_running", sleeve_id=candidate.get("sleeve_id"))
        elif candidate and candidate.get("status") == "superseded":
            value.update(status="superseded", replaced_by=candidate.get("replaced_by"),
                         sleeve_id=candidate.get("sleeve_id"))
        if candidate:
            for field in (
                "replacement_id", "replaced_by", "replaces", "performance_scope",
                "current_version_performance", "replacement_committed_at",
            ):
                if candidate.get(field) is not None:
                    value[field] = candidate[field]
            if value.get("performance_scope") == LEGACY_PERFORMANCE_SCOPE_ACROSS_VERSIONS:
                # Candidates admitted before the token was unified still carry
                # the old spelling, which the owner UI does not test for.
                value["performance_scope"] = PERFORMANCE_SCOPE_ACROSS_VERSIONS
    from quant_system.research.definition_paper import definition_schedule_available

    value["execution_ready"] = definition_schedule_available()
    value["activation_blockers"] = (
        [] if value["execution_ready"] else ["strategy_definition_schedule_unavailable"]
    )
    if value.get("status") == "superseded":
        value["activation_blockers"].append("strategy_version_replaced")
    return _view(value)


def list_strategies(settings: Settings) -> dict:
    items = []
    for path in sorted(_root(settings).glob("strategy-*/entry.json")):
        try:
            items.append(read_strategy(settings, path.parent.name))
        except (OSError, ValueError, KeyError):
            items.append(
                {"strategy_id": path.parent.name, "title": "记录无法读取", "status": "stale"}
            )
    return {"items": items}


def factor_options(settings):
    from quant_system.research.factor_catalog import formula_components

    registry = build_factor_registry()
    options = [
        {
            "factor_id": f.factor_id,
            "label": f.display_name_zh or f.factor_name,
            "expression": None,
            "lookback": f.lookback,
            "direction": "lower_is_better"
            if f.direction == "lower_is_better"
            else "higher_is_better",
            "origin": registry.origins()[f.factor_id],
        }
        for f in registry.list_metadata()
    ]
    report = read_studies(settings)
    for proposal in (report.get("discovery") or {}).get("proposals", []):
        if proposal.get("status") != "frozen":
            continue
        options.append(
            {
                "factor_id": formula_factor_id(proposal["expression"]),
                "label": proposal["title"],
                "expression": proposal["expression"],
                "lookback": proposal["lookback"],
                "direction": "higher_is_better",
                "origin": "research_proposal",
            }
        )
    for component in formula_components(settings):
        existing = next(
            (row for row in options if row["factor_id"] == component["factor_id"]), None
        )
        if existing is not None:
            existing.update(
                source_refs=component["source_refs"], research_only=True,
                status=component["status"], source_digest=component["source_digest"],
            )
        else:
            options.append(component)
    return {"factors": options}


def compose_strategy(settings, payload):
    if payload.get("kind", "factor_blend") != "factor_blend":
        raise ValueError("strategy_compose_kind_invalid")
    values = {key: value for key, value in payload.items() if key != "kind"}
    definition = StrategyDefinition(kind="factor_blend", history_start="2015-01-01", **values)
    end = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    start = "2018-01-01"
    return _save_definition(settings, definition, {"type": "compose", "start": start, "end": end})


def _save_definition(settings, definition, origin):
    strategy_id = "strategy-" + definition.content_digest[:24]
    directory = _directory(settings, strategy_id)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "write.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (directory / "entry.json").exists():
            return read_strategy(settings, strategy_id)
        _write(directory / "definition.json", definition.model_dump(mode="json"))
        value = {
            "strategy_id": strategy_id,
            "title": definition.title,
            "definition_digest": definition.content_digest,
            "source_sha256": _file_hash(directory / "definition.json"),
            "definition": definition.model_dump(mode="json"),
            "origin": origin,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "draft",
            "validation": None,
            "candidate_id": None,
            "sleeve_id": None,
            "error": None,
        }
        _write(directory / "entry.json", value)
    return read_strategy(settings, strategy_id)


def import_study(settings, run_id, profile_id, *, title=None):
    report, directory = _load_report(settings, run_id)
    results = [*report["results"], *(report.get("discovery") or {}).get("results", [])]
    result = next((r for r in results if r["profile"]["id"] == profile_id), None)
    if result is None or result.get("status") != "available":
        raise ValueError("strategy_study_result_unavailable")
    discovery = report.get("discovery") or {}
    if profile_id.startswith("rdagent:") and discovery.get("origin_run_id", run_id) != run_id:
        raise ValueError("strategy_discovery_requires_original_run")
    prices_path = directory / "prices.parquet"
    if _file_hash(prices_path) != report["source"]["prices_sha256"]:
        raise ValueError("strategy_input_prices_changed")
    prices = pd.read_parquet(prices_path)
    history_start = pd.to_datetime(
        prices.loc[prices.symbol == result["profile"]["benchmark_symbol"], "timestamp"], utc=True
    ).min()
    if pd.isna(history_start):
        raise ValueError("strategy_benchmark_history_missing")
    definition = definition_from_study(result, history_start=history_start.date().isoformat())
    if title:
        definition = definition.model_copy(update={"title": title})
    return _save_definition(
        settings,
        definition,
        {
            "type": "study",
            "run_id": run_id,
            "profile_id": profile_id,
            "start": result["start"],
            "end": result["end"],
            "prices_sha256": report["source"]["prices_sha256"],
        },
    )


def import_backtest(settings, run_id, *, title=None):
    if not re.fullmatch(r"backtest-[a-zA-Z0-9_-]+", run_id):
        raise ValueError("backtest_id_invalid")
    path = settings.data.data_dir / "api_runs" / "backtests" / run_id / "metadata.json"
    metadata = json.loads(path.read_text())
    request = metadata["request"]
    if metadata.get("source") != "futu":
        raise ValueError("strategy_requires_real_futu_backtest")
    symbols = metadata.get("symbols") or request.get("symbols")
    if not symbols:
        raise ValueError("backtest_universe_not_recorded")
    prices_path = path.parent / "backtests" / "input_prices.parquet"
    if not prices_path.is_file() or not metadata.get("input_prices_sha256"):
        raise ValueError("backtest_history_snapshot_missing_rerun_required")
    if _file_hash(prices_path) != metadata["input_prices_sha256"]:
        raise ValueError("backtest_history_snapshot_changed")
    history_start = pd.read_parquet(prices_path).timestamp.min()
    definition = definition_from_backtest(
        request, symbols, title or "我的多因子策略", history_start=str(history_start)[:10]
    )
    return _save_definition(
        settings,
        definition,
        {
            "type": "backtest",
            "run_id": run_id,
            "start": request["start"],
            "end": request["end"],
            "prices_sha256": metadata["input_prices_sha256"],
        },
    )


def _canonical_column(column):
    """One column normalized to dtype-stable Python values."""
    if pd.api.types.is_numeric_dtype(column) and not pd.api.types.is_bool_dtype(column):
        return [None if pd.isna(value) else float(value) for value in column]
    if pd.api.types.is_datetime64_any_dtype(column):
        return [None if pd.isna(value) else pd.Timestamp(value).isoformat() for value in column]
    return [None if pd.isna(value) else str(value) for value in column]


def _prices_content_digest(prices: pd.DataFrame) -> str:
    """Identity of a price frame's content, never of the file that stores it.

    Trial identity must survive a pandas/pyarrow upgrade that rewrites the same
    numbers into different parquet bytes, so column order, index values and
    every cell are normalized through fixed dtypes before hashing.
    """
    columns = sorted(str(name) for name in prices.columns)
    ordered = prices.copy()
    ordered.columns = [str(name) for name in ordered.columns]
    ordered = ordered[columns]
    return _hash(
        {
            "columns": columns,
            "index": [str(value) for value in ordered.index],
            "values": {name: _canonical_column(ordered[name]) for name in columns},
        }
    )


def _validation_trial_identity(definition_digest, prices, result) -> str:
    """Input identity of one definition validation, from frame content."""
    return _hash(
        {
            "definition": definition_digest,
            "prices": _prices_content_digest(prices),
            "start": result["start"],
            "end": result["end"],
            "cash": 10_000,
        }
    )


def _returns(result):
    curve = pd.DataFrame(result["curve"])
    initial = result.get("evaluation_initial_cash", 100_000.0)
    returns = curve.equity.pct_change(fill_method=None)
    returns.iloc[0] = curve.equity.iloc[0] / initial - 1
    return returns.tolist(), curve.date.tolist()


def _verified_legacy_trial_curve(settings, result, prices_digest):
    """Use only the same strategy's already bound, verified validation evidence."""
    try:
        digest = result["definition_digest"]
        directory = _directory(settings, "strategy-" + digest[:24])
        entry = json.loads((directory / "entry.json").read_text())
        previous = entry["validation"]
        if entry["definition_digest"] != digest or entry["strategy_id"] != directory.name:
            return False
        if not re.fullmatch(r"validation-[0-9a-f]{32}", previous["run_id"]):
            return False
        run = directory / "validations" / previous["run_id"]
        verified = verify_validation_receipt(
            run / "validation.json", expected_sha=entry.get("validation_sha256"),
            definition_digest=digest,
            comparison_digest=previous.get("comparison", {}).get("comparison_digest"),
        )
        original = json.loads((run / "platform-result.json").read_text())
        return (
            verified["run_id"] == run.name
            # The receipt already binds the file bytes; the frame content is what
            # the trial identity is made of, and it survives a writer upgrade.
            and _prices_content_digest(pd.read_parquet(run / "prices.parquet")) == prices_digest
            and original["definition_digest"] == digest
            and original["profile"]["id"] == result["profile"]["id"]
            and original["start"] == result["start"]
            and original["end"] == result["end"]
            and original.get("evaluation_initial_cash", 100_000)
            == result.get("evaluation_initial_cash", 100_000)
            and _hash(original["curve"]) == _hash(result["curve"])
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _record_trial(
    settings, result, run_id, universe, *, study_prices_digest=None, validation_prices_digest=None,
):
    content_addressed = run_id.startswith("recorded-study-")
    if content_addressed and run_id != "recorded-study-" + _hash({
        "profile": result["profile"], "prices": study_prices_digest, "curve": result["curve"],
    }):
        raise ValueError("trial_run_id_conflict")
    bound_validation = (
        run_id.startswith("definition-validation-") and validation_prices_digest is not None
    )
    if bound_validation and (
        result.get("evaluation_initial_cash", 100_000) != 10_000
        or run_id != "definition-validation-" + _hash({
            "definition": result.get("definition_digest"), "prices": validation_prices_digest,
            "start": result["start"], "end": result["end"], "cash": 10_000,
        })
    ):
        raise ValueError("trial_run_id_conflict")
    values, dates = _returns(result)
    trial = ResearchTrial.record(
        kind="platform_backtest",
        subject=result["profile"]["id"],
        universe=universe,
        daily_returns=values,
        window_start=dates[0],
        window_end=dates[-1],
        source="futu",
        metadata={
            "run_id": run_id,
            "strategy_definition_digest": result.get("definition_digest"),
            "membership_mode": "static_snapshot",
            **({"equity_curve_digest": _hash(result["curve"])} if bound_validation else {}),
        },
    )
    ledger = TrialsLedger(settings.data.data_dir / "trials")
    if content_addressed or bound_validation:
        existing = next((row for row in ledger.list() if row.trial_id == trial.trial_id), None)
        if existing is not None:
            reusable = content_addressed or (
                bound_validation
                and existing.metadata.get("equity_curve_digest")
                == trial.metadata["equity_curve_digest"]
            )
            if bound_validation and "equity_curve_digest" not in existing.metadata:
                reusable = _verified_legacy_trial_curve(settings, result, validation_prices_digest)
                if reusable:
                    trial = trial.model_copy(update={"metadata": {
                        key: value for key, value in trial.metadata.items()
                        if key != "equity_curve_digest"
                    }})
            # The input identity and actual curve are already bound to this
            # trial. Reuse its recorded moments: Python 3.12 changed float sum,
            # so recalculation can differ in final bits despite identical data.
            moments = {"ts", "sharpe", "sharpe_annual", "skewness", "kurtosis"}
            if reusable and (
                existing.model_dump(exclude=moments) == trial.model_dump(exclude=moments)
            ):
                trial = existing
    ledger.append(trial)


def _record_study_family(settings, universe):
    """Count saved successful alternatives, including losers, before admission."""
    for path in (settings.data.data_dir / "strategy_studies" / "runs").glob("*/report.json"):
        report = json.loads(path.read_text())
        for result in [
            *report.get("results", []),
            *(report.get("discovery") or {}).get("results", []),
        ]:
            if result.get("status") != "available" or set(result["profile"]["symbols"]) != set(
                universe
            ):
                continue
            if result.get("source") != "futu" or result.get("price_adjustment") != "qfq":
                continue
            prices_digest = (
                (report.get("discovery") or {}).get("prices_sha256")
                if result["profile"]["id"].startswith("rdagent:")
                else None
            )
            prices_digest = prices_digest or report.get("source", {}).get("prices_sha256")
            identity = _hash(
                {
                    "profile": result["profile"],
                    "prices": prices_digest,
                    "curve": result["curve"],
                }
            )
            _record_trial(
                settings, result, "recorded-study-" + identity, universe,
                study_prices_digest=prices_digest,
            )


def _comparison(prices, result, qlib, definition):
    values, dates = _returns(result)
    snapshot = _hash(prices.to_json(orient="split", date_format="iso"))
    weights_digest = _hash(
        [{k: r.get(k) for k in ("trade_date", "targets")} for r in result["signals"]]
    )
    common = {
        "snapshot_digest": snapshot,
        "universe_digest": _hash(definition.symbols),
        "calendar_digest": _hash(dates),
        "target_weights_digest": weights_digest,
        "return_dates": tuple(dates),
    }
    if qlib["return_dates"] != dates:
        raise ValueError("strategy_qlib_calendar_mismatch")
    initial = result["evaluation_initial_cash"]
    reconciliation = reconcile_saved_study(result, prices, None)
    if reconciliation["status"] != "matched":
        raise ValueError("strategy_platform_accounting_mismatch")
    terminal_weights = {
        r["symbol"]: r["market_value"] / reconciliation["equity"]
        for r in reconciliation["positions"]
    }
    platform = EngineReceipt(
        engine="platform",
        **common,
        daily_returns=tuple(values),
        terminal_nav=result["curve"][-1]["equity"] / initial,
        terminal_weights=terminal_weights,
        receipt_digest=_hash(result),
    )
    other = EngineReceipt(
        engine="qlib",
        **common,
        daily_returns=tuple(qlib["daily_returns"]),
        terminal_nav=qlib["terminal_nav"] / initial,
        terminal_weights=qlib["terminal_weights"],
        receipt_digest=_hash(qlib),
    )
    from dataclasses import asdict

    return asdict(
        compare_engine_receipts(qlib=other, platform=platform, policy=ComparisonPolicy.initial())
    )


def find_evaluation(settings, strategy_id, evaluation):
    from quant_system.research.strategy_evaluation_instance import find_evaluation as find

    entry = find(settings, _directory(settings, strategy_id), evaluation)
    if entry is not None:
        _read_admission(settings, entry)
    return entry


def _read_admission(settings, entry):
    from quant_system.research import admission_v2

    if not admission_v2.candidate_uses_protocol(entry):
        return None
    return admission_v2.read_bound_receipt(
        settings, entry.get("admission_v2"), definition_digest=entry["definition_digest"],
        validation_sha256=entry.get("validation_sha256"), source_sha256=entry["source_sha256"],
    )


def _attach_admission(settings, entry, run, protocol):
    from quant_system.research import admission_v2
    from quant_system.research.admission_qualification_flow import ensure_qualifications

    try:
        flow = ensure_qualifications(settings, validation_path=run / "validation.json", protocol=protocol)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        flow = {"status": "not_evaluated", "reason": str(exc), "cached": False}
    entry["qualification_flow"] = flow
    if (flow.get("cached") and flow.get("status") != "registered"
            and entry.get("admission_v2")):
        # A failed fixed attempt at identical code/input/recipe is not a request
        # to rerun engines or producer checks every worker tick.
        return _read_admission(settings, entry)
    receipt = admission_v2.evaluate_validation(
        settings, protocol=protocol, validation_path=run / "validation.json",
        expected_validation_sha=entry["validation_sha256"],
        definition_digest=entry["definition_digest"], source_sha256=entry["source_sha256"],
        evaluation=entry.get("evaluation"), book=assistant_remote.load_book(settings),
        _qualification_execution=flow.get("status") in {"registered", "not_configured"},
    )
    entry["admission_v2"] = admission_v2.write_receipt(run, receipt)
    if protocol["mode"] == "authoritative":
        entry["status"] = (
            "validated" if receipt["status"] == "passed" and receipt["validated_tier"] == "T2"
            else "validation_failed"
        )
        if entry["status"] != "validated":
            entry["candidate_id"] = None
    return receipt


def _publish_validation_candidate(settings, entry, run, definition, result):
    from quant_system.research import admission_v2

    values, dates = _returns(result)
    descriptor = entry.get("admission_v2")
    identity = (
        admission_v2.candidate_id(entry["validation_sha256"], descriptor) if descriptor
        else "strategy-" + entry["validation_sha256"][:24]
    )
    candidate = assistant_remote.record_verified_candidate(
        settings, candidate_id=identity, objective=definition.title,
        source="strategy_definition", source_path=str(run.parent.parent / "definition.json"),
        source_digest=entry["source_sha256"],
        factor_id="definition_" + entry["definition_digest"][:24],
        universe=list(definition.symbols),
        comparison_digest=entry["validation"]["comparison"]["comparison_digest"],
        daily_returns=values, return_dates=dates, turnover_period=result["metrics"]["turnover"],
        top_n=definition.top_n, verification_receipt_digest=entry["validation_sha256"],
        **({"admission_ref": descriptor} if descriptor is not None else {}),
    )
    entry["candidate_id"] = candidate["candidate_id"]


def refresh_admission(settings, strategy_id, evaluation, protocol, *, publish_entry):
    """Re-evaluate new sidecar only. Never replay engines or register another trial."""
    directory = _directory(settings, strategy_id)
    with (directory / "validation.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entry = find_evaluation(settings, strategy_id, evaluation)
        if entry is None or "admission_v2" not in entry:
            raise ValueError("admission_v2_saved_evaluation_required")
        if entry["admission_v2"]["protocol_digest"] != protocol["protocol_digest"]:
            raise ValueError("admission_v2_protocol_binding_mismatch")
        if read_strategy(settings, strategy_id)["status"] == "paper_running":
            raise ValueError("admission_v2_running_refresh_forbidden")
        run = directory / "validations" / entry["validation"]["run_id"]
        _attach_admission(settings, entry, run, protocol)
        if entry["status"] == "validated" and publish_entry:
            definition = validate_definition(entry["definition"])
            _publish_validation_candidate(
                settings, entry, run, definition,
                json.loads((run / "platform-result.json").read_text()),
            )
        _write(run / "evaluation-entry.json", entry)
        if publish_entry:
            _write(directory / "entry.json", entry)
        return _view(entry)


def evaluation_recovery_ready(settings, strategy_id, evaluation):
    from quant_system.research.strategy_evaluation_instance import computation_idle

    return computation_idle(settings, _directory(settings, strategy_id), evaluation)


def _parallel_cost_replay(run, prices, result, definition):
    """Append a fixed-signal cost sidecar; never replace original metrics/gates."""
    from quant_system.backtest.models import BacktestConfig
    from quant_system.research.cost_replay import (
        cost_replay_input_digest,
        cost_replay_source_identity,
        replay_cost_scenarios,
    )

    path = run / "parallel-cost-replay.json"
    if path.exists():
        raise ValueError("parallel_cost_replay_already_exists")
    try:
        inputs = {
            "prices": prices, "base_result": result,
            "target_schedule": {row["trade_date"]: row["targets"] for row in result["signals"]},
            "config": BacktestConfig(
                initial_cash=10_000, commission_bps=definition.commission_bps,
                slippage_bps=definition.slippage_bps,
                min_order_value=definition.min_order_value,
                whole_share_orders=definition.whole_share_orders,
            ),
            "source_identity": cost_replay_source_identity(),
        }
        report = replay_cost_scenarios(
            **inputs, expected_input_digest=cost_replay_input_digest(**inputs),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report = {"schema": "parallel_cost_replay_failure/v1", "status": "not_evaluated",
                  "reason": str(exc), "capital_authorized": False}
    _write(path, report)
    return {"path": str(path), "sha256": _file_hash(path),
            "status": report["status"], "authority": "parallel_only"}


def validate_strategy(
    settings, strategy_id, expected_digest, *, evaluation=None, publish_entry=True,
    admission_context=None,
):
    directory = _directory(settings, strategy_id)
    with (directory / "validation.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if evaluation is not None else 0))
        entry = read_strategy(settings, strategy_id)
        if entry["status"] == "stale" or entry["definition_digest"] != expected_digest:
            raise ValueError("strategy_definition_changed")
        if entry["status"] == "paper_running" and evaluation is None:
            return entry
        if entry["status"] == "paper_running" and publish_entry:
            raise ValueError("strategy_running_evaluation_must_be_detached")
        definition = validate_definition(entry["definition"])
        if evaluation is not None:
            from quant_system.research.intake_evaluation import validate_snapshot

            frozen_path = validate_snapshot(settings, evaluation)
            entry.update(evaluation=evaluation, validation=None, validation_sha256=None,
                         candidate_id=None, sleeve_id=None)
        entry.update(status="validating", error=None)
        if publish_entry:
            _write(directory / "entry.json", entry)
        run = directory / "validations" / f"validation-{uuid4().hex}"
        run.mkdir(parents=True)
        if evaluation is not None:
            _write(run / "evaluation-owner.json", {
                "evaluation_id": evaluation["evaluation_id"], "pid": os.getpid(),
                "definition_digest": expected_digest,
            })
        try:
            origin = entry["origin"]
            if evaluation is not None:
                origin = {**origin, "start": evaluation["start"], "end": evaluation["end"]}
                prices = pd.read_parquet(frozen_path)
                shutil.copyfile(frozen_path, run / "prices.parquet")
            elif origin["type"] == "study":
                _, origin_dir = _load_report(settings, origin["run_id"])
                price_path = origin_dir / "prices.parquet"
                if _file_hash(price_path) != origin["prices_sha256"]:
                    raise ValueError("strategy_input_prices_changed")
                prices = pd.read_parquet(price_path)
            elif origin["type"] == "backtest":
                price_path = (
                    settings.data.data_dir
                    / "api_runs"
                    / "backtests"
                    / origin["run_id"]
                    / "backtests"
                    / "input_prices.parquet"
                )
                if _file_hash(price_path) != origin["prices_sha256"]:
                    raise ValueError("strategy_input_prices_changed")
                prices = pd.read_parquet(price_path)
            else:
                prices, _ = _collect_prices(
                    settings,
                    list(dict.fromkeys([*definition.symbols, definition.benchmark_symbol])),
                    origin["end"],
                )
            if evaluation is None:
                prices.to_parquet(run / "prices.parquet", index=False)
            result = evaluate_definition(
                prices, definition, origin["start"], origin["end"], initial_cash=10_000
            )
            if result["status"] != "available":
                raise ValueError(result.get("reason") or "strategy_backtest_failed")
            _write(run / "platform-result.json", result)
            parallel_cost = _parallel_cost_replay(run, prices, result, definition)
            _record_study_family(settings, definition.symbols)
            prices_digest = _prices_content_digest(prices)
            trial_identity = _validation_trial_identity(expected_digest, prices, result)
            _record_trial(
                settings, result, "definition-validation-" + trial_identity, definition.symbols,
                validation_prices_digest=prices_digest,
            )
            _docker(
                run,
                "quant_system.research.definition_qlib_replay",
                [
                    "--prices",
                    "/study/prices.parquet",
                    "--result",
                    "/study/platform-result.json",
                    "--output",
                    "/study/qlib-replay.json",
                ],
            )
            qlib = json.loads((run / "qlib-replay.json").read_text())
            if (
                qlib.get("source", {}).get("prices_sha256") != _file_hash(run / "prices.parquet")
                or qlib.get("source", {}).get("platform_result_sha256")
                != _file_hash(run / "platform-result.json")
                or qlib.get("definition_digest") != expected_digest
                or qlib.get("initial_cash") != 10_000
                or qlib.get("terminal_nav_unit") != "USD"
            ):
                raise ValueError("strategy_qlib_input_identity_mismatch")
            comparison = _comparison(prices, result, qlib, definition)
            _docker(
                run,
                "quant_system.research.strategy_signal_validation",
                [
                    "--prices",
                    "/study/prices.parquet",
                    "--result",
                    "/study/platform-result.json",
                    "--output",
                    "/study/signal-analysis.json",
                ],
            )
            signal_analysis = json.loads((run / "signal-analysis.json").read_text())
            if (
                signal_analysis.get("definition_digest") != expected_digest
                or signal_analysis.get("source", {}).get("prices_sha256")
                != _file_hash(run / "prices.parquet")
                or signal_analysis.get("source", {}).get("result_sha256")
                != _file_hash(run / "platform-result.json")
            ):
                raise ValueError("strategy_signal_analysis_identity_mismatch")
            values, dates = _returns(result)
            dsr = evaluate_candidate_dsr(
                TrialsLedger(settings.data.data_dir / "trials"),
                universe=definition.symbols,
                daily_returns=values,
            )
            performance = dsr.pop("performance", {})
            performance.update(
                daily_returns=values,
                return_dates=dates,
                turnover_period=result["metrics"]["turnover"],
            )
            temporary = {"performance": performance}
            cost = assistant_remote._certify_cost_sensitivity(temporary, cost_bps=6)
            concentration = assistant_remote._candidate_concentration(
                temporary, assistant_remote.load_book(settings)["candidates"], settings=settings,
            )
            corr = concentration["raw_max"]
            blockers = []
            if not comparison["accepted"]:
                blockers.append("dual_engine_mismatch")
            if signal_analysis.get("status") not in {"available", "not_applicable"}:
                blockers.append("signal_validation_unavailable")
            if dsr.get("passed") is not True:
                blockers.append("dsr_failed")
            if not cost or cost.get("passed") is not True:
                blockers.append("cost_sensitivity_failed")
            if corr is not None and corr > 0.7:
                blockers.append("correlated_duplicate")
            if concentration["raw_status"] == "not_evaluated":
                blockers.append("correlation_unmeasured_blocked")
            validation = {
                "status": "passed" if not blockers else "failed",
                "run_id": run.name,
                "definition_digest": expected_digest,
                "simulation_allocation_usd": 10_000,
                "start": result["start"],
                "end": result["end"],
                "evaluation_calendar_digest": _hash(dates),
                "platform_metrics": result["metrics"],
                # Display-only sibling block; never merged into platform_metrics, so
                # the strict numeric metric whitelists keep their exact key set.
                "active_metrics": result.get("active_metrics"),
                "qlib": {
                    k: qlib.get(k) for k in ("engine", "qlib_commit", "terminal_nav", "costs")
                },
                "comparison": comparison,
                "signal_analysis": signal_analysis,
                "gates": {"dsr": dsr, "cost": cost, "max_hung_correlation": corr},
                "concentration_evidence": concentration,
                "parallel_cost_replay": parallel_cost,
                "blockers": blockers,
                "validated_at": datetime.now(UTC).isoformat(),
                "forward_status": "not_started",
                "historical_scope": "retrospective_not_unseen_holdout",
                "receipts": receipt_bindings(run),
                **({"evaluation": evaluation} if evaluation is not None else {}),
                **({"admission_protocol_digest": admission_context["protocol_digest"]}
                   if admission_context is not None else {}),
            }
            entry.update(
                validation=validation, status="validation_failed" if blockers else "validated"
            )
            _write(run / "validation.json", validation)
            entry["validation_sha256"] = _file_hash(run / "validation.json")
            if admission_context is not None:
                _attach_admission(settings, entry, run, admission_context)
            if not blockers:
                verify_validation_receipt(
                    run / "validation.json",
                    expected_sha=entry["validation_sha256"],
                    definition_digest=expected_digest,
                    comparison_digest=comparison["comparison_digest"],
                )
            if entry["status"] == "validated" and publish_entry:
                _publish_validation_candidate(settings, entry, run, definition, result)
        except Exception as exc:
            entry.update(
                status="validation_failed",
                error=str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
            )
            _write(run / "failure.json", {
                "status": "failed", "error": entry["error"],
                "definition_digest": expected_digest,
                "recorded_at": datetime.now(UTC).isoformat(),
            })
        if evaluation is not None:
            _write(run / "evaluation-entry.json", entry)
        if publish_entry:
            _write(directory / "entry.json", entry)
            return read_strategy(settings, strategy_id)
        return _view(entry)


def enable_strategy(
    settings, strategy_id, expected_digest, *, expected_receipt=None, expected_admission_sha=None,
):
    # Serialize against a legitimate revalidation replacing the current entry
    # between the paired-increment decision and account allocation.
    directory = _directory(settings, strategy_id)
    with (directory / "validation.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entry = read_strategy(settings, strategy_id)
        if expected_admission_sha is not None and (
            (entry.get("admission_v2") or {}).get("sha256") != expected_admission_sha
        ):
            raise ValueError("admission_v2_activation_receipt_changed")
        if expected_receipt is not None:
            from quant_system.research.validation_receipts import require_activation_receipt

            require_activation_receipt(entry, expected_receipt)
        if entry.get("definition_digest") != expected_digest or entry["status"] not in {
            "validated", "paper_running",
        }:
            raise ValueError("strategy_validation_required")
        assistant_remote.hang_candidate(
            settings, candidate_id=entry["candidate_id"],
            expected_source_digest=entry["source_sha256"],
            **({"expected_receipt": expected_receipt} if expected_receipt is not None else {}),
            **({"expected_admission_sha": expected_admission_sha}
               if expected_admission_sha is not None else {}),
        )
        return read_strategy(settings, strategy_id)


def replace_strategy(
    settings, strategy_id, expected_digest, *, expected_receipt, expected_admission_sha,
):
    """Thin fixed-lifecycle handoff: never aliases a replacement to new allocation."""
    from quant_system.execution.strategy_replacement import replace_verified_strategy
    from quant_system.research import admission_v2
    from quant_system.research.validation_receipts import require_activation_receipt

    directory = _directory(settings, strategy_id)
    with (directory / "validation.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entry = read_strategy(settings, strategy_id)
        require_activation_receipt(entry, expected_receipt)
        if entry["definition_digest"] != expected_digest or entry["status"] not in {
            "validated", "paper_running",
        }:
            raise ValueError("strategy_validation_required")
        if (entry.get("admission_v2") or {}).get("sha256") != expected_admission_sha:
            raise ValueError("admission_v2_activation_receipt_changed")
        receipt = _read_admission(settings, entry)
        intent = admission_v2._intent(receipt["protocol"])
        if intent["kind"] != "replacement":
            raise ValueError("admission_v2_explicit_replacement_required")
        target = intent["target"]
        result = replace_verified_strategy(
            settings, target_candidate_id=target["candidate_id"],
            target_sleeve_id=target["sleeve_id"],
            expected_old_definition_digest=target["definition_digest"],
            expected_old_config_version=target["config_version"],
            new_candidate_id=entry["candidate_id"],
            expected_new_source_digest=entry["source_sha256"],
            expected_admission_sha256=expected_admission_sha,
        )
        return {**read_strategy(settings, strategy_id), "replacement": result}
