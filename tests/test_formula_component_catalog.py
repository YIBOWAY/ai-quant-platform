"""Saved formulas are reusable research components, never standalone alpha proof."""

import hashlib
import json

from quant_system.config.settings import Settings
from quant_system.research import strategy_library as library
from quant_system.research.strategy_definition import (
    StrategyDefinition,
    StrategyFactor,
    formula_factor_id,
)


def _save(tmp_path, *, title="已保存研究组合", expression="$close/Max($close,252)", weight=1):
    settings = Settings()
    settings.data.data_dir = tmp_path
    factor = StrategyFactor(
        factor_id=formula_factor_id(expression),
        expression=expression,
        lookback=252,
        direction="higher_is_better",
        weight=weight,
    )
    definition = StrategyDefinition(
        kind="factor_blend",
        title=title,
        symbols=["SPY", "QQQ"],
        history_start="2015-01-02",
        rebalance="monthly",
        top_n=1,
        factors=[factor],
    )
    entry = library._save_definition(
        settings, definition, {"type": "external_intake", "job_id": "intake-sealed"}
    )
    return settings, entry, factor


def _files(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_factor_options_include_formula_embedded_in_saved_combination_without_writes(tmp_path):
    settings, _, factor = _save(tmp_path)
    before = _files(tmp_path)
    options = library.factor_options(settings)["factors"]
    row = next((x for x in options if x["factor_id"] == factor.factor_id), None)
    assert row is not None, "intake formula is stranded inside its saved combination"
    assert row["expression"] == factor.expression
    assert row["research_only"] is True
    assert row["source_refs"]
    assert _files(tmp_path) == before


def test_repeated_formula_is_one_component_with_all_strategy_origins(tmp_path):
    settings, _, factor = _save(tmp_path)
    _save(tmp_path, title="另一组合", weight=2)
    rows = [
        x for x in library.factor_options(settings)["factors"] if x["factor_id"] == factor.factor_id
    ]
    assert len(rows) == 1
    assert len(rows[0]["source_refs"]) == 2
    assert rows[0]["weight"] == 1


def test_changed_source_file_does_not_supply_a_reusable_component(tmp_path):
    settings, entry, factor = _save(tmp_path)
    path = tmp_path / "strategy_library" / entry["strategy_id"] / "definition.json"
    document = json.loads(path.read_text())
    document["title"] = "changed outside the saved receipt"
    path.write_text(json.dumps(document))
    assert factor.factor_id not in {
        x["factor_id"] for x in library.factor_options(settings)["factors"]
    }
