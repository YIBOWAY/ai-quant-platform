"""Artificial SEC records: these tests contain no market or alpha observations."""

from copy import deepcopy

import pytest

from quant_system.research.sec_pit import as_of, normalize_snapshot


def inputs():
    facts = {"cik": 320193, "facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"end": "2024-09-30", "val": 100, "accn": "0000320193-24-000001",
         "filed": "2024-10-01", "form": "10-K", "fy": 2025, "fp": "FY"},
        {"end": "2024-09-30", "val": 80, "accn": "0000320193-24-000002",
         "filed": "2024-10-10", "form": "10-K/A", "fy": 2025, "fp": "FY"},
    ]}}}}}
    submissions = {"cik": "0000320193", "tickers": ["AAPL"], "filings": {"recent": {
        "accessionNumber": ["0000320193-24-000001", "0000320193-24-000002"],
        "acceptanceDateTime": ["2024-10-01T21:05:00Z", "2024-10-10T20:10:00Z"],
        "filingDate": ["2024-10-01", "2024-10-10"], "form": ["10-K", "10-K/A"],
    }, "files": [{"name": "CIK0000320193-submissions-001.json"}]}}
    return facts, submissions


def snapshot(facts=None, submissions=None):
    a, b = inputs()
    return normalize_snapshot(facts or a, submissions or b,
                              fetched_at="2024-11-01T00:00:00Z")


def test_restatement_does_not_rewrite_earlier_asof_and_fiscal_year_is_not_knowledge_time():
    doc = snapshot()
    assert len(doc["records"]) == 2
    assert as_of(doc, "2024-10-01T21:04:59Z")["selected"] == []
    old = as_of(doc, "2024-10-01T21:05:00Z")["selected"]
    assert old[0]["val"] == 100 and old[0]["fy"] == 2025
    assert as_of(doc, "2024-10-10T20:10:00Z")["selected"][0]["val"] == 80
    assert doc["historical_security_mapping_verified"] is False
    assert doc["historical_coverage_complete"] is False


def test_no_filed_date_fallback_when_accession_has_no_acceptance():
    facts, subs = inputs()
    subs["filings"]["recent"]["acceptanceDateTime"][1] = ""
    doc = snapshot(facts, subs)
    assert doc["records"][1]["status"] == "unavailable"
    assert "acceptance_time_missing" in doc["records"][1]["issues"]
    assert as_of(doc, "2024-10-11T00:00:00Z")["unavailable_count"] == 1


def test_conflicting_latest_accession_blocks_silent_old_version_fallback():
    facts, subs = inputs()
    rows = facts["facts"]["us-gaap"]["Assets"]["units"]["USD"]
    rows.append({**rows[1], "val": 81})
    result = as_of(snapshot(facts, subs), "2024-10-11T00:00:00Z")
    assert result["selected"] == []
    assert result["blocked"][0]["reason"] == "latest_version_invalid"
    assert len(result["blocked"][0]["record_ids"]) == 2


@pytest.mark.parametrize("field,value,reason", [
    ("val", float("nan"), "value_invalid"), ("val", True, "value_invalid"),
    ("end", "2024-11-03", "period_after_filing"),
    ("end", "2024-02-30", "period_invalid"),
    ("start", "2024-09-01", "instant_has_start"),
    ("form", "8-K", "form_not_supported"),
])
def test_bad_fact_never_selected(field, value, reason):
    facts, subs = inputs()
    facts["facts"]["us-gaap"]["Assets"]["units"]["USD"][0][field] = value
    doc = snapshot(facts, subs)
    assert reason in doc["records"][0]["issues"]
    assert as_of(doc, "2024-10-02T00:00:00Z")["selected"] == []


