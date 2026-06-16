import re
from pathlib import Path

from pydantic import BaseModel

from quant_system.api.schemas import options_radar

API_TYPES = Path("src/frontend/lib/api.ts")
RADAR_VIEW = Path("src/frontend/components/forms/OptionsRadarView.tsx")


def _frontend_type_fields(type_name: str) -> set[str]:
    api_types = API_TYPES.read_text(encoding="utf-8")
    match = re.search(
        rf"export type {re.escape(type_name)} = (?:ApiEnvelope & )?\{{(?P<body>.*?)\n\}};",
        api_types,
        flags=re.DOTALL,
    )
    assert match is not None, f"{type_name} is not exported from {API_TYPES}"
    return set(
        re.findall(
            r"^\s*([A-Za-z_][A-Za-z0-9_]*)\??:",
            match.group("body"),
            re.MULTILINE,
        )
    )


def _response_models(module: object) -> list[type[BaseModel]]:
    return [
        item
        for item in vars(module).values()
        if isinstance(item, type)
        and issubclass(item, BaseModel)
        and item.__name__.endswith("Response")
    ]


def test_options_radar_uses_backend_daily_scan_response_type_names() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    view = RADAR_VIEW.read_text(encoding="utf-8")

    for type_name in [
        "OptionsDailyScanDatesResponse",
        "OptionsDailyScanStatusResponse",
        "OptionsDailyScanResponse",
        "OptionsDailyScanRunResponse",
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
    assert "export type OptionsRadarRunResponse = OptionsDailyScanRunResponse;" in api_types
    assert "export type OptionsRadarSymbolResponse = OptionsDailyScanSymbolResponse;" in api_types
    assert "export type OptionsRadarCandidate = OptionsRadarCandidateResponse;" in api_types
    assert "OptionsDailyScanStatusResponse" in view
    assert "OptionsDailyScanResponse" in view
    assert "OptionsDailyScanRunResponse" in view
    assert "apiRequest<OptionsDailyScanResponse>" in view
    assert "apiPost<OptionsDailyScanRunResponse>" in view


def test_shared_options_daily_scan_types_match_backend_required_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for field in [
        "is_stale: boolean;",
        "snapshot_age_days: number;",
        "expired_candidate_count: number;",
        'provider: "sample" | "futu";',
    ]:
        assert field in api_types


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
    for response_model in _response_models(options_radar):
        backend_fields = set(response_model.model_fields)
        frontend_fields = _frontend_type_fields(response_model.__name__)

        assert backend_fields <= frontend_fields, response_model.__name__
