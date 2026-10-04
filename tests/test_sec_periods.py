"""Artificial annual SEC period and availability counterexamples."""

from copy import deepcopy

import pytest

from quant_system.research.sec_pit import normalize_snapshot


def documents(*, start="2023-01-01", end="2023-12-31", report_date=None):
    filing = {
        "accessionNumber": "0000000001-24-000001",
        "acceptanceDateTime": "2024-02-01T21:00:00Z",
        "filingDate": "2024-02-01",
        "form": "10-K",
        "reportDate": report_date or end,
    }
    fact = {
        "start": start,
        "end": end,
        "val": 100,
        "accn": filing["accessionNumber"],
        "filed": filing["filingDate"],
        "form": "10-K",
        "fy": 2099,
        "fp": "Q1",
    }
    instant = {**fact, "val": 500}
    instant.pop("start")
    facts = {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "GrossProfit": {"units": {"USD": [fact]}},
                "Assets": {"units": {"USD": [instant]}},
                "Revenues": {"units": {"USD": [{**fact, "val": 1000}]}},
            }
        },
    }
    submissions = {
        "cik": "0000000001",
        "filings": {"recent": {key: [value] for key, value in filing.items()}, "files": []},
    }
    return facts, submissions


def add_version(
    facts,
    submissions,
    *,
    accn="0000000001-24-000002",
    accepted="2024-03-01T21:00:00Z",
    form="10-K/A",
    report="2023-12-31",
    end=None,
    start=None,
    value=120,
):
    row = deepcopy(facts["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"][0])
    row.update(accn=accn, filed=accepted[:10], form=form, val=value)
    if start is not None:
        row["start"] = start
    if end is not None:
        row["end"] = end
    facts["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"].append(row)
    filing = dict(
        accessionNumber=accn,
        acceptanceDateTime=accepted,
        filingDate=accepted[:10],
        form=form,
        reportDate=report,
    )
    for key, val in filing.items():
        submissions["filings"]["recent"][key].append(val)


def query(facts, submissions, cutoff="2024-02-03T00:00:00Z", **changes):
    from quant_system.research.sec_periods import annual_as_of

    snapshot = normalize_snapshot(facts, submissions, fetched_at="2026-01-01T00:00:00Z")
    kwargs = dict(
        cutoff=cutoff,
        disclosure_delay_seconds=86400,
        max_period_age_days=450,
        annual_day_counts=(364, 365, 366, 371),
        submission_history=(),
    )
    kwargs.update(changes)
    return annual_as_of(snapshot, submissions, **kwargs)


@pytest.mark.parametrize(
    "start,end,days",
    [
        ("2023-01-01", "2023-12-31", 365),
        ("2024-01-01", "2024-12-31", 366),
        ("2022-09-25", "2023-09-30", 371),
        ("2023-01-02", "2023-12-31", 364),
    ],
)
def test_annual_period_uses_actual_inclusive_dates_not_fy_fp(start, end, days):
    facts, submissions = documents(start=start, end=end)
    if end.startswith("2024"):
        submissions["filings"]["recent"]["filingDate"][0] = "2025-02-01"
        submissions["filings"]["recent"]["acceptanceDateTime"][0] = "2025-02-01T21:00:00Z"
        for concept in facts["facts"]["us-gaap"].values():
            concept["units"]["USD"][0]["filed"] = "2025-02-01"
    result = query(facts, submissions, cutoff="2025-02-03T00:00:00Z", max_period_age_days=1000)
    assert result["annual_period_end"] == end
    assert result["concepts"]["GrossProfit"]["selected"]["duration_days"] == days
    assert result["concepts"]["GrossProfit"]["selected"]["start"] == start
    assert result["concepts"]["Assets"]["selected"]["end"] == end
    assert result["pit_backtest_ready"] is False


def test_original_annual_anchor_cannot_come_from_future_10k():
    facts, submissions = documents()
    result = query(facts, submissions, cutoff="2024-02-02T20:59:59Z")
    assert result["annual_period_end"] is None
    assert result["status"] == "unavailable"
    exact = query(facts, submissions, cutoff="2024-02-02T21:00:00Z")
    assert exact["concepts"]["GrossProfit"]["selected"]["val"] == 100


