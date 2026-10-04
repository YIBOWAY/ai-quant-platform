"""Read-only catalogue of source-bound formulas saved alone or inside combinations."""

from __future__ import annotations

import hashlib
import json

from quant_system.d34.qlib_expr import compile_qlib_expr
from quant_system.research.strategy_definition import (
    StrategyFactor,
    formula_factor_id,
    validate_definition,
)


def formula_components(settings) -> list[dict]:
    """Reuse an expression, not its parent's portfolio weights or qualification."""
    components: dict[str, dict] = {}
    root = settings.data.data_dir / "strategy_library"
    for path in sorted(root.glob("strategy-*/entry.json")):
        try:
            entry = json.loads(path.read_text())
            source = path.with_name("definition.json")
            if hashlib.sha256(source.read_bytes()).hexdigest() != entry["source_sha256"]:
                continue
            definition = validate_definition(entry["definition"])
            if (
                definition.content_digest != entry["definition_digest"]
                or entry["strategy_id"] != "strategy-" + definition.content_digest[:24]
                or entry["strategy_id"] != path.parent.name
            ):
                continue
            expressions = [factor.expression for factor in definition.factors if factor.expression]
            if definition.formula:
                expressions.append(definition.formula.expression)
            for expression in dict.fromkeys(expressions):
                compiled = compile_qlib_expr(expression)
                spec = StrategyFactor(
                    factor_id=formula_factor_id(compiled.qlib),
                    expression=compiled.qlib,
                    lookback=compiled.lookback,
                    direction="higher_is_better",
                    weight=1,
                )
                row = components.setdefault(
                    spec.factor_id,
                    {
                        **spec.model_dump(mode="json"),
                        "label": f"已保存公式 · {compiled.qlib}",
                        "origin": "saved_formula",
                        "research_only": True,
                        "status": "component_not_independently_validated",
                        "source_refs": [],
                        "note": "公式可以组合研究；所属组合的通过或失败，不等于单因子有效性结论。",
                    },
                )
                origin = entry.get("origin") or {}
                row["source_refs"].append(
                    {
                        "strategy_id": entry["strategy_id"],
                        "title": entry["title"],
                        "definition_digest": definition.content_digest,
                        "source_type": origin.get("type"),
                        "job_id": origin.get("job_id"),
                        "saved_status": entry.get("status"),
                        "validation_run_id": (entry.get("validation") or {}).get("run_id"),
                    }
                )
        except (OSError, ValueError, KeyError, TypeError):
            # A broken or stale source cannot silently enter the usable catalogue.
            continue
    return list(components.values())


def get_formula_component(settings, factor_id: str) -> dict | None:
    return next(
        (row for row in formula_components(settings) if row["factor_id"] == factor_id), None
    )
