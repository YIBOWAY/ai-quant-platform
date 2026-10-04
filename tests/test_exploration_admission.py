from __future__ import annotations

import json
import shutil

import pandas as pd
import pytest

from quant_system.research.behavior_review import run_research_exploration
from quant_system.research.exploration_admission import prepare_exploration_candidate
from quant_system.research.exploration_sandbox import digest


@pytest.fixture(scope="module")
def validated_run(tmp_path_factory):
    directory = tmp_path_factory.mktemp("bridge") / "run"
    rows = []
    for symbol, base in [("AAPL", 100), ("MSFT", 200), ("SPY", 300)]:
        for day, stamp in enumerate(pd.date_range("2024-01-01", periods=8, tz="UTC")):
            close = base + day * (base / 100 + 0.1)
            rows.append(
                dict(
                    symbol=symbol,
                    timestamp=stamp,
                    available_at=stamp,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=1000,
                    eligible=True,
                )
            )
    source = """
def compute(ohlcv, context):
    close = ohlcv.close.where(ohlcv.available_at <= ohlcv.timestamp)
    score = close / close.groupby(ohlcv.symbol).shift(1) - 1
    return ohlcv[['symbol', 'timestamp']].assign(score=score.where(ohlcv.eligible & close.notna()))
"""
    result = run_research_exploration(
        source, pd.DataFrame(rows), {}, expression="$close/Ref($close,1)-1", output_dir=directory
    )
    assert result["status"] == "research_candidate"
    return directory


def material():
    return {
        "source_urls": [
            "https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html"
        ],
        "source_title": "Sealed synthetic bridge test; data-interface reference only",
        "published_at": None,
        "retrieved_at": "2026-09-20T08:00:00Z",
        "hypothesis": "Local engineering fixture, not an external research claim.",
        "adaptation_note": "Synthetic fixture used only to test candidate format and integrity.",
    }


def test_real_sandbox_result_freezes_schema_valid_material_without_submitting(validated_run):
    candidate = prepare_exploration_candidate(
        validated_run,
        source_material=material(),
        ordered_symbols=["AAPL", "MSFT", "SPY"],
        data_provenance={"scope": "sealed_synthetic_test"},
    )
    assert candidate["status"] == "frozen_research_material"
    assert candidate["intake_schema_validation"]["status"] == "pass"
    assert candidate["admission_status"] == "not_evaluated"
    assert candidate["queue_submitted"] is False
    assert candidate["capital_authorized"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "not_evaluated_probe",
        "not_evaluated_causal",
        "compiler_version",
        "input_digest",
        "causal_input_digest",
        "missing_prefix",
        "source_code",
        "scorecard",
    ],
)
def test_corrupt_or_unevaluated_evidence_cannot_freeze(validated_run, tmp_path, mutation):
    directory = tmp_path / "copy"
    shutil.copytree(validated_run, directory)
    receipt = json.loads((directory / "receipt.json").read_text())
    if mutation == "not_evaluated_probe":
        receipt["behavior"]["probes"][0]["status"] = "not_evaluated"
    elif mutation == "not_evaluated_causal":
        receipt["causal_execution"]["executions"][0]["status"] = "not_evaluated"
    elif mutation == "compiler_version":
        receipt["behavior"]["reference"]["comparisons"]["baseline"]["compiler_sha256"] = "0" * 64
    elif mutation == "input_digest":
        receipt["behavior"]["input_digest"] = "0" * 64
    elif mutation == "causal_input_digest":
        receipt["causal_execution"]["executions"][0]["input_digest"] = "0" * 64
    elif mutation == "missing_prefix":
        receipt["behavior"]["probes"] = [
            p for p in receipt["behavior"]["probes"] if p.get("probe") != "prefix_truncation"
        ]
    elif mutation == "source_code":
        (directory / "factor.py").write_text("def compute(a,b): return None")
    elif mutation == "scorecard":
        (directory / "scorecard.json").write_text("{}")
    review = receipt["behavior"]
    review["review_digest"] = digest({k: v for k, v in review.items() if k != "review_digest"})
    receipt["receipt_digest"] = digest({k: v for k, v in receipt.items() if k != "receipt_digest"})
    (directory / "receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        prepare_exploration_candidate(
            directory,
            source_material=material(),
            ordered_symbols=["AAPL", "MSFT", "SPY"],
            data_provenance={"scope": "sealed_synthetic_test"},
        )
