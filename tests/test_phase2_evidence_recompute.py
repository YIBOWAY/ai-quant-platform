from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

spec = importlib.util.spec_from_file_location(
    "recompute", Path(__file__).parents[1] / "scripts/recompute_phase2_evidence.py"
)
recompute = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recompute)


def test_initial_capital_seed_preserves_first_commission_in_nav_returns():
    detail = {
        "sleeve": {"initial_allocated_cash": 23456.0, "created_at": "2024-01-02T13:00:00+00:00"},
        "executions": [{"status": "filled", "target_date": "2024-01-03", "fills": [{}]}],
    }
    rows = [
        {"date": "2024-01-03", "sleeve_equity": 23454.0, "spy_close": 102.0, "filled": True},
        {"date": "2024-01-04", "sleeve_equity": 23460.0, "spy_close": 103.0, "filled": False},
    ]
    prices = pd.DataFrame(
        {
            "symbol": ["SPY"] * 3,
            "timestamp": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"], utc=True),
            "close": [100.0, 102.0, 103.0],
            "provider": ["futu"] * 3,
            "price_adjustment": ["qfq"] * 3,
        }
    )
    seeded = recompute.seed_sleeve_observations(rows, detail, prices)
    assert seeded["status"] == "ready"
    assert seeded["rows"][0]["sleeve_equity"] == 23456.0
    assert seeded["rows"][0]["date"] == "2024-01-02"
    first_return = seeded["rows"][1]["sleeve_equity"] / seeded["rows"][0]["sleeve_equity"] - 1
    assert first_return < 0
    metrics = recompute.sleeve_active_metrics(seeded["rows"])
    assert metrics["status"] == "ready"


def test_missing_initial_benchmark_mark_is_unavailable_not_guessed():
    detail = {
        "sleeve": {"initial_allocated_cash": 23456.0, "created_at": "2024-01-02T13:00:00+00:00"},
        "executions": [],
    }
    rows = [{"date": "2024-01-03", "sleeve_equity": 23454.0, "spy_close": 102.0, "filled": True}]
    result = recompute.seed_sleeve_observations(rows, detail, None)
    assert result["status"] == "unavailable"
    assert result["rows"] == []