def test_later_amendment_changes_only_later_views_and_keeps_originals():
    facts, submissions = documents()
    add_version(facts, submissions)
    original = deepcopy((facts, submissions))
    old = query(facts, submissions, cutoff="2024-03-02T20:59:59Z")
    new = query(facts, submissions, cutoff="2024-03-02T21:00:00Z")
    assert old["concepts"]["GrossProfit"]["selected"]["val"] == 100
    assert new["concepts"]["GrossProfit"]["selected"]["val"] == 120
    assert (facts, submissions) == original


def test_comparative_previous_year_does_not_fill_current_year_under_new_fy_label():
    facts, submissions = documents()
    add_version(
        facts,
        submissions,
        accn="0000000001-25-000002",
        accepted="2025-02-01T21:00:00Z",
        form="10-K",
        report="2024-12-31",
    )
    result = query(facts, submissions, cutoff="2025-02-03T00:00:00Z")
    assert result["annual_period_end"] == "2024-12-31"
    assert result["concepts"]["GrossProfit"]["selected"] is None
    assert result["concepts"]["Assets"]["selected"] is None


def test_comparative_quarterly_filing_can_update_exact_anchored_annual_period():
    facts, submissions = documents()
    add_version(
        facts, submissions, form="10-Q", report="2024-03-31", accepted="2024-05-01T21:00:00Z"
    )
    result = query(facts, submissions, cutoff="2024-05-03T00:00:00Z")
    assert result["annual_period_end"] == "2023-12-31"
    assert result["concepts"]["GrossProfit"]["selected"]["val"] == 120


@pytest.mark.parametrize("report", ["2023-12-30", "bad"])
def test_wrong_or_missing_report_date_cannot_select_unmatched_facts(report):
    facts, submissions = documents(report_date=report)
    assert query(facts, submissions)["concepts"]["GrossProfit"]["selected"] is None


def test_amendment_alone_does_not_create_missing_original_anchor():
    facts, submissions = documents()
    submissions["filings"]["recent"]["form"][0] = "10-K/A"
    for obj in facts["facts"]["us-gaap"].values():
        obj["units"]["USD"][0]["form"] = "10-K/A"
    assert query(facts, submissions)["annual_period_end"] is None


def test_same_end_with_two_original_annual_starts_is_not_silently_chosen():
    facts, submissions = documents()
    more = deepcopy(facts["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"][0])
    more["start"] = "2023-01-02"
    facts["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"].append(more)
    result = query(facts, submissions)
    assert result["concepts"]["GrossProfit"]["reason"] == "annual_start_conflict"


def test_stale_boundary_and_old_revenue_tag_are_explicit_without_zero_or_alias():
    facts, submissions = documents()
    assert query(facts, submissions, cutoff="2024-02-03T00:00:00Z", max_period_age_days=34)[
        "concepts"
    ]["GrossProfit"]["selected"]
    assert (
        query(facts, submissions, cutoff="2024-02-04T00:00:00Z", max_period_age_days=34)[
            "concepts"
        ]["GrossProfit"]["reason"]
        == "annual_period_stale"
    )
    facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0].update(
        start="2010-01-01", end="2010-12-31"
    )
    result = query(facts, submissions)["concepts"]["Revenues"]
    assert result["selected"] is None
    assert result["last_observed_period_end"] == "2010-12-31"
    assert result["reason"] == "concept_tag_stale_for_annual_period"


def test_invalid_latest_version_blocks_instead_of_falling_back():
    facts, submissions = documents()
    add_version(facts, submissions, value="invalid")
    result = query(facts, submissions, cutoff="2024-03-03T00:00:00Z")
    assert result["concepts"]["GrossProfit"]["selected"] is None
    assert result["concepts"]["GrossProfit"]["reason"] == "latest_version_invalid"


