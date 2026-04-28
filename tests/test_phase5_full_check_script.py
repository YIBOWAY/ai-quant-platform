from pathlib import Path

from scripts.run_spy_qqq_phase5_full_check import _write_markdown_report


def test_full_check_report_includes_exposure_adjusted_return(tmp_path) -> None:
    summary = {
        "source": "sample",
        "source_note": "test",
        "symbols": ["SPY", "QQQ"],
        "start": "2024-01-02",
        "end": "2024-01-31",
        "rows": 44,
        "factor_rows": 100,
        "target_gross_exposure": 0.5,
        "strategies": [
            {
                "strategy": "single_rsi",
                "backtest": {
                    "total_return": 0.10,
                    "exposure_adjusted_return": 0.20,
                    "sharpe": 1.0,
                    "max_drawdown": 0.03,
                    "trades": 4,
                },
                "paper": {
                    "trades": 4,
                    "risk_breaches": 0,
                    "final_equity": 110_000.0,
                },
            }
        ],
    }
    path = tmp_path / "summary.md"

    _write_markdown_report(path, summary)

    report = Path(path).read_text(encoding="utf-8")
    assert "Exposure-Adjusted Return" in report
    assert "20.0000%" in report
