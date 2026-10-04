"""Freeze and reproduce one complete static-24 window; never grant admission.

The original dated producers remain separate. New windows derive their complete
calendar and all 500 random schedules from fixed code, not uploaded population
hashes. Writes are restricted to the owner's window namespace or isolated outputs.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import time
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import exchange_calendars
import numpy as np
import pandas as pd

from quant_system.research.admission_qualifier import CONTROL_CONTEXT, CONTROL_SYMBOLS
from quant_system.research.evaluation_service import _hash
from quant_system.research.trials import ResearchTrial, TrialsLedger, universe_digest

SCHEMA = "admission_window/v1"
CONTROL_SCHEMA = "admission_window_controls/v1"
DATASET = CONTROL_VERSION = "futu24-auto-window-v1"
HISTORY_START, START = "2015-01-01", "2018-01-01"
SEED, N_VARIANTS = 20260920, 500
METHOD = {
    "version": "static24_monthly_random_top5/v1",
    "seed": SEED,
    "n_variants": N_VARIANTS,
    "generator": "numpy.random.Generator(PCG64), sequential choices",
}
COLUMNS = [
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "provider",
    "interval",
    "event_ts",
    "knowledge_ts",
    "price_adjustment",
]
ROOT = Path(__file__).resolve().parents[3]
_VERIFIED_CONTROLS = {}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    # Owner-root engine artifacts exceed the public proposal body's size cap.
    # No uploaded code or unbounded external response is accepted here.
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "window_duplicate_json_key")
            result[key] = value
        return result

    return json.loads(
        Path(path).read_text(),
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("window_nonfinite_json")),
    )


def _write(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, sort_keys=True, allow_nan=False, indent=2)
        handle.write("\n")
    Path(path).chmod(0o600)


def _file(path, *, owner=None):
    path = Path(path)
    _require(path.is_absolute() and path.is_file(), "window_source_file_missing")
    _require(not any(p.is_symlink() for p in (path, *path.parents)), "window_symlink_forbidden")
    if owner is not None:
        _require(path.resolve().is_relative_to(owner), "window_source_outside_owner")
    return path.resolve()


def _producer_sources():
    from quant_system.research.strategy_definition import _COMMON_SOURCES

    names = [
        "src/quant_system/" + name
        for name in (
            *_COMMON_SOURCES,
            "research/admission_window.py",
            "research/admission_v2.py",
            "research/admission_qualifier.py",
            "research/intake_evaluation.py",
            "research/external_intake.py",
            "research/validation_receipts.py",
            "research/trials.py",
            "research/active_metrics.py",
        )
    ]
    names.append("scripts/recompute_phase2_evidence.py")
    names.append("scripts/calibrate_admission_semantics.py")
    return {name: _sha(ROOT / name) for name in sorted(set(names))}


def _output_directory(output, owner):
    output, owner = Path(output).absolute(), Path(owner).resolve()
    _require(not any(p.is_symlink() for p in (output, *output.parents)), "window_symlink_forbidden")
    output = output.resolve()
    namespace = owner / "research_intake/admission_v2/windows"
    _require(
        not owner.is_relative_to(output)
        and (not output.is_relative_to(owner) or output.is_relative_to(namespace)),
        "window_output_not_research_namespace",
    )
    _require(not output.exists(), "window_output_already_exists")
    output.mkdir(parents=True, mode=0o700)
    return output


def _sessions(end):
    value = pd.Timestamp(end)
    _require(value.tzinfo is None and value.isoformat()[:10] == end, "window_end_invalid")
    _require(value >= pd.Timestamp(START), "window_end_before_start")
    calendar = exchange_calendars.get_calendar(
        "XNYS", start="2014-01-01", end=f"{value.year + 1}-12-31"
    )
    return pd.to_datetime(calendar.sessions_in_range(HISTORY_START, end), utc=True)


def window_context(requested_end):
    """Exact supported execution contract, with the actual last exchange session."""
    dates = _sessions(requested_end)
    return {
        **copy.deepcopy(CONTROL_CONTEXT),
        "history_start": HISTORY_START,
        "end": dates[-1].date().isoformat(),
        "universe_digest": universe_digest(CONTROL_SYMBOLS),
        "weights": "equal_weight_0.2",
        "engine_initial_cash": 100000,
        "membership": "static_frozen_24",
        "leverage": False,
        "upgrade_target": None,
    }


def _audit_frame(frame, requested_end):
    _require(set(COLUMNS).issubset(frame), "window_price_columns_missing")
    frame = frame[COLUMNS].copy()
    for name in ("timestamp", "event_ts", "knowledge_ts"):
        frame[name] = pd.to_datetime(frame[name], utc=True, errors="raise")
        _require(frame[name].notna().all(), "window_time_missing")
    dates = _sessions(requested_end)
    _require(
        set(frame.symbol) == {*CONTROL_SYMBOLS, "SPY"}
        and not frame.duplicated(["symbol", "timestamp"]).any()
        and len(frame) == len(dates) * 25
        and all(
            pd.DatetimeIndex(part.timestamp.sort_values()).equals(dates)
            for _, part in frame.groupby("symbol")
        ),
        "window_calendar_or_universe_mismatch",
    )
    _require(
        set(frame.provider) == {"futu"}
        and set(frame.interval) == {"1d"}
        and set(frame.price_adjustment) == {"qfq"},
        "window_provider_mismatch",
    )
    numbers = frame[["open", "high", "low", "close", "volume"]].to_numpy(float)
    _require(
        np.isfinite(numbers).all() and (numbers[:, :4] > 0).all() and (numbers[:, 4] >= 0).all(),
        "window_ohlcv_invalid",
    )
    _require(
        (frame.high + 1e-9 >= frame[["open", "low", "close"]].max(axis=1)).all()
        and (frame.low - 1e-9 <= frame[["open", "high", "close"]].min(axis=1)).all(),
        "window_ohlc_range_invalid",
    )
    return {
        "sessions_per_symbol": len(dates),
        "price_rows": len(frame),
        "evaluation_sessions": int((dates >= pd.Timestamp(START, tz="UTC")).sum()),
        "missing_sessions": 0,
        "provider": "futu",
        "adjustment": "qfq",
        "new_provider_requests": 0,
    }


def _source_identity(settings, validation_path):
    from quant_system.research import admission_v2 as admission
    from quant_system.research.external_intake import _load_job
    from quant_system.research.intake_evaluation import validate_snapshot
    from quant_system.research.strategy_definition import StrategyDefinition, validate_definition
    from quant_system.research.validation_receipts import verify_validation_receipt

    owner = Path(settings.data.data_dir).resolve()
    path = _file(validation_path, owner=owner)
    _require(
        path.is_relative_to(owner / "strategy_library") and path.name == "validation.json",
        "window_validation_path_invalid",
    )
    source = _file(path.parent.parent.parent / "definition.json", owner=owner)
    definition = validate_definition(_read(source))
    validation = verify_validation_receipt(
        path,
        expected_sha=_sha(path),
        definition_digest=definition.content_digest,
        require_admission=False,
    )
    _require(
        validation.get("comparison", {}).get("accepted") is True, "window_dual_engine_unverified"
    )
    evaluation = validation["evaluation"]
    job = _load_job(settings, evaluation["job_id"])
    protocol = job["admission_protocol"]
    admission.verify_protocol(protocol)
    job, plan, _ = admission._job_context(settings, protocol, definition.content_digest, evaluation)
    payload = dict(plan["payload"])
    history_start = payload.pop("history_start", plan.get("history_start", HISTORY_START))
    _require(plan.get("history_start", history_start) == history_start, "window_history_conflict")
    planned = validate_definition(StrategyDefinition(history_start=history_start, **payload))
    _require(
        planned.model_dump(mode="json", exclude={"title"})
        == definition.model_dump(mode="json", exclude={"title"})
        and source.parent.name == plan["strategy_id"],
        "window_planned_definition_mismatch",
    )
    context = window_context(evaluation["end"])
    actual = definition.model_dump(mode="json")
    keys = (
        "history_start",
        "benchmark_symbol",
        "rebalance",
        "top_n",
        "execution_price",
        "commission_bps",
        "slippage_bps",
        "target_gross_exposure",
        "max_weight_per_symbol",
        "selection",
        "min_order_value",
        "whole_share_orders",
    )
    _require(
        actual["symbols"] == CONTROL_SYMBOLS
        and all(actual[k] == context[k] for k in keys)
        and evaluation["symbols"] == [*CONTROL_SYMBOLS, "SPY"]
        and evaluation["start"] == START
        and evaluation["cash"] == 10000
        and evaluation["commission_bps"] == 1
        and evaluation["slippage_bps"] == 5,
        "window_definition_scope_unsupported",
    )
    prices = _file(validate_snapshot(settings, evaluation), owner=owner)
    snapshot = _file(prices.with_name("snapshot.json"), owner=owner)
    _require(_read(snapshot) == evaluation, "window_snapshot_changed")
    _require(
        _sha(path.parent / "prices.parquet") == _sha(prices), "window_validation_prices_changed"
    )
    result = _read(path.parent / "platform-result.json")
    dates = _sessions(evaluation["end"])
    curve_dates = dates[dates >= pd.Timestamp(START, tz="UTC")].strftime("%Y-%m-%d").tolist()
    _require(
        result["profile"]["symbols"] == CONTROL_SYMBOLS
        and result["profile"]["benchmark_symbol"] == "SPY"
        and [row["date"] for row in result["curve"]] == curve_dates
        and validation["evaluation_calendar_digest"] == _hash(curve_dates),
        "window_validation_calendar_or_profile_changed",
    )
    paths = [path, source, prices, snapshot]
    paths.extend(path.parent / name for name in validation["receipts"]["files"])
    immutable = {
        key: job[key]
        for key in (
            "job_id",
            "proposal",
            "payload_sha256",
            "plans",
            "plans_sha256",
            "admission_protocol",
            "evaluation",
        )
    }
    return {
        "owner_root": str(owner),
        "validation_path": str(path),
        "job_id": job["job_id"],
        "immutable_job_digest": _hash(immutable),
        "evaluation_id": evaluation["evaluation_id"],
        "requested_end": evaluation["end"],
        "prices_path": str(prices),
        "prices_sha256": _sha(prices),
        "files": {str(_file(p, owner=owner)): _sha(p) for p in paths},
    }


def _code_digest():
    from quant_system.research.admission_v2 import code_identity

    return code_identity()["digest"]


def _window_id(context, prices_sha256, sources, *, code_digest=None):
    return "futu24-window-" + _hash(
        {
            "context": context,
            "prices_sha256": prices_sha256,
            "method": METHOD,
            "producer_sources": sources,
            "code_digest": _code_digest() if code_digest is None else code_digest,
        }
    )


def window_identity(settings, validation_path):
    """Stable per-input key shared by both variants; no directory creation."""
    code_digest = _code_digest()
    source = _source_identity(settings, validation_path)
    _audit_frame(pd.read_parquet(source["prices_path"]), source["requested_end"])
    context = window_context(source["requested_end"])
    _require(_code_digest() == code_digest, "window_code_changed_during_identity")
    return {
        "window_id": _window_id(
            context, source["prices_sha256"], _producer_sources(), code_digest=code_digest
        ),
        "context": context,
    }


def freeze_window(settings, *, validation_path, output):
    """Copy a verified seed validation's data; later job progress is not an input."""
    code_digest = _code_digest()
    source = _source_identity(settings, validation_path)
    frame = pd.read_parquet(source["prices_path"])
    audit = _audit_frame(frame, source["requested_end"])
    sources = _producer_sources()
    context = window_context(source["requested_end"])
    window_id = _window_id(context, source["prices_sha256"], sources, code_digest=code_digest)
    output = _output_directory(output, settings.data.data_dir)
    (output / "prices.parquet").write_bytes(Path(source["prices_path"]).read_bytes())
    (output / "prices.parquet").chmod(0o600)
    _write(output / "source-audit.json", audit)
    manifest = {
        "schema": SCHEMA,
        "window_id": window_id,
        "dataset": DATASET,
        "context": context,
        "requested_start": START,
        "requested_end": source["requested_end"],
        "effective_start": context["start"],
        "effective_end": context["end"],
        "method": copy.deepcopy(METHOD),
        "producer_sources": sources,
        "code_digest": code_digest,
        "source": source,
        "artifacts": {
            name: {"path": name, "sha256": _sha(output / name)}
            for name in ("prices.parquet", "source-audit.json")
        },
        "historical_pit_verified": False,
        "corporate_action_vintage_verified": False,
        "broad_universe_qualified": False,
        "capital_authorized": False,
    }
    _require(
        _source_identity(settings, validation_path) == source, "window_source_changed_during_freeze"
    )
    _require(_producer_sources() == sources, "window_producer_changed_during_freeze")
    _require(_code_digest() == code_digest, "window_code_changed_during_freeze")
    _require(_sha(output / "prices.parquet") == source["prices_sha256"], "window_copy_changed")
    _write(output / "input-manifest.json", manifest)
    return {
        "manifest_path": str(output / "input-manifest.json"),
        "manifest_sha256": _sha(output / "input-manifest.json"),
        "window_id": window_id,
        "context": context,
    }


