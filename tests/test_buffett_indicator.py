"""Real FRED observations retrieved 2026-09-05, kept outside production data."""

from datetime import date

import pytest

from quant_system.data.market_valuation import fetch_buffett_indicator

# Source series: BOGZ1LM883164115Q (USD millions), GDP (USD billions, nominal SAAR).
CAP = """observation_date,BOGZ1LM883164115Q
2020-01-01,30576726
2020-04-01,37269030
2020-07-01,40764484
2020-10-01,47014703
2021-01-01,50311443
2021-04-01,54829467
2021-07-01,54865558
2021-10-01,59448087
2022-01-01,56166961
2022-04-01,46675199
2022-07-01,44409981
2022-10-01,46982196
2023-01-01,49927558
2023-04-01,53641838
2023-07-01,51662304
2023-10-01,57440881
2024-01-01,62742474
2024-04-01,64639788
2024-07-01,68755405
2024-10-01,70647887
2025-01-01,67587295
2025-04-01,74732978
2025-07-01,80885076
2025-10-01,83150083
2026-01-01,79673843
"""
GDP = """observation_date,GDP
2020-01-01,21751.238
2020-04-01,19958.291
2020-07-01,21704.437
2020-10-01,22087.160
2021-01-01,22680.693
2021-04-01,23425.910
2021-07-01,23982.379
2021-10-01,24813.600
2022-01-01,25250.347
2022-04-01,25861.292
2022-07-01,26336.304
2022-10-01,26770.514
2023-01-01,27216.445
2023-04-01,27530.055
2023-07-01,28074.846
2023-10-01,28424.722
2024-01-01,28708.161
2024-04-01,29147.044
2024-07-01,29511.664
2024-10-01,29825.182
2025-01-01,30042.113
2025-04-01,30485.729
2025-07-01,31098.027
2025-10-01,31422.526
2026-01-01,31865.721
2026-04-01,32486.066
"""
RELEASE = "<p>Release Date: June 11, 2026 2026:Q1 Release</p>"


def _source(url, *, release=RELEASE):
    if "id=BOGZ1LM883164115Q" in url:
        return CAP
    if "id=GDP" in url:
        return GDP
    return release


def test_buffett_uses_matching_quarter_nominal_units_and_prior_observations():
    result = fetch_buffett_indicator(as_of=date(2026, 9, 5), download=_source)
    assert result["error"] is None
    assert result["period"] == "2026Q1"
    assert result["source_date"] == "2026-03-31"
    assert result["release_date"] == "2026-06-11"
    assert result["gdp"] == 31865.721  # Q2 GDP exists but has no matching market cap.
    assert result["market_cap"] == 79673843
    assert result["value"] == pytest.approx(79673843 / (31865.721 * 1000) * 100, abs=0.0001)
    assert result["samples"] == 24
    assert result["score"] == 91.67  # Only two prior quarters exceed this observation.
    history = result["history_reference"]
    assert (history["samples"], history["frequency"]) == (24, "quarter")
    assert (history["start_date"], history["end_date"]) == ("2020-03-31", "2025-12-31")
    prior_values = sorted(
        float(cap.split(",")[1]) / (float(gdp.split(",")[1]) * 1000) * 100
        for cap, gdp in zip(CAP.splitlines()[1:-1], GDP.splitlines()[1:-2], strict=True)
    )
    assert history["median"] == pytest.approx((prior_values[11] + prior_values[12]) / 2, abs=0.0001)
    assert history["minimum"] == pytest.approx(prior_values[0], abs=0.0001)
    assert history["maximum"] == pytest.approx(prior_values[-1], abs=0.0001)


@pytest.mark.parametrize(
    ("release", "as_of", "error"),
    [
        ("<p>No release date</p>", date(2026, 9, 5), "buffett_release_date_missing"),
        (RELEASE, date(2026, 6, 10), "buffett_release_after_asof"),
        (
            RELEASE.replace("2026:Q1", "2026:Q2"),
            date(2026, 9, 5),
            "buffett_release_period_mismatch",
        ),
    ],
)
def test_buffett_does_not_invent_publication_date_or_mix_release_periods(release, as_of, error):
    result = fetch_buffett_indicator(
        as_of=as_of, download=lambda url: _source(url, release=release)
    )
    assert result["value"] is None and result["score"] is None
    assert error in result["error"]
