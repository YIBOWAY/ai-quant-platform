from pathlib import Path

API_TYPES = Path("src/frontend/lib/api.ts")
RADAR_VIEW = Path("src/frontend/components/forms/OptionsRadarView.tsx")


def test_options_radar_uses_backend_daily_scan_response_type_names() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    view = RADAR_VIEW.read_text(encoding="utf-8")

    for type_name in [
        "OptionsDailyScanDatesResponse",
        "OptionsDailyScanStatusResponse",
        "OptionsDailyScanResponse",
        "OptionsDailyScanSymbolResponse",
        "OptionsRadarCandidateResponse",
    ]:
        assert f"export type {type_name}" in api_types

    assert "export type OptionsRadarDatesResponse = OptionsDailyScanDatesResponse;" in api_types
    assert (
        "export type OptionsDailyTaskStatusResponse = "
        "OptionsDailyScanStatusResponse;"
    ) in api_types
    assert "export type OptionsRadarResponse = OptionsDailyScanResponse;" in api_types
    assert "export type OptionsRadarSymbolResponse = OptionsDailyScanSymbolResponse;" in api_types
    assert "export type OptionsRadarCandidate = OptionsRadarCandidateResponse;" in api_types
    assert "OptionsDailyScanStatusResponse" in view
    assert "OptionsDailyScanResponse" in view
    assert "apiRequest<OptionsDailyScanResponse>" in view
    assert "OptionsDailyScanRunResponse" in view
    assert 'apiPost<OptionsDailyScanRunResponse>("/api/options/daily-scan/run", {})' in view
    assert "Run Today's Scan" not in view


def test_shared_options_daily_scan_types_match_backend_required_fields() -> None:
    generated = Path("src/frontend/lib/api.generated.ts").read_text(encoding="utf-8")

    for field in [
        "is_stale: boolean",
        "snapshot_age_days: number",
        "expired_candidate_count: number",
        "shortfall_reasons:",
    ]:
        assert field in generated
    candidate_schema = generated.split(
        'OptionsRadarCandidateResponse: {', 1
    )[1].split("};", 1)[0]
    assert "global_score: number" in candidate_schema
    assert "rating:" not in candidate_schema
    assert "notes:" not in candidate_schema


def test_options_radar_symbol_detail_uses_backend_daily_scan_type_name() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    symbol_page = Path("src/frontend/app/options-radar/[symbol]/page.tsx").read_text(
        encoding="utf-8",
    )

    assert "export function getOptionsDailyScanSymbol" in api_types
    assert "apiGet<OptionsDailyScanSymbolResponse>" in api_types
    assert "getOptionsDailyScanSymbol" in symbol_page
    assert "getOptionsRadarSymbol" not in symbol_page


def test_options_radar_frontend_response_types_include_backend_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for model_name in (
        "OptionsRadarCandidateResponse",
        "OptionsDailyScanResponse",
        "OptionsDailyScanSymbolResponse",
    ):
        assert (
            f'GeneratedApiComponents["schemas"]["{model_name}"]' in api_types
        )
