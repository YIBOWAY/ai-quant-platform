"""Freeze the existing real Futu static-24+SPY panel for the current Phase2 window.

Read-only source adapter: zero provider calls, no filling and no source mixing.
This manifest is research input evidence, never PIT/full-market/capital authority.
The 09-08 dataset is not read as a fallback and is never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

import exchange_calendars as xc
import numpy as np
import pandas as pd

from quant_system.research.admission_qualifier import CONTROL_SYMBOLS
from quant_system.research.external_intake import strict_json

SCHEMA = "phase2_current_static24_inputs/v1"
DATASET = "futu24-current-20260920"
HISTORY_START = "2015-01-01"
REQUEST_START, REQUEST_END = "2018-01-01", "2026-09-19"
PRICE_SYMBOLS = [*CONTROL_SYMBOLS, "SPY"]
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

# Provider implementation packages of this repository: importing any of them is what
# makes a vendor request possible at all. The builder's own import graph already loads
# every module of ``quant_system.data.providers`` (research -> evaluation_service ->
# data.provider_factory), so the offline claim is scoped to provider modules loaded
# *after* this module was imported: only those can carry a request issued during the
# frozen-input work.
PROVIDER_MODULE_PREFIXES = (
    "quant_system.data.providers",
    "quant_system.data.provider_factory",
)


def _loaded_provider_modules() -> list[str]:
    return sorted(
        name
        for name in sys.modules
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in PROVIDER_MODULE_PREFIXES
        )
    )


_IMPORT_TIME_PROVIDER_MODULES = frozenset(_loaded_provider_modules())


def provider_request_evidence() -> dict:
    """Real ``sys.modules`` scan behind the manifest's ``provider_requests`` claim."""
    unexpected = sorted(set(_loaded_provider_modules()) - _IMPORT_TIME_PROVIDER_MODULES)
    return {
        "provider_requests": len(unexpected),
        "scanned_prefixes": list(PROVIDER_MODULE_PREFIXES),
        "provider_modules_loaded_since_import": unexpected,
        "import_time_provider_modules": sorted(_IMPORT_TIME_PROVIDER_MODULES),
    }


