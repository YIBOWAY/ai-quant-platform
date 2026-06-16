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
        "PredictionMarketBacktestResponse",
    ]:
        assert f"export type {type_name}" in api_types

    for type_name in [
        "PredictionMarketScanResponse",
        "PredictionMarketDryArbitrageResponse",
        "PredictionMarketBacktestResponse",
    ]:
        assert type_name in form

    assert "type PMRunResponse =" in form
    assert "apiPost<PMRunResponse>" in form
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
