"""One bounded saved Futu intake panel, ending 2026-09-24; never a future-data grant.

The source is the independently inspected existing owner job and its two original
engine receipts. This producer only reads those files and writes a new isolated
manifest. It neither fetches prices nor rewrites any original research evidence.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import exchange_calendars
import numpy as np
import pandas as pd

from quant_system.research.admission_qualifier import CONTROL_SYMBOLS
from quant_system.research.external_intake import _sha, strict_json
from quant_system.research.intake_evaluation import validate_snapshot
from quant_system.research.validation_receipts import verify_validation_receipt

DATASET = "futu24-saved-intake-20260924"
SCHEMA = "phase2_saved_intake_static24_inputs/v1"
JOB_ID = "intake-00f79f819824c473a9bc6f42"
JOB_SHA = "f13771959e4540d01e31a291637cbc2419e5e59bbf897e81fb3b470cfa73c377"
PRICES_SHA = "0880dbd7b809ae12f4a725bd8c504ec9d8b2de7267114db2fca3b53586e6e704"
HISTORY_START, START, END = "2015-01-01", "2018-01-01", "2026-09-24"
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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _audit_frame(frame):
    _require(set(COLUMNS).issubset(frame), "september24_price_columns_missing")
    frame = frame.copy()
    for name in ("timestamp", "event_ts", "knowledge_ts"):
        frame[name] = pd.to_datetime(frame[name], utc=True, errors="raise")
        _require(frame[name].notna().all(), "september24_time_missing")
    days = pd.to_datetime(
        exchange_calendars.get_calendar(
            "XNYS", start="2014-01-01", end="2027-01-01"
        ).sessions_in_range(HISTORY_START, END),
        utc=True,
    )
    _require(
        set(frame.symbol) == {*CONTROL_SYMBOLS, "SPY"}
        and len(frame) == 73725
        and len(days) == 2949
        and not frame.duplicated(["symbol", "timestamp"]).any()
        and all(
            pd.DatetimeIndex(part.timestamp.sort_values()).equals(days)
            for _, part in frame.groupby("symbol")
        ),
        "september24_calendar_or_universe_mismatch",
    )
    _require(
        set(frame.provider) == {"futu"}
        and set(frame.interval) == {"1d"}
        and set(frame.price_adjustment) == {"qfq"},
        "september24_provider_mismatch",
    )
    values = frame[["open", "high", "low", "close", "volume"]].to_numpy(float)
    _require(
        np.isfinite(values).all() and (values[:, :4] > 0).all() and (values[:, 4] >= 0).all(),
        "september24_ohlcv_invalid",
    )
    _require(
        (frame.high + 1e-9 >= frame[["open", "low", "close"]].max(axis=1)).all()
        and (frame.low - 1e-9 <= frame[["open", "high", "close"]].min(axis=1)).all(),
        "september24_ohlc_range_invalid",
    )
    return {
        "status": "verified",
        "sessions_per_symbol": len(days),
        "price_rows": len(frame),
        "evaluation_sessions": int((days >= pd.Timestamp(START, tz="UTC")).sum()),
        "missing_sessions": 0,
        "duplicate_symbol_sessions": 0,
        "provider": "futu",
        "adjustment": "qfq",
        "new_provider_requests": 0,
    }


def freeze_inputs(source_job, output):
    source_job, output = Path(source_job).resolve(), Path(output).resolve()
    _require(
        source_job.name == JOB_ID + ".json" and sha(source_job) == JOB_SHA,
        "september24_original_job_changed",
    )
    owner = source_job.parents[2]
    _require(not output.is_relative_to(owner), "september24_output_must_be_isolated")
    # A completed worker record includes both full validation summaries and is
    # larger than the public proposal-size limit. Its exact bytes are pinned.
    job = json.loads(source_job.read_text())
    _require(
        job["job_id"] == JOB_ID
        and job["status"] == "failed"
        and _sha(job["proposal"]) == job["payload_sha256"]
        and _sha(job["plans"]) == job["plans_sha256"],
        "september24_job_identity_changed",
    )
    evaluation = job["evaluation"]
    _require(
        evaluation["start"] == START
        and evaluation["end"] == END
        and evaluation["plans_sha256"] == job["plans_sha256"]
        and evaluation["cash"] == 10000
        and evaluation["commission_bps"] == 1
        and evaluation["slippage_bps"] == 5,
        "september24_evaluation_changed",
    )
    prices = validate_snapshot(SimpleNamespace(data=SimpleNamespace(data_dir=owner)), evaluation)
    _require(sha(prices) == PRICES_SHA, "september24_original_prices_changed")
    originals = {str(source_job): JOB_SHA, str(prices): PRICES_SHA}
    _require(
        {p["variant"] for p in job["plans"]} == {"baseline", "augmented"},
        "september24_original_pair_missing",
    )
    for plan in job["plans"]:
        row = next(r for r in job["results"] if r["variant"] == plan["variant"])
        directory = owner / "strategy_library" / plan["strategy_id"]
        run = directory / "validations" / row["validation"]["run_id"]
        definition = strict_json((directory / "definition.json").read_text())
        _require(
            definition["symbols"] == CONTROL_SYMBOLS
            and definition["benchmark_symbol"] == "SPY"
            and definition["history_start"] == HISTORY_START,
            "september24_original_universe_changed",
        )
        validation = verify_validation_receipt(
            run / "validation.json",
            expected_sha=row["validation_sha256"],
            definition_digest=plan["definition_digest"],
            require_admission=False,
        )
        _require(
            validation["evaluation"] == evaluation
            and validation["comparison"]["accepted"] is True
            and sha(run / "prices.parquet") == PRICES_SHA,
            "september24_original_pair_input_mismatch",
        )
        for path in [
            directory / "definition.json",
            run / "validation.json",
            *[run / name for name in validation["receipts"]["files"]],
        ]:
            _require(path.is_file() and not path.is_symlink(), "september24_source_not_file")
            originals[str(path)] = sha(path)
    raw = prices.read_bytes()
    audit = _audit_frame(pd.read_parquet(io.BytesIO(raw)))
    output.mkdir(parents=True, exist_ok=False)
    (output / "prices.parquet").write_bytes(raw)
    (output / "builder-snapshot.py").write_bytes(Path(__file__).read_bytes())
    (output / "source-audit.json").write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n")
    manifest = {
        "schema": SCHEMA,
        "dataset": DATASET,
        "ordered_symbols": CONTROL_SYMBOLS,
        "benchmark_symbol": "SPY",
        "history_start": HISTORY_START,
        "requested_start": START,
        "requested_end": END,
        "effective_start": "2018-01-02",
        "effective_end": END,
        "price_rows": audit["price_rows"],
        "sessions_per_symbol": audit["sessions_per_symbol"],
        "evaluation_sessions": audit["evaluation_sessions"],
        "source_job_id": JOB_ID,
        "source_job_sha256": JOB_SHA,
        "sources": [{"path": path, "sha256": value} for path, value in sorted(originals.items())],
        "artifacts": {
            name: {"path": name, "sha256": sha(output / name)}
            for name in ("prices.parquet", "source-audit.json", "builder-snapshot.py")
        },
        "historical_pit_verified": False,
        "corporate_action_vintage_verified": False,
        "broad_universe_qualified": False,
        "provider_requests": 0,
        "predeclared_control": {
            "seed": 20260920,
            "n_variants": 500,
            "top_n": 5,
            "rebalance": "monthly",
            "weights": "equal_weight_0.2",
            "commission_bps": 1,
            "slippage_bps": 5,
            "execution_price": "next_open",
            "engine_initial_cash": 100000,
        },
        "scope": "existing_real_input_new_bounded_calibration_not_formal_authority",
    }
    _require(
        all(sha(path) == value for path, value in originals.items()),
        "september24_source_changed_during_freeze",
    )
    path = output / "input-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return {**audit, "status": "ready", "manifest_path": str(path), "manifest_sha256": sha(path)}


def read_frozen_inputs(manifest_path, expected_sha):
    path = Path(manifest_path).resolve()
    _require(not path.is_symlink() and sha(path) == expected_sha, "september24_manifest_changed")
    manifest = strict_json(path.read_text())
    _require(
        manifest["schema"] == SCHEMA
        and manifest["dataset"] == DATASET
        and manifest["source_job_id"] == JOB_ID
        and manifest["source_job_sha256"] == JOB_SHA
        and manifest["ordered_symbols"] == CONTROL_SYMBOLS
        and manifest["effective_start"] == "2018-01-02"
        and manifest["effective_end"] == END
        and manifest["requested_start"] == START
        and manifest["requested_end"] == END,
        "september24_manifest_scope_changed",
    )
    names = {"prices.parquet", "source-audit.json", "builder-snapshot.py"}
    _require(
        set(manifest["artifacts"]) == names
        and {p.name for p in path.parent.iterdir()} == names | {"input-manifest.json"},
        "september24_payload_closure_changed",
    )
    for name, info in manifest["artifacts"].items():
        artifact = path.parent / name
        _require(
            info["path"] == name and not artifact.is_symlink() and sha(artifact) == info["sha256"],
            "september24_payload_changed",
        )
    _require(
        sha(path.parent / "prices.parquet") == PRICES_SHA, "september24_original_prices_changed"
    )
    for info in manifest["sources"]:
        _require(
            not Path(info["path"]).is_symlink() and sha(info["path"]) == info["sha256"],
            "september24_original_source_changed",
        )
    frame = pd.read_parquet(path.parent / "prices.parquet")
    _audit_frame(frame)
    return frame, manifest
