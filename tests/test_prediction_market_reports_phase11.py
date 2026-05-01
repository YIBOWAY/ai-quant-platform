import json

from quant_system.prediction_market.backtest import (
    PredictionMarketBacktestConfig,
    run_prediction_market_quasi_backtest,
)
from quant_system.prediction_market.charts import write_prediction_market_charts
from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider
from quant_system.prediction_market.reporting import write_phase11_backtest_report


def test_phase11_charts_and_report_are_written(tmp_path) -> None:
    result = run_prediction_market_quasi_backtest(
        provider=SamplePredictionMarketProvider(),
        config=PredictionMarketBacktestConfig(min_edge_bps=200),
    )

    chart_index = write_prediction_market_charts(result=result, output_dir=tmp_path)
    report_path = write_phase11_backtest_report(
        result=result,
        chart_index=chart_index,
        output_dir=tmp_path,
        run_id="pm-test-run",
        provider="sample",
    )

    index_path = tmp_path / "chart_index.json"
    result_path = tmp_path / "result.json"
    assert index_path.exists()
    assert result_path.exists()
    assert report_path.exists()
    assert "read-only" in report_path.read_text(encoding="utf-8").lower()

    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    chart_names = {item["name"] for item in index_payload["charts"]}
    assert {
        "opportunity_count",
        "edge_histogram",
        "cumulative_estimated_edge",
        "parameter_sensitivity",
    }.issubset(chart_names)
    for item in index_payload["charts"]:
        assert (tmp_path / item["path"]).exists()
