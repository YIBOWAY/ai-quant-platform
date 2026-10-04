"""Offline SEC filing versions and as-of views; no security mapping or trading authority.

The original JSON remains authoritative. This narrow US-GAAP/USD study keeps
all selected-concept observations, including rejected and unmatched versions.
Historical acceptance timestamps are reconstructed from today's submissions
snapshot; they are not proof of an observed historical API vintage.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime

CONCEPTS = {
    "Assets": "instant",
    "Liabilities": "instant",
    "AssetsCurrent": "instant",
    "LiabilitiesCurrent": "instant",
    "NetIncomeLoss": "duration",
    "NetCashProvidedByUsedInOperatingActivities": "duration",
    "GrossProfit": "duration",
    "Revenues": "duration",
}
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
SCHEMA = "sec_pit_research_snapshot/v2"


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp_invalid")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp_timezone_required")
    return result.astimezone(UTC)


def _day(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date_invalid")
    return date.fromisoformat(value)


def _cik(value) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"\d{1,10}", str(value)):
        raise ValueError("cik_invalid")
    result = int(value)
    if result <= 0:
        raise ValueError("cik_invalid")
    return result


def _submissions(document: dict) -> dict:
    recent = document["filings"]["recent"]
    columns = ("accessionNumber", "acceptanceDateTime", "filingDate", "form")
    if any(not isinstance(recent.get(key), list) for key in columns):
        raise ValueError("submissions_columns_invalid")
    if len({len(recent[key]) for key in columns}) != 1:
        raise ValueError("submissions_columns_length_mismatch")
    result = {}
    for values in zip(*(recent[key] for key in columns), strict=True):
        row = dict(zip(columns, values, strict=True))
        accession = row["accessionNumber"]
        if not isinstance(accession, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            raise ValueError("submissions_accession_invalid")
        if accession in result and result[accession] != row:
            raise ValueError("submissions_accession_conflict")
        result[accession] = row
    return result


def _period_key(row: dict) -> tuple:
    return tuple(row.get(key) for key in ("cik", "taxonomy", "tag", "unit", "start", "end"))


def normalize_snapshot(
    companyfacts: dict, submissions: dict, *, fetched_at: str,
    submission_history: tuple | list = (),
) -> dict:
    """Preserve facts and rejection reasons; never guess tags or disclosure times."""
    observed = _timestamp(fetched_at)
    cik = _cik(companyfacts["cik"])
    if cik != _cik(submissions["cik"]):
        raise ValueError("snapshot_cik_mismatch")
    filings = _submissions(submissions)
    declared_history = {item["name"]: item for item in submissions["filings"].get("files", [])}
    used_history = set()
    for batch in submission_history:
        name = batch["name"]
        if name not in declared_history or name in used_history:
            raise ValueError("history_file_not_declared")
        if not re.fullmatch(rf"CIK{cik:010d}-submissions-\d+\.json", name):
            raise ValueError("history_file_identity_invalid")
        for accession, row in _submissions({"filings": {"recent": batch["data"]}}).items():
            if accession in filings and filings[accession] != row:
                raise ValueError("submissions_accession_conflict")
            filings[accession] = row
        used_history.add(name)
    concepts = companyfacts.get("facts", {}).get("us-gaap", {})
    records = []
    for tag, period_type in CONCEPTS.items():
        for unit, observations in concepts.get(tag, {}).get("units", {}).items():
            if not isinstance(observations, list):
                raise ValueError("concept_units_invalid")
            for index, original in enumerate(observations):
                if not isinstance(original, dict):
                    raise ValueError("fact_invalid")
                row = {key: original.get(key) for key in
                       ("start", "end", "val", "accn", "filed", "form", "fy", "fp", "frame")}
                row.update(record_id=f"{tag}/{unit}/{index}", cik=cik, taxonomy="us-gaap",
                           tag=tag, unit=unit, period_type=period_type, accepted_at=None, issues=[])
                issues = row["issues"]
                if unit != "USD":
                    issues.append("unit_not_supported")
                if (isinstance(row["val"], bool) or not isinstance(row["val"], (int, float))
                        or not math.isfinite(row["val"])):
                    issues.append("value_invalid")
                    # JSON output must remain valid; the raw source retains the exact value.
                    row["val"] = None
                if row["form"] not in FORMS:
                    issues.append("form_not_supported")
                try:
                    end, filed = _day(row["end"]), _day(row["filed"])
                    if end > filed:
                        issues.append("period_after_filing")
                    if filed > observed.date():
                        issues.append("filing_after_snapshot")
                    if period_type == "instant" and row["start"] is not None:
                        issues.append("instant_has_start")
                    if period_type == "duration":
                        if row["start"] is None:
                            issues.append("duration_start_missing")
                        elif _day(row["start"]) > end:
                            issues.append("duration_reversed")
                except (ValueError, TypeError):
                    issues.append("period_invalid")
                filing = filings.get(row["accn"])
                if filing is None or not filing["acceptanceDateTime"]:
                    issues.append("acceptance_time_missing")
                else:
                    try:
                        accepted = _timestamp(filing["acceptanceDateTime"])
                        if accepted > observed:
                            issues.append("acceptance_after_snapshot")
                        try:
                            if accepted.date() < _day(row["end"]):
                                issues.append("acceptance_before_period_end")
                        except (ValueError, TypeError):
                            pass  # Already reported as period_invalid above.
                        row["accepted_at"] = accepted.isoformat()
                    except ValueError:
                        issues.append("acceptance_time_invalid")
                    if filing["filingDate"] != row["filed"] or filing["form"] != row["form"]:
                        issues.append("submission_fact_mismatch")
                records.append(row)
    versions = defaultdict(list)
    for row in records:
        versions[(*_period_key(row), row["accn"])].append(row)
    for rows in versions.values():
        if len({row["val"] for row in rows}) > 1:
            for row in rows:
                row["issues"].append("same_accession_period_conflict")
    for row in records:
        row["status"] = "available" if not row["issues"] else "unavailable"
    return {
        "schema": SCHEMA, "cik": cik, "fetched_at": observed.isoformat(),
        "concepts": CONCEPTS.copy(), "records": records,
        "missing_concepts": [tag for tag in CONCEPTS if tag not in concepts],
        "issues": dict(Counter(issue for row in records for issue in row["issues"])),
        "historical_coverage_complete": False,
        "unfetched_submission_files": [item for name, item in declared_history.items()
                                       if name not in used_history],
        "included_submission_files": sorted(used_history),
        "historical_security_mapping_verified": False,
        "historical_api_vintage_observed": False,
        "pit_backtest_ready": False,
    }


def as_of(snapshot: dict, cutoff: str) -> dict:
    """Latest disclosed version for every exact concept/period; no stale fallback.

