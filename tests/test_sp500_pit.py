"""T1.4 S&P 500 PIT membership builder tests.

Two layers:

* unit tests use small synthetic fixtures so the parser/entity rules are pinned
  exactly (F2 column binding, F1 empty-parse guard, A12 interval overlap, A13
  broker-wire rejection, A7 ticker reuse);
* ``test_real_sources_end_to_end`` runs the full pipeline over the read-only
  sources staged in ``artifacts/t14-sp500-membership-2026-09-16/sources`` and
  checks the whole A1..A17 suite. It skips when that directory is absent (the
  artifacts are intentionally not committed).
"""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from quant_system.universes import sp500_pit
from quant_system.universes.sp500_pit import (
    BROKER_NEGATIVE_CASES,
    MIN_WIKIPEDIA_DATED_ROWS,
    MONTH_END_MEMBER_BOUNDS_BY_ERA,
    RENAME_HANDOFF_EVIDENCE,
    AliasRow,
    AliasTable,
    SourceBundle,
    Sp500PitError,
    build_coverage,
    build_sp500_pit,
    canonical_ticker,
    classify_reason,
    detect_renames,
    handoff_renames,
    looks_like_broker_wire,
    month_end_grid,
    parse_fja_snapshots,
    parse_fja_start_end,
    parse_wikipedia_changes,
    same_day_handoff_survey,
    to_futu_wire,
    to_longbridge_wire,
    wiki_name_history,
    write_products,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCES = REPO_ROOT / "artifacts" / "t14-sp500-membership-2026-09-16" / "sources"


# ---------------------------------------------------------------------------
# synthetic fixture helpers
# ---------------------------------------------------------------------------
def wiki_table(rows: list[tuple[str, str, str, str, str, str]]) -> str:
    """Render an ``id="changes"`` wikitable.

    Cells per row: (date, added, added_name, removed, removed_name, reason).
    """

    lines = [
        "Some prose above the table.",
        '{| class="wikitable sortable" id="changes"',
        "|-",
        '! data-sort-type="date" rowspan="2" | Effective Date',
        '! colspan="2" | Added',
        '! colspan="2" | Removed',
        '! rowspan="2" | Reason',
        '! rowspan="2" | Refs',
        "|-",
        "! Ticker || Security || Ticker || Security",
    ]
    for when, added, added_name, removed, removed_name, reason in rows:
        lines.extend(
            [
                "|-",
                f"|| {when}",
                f"|| {added} ",
                f"|| {added_name} ",
                f"|| {removed} ",
                f"|| {removed_name} ",
                f"|| {reason}",
                "|| <ref>{{cite web |url=https://example.test/a.pdf |date=June 1, 2026}}</ref>",
            ]
        )
    lines.append("|}")
    return "\n".join(lines)


CAG_ROW = (
    "June 30, 2026",
    "",
    "",
    "CAG",
    "[[Conagra Brands]]",
    "Market capitalization changes.",
)
SPINOFF_ROW = (
    "June 29, 2026",
    "HONA",
    "[[Honeywell Aerospace]]",
    "",
    "",
    "[[Honeywell]] completed the [[corporate spin-off]] of Honeywell Aerospace.",
)
RENAME_ROW = (
    "June 9, 2022",
    "META",
    "[[Meta Platforms]]",
    "FB",
    "[[Facebook, Inc.|Facebook]]",
    "Facebook changed its ticker symbol from FB to META.",
)
MERGER_RENAME_ROW = (
    "March 2, 2020",
    "IR",
    "[[Ingersoll Rand]]",
    "XEC",
    "[[Cimarex Energy]]",
    "Gardner Denver acquired Ingersoll Rand's industrial businesses then changed "
    "its name to the new Ingersoll Rand.",
)
RECEIVERSHIP_ROW = (
    "March 15, 2023",
    "BG",
    "[[Bunge Global]]",
    "SIVB",
    "[[SVB Financial]]",
    "The FDIC placed SVB's main subsidiary into receivership.",
)


# ---------------------------------------------------------------------------
# parser discipline (F1 / F2 / R-5)
# ---------------------------------------------------------------------------
def test_blank_cell_is_preserved_and_bound_by_index() -> None:
    """F2/R-5: the June 30, 2026 row must read Added='' Removed='CAG'.

    A parser that drops empty cells shifts columns and turns "CAG left the
    index" into "CAG joined the index" — the exact T1.1 R4 bug.
    """

    rows = parse_wikipedia_changes(wiki_table([CAG_ROW, SPINOFF_ROW, RENAME_ROW]), min_rows=1)
    cag = rows[0]
    assert cag.added_ticker == ""
    assert cag.removed_ticker == "CAG"
    assert cag.added_name == ""
    assert cag.removed_name == "Conagra Brands"
    assert cag.reason_text == "Market capitalization changes."
    assert cag.raw_row_index >= 0
    # the row is still counted, and the announcement date comes from the ref
    assert cag.announced_date == "2026-06-01"


def test_parser_refuses_empty_or_short_parse() -> None:
    """F1/A15: an empty or partial parse raises instead of returning a table."""

    with pytest.raises(Sp500PitError, match="no wikitable"):
        parse_wikipedia_changes("== History ==\nThe index has 500 companies.\n")
    with pytest.raises(Sp500PitError, match="silent-partial-parse"):
        parse_wikipedia_changes(wiki_table([CAG_ROW]), min_rows=MIN_WIKIPEDIA_DATED_ROWS)


def test_reason_classification_separates_pure_renames_from_merger_renames() -> None:
    assert classify_reason("Ceridian changed its ticker symbol from CDAY to DAY.") == "rename"
    assert classify_reason("FLEETCOR Technologies changed its name to Corpay.") == "rename"
    assert classify_reason("Old Kraft Foods was renamed Mondelez.") == "rename"
    assert classify_reason(MERGER_RENAME_ROW[5]) == "acquisition"
    assert classify_reason(RECEIVERSHIP_ROW[5]) == "bankruptcy-receivership"
    assert classify_reason("Market capitalization changes.") == "market-capitalization"
    assert classify_reason("") == "blank"
    assert (
        classify_reason("Dupont completed the corporate spin-off of Qnity Electronics.")
        == "spinoff"
    )


def test_rename_detection_and_handoff_survey() -> None:
    rows = parse_wikipedia_changes(
        wiki_table([CAG_ROW, SPINOFF_ROW, RENAME_ROW, MERGER_RENAME_ROW, RECEIVERSHIP_ROW]),
        min_rows=1,
    )
    segments = parse_fja_start_end(
        "ticker,start_date,end_date\nFB,2013-12-23,2022-06-09\nMETA,2022-06-09,\nXEC,2010-01-01,2020-03-02\nIR,2020-03-02,\n"
    )
    renames = detect_renames(rows, segments)
    assert [(r.old_ticker, r.new_ticker) for r in renames] == [("FB", "META")]
    assert renames[0].date_confidence == "confirmed-both-sources"
    # the merger-driven ticker change must NOT be treated as a rename (F7 guard)
    assert ("XEC", "IR") not in {(r.old_ticker, r.new_ticker) for r in renames}


def test_handoff_renames_only_uses_the_evidenced_groups() -> None:
    """Guard against generalising "same-day handoff == rename" to all 1123 pairs."""

    segments = parse_fja_start_end(
        "ticker,start_date,end_date\n"
        "WLTW,2016-01-05,2022-01-10\nWTW,2022-01-10,\n"
        "FB,2013-12-23,2022-06-09\nMETA,2022-06-09,\n"
        "ANTM,2002-07-25,2022-06-28\nELV,2022-06-28,\n"
        "NLOK,2019-11-05,2022-11-08\nGEN,2022-11-08,\n"
        "CDAY,2021-09-20,2024-02-01\nDAY,2024-02-01,2026-02-09\n"
        "FLT,2018-06-20,2024-03-25\nCPAY,2024-03-25,\n"
    )
    extra, gaps = handoff_renames([], segments)
    assert {f"{r.old_ticker}->{r.new_ticker}" for r in extra} == {
        "WLTW->WTW",
        "FB->META",
        "ANTM->ELV",
        "NLOK->GEN",
        "CDAY->DAY",
        "FLT->CPAY",
    }
    assert gaps == []
    survey = same_day_handoff_survey(segments)
    assert survey["same_day_handoff_pairs"] == 6
    assert survey["evidenced_renames"] == 6
    assert survey["unverifiable_pairs"] == 0
    assert len(RENAME_HANDOFF_EVIDENCE) == 6


def test_handoff_rename_reports_a_missing_segment_instead_of_guessing() -> None:
    segments = parse_fja_start_end("ticker,start_date,end_date\nMETA,2022-06-09,\n")
    extra, gaps = handoff_renames([], segments)
    assert extra == []
    assert {g["kind"] for g in gaps} == {"rename-handoff-missing"}


# ---------------------------------------------------------------------------
# alias table (A12 / A13 / R-6)
# ---------------------------------------------------------------------------
def _alias(ticker: str, start: str, end: str | None, entity: str, **kw: object) -> AliasRow:
    return AliasRow(
        ticker=ticker,
        valid_from=start,
        valid_to=end,
        entity_id=entity,
        is_alias=bool(kw.get("is_alias", False)),
        alias_of=kw.get("alias_of"),  # type: ignore[arg-type]
        rename_event_ref=kw.get("rename_event_ref"),  # type: ignore[arg-type]
        source=str(kw.get("source", "test")),
    )


def test_alias_resolution_is_interval_bound() -> None:
    table = AliasTable(
        [
            _alias("Q", "2000-07-06", "2011-04-01", "E:X:qwest"),
            _alias("Q", "2025-11-03", None, "E:CIK0002058873"),
            _alias("AAPL", "1982-11-30", None, "E:CIK0000320193"),
        ]
    )
    assert table.resolve("Q", "2010-01-01") == "E:X:qwest"
    assert table.resolve("Q", "2011-04-01") is None  # valid_to is exclusive
    assert table.resolve("Q", "2026-01-01") == "E:CIK0002058873"
    assert table.resolve("AAPL", "1990-01-01") == "E:CIK0000320193"


def test_overlapping_intervals_raise_instead_of_picking_one() -> None:
    """A12: an overlap is a data defect and must never resolve silently."""

    with pytest.raises(Sp500PitError, match="alias interval overlap"):
        AliasTable(
            [
                _alias("Q", "2000-07-06", "2011-04-01", "E:X:qwest"),
                _alias("Q", "2010-01-01", None, "E:X:other"),
            ]
        )


def test_broker_wire_codes_are_rejected_as_identity_sources() -> None:
    """A13/R-9: FB-US and ANSS-US resolve to ETFs at the broker, Q to Qnity."""

    table = AliasTable([_alias("META", "2022-06-09", None, "E:CIK0001326801")])
    for wire, _note, _kind in BROKER_NEGATIVE_CASES:
        if looks_like_broker_wire(wire):
            with pytest.raises(Sp500PitError, match="broker wire code"):
                table.resolve(wire, "2026-01-01")
    assert looks_like_broker_wire("US.AAPL") is True
    assert looks_like_broker_wire("AAPL-US") is True
    assert looks_like_broker_wire("Q") is False  # syntactically fine, semantically reused
    # consumption mapping helpers stay available for the data path
    assert to_futu_wire("BRK.B") == "US.BRK.B"
    assert to_longbridge_wire("BRK.B") == "BRK.B.US"


def test_canonical_ticker_normalises_hyphen_and_keeps_q_suffix() -> None:
    assert canonical_ticker("BRK-B") == "BRK.B"
    assert canonical_ticker("AAMRQ") == "AAMRQ"
    assert canonical_ticker("ALOG-201806") == "ALOG-201806"


def test_entity_name_is_taken_per_seat_not_per_ticker() -> None:
    """Q named three entities over time; the name must follow the seat."""

    rows = parse_wikipedia_changes(
        wiki_table(
            [
                (
                    "March 31, 2011",
                    "EW",
                    "[[Edwards Lifesciences]]",
                    "Q",
                    "[[Qwest]]",
                    "Qwest was acquired by CenturyLink.",
                ),
                (
                    "November 3, 2025",
                    "Q",
                    "[[Qnity Electronics]]",
                    "",
                    "",
                    "Dupont completed the corporate spin-off of Qnity Electronics.",
                ),
            ]
        ),
        min_rows=1,
    )
    history = wiki_name_history(rows)
    assert [name for _d, name in history["Q"]] == ["Qwest", "Qnity Electronics"]


def test_month_end_grid_uses_the_last_nyse_session() -> None:
    grid = month_end_grid("2024-01", "2024-03")
    assert grid == ["2024-01-31", "2024-02-29", "2024-03-28"]  # 2024-03-29 is Good Friday
    assert len(month_end_grid("1996-01", "2026-08")) == 368


def test_snapshot_parser_rejects_an_empty_file() -> None:
    with pytest.raises(Sp500PitError):
        parse_fja_snapshots("date,tickers\n")


# ---------------------------------------------------------------------------
# synthetic end-to-end build (pipeline wiring, writers, rename merge)
# ---------------------------------------------------------------------------
SYNTHETIC_SNAPSHOTS = (
    "date,tickers\n"
    '2022-06-09,"FB,CAG,AAPL"\n'
    '2022-06-30,"META,CAG,AAPL"\n'
    '2023-03-15,"META,CAG,AAPL,BG"\n'
    '2026-06-30,"META,AAPL,BG"\n'
)
SYNTHETIC_START_END = (
    "ticker,start_date,end_date\n"
    "FB,2013-12-23,2022-06-09\n"
    "META,2022-06-09,\n"
    "CAG,1996-01-02,2026-06-30\n"
    "AAPL,1982-11-30,\n"
    "SIVB,2018-03-19,2023-03-15\n"
    "BG,2023-03-15,\n"
)
SYNTHETIC_JOEYFIFE = json.dumps(
    {
        "current": ["META", "AAPL", "BG"],
        "changes": [
            {"date": "2022-06-09", "added": "META", "removed": ""},
            {"date": "2026-06-30", "added": "", "removed": "CAG"},
        ],
    }
)
SYNTHETIC_CONSTITUENTS = (
    "Symbol,Security,GICS Sector,GICS Sub-Industry,Headquarters Location,"
    "Date added,CIK,Founded\n"
    "META,Meta Platforms,Communication Services,Interactive Media & Services,"
    "Menlo Park,2013-12-23,1326801,2004\n"
    "AAPL,Apple,Information Technology,Technology Hardware,"
    "Cupertino,1982-11-30,320193,1977\n"
    "BG,Bunge Global,Consumer Staples,Agricultural Products,"
    "Chesterfield,2023-03-15,1144519,1818\n"
)


def synthetic_sources() -> SourceBundle:
    return SourceBundle(
        wikipedia_changes_raw=wiki_table([RENAME_ROW, CAG_ROW, RECEIVERSHIP_ROW]),
        fja_snapshots_csv=SYNTHETIC_SNAPSHOTS,
        fja_start_end_csv=SYNTHETIC_START_END,
        joeyfife_json=SYNTHETIC_JOEYFIFE,
        current_constituents_csv=SYNTHETIC_CONSTITUENTS,
        wikipedia_revision="2026-08-23T16:26:12Z",
    )


def test_synthetic_build_merges_renames_and_keeps_ticker_reuse_separate() -> None:
    result = build_sp500_pit(
        synthetic_sources(),
        built_at="2026-01-01T00:00:00+00:00",
        grid_start="2022-06",
        grid_end="2026-07",
        min_wikipedia_rows=1,
    )
    table = result.alias_table()
    # A11: FB's seat and META's seat are one entity, resolved on both sides of the rename
    assert table.resolve("FB", "2022-06-08") == table.resolve("META", "2022-06-09")
    assert table.resolve("META", "2022-06-09") is not None
    # A12: no overlap, and the two Q-style seats stay separate when they differ
    assert table.resolve("CAG", "2026-06-30") is None  # exclusive end
    assert table.resolve("CAG", "2026-06-29") == table.resolve("CAG", "1996-01-02")
    # A5: the receivership row is attributed, not lumped into acquisitions
    sivb = [e for e in result.events if e.ticker_as_of == "SIVB"]
    assert [e.event_type for e in sivb] == ["bankruptcy-receivership"]
    assert sivb[0].reason_class == "bankruptcy-receivership"
    # blank ticker cells survive as blank-* events carrying the physical row index
    blanks = [e for e in result.events if e.event_type.startswith("blank")]
    expected_index = parse_wikipedia_changes(
        wiki_table([RENAME_ROW, CAG_ROW, RECEIVERSHIP_ROW]), min_rows=1
    )[1].raw_row_index
    assert [e.event_type for e in blanks] == ["blank-add"]
    assert blanks[0].raw_row_index == expected_index
    assert blanks[0].entity_id is None  # an unidentifiable side never invent an entity
    # month-end rows exist for every month in the (small) grid and are key-unique
    months = {row.month_end for row in result.month_end_rows}
    assert months == set(month_end_grid("2022-06", "2026-07"))
    keys = [(row.month_end, row.entity_id) for row in result.month_end_rows]
    assert len(keys) == len(set(keys))
    # entity ids are CIK-anchored for current seats (A13: no fund entities here)
    meta = result.entity_by_id()[table.resolve("META", "2026-01-01")]
    assert meta.entity_key_kind == "cik" and meta.display_ticker == "META"


def test_synthetic_build_writes_every_deliverable(tmp_path: Path) -> None:
    result = build_sp500_pit(
        synthetic_sources(),
        built_at="2026-01-01T00:00:00+00:00",
        grid_start="2022-06",
        grid_end="2023-06",
        min_wikipedia_rows=1,
    )
    hashes = write_products(result, tmp_path)
    expected = {
        "entities.csv",
        "symbol_history.jsonl",
        "aliases.csv",
        "events.csv",
        "month_end_membership.csv",
        "month_end_lists.jsonl",
        "ticker_norm_map.csv",
        "reconciliation_joeyfife.csv",
        "reconciliation_wiki_vs_fja.csv",
        "gaps.csv",
        "coverage.json",
        "coverage_report.json",
        "LICENSE_NOTES.md",
    }
    assert expected.issubset(set(hashes))
    assert (tmp_path / "build_manifest.json").is_file()
    coverage = json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))
    assert isinstance(coverage["snapshot_coverage"], dict)
    assert "max_gap_days" in coverage
    assert coverage["assertions"]["total"] == 17
    assert set(coverage["assertions"]["detail"]) >= {"A1", "A8", "A17"}
    assert coverage["contract"] == "qs.universe_sp500_pit/v1"
    assert coverage["daily_precision_claimed"] is False
    # D2 rows mirror D1's embedded symbol_history
    history = [
        json.loads(line)
        for line in (tmp_path / "symbol_history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    entity_rows = list(csv.DictReader((tmp_path / "entities.csv").open(encoding="utf-8")))
    embedded = sum(len(json.loads(row["symbol_history"])) for row in entity_rows)
    assert len(history) == embedded
    # D8 is the joeyfife diagnostic and joeyfife never enters a product table
    assert (
        (tmp_path / "reconciliation_joeyfife.csv")
        .read_text(encoding="utf-8")
        .startswith("date,ticker,entity_id")
    )
    assert "joeyfife" not in (tmp_path / "aliases.csv").read_text(encoding="utf-8")


def test_assertion_change_gets_new_validation_identity_without_changing_data_build() -> None:
    result = build_sp500_pit(
        synthetic_sources(),
        built_at="2026-01-01T00:00:00+00:00",
        grid_start="2022-06",
        grid_end="2023-06",
        min_wikipedia_rows=1,
    )
    before = result.coverage
    assert before["validation_digest"] == build_coverage(result)["validation_digest"]
    original = next(a for a in result.assertions if a.id == "A8")
    assert original.passed is False
    result.assertions = [
        replace(a, passed=True, detail="Changed assertion outcome on unchanged data")
        if a.id == "A8" else a
        for a in result.assertions
    ]
    after = build_coverage(result)

    assert before["build_id"] == after["build_id"]
    assert before["validation_digest"] != after["validation_digest"]
    assert before["validation_identity"] != after["validation_identity"]


@pytest.mark.parametrize("changed_input", ["rule_version", "threshold", "source_hash"])
def test_validation_digest_binds_rule_threshold_and_source(changed_input, monkeypatch) -> None:
    result = build_sp500_pit(
        synthetic_sources(), grid_start="2022-06", grid_end="2023-06", min_wikipedia_rows=1
    )
    before = result.coverage
    if changed_input == "rule_version":
        monkeypatch.setattr(sp500_pit, "SP500_PIT_VALIDATION_RULE_VERSION", "test-rule/v3")
    elif changed_input == "threshold":
        monkeypatch.setattr(sp500_pit, "BASELINE_MAX_GAP_DAYS", 92)
    else:
        result.facts["source_hashes"] = {
            **result.facts["source_hashes"], "fja05680_updated": "0" * 64
        }
    after = build_coverage(result)

    assert before["build_id"] == after["build_id"]
    assert before["validation_digest"] != after["validation_digest"]


def test_validation_metadata_and_limits_survive_writing(tmp_path: Path) -> None:
    result = build_sp500_pit(
        synthetic_sources(), grid_start="2022-06", grid_end="2023-06", min_wikipedia_rows=1
    )
    write_products(result, tmp_path)
    coverage = json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "build_manifest.json").read_text(encoding="utf-8"))

    for document in (coverage, manifest):
        assert document["validation_digest"] == result.coverage["validation_digest"]
        assert document["validation_identity"] == result.coverage["validation_identity"]
        assert document["independent_completeness"] == "not_verified"
        assert document["research_ready"] is False
        assert document["build_status_scope"] == "configured_assertions_only"
    a8 = next(a for a in result.assertions if a.id == "A8")
    assert a8.evidence["check_kind"] == "source_calibrated_drift_check"
    assert a8.evidence["independent_completeness"] == "not_verified"


