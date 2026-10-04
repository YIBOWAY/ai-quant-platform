from pathlib import Path

API_TYPES = Path("src/frontend/lib/api.ts")
SCREENER_FORM = Path("src/frontend/components/forms/OptionsScreenerForm.tsx")
SCREENER_RESULTS = Path("src/frontend/components/forms/OptionsScreenerResults.tsx")


def test_options_screener_form_uses_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = SCREENER_FORM.read_text(encoding="utf-8")

    for type_name in ["OptionsScreenerCandidate", "OptionsScreenerResult"]:
        assert f"export type {type_name}" in api_types

    assert "OptionsScreenerResult" in component
    assert '"@/lib/api"' in component
    assert "type ScreenerCandidate =" not in component
    assert "type ScreenerResult =" not in component
    assert "apiPost<OptionsScreenerResult>" in component


def test_shared_options_screener_types_include_backend_response_model_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for field in [
        "underlying: string;",
        'strategy_type: "sell_put" | "covered_call";',
        'option_type: "PUT" | "CALL";',
        "underlying_price: number;",
        "historical_volatility?: number | null;",
        "hv_iv_ratio?: number | null;",
        "premium_per_contract?: number | null;",
        "trend_pass?: boolean | null;",
        "hv_iv_pass?: boolean | null;",
        "avg_daily_volume?: number | null;",
        'rating: "Strong" | "Watch" | "Avoid";',
        "scanned_expirations: string[];",
        "expiration_count: number;",
        "rejection_summary: Record<string, number>;",
        "assumptions: string[];",
    ]:
        assert field in api_types


def test_options_screener_exposes_quality_filters_and_candidate_notes() -> None:
    component = SCREENER_FORM.read_text(encoding="utf-8")
    results = SCREENER_RESULTS.read_text(encoding="utf-8")

    assert "minMarketCap" in component
    assert "minAdv" in component
    assert "minMid" in component
    assert component.count("min_market_cap: 0") >= 4
    assert "include_rejected: false" in component
    assert "showRejected" in component
    assert "candidate.notes.map" in results
    assert "translateRejectionReason(note, locale)" in results


def test_options_screener_displays_shared_ev_kernel_and_event_truth() -> None:
    results = SCREENER_RESULTS.read_text(encoding="utf-8")

    for field in [
        "candidate.extrinsic_value",
        "candidate.gross_annualized_yield",
        "candidate.pop",
        "candidate.expected_value",
        "candidate.excess_annualized_ev",
        "candidate.liquidity_factor",
        "candidate.earnings_date",
        "candidate.earnings_in_window",
        "candidate.ex_dividend_date",
        "candidate.ex_dividend_in_window",
        "candidate.take_profit_50_price",
        "candidate.manage_at_21_dte",
        "candidate.recommendation_rejection_reasons",
    ]:
        assert field in results

    assert '"POP≈"' in results
    assert '"50% TP"' in results
    assert '"乘法流动性"' in results


def test_options_screener_keeps_wide_result_rows_compact_and_localizes_stale_errors() -> None:
    component = SCREENER_FORM.read_text(encoding="utf-8")
    results = SCREENER_RESULTS.read_text(encoding="utf-8")

    assert 'resultHeaderClass = "whitespace-nowrap' in results
    assert 'resultCellClass = "whitespace-nowrap' in results
    assert "resultHeaderClass}" in results
    assert "resultCellClass}" in results
    assert "sticky left-0" in results
    assert "optionsErrorMessage(mutation.error, locale)" in component
