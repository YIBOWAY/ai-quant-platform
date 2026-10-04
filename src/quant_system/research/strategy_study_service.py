"""Fixed, purpose-specific research with an optional bounded RD-Agent experiment."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import numpy as np
import pandas as pd

from quant_system.config.settings import Settings, load_settings
from quant_system.d34.research_cli import _existing_env_file
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.research.evaluation_service import _file_hash, _hash, _view, _write
from quant_system.research.profile_backtests import run_formula_profile, run_profile
from quant_system.research.study_active_evidence import project_study_active_metrics
from quant_system.research.study_profiles import list_study_profiles
from quant_system.research.study_runtime import StudyRuntimeError, resolve_docker_executable
from quant_system.research.study_signal_diagnostics import monthly_pairs
from quant_system.research.temporal_protocol import recent_research_window, research_window_metrics
from quant_system.research.trials import ResearchTrial, TrialsLedger

VERSION = "purpose-specific-studies-v2"
START = "2018-01-01"
FETCH_START = "2015-01-01"
TRAIN_END = "2021-12-31"
IMAGE = "hqa-qlib-evaluation:0.1.0"


def _root(settings):
    return settings.data.data_dir / "strategy_studies"


def calculation_digest():
    source = Path(__file__).resolve().parents[1]
    paths = [
        "research/study_profiles.py",
        "research/profile_backtests.py",
        "research/reference_backtests.py",
        "research/study_signal_diagnostics.py",
        "backtest/engine.py",
        "backtest/models.py",
        "backtest/metrics.py",
        "backtest/broker.py",
        "backtest/order_generation.py",
        "d34/qlib_expr.py",
    ]
    return _hash({"version": VERSION, "files": {p: _file_hash(source / p) for p in paths}})


def _empty():
    return {
        "status": "not_started",
        "run_id": None,
        "updated_at": None,
        "protocol_digest": None,
        "calculation_digest": None,
        "profiles": list_study_profiles(),
        "source": {},
        "results": [],
        "discovery": None,
        "progress": "尚未运行用途研究",
        "error": None,
        "warnings": [],
        "stages": {},
    }


def _run_directory(settings, run_id):
    if not re.fullmatch(r"study-[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("invalid_study_run_id")
    directory = _root(settings) / "runs" / run_id
    if directory.resolve().parent != (_root(settings) / "runs").resolve():
        raise ValueError("invalid_study_run_path")
    return directory


def _discovery_from_report(report):
    saved = report.get("discovery")
    if not isinstance(saved, dict):
        return None
    discovery = {
        **deepcopy(saved),
        "origin_run_id": saved.get("origin_run_id") or report.get("run_id"),
        "evaluated_at": saved.get("evaluated_at") or report.get("updated_at"),
        "calculation_digest": saved.get("calculation_digest") or report.get("calculation_digest"),
        "prices_sha256": saved.get("prices_sha256")
        or report.get("source", {}).get("prices_sha256"),
    }
    return _correct_discovery_time(discovery, report)


def _correct_discovery_time(discovery, origin_report):
    """Correct the old start-time projection only from that discovery's final report."""
    if (
        discovery.get("origin_run_id") != origin_report.get("run_id")
        or origin_report.get("status") not in {"ready", "partial", "failed", "stale"}
        or (origin_report.get("discovery") or {}).get("generated_at")
        != discovery.get("generated_at")
    ):
        return discovery
    try:
        generated = pd.to_datetime(discovery.get("generated_at"), utc=True)
        evaluated = pd.to_datetime(discovery.get("evaluated_at"), utc=True)
        completed = pd.to_datetime(origin_report.get("updated_at"), utc=True)
        if evaluated < generated <= completed:
            discovery = {
                **discovery,
                "evaluated_at": origin_report["updated_at"],
                "evaluated_at_source": "origin_report.updated_at",
                "original_evaluated_at": discovery.get("evaluated_at"),
            }
    except (ValueError, TypeError):
        # No trustworthy completion timestamp: retain the original evidence.
        pass
    return discovery


