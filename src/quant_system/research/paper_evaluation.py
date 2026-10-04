"""Read-only paper-performance facts and a separately persisted Grok explanation.

The source is the committed sleeve journal, never the account inventory or a
backtest. Prices mark real holdings between fills without creating observations.
This module cannot create a signal or trade.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from contextlib import suppress
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from quant_system.brief.rollup_llm import RollupLlmClient
from quant_system.config.settings import Settings, load_settings
from quant_system.d34.hung_sleeve_effect import (
    build_effect_from_storage,
    collect_official_marks,
)
from quant_system.data.provider_factory import (
    DataProviderUnavailableError,
    build_ohlcv_provider,
)
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.strategy_replacement import PERFORMANCE_SCOPE_ACROSS_VERSIONS
from quant_system.research.active_metrics import sleeve_active_metrics

VERSION = "paper_evaluation_v2"
MODEL = "grok-4.6"
REASONING_EFFORT = "xhigh"
_STATUSES = {"ready", "partial", "unavailable", "failed"}
_LIMITATIONS = [
    "估值来自已提交成交和真实日线价格；缺价日留空，不能把成交日数当作完整净值日数。",
    "累计盈亏率为累计盈亏 / 累计投入，不是时间加权收益；"
    "首个成交收盘起算收益另列，仅资金不变时可用。",
    "费用数字只含已提交成交的佣金；滑点已在成交价中，但本报告没有独立的滑点金额。",
    "没有保存逐日完整预测分数与对应未来收益，无法判断在线 IC 或预测能力是否下降。",
]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return float(value) if math.isfinite(value) else None


def _digest(facts: dict) -> str:
    raw = {"facts": facts, "version": VERSION, "model": MODEL, "effort": REASONING_EFFORT}
    return hashlib.sha256(
        json.dumps(raw, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


def _official(storage: PaperStrategySleeveStorage) -> list:
    return [
        sleeve
        for sleeve in storage.list_sleeves()
        if sleeve.metadata.get("automation_source") == "d34"
        and sleeve.metadata.get("fossil") is not True
        and sleeve.metadata.get("official_observation") is not False
    ]


def _verified_version_history(storage, sleeve) -> list[dict]:
    try:
        from quant_system.execution.strategy_replacement import verified_replacement_history
    except ImportError:
        if any('replacement' in key or 'version_observation' in key for key in sleeve.metadata):
            raise ValueError('replacement_version_history_unverified') from None
        return []
    return verified_replacement_history(storage, sleeve)


def _version_performance_scope(storage, sleeve, signals) -> dict:
    history = _verified_version_history(storage, sleeve)
    if not history:
        return {}
    current = history[-1]
    effective = datetime.fromisoformat(current['effective_at'].replace('Z', '+00:00'))
    if (effective.tzinfo is None
            or current['to_config_version'] != sleeve.strategy_config_version
            or current['to_candidate_id'] != sleeve.metadata.get('candidate_id')):
        raise ValueError('replacement_version_history_mismatch')
    effective = effective.astimezone(UTC)
    version_signals = [s for s in signals
                       if s.strategy_config_id == sleeve.strategy_config_id
                       and s.strategy_config_version == sleeve.strategy_config_version]
    return {
        'performance_scope': PERFORMANCE_SCOPE_ACROSS_VERSIONS,
        'version_history': history,
        'current_version_observation_start': effective.isoformat(),
        'current_version_signal_count': len(version_signals),
        'current_version_performance': {
            'status': 'not_evaluated',
            'reason': 'version_specific_nav_not_separately_valued',
            'config_version': sleeve.strategy_config_version,
            'candidate_id': current['to_candidate_id'],
            'effective_at': effective.isoformat(),
            'note': (
                '整仓历史跨策略版本保留；尚未单独建立当前版本的净值起点，'
                '不能将升级前盈亏归给新公式。'
            ),
        },
    }


def _window(start: dict, end: dict, marks: list[dict]) -> dict:
    first = _number(start.get("sleeve_equity"))
    last = _number(end.get("sleeve_equity"))
    included = [row for row in marks if start["date"] < row["date"] <= end["date"]]
    gross = sum(row["fill_notional"] for row in included)
    commission = sum(row["cost"] for row in included)
    capital_unchanged = start.get("allocated_cash") == end.get("allocated_cash")
    return {
        "start": start["date"],
        "end": end["date"],
        "boundary": "(start, end]",
        "calendar_days": (date.fromisoformat(end["date"]) - date.fromisoformat(start["date"])).days,
        "filled_observation_count": len(included),
        "return_pct": (last / first - 1) * 100 if first and last and capital_unchanged else None,
        "fill_notional_usd": gross,
        "commission_usd": commission,
        "turnover": gross / first if first else None,
        "commission_drag_pct": commission / first * 100 if first else None,
    }


def _window_comparison(series: list[dict], marks: list[dict]) -> dict:
    """Compare disjoint holding intervals, never overlapping cumulative totals."""
    if len(series) < 3:
        return {
            "status": "unavailable",
            "reason": "至少需要三个有效估值点形成两个区间。",
            "previous": None,
            "current": None,
            "changes": None,
        }
    previous = _window(series[-3], series[-2], marks)
    current = _window(series[-2], series[-1], marks)
    comparable = (
        previous["calendar_days"] == current["calendar_days"]
        and previous["calendar_days"] > 0
        and all(_number(row["return_pct"]) is not None for row in (previous, current))
    )
    return {
        "status": "available" if comparable else "not_comparable",
        "reason": (
            "两个不重叠的估值区间；变化是区间差，也不能证明因果。"
            if comparable
            else "区间长度不同或净值缺失，保留各区间实值，不计算变化。"
        ),
        "previous": previous,
        "current": current,
        "changes": {
            "return_percentage_points": current["return_pct"] - previous["return_pct"],
            "commission_usd": current["commission_usd"] - previous["commission_usd"],
            "turnover": current["turnover"] - previous["turnover"],
            "commission_drag_percentage_points": (
                current["commission_drag_pct"] - previous["commission_drag_pct"]
            ),
        }
        if comparable
        else None,
    }


def _empty_facts(reason: str | None = None) -> dict:
    return {
        "schema_version": VERSION,
        "status": "unavailable",
        "as_of": None,
        "sleeves": [],
        "period": {
            "start": None,
            "end": None,
            "basis": "filled_observation_dates",
            "observation_count": 0,
        },
        "metrics": {},
        "observation_series": [],
        "active_metrics": None,
        "signal_health": {},
        "window_comparison": {
            "status": "unavailable",
            "reason": reason or "尚无成交观察。",
            "previous": None,
            "current": None,
            "changes": None,
        },
        "prediction_decay": {"status": "unavailable", "reason": _LIMITATIONS[3]},
        "limitations": list(_LIMITATIONS),
        "evidence": [],
        "error": reason,
    }


def build_paper_facts(settings: Settings) -> dict:
    """Read committed observations and real Futu prices; never mutate paper state."""
    facts = _empty_facts()
    storage = PaperStrategySleeveStorage(settings.data.data_dir / "api_runs")
    try:
        sleeves = _official(storage)
        # This public reader checks each fill journal and its cash/lot transitions.
        # Fail before market access when a committed state is missing or corrupt.
        _, marks = collect_official_marks(sleeve_storage=storage)
        signals: list = []
        executions: list = []
        for sleeve in sleeves:
            sleeve_signals = storage.load_signals(sleeve.sleeve_id)
            sleeve_executions = storage.load_executions(sleeve.sleeve_id)
            try:
                version_scope = _version_performance_scope(storage, sleeve, sleeve_signals)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                # One sleeve whose version boundary cannot be verified must not
                # make every other sleeve's report unverifiable; degrade its row.
                reason = type(exc).__name__ + ':' + str(exc)
                version_scope = {
                    'version_scope_status': 'unverifiable',
                    'version_scope_reason': reason,
                    'current_version_performance': {
                        'status': 'unverifiable',
                        'reason': reason,
                        'note': (
                            '该仓的版本边界无法核验；它的累计盈亏不能归给当前版本，'
                            '其余仓位与整仓汇总不受影响。'
                        ),
                    },
                }
            signals.extend(sleeve_signals)
            executions.extend(sleeve_executions)
            facts["sleeves"].append(
                {
                    "sleeve_id": sleeve.sleeve_id,
                    "candidate_id": sleeve.metadata.get("candidate_id"),
                    "status": str(sleeve.status),
                    "signal_count": len(sleeve_signals),
                    "latest_signal_date": max(
                        (s.signal_date for s in sleeve_signals), default=None
                    ),
                    **version_scope,
                }
            )
        if any(row.get('version_history') for row in facts['sleeves']):
            facts['performance_scope'] = PERFORMANCE_SCOPE_ACROSS_VERSIONS
            facts['limitations'].append(
                '本报告的整仓盈亏、费用和信号次数包含升级前后多个版本；'
                '新公式单独的前瞻表现尚未计算，不能把旧版本收益归给它。'
            )
        facts["signal_health"] = {
            "count": len(signals),
            "status_counts": dict(sorted(Counter(str(s.status) for s in signals).items())),
            "latest_signal_date": max((s.signal_date for s in signals), default=None),
            "execution_status_counts": dict(
                sorted(Counter(str(e.status) for e in executions).items())
            ),
            "signal_ids": sorted(s.signal_id for s in signals),
            "filled_execution_ids": sorted(
                e.execution_id for e in executions if str(e.status) == "filled" and e.fills
            ),
        }
        if not marks:
            effect = build_effect_from_storage(sleeve_storage=storage)
        else:
            try:
                provider, name = build_ohlcv_provider(settings, requested="futu")
            except DataProviderUnavailableError:
                provider, name = None, None
            effect = build_effect_from_storage(
                sleeve_storage=storage,
                price_provider=provider,
                price_source=f"{name}:qfq" if name else None,
            )
        if effect.get("sleeve_equity_reason") == "committed_effect_state_unavailable":
            raise ValueError("committed_effect_state_unavailable")
        series = effect["series"]
        cutoff = effect.get("requested_as_of")
        if sorted(row["date"] for row in marks if not cutoff or row["date"] <= cutoff) != [
            row["date"] for row in series if row.get("filled") is not False
        ]:
            raise ValueError("paper_observation_changed_during_read")
        # Signal/execution health remains current; performance costs stop at the
        # same actual valuation date as NAV, never at a later intraday fill.
        valued_through = effect.get("as_of")
        marks = [row for row in marks if valued_through and row["date"] <= valued_through]
        prices_valid = effect["sleeve_equity_status"] == "available"
        aggregate_ambiguous = len(sleeves) > 1 and (
            any(row.get("allocated_cash") is None for row in series)
            or len({row.get("allocated_cash") for row in series}) > 1
        )
        valid_values = (
            [row["sleeve_equity"] for row in series]
            if marks and prices_valid and not aggregate_ambiguous
            and all(row["sleeve_equity"] is not None for row in series) else []
        )
        peak = 0.0
        drawdown = 0.0
        for value in valid_values:
            peak = max(peak, value)
            drawdown = max(drawdown, (peak - value) / peak) if peak else drawdown
        if aggregate_ambiguous:
            facts["limitations"].append(
                "期内投入本金有变化或来源不足；不从合计资产涨跌计算回撤、夏普率或区间超额收益。"
            )
        sleeve_return = (
            _number(effect["sleeve_return_pct"]) if prices_valid else None
        )
        observation_return = _number(effect.get("observation_return_pct"))
        spy_return = _number(effect["spy_return_pct"]) if len(series) > 1 else None
        facts.update(
            {
                "status": "partial" if series else "unavailable",
                "as_of": effect.get("as_of"),
                "period": {
                    "start": series[0]["date"] if series else None,
                    "end": effect.get("as_of"),
                    "basis": "committed_holdings_daily_prices",
                    "observation_count": effect["observation_day_count"],
                    "closed_observation_count": sum(
                        row.get("filled") is not False for row in series
                    ),
                    "valuation_count": effect.get("valuation_day_count"),
                    "requested_as_of": effect.get("requested_as_of"),
                    "valuation_status": effect.get("valuation_status"),
                    "covered_sleeve_count": effect.get("covered_sleeve_count"),
                    "missing_valuation_dates": effect.get("missing_valuation_dates", []),
                    "allocation_time_source": effect.get("allocation_time_source"),
                },
                "metrics": {
                    "sleeve_return_pct": sleeve_return,
                    "return_method": effect.get("return_method"),
                    "net_profit_usd": effect.get("net_profit_usd"),
                    "allocated_cash_usd": effect.get("allocated_cash"),
                    "observation_return_pct": observation_return,
                    "spy_return_pct": spy_return,
                    "relative_return_percentage_points": (
                        observation_return - spy_return
                        if observation_return is not None and spy_return is not None
                        else None
                    ),
                    "sleeve_equity_usd": _number(effect["sleeve_equity"]),
                    "observed_max_drawdown_pct": drawdown * 100 if len(valid_values) > 1 else None,
                    "commission_usd": sum(row["cost"] for row in marks) if marks else None,
                    "fill_notional_usd": sum(row["fill_notional"] for row in marks)
                    if marks
                    else None,
                    "commission_drag_pct": _number(effect["cost_drag_pct"])
                    if prices_valid
                    else None,
                    "turnover": _number(effect["turnover"]) if prices_valid else None,
                    "turnover_definition": (
                        "累计买卖双边成交额 / 首个成交观察日收盘资产；不是年化换手。"
                    ),
                    "cost_definition": "仅已提交成交的佣金，不包括独立滑点金额。",
                    "cost_as_of": valued_through,
                    "slippage_usd": None,
                    "daily_sharpe": None,
                },
                "observation_series": series,
                # Active-return sibling block for the sleeve NAV leg vs SPY, the
                # same shape the study/reference/strategy seams emit. The two legs
                # are the per-observation-day real marks in ``series``; the
                # aggregate is suppressed, not faked, when capital moved mid-window.
                "active_metrics": sleeve_active_metrics(
                    series,
                    benchmark_symbol="SPY",
                    unavailable_reason=(
                        "sleeve_capital_change_ambiguous" if aggregate_ambiguous else None
                    ),
                ),
                "window_comparison": _window_comparison(series, marks)
                if marks and not aggregate_ambiguous
                else {
                    "status": "unavailable",
                    "reason": (
                        "尚无已提交成交；仅显示已分配现金估值。" if not marks else
                        "投入本金变化或来源不足，不能用合计资产比值比较区间表现。"
                    ),
                    "previous": None,
                    "current": None,
                    "changes": None,
                },
                "error": effect.get("sleeve_equity_reason"),
            }
        )
        facts["evidence"] = [
            {
                "id": "coverage",
                "fields": ["period", "sleeves", "limitations"],
                "source": "committed sleeve journals",
                "price_source": effect.get("price_source"),
            },
            {
                "id": "performance",
                "fields": ["metrics", "observation_series"],
                "source": "validated committed cash/lots and matching Futu closes",
            },
            {
                "id": "costs",
                "fields": [
                    "metrics.commission_usd",
                    "metrics.fill_notional_usd",
                    "metrics.commission_drag_pct",
                    "metrics.turnover",
                ],
                "source": "committed execution fills, metadata.commission",
            },
            {
                "id": "windows",
                "fields": ["window_comparison"],
                "source": "disjoint (start, end] intervals",
            },
            {
                "id": "signals",
                "fields": ["signal_health"],
                "source": "immutable saved signals/executions",
            },
            {
                "id": "prediction",
                "fields": ["prediction_decay"],
                "source": "no persisted matched score/label history",
            },
        ]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return _empty_facts(f"模拟运行记录暂不可核验：{type(exc).__name__}")
    return facts


def _cache_dir(settings: Settings) -> Path:
    return settings.data.data_dir / "paper_evaluations"


def _initial() -> dict:
    return {
        "status": "unavailable",
        "facts_status": "unavailable",
        "interpretation_status": "not_requested",
        "fact_archive": None,
        "fact_archive_status": "not_archived",
        "as_of": None,
        "updated_at": None,
        "input_digest": None,
        "facts": _empty_facts(),
        "analysis": None,
        "error": None,
    }


def _read_document(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("status") not in _STATUSES:
        raise ValueError("paper_evaluation_cache_invalid")
    facts = document["facts"]
    if facts.get("schema_version") != VERSION:
        raise ValueError("paper_evaluation_method_changed")
    if document["input_digest"] != _digest(facts) or document["as_of"] != facts["as_of"]:
        raise ValueError("paper_evaluation_cache_identity_mismatch")
    analysis = document.get("analysis")
    if analysis:
        if analysis.get("model") != MODEL or analysis.get("reasoning_effort") != REASONING_EFFORT:
            raise ValueError("paper_evaluation_cache_model_mismatch")
        _validate_analysis(analysis, facts)
    if document["status"] == "ready" and not analysis:
        raise ValueError("paper_evaluation_cache_missing_analysis")
    if document.get("fact_archive"):
        from quant_system.research.paper_fact_archive import read_fact_archive

        packet = read_fact_archive(path.parent, document["fact_archive"])
        if packet["facts"] != facts:
            raise ValueError("paper_evaluation_fact_archive_mismatch")
        document["fact_archive_status"] = "archived"
    else:
        document["fact_archive_status"] = "legacy_not_separately_archived"
    document["facts_status"] = facts.get("status", "unavailable")
    document.setdefault("interpretation_status", "available" if analysis else
                        "failed" if document["status"] == "failed" else "not_requested")
    return document


def read_paper_evaluation(settings: Settings) -> dict:
    """Pure cache read: no provider access, locks, writes, or model generation."""
    path = _cache_dir(settings) / "latest.json"
    if not path.exists():
        return _initial()
    try:
        document = _read_document(path)
        legacy_failure = "模拟运行 AI 解读未生成：ValueError；已保留程序计算的事实。"
        if document.get("status") == "failed" and document.get("error") == legacy_failure:
            # Old attempts did not save the validation reason or model answer.
            # Explain the limit without changing the archived failure or retrying.
            return {**document, "error": (
                "上次 AI 解读未通过校验；旧记录未保存具体原因，无法判断是哪一项。"
                "已保留程序计算的事实，未重新调用模型。"
            )}
        return document
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if str(exc) == "paper_evaluation_method_changed":
            return {
                **_initial(),
                "error": "模拟复盘口径已更新，旧摘要保留为历史；下次更新后生成新解读。",
            }
        return {
            **_initial(),
            "status": "failed",
            "error": "上次模拟运行解读无法读取，未生成新的结果。",
        }


def current_paper_summary(document: dict, effect: dict, *, issue_date: date) -> str:
    """Return a saved summary only when its observation facts match this read.

    The archive reads the current effect separately. A previously valid model
    response must not describe a newer/different performance snapshot.
    """
    facts = document["facts"]
    analysis = document["analysis"]
    series = effect["series"]
    count = effect["observation_day_count"]
    if (
        document.get("status") not in {"ready", "partial"}
        or document.get("error")
        or not isinstance(analysis, dict)
        or analysis.get("model") != MODEL
        or analysis.get("reasoning_effort") != REASONING_EFFORT
        or facts.get("error")
        or effect.get("sleeve_equity_status") != "available"
        or not isinstance(series, list)
        or not series
        or sum(row.get("filled") is not False for row in series)
        != facts["period"].get("closed_observation_count", count)
        or len(facts["sleeves"]) != effect["hung_count"]
        or facts["period"]["observation_count"] != count
        or facts["period"]["basis"] != "committed_holdings_daily_prices"
        or document["input_digest"] != _digest(facts)
    ):
        raise ValueError("paper_summary_unavailable")
    as_of = document["as_of"]
    if (
        not isinstance(as_of, str)
        or date.fromisoformat(as_of) > issue_date
        or as_of != facts["as_of"]
        or as_of != facts["period"]["end"]
        or as_of != effect.get("as_of")
        or facts["period"]["start"] != series[0]["date"]
        or facts["observation_series"] != series
    ):
        raise ValueError("paper_summary_observations_changed")
    pairs = [
        ("sleeve_equity_usd", "sleeve_equity"),
        ("commission_drag_pct", "cost_drag_pct"),
        ("turnover", "turnover"),
        ("sleeve_return_pct", "sleeve_return_pct"),
        ("net_profit_usd", "net_profit_usd"),
        ("allocated_cash_usd", "allocated_cash"),
    ]
    if count > 1:
        pairs.extend(
            [("spy_return_pct", "spy_return_pct")]
        )
    for metric, source in pairs:
        expected = _number(effect.get(source))
        actual = _number(facts["metrics"].get(metric))
        if (actual is None) != (expected is None) or (
            actual is not None and not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8)
        ):
            raise ValueError("paper_summary_performance_changed")
    _validate_analysis(analysis, facts)
    # The durable watermark identifies the evaluation. Raw internal citation IDs
    # would be unexplained jargon inside a daily newspaper paragraph.
    return re.sub(
        r"\[(?:coverage|performance|costs|windows|signals|prediction)\]", "", analysis["summary"]
    ).strip()


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_analysis(raw: dict, facts: dict) -> dict:
    ids = {item["id"] for item in facts["evidence"]}
    normalized: dict = {}
    for field in ("summary", "observations", "explanations", "limitations"):
        values = [raw.get(field)] if field == "summary" else raw.get(field)
        if not isinstance(values, list) or not 1 <= len(values) <= 6:
            raise ValueError(f"paper_analysis_invalid_{field}")
        for text in values:
            if not isinstance(text, str) or not text.strip() or len(text) > 1200:
                raise ValueError("paper_analysis_invalid_text")
            cited = set(re.findall(r"\[([a-z]+)\]", text))
            if not cited or not cited.issubset(ids):
                raise ValueError("paper_analysis_missing_fact_reference")
            prose = re.sub(r"\[[a-z]+\]", "", text)
            if re.search(r"\bIC\b|预测(?:能力|效果)?|夏普|Sharpe", prose, re.I) and not re.search(
                r"无法|不能|不可|未保存|未提供|不足|不支持|缺少|未计算|未知|不代表|尚无", prose
            ):
                raise ValueError("paper_analysis_unsupported_prediction_or_sharpe")
        normalized[field] = values[0] if field == "summary" else values
    return normalized


def _analysis_failure_message(exc: Exception) -> str:
    reasons = {
        "paper_evaluation_model_mismatch": "模型或思考程度与设置不一致",
        "paper_analysis_missing_fact_reference": "回答缺少可核对的事实引用",
        "paper_analysis_unsupported_prediction_or_sharpe": (
            "回答包含没有数据支持的预测能力或夏普率判断"
        ),
        "paper_analysis_invalid_text": "回答中有空白、过长或类型不正确的文字",
        **{f"paper_analysis_invalid_{field}": "回答未按要求提供摘要、观察、解释和限制说明"
           for field in ("summary", "observations", "explanations", "limitations")},
    }
    # Match only program-owned codes. Provider response bodies and exception
    # messages can contain private data and must not enter the saved report.
    reason = reasons.get(str(exc), "模型调用或回答解析未完成，未取得可核验的解读")
    return f"模拟运行 AI 解读未生成：{reason}；已保留程序计算的事实。"


def refresh_paper_evaluation(settings: Settings, client: Any | None = None) -> dict:
    """One explicit attempt per changed facts digest; failure cannot break a brief."""
    from quant_system.research.paper_fact_archive import capture_paper_sources, persist_fact_archive

    try:
        sources_before = capture_paper_sources(settings)
        facts = build_paper_facts(settings)
    except Exception as exc:  # External data boundary; do not expose credentials or raw IO errors.
        facts = _empty_facts(f"模拟运行数据读取失败：{type(exc).__name__}")
        sources_before = None
    try:
        sources_after = capture_paper_sources(settings)
        if sources_before is None or sources_after["digest"] != sources_before["digest"]:
            raise ValueError("paper_fact_sources_changed_during_build")
        fact_archive = persist_fact_archive(_cache_dir(settings), facts, sources_before)
    except (OSError, ValueError, TypeError, KeyError):
        failed_facts = _empty_facts("事实原件未能完整保存或来源在计算中变化；未调用AI解读。")
        failure = {"status": "failed", "as_of": None, "updated_at": datetime.now(UTC).isoformat(),
                   "input_digest": _digest(failed_facts), "facts": failed_facts, "analysis": None,
                   "facts_status": "unavailable", "interpretation_status": "not_requested",
                   "fact_archive": None, "fact_archive_status": "not_archived",
                   "error": failed_facts["error"]}
        # The returned failure never claims this diagnostic was persisted.
        with suppress(OSError, ValueError, TypeError):
            _write(_cache_dir(settings) / "latest.json", failure)
        return failure
    digest = _digest(facts)
    path = _cache_dir(settings) / f"{digest}.json"
    if path.exists():
        try:
            prior = _read_document(path)
        except (OSError, ValueError, TypeError, KeyError):
            pass
        else:
            # Includes failed attempts: ordinary scheduled refresh is not a retry loop.
            try:
                prior = {**prior, "fact_archive": fact_archive, "fact_archive_status": "archived",
                         "facts_status": facts["status"]}
                _write(_cache_dir(settings) / "latest.json", prior)
            except (OSError, ValueError, TypeError):
                return {
                    **prior,
                    "status": "failed",
                    "error": "模拟运行解读最新索引保存失败；已有历史解读保持原生成时间。",
                }
            return prior
    result = {
        "status": "unavailable",
        "as_of": facts["as_of"],
        "updated_at": datetime.now(UTC).isoformat(),
        "input_digest": digest,
        "facts": facts,
        "analysis": None,
        "error": facts.get("error"),
        "fact_archive": fact_archive,
        "fact_archive_status": "archived",
        "facts_status": facts["status"],
        "interpretation_status": "not_requested",
    }
    if (facts["period"]["observation_count"] > 0
            and facts["period"].get("valuation_count", 0) > 0 and not facts.get("error")):
        try:
            llm = client if client is not None else RollupLlmClient(model=MODEL)
            if llm.model != MODEL or llm.reasoning_effort != REASONING_EFFORT:
                raise ValueError("paper_evaluation_model_mismatch")
            raw = llm._chat_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是个人量化助手的模拟运行评价员。只根据给出的已核验事实解释，禁止调用工具、"
                            "补造行情、回测、成交或预测。使用易懂中文，少用术语。"
                            "输出 JSON：summary 字符串、observations/explanations/limitations "
                            "各 1-6 个字符串。每个字符串必须引用给出的证据 ID，如 "
                            "[performance]、[costs]、[windows]、[signals]、[prediction]、[coverage]。"
                            "成交日数和估值日数必须分开。不是实时资产；禁止自行补算日频夏普。"
                            "只有valuation_status=complete、期内投入本金不变且已提供对应非空指标时，"
                            "才可以陈述已计算的完整区间回撤；缺价或投入变化时不能从总资产推算回撤。"
                            "不存在逐日完整 score/label，所以不能断言预测能力下降或算出了 IC 衰减。"
                            "只能说已记录净值/费用/换手如何变化；不能把亏损直接归因于某原因。"
                            "佣金不是全部成本，滑点金额未知。两个区间只在 comparable 时比较；"
                            "window_comparison.status=not_comparable 时只列事实，不比较改善/恶化。"
                            "少于两个有效估值点不能评判区间表现；即使尚未再次成交，已有真实日度估值也可描述。"
                            "累计盈亏/累计投入不是时间加权收益，不能与不同资金口径的基准作超额收益。"
                            "若performance_scope=cumulative_sleeve_history_across_versions，"
                            "必须说明指标是升级前后整仓累计；当前版本独立表现未计算，"
                            "不得把旧版本利润、历史信号次数或整个区间效果归给新公式。"
                            "不要要求用户自行计算；明确已经确定和仍未知的内容。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(facts, ensure_ascii=False, allow_nan=False),
                    },
                ]
            )
            result["analysis"] = {
                **_validate_analysis(raw, facts),
                "model": llm.model,
                "reasoning_effort": llm.reasoning_effort,
                "generated_at": datetime.now(UTC).isoformat(),
            }
            result["interpretation_status"] = "available"
            result["status"] = "partial" if facts["status"] != "ready" else "ready"
        except Exception as exc:  # One model attempt; do not reuse an older-data summary.
            result["interpretation_status"] = "failed"
            result["status"] = "failed"
            result["error"] = _analysis_failure_message(exc)
    try:
        _write(path, result)
        _write(_cache_dir(settings) / "latest.json", result)
    except (OSError, ValueError, TypeError):
        result["status"] = "failed"
        result["error"] = "模拟运行解读保存失败；未将未保存结果标为最新记录。"
    return result


def main() -> int:
    """Independent 17:20 evaluation step; no archive, research or trade writes."""
    try:
        result = refresh_paper_evaluation(load_settings())
        analysis = result.get("analysis") or {}
        print(
            json.dumps(
                {
                    "paper_evaluation_status": result["status"],
                    "as_of": result["as_of"],
                    "input_digest": result["input_digest"],
                    "ai_ready": bool(analysis),
                    "model": analysis.get("model"),
                    "reasoning_effort": analysis.get("reasoning_effort"),
                    "error": result.get("error"),
                },
                ensure_ascii=False,
            )
        )
        return 1 if result.get("error") or result["status"] == "failed" else 0
    except Exception as exc:
        print(json.dumps({"paper_evaluation_error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
