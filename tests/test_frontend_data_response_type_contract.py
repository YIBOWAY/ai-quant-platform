from pathlib import Path

API_TYPES = Path("src/frontend/lib/api.ts")


def test_frontend_ohlcv_type_matches_backend_response_name() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    assert "export type OHLCVResponse" in api_types
    assert "export type OhlcvResponse = OHLCVResponse;" in api_types
    assert "apiGet<OHLCVResponse>" in api_types
