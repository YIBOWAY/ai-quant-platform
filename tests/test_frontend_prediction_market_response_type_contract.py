from pathlib import Path

API_TYPES = Path("src/frontend/lib/api.ts")
FORM = Path("src/frontend/components/forms/PMRunForm.tsx")


def test_prediction_market_form_uses_shared_post_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    form = FORM.read_text(encoding="utf-8")

    for type_name in [
        "PredictionMarketCandidate",
        "PredictionMarketScanResponse",
        "PredictionMarketProposedLeg",
        "PredictionMarketProposedTrade",
        "PredictionMarketDryArbitrageResponse",
        "PredictionMarketBacktestRunResponse",
        "PredictionMarketRunResponse",
    ]:
        assert f"export type {type_name}" in api_types

    assert (
        "export type PredictionMarketBacktestResponse = "
        "PredictionMarketBacktestRunResponse;"
    ) in api_types
    assert "PredictionMarketRunResponse" in form
    assert "| PredictionMarketScanResponse" in api_types
    assert "| PredictionMarketDryArbitrageResponse" in api_types
    assert "| PredictionMarketBacktestRunResponse" in api_types
    assert "type PMRunResponse =" not in form
    assert "PredictionMarketScanResponse" not in form
    assert "PredictionMarketDryArbitrageResponse" not in form
    assert "apiPost<PredictionMarketRunResponse>" in form
    assert "apiPost<Record<string, unknown>>" not in form
    assert "as PredictionMarketBacktestResponse" not in form


def test_shared_prediction_market_post_types_include_backend_response_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for field in [
        "candidates: PredictionMarketCandidate[];",
        "market_id: string;",
        "condition_id: string;",
        "scanner_id: string;",
        "edge_bps: number;",
        "prices: Record<string, number>;",
        'direction: "underpriced_complete_set" | "overpriced_complete_set";',
        "candidate_id: string;",
        "proposed_trades: PredictionMarketProposedTrade[];",
        "opportunity: PredictionMarketCandidate;",
        "legs: PredictionMarketProposedLeg[];",
        "dry_run: boolean;",
        "threshold_passed: boolean;",
        "report_path: string;",
        "provider: string;",
        "cache_status?: string;",
    ]:
        assert field in api_types


def test_prediction_market_history_form_uses_backend_run_type_name() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    history_form = Path("src/frontend/components/forms/PMHistoryBacktestForm.tsx").read_text(
        encoding="utf-8"
    )

    assert "export type PredictionMarketTimeseriesBacktestRunResponse" in api_types
    assert (
        "export type PredictionMarketTimeseriesResponse = "
        "PredictionMarketTimeseriesBacktestRunResponse;"
    ) in api_types
    assert "PredictionMarketTimeseriesBacktestRunResponse" in history_form
    assert "apiPost<PredictionMarketTimeseriesBacktestRunResponse>" in history_form
