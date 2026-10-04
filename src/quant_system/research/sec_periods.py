"""Offline annual SEC facts with explicit period, availability and expiry rules.

An annual filing's reportDate anchors its period end; duration facts additionally
need an original 10-K start/end observation. fy/fp/frame are retained as original
metadata, never used to infer the fact's year. No ratios, quarterly derivation,
security mapping, market returns or funding authority are provided here.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import timedelta

from quant_system.research.sec_pit import CONCEPTS, SCHEMA, _cik, _day, _timestamp, as_of


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _filing_index(submissions, history):
    """Read the reportDate omitted by the narrow existing SEC version parser."""
    columns = ("accessionNumber", "acceptanceDateTime", "filingDate", "form", "reportDate")
    batches = [submissions["filings"]["recent"]]
    declared = {row["name"] for row in submissions["filings"].get("files", [])}
    seen = set()
    for item in history:
        if item["name"] not in declared or item["name"] in seen:
            raise ValueError("annual_history_file_not_declared")
        seen.add(item["name"])
        batches.append(item["data"])
    index = {}
    for batch in batches:
        if (
            any(not isinstance(batch.get(key), list) for key in columns)
            or len({len(batch[key]) for key in columns}) != 1
        ):
            raise ValueError("annual_submission_columns_invalid")
        for values in zip(*(batch[key] for key in columns), strict=True):
            row = dict(zip(columns, values, strict=True))
            accn = row["accessionNumber"]
            if accn in index and index[accn] != row:
                raise ValueError("annual_submission_accession_conflict")
            index[accn] = row
    return index


def _known_future_filing(filing, cutoff):
    """A future filing date can rule out a row; it cannot supply an exact time."""
    try:
        return _day(filing["filingDate"]) > cutoff.date()
    except (KeyError, TypeError, ValueError):
        return False


def _may_replace_annual(filing, target):
    try:
        return target is None or _day(filing["reportDate"]) >= _day(target)
    except (KeyError, TypeError, ValueError):
        # An invalid end cannot prove that this is only an older annual report.
        return True


def annual_as_of(
    snapshot,
    submissions,
    *,
    submission_history,
    cutoff,
    disclosure_delay_seconds,
    max_period_age_days,
    annual_day_counts,
):
    """Select each exact tag for the latest publicly available original annual end.

    All policy parameters are required. Age is measured from the period end,
    inclusive duration is (end-start).days+1, and availability includes the caller's
    explicit delay. Comparatives/amendments update only exact anchored periods.
    Missing new-year tags do not fall back to older periods or alternative tags.
    """
    if (
        type(disclosure_delay_seconds) is not int
        or disclosure_delay_seconds < 0
        or type(max_period_age_days) is not int
        or max_period_age_days < 0
        or not isinstance(annual_day_counts, (tuple, list))
        or not annual_day_counts
        or any(
            type(value) is not int or value not in {364, 365, 366, 371}
            for value in annual_day_counts
        )
    ):
        raise ValueError("annual_query_policy_invalid")
    if snapshot.get("schema") != SCHEMA:
        raise ValueError("annual_snapshot_schema_invalid")
    if _cik(snapshot["cik"]) != _cik(submissions["cik"]):
        raise ValueError("annual_snapshot_cik_mismatch")
    at = _timestamp(cutoff)
    if at > _timestamp(snapshot["fetched_at"]):
        raise ValueError("asof_after_snapshot")
    try:
        effective = at - timedelta(seconds=disclosure_delay_seconds)
    except OverflowError as exc:
        raise ValueError("annual_query_policy_invalid") from exc
    filings = _filing_index(submissions, submission_history)
    rows = snapshot["records"]
    for row in rows:
        filing = filings.get(row["accn"])
        if row.get("status") == "available" and (
            filing is None
            or filing["form"] != row["form"]
            or filing["filingDate"] != row["filed"]
            or _timestamp(filing["acceptanceDateTime"]) != _timestamp(row["accepted_at"])
        ):
            raise ValueError("annual_record_submission_mismatch")

    annual_filings, invalid_filings, unknown_annual_times = [], [], []
    for filing in filings.values():
        if filing["form"] != "10-K":
            continue
        try:
            accepted = _timestamp(filing["acceptanceDateTime"])
        except (ValueError, TypeError):
            invalid_filings.append(
                {"accn": filing["accessionNumber"], "reason": "annual_acceptance_unknown"}
            )
            if not _known_future_filing(filing, at):
                unknown_annual_times.append(filing)
            continue
        if accepted > effective:
            continue
        try:
            end = _day(filing["reportDate"])
            if end > accepted.date() or end > _day(filing["filingDate"]):
                raise ValueError("future annual end")
        except (ValueError, TypeError):
            invalid_filings.append(
                {
                    "accn": filing["accessionNumber"],
                    "accepted_at": accepted.isoformat(),
                    "reason": "annual_report_date_invalid",
                }
            )
            continue
        annual_filings.append(
            {
                "accn": filing["accessionNumber"],
                "end": end.isoformat(),
                "accepted_at": accepted.isoformat(),
            }
        )
    target = max((row["end"] for row in annual_filings), default=None)
    target_problem = None
    if target is None:
        target_problem = "original_10k_anchor_missing"
    elif any(
        row.get("accepted_at")
        and _timestamp(row["accepted_at"])
        >= max(_timestamp(filing["accepted_at"]) for filing in annual_filings)
        for row in invalid_filings
    ):
        target, target_problem = None, "latest_annual_report_date_invalid"
    if target_problem in {None, "original_10k_anchor_missing"} and any(
        _may_replace_annual(filing, target) for filing in unknown_annual_times
    ):
        target, target_problem = None, "latest_annual_acceptance_unknown"
    anchors = {filing["accn"]: filing for filing in annual_filings}
    duration_starts = defaultdict(set)
    period_proofs = defaultdict(list)
    for row in rows:
        anchor = anchors.get(row["accn"])
        if (
            anchor is None
            or row["status"] != "available"
            or row["period_type"] != "duration"
            or row["end"] != anchor["end"]
            or _timestamp(row["accepted_at"]) > effective
        ):
            continue
        days = (_day(row["end"]) - _day(row["start"])).days + 1
        if days in annual_day_counts:
            duration_starts[row["end"]].add(row["start"])
            period_proofs[row["end"]].append(
                {
                    "record_id": row["record_id"],
                    "accn": row["accn"],
                    "start": row["start"],
                    "end": row["end"],
                    "duration_days": days,
                    "accepted_at": row["accepted_at"],
                }
            )
    # The existing general version reader conservatively blocks any undated
    # version. For an annual historical view, an original declared filingDate
    # after this query rules that version out. It remains in the source snapshot;
    # no filed date is ever converted to a guessed acceptance timestamp.
    query_rows = [
        row for row in rows
        if not (
            row.get("accepted_at") is None
            and row["accn"] in filings
            and filings[row["accn"]]["filingDate"] == row["filed"]
            and _known_future_filing(filings[row["accn"]], at)
        )
    ]
    versions = as_of({**snapshot, "records": query_rows}, effective.isoformat())
    original_by_id = {row["record_id"]: row for row in rows}
    blocked = {}
    for problem in versions["blocked"]:
        for record_id in problem["record_ids"]:
            row = original_by_id[record_id]
            blocked[(row["tag"], row["start"], row["end"])] = problem["reason"]
    concepts = {}
    age = (at.date() - _day(target)).days if target else None
    for tag, period_type in CONCEPTS.items():
        disclosed = [
            row
            for row in rows
            if row["tag"] == tag
            and row.get("accepted_at")
            and _timestamp(row["accepted_at"]) <= effective
        ]
        observed_ends = []
        for row in disclosed:
            try:
                observed_ends.append(_day(row["end"]).isoformat())
            except (ValueError, TypeError):
                continue
        last_end = max(observed_ends, default=None)
        entry = {
            "status": "unavailable",
            "reason": target_problem,
            "selected": None,
            "last_observed_period_end": last_end,
            "last_observed_period_age_days": (at.date() - _day(last_end)).days
            if last_end
            else None,
        }
        starts = duration_starts[target] if target else set()
        if target is None:
            concepts[tag] = entry
            continue
        if age > max_period_age_days:
            entry["reason"] = "annual_period_stale"
        elif period_type == "duration" and len(starts) > 1:
            entry["reason"] = "annual_start_conflict"
        elif period_type == "duration" and not starts:
            entry["reason"] = "annual_duration_anchor_missing"
        else:
            start = next(iter(starts)) if period_type == "duration" else None
            key = (tag, start, target)
            matches = [
                row for row in versions["selected"] if (row["tag"], row["start"], row["end"]) == key
            ]
            if key in blocked:
                entry["reason"] = blocked[key]
            elif len(matches) != 1:
                entry["reason"] = (
                    "concept_tag_stale_for_annual_period"
                    if entry["last_observed_period_age_days"] is not None
                    and entry["last_observed_period_age_days"] > max_period_age_days
                    else "concept_missing_for_annual_period"
                )
            else:
                selected = dict(matches[0])
                selected.update(
                    annual_period_end=target,
                    duration_days=(_day(target) - _day(start)).days + 1 if start else None,
                    available_at=(
                        _timestamp(selected["accepted_at"])
                        + timedelta(seconds=disclosure_delay_seconds)
                    ).isoformat(),
                    period_age_days=age,
                )
                entry.update(status="available", reason=None, selected=selected)
        concepts[tag] = entry
    policy = {
        "disclosure_delay_seconds": disclosure_delay_seconds,
        "max_period_age_days": max_period_age_days,
        "annual_day_counts": sorted(set(annual_day_counts)),
        "day_count": "inclusive",
    }
    return {
        "schema": "sec_annual_facts_asof/v1",
        "cik": snapshot["cik"],
        "cutoff": at.isoformat(),
        "effective_disclosure_cutoff": effective.isoformat(),
        "status": "available"
        if all(row["status"] == "available" for row in concepts.values())
        else "partial"
        if any(row["status"] == "available" for row in concepts.values())
        else "unavailable",
        "annual_period_end": target,
        "period_age_days": age,
        "policy": policy,
        "concepts": concepts,
        "original_annual_filings": annual_filings,
        "annual_duration_proofs": dict(period_proofs),
        "invalid_annual_filings": invalid_filings,
        "input_digest": _digest({"snapshot": snapshot, "filings": filings}),
        "policy_digest": _digest(policy),
        "research_only": True,
        "pit_backtest_ready": False,
        "historical_api_vintage_observed": False,
        "historical_security_mapping_verified": False,
        "quarterly_ytd_ttm": "not_evaluated",
        "ratios_and_market_returns": "not_evaluated",
    }
