"""Persistence glue for factor scorecards: artifact layout, staleness, DSR tombstone.

Reads never recompute statistics; writes land under
``<data_dir>/factor_scorecards/`` (``runs/scorecard-<uuid>/`` plus ``latest.json``).
Legacy provider refreshes append a skipped tombstone. Selected wide-universe
runs are immutable archives: reads and refreshes only verify the saved bytes,
never fetch a provider, recompute statistics, or write a trial/account record.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_system.data.provider_factory import DataProviderUnavailableError, build_ohlcv_provider
from quant_system.factors.pipeline import compute_factor_pipeline
from quant_system.factors.registry import build_factor_registry
from quant_system.factors.scorecard import (
    SCORECARD_SCHEMA_VERSION,
    build_factor_scorecard_bundle,
    provenance_is_stale,
)
from quant_system.universe.registry import build_default_universe_registry

SCORECARD_DIR_NAME = "factor_scorecards"
ARTIFACT_NAMES = ("ic_daily", "quantile_daily", "long_short_daily", "correlation_daily", "audit")
NO_SCORECARD_RUN_REASON = "no_scorecard_run"
LATEST_UNREADABLE_REASON = "latest_scorecard_unreadable"
_STORED_STATUSES = ("ready", "partial", "unavailable", "updating")
WIDE_SELECTION = "wide-selection.json"
WIDE_FILES = {
    "scorecard.json",
    "run-config.json",
    "input-manifest.json",
    "skip-registry.json",
    "factor-coverage.json",
    *(f"{name}.parquet" for name in ARTIFACT_NAMES),
}
_WIDE_NAMES = {
    "momentum": ("20 日动量", "20-day momentum", "比较过去 20 个交易日的价格变化。"),
    "volatility": ("20 日波动率", "20-day volatility", "观察日收益波动，按原定义以低波动为优。"),
    "liquidity": ("20 日成交额", "20-day liquidity", "观察过去 20 日平均成交金额的对数。"),
    "rsi": ("14 日 RSI 反转", "14-day RSI reversal", "衡量近期涨跌强弱，按原定义关注低 RSI。"),
    "macd": ("MACD 柱值", "MACD histogram", "观察价格趋势与信号线之间的差异。"),
    "agent_candidate_wave2_sceneb_mom20_v3": (
        "20 日动量登记版本",
        "Registered 20-day momentum",
        "保留已登记动量实现，并披露与内置动量的重复关系。",
    ),
    "paper_reversal_momentum_proxy_v2": (
        "短期反转与长期动量",
        "Reversal and long-term momentum",
        "合并近一个月反转与此前长期动量的原始代理定义。",
    ),
    "formula_fcc06e9c023c8e3f": (
        "距 252 日高点",
        "Distance to 252-day high",
        "比较收盘价与 252 日最高收盘价。",
    ),
    "formula_e9ec66887a62cb89": (
        "126 日非流动性",
        "126-day illiquidity",
        "衡量单位成交金额对应的价格变化；保留提案的原方向。",
    ),
    "formula_68350bf276a2a793": (
        "21 日极端上涨反转",
        "21-day extreme-return reversal",
        "对近 21 日最大单日涨幅取负值。",
    ),
    "formula_9e56df092c6f2fb0": (
        "60 日趋势质量",
        "60-day trend quality",
        "比较平均日收益与日收益波动。",
    ),
    "formula_c62d1250f8302415": (
        "21 日隔夜收益",
        "21-day overnight return",
        "观察前收盘到当日开盘的平均变化。",
    ),
    "formula_b66b213aacc0fc66": (
        "5 日短期反转",
        "5-day reversal",
        "对最近五日的日收益取反向平均。",
    ),
    "formula_6d955a021e897eee": (
        "21 日日内收益",
        "21-day intraday return",
        "观察开盘到收盘的平均变化。",
    ),
    "formula_588af785d5b97dd5": (
        "5 / 49 日量比",
        "5 / 49-day volume ratio",
        "比较短期与较长期的平均成交量。",
    ),
    "formula_a318aeea101855ed": (
        "30 日对数收盘价（诊断）",
        "30-day log close diagnostic",
        "原诊断公式，仅是对数价格均值，不称为波动率。",
    ),
    "formula_935e569eb6d466ac": (
        "30 日相对高低价差",
        "30-day relative price range",
        "观察每日高低价差相对低价的平均值。",
    ),
    "formula_8ec472f12dee0d1f": (
        "30 日对数最高价（诊断）",
        "30-day log high diagnostic",
        "原诊断公式，仅是对数最高价均值。",
    ),
    "formula_a974503e7b46e115": (
        "30 日对数价差",
        "30-day log price range",
        "观察对数最高价减对数最低价；保留等价变体关系。",
    ),
    "formula_90a6dd4e7a8f06c4": (
        "30 日高低价比对数",
        "30-day log high-low ratio",
        "观察高低价比的对数，与对数价差分别登记。",
    ),
    "formula_97bfebd272e499bd": (
        "30 日反向对数价差",
        "30-day negative log range",
        "对对数高低价差取反向值。",
    ),
    "formula_ef9ac7ff3d5608d3": (
        "20 日价格路径效率",
        "20-day price efficiency",
        "比较净价格位移与累计每日绝对变化。",
    ),
    "formula_b3ac9f6ae9705b36": (
        "20 日涨跌方向均值",
        "20-day return direction",
        "统计近 20 日涨跌符号的平均值。",
    ),
    "formula_7f12cf82b242c0b5": (
        "63 日下跌幅度",
        "63-day downside magnitude",
        "保留原公式，对下跌日的价格变化作非对称度量。",
    ),
    "pmf_momentum_12_2": (
        "月末 12–2 动量分量",
        "Month-end 12–2 momentum",
        "跳过最近一个月，观察此前长期动量；仅在月末评价。",
    ),
    "pmf_low_vol_252": (
        "月末 252 日低波动分量",
        "Month-end 252-day low volatility",
        "对 252 日日收益波动取负值；仅在月末评价。",
    ),
    "pmf_reversal_1m": (
        "月末一个月反转分量",
        "Month-end one-month reversal",
        "对最近一个月收益取负值；仅在月末评价。",
    ),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wide_payload(run_dir: Path, expected: str) -> dict:
    """Validate completed immutable output bytes, then add presentation metadata."""
    try:
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected)
            or _sha(run_dir / "output-digests.json") != expected
        ):
            raise ValueError("wide_output_manifest_mismatch")
        digests = json.loads((run_dir / "output-digests.json").read_text())
        if not isinstance(digests, dict) or not WIDE_FILES.issubset(digests):
            raise ValueError("wide_output_incomplete")
        if set(digests) != WIDE_FILES or {p.name for p in run_dir.iterdir()} != WIDE_FILES | {
            "output-digests.json"
        }:
            raise ValueError("wide_output_not_closed")
        for name, digest in digests.items():
            if Path(name).name != name or name in {".", "..", "output-digests.json"}:
                raise ValueError("wide_output_invalid_filename")
            if _sha(run_dir / name) != digest:
                raise ValueError("wide_output_digest_mismatch")
        card = json.loads((run_dir / "scorecard.json").read_text())
        config = json.loads((run_dir / "run-config.json").read_text())
        acceptance = json.loads((run_dir / "skip-registry.json").read_text())
        coverage = json.loads((run_dir / "factor-coverage.json").read_text())["factors"]
        if not all(isinstance(item, dict) for item in (card, config, acceptance)):
            raise ValueError("wide_output_invalid_schema")
        if not _latest_shape_ok(card) or card.get("schema_version") != SCORECARD_SCHEMA_VERSION:
            raise ValueError("wide_scorecard_invalid")
        config_body = {k: v for k, v in config.items() if k != "digest"}
        calculated = hashlib.sha256(
            json.dumps(config_body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        identity = card["wide_run"]
        if (
            calculated != config["digest"]
            or identity["factor_manifest_digest"] != calculated
            or identity["factor_manifest_file_sha256"] != digests["run-config.json"]
            or identity["input_manifest_sha256"] != digests["input-manifest.json"]
        ):
            raise ValueError("wide_input_identity_mismatch")
        expected_ids = {item["factor_id"] for item in config["objects"]}
        actual_ids = [item["factor_id"] for item in card["factors"]]
        if (
            len(expected_ids) != 27
            or len(actual_ids) != 27
            or set(actual_ids) != expected_ids
            or {item["factor_id"] for item in coverage} != expected_ids
        ):
            raise ValueError("wide_factor_set_incomplete")
        if (
            identity.get("admission_authority") is not False
            or acceptance.get("admission_authority") is not False
            or acceptance != card.get("data_acceptance")
        ):
            raise ValueError("wide_research_scope_mismatch")
        catalog = []
        for item in config["objects"]:
            key = item["factor_id"]
            if key not in _WIDE_NAMES:
                raise ValueError("wide_factor_definition_unknown")
            chinese, english, purpose = _WIDE_NAMES[key]
            catalog.append(
                {
                    **item,
                    "name_zh": chinese,
                    "name_en": english,
                    "purpose_zh": purpose,
                    "purpose_en": english + "; fixed research definition.",
                    "definition": item.get("qlib", item.get("definition", key)),
                }
            )
        card.update(
            factor_catalog=catalog,
            factor_coverage=coverage,
            stale=provenance_is_stale(card.get("provenance")),
            progress="",
            error=None,
        )
        card["run"] = {
            "run_id": f"wide-{expected[:20]}",
            "run_dir": str(run_dir),
            "kind": "wide_universe",
            "refresh_mode": "verify_saved_run",
            "output_manifest_sha256": expected,
            "href": "/research-evaluation?tab=scorecards",
        }
        return card
    except FileNotFoundError as exc:
        raise ValueError("wide_output_incomplete") from exc
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("wide_output_invalid_schema") from exc


def record_scorecard_operation(
    settings, *, output_dir=None, action: str, status: str, reason: str | None = None
) -> None:
    _write_latest(
        _base_dir(settings, output_dir) / "operation.json",
        {
            "action": action,
            "status": status,
            "reason": reason,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def _with_operation(payload: dict, base: Path) -> dict:
    try:
        operation = json.loads((base / "operation.json").read_text())
        if (
            isinstance(operation, dict)
            and operation.get("status") in {"running", "completed", "failed"}
            and (operation.get("reason") is None or isinstance(operation.get("reason"), str))
        ):
            payload["operation"] = operation
            if operation.get("status") == "failed":
                payload["error"] = operation.get("reason", "scorecard_operation_failed")
    except (OSError, ValueError):
        pass
    return payload


def _read_selected_wide(base: Path) -> dict:
    try:
        selection = json.loads((base / WIDE_SELECTION).read_text())
        run_id = selection["run_id"]
        if not re.fullmatch(r"wide-[0-9a-f]{20}", run_id):
            raise ValueError("wide_selection_invalid")
        payload = _wide_payload(base / "runs" / run_id, selection["output_manifest_sha256"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, ValueError) and str(exc).startswith("wide_")
            else "wide_selection_invalid"
        )
        payload = {
            **_unavailable(reason),
            "factors": [],
            "run": {"kind": "wide_universe", "refresh_mode": "verify_saved_run"},
        }
    return _with_operation(payload, base)


def _has_wide_selection_or_history(base: Path) -> bool:
    return (base / WIDE_SELECTION).exists() or any(
        (base / "runs").glob("wide-????????????????????")
    )


def import_wide_scorecard(
    settings,
    run_dir: str | Path,
    *,
    expected_output_manifest_sha256: str,
    output_dir: str | Path | None = None,
) -> dict:
    """Explicit local import. Validation/copy failures retain the previous selection."""
    base = _base_dir(settings, output_dir)
    record_scorecard_operation(settings, output_dir=base, action="import", status="running")
    temporary = None
    try:
        source = Path(run_dir)
        checked = _wide_payload(source, expected_output_manifest_sha256)
        target = base / "runs" / checked["run"]["run_id"]
        if not target.exists():
            temporary = target.parent / f".import-{uuid.uuid4().hex}"
            temporary.mkdir(parents=True, exist_ok=False)
            names = json.loads((source / "output-digests.json").read_text())
            for name in [*names, "output-digests.json"]:
                shutil.copyfile(source / name, temporary / name)
            _wide_payload(temporary, expected_output_manifest_sha256)
            temporary.rename(target)
            temporary = None
        _wide_payload(target, expected_output_manifest_sha256)
        _write_latest(
            base / WIDE_SELECTION,
            {
                "run_id": checked["run"]["run_id"],
                "output_manifest_sha256": expected_output_manifest_sha256,
            },
        )
        record_scorecard_operation(settings, output_dir=base, action="import", status="completed")
        return _read_selected_wide(base)
    except Exception as exc:
        reason = (
            str(exc)
            if isinstance(exc, ValueError) and str(exc).startswith("wide_")
            else "wide_import_failed"
        )
        record_scorecard_operation(
            settings, output_dir=base, action="import", status="failed", reason=reason
        )
        raise
    finally:
        if temporary is not None and temporary.is_dir():
            shutil.rmtree(temporary)


def _base_dir(settings, output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        return Path(output_dir)
    return Path(settings.data.data_dir) / SCORECARD_DIR_NAME


def _unavailable(reason: str) -> dict:
    """Shape shared by every "nothing usable stored" read answer."""
    return {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "status": "unavailable",
        "reason": reason,
        "stale": False,
    }


def _write_latest(path: Path, value: dict) -> None:
    """Write ``latest.json`` atomically (temp file + ``os.replace``).

    A plain ``write_text`` can be observed half-written by a concurrent GET; the
    rename is atomic on the same filesystem, so a reader sees either the previous
    deck or the complete new one, never a truncated one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _write_artifact(frame: pd.DataFrame, path: Path) -> None:
    if frame.empty and not len(frame.columns):
        frame = pd.DataFrame({"empty": pd.Series(dtype="object")})
    frame.to_parquet(path, index=False)


