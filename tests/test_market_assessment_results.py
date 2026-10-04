"""Explanations over captured real market inputs, not generated market samples."""

import json
from pathlib import Path

from quant_system.factors.market_assessment import _rule_assessment


def captured(scope):
    path = Path(__file__).parents[1] / "artifacts/market-outlook-2026-09-05" / f"{scope}-final.json"
    return json.loads(path.read_text())


def explain(scope):
    document = captured(scope)
    return _rule_assessment(
        scope,
        document["scores"],
        document["coverage"],
        document["factors"],
        document["market_rows"],
    )


def test_us_results_report_checks_instead_of_sending_the_reader_to_check():
    result = explain("us")
    assert result["headline"] == "美股估值偏高，但目前尚未出现明显的下跌信号"
    text = " ".join(result["reasons"] + result["watch_next"] + result["invalidations"])
    assert "8.50%" in text and "3.54%" in text
    assert "14.32" in text and "VIX3M" in text
    assert "已" in text
    assert all(word not in text for word in ("优先检查", "先确认", "先复核", "重新审视"))


def test_asia_checks_name_actual_hot_and_declining_markets():
    result = explain("asia")
    text = " ".join(result["reasons"] + result["watch_next"])
    assert "中国台湾" in text and "33.68%" in text
    assert "印度尼西亚" in text and "30.77%" in text
    assert "中国 A 股" in text
    assert "先复核" not in text