def require_offline_provider_free(stage: str) -> dict:
    """Refuse to certify a stage that loaded a provider module after import time."""
    evidence = provider_request_evidence()
    if evidence["provider_requests"]:
        raise ValueError(
            f"provider_module_loaded:{stage}:"
            + ",".join(evidence["provider_modules_loaded_since_import"])
        )
    return evidence


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        handle.write("\n")


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def audit_sources(source_root):
    source_root = Path(source_root).resolve()
    sessions = pd.to_datetime(
        xc.get_calendar("XNYS", start="2014-01-01", end="2027-12-31").sessions_in_range(
            HISTORY_START, REQUEST_END
        ),
        utc=True,
    )
    frames, details, issues = [], [], []
    for symbol in PRICE_SYMBOLS:
        path, metadata_path = (
            source_root / f"{symbol}.parquet",
            source_root / f"{symbol}.metadata.json",
        )
        detail = {"symbol": symbol, "path": str(path), "metadata_path": str(metadata_path)}
        try:
            _require(
                path.is_file()
                and metadata_path.is_file()
                and not path.is_symlink()
                and not metadata_path.is_symlink(),
                "source_file_missing_or_symlink",
            )
            price_sha, metadata_sha = sha(path), sha(metadata_path)
            metadata = strict_json(metadata_path.read_text())
            _require(
                metadata.get("symbol") == symbol
                and metadata.get("source") == "futu"
                and metadata.get("adjustment") == "futu_qfq"
                and metadata.get("sha256") == price_sha
                and metadata.get("status") == "available",
                "source_metadata_identity_mismatch",
            )
            raw = pd.read_parquet(path)
            _require(
                set(COLUMNS).issubset(raw) and metadata.get("rows") == len(raw),
                "source_columns_or_row_count_mismatch",
            )
            _require(
                set(raw.symbol) == {symbol}
                and set(raw.provider) == {"futu"}
                and set(raw.interval) == {"1d"}
                and set(raw.price_adjustment) == {"qfq"},
                "source_provider_or_symbol_mismatch",
            )
            for key in ("timestamp", "event_ts", "knowledge_ts"):
                raw[key] = pd.to_datetime(raw[key], utc=True, errors="raise")
                _require(raw[key].notna().all(), "source_time_missing")
            _require(
                raw.timestamp.is_monotonic_increasing and not raw.timestamp.duplicated().any(),
                "duplicate_or_unordered_sessions",
            )
            frame = raw.loc[
                raw.timestamp.between(
                    pd.Timestamp(HISTORY_START, tz="UTC"), pd.Timestamp(REQUEST_END, tz="UTC")
                ),
                COLUMNS,
            ].copy()
            actual = pd.DatetimeIndex(frame.timestamp)
            detail.update(
                missing_dates=sessions.difference(actual).strftime("%Y-%m-%d").tolist(),
                extra_dates=actual.difference(sessions).strftime("%Y-%m-%d").tolist(),
            )
            _require(actual.equals(sessions), "xnys_session_coverage_mismatch")
            numbers = frame[["open", "high", "low", "close", "volume"]].to_numpy(float)
            _require(
                np.isfinite(numbers).all()
                and (numbers[:, :4] > 0).all()
                and (numbers[:, 4] >= 0).all(),
                "ohlcv_missing_or_invalid",
            )
            _require(
                (frame.high + 1e-9 >= frame[["open", "close", "low"]].max(axis=1)).all()
                and (frame.low - 1e-9 <= frame[["open", "close", "high"]].min(axis=1)).all(),
                "ohlc_range_inconsistent",
            )
            _require(
                sha(path) == price_sha and sha(metadata_path) == metadata_sha,
                "source_changed_during_read",
            )
            detail.update(
                status="verified",
                sha256=price_sha,
                metadata_sha256=metadata_sha,
                raw_rows=len(raw),
                used_rows=len(frame),
                first_session=actual[0].date().isoformat(),
                last_session=actual[-1].date().isoformat(),
                knowledge_ts_min=frame.knowledge_ts.min().isoformat(),
                knowledge_ts_max=frame.knowledge_ts.max().isoformat(),
                original_metadata_status=metadata.get("status"),
            )
            frames.append(frame)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            detail.update(status="failed", reason=str(exc))
            issues.append({"symbol": symbol, "reason": str(exc)})
        details.append(detail)
    offline = require_offline_provider_free("source_audit")
    audit = {
        "status": "failed" if issues else "ready",
        "source_root": str(source_root),
        "history_start": HISTORY_START,
        "requested_start": REQUEST_START,
        "requested_end": REQUEST_END,
        "expected_sessions_per_symbol": len(sessions),
        "sources": details,
        "issues": issues,
        "provider_requests": offline["provider_requests"],
        "provider_request_evidence": offline,
        "fills_or_cross_source_fallbacks": 0,
    }
    return (
        None
        if issues
        else pd.concat(frames, ignore_index=True)
        .sort_values(["timestamp", "symbol"])
        .reset_index(drop=True)
    ), audit