def read_window(manifest_path, expected_sha):
    path = _file(manifest_path)
    _require(_sha(path) == expected_sha, "window_manifest_changed")
    manifest = _read(path)
    sources = _producer_sources()
    code_digest = _code_digest()
    context = window_context(manifest["requested_end"])
    _require(
        manifest["schema"] == SCHEMA
        and manifest["method"] == METHOD
        and manifest["producer_sources"] == sources
        and manifest.get("code_digest") == code_digest
        and manifest["context"] == context
        and manifest["requested_start"] == START
        and manifest["effective_start"] == context["start"]
        and manifest["effective_end"] == context["end"]
        and all(
            manifest[k] is False
            for k in (
                "historical_pit_verified",
                "corporate_action_vintage_verified",
                "broad_universe_qualified",
                "capital_authorized",
            )
        ),
        "window_manifest_scope_or_source_changed",
    )
    source = manifest["source"]
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=Path(source["owner_root"])))
    _require(
        _source_identity(settings, source["validation_path"]) == source,
        "window_source_identity_changed",
    )
    window_id = _window_id(context, source["prices_sha256"], sources, code_digest=code_digest)
    _require(
        manifest["window_id"] == window_id and manifest["dataset"] == DATASET,
        "window_identity_changed",
    )
    names = {"prices.parquet", "source-audit.json"}
    _require(
        set(manifest["artifacts"]) == names
        and {p.name for p in path.parent.iterdir()} == names | {path.name},
        "window_payload_closure_changed",
    )
    for name in names:
        artifact = _file(path.parent / name)
        _require(
            manifest["artifacts"][name] == {"path": name, "sha256": _sha(artifact)},
            "window_artifact_changed",
        )
    _require(
        _sha(path.parent / "prices.parquet") == source["prices_sha256"], "window_prices_changed"
    )
    frame = pd.read_parquet(path.parent / "prices.parquet")
    _require(
        _audit_frame(frame, manifest["requested_end"]) == _read(path.parent / "source-audit.json"),
        "window_audit_changed",
    )
    return frame, manifest