# ---------------------------------------------------------------------------
# real sources end-to-end (A1..A17)
# ---------------------------------------------------------------------------
pytestmark_real = pytest.mark.skipif(
    not REAL_SOURCES.is_dir(),
    reason="T1.4 sources are staged artifacts and intentionally not committed",
)


@pytestmark_real
def test_real_sources_end_to_end(tmp_path: Path) -> None:
    sources = SourceBundle.from_dir(REAL_SOURCES)
    result = build_sp500_pit(sources, built_at="2026-09-16T12:00:00+00:00")
    by_id = {a.id: a for a in result.assertions}
    assert len(by_id) == 17

    for assertion_id in (
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A9",
        "A11",
        "A12",
        "A13",
        "A14",
        "A15",
        "A16",
        "A17",
    ):
        assert by_id[assertion_id].passed, f"{assertion_id}: {by_id[assertion_id].detail}"
    assert by_id["A10"].passed, by_id["A10"].detail

    # A8 uses source-calibrated drift bands: the
    # fja05680 source's member count drifts by era (487-493 in 1996-2000,
    # 494-499 in 2001-2014, 499-506 in 2015+), so the flat [495,510] baseline
    # failed on the source's early years. Neither bound establishes independent
    # completeness. Preserve the current era pass and the original diagnostic.
    assert by_id["A8"].passed, by_id["A8"].detail
    a8 = by_id["A8"].evidence
    assert a8["violations"] == 0
    assert a8["check_kind"] == "source_calibrated_drift_check"
    assert a8["independent_completeness"] == "not_verified"
    counterfactual = a8["original_flat_bounds_counterfactual"]
    assert counterfactual["bounds"] == [495, 510]
    assert counterfactual["violations"] == 81
    assert len(counterfactual["violations_by_month"]) == 81
    assert counterfactual["authority"] == "diagnostic_only"
    assert [list(b) for b in MONTH_END_MEMBER_BOUNDS_BY_ERA] == [
        ["1996-01", "2000-12", 485, 496],
        ["2001-01", "2014-12", 492, 502],
        ["2015-01", "9999-12", 497, 510],
    ]

    coverage = result.coverage
    assert coverage["snapshot_coverage"]["n_snapshots"] == 2720
    assert coverage["snapshot_coverage"]["start"] == "1996-01-02"
    assert coverage["snapshot_coverage"]["end"] == "2026-08-18"
    assert coverage["max_gap_days"] == 91 and coverage["gaps_gt_30d"] == 33
    assert coverage["wikipedia_dated_rows"] == 407
    assert coverage["wikipedia_blank_rows"] == 42
    assert coverage["wikipedia_revision"] == "2026-08-23T16:26:12Z"
    assert coverage["unvalidated_span"] == "1976-07-01..1995-12-31"
    assert coverage["assertions"]["hard_failed"] == []
    assert coverage["assertions"]["build_status"] == "ok"
    assert coverage["independent_completeness"] == "not_verified"
    assert coverage["research_ready"] is False
    assert coverage["build_status_scope"] == "configured_assertions_only"
    assert coverage["month_end_grid"]["n_months"] == 368

    # the month-end product reproduces the anchor snapshot roster line for line
    last = result.month_end_lists[-1]
    assert last["month_end"] == "2026-08-31"
    assert last["n_members"] == 503
    assert len(last["members"]) == 503
    assert not coverage["unresolvable_tickers"]
    assert coverage["entity_duplicate_months"] == 0

    # A4 details: all six evidenced handoffs reproduce
    assert {k: v["ok"] for k, v in by_id["A4"].evidence.items()} == {
        "WLTW->WTW": True,
        "CDAY->DAY": True,
        "FLT->CPAY": True,
        "FB->META": True,
        "ANTM->ELV": True,
        "NLOK->GEN": True,
    }
    # A7: Q's three seats resolve to three different entities
    table = result.alias_table()
    assert (
        len(
            {
                table.resolve("Q", "2010-01-01"),
                table.resolve("Q", "2017-10-01"),
                table.resolve("Q", "2026-01-01"),
            }
        )
        == 3
    )

    # writers: every deliverable is emitted and the manifest pins the build
    hashes = write_products(result, tmp_path)
    assert "coverage.json" in hashes
    manifest = json.loads((tmp_path / "build_manifest.json").read_text(encoding="utf-8"))
    assert manifest["assertions_hard_failed"] == []
    assert manifest["build_status"] == "ok"
    assert manifest["validation_digest"] == coverage["validation_digest"]
    assert manifest["validation_identity"] == coverage["validation_identity"]
    assert manifest["independent_completeness"] == "not_verified"
    assert manifest["research_ready"] is False
    assert len(manifest["file_sha256"]) >= 13
    written_rows = sum(1 for _ in (tmp_path / "month_end_membership.csv").open(encoding="utf-8"))
    assert written_rows == len(result.month_end_rows) + 1  # header
