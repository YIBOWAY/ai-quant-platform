from pathlib import Path

API_TYPES = Path("src/frontend/lib/api.ts")


def test_frontend_catalog_types_match_backend_response_names() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for type_name in [
        "StrategyCatalogResponse",
        "UniverseCatalogResponse",
        "FactorCatalogResponse",
    ]:
        assert f"export type {type_name}" in api_types

    assert "export type StrategiesResponse = StrategyCatalogResponse;" in api_types
    assert "export type UniversesResponse = UniverseCatalogResponse;" in api_types
    assert "export type FactorsResponse = FactorCatalogResponse;" in api_types
    assert "apiGet<StrategyCatalogResponse>" in api_types
    assert "apiGet<UniverseCatalogResponse>" in api_types
    assert "apiGet<FactorCatalogResponse>" in api_types
