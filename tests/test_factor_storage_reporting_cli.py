from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.factors.examples import MomentumFactor
from quant_system.factors.pipeline import compute_factor_pipeline
from quant_system.factors.reporting import generate_factor_report
from quant_system.factors.storage import LocalFactorStorage

runner = CliRunner()


def test_factor_storage_writes_research_artifacts(tmp_path) -> None:
    frame = SampleOHLCVProvider().fetch_ohlcv(
        ["SPY", "AAPL"],
        start="2024-01-02",
        end="2024-01-31",
    )
    factor_results = compute_factor_pipeline(frame, factors=[MomentumFactor(lookback=3)])
    storage = LocalFactorStorage(base_dir=tmp_path)

    result_path = storage.save_factor_results(factor_results)
    report_path = storage.save_report("# Factor Report\n")

    assert result_path.exists()
    assert report_path.exists()
    assert pd.read_parquet(result_path).equals(factor_results.reset_index(drop=True))


def test_factor_report_contains_core_phase_2_sections() -> None:
    report = generate_factor_report(
        factor_results=pd.DataFrame(
            {
                "factor_id": ["momentum"],
                "factor_name": ["Momentum"],
                "signal_ts": [pd.Timestamp("2024-01-02", tz="UTC")],
                "value": [0.1],
            }
        ),
        signal_frame=pd.DataFrame({"score": [0.5]}),
        ic_frame=pd.DataFrame({"factor_id": ["momentum"], "ic": [0.2], "rank_ic": [0.3]}),
        quantile_frame=pd.DataFrame(
            {"factor_id": ["momentum"], "quantile": [1], "mean_forward_return": [0.01]}
        ),
    )

    assert "Phase 2 Factor Report" in report
    assert "Information Coefficient" in report
    assert "Quantile Returns" in report


def test_factor_run_sample_cli_generates_report_and_artifacts(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "factor",
            "run-sample",
            "--symbol",
            "SPY",
            "--symbol",
            "AAPL",
            "--start",
            "2024-01-02",
            "--end",
            "2024-02-15",
            "--lookback",
            "3",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "factor_results=" in result.output
    assert "sample data 是确定性合成序列" in result.stderr
    assert "Tiingo 数据复核" in result.stderr
    assert Path(tmp_path, "factors", "factor_results.parquet").exists()
    assert Path(tmp_path, "factors", "factor_signals.parquet").exists()
    assert Path(tmp_path, "factors", "factor_ic.parquet").exists()
    assert Path(tmp_path, "factors", "quantile_returns.parquet").exists()
    assert Path(tmp_path, "reports", "factor_report.md").exists()
    factor_results = pd.read_parquet(Path(tmp_path, "factors", "factor_results.parquet"))
    assert {"momentum", "volatility", "liquidity", "rsi", "macd"}.issubset(
        set(factor_results["factor_id"])
    )