def freeze_current_inputs(source_root, output):
    source_root, output = Path(source_root).resolve(), Path(output).resolve()
    _require(
        not output.is_relative_to(source_root) and not source_root.is_relative_to(output),
        "output_must_be_separate_from_sources",
    )
    frame, audit = audit_sources(source_root)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "source-audit.json", audit)
    (output / "builder-snapshot.py").write_bytes(Path(__file__).read_bytes())
    if frame is None:
        return {
            "status": "failed",
            "audit_path": str(output / "source-audit.json"),
            "issues": audit["issues"],
        }
    prices = output / "prices.parquet"
    frame.to_parquet(prices, index=False)
    evaluation_dates = frame.loc[
        frame.symbol.eq("SPY") & (frame.timestamp >= pd.Timestamp(REQUEST_START, tz="UTC")),
        "timestamp",
    ]
    manifest = {
        "schema": SCHEMA,
        "dataset": DATASET,
        "ordered_symbols": CONTROL_SYMBOLS,
        "benchmark_symbol": "SPY",
        "price_symbols": PRICE_SYMBOLS,
        "history_start": HISTORY_START,
        "requested_start": REQUEST_START,
        "requested_end": REQUEST_END,
        "effective_start": evaluation_dates.iloc[0].date().isoformat(),
        "effective_end": evaluation_dates.iloc[-1].date().isoformat(),
        "sessions_per_symbol": audit["expected_sessions_per_symbol"],
        "evaluation_sessions": len(evaluation_dates),
        "price_rows": len(frame),
        "provider": "futu",
        "adjustment": "qfq",
        "source_metadata_adjustment": "futu_qfq",
        "delivery": "frozen_original_files_no_new_vendor_request",
        "provider_requests": audit["provider_requests"],
        "provider_request_evidence": audit["provider_request_evidence"],
        "sources": audit["sources"],
        "artifacts": {
            name: {"path": name, "sha256": sha(output / name)}
            for name in ("prices.parquet", "source-audit.json", "builder-snapshot.py")
        },
        "historical_pit_verified": False,
        "corporate_action_vintage_verified": False,
        "broad_universe_qualified": False,
        "limitations": [
            "Explicit static 24-stock universe; survivor-selection bias remains.",
            "Saved QFQ prices are a retrospective snapshot, not historical publication-time "
            "or adjustment-vintage proof.",
            "Research input only; no admission, new capital, natural delivery "
            "or formal trial authority.",
        ],
        "predeclared_control": {
            "seed": 20260920,
            "n_variants": 500,
            "rebalance": "monthly",
            "top_n": 5,
            "weights": "equal_weight_0.2",
            "commission_bps": 1,
            "slippage_bps": 5,
            "execution_price": "next_open",
            "engine_initial_cash": 100000,
        },
        "predeclared_owner_example": {
            "expression": "(($close/Ref($close,5))-1)",
            "rebalance": "monthly",
            "top_n": 5,
            "initial_cash": 10000,
            "same_identity_as_four_symbol_sandbox": False,
            "auto_enable": False,
        },
    }
    write_json(output / "input-manifest.json", manifest)
    return {
        "status": "ready",
        "manifest_path": str(output / "input-manifest.json"),
        "manifest_sha256": sha(output / "input-manifest.json"),
        "price_rows": len(frame),
        "evaluation_sessions": len(evaluation_dates),
    }


def read_frozen_inputs(manifest_path, expected_sha256):
    """Verify exact payload/source closure, then return the already-frozen bytes."""
    path = Path(manifest_path).resolve()
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "frozen_manifest_changed")
    manifest = strict_json(raw.decode())
    from quant_system.research import admission_dataset_20260924 as september24

    if manifest.get("dataset") == september24.DATASET:
        return september24.read_frozen_inputs(path, expected_sha256)
    _require(
        manifest["schema"] == SCHEMA
        and manifest["dataset"] == DATASET
        and manifest["ordered_symbols"] == CONTROL_SYMBOLS
        and manifest["requested_start"] == REQUEST_START
        and manifest["requested_end"] == REQUEST_END,
        "frozen_manifest_scope_mismatch",
    )
    _require(
        set(manifest["artifacts"])
        == {"prices.parquet", "source-audit.json", "builder-snapshot.py"},
        "frozen_payload_closure_mismatch",
    )
    _require(
        {p.name for p in path.parent.iterdir()} == {"input-manifest.json", *manifest["artifacts"]},
        "frozen_payload_closure_mismatch",
    )
    loaded = {}
    for name, descriptor in manifest["artifacts"].items():
        artifact = path.parent / name
        _require(
            descriptor["path"] == name and artifact.is_file() and not artifact.is_symlink(),
            "frozen_payload_closure_mismatch",
        )
        contents = artifact.read_bytes()
        _require(
            hashlib.sha256(contents).hexdigest() == descriptor["sha256"], "frozen_payload_changed"
        )
        loaded[name] = contents
    _require(
        [item["symbol"] for item in manifest["sources"]] == PRICE_SYMBOLS,
        "frozen_source_scope_mismatch",
    )
    for item in manifest["sources"]:
        _require(
            sha(item["path"]) == item["sha256"]
            and sha(item["metadata_path"]) == item["metadata_sha256"],
            "frozen_source_changed",
        )
    frame = pd.read_parquet(io.BytesIO(loaded["prices.parquet"]))
    _require(len(frame) == manifest["price_rows"], "frozen_row_count_changed")
    # The deployed control runner reads the frozen payload once before its variants and
    # once after them, so this second scan refuses to certify a run whose comparison
    # imported a provider module.
    require_offline_provider_free("frozen_input_read")
    return frame, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-root", type=Path)
    source.add_argument("--source-intake-job", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.source_intake_job:
        from quant_system.research.admission_dataset_20260924 import freeze_inputs

        result = freeze_inputs(args.source_intake_job, args.output)
    else:
        result = freeze_current_inputs(args.source_root, args.output)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
