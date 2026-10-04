"""Artificial original-file regressions for historical snapshot identity."""
import hashlib
import json

import pandas as pd
import pytest

from quant_system.research import admission_consumer_checks as checks
from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2.family import ArchivedCurveResolver
from quant_system.research.strategy_definition import StrategyDefinition, StrategyFactor
from tests.test_gate_v2_family_contract import example


def originals(tmp_path, monkeypatch):
    source, random = tmp_path / "source", tmp_path / "random"
    rows, directories = [], []
    for index in range(2):
        row, payload = example()
        definition = StrategyDefinition(
            kind="factor_blend", title="Artificial snapshot identity",
            symbols=["AAA", "BBB"], history_start="2019-01-01", top_n=index + 1,
            factors=[StrategyFactor(factor_id="momentum", lookback=5,
                                    direction="higher_is_better", weight=1)],
        )
        payload.pop("family_contract")
        payload.update(definition=definition.model_dump(mode="json"),
                       definition_digest=definition.content_digest,
                       profile={"id": "artificial", "symbols": ["AAA", "BBB"],
                                "benchmark_symbol": "SPY"},
                       frequency="daily", source="futu", price_adjustment="qfq")
        row = row.model_copy(update={"trial_id": f"original-{index}", "metadata": {
            "run_id": f"run-{index}", "equity_curve_digest": _hash(payload["curve"]),
            "strategy_definition_digest": definition.content_digest,
        }}).model_dump(mode="json")
        directory = source / f"strategy_library/strategy-{index}/validations/validation-original"
        directory.mkdir(parents=True)
        (directory / "platform-result.json").write_text(json.dumps(payload))
        (directory / "validation.json").write_text(json.dumps({
            "definition_digest": definition.content_digest}))
        pd.DataFrame({"timestamp": [pd.Timestamp("2020-01-02", tz="UTC")],
                      "symbol": ["AAA"], "open": [100.0], "close": [100.0]}).to_parquet(
                          directory / "prices.parquet", index=False)
        (directory / "qlib-replay.json").write_text(json.dumps({
            "scope": "artificial archive fixture", "definition_digest": definition.content_digest}))
        rows.append(row)
        directories.append(directory)
    ledger = random / "families/source-trials.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
    # Pin this declared artificial input, without changing any quality threshold
    # or substituting the resolver/freezer under test.
    monkeypatch.setattr(checks, "LEDGER_SHA", hashlib.sha256(ledger.read_bytes()).hexdigest())
    return source, random, rows, directories


def test_snapshot_preserves_both_definitions_when_curves_are_identical(tmp_path, monkeypatch):
    source, random, rows, directories = originals(tmp_path, monkeypatch)
    assert rows[0]["metadata"]["equity_curve_digest"] == rows[1]["metadata"]["equity_curve_digest"]
    output = tmp_path / "frozen"
    result = checks.freeze_family_snapshot(random, source, output)
    resolver = ArchivedCurveResolver(output, trusted_trials=rows)
    assert result["files"] == 8
    for row, directory in zip(rows, directories, strict=True):
        resolved = resolver(row)
        assert resolved is not None
        assert resolved["definition_digest"] == row["metadata"]["strategy_definition_digest"]
        for name in (
            "platform-result.json", "prices.parquet", "validation.json", "qlib-replay.json"
        ):
            original = directory / name
            alias = output / original.relative_to(source)
            assert alias.resolve() == original
            assert alias.read_bytes() == original.read_bytes()


def test_missing_selected_original_cannot_borrow_equal_curve(tmp_path, monkeypatch):
    source, random, _rows, directories = originals(tmp_path, monkeypatch)
    (directories[0] / "qlib-replay.json").unlink()
    with pytest.raises(FileNotFoundError):
        checks.freeze_family_snapshot(random, source, tmp_path / "frozen")