def _default_library_factor_results(
    registry, ohlcv: pd.DataFrame | None, lookback: int
) -> pd.DataFrame:
    """Compute the registry default factor set (examples + promoted) on ``ohlcv``.

    This is the "库内默认因子集" the scorecard correlates the candidate against when the
    caller does not pass ``library_factor_results``. Values may not be obtainable (never
    computed, empty registry, a factor that cannot be evaluated on this panel); in that
    case an empty frame is returned so the scorecard reports an explicit
    ``library_factor_values_unavailable`` reason instead of silently pretending the
    library was never supplied.
    """
    if ohlcv is None:
        return pd.DataFrame()
    factor_ids = registry.factor_ids()
    if not factor_ids:
        return pd.DataFrame()
    try:
        factors = [registry.create(factor_id, lookback=lookback) for factor_id in factor_ids]
        return compute_factor_pipeline(ohlcv, factors=factors)
    except Exception:  # noqa: BLE001 - surfaced as an explicit reason, never silently
        return pd.DataFrame()


def refresh_factor_scorecards(
    settings,
    request: Mapping[str, Any] | None = None,
    *,
    output_dir: str | Path | None = None,
    factor_results: pd.DataFrame | None = None,
    ohlcv: pd.DataFrame | None = None,
    library_factor_results: pd.DataFrame | None = None,
    sleeve_returns=None,
) -> dict:
    """Build, persist and register one scorecard run; returns the stored payload."""
    base = _base_dir(settings, output_dir)
    if _has_wide_selection_or_history(base):
        record_scorecard_operation(settings, output_dir=base, action="refresh", status="running")
        selected = _read_selected_wide(base)
        if selected.get("reason"):
            record_scorecard_operation(
                settings,
                output_dir=base,
                action="refresh",
                status="failed",
                reason=selected["reason"],
            )
        else:
            record_scorecard_operation(
                settings, output_dir=base, action="refresh", status="completed"
            )
        return _read_selected_wide(base)
    request = dict(request or {})
    provider = str(request.get("provider", "futu"))
    universe_id = str(request.get("universe_id", "etf"))
    start = str(request.get("start", "2024-01-02"))
    end = str(request.get("end", "2024-12-31"))
    benchmark = str(request.get("benchmark_symbol", "SPY"))
    horizons = tuple(int(horizon) for horizon in request.get("horizons", (1, 5, 21)))
    quantiles = int(request.get("quantiles", 5))
    lookback = int(request.get("lookback", 20))

    registry = build_factor_registry()
    if factor_results is None or ohlcv is None:
        universe = build_default_universe_registry().get(universe_id)
        symbols = sorted(set(universe.normalized_symbols()).union({benchmark.upper().strip()}))
        provider_instance, source = build_ohlcv_provider(settings, requested=provider)
        try:
            ohlcv = provider_instance.fetch_ohlcv(symbols, start=start, end=end)
        except Exception as exc:  # noqa: BLE001 - provider errors are re-raised typed
            raise DataProviderUnavailableError(provider, exc.__class__.__name__) from exc
        factors = [
            registry.create(factor_id, lookback=lookback) for factor_id in registry.factor_ids()
        ]
        factor_results = compute_factor_pipeline(ohlcv, factors=factors)
        # In this path the candidate set *is* the registry default set, so it doubles as
        # the peer library without recomputation.
        peers = library_factor_results if library_factor_results is not None else factor_results
    else:
        source = str(request.get("source", "injected"))
        symbols = sorted(set(ohlcv["symbol"].astype(str).str.upper()))
        # Design §1.2/§3.6: when the caller does not inject the peer library, the service
        # computes the registry default factor set on the same panel and injects it.
        peers = (
            library_factor_results
            if library_factor_results is not None
            else _default_library_factor_results(registry, ohlcv, lookback)
        )

    scorecard, artifacts = build_factor_scorecard_bundle(
        factor_results=factor_results,
        ohlcv=ohlcv,
        factor_metadata=registry.list_metadata(),
        benchmark_symbol=benchmark,
        sleeve_returns=sleeve_returns,
        horizons=horizons,
        quantiles=quantiles,
        library_factor_results=peers,
    )

    base = _base_dir(settings, output_dir)
    run_id = f"scorecard-{uuid.uuid4().hex}"
    run_dir = base / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "provider": provider,
        "universe_id": universe_id,
        "start": start,
        "end": end,
        "benchmark_symbol": benchmark,
        "horizons": list(horizons),
        "quantiles": quantiles,
        "lookback": lookback,
    }
    (run_dir / "request.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "scorecard.json").write_text(
        json.dumps(scorecard, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for name in ARTIFACT_NAMES:
        _write_artifact(artifacts.get(name, pd.DataFrame()), run_dir / f"{name}.parquet")

    latest = {
        **scorecard,
        "run": {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "request": payload,
            "generated_at": datetime.now(UTC).isoformat(),
        },
    }
    base.mkdir(parents=True, exist_ok=True)
    _write_latest(base / "latest.json", latest)
    _persist_scorecard_tombstone(
        settings=settings,
        run_id=run_id,
        symbols=symbols,
        start=start,
        end=end,
        source=source,
        input_digest=scorecard["provenance"]["input_digest"],
        request=payload,
    )
    return latest


def _persist_scorecard_tombstone(
    *,
    settings,
    run_id: str,
    symbols: list[str],
    start: str,
    end: str,
    source: str,
    input_digest: str,
    request: Mapping[str, Any],
) -> None:
    from quant_system.research.trials import ResearchTrial, TrialsLedger  # noqa: PLC0415

    TrialsLedger(Path(settings.data.data_dir) / "trials").append(
        ResearchTrial.skipped(
            kind="factor_scorecard",
            subject="factor_scorecard_refresh",
            universe=symbols,
            reason="evaluation_dashboard_not_dsr_family",
            window_start=start,
            window_end=end,
            source=source,
            metadata={
                "run_id": run_id,
                "input_digest": input_digest,
                "request": dict(request),
            },
        )
    )


def _latest_shape_ok(payload: Mapping[str, Any]) -> bool:
    """Mirror the response model's top-level types so a valid-JSON deck with
    wrong-typed members also answers ``unavailable`` instead of failing
    response validation with a 500."""

    if payload.get("status") not in _STORED_STATUSES:
        return False
    for key in ("schema_version", "generated_at", "reason", "error"):
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            return False
    for key in ("methodology", "provenance"):
        if not isinstance(payload.get(key, {}), dict):
            return False
    if not isinstance(payload.get("factors", []), list):
        return False
    if payload.get("run") is not None and not isinstance(payload.get("run"), dict):
        return False
    for key in ("data_acceptance", "wide_run", "operation"):
        if payload.get(key) is not None and not isinstance(payload[key], dict):
            return False
    for key in ("factor_catalog", "factor_coverage"):
        if not isinstance(payload.get(key, []), list):
            return False
    return isinstance(payload.get("progress", ""), str)


def read_factor_scorecards(settings, *, output_dir: str | Path | None = None) -> dict:
    """Read the latest stored scorecard and flag it stale when the source changed.

    A stored deck that cannot be parsed (truncated, invalid JSON, byte-damaged, JSON
    that is not an object, or an object whose top-level members do not match the
    response types) is reported as ``unavailable`` with an explicit reason instead of
    raising: the GET route is observational and must not answer 500 because of a
    damaged file. A missing file keeps its own ``no_scorecard_run`` reason.
    """
    base = _base_dir(settings, output_dir)
    if _has_wide_selection_or_history(base):
        return _read_selected_wide(base)
    latest_path = base / "latest.json"
    try:
        raw = latest_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _with_operation(_unavailable(NO_SCORECARD_RUN_REASON), base)
    except (OSError, UnicodeDecodeError):
        # UnicodeDecodeError subclasses ValueError, not OSError: a byte-damaged
        # file must land here too, or the observational GET answers 500.
        return _unavailable(LATEST_UNREADABLE_REASON)
    try:
        payload = json.loads(raw)
    except ValueError:
        return _unavailable(LATEST_UNREADABLE_REASON)
    if not isinstance(payload, dict) or not _latest_shape_ok(payload):
        return _unavailable(LATEST_UNREADABLE_REASON)
    provenance = payload.get("provenance")
    payload["stale"] = provenance_is_stale(provenance)
    return _with_operation(payload, base)