def test_wrong_unit_is_retained_but_not_selected():
    facts, subs = inputs()
    units = facts["facts"]["us-gaap"]["Assets"]["units"]
    units["EUR"] = units.pop("USD")
    doc = snapshot(facts, subs)
    assert doc["records"][0]["unit"] == "EUR"
    assert as_of(doc, "2024-10-11T00:00:00Z")["selected"] == []


def test_duration_requires_actual_start_no_quarter_from_fp_guess():
    facts, subs = inputs()
    concepts = facts["facts"]["us-gaap"]
    concepts["NetIncomeLoss"] = concepts.pop("Assets")
    doc = snapshot(facts, subs)
    assert "duration_start_missing" in doc["records"][0]["issues"]


@pytest.mark.parametrize("change", ["cik", "unequal_columns", "naive_acceptance"])
def test_invalid_submission_identity_and_timing(change):
    facts, subs = inputs()
    if change == "cik":
        subs["cik"] = "1045810"
    elif change == "unequal_columns":
        subs["filings"]["recent"]["form"].pop()
    else:
        subs["filings"]["recent"]["acceptanceDateTime"][0] = "2024-10-01T21:05:00"
    if change == "naive_acceptance":
        doc = snapshot(facts, subs)
        assert "acceptance_time_invalid" in doc["records"][0]["issues"]
    else:
        with pytest.raises(ValueError):
            snapshot(facts, subs)


@pytest.mark.parametrize("cutoff", ["2024-10-01", "2024-12-01T00:00:00Z"])
def test_asof_must_be_aware_and_not_beyond_observed_snapshot(cutoff):
    with pytest.raises(ValueError):
        as_of(snapshot(), cutoff)


def test_input_never_mutated():
    facts, subs = inputs()
    original = deepcopy((facts, subs))
    snapshot(facts, subs)
    assert (facts, subs) == original


def test_acceptance_before_reported_period_is_rejected():
    facts, subs = inputs()
    subs["filings"]["recent"]["acceptanceDateTime"][0] = "2024-08-01T12:00:00Z"
    doc = snapshot(facts, subs)
    assert "acceptance_before_period_end" in doc["records"][0]["issues"]
    assert as_of(doc, "2024-10-02T00:00:00Z")["selected"] == []


def test_unknown_acceptance_revision_cannot_silently_fall_back_to_old_value():
    facts, subs = inputs()
    subs["filings"]["recent"]["acceptanceDateTime"][1] = ""
    result = as_of(snapshot(facts, subs), "2024-10-11T00:00:00Z")
    assert result["selected"] == []
    assert result["blocked"][0]["reason"] == "unknown_acceptance_version"


def test_additional_historical_submissions_are_bound_to_declared_file():
    facts, subs = inputs()
    history = deepcopy(subs["filings"]["recent"])
    for key in subs["filings"]["recent"]:
        subs["filings"]["recent"][key] = []
    additions = [{"name": "CIK0000320193-submissions-001.json", "data": history}]
    doc = normalize_snapshot(facts, subs, fetched_at="2024-11-01T00:00:00Z",
                             submission_history=additions)
    assert doc["issues"] == {} and doc["unfetched_submission_files"] == []
    assert as_of(doc, "2024-10-02T00:00:00Z")["selected"][0]["val"] == 100
    additions[0]["name"] = "CIK0001045810-submissions-001.json"
    with pytest.raises(ValueError, match="history_file_not_declared"):
        normalize_snapshot(facts, subs, fetched_at="2024-11-01T00:00:00Z",
                           submission_history=additions)


def test_conflicting_accession_across_current_and_history_is_rejected():
    facts, subs = inputs()
    history = deepcopy(subs["filings"]["recent"])
    history["acceptanceDateTime"][0] = "2024-10-01T19:00:00Z"
    with pytest.raises(ValueError, match="submissions_accession_conflict"):
        normalize_snapshot(facts, subs, fetched_at="2024-11-01T00:00:00Z",
                           submission_history=[{
                               "name": "CIK0000320193-submissions-001.json", "data": history}])