def _window_artifact_hashes(manifest_path, manifest):
    """All frozen payload bytes participate in the consumer's final CAS check."""
    directory = Path(manifest_path).resolve().parent
    return {
        str(directory / name): artifact["sha256"]
        for name, artifact in manifest["artifacts"].items()
    }


def control_population(context):
    """All fixed RNG choices in order, including the prior-month decision day."""
    _require(context == window_context(context["end"]), "window_context_unsupported")
    dates = _sessions(context["end"])
    boundaries = [
        (before.date().isoformat(), after.date().isoformat())
        for before, after in zip(dates[:-1], dates[1:], strict=True)
        if (before.year, before.month) != (after.year, after.month)
        and after >= pd.Timestamp(START, tz="UTC")
    ]
    rng = np.random.Generator(np.random.PCG64(SEED))
    eligible = sorted(CONTROL_SYMBOLS)
    return [
        {
            "index": index,
            "schedule": [
                {
                    "signal_date": signal,
                    "trade_date": trade,
                    "eligible_symbols": list(eligible),
                    "targets": {
                        symbol: 0.2
                        for symbol in sorted(rng.choice(eligible, size=5, replace=False).tolist())
                    },
                }
                for signal, trade in boundaries
            ],
        }
        for index in range(N_VARIANTS)
    ]


