from datetime import date

from quant_system.data.market_valuation import fetch_asia_valuations


def test_ashr_missing_valuation_identifies_us_issuer_and_actual_search_date():
    result = fetch_asia_valuations(("ASHR",), as_of=date(2026, 9, 5))["ASHR"]
    assert result["source_url"] == (
        "https://etf.dws.com/en-us/ASHR-harvest-csi-300-china-a-shares-etf/"
    )
    assert result["searched_date"] == "2026-09-05"
    assert "issuer_valuation_unavailable" in result["error"]
    assert "PE/PB" in result["error"] and "UCITS" in result["error"]
    assert "pe" not in result and "pb" not in result and "source_date" not in result
