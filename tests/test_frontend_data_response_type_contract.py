import re
from pathlib import Path

from quant_system.api.schemas.health import HealthResponse

API_TYPES = Path("src/frontend/lib/api.ts")


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


def test_frontend_health_response_type_includes_backend_fields() -> None:
    backend_fields = set(HealthResponse.model_fields)
    frontend_fields = _frontend_type_fields("HealthResponse")

    assert backend_fields <= frontend_fields