def _retain_discovery(settings, report):
    """Repair the read projection of older interrupted refreshes, without writes."""
    saved = _discovery_from_report(report)
    if not saved or not (saved.get("proposals") or saved.get("results")):
        candidates = []
        for path in (_root(settings) / "runs").glob("*/report.json"):
            try:
                previous = json.loads(path.read_text())
                if (
                    report.get("updated_at")
                    and previous.get("updated_at", "") > report["updated_at"]
                ):
                    continue
                discovery = _discovery_from_report(previous)
                if discovery and (discovery.get("proposals") or discovery.get("results")):
                    candidates.append(discovery)
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        if candidates:
            retained = max(candidates, key=lambda value: value.get("evaluated_at") or "")
            if saved and saved.get("status") == "failed":
                retained["last_attempt"] = saved
            saved = retained
    if saved and saved.get("origin_run_id") and saved["origin_run_id"] != report.get("run_id"):
        try:
            origin = _run_directory(settings, saved["origin_run_id"]) / "report.json"
            saved = _correct_discovery_time(saved, json.loads(origin.read_text()))
        except (OSError, ValueError, TypeError):
            pass
    if saved and (
        saved.get("calculation_digest") != report.get("calculation_digest")
        or saved.get("prices_sha256") != report.get("source", {}).get("prices_sha256")
    ):
        saved.update(status="stale", evaluation_status="stale")
    report["discovery"] = saved
    return report


def _study_view(report):
    shown = _view(report)
    window = (shown.get("discovery") or {}).get("research_window")
    if window:
        shown["warnings"] = [
            text for text in shown.get("warnings", []) if not text.startswith("模型只接收2018–2021")
        ]
        if window["note"] not in shown["warnings"]:
            shown["warnings"].append(window["note"])
    for original, displayed in zip(
        report.get("results", []), shown.get("results", []), strict=True
    ):
        displayed["signal_dates"] = [row["signal_date"] for row in original.get("signals", [])]
        profile_id = quote(original["profile"]["id"], safe="")
        displayed["detail_url"] = (
            f"/api/strategy-studies/{report['run_id']}/profiles/{profile_id}"
            if report.get("run_id")
            else None
        )
    return shown


def read_studies(settings: Settings, run_id: str | None = None) -> dict:
    path = (
        _run_directory(settings, run_id) / "report.json"
        if run_id
        else _root(settings) / "latest.json"
    )
    if not path.exists():
        if run_id:
            raise KeyError("study_run_not_found")
        return _empty()
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or not isinstance(value.get("results"), list):
            raise ValueError("invalid_study_report")
        if value["status"] == "updating":
            try:
                pid = int(value["pid"])
                if pid <= 0:
                    raise ValueError("invalid_pid")
                os.kill(pid, 0)
            except (OSError, ValueError):
                value.update(status="failed", error="上次研究已中断，可显式重新运行。")
        elif value.get("calculation_digest") != calculation_digest():
            value.update(
                status="stale",
                error=(value.get("error") or "") + "计算实现已变化，以下为旧版本结果。",
            )
        return _study_view(
            project_study_active_metrics(settings, _retain_discovery(settings, value))
        )
    except (OSError, ValueError, KeyError, TypeError):
        return {**_empty(), "status": "failed", "error": "已保存研究无法读取"}


