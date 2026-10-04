"""Real-data reference studies and isolated Qlib evaluation; never paper execution."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from quant_system.config.settings import Settings, load_settings
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.research.trials import ResearchTrial, TrialsLedger

VERSION = "research-evaluation-v1"
IMAGE = "hqa-qlib-evaluation:0.1.0"
UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLY", "XLP", "XLE"]
FETCH_START = "2015-01-01"
REFERENCE_START = "2018-01-01"


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(settings: Settings) -> Path:
    return settings.data.data_dir / "research_evaluations"


def _key_name(key: str | None) -> str:
    return "catalog" if key is None else hashlib.sha256(key.encode()).hexdigest()[:24]


def _latest(settings: Settings, key: str | None) -> Path:
    return _root(settings) / _key_name(key) / "latest.json"


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def source_digest() -> str:
    import inspect

    from quant_system.factors.registry import build_factor_registry

    code_root = Path(__file__).resolve().parents[1]
    paths = [
        "research/evaluation_service.py",
        "research/reference_backtests.py",
        "research/qlib_evaluation.py",
        "backtest/engine.py",
        "backtest/strategy.py",
        "backtest/broker.py",
        "backtest/order_generation.py",
        "backtest/metrics.py",
        "replication/reversal_momentum.py",
        "experiments/scoring.py",
        "factors/base.py",
        "d34/qlib_expr.py",
        "strategies/registry.py",
        "universe/registry.py",
    ]
    files = {name: _file_hash(code_root / name) for name in paths}
    for factor_id in build_factor_registry().factor_ids():
        factor = build_factor_registry().create(factor_id)
        files[f"factor:{factor_id}"] = _hash(
            {
                "code": inspect.getsource(type(factor)),
                "metadata": factor.metadata.model_dump(mode="json"),
            }
        )
    return _hash({"version": VERSION, "files": files})


def _empty(key=None) -> dict:
    return {
        "status": "not_started",
        "key": key,
        "run_id": None,
        "updated_at": None,
        "input_digest": None,
        "source_digest": None,
        "source": {},
        "reference": None,
        "rolling": None,
        "error": None,
        "warnings": [],
        "progress": "尚未运行真实数据评价",
    }


def _view(value):
    """Keep exact metrics, while avoiding full daily/model arrays in page payloads."""
    if isinstance(value, dict):
        shown = {
            k: _view(v)
            for k, v in value.items()
            if k
            not in {
                "daily_returns",
                "predictions",
                "labels",
                "daily",
                "benchmark_daily_returns",
                "return_dates",
                "signals",
                "trades",
                "peer_signals",
            }
        }
        if "signals" in value:
            shown["latest_signal"] = _view(value["signals"][-1]) if value["signals"] else None
        return shown
    if isinstance(value, list):
        if (
            len(value) > 400
            and isinstance(value[0], dict)
            and ("equity" in value[0] or "alpha" in value[0])
        ):
            step = math.ceil(len(value) / 400)
            return [_view(v) for v in value[::step]] + (
                [_view(value[-1])] if (len(value) - 1) % step else []
            )
        return [_view(v) for v in value]
    return value


def read_evaluation(settings: Settings, key: str | None = None) -> dict:
    if key and key.startswith("research:strategy-"):
        from quant_system.research.collection_catalog import _catalog

        item = next(
            (
                row
                for row in _catalog(
                    settings, settings.data.data_dir / "api_runs", settings.data.data_dir
                )["items"]
                if row["key"] == key
            ),
            None,
        )
        if item is None:
            return {**_empty(key), "status": "failed", "error": "未找到这份策略对应的候选记录。"}
        return {
            **_empty(key),
            "status": "ready" if item["evidence"] else "partial",
            "run_id": item["evidence"][0]["run_id"] if item["evidence"] else None,
            "updated_at": item["evidence"][0].get("created_at") if item["evidence"] else None,
            "input_digest": item.get("_validation_sha256"),
            "source_digest": item["source_digest"],
            "warnings": item["notes"],
            "source": {
                "mode": "strategy_definition",
                "candidate_id": item["id"],
                "title": item["name"],
                "description": item["description"],
                "evidence": item["evidence"],
                "links": item["links"],
            },
            "progress": "读取这份策略的冻结规则与已保存验证；未运行新回测。",
        }
    path = _latest(settings, key)
    if not path.exists():
        return _empty(key)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        from quant_system.api.schemas.research_evaluation import ResearchEvaluationResponse

        ResearchEvaluationResponse.model_validate(raw)
        if raw.get("key") != key:
            raise ValueError("evaluation_key_mismatch")
        if raw["status"] == "updating":
            try:
                pid = int(raw.get("pid", -1))
                if pid <= 0:
                    raise ValueError("invalid_evaluation_pid")
                os.kill(pid, 0)
            except (OSError, ValueError):
                raw.update(status="failed", error="上次评价已中断；不会在读取页面时自动重跑。")
        elif raw.get("source_digest") and raw["source_digest"] != source_digest():
            raw.update(status="stale", error="实现代码已变化，以下为旧版本评价，请重新运行。")
        elif key is not None:
            try:
                matches = raw.get("source", {}).get("candidate") == _candidate(settings, key)
            except (OSError, ValueError, KeyError):
                matches = False
            if not matches:
                raw.update(
                    status="stale", error="该研究的源码或配置已变化，旧评价不再代表当前实现。"
                )
        return _view(raw)
    except (OSError, ValueError, KeyError):
        return {**_empty(key), "status": "failed", "error": "评价文件无法读取，请重新运行。"}


def _candidate(settings, key):
    if key is None:
        return None
    from quant_system.research.collection_catalog import _catalog

    catalog = _catalog(settings, settings.data.data_dir / "api_runs", settings.data.data_dir)
    item = next(
        (item for item in catalog["items"] if item["key"] == key and item["kind"] == "research"),
        None,
    )
    if (
        not item
        or not item.get("source_digest")
        or (item.get("comparison") or {}).get("status") != "accepted"
    ):
        raise ValueError("research_source_unavailable")
    params = item.get("_parameters", {})
    if not params.get("expression") or not item.get("universe"):
        raise ValueError("research_expression_unavailable")
    return {
        "key": key,
        "expression": params["expression"],
        "universe": item["universe"],
        "selection_end": params["end_time"],
        "source_digest": item["source_digest"],
    }


def prepare_prices(settings: Settings, universe: list[str], end: str) -> tuple[pd.DataFrame, dict]:
    request = {
        "provider": "futu",
        "adjustment": "qfq",
        "symbols": universe,
        "start": FETCH_START,
        "end": end,
        "interval": "1d",
    }
    directory = _root(settings) / "inputs" / _hash(request)
    manifest_path, prices_path = directory / "manifest.json", directory / "prices.parquet"
    if manifest_path.exists() and prices_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("request") == request and manifest.get("prices_sha256") == _file_hash(
            prices_path
        ):
            return pd.read_parquet(prices_path), manifest
    provider, name = build_ohlcv_provider(settings, requested="futu")
    if name != "futu":
        raise ValueError("real_provider_required")
    frames = []
    for symbol in universe:
        # One source request per symbol. No substitute data or provider fallback.
        frames.append(provider.fetch_ohlcv([symbol], start=FETCH_START, end=end, interval="1d"))
    frame = pd.concat(frames, ignore_index=True)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if set(frame["symbol"]) != set(universe) or frame.duplicated(["symbol", "timestamp"]).any():
        raise ValueError("incomplete_or_duplicate_market_data")
    if set(frame["provider"]) != {"futu"} or set(frame["interval"]) != {"1d"}:
        raise ValueError("market_source_mismatch")
    if frame["timestamp"].max().date() > date.fromisoformat(end):
        raise ValueError("future_market_data")
    for field in ["open", "high", "low", "close"]:
        if not np.isfinite(frame[field]).all() or (frame[field] <= 0).any():
            raise ValueError("invalid_market_prices")
    frame = frame.sort_values(["timestamp", "symbol"], ignore_index=True)
    directory.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(prices_path, index=False)
    manifest = {
        "request": request,
        "prices_sha256": _file_hash(prices_path),
        "data_start": str(frame["timestamp"].min().date()),
        "data_end": str(frame["timestamp"].max().date()),
        "rows": len(frame),
        "captured_at": datetime.now(UTC).isoformat(),
    }
    _write(manifest_path, manifest)
    return frame, manifest


def candidate_feature(prices: pd.DataFrame, expression: str) -> pd.Series:
    from quant_system.d34.qlib_expr import compile_qlib_expr

    compiled = compile_qlib_expr(expression)
    frame = prices.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    # Only the existing AST-whitelisted compiler's generated expression is evaluated;
    # neither candidate files nor model-authored Python are executed.
    values = eval(compiled.pandas_body, {"__builtins__": {}, "frame": frame, "np": np})  # noqa: S307
    index = pd.MultiIndex.from_arrays(
        [pd.to_datetime(frame["timestamp"], utc=True), frame["symbol"]],
        names=["datetime", "instrument"],
    )
    return (
        pd.Series(np.asarray(values), index=index).sort_index().replace([np.inf, -np.inf], np.nan)
    )


def _run_qlib(directory: Path, *, runner=subprocess.run) -> dict:
    src = Path(__file__).resolve().parents[2]
    image = runner(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    ).stdout.strip()
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cpus",
        "2",
        "--memory",
        "4g",
        "--tmpfs",
        "/tmp:rw,size=512m",
        "--mount",
        f"type=bind,source={src},target=/workspace/src,readonly",
        "--mount",
        f"type=bind,source={directory.resolve()},target=/study",
        "-e",
        "PYTHONPATH=/workspace/src:/opt/rdagent",
        "-e",
        "OMP_NUM_THREADS=2",
        "-e",
        "OPENBLAS_NUM_THREADS=2",
        "--entrypoint",
        "python",
        image,
        "-m",
        "quant_system.research.qlib_evaluation",
        "--input-dir",
        "/study",
        "--output",
        "/study/qlib-result.json",
    ]
    with (directory / "qlib-runtime.log").open("w") as log:
        result = runner(command, stdout=log, stderr=subprocess.STDOUT, timeout=1800, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"qlib_evaluation_exit_{result.returncode}")
    output = json.loads((directory / "qlib-result.json").read_text())
    output["image_id"] = image
    return output


def _record_evaluation_portfolios(settings, report, *, rolling=False):
    """Record independent net portfolios, not each fold or benchmark replay."""
    source = report.get("source") or {}
    # captured_at, progress, run_id and other observation metadata do not make
    # the same frozen prices/features/config into a new trial.
    frozen_input = _hash(
        {
            "source": {
                key: source.get(key)
                for key in (
                    "prices_sha256",
                    "feature_sha256",
                    "request",
                    "universe",
                    "candidate",
                    "reference_start",
                    "benchmark",
                    "risk_free_rate",
                )
            },
            "code": report.get("source_digest"),
        }
    )
    entries = []
    if not rolling:
        entries = [
            (str(row.get("key")), row) for row in (report.get("reference") or {}).get("rows", [])
        ]
    else:
        output = report.get("rolling") or {}
        methodology = output.get("methodology") or {}
        base_features = ["momentum", "volatility", "liquidity"]
        if output.get("baseline"):
            entries.append(
                (
                    "rolling:" + _hash({"features": sorted(base_features), "method": methodology}),
                    {**output["baseline"], "_trial_control": True},
                )
            )
        for case in output.get("comparisons") or []:
            for side in ("baseline", "augmented"):
                if case.get(side):
                    subject = "rolling:" + _hash(
                        {
                            "features": sorted(case.get(side + "_features") or []),
                            "method": methodology,
                        }
                    )
                    entries.append((subject, {**case[side], "_trial_control": side == "baseline"}))
    ledger = TrialsLedger(settings.data.data_dir / "trials")
    for subject, result in entries:
        values, dates = result.get("daily_returns") or [], result.get("return_dates") or []
        available = (
            not result.get("_trial_control")
            and result.get("status") in {"available", "ready", "partial"}
            and result.get("frequency", "daily") == "daily"
            and result.get("source") == "futu"
            and result.get("price_adjustment") == "qfq"
            and len(values) > 0
            and len(values) == len(dates)
            and dates == sorted(set(dates))
            and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                for v in values
            )
        )
        binding = {
            "input": frozen_input,
            "subject": subject,
            "frequency": result.get("frequency", "daily"),
            "available": available,
            "control": bool(result.get("_trial_control")),
        }
        kwargs = {
            "kind": "qlib_backtest" if rolling else "platform_backtest",
            "subject": subject,
            "universe": report.get("source", {}).get("universe") or [],
            "source": "futu",
            "window_start": dates[0] if available else result.get("start"),
            "window_end": dates[-1] if available else result.get("end"),
            "metadata": {
                "run_id": "evaluation-portfolio-" + _hash(binding),
                "input_digest": frozen_input,
                "returns_digest": _hash({"values": values, "dates": dates}) if available else None,
                "frequency": binding["frequency"],
            },
        }
        trial = (
            ResearchTrial.record(**kwargs, daily_returns=values)
            if available
            else ResearchTrial.skipped(
                **kwargs,
                reason="rolling_baseline_control_not_new_hypothesis"
                if binding["control"]
                else "monthly_gross_not_daily_dsr"
                if binding["frequency"] == "monthly"
                else "evaluation_without_verified_net_daily_curve",
            )
        )
        ledger.append(trial)


def refresh_evaluation(settings: Settings, key: str | None = None) -> dict:
    if key and key.startswith("research:strategy-"):
        raise ValueError("strategy_definition_requires_own_validation")
    requested_at = datetime.now(UTC)
    root = _root(settings)
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / "evaluation.lock").open("a+")
    # Completed-job evaluation waits for the slot instead of losing the request.
    fcntl.flock(lock, fcntl.LOCK_EX)
    report = _empty(key)
    directory = root / "runs" / f"evaluation-{uuid4().hex}"
    try:
        latest = read_evaluation(settings, key)
        if (
            latest["status"] in {"ready", "partial"}
            and latest.get("updated_at")
            and datetime.fromisoformat(latest["updated_at"]) >= requested_at
        ):
            report = latest
            return report
        candidate = _candidate(settings, key)
        universe = list(candidate["universe"] if candidate else UNIVERSE)
        # Benchmark is fetched alongside, not added to the strategy universe.
        fetch_universe = universe + ["QQQ"] if "QQQ" not in universe else universe
        report.update(
            status="updating",
            run_id=directory.name,
            pid=os.getpid(),
            updated_at=datetime.now(UTC).isoformat(),
            source_digest=source_digest(),
            progress="取得真实 Futu 历史数据",
        )
        _write(_latest(settings, key), report)
        end = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
        prices, manifest = prepare_prices(settings, fetch_universe, end)
        from quant_system.research.reference_backtests import (
            build_reference_backtests,
            compute_reference_features,
        )

        features = compute_reference_features(prices[prices.symbol.isin(universe)])
        request = {"selection_end": None, "candidate_ids": None}
        if candidate:
            candidate_id = "candidate::" + key.split(":", 1)[1]
            features[candidate_id] = candidate_feature(
                prices[prices.symbol.isin(universe)], candidate["expression"]
            )
            request = {"selection_end": candidate["selection_end"], "candidate_ids": [candidate_id]}
        directory.mkdir(parents=True, exist_ok=True)
        prices.to_parquet(directory / "prices.parquet", index=False)
        features.to_parquet(directory / "features.parquet")
        _write(directory / "request.json", request)
        report["source"] = {
            **manifest,
            "universe": universe,
            "benchmark": "QQQ",
            "candidate": candidate,
            "feature_sha256": _file_hash(directory / "features.parquet"),
            "reference_start": REFERENCE_START,
            "membership": "fixed_present_day_universe_not_point_in_time",
            "risk_free_rate": 0.0,
        }
        report["input_digest"] = _hash(
            {"source": report["source"], "code": report["source_digest"], "request": request}
        )
        report["progress"] = "计算固定配置参考回测"
        _write(_latest(settings, key), report)
        if not candidate:
            report["reference"] = build_reference_backtests(
                prices, start=REFERENCE_START, end=manifest["data_end"]
            )
            _write(directory / "reference.json", report["reference"])
            _record_evaluation_portfolios(settings, report)
        report["progress"] = "Qlib 滚动训练、样本外预测与新因子对照"
        _write(_latest(settings, key), report)
        report["rolling"] = _run_qlib(directory)
        _record_evaluation_portfolios(settings, report, rolling=True)
        report["status"] = "ready" if report["rolling"].get("status") == "ready" else "partial"
        report["warnings"] = [
            "固定当前标的集合的历史参考，不代表历史时点成分还原。",
            "Qlib 模型测试段未参与本折训练；已研究过的因子历史不能因此变成独立的因子发现样本外。",
            "夏普按252交易日年化、无风险利率设为0，现金不计息；不是收益保证。",
        ]
        report.update(updated_at=datetime.now(UTC).isoformat(), progress="评价完成")
        _write(directory / "report.json", report)
    except Exception as exc:  # noqa: BLE001 - retain evidence and a secret-free failure
        report.update(
            status="partial" if report.get("reference") else "failed",
            error=(
                f"评价未完整完成：{type(exc).__name__} "
                f"({getattr(exc, 'code', 'evaluation_failed')})"
            ),
            progress="部分结果已保留" if report.get("reference") else "评价失败",
            updated_at=datetime.now(UTC).isoformat(),
        )
        directory.mkdir(parents=True, exist_ok=True)
        _write(directory / "report.json", report)
    finally:
        _write(_latest(settings, key), report)
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return _view(report)


def evaluate_completed_job(settings: Settings, job_id: str) -> list[dict]:
    from quant_system.research.collection_catalog import _catalog

    catalog = _catalog(settings, settings.data.data_dir / "api_runs", settings.data.data_dir)
    results = []
    for item in catalog["items"]:
        if item["kind"] != "research" or not any(
            job_id in Path(ref["path"]).parts for ref in item["source_refs"]
        ):
            continue
        previous = read_evaluation(settings, item["key"])
        if previous["status"] in {"ready", "partial", "failed", "updating"}:
            continue
        result = refresh_evaluation(settings, item["key"])
        results.append(
            {
                "key": item["key"],
                "status": result["status"],
                "run_id": result["run_id"],
                "error": result["error"],
            }
        )
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Real-data reference and Qlib evaluation")
    parser.add_argument(
        "--key", help="Exact existing research key, otherwise the registered catalog"
    )
    args = parser.parse_args(argv)
    result = refresh_evaluation(load_settings(), args.key)
    print(
        json.dumps(
            {k: result.get(k) for k in ["status", "run_id", "progress", "error"]},
            ensure_ascii=False,
        )
    )
    return int(result["status"] not in {"ready", "partial", "not_started"})


if __name__ == "__main__":
    raise SystemExit(main())
