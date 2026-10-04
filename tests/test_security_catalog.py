from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import Settings
from quant_system.data.security_catalog import CATALOG_VERSION, parse_catalog_csv, search_catalog

FIXTURE = Path(__file__).parent / "fixtures/financedatabase-us-subset.json"


def test_public_directory_search_uses_captured_names_and_keeps_listing_identity(tmp_path):
    settings = Settings()
    settings.data.data_dir = tmp_path
    (tmp_path / "security_catalog.json").write_text(FIXTURE.read_text())
    result = search_catalog(settings, "Microsoft")
    assert result["version"] == CATALOG_VERSION
    assert result["items"][0]["symbol"] == "MSFT"
    assert result["items"][0]["sector"] == "Information Technology"
    ashr = search_catalog(settings, "ASHR")["items"][0]
    assert ashr["isin"] == "US2330518794"
    assert ashr["asset_type"] == "etf"
    assert not any(key in ashr for key in ("price", "pe", "pb", "market_cap"))
    assert search_catalog(settings, "unknown_security_query")["items"] == []


def test_catalog_api_without_import_is_unavailable_not_sample(tmp_path):
    settings = Settings()
    settings.data.data_dir = tmp_path
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))
    response = client.get("/api/securities/search?query=Microsoft")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "security_catalog_unavailable"
    (tmp_path / "security_catalog.json").write_text(FIXTURE.read_text())
    assert (
        client.get("/api/securities/search?query=Microsoft").json()["items"][0]["symbol"] == "MSFT"
    )


def test_indicative_value_symbols_are_not_sent_to_quote_provider():
    # These are actual indicative-value identifiers from the pinned ASE ETF CSV.
    data = (
        "symbol,name,currency,exchange,isin\n"
        "^ADFI-IV,Active fixed income indicative value,USD,ASE,\n"
        "^ARB-IV,Arbitrage indicative value,USD,ASE,\n"
    )
    assert parse_catalog_csv(data, asset_type="etf", exchange="ASE") == []
