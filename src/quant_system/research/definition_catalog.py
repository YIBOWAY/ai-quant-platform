"""Read-only projection of one exact saved definition and its historical evidence.

This reader is intentionally separate from the strict activation verifier. It
cannot authorize a current strategy or replace a missing candidate receipt with
the latest validation of a similarly named recipe.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode

from quant_system.research.strategy_definition import (
    StrategyDefinition,
    current_source_fingerprints,
)
from quant_system.research.validation_receipts import file_sha

_FILES = ("prices.parquet", "platform-result.json", "qlib-replay.json", "signal-analysis.json")


def _read(path):
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("definition_record_invalid")
    return raw


def _archived_validation(path, record, definition):
    expected = record.get("verification_receipt_digest")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("definition_validation_unbound")
    matches = [
        p
        for p in (path.parent / "validations").glob("validation-*/validation.json")
        if p.resolve().is_relative_to(path.parent) and file_sha(p) == expected
    ]
    if len(matches) != 1:
        raise ValueError("definition_validation_missing_or_ambiguous")
    receipt_path = matches[0]
    receipt = _read(receipt_path)
    if (
        receipt.get("definition_digest") != definition.content_digest
        or receipt.get("run_id") != receipt_path.parent.name
        or receipt.get("comparison", {}).get("comparison_digest") != record.get("comparison_digest")
        or receipt.get("status") not in {"passed", "failed"}
    ):
        raise ValueError("definition_validation_identity_mismatch")
    bindings = receipt.get("receipts", {})
    files, sources = bindings.get("files", {}), bindings.get("sources", {})
    for name in _FILES:
        target = (receipt_path.parent / name).resolve()
        if not target.is_relative_to(receipt_path.parent) or file_sha(target) != files.get(name):
            raise ValueError("definition_validation_file_changed")
    platform, qlib, analysis = [_read(receipt_path.parent / name) for name in _FILES[1:]]
    if (
        any(
            v.get("definition_digest") != definition.content_digest
            for v in (platform, qlib, analysis)
        )
        or platform.get("definition") != definition.model_dump(mode="json")
        or platform.get("source") != "futu"
        or platform.get("price_adjustment") != "qfq"
        or platform.get("status") != "available"
        or qlib.get("status") != "available"
        or qlib.get("source", {}).get("prices_sha256") != files["prices.parquet"]
        or qlib.get("source", {}).get("platform_result_sha256") != files["platform-result.json"]
        or analysis.get("source", {}).get("prices_sha256") != files["prices.parquet"]
        or analysis.get("source", {}).get("result_sha256") != files["platform-result.json"]
        or qlib.get("source", {}).get("replay_source_sha256")
        != sources.get("definition_qlib_replay.py")
        or analysis.get("source", {}).get("validation_source_sha256")
        != sources.get("strategy_signal_validation.py")
        or analysis.get("source", {}).get("fit_metrics_source_sha256")
        != sources.get("qlib_evaluation.py")
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(sources.get(name, "")))
            for name in (
                "definition_qlib_replay.py",
                "strategy_signal_validation.py",
                "qlib_evaluation.py",
            )
        )
    ):
        raise ValueError("definition_validation_outputs_mismatch")
    return receipt_path, receipt, platform, qlib


def populate_definition_item(item, record, settings):
    # Local import avoids making the generic catalog and the archive adapter
    # share activation/strategy execution dependencies.
    from quant_system.research.collection_catalog import _metrics, _number

    item["comparison"] = {"status": "unavailable"}
    try:
        path = Path(str(record["source_path"])).resolve()
        root = (settings.data.data_dir / "strategy_library").resolve()
        if not path.is_relative_to(root) or path.name != "definition.json":
            raise ValueError("definition_source_outside_library")
        if file_sha(path) != record.get("source_digest"):
            raise ValueError("definition_source_changed")
        raw_definition = _read(path)
        saved_digest = str(raw_definition.get("content_digest", ""))
        if (
            not re.fullmatch(r"[0-9a-f]{64}", saved_digest)
            or path.parent.name != "strategy-" + saved_digest[:24]
            or record.get("factor_id") != "definition_" + saved_digest[:24]
            or raw_definition.get("symbols") != record.get("universe")
        ):
            raise ValueError("definition_candidate_identity_mismatch")
        # Legacy recipes can lack fields required for execution today. Their
        # exact source-bound title still identifies the historical item; do not
        # add invented defaults merely to turn them into executable recipes.
        if isinstance(raw_definition.get("title"), str):
            item["name"] = item["name_en"] = raw_definition["title"][:200]
        definition = StrategyDefinition.model_validate(raw_definition)
        strategy_id = "strategy-" + definition.content_digest[:24]
        if (
            path.parent.name != strategy_id
            or record.get("factor_id") != "definition_" + definition.content_digest[:24]
            or list(definition.symbols) != record.get("universe")
        ):
            raise ValueError("definition_candidate_identity_mismatch")
        item.update(
            name=definition.title.replace(" / baseline", " · 原组合").replace(
                " / augmented", " · 加入新因子"
            ),
            name_en=definition.title,
            source_digest=record["source_digest"],
            _source=path.read_text(),
            _parameters=definition.model_dump(mode="json"),
        )
        item["source_refs"] = [
            {"label": "冻结策略规则（JSON）", "path": str(path), "digest": record["source_digest"]}
        ]
        frequency = {"daily": "每天", "weekly": "每周", "monthly": "每月"}[definition.rebalance]
        selection = {"top": "分数最高", "positive_top": "正分且分数最高", "bottom": "分数最低"}[
            definition.selection
        ]
        rule = (
            definition.formula.expression
            if definition.formula
            else "；".join(
                f"{f.expression or f.factor_id}（权重 {f.weight:g}，"
                f"{'低值优先' if f.direction == 'lower_is_better' else '高值优先'}）"
                for f in definition.factors
            )
        )
        if definition.profile_snapshot is not None:
            rule = "；".join(
                str(value)
                for value in (
                    definition.profile_snapshot.get("formation"),
                    *(definition.profile_snapshot.get("rules") or []),
                )
                if value
            )
        item["description"] = (
            f"{frequency}在 {len(definition.symbols)} 个标的中选择{selection}的至多 "
            f"{definition.top_n} 个，目标总仓位 {definition.target_gross_exposure:.0%}，单标的上限 "
            f"{definition.max_weight_per_symbol:.0%}，下一交易日开盘执行。"
            + (f"信号规则：{rule}。" if rule else "规则详见冻结策略配置。")
        )
        item["links"].insert(
            0,
            {
                "label": "查看这份策略的规则与验证",
                "href": "/strategy-library?"
                + urlencode({"strategy": strategy_id})
                + "#strategy-"
                + strategy_id,
            },
        )
        if definition.source_fingerprints != current_source_fingerprints(definition):
            item["notes"].append(
                "当前执行代码与冻结版本不同；以下仅为该版本的历史记录，不代表当前版本已通过验证。"
            )
    except (OSError, ValueError, KeyError, TypeError):
        item["implementation_status"] = "source_unavailable"
        item["notes"].append(
            "策略规则文件与候选记录无法对应，或旧规则缺少当前要求的字段；未显示其他策略的介绍或指标。"
        )
        return
    try:
        receipt_path, receipt, platform, qlib = _archived_validation(path, record, definition)
        item["_validation_sha256"] = record["verification_receipt_digest"]
        if any(
            file_sha(Path(__file__).with_name(name)) != digest
            for name, digest in receipt["receipts"]["sources"].items()
            if name
            in {"definition_qlib_replay.py", "strategy_signal_validation.py", "qlib_evaluation.py"}
        ):
            item["notes"].append(
                "当前验证器代码已变化；原结果仍为当时保存的历史证据，不作为当前版本验证。"
            )
        for engine, result, filename in (
            ("qlib", qlib, "qlib-replay.json"),
            ("platform", platform, "platform-result.json"),
        ):
            metrics = _metrics(result.get("metrics") or {})
            if metrics.get("max_drawdown") is not None:
                metrics["max_drawdown"] = abs(metrics["max_drawdown"])
            item["evidence"].append(
                {
                    "kind": "dual_engine",
                    "engine": engine,
                    "status": "historical",
                    "run_id": receipt["run_id"],
                    "source": "futu",
                    "start": platform.get("start"),
                    "end": platform.get("end"),
                    "created_at": receipt.get("validated_at"),
                    "metrics": metrics,
                    "source_ref": str(receipt_path.parent / filename),
                    "note": (
                        "该候选绑定的历史验证；只列该引擎原文件已保存的指标，"
                        "未保存的留空。不是新的准入结论。"
                    ),
                }
            )
        comparison = receipt["comparison"]
        item["comparison"] = {
            "status": "accepted" if comparison.get("accepted") is True else "rejected",
            "daily_return_correlation": _number(comparison.get("daily_return_correlation")),
            "terminal_nav_difference_bps": _number(comparison.get("terminal_nav_difference_bps")),
        }
        item["notes"].append(
            "历史双引擎一致性只说明两种执行计算接近，不代表收益稳定，也不替代当前自动质检。"
        )
    except (OSError, ValueError, KeyError, TypeError):
        item["evidence"] = []
        item["notes"].append(
            "该候选没有可核对的专属验证文件，或原文件已变化。保留策略规则，指标留空；不会借用最新或同名策略的结果。"
        )
