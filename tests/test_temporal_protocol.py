import pandas as pd
import pytest

from quant_system.research.temporal_protocol import (
    mature_pairs,
    recent_research_window,
    research_window_metrics,
)


def test_recent_window_moves_with_real_watermark_not_fixed_2021():
    window = recent_research_window("2026-09-08")
    assert window["training_start"] == "2022-09-01"
    assert window["training_end"] == "2026-09-08"
    assert window["historical_evaluation"] == "retrospective_not_unseen_holdout"
    assert recent_research_window("2025-08-29")["training_end"] == "2025-08-29"


def test_unmatured_labels_do_not_enter_latest_research():
    frame = pd.DataFrame(
        {"datetime": ["2026-07-31", "2026-08-31"], "label_end": ["2026-09-01", "2026-10-01"]}
    )
    assert mature_pairs(frame, "2022-09-01", "2026-09-08").datetime.tolist() == ["2026-07-31"]


def test_window_metrics_use_prior_equity_and_ignore_future_outcomes():
    result = {
        "curve": [
            {"date": "2025-12-31", "equity": 200_000},
            {"date": "2026-01-02", "equity": 180_000},
            {"date": "2026-01-05", "equity": 220_000},
            {"date": "2026-01-06", "equity": 999_999},
        ],
        "trades": [],
    }
    metrics = research_window_metrics(result, "2026-01-01", "2026-01-05")
    assert metrics["total_return"] == pytest.approx(0.1)
    assert metrics["max_drawdown"] == pytest.approx(0.1)