def read_study_profile(
    settings: Settings, run_id: str, profile_id: str, *, signal_date=None
) -> dict:
    """Read an exact saved result. No provider, backtest engine or model is invoked."""
    directory = _run_directory(settings, run_id)
    try:
        report = json.loads((directory / "report.json").read_text())
    except FileNotFoundError as exc:
        raise KeyError("study_run_not_found") from exc
    studies = report.get("results", []) + (report.get("discovery") or {}).get("results", [])
    study = next(
        (item for item in studies if item.get("profile", {}).get("id") == profile_id), None
    )
    if study is None:
        raise KeyError("study_profile_not_found")
    signals = study.get("signals", [])
    selected = (
        [row for row in signals if row["signal_date"] == signal_date] if signal_date else signals
    )
    if signal_date and not selected:
        raise KeyError("study_signal_date_not_found")
    dates = {row["trade_date"] for row in selected}
    trades = [row for row in study.get("trades", []) if not signal_date or row["date"] in dates]
    reconciliation = {"status": "unavailable", "reason": "缺少可核验的原始行情快照"}
    path = directory / "prices.parquet"
    if path.is_file() and _file_hash(path) == report.get("source", {}).get("prices_sha256"):
        from quant_system.research.study_reconciliation import reconcile_saved_study

        try:
            prices = pd.read_parquet(path)
            reconciliation = reconcile_saved_study(
                study, prices, selected[0]["trade_date"] if signal_date else None
            )
            full = reconcile_saved_study(study, prices, None)
            reconciliation["full_period"] = {
                "status": full["status"],
                "as_of": full.get("as_of"),
                "net_profit": full.get("equity", 0) - full.get("initial_cash", 0)
                if full["status"] == "matched"
                else None,
                "attribution": full.get("attribution", []) if full["status"] == "matched" else [],
            }
        except (OSError, ValueError, KeyError, TypeError):
            reconciliation = {"status": "unavailable", "reason": "已保存成交或行情证据格式不完整"}
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile": study["profile"],
        "status": study.get("status", "unavailable"),
        "signal_dates": [row["signal_date"] for row in signals],
        "selected_signal_date": signal_date,
        "signals": selected,
        "trades": trades,
        "reconciliation": reconciliation,
        "source": {
            key: report.get("source", {}).get(key)
            for key in ("provider", "adjustment", "data_start", "data_end", "prices_sha256")
        },
        "provenance": {
            key: report.get(key)
            for key in ("run_id", "updated_at", "protocol_digest", "calculation_digest")
        },
    }


def _collect_prices(settings, symbols, end):
    """Reuse verified same-request Futu snapshots; record every unavailable symbol."""
    roots = [settings.data.data_dir / "research_evaluations" / "inputs", _root(settings) / "prices"]
    cached = {}
    for root in roots:
        if not root.exists():
            continue
        for manifest_path in sorted(root.glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text())
                request = manifest["request"]
                path = manifest_path.parent / "prices.parquet"
                if not (
                    request["provider"] == "futu"
                    and request["adjustment"] == "qfq"
                    and request["interval"] == "1d"
                    and request["start"] == FETCH_START
                    and request["end"] == end
                    and _file_hash(path) == manifest["prices_sha256"]
                ):
                    continue
                frame = pd.read_parquet(path)
                for symbol in set(frame.symbol) & set(symbols):
                    cached[symbol] = (frame[frame.symbol == symbol], manifest)
            except (OSError, ValueError, KeyError):
                continue
    provider, source = build_ohlcv_provider(settings, requested="futu")
    if source != "futu":
        raise ValueError("futu_required")
    frames, errors, origins = [], {}, {}
    for symbol in symbols:
        try:
            if symbol in cached:
                frame, manifest = cached[symbol]
            else:
                frame = provider.fetch_ohlcv([symbol], start=FETCH_START, end=end, interval="1d")
                if frame.empty or set(frame.symbol) != {symbol}:
                    raise ValueError("missing_symbol_history")
                request = {
                    "provider": "futu",
                    "adjustment": "qfq",
                    "symbols": [symbol],
                    "start": FETCH_START,
                    "end": end,
                    "interval": "1d",
                }
                destination = _root(settings) / "prices" / _hash(request)
                destination.mkdir(parents=True, exist_ok=True)
                frame.to_parquet(destination / "prices.parquet", index=False)
                manifest = {
                    "request": request,
                    "prices_sha256": _file_hash(destination / "prices.parquet"),
                    "captured_at": datetime.now(UTC).isoformat(),
                }
                _write(destination / "manifest.json", manifest)
            if set(frame.provider) != {"futu"} or set(frame.price_adjustment) != {"qfq"}:
                raise ValueError("source_mismatch")
            frames.append(frame)
            origins[symbol] = {
                "prices_sha256": manifest["prices_sha256"],
                "captured_at": manifest.get("captured_at"),
                "rows": len(frame),
                "start": str(frame.timestamp.min())[:10],
                "end": str(frame.timestamp.max())[:10],
            }
        except Exception as exc:  # noqa: BLE001 - no provider substitution or silent universe change
            errors[symbol] = str(getattr(exc, "code", type(exc).__name__))
    if not frames:
        raise ValueError("no_real_prices")
    prices = pd.concat(frames, ignore_index=True).sort_values(
        ["timestamp", "symbol"], ignore_index=True
    )
    if prices.duplicated(["timestamp", "symbol"]).any():
        raise ValueError("duplicate_prices")
    return prices, {
        "provider": "futu",
        "adjustment": "qfq",
        "requested_symbols": symbols,
        "by_symbol": origins,
        "unavailable_symbols": errors,
        "rows": len(prices),
        "data_start": str(prices.timestamp.min())[:10],
        "data_end": str(prices.timestamp.max())[:10],
    }