def verify_control_population(context, population, *, method):
    _require(method == METHOD, "window_control_method_changed")
    _require(population == control_population(context), "window_control_population_changed")
    return _hash(population)


@lru_cache(maxsize=2)
def _load_driver(source_sha):
    path = ROOT / "scripts/recompute_phase2_evidence.py"
    _require(_sha(path) == source_sha, "window_engine_driver_changed")
    spec = importlib.util.spec_from_file_location("fixed_window_engine_" + source_sha, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _driver():
    return _load_driver(_sha(ROOT / "scripts/recompute_phase2_evidence.py"))


def _profile(prices, manifest):
    from quant_system.research.profile_backtests import run_profile

    result = run_profile(prices, "stocks_momentum_12_2", start=START, end=manifest["requested_end"])
    _require(result["status"] == "available", "window_control_profile_unavailable")
    expected = control_population(manifest["context"])[0]["schedule"]
    observed = [
        {key: row[key] for key in ("signal_date", "trade_date", "eligible_symbols")}
        for row in result["signals"]
    ]
    _require(
        observed
        == [
            {key: row[key] for key in ("signal_date", "trade_date", "eligible_symbols")}
            for row in expected
        ]
        and all(row["ready"] is True for row in result["signals"])
        and result["start"] == manifest["effective_start"]
        and result["end"] == manifest["effective_end"],
        "window_control_profile_scope_changed",
    )
    return result


def _engine_frame(prices, context):
    from quant_system.research.reference_backtests import _prepare_prices

    frame = _prepare_prices(prices)
    return frame[
        frame.symbol.isin(CONTROL_SYMBOLS)
        & frame.timestamp.between(
            pd.Timestamp(context["start"], tz="UTC"), pd.Timestamp(context["end"], tz="UTC")
        )
    ]


def _schedule(records):
    return {pd.Timestamp(row["trade_date"], tz="UTC"): row["targets"] for row in records}


def _trial_for_result(index, rows, identity, schedule, profile):
    equity = pd.Series([row["equity"] for row in rows])
    returns = equity.div(equity.shift(1).fillna(100000)).sub(1).tolist()
    definition_digest = _hash({"generator": identity, "schedule": schedule})
    return ResearchTrial.record(
        kind="platform_backtest",
        subject=f"random-top5-{index:04d}",
        universe=CONTROL_SYMBOLS,
        daily_returns=returns,
        window_start=profile["start"],
        window_end=profile["end"],
        source="futu_saved_prices",
        metadata={
            "run_id": "phase2-null-" + definition_digest,
            "strategy_definition_digest": definition_digest,
            "equity_curve_digest": _hash(rows),
            "scope_tag": "random_control_calibration",
            "canonical_family_member": False,
            "source_identity": identity,
        },
    ).model_dump(mode="json")


def _reference_trial(profile, identity):
    equity = pd.Series([row["equity"] for row in profile["curve"]])
    return ResearchTrial.record(
        kind="strategy_replication",
        subject="fixed_control_context_reference",
        universe=CONTROL_SYMBOLS,
        daily_returns=equity.div(equity.shift(1).fillna(100000)).sub(1).tolist(),
        window_start=profile["start"],
        window_end=profile["end"],
        source="futu_saved_prices",
        metadata={
            "run_id": "control-context-" + _hash(identity),
            "scope_tag": "random_control_calibration",
            "canonical_family_member": False,
            "new_hypothesis": False,
            "role": "fixed_reference_recompute",
        },
    )


def verify_control_variant(directory, *, index, frame, schedule, profile, identity):
    """Re-execute one already counted control; not a new hypothesis or a pass grant."""
    from quant_system.backtest.models import BacktestConfig
    from quant_system.research.profile_backtests import _run

    directory = Path(directory)
    receipt = _read(_file(directory / "receipt.json"))
    names = {
        "schedule.json",
        "config.json",
        "platform-result.json",
        "equity_curve.parquet",
        "trade_blotter.parquet",
        "orders.parquet",
        "positions.parquet",
        "attribution.parquet",
    }
    _require(
        receipt["index"] == index
        and receipt["status"] == "completed"
        and set(receipt["files"]) == names
        and {p.name for p in directory.iterdir()} == names | {"receipt.json"},
        "window_control_variant_closure_changed",
    )
    for name, digest in receipt["files"].items():
        _require(_sha(_file(directory / name)) == digest, "window_control_artifact_changed")
    _require(_read(directory / "schedule.json") == schedule, "window_control_selection_changed")
    _require(
        _read(directory / "config.json")
        == BacktestConfig(initial_cash=100000, commission_bps=1, slippage_bps=5).model_dump(
            mode="json"
        ),
        "window_control_execution_changed",
    )
    # Use the same existing pure engine seam. All logical trials were recorded
    # by produce_controls; this verification is a deterministic replay only.
    result = _run(frame, _schedule(schedule))
    for name in ("equity_curve", "trade_blotter", "orders", "positions", "attribution"):
        try:
            pd.testing.assert_frame_equal(
                getattr(result, name).reset_index(drop=True),
                pd.read_parquet(directory / f"{name}.parquet").reset_index(drop=True),
                check_dtype=False,
                check_exact=True,
            )
        except AssertionError as exc:
            raise ValueError("window_control_engine_replay_mismatch:" + name) from exc
    benchmark = {row["date"]: row["benchmark"] for row in profile["curve"]}
    rows = [
        {
            "date": row.timestamp.date().isoformat(),
            "equity": float(row.equity),
            "benchmark": benchmark[row.timestamp.date().isoformat()],
        }
        for row in result.equity_curve.itertuples(index=False)
    ]
    payload = _read(directory / "platform-result.json")
    expected_trial = _trial_for_result(index, rows, identity, schedule, profile)
    _require(
        payload
        == {"curve": rows, "evaluation_initial_cash": 100000, "scope": "random_control_calibration"}
        and receipt["curve_digest"] == _hash(rows)
        and receipt["definition_digest"] == _hash({"generator": identity, "schedule": schedule})
        and receipt["metrics"] == result.metrics.model_dump(mode="json")
        and receipt["costs"] == _driver()._costs(result.trade_blotter)
        and receipt["minimum_cash"] == float(result.equity_curve.cash.min())
        and {k: v for k, v in receipt["trial"].items() if k != "ts"}
        == {k: v for k, v in expected_trial.items() if k != "ts"},
        "window_control_recomputed_result_changed",
    )
    return receipt


def produce_controls(manifest_path, expected_sha, family_ledger, output):
    """Execute the fixed full population, retaining every failure and trial.

    Never called by a read API. The caller owns the nonblocking window lock;
    existing outputs are never overwritten and partial batches cannot qualify.
    """
    from quant_system.research.admission_consumer_checks import LEDGER_SHA

    prices, manifest = read_window(manifest_path, expected_sha)
    input_directory, requested_output = Path(manifest_path).resolve().parent, Path(output).resolve()
    _require(
        not input_directory.is_relative_to(requested_output)
        and not requested_output.is_relative_to(input_directory),
        "window_control_output_overlaps_input",
    )
    family_ledger = _file(family_ledger)
    _require(_sha(family_ledger) == LEDGER_SHA, "window_control_historical_family_changed")
    profile = _profile(prices, manifest)
    output = _output_directory(output, manifest["source"]["owner_root"])
    (output / "families").mkdir(mode=0o700)
    (output / "families/source-trials.jsonl").write_bytes(family_ledger.read_bytes())
    document = {
        "scope": "fixed_window_control_not_formal_research",
        "results": [profile],
        "source": {
            "provider": "futu",
            "adjustment": "qfq",
            "prices_sha256": manifest["source"]["prices_sha256"],
        },
    }
    _write(output / "saved-study-snapshot.json", document)
    identity = {
        "schema": CONTROL_SCHEMA,
        "control_version": CONTROL_VERSION,
        "window_id": manifest["window_id"],
        **METHOD,
        "prices_path": str(Path(manifest_path).resolve().parent / "prices.parquet"),
        "prices_sha256": manifest["source"]["prices_sha256"],
        "approved_input_manifest": str(Path(manifest_path).resolve()),
        "approved_input_manifest_sha256": expected_sha,
        "profile_digest": _hash(profile),
        "source_hashes": manifest["producer_sources"],
        "requested_window": {"start": START, "end": manifest["requested_end"]},
        "effective_window": {"start": profile["start"], "end": profile["end"]},
        "family_ledger_sha256": LEDGER_SHA,
        "initial_cash": 100000,
        "probe_only": False,
        "capital_authorized": False,
        "formal_trial_writes": False,
        "historical_pit_verified": False,
    }
    _write(output / "inputs.json", identity)
    population = control_population(manifest["context"])
    _write(output / "planned-population.json", {"method": METHOD, "population": population})
    frame = _engine_frame(prices, manifest["context"])
    ledger = TrialsLedger(output / "research_index")
    ledger.append(_reference_trial(profile, identity))
    failures, started = [], time.monotonic()
    driver = _driver()
    for item in population:
        index, records = item["index"], item["schedule"]
        try:
            receipt = driver.run_variant(
                index, frame, _schedule(records), records, profile, output, identity
            )
            ledger.append(ResearchTrial.model_validate(receipt["trial"]))
        except Exception as exc:
            receipt = {
                "index": index,
                "status": "failed",
                "error_type": type(exc).__name__,
                "reason": str(exc),
            }
            _write(output / f"variant-{index:04d}-failure.json", receipt)
            ledger.append(
                ResearchTrial.skipped(
                    kind="platform_backtest",
                    subject=f"window-control-{index:04d}",
                    universe=CONTROL_SYMBOLS,
                    source="phase2_random_control",
                    reason=str(exc),
                    metadata={
                        "run_id": f"window-control-failed-{manifest['window_id']}-{index}",
                        "scope_tag": "random_control_calibration",
                        "canonical_family_member": False,
                    },
                )
            )
            failures.append(receipt)
        driver.append_index(output / "research-index.jsonl", receipt)
    read_window(manifest_path, expected_sha)
    _require(_sha(family_ledger) == LEDGER_SHA, "window_control_historical_family_changed")
    summary = {
        "schema": CONTROL_SCHEMA,
        "control_version": CONTROL_VERSION,
        "window_id": manifest["window_id"],
        "status": "partial" if failures else "completed",
        "n_variants": N_VARIANTS,
        "successful": N_VARIANTS - len(failures),
        "failures": failures,
        "elapsed_seconds": time.monotonic() - started,
        "full_gate_evaluated": False,
        "capital_authorized": False,
        "formal_trial_writes": False,
        "local_trial_records": N_VARIANTS + 1,
        "extra_reference_logical_attempts": 1,
    }
    _write(output / "summary.json", summary)
    files = {str(p.relative_to(output)): _sha(p) for p in sorted(output.rglob("*")) if p.is_file()}
    _write(output / "artifact-manifest.json", {"files": files})
    return summary


def verify_control_artifacts(manifest_path, expected_sha, control_root, *, execution_trace=None):
    """Cold verification replays every real engine result; warm hits rehash all files."""
    from quant_system.research.admission_consumer_checks import LEDGER_SHA

    prices, manifest = read_window(manifest_path, expected_sha)
    root = Path(control_root).resolve()
    expected_dirs = {f"variant-{i:04d}" for i in range(N_VARIANTS)}
    _require(
        {p.name for p in root.glob("variant-*")} == expected_dirs
        and all((root / name / "receipt.json").is_file() for name in expected_dirs),
        "window_control_population_incomplete",
    )
    inputs = _read(_file(root / "inputs.json"))
    _require(
        inputs["schema"] == CONTROL_SCHEMA
        and inputs["control_version"] == CONTROL_VERSION
        and inputs["window_id"] == manifest["window_id"]
        and all(inputs.get(k) == v for k, v in METHOD.items())
        and inputs["source_hashes"] == _producer_sources()
        and inputs["approved_input_manifest"] == str(Path(manifest_path).resolve())
        and inputs["approved_input_manifest_sha256"] == expected_sha
        and inputs["prices_path"] == str(Path(manifest_path).resolve().parent / "prices.parquet")
        and inputs["prices_sha256"] == manifest["source"]["prices_sha256"]
        and inputs["family_ledger_sha256"] == LEDGER_SHA
        and inputs["initial_cash"] == 100000
        and inputs["probe_only"] is False
        and inputs["capital_authorized"] is False
        and inputs["formal_trial_writes"] is False,
        "window_control_inputs_changed",
    )
    _require(
        _sha(_file(root / "families/source-trials.jsonl")) == LEDGER_SHA,
        "window_control_historical_family_changed",
    )
    population = _read(_file(root / "planned-population.json"))
    population_digest = verify_control_population(
        manifest["context"], population["population"], method=population["method"]
    )
    artifact = _read(_file(root / "artifact-manifest.json"))
    actual_files = {
        str(p.relative_to(root)): _sha(_file(p))
        for p in root.rglob("*")
        if p.is_file() and p != root / "artifact-manifest.json"
    }
    _require(artifact == {"files": actual_files}, "window_control_file_closure_changed")
    summary = _read(root / "summary.json")
    _require(
        summary["status"] == "completed"
        and summary["n_variants"] == 500
        and summary["successful"] == 500
        and summary["failures"] == []
        and summary["control_version"] == CONTROL_VERSION
        and summary["window_id"] == manifest["window_id"]
        and summary["local_trial_records"] == 501
        and summary["extra_reference_logical_attempts"] == 1
        and summary["formal_trial_writes"] is False
        and summary["capital_authorized"] is False
        and summary["full_gate_evaluated"] is False,
        "window_control_summary_incomplete",
    )
    cache_key = _hash(
        {
            "window": manifest["window_id"],
            "manifest_sha": expected_sha,
            "files": actual_files,
            "source": manifest["source"],
        }
    )
    if cache_key not in _VERIFIED_CONTROLS:
        try:
            profile = _profile(prices, manifest)
        except Exception:
            if execution_trace is not None:
                execution_trace["failed_call_engine_count_unknown"] = True
            raise
        if execution_trace is not None:
            # A completed _profile calls the four fixed net/gross/benchmark/peer
            # engine seams. No count is claimed on an interrupted/failed call.
            execution_trace["confirmed_profile_engine_runs"] = (
                execution_trace.get("confirmed_profile_engine_runs", 0) + 4
            )
        _require(inputs["profile_digest"] == _hash(profile), "window_control_profile_changed")
        saved = _read(root / "saved-study-snapshot.json")
        _require(saved["results"] == [profile], "window_control_saved_profile_changed")
        frame = _engine_frame(prices, manifest["context"])
        receipts = []
        for item in population["population"]:
            try:
                receipt = verify_control_variant(
                    root / f"variant-{item['index']:04d}", index=item["index"], frame=frame,
                    schedule=item["schedule"], profile=profile, identity=inputs,
                )
            except Exception:
                if execution_trace is not None:
                    execution_trace["failed_call_engine_count_unknown"] = True
                raise
            receipts.append(receipt)
            if execution_trace is not None:
                execution_trace["confirmed_variant_engine_runs"] = (
                    execution_trace.get("confirmed_variant_engine_runs", 0) + 1
                )
        trials = TrialsLedger(root / "research_index").list()
        expected_trials = {receipt["trial"]["trial_id"]: receipt["trial"] for receipt in receipts}
        actual_trials = {
            row.trial_id: row.model_dump(mode="json")
            for row in trials
            if row.kind == "platform_backtest"
        }
        _require(
            len(trials) == 501 and actual_trials == expected_trials,
            "window_control_trial_population_changed",
        )
        reference = [
            r.model_dump(mode="json", exclude={"ts"})
            for r in trials
            if r.kind != "platform_backtest"
        ]
        _require(
            reference
            == [_reference_trial(profile, inputs).model_dump(mode="json", exclude={"ts"})],
            "window_control_reference_trial_changed",
        )
        index_rows = [
            _read_json_line(line)
            for line in (root / "research-index.jsonl").read_text().splitlines()
        ]
        _require(index_rows == receipts, "window_control_index_population_changed")
        # Recheck before caching; a modified result cannot win a warm cache hit.
        _require(
            all(_sha(root / name) == digest for name, digest in actual_files.items()),
            "window_control_changed_during_replay",
        )
        read_window(manifest_path, expected_sha)
        _VERIFIED_CONTROLS[cache_key] = True
        if len(_VERIFIED_CONTROLS) > 4:
            del _VERIFIED_CONTROLS[next(iter(_VERIFIED_CONTROLS))]
    receipts_sha = _hash(
        {
            f"variant-{i:04d}/receipt.json": _sha(root / f"variant-{i:04d}/receipt.json")
            for i in range(N_VARIANTS)
        }
    )
    return {
        "control_version": CONTROL_VERSION,
        "window_id": manifest["window_id"],
        "context": manifest["context"],
        "inputs_sha256": _sha(root / "inputs.json"),
        "receipts_sha256": receipts_sha,
        "prices_sha256": manifest["source"]["prices_sha256"],
        "population_digest": population_digest,
        "engine_replay_verified": True,
        "file_hashes": {str(root / name): digest for name, digest in actual_files.items()},
        "extra_file_hashes": {
            **manifest["source"]["files"],
            **_window_artifact_hashes(manifest_path, manifest),
            str(Path(manifest_path).resolve()): expected_sha,
            str(root / "artifact-manifest.json"): _sha(root / "artifact-manifest.json"),
            **{str(root / name): digest for name, digest in actual_files.items()},
        },
        "source_projection_digest": manifest["source"]["immutable_job_digest"],
        "capital_authorized": False,
    }


def _read_json_line(line):
    return json.loads(line)
