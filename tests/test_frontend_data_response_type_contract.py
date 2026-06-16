from pathlib import Path

API_TYPES = Path("src/frontend/lib/api.ts")


def test_frontend_ohlcv_type_matches_backend_response_name() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    assert "export type OHLCVResponse" in api_types
    assert "export type OhlcvResponse = OHLCVResponse;" in api_types
    assert "apiGet<OHLCVResponse>" in api_types


def test_frontend_error_response_matches_backend_error_envelope_name() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    assert "export type ErrorResponse" in api_types
    assert "detail: string;" in api_types
    assert "safety?: SafetyFooter | null;" in api_types