def _docker(directory, module, args, *, model=False):
    src = Path(__file__).resolve().parents[2]
    command = [
        resolve_docker_executable(),
        "run",
        "--rm",
        "--read-only",
        "--cpus",
        "2",
        "--memory",
        "4g",
        "--tmpfs",
        "/tmp:rw,size=512m",
        "--workdir",
        "/study",
        "--mount",
        f"type=bind,source={src},target=/workspace/src,readonly",
        "--mount",
        f"type=bind,source={directory.resolve()},target=/study",
        "-e",
        "PYTHONPATH=/workspace/src:/opt/rdagent",
        "-e",
        "OPENBLAS_NUM_THREADS=2",
        "-e",
        "LITELLM_LOCAL_MODEL_COST_MAP=True",
    ]
    if model:
        env_path = _existing_env_file(Path(__file__).resolve().parents[3])
        command += ["--env-file", str(env_path)]
    else:
        command += ["--network", "none"]
    command += ["--entrypoint", "python", IMAGE, "-m", module, *args]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=600 if model else 120, check=False
        )
    except FileNotFoundError as exc:
        raise StudyRuntimeError(f"无法启动 Docker 可执行文件：{command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise StudyRuntimeError("Docker 研究容器超过阶段时限") from exc
    # Never persist raw stdout/stderr from model infrastructure: it may contain context.
    if result.returncode != 0:
        raise StudyRuntimeError(f"Docker 研究容器退出码 {result.returncode}；阶段未生成有效结果")


def _diagnostics(directory, prices, results, *, research_window=None):
    pairs = []
    for result in results:
        if result.get("status") != "available":
            continue
        frame = monthly_pairs(prices, result)
        if not frame.empty:
            frame["study_id"] = result["profile"]["id"]
            pairs.append(frame)
    if not pairs:
        return
    pd.concat(pairs, ignore_index=True).to_parquet(directory / "signal-pairs.parquet", index=False)
    args = ["--pairs", "/study/signal-pairs.parquet", "--output", "/study/signal-statistics.json"]
    if research_window:
        args += [
            "--research-start",
            research_window["training_start"],
            "--research-end",
            research_window["training_end"],
        ]
    _docker(
        directory,
        "quant_system.research.study_signal_diagnostics",
        args,
    )
    statistics = json.loads((directory / "signal-statistics.json").read_text())
    for result in results:
        result["signal_diagnostics"] = statistics.get(
            result["profile"]["id"],
            {"status": "not_applicable", "reason": "单标的择时不使用横截面IC"},
        )


def _training_facts(results, universe, *, research_window=None):
    statistics = []
    for result in results:
        if result["profile"]["id"] not in {"stocks_momentum_12_2", "stocks_price_multifactor"}:
            continue
        train = result.get("splits", {}).get("train", {})
        metrics = train.get("metrics", {})
        signal = result.get("signal_diagnostics", {}).get("splits", {}).get("train", {})
        if research_window:
            metrics = research_window_metrics(
                result, research_window["training_start"], research_window["training_end"]
            )
            signal = result.get("signal_diagnostics", {}).get("research", {})
        if result.get("status") != "available" or not metrics:
            continue
        statistics.append(
            {
                "id": result["profile"]["id"],
                "expression": None,
                "observations": int(signal.get("samples", 0)),
                "rank_ic": signal.get("rank_ic"),
                "ic_ir": signal.get("rank_ic_ir"),
                **{k: metrics.get(k) for k in ["sharpe", "annualized_return", "max_drawdown"]},
            }
        )
    if not statistics:
        raise ValueError("training_evidence_unavailable")
    return {
        "training_start": research_window["training_start"] if research_window else START,
        "training_end": research_window["training_end"] if research_window else TRAIN_END,
        "universe": universe,
        "factor_statistics": statistics,
    }


def _record_study_result(settings, result, prices_digest, *, attempt_id, audit_only=None):
    """Write once at the owning workflow, not once per gross/benchmark replay."""
    profile = result.get("profile") or {}
    curve = result.get("curve") or []
    if (
        audit_only is None
        and result.get("status") == "available"
        and curve
        and result.get("source") == "futu"
        and result.get("price_adjustment") == "qfq"
    ):
        from quant_system.research.strategy_library import _record_trial

        identity = _hash({"profile": profile, "prices": prices_digest, "curve": curve})
        _record_trial(
            settings,
            result,
            "recorded-study-" + identity,
            profile["symbols"],
            study_prices_digest=prices_digest,
        )
        return
    reason = audit_only or "study_without_verified_net_daily_curve"
    TrialsLedger(settings.data.data_dir / "trials").append(
        ResearchTrial.skipped(
            kind="platform_backtest",
            subject=str(profile.get("id") or "study"),
            universe=profile.get("symbols") or [],
            source="futu",
            reason=reason,
            window_start=result.get("start"),
            window_end=result.get("end"),
            metadata={
                "run_id": "study-audit-"
                + _hash(
                    {
                        "attempt": attempt_id,
                        "prices": prices_digest,
                        "profile": profile,
                        "reason": reason,
                    }
                ),
                "prices_digest": prices_digest,
            },
        )
    )


def _discover(settings, directory, prices, results):
    from quant_system.research.bounded_discovery import proposal_protocol_digest
    from quant_system.research.study_profiles import STOCKS

    window = recent_research_window(str(prices.timestamp.max())[:10])
    _diagnostics(directory, prices, results, research_window=window)
    facts = _training_facts(results, list(STOCKS), research_window=window)
    identity = {
        "facts": facts,
        "proposal_protocol": proposal_protocol_digest(),
    }
    cache = _root(settings) / "hypotheses" / _hash(identity)
    cache.mkdir(parents=True, exist_ok=True)
    if not (cache / "proposals.json").exists():
        _write(cache / "training.json", facts)
        try:
            _docker(
                cache,
                "quant_system.research.bounded_discovery",
                ["--facts", "/study/training.json", "--output", "/study/proposals.json"],
                model=True,
            )
        except RuntimeError:
            if not (cache / "proposals.json").exists():
                raise
    proposals = json.loads((cache / "proposals.json").read_text())
    # This immutable proposal file exists before validation/test outcome calculation.
    experiment_results = []
    seen = []
    discovery_dir = directory / "discovery"
    discovery_dir.mkdir(exist_ok=True)
    prices_digest = _file_hash(directory / "prices.parquet")
    for proposal in proposals.get("proposals", []):
        if proposal.get("status") != "frozen":
            continue
        training = run_formula_profile(
            prices,
            proposal["expression"],
            start=window["training_start"],
            end=window["training_end"],
            proposal_id=proposal["id"],
            title=proposal["title"],
        )
        reason, ranks = _signal_rejection(training, seen)
        _write(discovery_dir / ("training-" + _hash(proposal["id"])[:24] + ".json"), training)
        _record_study_result(
            settings,
            training,
            prices_digest,
            attempt_id=f"{directory.name}:training:{proposal['id']}",
            audit_only=None if reason else "training_partition_of_same_full_hypothesis",
        )
        if reason:
            proposal.update(status="rejected", reason=reason)
            continue
        seen.append(ranks)
        result = run_formula_profile(
            prices,
            proposal["expression"],
            start=START,
            end=str(prices.timestamp.max())[:10],
            proposal_id=proposal["id"],
            title=proposal["title"],
        )
        experiment_results.append(result)
        _write(discovery_dir / ("result-" + _hash(proposal["id"])[:24] + ".json"), result)
        _record_study_result(
            settings, result, prices_digest, attempt_id=f"{directory.name}:full:{proposal['id']}"
        )
    _diagnostics(discovery_dir, prices, experiment_results)
    return {
        **proposals,
        "results": experiment_results,
        "training_end": window["training_end"],
        "research_window": window,
        "evaluation_scope": "retrospective_research_then_forward_observation",
        "evaluation_status": "evaluated" if proposals.get("status") == "frozen" else "failed",
        "proposal_sha256": _file_hash(cache / "proposals.json"),
    }


def _signal_rejection(training, seen):
    """Reject unusable or equivalent ranking rules using training data only."""
    if training.get("status") != "available":
        return "训练期公式无法计算有效组合：" + str(training.get("reason")), None
    records = []
    for signal in training.get("signals", []):
        records.extend(
            {"date": signal["signal_date"], "symbol": row["symbol"], "score": row.get("score")}
            for row in signal.get("scores", [])
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        return "训练期信号全部缺失", None
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=["score"])
    if frame.empty or frame.groupby("date").score.nunique().max() < 2:
        return "训练期信号为常数，不能用于横截面排序", None
    ranks = (
        frame.set_index(["date", "symbol"]).score.groupby(level="date").rank(pct=True).sort_index()
    )
    if any(
        ranks.index.equals(other.index) and np.allclose(ranks, other, atol=1e-12, rtol=0)
        for other in seen
    ):
        return "训练期排序与本批已提出的公式完全相同", None
    return None, ranks


_STAGE_NAMES = {
    "prices": "真实行情快照",
    "backtests": "固定方案回测",
    "signal_diagnostics": "Qlib 信号诊断",
    "discovery": "RD-Agent 因子探索",
}


def _failure_message(stage, exc):
    if isinstance(exc, StudyRuntimeError):
        description = str(exc)
    elif isinstance(exc, FileNotFoundError):
        description = (
            f"缺少文件或可执行程序：{Path(exc.filename).name if exc.filename else '未提供文件名'}"
        )
    else:
        # Provider and model exceptions may embed credentials or context.
        description = f"{type(exc).__name__}，该阶段未生成完整结果"
    return f"{_STAGE_NAMES[stage]}失败：{description}"


def _checkpoint(root, directory, report):
    _write(directory / "report.json", report)
    _write(root / "latest.json", report)


def _stage(report, name, status, **details):
    report.setdefault("stages", {})[name] = {
        "status": status,
        "updated_at": datetime.now(UTC).isoformat(),
        **details,
    }


def run_studies(settings: Settings, *, include_discovery=False) -> dict:
    root = _root(settings)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "run.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous_path = root / "latest.json"
        try:
            previous = json.loads(previous_path.read_text())
        except (OSError, ValueError):
            previous = {}
        result = _empty()
        directory = root / "runs" / f"study-{uuid4().hex}"
        directory.mkdir(parents=True)
        profiles = list_study_profiles()
        protocol = {
            "version": VERSION,
            "profiles": profiles,
            "evaluation_start": START,
            "historical_training_end": TRAIN_END,
            "research_window_rule": "last_four_years_through_completed_data_watermark",
            "validation_end": "2024-12-31",
            "test_start": "2025-01-01",
        }
        _write(directory / "protocol.json", protocol)
        result.update(
            status="updating",
            run_id=directory.name,
            pid=os.getpid(),
            protocol_digest=_hash(protocol),
            calculation_digest=calculation_digest(),
            updated_at=datetime.now(UTC).isoformat(),
            progress="取得各研究方案的真实行情",
        )
        result["discovery"] = _discovery_from_report(_retain_discovery(settings, previous))
        stage = "prices"
        _stage(result, stage, "updating")
        _checkpoint(root, directory, result)
        try:
            symbols = list(
                dict.fromkeys(s for p in profiles for s in [*p["symbols"], p["benchmark_symbol"]])
            )
            prices, source = _collect_prices(
                settings, symbols, (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
            )
            prices.to_parquet(directory / "prices.parquet", index=False)
            result["source"] = {**source, "prices_sha256": _file_hash(directory / "prices.parquet")}
            _retain_discovery(settings, result)
            _stage(result, stage, "ready")
            stage = "backtests"
            _stage(result, stage, "updating")
            for profile in profiles:
                result["progress"] = "计算：" + profile["name"]
                _checkpoint(root, directory, result)
                study = run_profile(prices, profile["id"], start=START, end=source["data_end"])
                result["results"].append(study)
                _write(directory / (profile["id"] + ".json"), study)
                _record_study_result(
                    settings,
                    study,
                    result["source"]["prices_sha256"],
                    attempt_id=f"{directory.name}:{profile['id']}",
                )
                _checkpoint(root, directory, result)
            _stage(
                result,
                stage,
                "ready"
                if all(r["status"] == "available" for r in result["results"])
                else "partial",
            )
            stage = "signal_diagnostics"
            _stage(result, stage, "updating")
            result["progress"] = "Qlib核验与实际持有月份匹配的信号"
            _checkpoint(root, directory, result)
            _diagnostics(directory, prices, result["results"])
            _stage(result, stage, "ready")
            for study in result["results"]:
                _write(directory / (study["profile"]["id"] + ".json"), study)
            if include_discovery:
                stage = "discovery"
                _stage(result, stage, "updating")
                result["progress"] = "RD-Agent提出最多3条训练期假说，再逐条评价"
                _checkpoint(root, directory, result)
                try:
                    discovered = _discover(settings, directory, prices, result["results"])
                    discovered["evaluated_at"] = datetime.now(UTC).isoformat()
                    if discovered.get("status") == "failed" and result.get("discovery"):
                        result["discovery"]["last_attempt"] = discovered
                    else:
                        result["discovery"] = discovered
                        result["discovery"] = _discovery_from_report(result)
                    _stage(
                        result, stage, "failed" if discovered.get("status") == "failed" else "ready"
                    )
                except Exception as exc:  # noqa: BLE001 - keep public studies when LLM fails
                    failure = {
                        "status": "failed",
                        "error": _failure_message(stage, exc),
                        "proposals": [],
                        "results": [],
                    }
                    if result.get("discovery"):
                        result["discovery"]["last_attempt"] = failure
                    else:
                        result["discovery"] = failure
                    _stage(result, stage, "failed", error=failure["error"])
                    result["error"] = failure["error"]
            else:
                _stage(result, "discovery", "not_requested")
            result["status"] = (
                "ready" if all(r["status"] == "available" for r in result["results"]) else "partial"
            )
            if (result.get("discovery") or {}).get("status") == "failed" or result["stages"].get(
                "discovery", {}
            ).get("status") == "failed":
                result["status"] = "partial"
            result.update(updated_at=datetime.now(UTC).isoformat(), progress="用途研究完成")
            result["warnings"] = [
                "静态现存股票名单有幸存者偏差，不能据此证明全市场超额。",
                "方案事先固定，不按测试期收益挑选参数或只保留赢家。",
                "同池等权对照用于分开股票池本身与排序规则的作用；风险水平仍需比较。",
            ]
            if result.get("discovery"):
                result["warnings"].append(
                    "模型接收该次研究窗口内的统计；已看过的历史属于回顾性研究，前瞻证据从定义冻结后开始。"
                )
        except Exception as exc:  # noqa: BLE001 - no mock data or falsified completion
            message = _failure_message(stage, exc)
            _stage(result, stage, "failed", error=message)
            result.update(
                status="partial" if result["results"] else "failed",
                error=message,
                progress="保留已完成部分",
            )
        _retain_discovery(settings, result)
        _checkpoint(root, directory, result)
        return _study_view(result)


def recover_study_diagnostics(settings: Settings, run_id: str) -> dict:
    """Resume only Qlib diagnostics from an exact saved run; no fetch/model/backtest."""
    root = _root(settings)
    directory = _run_directory(settings, run_id)
    if not (directory / "report.json").is_file():
        raise KeyError("study_run_not_found")
    with (root / "run.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = json.loads((directory / "report.json").read_text())
        prices_path = directory / "prices.parquet"
        if _file_hash(prices_path) != report.get("source", {}).get("prices_sha256"):
            raise ValueError("study_prices_digest_mismatch")
        if report.get("stages", {}).get("signal_diagnostics", {}).get("status") == "ready":
            return _study_view(_retain_discovery(settings, report))
        # The original report and source identity survive recovery unchanged.
        previous = {key: report.get(key) for key in ("status", "error", "updated_at")}
        _retain_discovery(settings, report)
        try:
            _diagnostics(directory, pd.read_parquet(prices_path), report["results"])
            _stage(report, "signal_diagnostics", "ready")
            report.update(
                status="ready"
                if report["results"] and all(r["status"] == "available" for r in report["results"])
                else "partial",
                error=None,
                progress="已恢复 Qlib 信号诊断；原回测与历史探索保留",
            )
            if report.get("stages", {}).get("discovery", {}).get("status") == "failed":
                report.update(status="partial", error=report["stages"]["discovery"].get("error"))
            for study in report["results"]:
                _write(directory / (study["profile"]["id"] + ".json"), study)
        except Exception as exc:  # noqa: BLE001 - persist the exact interrupted phase
            message = _failure_message("signal_diagnostics", exc)
            _stage(report, "signal_diagnostics", "failed", error=message)
            report.update(
                status="partial", error=message, progress="Qlib 诊断恢复未完成，原回测保留"
            )
        report["recovery"] = {
            "stage": "signal_diagnostics",
            "recovered_at": datetime.now(UTC).isoformat(),
            **{f"previous_{key}": value for key, value in previous.items()},
        }
        _write(directory / "report.json", report)
        latest = (
            json.loads((root / "latest.json").read_text())
            if (root / "latest.json").exists()
            else {}
        )
        if latest.get("run_id") == run_id:
            _write(root / "latest.json", report)
        return _study_view(report)


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--recover-diagnostics", metavar="RUN_ID")
    args = parser.parse_args()
    if args.recover_diagnostics and args.discover:
        parser.error("--recover-diagnostics cannot request --discover")
    result = (
        recover_study_diagnostics(load_settings(), args.recover_diagnostics)
        if args.recover_diagnostics
        else run_studies(load_settings(), include_discovery=args.discover)
    )
    print(
        json.dumps(
            {k: result.get(k) for k in ["status", "run_id", "error", "progress"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