This does not infer trailing-year totals or which fiscal period a strategy wants.
Missing acceptance times are reported and do not become filed-date estimates.
"""
    if snapshot.get("schema") != SCHEMA:
        raise ValueError("snapshot_schema_invalid")
    at = _timestamp(cutoff)
    if at > _timestamp(snapshot["fetched_at"]):
        raise ValueError("asof_after_snapshot")
    groups = defaultdict(list)
    unresolved = defaultdict(list)
    unknown = []
    for row in snapshot["records"]:
        if row["accepted_at"] is None:
            unknown.append(row["record_id"])
            unresolved[_period_key(row)].append(row)
        elif _timestamp(row["accepted_at"]) <= at:
            groups[_period_key(row)].append(row)
    selected, blocked = [], []
    for key in dict.fromkeys((*groups, *unresolved)):
        rows = groups[key]
        # The original filed date is not a substitute for an acceptance instant.
        # An undated version may supersede the known one; leave that period unknown.
        if unresolved[key]:
            blocked.append({"reason": "unknown_acceptance_version",
                            "record_ids": [row["record_id"] for row in unresolved[key]]})
            continue
        latest = max(_timestamp(row["accepted_at"]) for row in rows)
        versions = [row for row in rows if _timestamp(row["accepted_at"]) == latest]
        if any(row["status"] != "available" for row in versions):
            reason = "latest_version_invalid"
        elif len({(row["accn"], row["val"]) for row in versions}) != 1:
            reason = "simultaneous_version_conflict"
        else:
            selected.append(dict(versions[0]))
            continue
        blocked.append({"reason": reason, "record_ids": [row["record_id"] for row in versions]})
    return {
        "schema": "sec_pit_asof/v2", "cutoff": at.isoformat(), "cik": snapshot["cik"],
        "selected": selected, "blocked": blocked,
        "unavailable_count": len(unknown), "unknown_acceptance_record_ids": unknown,
        "historical_coverage_complete": False, "pit_backtest_ready": False,
    }