@pytest.mark.parametrize(
    "changes",
    [
        {"disclosure_delay_seconds": -1},
        {"max_period_age_days": True},
        {"annual_day_counts": ()},
        {"cutoff": "2024-03-03"},
    ],
)
def test_required_query_parameters_are_validated(changes):
    with pytest.raises(ValueError):
        query(*documents(), **changes)


def test_wrong_issuer_or_acceptance_metadata_is_rejected():
    facts, submissions = documents()
    from quant_system.research.sec_periods import annual_as_of

    snapshot = normalize_snapshot(facts, submissions, fetched_at="2026-01-01T00:00:00Z")
    submissions["cik"] = "0000000002"
    with pytest.raises(ValueError, match="cik"):
        annual_as_of(
            snapshot,
            submissions,
            cutoff="2024-03-01T00:00:00Z",
            disclosure_delay_seconds=86400,
            max_period_age_days=450,
            annual_day_counts=(364, 365, 366, 371),
            submission_history=(),
        )


def test_instant_at_a_quarter_end_is_not_an_annual_period_balance():
    facts, submissions = documents()
    facts["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["end"] = "2023-09-30"
    result = query(facts, submissions)
    assert result["concepts"]["GrossProfit"]["selected"]
    assert result["concepts"]["Assets"]["selected"] is None


def test_old_invalid_period_metadata_is_reported_without_crashing_current_view():
    facts, submissions = documents()
    facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["end"] = "invalid"
    result = query(facts, submissions)
    assert result["concepts"]["Revenues"]["selected"] is None
    assert result["concepts"]["GrossProfit"]["selected"]


@pytest.mark.parametrize("acceptance", ["", "not-a-time", None])
def test_newer_annual_filing_with_unknown_acceptance_cannot_fall_back(acceptance):
    facts, submissions = documents()
    add_version(facts, submissions, accn="0000000001-25-000002",
                accepted="2025-02-01T21:00:00Z", form="10-K", report="2024-12-31",
                start="2024-01-01", end="2024-12-31", value=200)
    submissions["filings"]["recent"]["acceptanceDateTime"][-1] = acceptance
    result = query(facts, submissions, cutoff="2025-02-03T00:00:00Z")
    assert result["annual_period_end"] is None
    assert result["concepts"]["GrossProfit"]["selected"] is None
    assert result["concepts"]["GrossProfit"]["reason"] == "latest_annual_acceptance_unknown"


@pytest.mark.parametrize("form", ["10-K", "10-K/A"])
def test_known_future_unknown_acceptance_does_not_contaminate_older_view(form):
    facts, submissions = documents()
    add_version(facts, submissions, accepted="2024-03-01T21:00:00Z", form=form)
    submissions["filings"]["recent"]["acceptanceDateTime"][-1] = ""
    originals = deepcopy((facts, submissions))
    result = query(facts, submissions, cutoff="2024-02-03T00:00:00Z")
    assert result["annual_period_end"] == "2023-12-31"
    assert result["concepts"]["GrossProfit"]["selected"]["val"] == 100
    assert (facts, submissions) == originals


def test_older_year_unknown_annual_anchor_does_not_hide_current_year():
    facts, submissions = documents()
    add_version(facts, submissions, accepted="2024-02-02T21:00:00Z", form="10-K",
                report="2022-12-31", start="2022-01-01", end="2022-12-31")
    submissions["filings"]["recent"]["acceptanceDateTime"][-1] = ""
    result = query(facts, submissions)
    assert result["annual_period_end"] == "2023-12-31"
    assert result["concepts"]["GrossProfit"]["selected"]["val"] == 100


def test_unknown_acceptance_same_current_year_blocks_without_guessing_public_time():
    facts, submissions = documents()
    add_version(facts, submissions, accepted="2024-02-03T21:00:00Z", form="10-K")
    submissions["filings"]["recent"]["acceptanceDateTime"][-1] = ""
    result = query(facts, submissions, cutoff="2024-02-03T00:00:00Z")
    assert result["annual_period_end"] is None
    assert result["concepts"]["Assets"]["reason"] == "latest_annual_acceptance_unknown"
