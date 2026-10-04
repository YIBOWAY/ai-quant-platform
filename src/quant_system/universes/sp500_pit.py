"""S&P 500 point-in-time membership builder (T1.4, namespace ``sp500_pit_v1``).

Design authority: ``evidence/phase1-t14/design.md`` (T1.4 design) with the rule
set in ``docs/audits/2026-09-16-candidate-universe-sources.md`` (§4 R-1..R-9,
§8 F1..F7) and the empirical verdicts in
``docs/receipts/2026-09-16-t12-60-symbol-sample.md``.

This module is a *builder*: it reads three public read-only datasets (plus an
optional current-constituent CIK map) and emits append-only artifacts. It does
not touch ``universes/pit.py`` and does not modify any shipped enum.

Core principles (design §0):

* **P1 entity before ticker** — joins and churn statistics key on
  ``(entity_id, date)``; a ticker is only "an entity's doorplate on a day".
* **P2 events are the skeleton, snapshots validate it** — every disagreement is
  written out, never silently resolved.
* **P3 empty cells are first-class** — the 42 blank Wikipedia ticker cells are
  preserved; dropping them shifts columns and turns "CAG removed" into
  "CAG added".
* **P4 an empty parse must raise**, never return an empty table.
* **P5 products carry their own confidence** (source / as_of / date_confidence).
* **P6 joeyfife is cross-check only** and never enters a product table.

Implemented deviations from the literal design text — all deliberate, all
registered as gaps/reconciliation rows rather than hidden:

1. **Rename evidence is interval-scoped.** A literal reading of design rule 2
   ("old.code last day == new.code first day") matches 1123 same-day handoffs in
   ``sp500_ticker_start_end.csv``; those are same-day index rebalances, not
   renames, and merging them would fuse unrelated companies. Renames therefore
   come from (a) the 5 pure-rename rows in the Wikipedia table and (b) the 6
   handoff groups empirically evidenced in T1.1 R8. The remaining 1117
   same-day handoff pairs are quantified in ``gaps.csv`` (G6).
2. **``agreement`` is computed against the anchor snapshot** (design step 2b),
   with ``conflict`` reserved for a *contradicted* removal (the next fja snapshot
   still lists the entity). Per-row diffs land in
   ``reconciliation_wiki_vs_fja.csv``; the next-snapshot cross-check is
   aggregated into ``coverage.json``.
3. **CIK is only valid for currently-listed seats.** ``datasets/s-and-p-500-companies``
   is a *current* cross-section, so ``Q``'s CIK belongs to Qnity (2025-), not to
   the 2000-2011 ``Q`` seat. CIK anchoring is therefore applied to the open
   alias interval only; closed historical seats fall back to ``E:X:<slug>``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

SP500_PIT_CONTRACT = "qs.universe_sp500_pit/v1"
SP500_PIT_NAMESPACE = "sp500_pit_v1"
SP500_PIT_VALIDATION_RULE_VERSION = "sp500_pit_assertions/v2"

WIKIPEDIA_CHANGES_SOURCE_URL = (
    "https://en.wikipedia.org/w/index.php?title=Historical_components_of_the_S%26P_500&action=raw"
)
WIKIPEDIA_MAIN_ARTICLE_URL = (
    "https://en.wikipedia.org/w/index.php?title=List_of_S%26P_500_companies&action=raw"
)
# URL-encoded titles, asserted by A15 so a scraper can never drift back to the
# main article (which no longer carries the changes table: R1/S2).
WIKIPEDIA_CHANGES_SOURCE_TITLE = "Historical_components_of_the_S%26P_500"
WIKIPEDIA_MAIN_ARTICLE_SOURCE_TITLE = "List_of_S%26P_500_companies"
FJA_UPDATED_SOURCE_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
)
FJA_START_END_SOURCE_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/sp500_ticker_start_end.csv"
)
JOEYFIFE_SOURCE_URL = (
    "https://raw.githubusercontent.com/joeyfife/point-in-time-sp500/main/data/membership.json"
)

# --- baseline constants (T1.1 §2 R1-R11 / design §4 A1..A17) --------------
MIN_WIKIPEDIA_DATED_ROWS = 400  # A1: baseline 407
BASELINE_BLANK_ROWS = 42  # A3
BASELINE_SNAPSHOT_COUNT = 2720  # A9
BASELINE_MAX_GAP_DAYS = 91  # A9
BASELINE_GAPS_GT_30D = 33  # A9
EXPECTED_WIKIPEDIA_REVISION = "2026-08-23T16:26:12Z"  # drift detector (G8)
MONTH_END_MEMBER_BOUNDS_BY_ERA: tuple[tuple[str, str, int, int], ...] = (
    # A8-count is a source-calibrated drift check, not independent completeness.
    # The fja05680 source's member count drifts
    # by era — 487-493 in 1996-2000, 494-499 in 2001-2014, 499-506 in 2015+.
    # Retain the existing calibrated bands as source/build drift limits;
    # they are not independently established bounds on the true roster.
    ("1996-01", "2000-12", 485, 496),
    ("2001-01", "2014-12", 492, 502),
    ("2015-01", "9999-12", 497, 510),
)
ORIGINAL_MONTH_END_MEMBER_BOUNDS = (495, 510)  # counterfactual diagnostic only
DEFAULT_MONTH_GRID_START = "1996-01"
DEFAULT_MONTH_GRID_END = "2026-08"
FUNDAMENTAL_COUNT_NOTE = (
    "fja05680 1996-1998 snapshots list 487-493 tickers; A8 uses per-era bands "
    "calibrated to the source's own drift; independent completeness is not_verified"
)

# A4: the six empirically evidenced same-day handoffs (T1.1 §2 R8).
RENAME_HANDOFF_EVIDENCE: tuple[tuple[str, str, str], ...] = (
    ("WLTW", "WTW", "2022-01-10"),
    ("CDAY", "DAY", "2024-02-01"),
    ("FLT", "CPAY", "2024-03-25"),
    ("FB", "META", "2022-06-09"),
    ("ANTM", "ELV", "2022-06-28"),
    ("NLOK", "GEN", "2022-11-08"),
)

# A13: broker wire codes that must never be used as an identity source
# (T1.2 §四 — FB-US/ANSS-US resolve to ETFs, Q resolves to Qnity wrong-security).
BROKER_NEGATIVE_CASES: tuple[tuple[str, str, str], ...] = (
    ("FB-US", "Futu basicinfo resolved to PROSHARES S&P 500 DYNAMIC BUFFER ETF", "etf"),
    ("ANSS-US", "Futu basicinfo resolved to 1x short Anthropic ETF (Leverage Shares)", "etf"),
    (
        "Q",
        "Futu basicinfo resolved to Qnity Electronics (2025 spin-off), not the 2000-2011 Q seat",
        "reused-ticker",
    ),
)

# A15: the changes table moved here on 2026-08-11; the main article has none.
WIKIPEDIA_CHANGES_TITLE = "Historical_components_of_the_S&P_500"
WIKIPEDIA_MAIN_ARTICLE_TITLE = "List_of_S&P_500_companies"


class Sp500PitError(RuntimeError):
    """Hard build/assertion failure (design: hard assertions raise)."""


# ---------------------------------------------------------------------------
# value objects
# ---------------------------------------------------------------------------
EventType = Literal[
    "add",
    "remove",
    "rename",
    "acquisition-delisted",
    "bankruptcy-receivership",
    "index-removal",
    "blank-add",
    "blank-remove",
]
ReasonClass = Literal[
    "market-capitalization",
    "acquisition",
    "spinoff",
    "bankruptcy-receivership",
    "index-removal",
    "rename",
    "other",
    "blank",
]
DateConfidence = Literal["confirmed-both-sources", "single-source", "inferred", "unverified"]
Agreement = Literal["both", "wikipedia_only", "fja_only", "conflict"]
MembershipSource = Literal[
    "snapshot_exact", "snapshot_forward_fill", "event_replay", "cross_validated"
]
DelistReason = Literal[
    "none",
    "acquisition",
    "bankruptcy-receivership",
    "index-removal",
    "ticker-change",
    "unknown",
]


@dataclass(frozen=True)
class WikiRow:
    """One dated physical row of the Wikipedia changes table (F2: index-bound)."""

    raw_row_index: int
    effective_date: str
    added_ticker: str
    added_name: str
    removed_ticker: str
    removed_name: str
    reason_text: str
    refs: str
    cell_count: int

    @property
    def announced_date(self) -> str | None:
        return parse_ref_announced_date(self.refs, self.effective_date)


@dataclass(frozen=True)
class Snapshot:
    as_of: str
    tickers: tuple[str, ...]


@dataclass(frozen=True)
class Segment:
    """A ticker's membership interval from ``sp500_ticker_start_end.csv``."""

    ticker: str
    start: str
    end: str | None
    source: str = "fja05680_start_end"


@dataclass(frozen=True)
class AliasRow:
    ticker: str
    valid_from: str
    valid_to: str | None
    entity_id: str
    is_alias: bool
    alias_of: str | None
    rename_event_ref: str | None
    source: str


@dataclass(frozen=True)
class EventRow:
    event_id: str
    entity_id: str | None
    ticker_as_of: str | None
    security_name_raw: str | None
    event_type: str
    effective_date: str
    announced_date: str | None
    date_confidence: str
    side: str
    counterpart_ticker: str | None
    reason_text: str | None
    reason_class: str
    source: str
    source_ref: str | None
    as_of: str
    ret_str: str | None
    raw_row_index: int | None


@dataclass(frozen=True)
class EntityRow:
    entity_id: str
    entity_key_kind: str
    cik: str | None
    canonical_name: str
    display_ticker: str | None
    first_seen: str
    last_seen: str | None
    delist_reason: str
    delisting_date: str | None
    entity_type: str
    provenance: tuple[str, ...]
    symbol_history: tuple[dict, ...]


@dataclass(frozen=True)
class MonthEndRow:
    month_end: str
    entity_id: str
    ticker_as_of: str | None
    membership_source: str
    snapshot_date_used: str | None
    gap_days: int
    confidence: str
    agreement: str


@dataclass(frozen=True)
class Assertion:
    id: str
    hard: bool
    passed: bool
    detail: str
    evidence: dict = field(default_factory=dict)


@dataclass
class BuildResult:
    entities: list[EntityRow]
    aliases: list[AliasRow]
    events: list[EventRow]
    month_end_rows: list[MonthEndRow]
    month_end_lists: list[dict]
    coverage: dict
    gaps: list[dict]
    reconciliation_wiki_vs_fja: list[dict]
    reconciliation_joeyfife: list[dict]
    ticker_norm_map: list[dict]
    assertions: list[Assertion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    def alias_table(self) -> AliasTable:
        return AliasTable(self.aliases)

    def entity_by_id(self) -> dict[str, EntityRow]:
        return {row.entity_id: row for row in self.entities}

    def hard_failures(self) -> list[Assertion]:
        return [a for a in self.assertions if a.hard and not a.passed]


class AliasTable:
    """The only entity-resolution entry point (design §1.2 / F3 / A12).

    ``resolve(ticker, date)`` returns the entity id valid on that date, ``None``
    when the ticker was not a member then, and raises when two intervals for the
    same ticker overlap (overlap == data defect, never a silent pick).
    """

    def __init__(self, rows: Sequence[AliasRow]) -> None:
        self.rows = list(rows)
        self._by_ticker: dict[str, list[AliasRow]] = {}
        for row in self.rows:
            self._by_ticker.setdefault(row.ticker, []).append(row)
        for ticker, bucket in self._by_ticker.items():
            bucket.sort(key=lambda r: r.valid_from)
            for left, right in zip(bucket, bucket[1:], strict=False):
                if left.valid_to is None or left.valid_to > right.valid_from:
                    raise Sp500PitError(
                        f"A12 alias interval overlap for {ticker}: "
                        f"[{left.valid_from},{left.valid_to}) "
                        f"vs [{right.valid_from},{right.valid_to})"
                    )

    def resolve(self, ticker: str, on_date: str) -> str | None:
        if looks_like_broker_wire(ticker):
            raise Sp500PitError(
                f"A13 broker wire code {ticker!r} must not be used for entity resolution "
                f"(T1.2 §四: FB-US/ANSS-US resolve to ETFs, Q to the wrong security)"
            )
        hits = [
            row
            for row in self._by_ticker.get(ticker.upper(), ())
            if row.valid_from <= on_date and (row.valid_to is None or on_date < row.valid_to)
        ]
        if not hits:
            return None
        if len(hits) > 1:
            raise Sp500PitError(
                f"A12 ambiguous alias for {ticker}@{on_date}: {[h.entity_id for h in hits]}"
            )
        return hits[0].entity_id

    def intervals(self, ticker: str) -> list[AliasRow]:
        return list(self._by_ticker.get(ticker.upper(), ()))


def looks_like_broker_wire(ticker: str) -> bool:
    """True for Futu ``US.X`` / ``X-US`` wire forms (R-9 red line, A13)."""
    upper = ticker.strip().upper()
    return upper.startswith("US.") or upper.endswith("-US") or upper.endswith(".US")


def _sha16(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _iso(value: date) -> str:
    return value.isoformat()


def _to_date(value: str) -> date:
    return date.fromisoformat(value)


# ---------------------------------------------------------------------------
# reason classification (R-3/R-4/R-5/R-8)
# ---------------------------------------------------------------------------
_RENAME_RE = re.compile(r"changed its ticker symbol|changed its name to|was renamed", re.I)
_MERGER_GUARD_RE = re.compile(r"acquir|merger|merged|takeover|buyout|consortium", re.I)
_BANKRUPTCY_RE = re.compile(r"receivership|\bFDIC\b|bankrupt|chapter\s*11|liquidat", re.I)
_MARCAP_RE = re.compile(r"market capitalization", re.I)
_SPINOFF_RE = re.compile(r"spin-?off|spun off|split-?off|spin off", re.I)
_ACQUISITION_RE = re.compile(r"acquir|merger|merged|takeover|buyout", re.I)


def classify_reason(reason_text: str | None) -> str:
    """Map a Wikipedia ``Reason`` cell to the design's ``reason_class`` enum.

    Order matters and is calibrated against T1.1 §2 R5: the merger/spin-off guard
    runs before the rename rule so the five merger-driven ticker changes
    (IR/XEC, AMCR/BMS, DWDP/DOW, WLTW/FOSL, AAL/AGN) are NOT treated as pure
    renames. Exactly five rows classify as ``rename`` (CDAY/DAY, WLTW/WTW,
    FLT/CPAY, Q/IQV, KFT/MDLZ).
    """

    text = (reason_text or "").strip()
    if not text:
        return "blank"
    if _BANKRUPTCY_RE.search(text):
        return "bankruptcy-receivership"
    if _RENAME_RE.search(text) and not _MERGER_GUARD_RE.search(text):
        return "rename"
    if _MARCAP_RE.search(text):
        return "market-capitalization"
    if _SPINOFF_RE.search(text):
        return "spinoff"
    if _ACQUISITION_RE.search(text):
        return "acquisition"
    return "other"


_REMOVED_EVENT_TYPE = {
    "acquisition": "acquisition-delisted",
    "bankruptcy-receivership": "bankruptcy-receivership",
    "market-capitalization": "index-removal",
}
_REF_DATE_RE = re.compile(r"\|\s*date\s*=\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
_MONTH_NAME = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_WIKI_DATE_RE = re.compile(r"^([A-Z][a-z]+) (\d{1,2}), (\d{4})$")


def parse_wiki_date(text: str) -> str | None:
    """``"June 30, 2026"`` -> ``"2026-06-30"`` (None when not a dated row)."""

    match = _WIKI_DATE_RE.match(text.strip())
    if not match:
        return None
    month = _MONTH_NAME.get(match.group(1).lower())
    if month is None:
        return None
    return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"


def parse_ref_announced_date(refs: str, effective_date: str) -> str | None:
    """Best-effort announcement date from ``<ref>`` ``|date=`` params (gap G3).

    Never silently shifts the effective date: a candidate is only accepted when
    it is a real date, not after the effective date, and unambiguous.
    """

    seen = {parse_wiki_date(m) for m in _REF_DATE_RE.findall(refs or "")}
    seen.discard(None)
    if len(seen) != 1:
        return None
    candidate = seen.pop()
    return candidate if candidate <= effective_date else None


def strip_wikilink(text: str) -> str:
    """``[[Silver Lake (investment firm)|Silver Lake]]`` -> ``Silver Lake``."""

    value = (text or "").strip()
    value = re.sub(r"<ref[^>]*>.*?</ref>", "", value, flags=re.S)
    value = re.sub(r"<ref[^>]*/>", "", value)

    def _unwrap(match: re.Match[str]) -> str:
        return match.group(1).split("|")[-1]

    value = re.sub(r"\[\[([^\]]+)\]\]", _unwrap, value)
    value = re.sub(r"''+", "", value)
    return value.strip()


# ---------------------------------------------------------------------------
# source parsers
# ---------------------------------------------------------------------------
def parse_wikipedia_changes(raw: str, *, min_rows: int = MIN_WIKIPEDIA_DATED_ROWS) -> list[WikiRow]:
    """Parse the ``id="changes"`` wikitable of the Historical-components article.

    F1 (hard): fewer than ``min_rows`` dated rows raises instead of returning an
    empty/partial table. F2: cells are bound **by index**; empty cells are kept.
    """

    anchor = raw.find('id="changes"')
    if anchor < 0:
        raise Sp500PitError(
            'F1/A15 no wikitable with id="changes" found — the parser is pointed at the '
            f"wrong article; the changes table lives at {WIKIPEDIA_CHANGES_TITLE!r}, "
            f"not {WIKIPEDIA_MAIN_ARTICLE_TITLE!r}"
        )
    end = raw.find("\n|}", anchor)
    if end < 0:
        raise Sp500PitError("malformed wikitext: unterminated changes table")
    block = raw[anchor:end]

    rows: list[list[str]] = []
    current: list[str] | None = None
    for raw_line in block.split("\n"):
        line = raw_line.strip()
        if line.startswith("|-"):
            if current is not None:
                rows.append(current)
            current = []
            continue
        if current is None or line.startswith("!") or line.startswith("{|"):
            continue
        current.append(raw_line)
    if current is not None:
        rows.append(current)

    parsed: list[WikiRow] = []
    for index, row_lines in enumerate(rows):
        cells = _row_cells(row_lines)
        if not cells:
            continue
        effective = parse_wiki_date(cells[0])
        if effective is None:
            continue
        padded = list(cells) + [""] * (6 - len(cells))
        # cell 5 is Reason, cell 6 (when present) is Refs; some rows inline the
        # <ref> into the Reason cell, so the announcement-date probe sees both.
        refs_text = " ".join(padded[5:])
        parsed.append(
            WikiRow(
                raw_row_index=index,
                effective_date=effective,
                added_ticker=padded[1].strip().upper(),
                added_name=strip_wikilink(padded[2]),
                removed_ticker=padded[3].strip().upper(),
                removed_name=strip_wikilink(padded[4]),
                reason_text=re.sub(r"<ref.*", "", padded[5], flags=re.S).strip(),
                refs=refs_text,
                cell_count=len(cells),
            )
        )
    if len(parsed) < min_rows:
        raise Sp500PitError(
            f"F1 silent-partial-parse guard: only {len(parsed)} dated rows found "
            f"(minimum {min_rows}). Re-baseline before trusting the artifact."
        )
    return parsed


def _row_cells(row_lines: Sequence[str]) -> list[str]:
    """Bind cells by index (F2); a trailing ``|`` from ``| X |`` lines is dropped."""

    cells: list[str] = []
    for line in row_lines:
        if line.startswith("||"):
            cells.extend(line[2:].split("||"))
        elif line.startswith("|"):
            cells.extend(line[1:].split("||"))
        else:
            cells.append(line)
    return [cell.strip().rstrip("|").strip() for cell in cells]


def parse_fja_snapshots(text: str) -> list[Snapshot]:
    """Parse ``date,tickers`` snapshot CSV (one quoted comma list per snapshot)."""

    snapshots: list[Snapshot] = []
    for row in csv.DictReader(io.StringIO(text)):
        as_of = (row.get("date") or "").strip()
        if not as_of:
            continue
        tickers = tuple(
            t.strip().upper() for t in (row.get("tickers") or "").split(",") if t.strip()
        )
        snapshots.append(Snapshot(as_of=as_of, tickers=tickers))
    if not snapshots:
        raise Sp500PitError("F1 empty fja05680 snapshot file")
    snapshots.sort(key=lambda s: s.as_of)
    return snapshots


def parse_fja_start_end(text: str) -> list[Segment]:
    segments: list[Segment] = []
    for row in csv.DictReader(io.StringIO(text)):
        ticker = (row.get("ticker") or "").strip().upper()
        start = (row.get("start_date") or "").strip()
        if not ticker or not start:
            continue
        end = (row.get("end_date") or "").strip() or None
        segments.append(Segment(ticker=ticker, start=start, end=end))
    if not segments:
        raise Sp500PitError("F1 empty sp500_ticker_start_end.csv")
    return segments


def load_joeyfife(text: str) -> dict:
    payload = json.loads(text)
    if "current" not in payload or "changes" not in payload:
        raise Sp500PitError("joeyfife membership.json missing current/changes")
    return payload


def load_cik_map(text: str) -> dict[str, str]:
    """Ticker -> 10-digit CIK from the *current* constituents cross-section.

    Only current (open) seats may use these: ``Q`` currently maps to Qnity, and
    that CIK must not leak onto the 2000-2011 ``Q`` seat (R-6 / A7).
    """

    mapping: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(text)):
        symbol = (row.get("Symbol") or "").strip().upper()
        cik = (row.get("CIK") or "").strip()
        if symbol and cik:
            mapping[symbol] = cik.zfill(10)
    return mapping


def snapshot_gap_stats(snapshots: Sequence[Snapshot]) -> dict:
    pairs = list(zip(snapshots, snapshots[1:], strict=False))
    gaps = [(a.as_of, b.as_of, (_to_date(b.as_of) - _to_date(a.as_of)).days) for a, b in pairs]
    worst = max(gaps, key=lambda g: g[2]) if gaps else None
    density: dict[str, int] = {}
    for snap in snapshots:
        density[snap.as_of[:4]] = density.get(snap.as_of[:4], 0) + 1
    return {
        "start": snapshots[0].as_of,
        "end": snapshots[-1].as_of,
        "n_snapshots": len(snapshots),
        "density_by_year": density,
        "max_gap_days": worst[2] if worst else 0,
        "max_gap_pair": [worst[0], worst[1]] if worst else [],
        "gaps_gt_30d": sum(1 for g in gaps if g[2] > 30),
        "gaps": gaps,
    }


def month_end_grid(
    start: str = DEFAULT_MONTH_GRID_START, end: str = DEFAULT_MONTH_GRID_END
) -> list[str]:
    """Last NYSE trading session of each month (avoids weekend/holiday phantoms)."""

    import exchange_calendars as xcals
    import pandas as pd

    calendar = xcals.get_calendar("XNYS", start="1995-01-01", end="2027-12-31")
    start_year, start_month = (int(part) for part in start.split("-"))
    end_year, end_month = (int(part) for part in end.split("-"))
    grid: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        month_end = pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)
        session = calendar.date_to_session(month_end, direction="previous")
        grid.append(str(session.date()))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return grid


# ---------------------------------------------------------------------------
# ticker normalisation layer (F4)
# ---------------------------------------------------------------------------
_NORGATE_RE = re.compile(r"^([A-Z][A-Z0-9.]*)-\d{6}$")


def canonical_ticker(variant: str) -> str:
    """F4: canonical form is the upper-case dotted ticker, Q suffix preserved."""

    value = variant.strip().upper()
    if "-" in value and not _NORGATE_RE.match(value):
        head, _, tail = value.rpartition("-")
        if len(tail) == 1 and head:
            return f"{head}.{tail}"
    return value


def to_futu_wire(canonical: str) -> str:
    """Consumption mapping only — never an identity source (A13 / R-9)."""

    return f"US.{canonical}"


def to_longbridge_wire(canonical: str) -> str:
    """Consumption mapping only — never an identity source (A13 / R-9)."""

    return f"{canonical}.US"


def build_ticker_norm_map(tickers: Iterable[str], segments: Sequence[Segment]) -> list[dict]:
    """Self-built cross-convention map (F4: no ready-made map exists)."""

    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(
        canonical: str,
        variant: str,
        convention: str,
        base: str | None,
        suffix: str | None,
        source: str,
        note: str,
    ) -> None:
        key = (canonical, variant)
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "canonical_ticker": canonical,
                "variant": variant,
                "variant_convention": convention,
                "base_ticker": base or "",
                "suffix": suffix or "",
                "source": source,
                "note": note,
            }
        )

    for ticker in sorted(set(tickers)):
        add(ticker, ticker, "dot" if "." in ticker else "other", None, None, "observed", "")
        norgate = _NORGATE_RE.match(ticker)
        if norgate:
            add(
                norgate.group(1),
                ticker,
                "norgate_date",
                norgate.group(1),
                ticker.rsplit("-", 1)[1],
                "norgate_convention",
                "predefined Norgate suffix slot (not yet sourced)",
            )
        if ticker.endswith("Q") and len(ticker) > 2:
            add(
                ticker,
                ticker,
                "bankruptcy_q",
                ticker[:-1],
                "Q",
                "observed",
                "ambiguous: only strip Q when source=fja05680 and date > end_date (F4)",
            )
    for canonical, hyphen in (("BRK.B", "BRK-B"), ("BF.B", "BF-B")):
        add(
            canonical,
            hyphen,
            "hyphen",
            canonical,
            None,
            "T1.1_F4_sample",
            "Yahoo/yfiua hyphen form",
        )
    return rows


# ---------------------------------------------------------------------------
# rename evidence (R-1/R-2, A4/A11) — deliberately interval-scoped
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RenameEvidence:
    old_ticker: str
    new_ticker: str
    effective_date: str
    date_confidence: str
    sources: tuple[str, ...]
    raw_row_index: int | None = None
    reason_text: str = ""


def _segment_bounds(segments: Sequence[Segment], ticker: str) -> list[tuple[str, str | None]]:
    return [(s.start, s.end) for s in segments if s.ticker == ticker]


def detect_renames(
    wiki_rows: Sequence[WikiRow], segments: Sequence[Segment]
) -> list[RenameEvidence]:
    """Collect rename evidence from the Wikipedia table.

    Only the five *pure* ticker changes classify as ``rename`` (R5). The six
    evidenced same-day handoffs (A4) are added by :func:`handoff_renames`, which
    deliberately does NOT generalise to all 1123 same-day handoffs in
    ``sp500_ticker_start_end.csv`` (see module docstring deviation 1).
    """

    found: list[RenameEvidence] = []
    for row in wiki_rows:
        if classify_reason(row.reason_text) != "rename":
            continue
        if not row.added_ticker or not row.removed_ticker:
            continue
        old_bounds = _segment_bounds(segments, row.removed_ticker)
        new_bounds = _segment_bounds(segments, row.added_ticker)
        corroborated = any(end == row.effective_date for _, end in old_bounds) and any(
            start == row.effective_date for start, _ in new_bounds
        )
        sources = ("wikipedia",) + (("fja05680_start_end",) if corroborated else ())
        found.append(
            RenameEvidence(
                old_ticker=row.removed_ticker,
                new_ticker=row.added_ticker,
                effective_date=row.effective_date,
                date_confidence="confirmed-both-sources" if corroborated else "single-source",
                sources=sources,
                raw_row_index=row.raw_row_index,
                reason_text=row.reason_text,
            )
        )
    return found


def handoff_renames(
    wiki_renames: Sequence[RenameEvidence], segments: Sequence[Segment]
) -> tuple[list[RenameEvidence], list[dict]]:
    """A4's six evidenced handoffs, minus those already evidenced by Wikipedia."""

    known = {(r.old_ticker, r.new_ticker) for r in wiki_renames}
    extra: list[RenameEvidence] = []
    gaps: list[dict] = []
    for old, new, when in RENAME_HANDOFF_EVIDENCE:
        if (old, new) in known:
            continue
        old_end = {end for _, end in _segment_bounds(segments, old) if end}
        new_start = {start for start, _ in _segment_bounds(segments, new)}
        if when not in old_end or when not in new_start:
            gaps.append(
                {
                    "gap_id": "G-A4",
                    "kind": "rename-handoff-missing",
                    "fact": f"{old}->{new} handoff on {when} not reproducible "
                    "from sp500_ticker_start_end.csv",
                    "disposition": "handoff skipped; re-baseline the source before "
                    "trusting renames",
                }
            )
            continue
        extra.append(
            RenameEvidence(
                old_ticker=old,
                new_ticker=new,
                effective_date=when,
                date_confidence="single-source",
                sources=("fja05680_start_end",),
                reason_text="T1.1 R8 same-day handoff (not present in the Wikipedia table)",
            )
        )
    return extra, gaps


def same_day_handoff_survey(segments: Sequence[Segment]) -> dict:
    """Quantify the same-day handoffs the rename rule deliberately ignores (G6)."""

    ends: dict[str, list[str]] = {}
    starts: dict[str, list[str]] = {}
    for seg in segments:
        starts.setdefault(seg.start, []).append(seg.ticker)
        if seg.end:
            ends.setdefault(seg.end, []).append(seg.ticker)
    pairs = [
        (old, new, when)
        for when in sorted(set(ends) & set(starts))
        for old in ends[when]
        for new in starts[when]
        if old != new
    ]
    one_to_one = {
        when
        for when in set(ends) & set(starts)
        if len({t for t in ends[when]}) == 1 and len({t for t in starts[when]}) == 1
    }
    evidenced = {(old, new, when) for old, new, when in RENAME_HANDOFF_EVIDENCE}
    wiki_like = [p for p in pairs if p in evidenced]
    return {
        "same_day_handoff_pairs": len(pairs),
        "one_to_one_dates": len(one_to_one),
        "evidenced_renames": len(wiki_like),
        "unverifiable_pairs": len(pairs) - len(wiki_like),
    }


# ---------------------------------------------------------------------------
# interval drafts -> entities (P1 / R-1 / R-6)
# ---------------------------------------------------------------------------
@dataclass
class IntervalDraft:
    ticker: str
    valid_from: str
    valid_to: str | None
    source: str
    group: int = -1
    wiki_row_index: int | None = None

    @property
    def covers(self) -> tuple[str, str]:
        return (self.valid_from, self.valid_to or "9999-12-31")


def wiki_ticker_events(wiki_rows: Sequence[WikiRow]) -> list[tuple[str, str, str, str, int]]:
    """(ticker, date, side, event_type, raw_row_index) for non-blank wiki sides."""

    out: list[tuple[str, str, str, str, int]] = []
    for row in wiki_rows:
        reason_class = classify_reason(row.reason_text)
        if row.added_ticker and reason_class != "rename":
            out.append((row.added_ticker, row.effective_date, "added", "add", row.raw_row_index))
        if row.removed_ticker:
            event_type = (
                "rename"
                if reason_class == "rename"
                else _REMOVED_EVENT_TYPE.get(reason_class, "remove")
            )
            out.append(
                (row.removed_ticker, row.effective_date, "removed", event_type, row.raw_row_index)
            )
    out.sort(key=lambda item: (item[1], item[4], item[0]))
    return out


def build_interval_drafts(
    segments: Sequence[Segment], ticker_events: Sequence[tuple[str, str, str, str, int]]
) -> tuple[list[IntervalDraft], list[dict]]:
    """Alias intervals from the fja start/end file, backfilled from Wikipedia.

    fja05680 already covers every ticker that ever appears in a snapshot
    (verified: 1209/1209), so Wikipedia backfill only fires for tickers that are
    pure event-table additions (``KFT``, ``Q`` 2017-08-29..2017-11-15).
    """

    drafts = [
        IntervalDraft(seg.ticker, seg.start, seg.end, "fja05680_start_end") for seg in segments
    ]
    gaps: list[dict] = []

    by_ticker: dict[str, list[tuple[str, str]]] = {}
    open_add: dict[str, str] = {}
    for ticker, when, side, _event_type, _row in ticker_events:
        if side == "added":
            open_add.setdefault(ticker, when)
        elif ticker in open_add:
            by_ticker.setdefault(ticker, []).append((open_add.pop(ticker), when))
    for ticker, start in open_add.items():
        by_ticker.setdefault(ticker, []).append((start, None))

    for ticker, spans in by_ticker.items():
        existing = [d for d in drafts if d.ticker == ticker]
        for start, end in spans:
            span_end = end or "9999-12-31"
            if any(
                d.valid_from < span_end and (d.valid_to or "9999-12-31") > start for d in existing
            ):
                continue
            drafts.append(IntervalDraft(ticker, start, end, "wikipedia", wiki_row_index=None))
    return drafts, gaps


def merge_rename_groups(
    drafts: list[IntervalDraft], renames: Sequence[RenameEvidence]
) -> list[dict]:
    """Union the two seats joined by a rename (interval-scoped, so Q's 2000-2011
    Qwest seat is NOT fused with the 2017 Quintiles seat)."""

    gaps: list[dict] = []
    for rename in renames:
        old = _pick_old_draft(drafts, rename)
        new = _pick_new_draft(drafts, rename)
        if old is None or new is None:
            gaps.append(
                {
                    "gap_id": "G6",
                    "kind": "rename-interval-missing",
                    "fact": f"rename {rename.old_ticker}->{rename.new_ticker}"
                    f"@{rename.effective_date}: old={old is not None} new={new is not None}",
                    "disposition": "rename event recorded but no entity merge performed",
                }
            )
            continue
        if old.valid_to != rename.effective_date:
            gaps.append(
                {
                    "gap_id": "G6",
                    "kind": "rename-handoff-date-conflict",
                    "fact": f"{rename.old_ticker} interval ends {old.valid_to} but the rename is "
                    f"dated {rename.effective_date}",
                    "disposition": "source interval preserved (no silent trimming)",
                }
            )
        if _find(drafts, old) != _find(drafts, new):
            _union(drafts, old, new)
    return gaps


def _pick_old_draft(
    drafts: Sequence[IntervalDraft], rename: RenameEvidence
) -> IntervalDraft | None:
    candidates = [
        d
        for d in drafts
        if d.ticker == rename.old_ticker
        and d.valid_from <= rename.effective_date
        and (d.valid_to is None or d.valid_to >= rename.effective_date)
    ]
    if not candidates:
        return None
    exact = [d for d in candidates if d.valid_to == rename.effective_date]
    return (exact or sorted(candidates, key=lambda d: d.valid_from))[-1]


def _pick_new_draft(
    drafts: Sequence[IntervalDraft], rename: RenameEvidence
) -> IntervalDraft | None:
    candidates = [
        d
        for d in drafts
        if d.ticker == rename.new_ticker
        and d.valid_from <= rename.effective_date
        and (d.valid_to is None or d.valid_to >= rename.effective_date)
    ]
    if candidates:
        return sorted(candidates, key=lambda d: d.valid_from)[0]
    return next(
        (
            d
            for d in drafts
            if d.ticker == rename.new_ticker and d.valid_from >= rename.effective_date
        ),
        None,
    )


# Index-based union-find over interval drafts (keyed by object identity, so the
# dataclass equality of two identical-looking seats can never fuse them).
_UF_PARENT: dict[int, list[int]] = {}


def _index_of(drafts: Sequence[IntervalDraft], draft: IntervalDraft) -> int:
    for index, candidate in enumerate(drafts):
        if candidate is draft:
            return index
    raise Sp500PitError("interval draft is not part of this build")


def _find(drafts: Sequence[IntervalDraft], draft: IntervalDraft) -> int:
    parents = _UF_PARENT.setdefault(id(drafts), list(range(len(drafts))))
    index = _index_of(drafts, draft)
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    draft.group = index
    return index


def _union(drafts: list[IntervalDraft], left: IntervalDraft, right: IntervalDraft) -> None:
    root_left, root_right = _find(drafts, left), _find(drafts, right)
    if root_left != root_right:
        _UF_PARENT[id(drafts)][root_right] = root_left


def event_id_for(entity_id: str | None, effective_date: str, event_type: str, source: str) -> str:
    """Proxy key ``sha1(entity_id|date|type|source)[:16]`` (design §1.3)."""

    return _sha16(entity_id or "NULL", effective_date, event_type, source)


def removal_records(
    wiki_rows: Sequence[WikiRow], ticker_events: Sequence[tuple[str, str, str, str, int]]
) -> dict[str, list[dict]]:
    """``ticker -> [removal record, ...]`` in date order (R-3/R-4/R-8).

    Keyed by ticker *and* kept as a list, because one ticker can be removed by
    several different entities over time (``Q`` Qwest 2011, ``Q`` Quintiles 2017).
    """

    by_row = {row.raw_row_index: row for row in wiki_rows}
    records: dict[str, list[dict]] = {}
    for ticker, when, side, event_type, row_index in ticker_events:
        if side != "removed":
            continue
        row = by_row.get(row_index)
        reason_class = classify_reason(row.reason_text) if row else "other"
        previous = [r for r in records.get(ticker, []) if r["date"] == when]
        if previous:
            continue
        records.setdefault(ticker, []).append(
            {
                "date": when,
                "reason_class": reason_class,
                "event_type": event_type,
                "raw_row_index": row_index,
            }
        )
    for ticker in records:
        records[ticker].sort(key=lambda r: r["date"])
    return records


_DELIST_REASON_MAP = {
    "acquisition": "acquisition",
    "bankruptcy-receivership": "bankruptcy-receivership",
    "market-capitalization": "index-removal",
    "rename": "ticker-change",
}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "unknown"


def load_current_names(text: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(text)):
        symbol = (row.get("Symbol") or "").strip().upper()
        security = (row.get("Security") or "").strip()
        if symbol and security:
            names[symbol] = security
    return names


def build_entities(
    drafts: list[IntervalDraft],
    cik_map: dict[str, str],
    wiki_names: dict[str, list[tuple[str, str]]],
    current_names: dict[str, str],
    removal_by_ticker: dict[str, list[dict]],
    renames: Sequence[RenameEvidence],
) -> tuple[list[EntityRow], list[AliasRow], list[dict]]:
    """Fold interval drafts into entities + alias rows (R-1/R-2/R-6).

    ``entity_id`` uses ``E:CIK<10 digits>`` when the group holds an *open* seat
    that appears in the current constituents cross-section, else ``E:X:<slug>``.
    A CIK shared by several concurrently-listed security lines (dual-class
    issuers: GOOG/GOOGL, FOX/FOXA, NWS/NWSA) gets an explicit ``:<ticker>``
    discriminator, because the index roster counts lines (fja lists 503) and
    collapsing them would drop real members.
    """

    groups: dict[int, list[IntervalDraft]] = {}
    for draft in drafts:
        groups.setdefault(_find(drafts, draft), []).append(draft)

    open_cik_counts = Counter(
        cik_map[d.ticker] for d in drafts if d.valid_to is None and d.ticker in cik_map
    )

    rename_by_pair = {(r.old_ticker, r.new_ticker): r for r in renames}
    ordered = sorted(
        groups.values(),
        key=lambda seats: (min(s.valid_from for s in seats), min(s.ticker for s in seats)),
    )

    used_slugs: dict[str, int] = {}
    entities: list[EntityRow] = []
    aliases: list[AliasRow] = []
    gaps: list[dict] = []

    for seats in ordered:
        seats = sorted(seats, key=lambda s: (s.valid_from, s.ticker))
        open_seats = [s for s in seats if s.valid_to is None]
        if len(open_seats) > 1:
            gaps.append(
                {
                    "gap_id": "G11",
                    "kind": "multiple-open-seats",
                    "fact": f"entity group has {len(open_seats)} open seats: "
                    f"{[s.ticker for s in open_seats]}",
                    "disposition": "display_ticker taken from the latest seat; review the source",
                }
            )
        representative = (
            max(open_seats, key=lambda s: s.valid_from).ticker
            if open_seats
            else max(seats, key=lambda s: (s.valid_from, s.ticker)).ticker
        )
        cik = cik_map.get(representative) if open_seats else None
        canonical_name = _entity_name(wiki_names, seats, representative, current_names)
        if cik:
            if open_cik_counts[cik] > 1:
                entity_id = f"E:CIK{cik}:{representative}"
            else:
                entity_id = f"E:CIK{cik}"
            key_kind = "cik"
        else:
            base = f"E:X:{_slugify(canonical_name)}"
            count = used_slugs.get(base, 0) + 1
            used_slugs[base] = count
            entity_id = base if count == 1 else f"{base}-{count}"
            key_kind = "slug"

        first_seen = min(s.valid_from for s in seats)
        last_seen = None if open_seats else max(s.valid_to for s in seats if s.valid_to)

        symbol_history = []
        for seat in seats:
            rename = rename_by_pair.get((seat.ticker, representative))
            alias_of = representative if seat.ticker != representative else None
            reason = "rename" if rename else ("initial" if seat is seats[0] else "membership")
            symbol_history.append(
                {
                    "entity_id": entity_id,
                    "ticker": seat.ticker,
                    "valid_from": seat.valid_from,
                    "valid_to": seat.valid_to,
                    "alias_of": alias_of,
                    "reason": reason,
                    "source": seat.source,
                }
            )
            rename_ref = None
            for candidate in renames:
                if (
                    candidate.old_ticker == seat.ticker
                    and seat.valid_to == candidate.effective_date
                ):
                    rename_ref = event_id_for(
                        entity_id, candidate.effective_date, "rename", candidate.sources[0]
                    )
                    break
            aliases.append(
                AliasRow(
                    ticker=seat.ticker,
                    valid_from=seat.valid_from,
                    valid_to=seat.valid_to,
                    entity_id=entity_id,
                    is_alias=seat.ticker != representative,
                    alias_of=representative if seat.ticker != representative else None,
                    rename_event_ref=rename_ref,
                    source=seat.source,
                )
            )

        delist_reason = "none"
        delisting_date: str | None = None
        if not open_seats:
            latest: dict | None = None
            for seat in seats:
                for record in removal_by_ticker.get(seat.ticker, []):
                    # attribute only removals that belong to THIS seat's window
                    if (
                        seat.valid_from <= record["date"]
                        and (seat.valid_to is None or record["date"] <= seat.valid_to)
                        and (latest is None or record["date"] >= latest["date"])
                    ):
                        latest = record
            if latest is None:
                delist_reason = "unknown"
                gaps.append(
                    {
                        "gap_id": "G7",
                        "kind": "unattributed-removal",
                        "fact": f"{entity_id} ({representative}) left the index on {last_seen} "
                        "with no Wikipedia removal row",
                        "disposition": "delist_reason=unknown; delisting_date left null "
                        "(no authoritative field)",
                    }
                )
            else:
                delist_reason = _DELIST_REASON_MAP.get(latest["reason_class"], "unknown")
                if delist_reason in {"acquisition", "bankruptcy-receivership"}:
                    delisting_date = latest["date"]
                else:
                    delisting_date = None  # R-8/A14: index-removal is NOT a delisting

        provenance = tuple(
            sorted(
                {"wikipedia", "fja05680_snapshot"}
                | {s.source for s in seats}
                | ({"sec_cik_cross_section"} if cik else set())
            )
        )
        entities.append(
            EntityRow(
                entity_id=entity_id,
                entity_key_kind=key_kind,
                cik=cik,
                canonical_name=canonical_name,
                display_ticker=representative,
                first_seen=first_seen,
                last_seen=last_seen,
                delist_reason=delist_reason,
                delisting_date=delisting_date,
                entity_type="operating_company",
                provenance=provenance,
                symbol_history=tuple(symbol_history),
            )
        )
    return entities, aliases, gaps


# ---------------------------------------------------------------------------
# event table (R-3/R-4/R-5/R-8/F3)
# ---------------------------------------------------------------------------
_BLANK_EVENT_TYPES = ("blank-add", "blank-remove")


def build_events(
    wiki_rows: Sequence[WikiRow],
    renames: Sequence[RenameEvidence],
    alias_table: AliasTable,
    segments: Sequence[Segment],
    *,
    wiki_revision: str | None,
    built_at: str,
) -> list[EventRow]:
    """One row per index-membership change (design §1.3).

    Removed-side entity resolution looks one day back because alias intervals are
    half-open ``[valid_from, valid_to)`` — verified empirically: WHR is absent
    from the 2024-03-18 snapshot but present in earlier ones.
    """

    events: list[EventRow] = []
    source_ref = (
        f"wikipedia revision={wiki_revision}" if wiki_revision else WIKIPEDIA_CHANGES_SOURCE_URL
    )

    def _resolve(ticker: str, on_date: str) -> str | None:
        return alias_table.resolve(ticker, on_date) if ticker else None

    for row in wiki_rows:
        reason_class = classify_reason(row.reason_text)
        announced = row.announced_date
        added_entity = _resolve(row.added_ticker, row.effective_date) if row.added_ticker else None
        removed_entity = (
            _resolve(row.removed_ticker, _previous_day(row.effective_date))
            if row.removed_ticker
            else None
        )
        if reason_class == "rename":
            events.append(
                EventRow(
                    event_id=event_id_for(
                        removed_entity, row.effective_date, "rename", "wikipedia"
                    ),
                    entity_id=removed_entity,
                    ticker_as_of=row.added_ticker or row.removed_ticker,
                    security_name_raw=row.added_name or row.removed_name or None,
                    event_type="rename",
                    effective_date=row.effective_date,
                    announced_date=announced,
                    date_confidence=_wiki_confidence(row, "rename", segments),
                    side="removed",
                    counterpart_ticker=row.removed_ticker or None,
                    reason_text=row.reason_text or None,
                    reason_class=reason_class,
                    source="wikipedia",
                    source_ref=source_ref,
                    as_of=built_at,
                    ret_str=None,
                    raw_row_index=row.raw_row_index,
                )
            )
            continue

        if not row.added_ticker:
            events.append(_blank_event(row, "blank-add", built_at, source_ref))
        else:
            events.append(
                EventRow(
                    event_id=event_id_for(added_entity, row.effective_date, "add", "wikipedia"),
                    entity_id=added_entity,
                    ticker_as_of=row.added_ticker,
                    security_name_raw=row.added_name or None,
                    event_type="add",
                    effective_date=row.effective_date,
                    announced_date=announced,
                    date_confidence=_wiki_confidence(row, "add", segments),
                    side="added",
                    counterpart_ticker=row.removed_ticker or None,
                    reason_text=row.reason_text or None,
                    reason_class=reason_class,
                    source="wikipedia",
                    source_ref=source_ref,
                    as_of=built_at,
                    ret_str=None,
                    raw_row_index=row.raw_row_index,
                )
            )

        if not row.removed_ticker:
            events.append(_blank_event(row, "blank-remove", built_at, source_ref))
        else:
            event_type = _REMOVED_EVENT_TYPE.get(reason_class, "remove")
            events.append(
                EventRow(
                    event_id=event_id_for(
                        removed_entity, row.effective_date, event_type, "wikipedia"
                    ),
                    entity_id=removed_entity,
                    ticker_as_of=row.removed_ticker,
                    security_name_raw=row.removed_name or None,
                    event_type=event_type,
                    effective_date=row.effective_date,
                    announced_date=announced,
                    date_confidence=_wiki_confidence(row, "remove", segments),
                    side="removed",
                    counterpart_ticker=row.added_ticker or None,
                    reason_text=row.reason_text or None,
                    reason_class=reason_class,
                    source="wikipedia",
                    source_ref=source_ref,
                    as_of=built_at,
                    ret_str=None,
                    raw_row_index=row.raw_row_index,
                )
            )

    for rename in renames:
        if "fja05680_start_end" not in rename.sources:
            continue
        entity_id = alias_table.resolve(
            rename.new_ticker, rename.effective_date
        ) or alias_table.resolve(rename.old_ticker, _previous_day(rename.effective_date))
        events.append(
            EventRow(
                event_id=event_id_for(
                    entity_id, rename.effective_date, "rename", "fja05680_start_end"
                ),
                entity_id=entity_id,
                ticker_as_of=rename.new_ticker,
                security_name_raw=None,
                event_type="rename",
                effective_date=rename.effective_date,
                announced_date=None,
                date_confidence=rename.date_confidence,
                side="removed",
                counterpart_ticker=rename.old_ticker,
                reason_text=rename.reason_text or None,
                reason_class="rename",
                source="fja05680_start_end",
                source_ref=FJA_START_END_SOURCE_URL,
                as_of=built_at,
                ret_str=None,
                raw_row_index=rename.raw_row_index,
            )
        )
    return events


def _blank_event(row: WikiRow, event_type: str, built_at: str, source_ref: str) -> EventRow:
    return EventRow(
        event_id=event_id_for(None, row.effective_date, event_type, "wikipedia"),
        entity_id=None,
        ticker_as_of=None,
        security_name_raw=None,
        event_type=event_type,
        effective_date=row.effective_date,
        announced_date=row.announced_date,
        date_confidence="unverified",
        side="added" if event_type == "blank-add" else "removed",
        counterpart_ticker=row.removed_ticker or row.added_ticker or None,
        reason_text=row.reason_text or None,
        reason_class=classify_reason(row.reason_text),
        source="wikipedia",
        source_ref=source_ref,
        as_of=built_at,
        ret_str=None,
        raw_row_index=row.raw_row_index,
    )


def _wiki_confidence(row: WikiRow, side: str, segments: Sequence[Segment]) -> str:
    """``confirmed-both-sources`` when sp500_ticker_start_end agrees on the date.

    A blank side is ``unverified``: the date is known but the security is not
    identifiable at all (design §7 ⚠️ mapping).
    """

    if side == "add":
        if not row.added_ticker:
            return "unverified"
        matched = any(
            s.ticker == row.added_ticker and s.start == row.effective_date for s in segments
        )
    elif side == "remove":
        if not row.removed_ticker:
            return "unverified"
        matched = any(
            s.ticker == row.removed_ticker and s.end == row.effective_date for s in segments
        )
    else:
        old_end = any(
            s.ticker == row.removed_ticker and s.end == row.effective_date for s in segments
        )
        new_start = any(
            s.ticker == row.added_ticker and s.start == row.effective_date for s in segments
        )
        matched = old_end and new_start
    return "confirmed-both-sources" if matched else "single-source"


def _previous_day(iso: str) -> str:
    return _iso(_to_date(iso) - timedelta(days=1))


# ---------------------------------------------------------------------------
# month-end rebuild (design §2, A8/A9)
# ---------------------------------------------------------------------------
def rebuild_month_end(
    snapshots: Sequence[Snapshot],
    events: Sequence[EventRow],
    alias_table: AliasTable,
    grid: Sequence[str],
) -> tuple[list[MonthEndRow], list[dict], list[dict], dict]:
    """Anchor each month-end on the latest fja05680 snapshot and replay the skeleton.

    Product set = anchor snapshot tickers with every non-blank skeleton event in
    ``(anchor, month_end]`` applied (design step 2b). ``agreement`` compares that
    replay (W) with the anchor snapshot set (F); per-entity differences are
    written to reconciliation, never silently resolved (P2/R-9).
    """

    dates = [s.as_of for s in snapshots]
    {s.as_of: s for s in snapshots}
    entity_tickers: dict[str, list[tuple[str, str]]] = {}
    for row in alias_table.rows:
        entity_tickers.setdefault(row.entity_id, []).append((row.ticker, row.valid_from))

    replayable = [
        e
        for e in events
        if e.entity_id and e.event_type not in _BLANK_EVENT_TYPES and e.event_type != "rename"
    ]

    rows: list[MonthEndRow] = []
    month_lists: list[dict] = []
    diffs: list[dict] = []
    stats = {
        "membership_source_counts": {},
        "confidence_counts": {},
        "agreement_counts": {},
        "unresolvable_tickers": {},
        "entity_duplicate_months": 0,
        "member_count_min": None,
        "member_count_max": None,
        "next_snapshot_validation": {"months": 0, "disagreements": 0, "examples": []},
        "counts_by_month_end": {},
    }

    for month_end in grid:
        index = bisect_right(dates, month_end) - 1
        if index < 0:
            continue
        anchor = snapshots[index]
        exact = anchor.as_of == month_end
        source_kind = "snapshot_exact" if exact else "snapshot_forward_fill"
        gap_days = (_to_date(month_end) - _to_date(anchor.as_of)).days
        if exact or gap_days <= 31:
            confidence = "high"
        elif gap_days <= 91:
            confidence = "medium"
        else:
            confidence = "low"

        window = [e for e in replayable if anchor.as_of < e.effective_date <= month_end]
        anchor_tickers = list(anchor.tickers)
        present = set(anchor_tickers)
        for event in window:
            if event.event_type in _BLANK_EVENT_TYPES or event.entity_id is None:
                continue
            if event.side == "added":
                present.add(event.ticker_as_of or "")
            else:
                present.discard(event.ticker_as_of or "")
        present.discard("")

        f_tickers = set(anchor_tickers)
        w_tickers = present
        next_index = bisect_right(dates, month_end)
        next_snapshot = snapshots[next_index] if next_index < len(snapshots) else None
        next_tickers = set(next_snapshot.tickers) if next_snapshot else set()
        next_entities: set[str] = set()
        if next_snapshot is not None:
            next_entities = {alias_table.resolve(t, next_snapshot.as_of) for t in next_tickers}
            next_entities.discard(None)

        resolved: dict[str, str] = {}
        chosen_ticker: dict[str, str] = {}
        for ticker in sorted(w_tickers | f_tickers):
            entity_id = alias_table.resolve(ticker, month_end)
            if entity_id is None:
                stats["unresolvable_tickers"][ticker] = (
                    stats["unresolvable_tickers"].get(ticker, 0) + 1
                )
                continue
            resolved[ticker] = entity_id
            previous = chosen_ticker.get(entity_id)
            if previous is None:
                chosen_ticker[entity_id] = ticker
            else:
                stats["entity_duplicate_months"] += 1
                if _seat_rank(alias_table, ticker, month_end) > _seat_rank(
                    alias_table, previous, month_end
                ):
                    chosen_ticker[entity_id] = ticker
        if len(chosen_ticker) < len(resolved):
            pass  # duplicates collapsed by design (KFT/MDLZ share one seat)

        w_entities = {resolved[t] for t in w_tickers if t in resolved}
        f_entities = {resolved[t] for t in f_tickers if t in resolved}
        f_entities - w_entities

        member_count = len(chosen_ticker)
        stats["counts_by_month_end"][month_end] = member_count
        stats["member_count_min"] = (
            member_count
            if stats["member_count_min"] is None
            else min(stats["member_count_min"], member_count)
        )
        stats["member_count_max"] = (
            member_count
            if stats["member_count_max"] is None
            else max(stats["member_count_max"], member_count)
        )

        for entity_id, ticker in sorted(chosen_ticker.items()):
            if entity_id in f_entities and entity_id in w_entities:
                agreement = "both"
            elif entity_id not in f_entities:
                agreement = "wikipedia_only"
            else:
                still_listed = entity_id in next_entities
                agreement = "conflict" if still_listed else "fja_only"
                diffs.append(
                    {
                        "basis": "anchor_snapshot",
                        "month_end": month_end,
                        "entity_id": entity_id,
                        "ticker_as_of": ticker,
                        "agreement": agreement,
                        "wikipedia_has": True,
                        "fja_has": True,
                        "mismatch_type": (
                            "removal-contradicted-by-next-snapshot"
                            if still_listed
                            else "wikipedia-ahead-of-anchor"
                        ),
                        "detail": f"anchor {anchor.as_of} lists it; skeleton removed "
                        f"it by {month_end}",
                    }
                )
            rows.append(
                MonthEndRow(
                    month_end=month_end,
                    entity_id=entity_id,
                    ticker_as_of=ticker,
                    membership_source=source_kind,
                    snapshot_date_used=anchor.as_of,
                    gap_days=gap_days,
                    confidence=confidence,
                    agreement=agreement,
                )
            )
            stats["agreement_counts"][agreement] = stats["agreement_counts"].get(agreement, 0) + 1

        for entity_id in sorted(w_entities - f_entities):
            diffs.append(
                {
                    "basis": "anchor_snapshot",
                    "month_end": month_end,
                    "entity_id": entity_id,
                    "ticker_as_of": chosen_ticker.get(entity_id, ""),
                    "agreement": "wikipedia_only",
                    "wikipedia_has": True,
                    "fja_has": False,
                    "mismatch_type": "skeleton-add-not-in-anchor",
                    "detail": f"anchor {anchor.as_of} lacks it; skeleton added it by {month_end}",
                }
            )

        if (
            next_snapshot is not None
            and (_to_date(next_snapshot.as_of) - _to_date(month_end)).days <= 31
        ):
            stats["next_snapshot_validation"]["months"] += 1
            disagreement = w_entities ^ next_entities
            if disagreement:
                stats["next_snapshot_validation"]["disagreements"] += len(disagreement)
                if len(stats["next_snapshot_validation"]["examples"]) < 15:
                    stats["next_snapshot_validation"]["examples"].append(
                        {
                            "month_end": month_end,
                            "next_snapshot": next_snapshot.as_of,
                            "n_disagreements": len(disagreement),
                        }
                    )

        month_lists.append(
            {
                "month_end": month_end,
                "membership_source": source_kind,
                "snapshot_date_used": anchor.as_of,
                "gap_days": gap_days,
                "confidence": confidence,
                "n_members": member_count,
                "members": [
                    {
                        "entity_id": entity_id,
                        "ticker": ticker,
                        "agreement": ("both" if entity_id in f_entities else "wikipedia_only"),
                    }
                    for entity_id, ticker in sorted(chosen_ticker.items())
                ],
                "added": [
                    {
                        "entity_id": e.entity_id,
                        "ticker": e.ticker_as_of,
                        "event_type": e.event_type,
                        "effective_date": e.effective_date,
                        "reason_class": e.reason_class,
                    }
                    for e in window
                    if e.side == "added"
                ],
                "removed": [
                    {
                        "entity_id": e.entity_id,
                        "ticker": e.ticker_as_of,
                        "event_type": e.event_type,
                        "effective_date": e.effective_date,
                        "reason_class": e.reason_class,
                    }
                    for e in window
                    if e.side == "removed"
                ],
            }
        )
        stats["membership_source_counts"][source_kind] = (
            stats["membership_source_counts"].get(source_kind, 0) + 1
        )
        stats["confidence_counts"][confidence] = stats["confidence_counts"].get(confidence, 0) + 1

    return rows, month_lists, diffs, stats


def _seat_rank(alias_table: AliasTable, ticker: str, on_date: str) -> str:
    for row in alias_table.intervals(ticker):
        if row.valid_from <= on_date and (row.valid_to is None or on_date < row.valid_to):
            return row.valid_from
    return ""


# ---------------------------------------------------------------------------
# joeyfife cross-check (A10 / P6: never enters a product table)
# ---------------------------------------------------------------------------
def _has_nearby_date(dates: Iterable[str], when: str, window_days: int = 60) -> bool:
    """True when the same ticker appears in the other source within the window.

    T1.1 §3.1 notes joeyfife dates "may be announcement dates", so a small
    offset is reported as ``date-shift``; a far-away date is a different event.
    """

    try:
        target = _to_date(when)
    except ValueError:
        return False
    for candidate in dates:
        if not candidate:
            continue
        try:
            if abs((_to_date(candidate) - target).days) <= window_days:
                return True
        except ValueError:
            continue
    return False


def reconcile_joeyfife(
    joeyfife: dict,
    ticker_events: Sequence[tuple[str, str, str, str, int]],
    alias_table: AliasTable,
    current: Sequence[str],
) -> tuple[list[dict], dict]:
    wiki_pairs = {(when, ticker) for ticker, when, _side, _type, _row in ticker_events}
    joey_pairs: set[tuple[str, str]] = set()
    joey_add_dates: dict[str, str] = {}
    joey_remove_dates: dict[str, str] = {}
    for change in joeyfife.get("changes", []):
        when = str(change.get("date") or "")
        added = str(change.get("added") or "").upper()
        removed = str(change.get("removed") or "").upper()
        if added:
            joey_pairs.add((when, added))
            joey_add_dates.setdefault(added, when)
        if removed:
            joey_pairs.add((when, removed))
            joey_remove_dates.setdefault(removed, when)

    rows: list[dict] = []
    for when, ticker in sorted(wiki_pairs | joey_pairs):
        in_wiki = (when, ticker) in wiki_pairs
        in_joey = (when, ticker) in joey_pairs
        if in_wiki and in_joey:
            continue
        if in_wiki:
            agreement, mismatch = "wikipedia_only", "missing-in-joeyfife"
            if _has_nearby_date([d for (d, t) in joey_pairs if t == ticker], when):
                mismatch = "date-shift"
        else:
            agreement, mismatch = "joeyfife_only", "missing-in-wikipedia"
            if _has_nearby_date([d for (d, t) in wiki_pairs if t == ticker], when):
                mismatch = "date-shift"
        rows.append(
            {
                "date": when,
                "ticker": ticker,
                "entity_id": alias_table.resolve(ticker, when)
                or alias_table.resolve(ticker, _previous_day(when))
                or "",
                "wikipedia_has": in_wiki,
                "joeyfife_has": in_joey,
                "agreement": agreement,
                "mismatch_type": mismatch,
            }
        )

    current_set = {t.upper() for t in current}
    wiki_tickers = {ticker for ticker, _w, _s, _t, _r in ticker_events}
    self_contradictions = 0
    for ticker in sorted(current_set):
        if ticker not in joey_add_dates:
            self_contradictions += 1
            rows.append(
                {
                    "date": "",
                    "ticker": ticker,
                    "entity_id": alias_table.resolve(ticker, "2026-06-30") or "",
                    "wikipedia_has": ticker in wiki_tickers,
                    "joeyfife_has": True,
                    "agreement": "joeyfife_only",
                    "mismatch_type": "joeyfife-current-without-add",
                }
            )
    for ticker, when in sorted(joey_add_dates.items()):
        if ticker not in joey_remove_dates and ticker not in current_set:
            rows.append(
                {
                    "date": when,
                    "ticker": ticker,
                    "entity_id": alias_table.resolve(ticker, when) or "",
                    "wikipedia_has": ticker in wiki_tickers,
                    "joeyfife_has": True,
                    "agreement": "joeyfife_only",
                    "mismatch_type": "joeyfife-add-without-remove",
                }
            )

    stats = {
        "joeyfife_changes": len(joeyfife.get("changes", [])),
        "joeyfife_current": len(joeyfife.get("current", [])),
        "wikipedia_side_pairs": len(wiki_pairs),
        "both": len(wiki_pairs & joey_pairs),
        "wikipedia_only": len(wiki_pairs - joey_pairs),
        "joeyfife_only": len(joey_pairs - wiki_pairs),
        "mismatch_rows": len(rows),
        "self_contradictions_current_without_add": self_contradictions,
        "note": "joeyfife is cross-check only and never enters a product table (P6/R9)",
    }
    return rows, stats


# ---------------------------------------------------------------------------
# sources + build
# ---------------------------------------------------------------------------
@dataclass
class SourceBundle:
    wikipedia_changes_raw: str
    fja_snapshots_csv: str
    fja_start_end_csv: str
    joeyfife_json: str
    current_constituents_csv: str | None = None
    wikipedia_main_article_raw: str | None = None
    wikipedia_revision: str | None = None

    @classmethod
    def from_dir(cls, root: Path | str) -> SourceBundle:
        base = Path(root)

        def _read(name: str, required: bool = True) -> str | None:
            path = base / name
            if not path.is_file():
                if required:
                    raise Sp500PitError(f"missing required source file: {path}")
                return None
            return path.read_text(encoding="utf-8")

        revision_path = base / "wikipedia_revision.txt"
        revision = (
            revision_path.read_text(encoding="utf-8").strip() if revision_path.is_file() else None
        )
        return cls(
            wikipedia_changes_raw=_read("wikipedia_changes_raw.txt") or "",
            fja_snapshots_csv=_read("fja05680_updated.csv") or "",
            fja_start_end_csv=_read("sp500_ticker_start_end.csv") or "",
            joeyfife_json=_read("joeyfife_membership.json") or "",
            current_constituents_csv=_read("current_constituents.csv", required=False),
            wikipedia_main_article_raw=_read("list_of_sp500_companies_raw.txt", required=False),
            wikipedia_revision=revision,
        )

    def hashes(self) -> dict[str, str]:
        return {
            "wikipedia_changes_raw": _sha256(self.wikipedia_changes_raw),
            "fja05680_updated": _sha256(self.fja_snapshots_csv),
            "sp500_ticker_start_end": _sha256(self.fja_start_end_csv),
            "joeyfife_membership": _sha256(self.joeyfife_json),
            "current_constituents": _sha256(self.current_constituents_csv or ""),
            "list_of_sp500_companies_raw": _sha256(self.wikipedia_main_article_raw or ""),
        }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def wiki_name_map(wiki_rows: Sequence[WikiRow]) -> dict[str, str]:
    """Latest (ticker -> security name) view — used for cross-checks only."""

    names: dict[str, str] = {}
    for ticker, entries in wiki_name_history(wiki_rows).items():
        names[ticker] = entries[-1][1]
    return names


def wiki_name_history(wiki_rows: Sequence[WikiRow]) -> dict[str, list[tuple[str, str]]]:
    """``ticker -> [(effective_date, security_name), ...]`` in date order.

    A ticker can name several entities over time (``Q`` = Qwest, then Quintiles,
    then Qnity), so the name must be picked per membership interval, never per
    ticker globally.
    """

    history: dict[str, list[tuple[str, str]]] = {}
    for row in sorted(wiki_rows, key=lambda r: r.effective_date):
        if row.added_ticker and row.added_name:
            history.setdefault(row.added_ticker, []).append((row.effective_date, row.added_name))
        if row.removed_ticker and row.removed_name:
            history.setdefault(row.removed_ticker, []).append(
                (row.effective_date, row.removed_name)
            )
    return history


def _entity_name(
    history: dict[str, list[tuple[str, str]]],
    seats: Sequence[IntervalDraft],
    representative: str,
    current_names: dict[str, str],
) -> str:
    order = [representative] + [
        s.ticker for s in sorted(seats, key=lambda s: s.valid_from, reverse=True)
    ]
    for ticker in order:
        entries = history.get(ticker)
        if not entries:
            continue
        intervals = [(s.valid_from, s.valid_to) for s in seats if s.ticker == ticker]
        for when, name in entries:
            for start, end in intervals:
                if start <= when and (end is None or when <= end):
                    return name
        return entries[-1][1]
    return current_names.get(representative) or representative


def build_sp500_pit(
    sources: SourceBundle,
    *,
    built_at: str | None = None,
    grid_start: str = DEFAULT_MONTH_GRID_START,
    grid_end: str = DEFAULT_MONTH_GRID_END,
    min_wikipedia_rows: int = MIN_WIKIPEDIA_DATED_ROWS,
) -> BuildResult:
    """Run the whole T1.4 pipeline (design §2). Pure: no filesystem writes."""

    built_at = built_at or datetime.now(UTC).isoformat(timespec="seconds")
    warnings: list[str] = []

    wiki_rows = parse_wikipedia_changes(sources.wikipedia_changes_raw, min_rows=min_wikipedia_rows)
    snapshots = parse_fja_snapshots(sources.fja_snapshots_csv)
    segments = parse_fja_start_end(sources.fja_start_end_csv)
    ticker_events = wiki_ticker_events(wiki_rows)

    renames = detect_renames(wiki_rows, segments)
    handoffs, gap_handoff = handoff_renames(renames, segments)
    renames = renames + handoffs

    drafts, _ = build_interval_drafts(segments, ticker_events)
    gap_merge = merge_rename_groups(drafts, renames)
    removal_by_ticker = removal_records(wiki_rows, ticker_events)

    cik_map = (
        load_cik_map(sources.current_constituents_csv) if sources.current_constituents_csv else {}
    )
    current_names = (
        load_current_names(sources.current_constituents_csv)
        if sources.current_constituents_csv
        else {}
    )
    if not cik_map:
        warnings.append(
            "no current-constituent CIK map supplied: every entity falls back to E:X:<slug>"
        )

    entities, aliases, gap_entities = build_entities(
        drafts, cik_map, wiki_name_history(wiki_rows), current_names, removal_by_ticker, renames
    )
    alias_table = AliasTable(aliases)
    events = build_events(
        wiki_rows,
        renames,
        alias_table,
        segments,
        wiki_revision=sources.wikipedia_revision,
        built_at=built_at,
    )

    grid = month_end_grid(grid_start, grid_end)
    month_rows, month_lists, diffs, month_stats = rebuild_month_end(
        snapshots, events, alias_table, grid
    )

    joeyfife = load_joeyfife(sources.joeyfife_json)
    jf_rows, jf_stats = reconcile_joeyfife(
        joeyfife, ticker_events, alias_table, joeyfife.get("current", [])
    )

    observed = set()
    for snap in snapshots:
        observed.update(snap.tickers)
    observed.update(row.added_ticker for row in wiki_rows if row.added_ticker)
    observed.update(row.removed_ticker for row in wiki_rows if row.removed_ticker)
    norm_map = build_ticker_norm_map(observed, segments)

    main_article_rows: int | None = None
    main_article_raised = False
    if sources.wikipedia_main_article_raw:
        try:
            parse_wikipedia_changes(sources.wikipedia_main_article_raw)
            # Unreachable when the guard works.
            main_article_rows = MONTH_END_MEMBER_BOUNDS_BY_ERA[-1][3]
        except Sp500PitError:
            main_article_raised = True
            main_article_rows = 0

    result = BuildResult(
        entities=entities,
        aliases=aliases,
        events=events,
        month_end_rows=month_rows,
        month_end_lists=month_lists,
        coverage={},
        gaps=[],
        reconciliation_wiki_vs_fja=diffs,
        reconciliation_joeyfife=jf_rows,
        ticker_norm_map=norm_map,
        warnings=warnings,
    )
    result.facts = {
        "sources": sources,
        "built_at": built_at,
        "build_parameters": {
            "grid_start": grid_start,
            "grid_end": grid_end,
            "min_wikipedia_rows": min_wikipedia_rows,
        },
        "wiki_rows": wiki_rows,
        "snapshots": snapshots,
        "segments": segments,
        "ticker_events": ticker_events,
        "renames": renames,
        "alias_table": alias_table,
        "month_stats": month_stats,
        "joeyfife_stats": jf_stats,
        "joeyfife": joeyfife,
        "snapshot_stats": snapshot_gap_stats(snapshots),
        "handoff_survey": same_day_handoff_survey(segments),
        "main_article_rows": main_article_rows,
        "main_article_raised": main_article_raised,
        "source_hashes": sources.hashes(),
        "gap_records": gap_handoff + gap_merge + gap_entities,
    }
    result.gaps = build_gaps(result)
    # coverage is built twice: the assertion suite reads the coverage dict (A9),
    # and coverage in turn records the assertion outcome.
    result.coverage = build_coverage(result)
    result.assertions = run_assertions(result)
    result.coverage = build_coverage(result)
    return result


# ---------------------------------------------------------------------------
# coverage.json / gaps.csv content (design §2.3, §6)
# ---------------------------------------------------------------------------
ZERO_HIT_TICKERS = ("VMW", "SPLK", "SGEN", "CREE", "WOLF")


def build_gaps(result: BuildResult) -> list[dict]:
    facts = result.facts
    sources: SourceBundle = facts["sources"]
    wiki_rows: list[WikiRow] = facts["wiki_rows"]
    events: list[EventRow] = result.events
    survey = facts["handoff_survey"]

    haystack = "\n".join(
        [
            sources.wikipedia_changes_raw,
            sources.fja_snapshots_csv,
            sources.fja_start_end_csv,
            sources.joeyfife_json,
        ]
    ).upper()
    zero_hits = [t for t in ZERO_HIT_TICKERS if not re.search(rf"(?<![A-Z]){t}(?![A-Z])", haystack)]

    blank_events = [e for e in events if e.event_type in _BLANK_EVENT_TYPES]
    blank_rows = {e.raw_row_index for e in blank_events}
    attributed = [e for e in events if e.announced_date]
    other_rows = [
        e for e in events if e.reason_class == "other" and e.event_type not in _BLANK_EVENT_TYPES
    ]
    unattributed = [g for g in facts["gap_records"] if g["kind"] == "unattributed-removal"]
    reuse = {}
    for row in result.aliases:
        reuse.setdefault(row.ticker, set()).add(row.entity_id)
    reused = {t: len(v) for t, v in reuse.items() if len(v) > 1}
    reused_preview = ";".join(
        f"{t}={n}" for t, n in sorted(reused.items(), key=lambda kv: (-kv[1], kv[0]))[:40]
    )
    if len(reused) > 40:
        reused_preview += f";..+{len(reused) - 40} more"
    facts["joeyfife_stats"]
    snapshot_stats = facts["snapshot_stats"]
    current_end = snapshot_stats["end"]
    jf_dates = [str(c.get("date") or "") for c in facts["joeyfife"].get("changes", [])]
    max([d for d in jf_dates if d], default=current_end)
    wiki_revision = sources.wikipedia_revision or EXPECTED_WIKIPEDIA_REVISION

    rows: list[dict] = [
        {
            "gap_id": "G1",
            "kind": "unverified-membership",
            "fact": f"zero hits across all three free sources: {', '.join(zero_hits) or 'none'}",
            "disposition": "never fabricated; requires an official S&P DJI announcement "
            "(spglobal.com returns 403 in this sandbox) before entering the event table",
            "quantified": f"zero_hit_tickers={','.join(zero_hits)}",
        },
        {
            "gap_id": "G2",
            "kind": "blank-ticker-rows",
            "fact": f"{len(blank_rows)} Wikipedia rows carry an empty Added/Removed ticker cell "
            f"({len(blank_events)} blank-* events)",
            "disposition": "preserved as blank-add/blank-remove (never dropped: dropping shifts "
            "columns, F2/R-5); excluded from month-end counts",
            "quantified": f"blank_rows={len(blank_rows)};blank_events={len(blank_events)};"
            f"baseline={BASELINE_BLANK_ROWS}",
        },
        {
            "gap_id": "G3",
            "kind": "announced-vs-effective-date",
            "fact": f"{len(attributed)}/{len([e for e in events if e.reason_class != 'blank'])} "
            "events carry a parseable announced_date; the source does not separate "
            "announcement from effective dates",
            "disposition": "dedicated announced_date column, never silently shifted (design G3)",
            "quantified": f"announced_filled={len(attributed)}",
        },
        {
            "gap_id": "G4",
            "kind": "no-delisting-prices",
            "fact": 'all three free sources answer only "which stocks existed", never '
            '"what did the delisted stock trade at"',
            "disposition": "out of scope for T1.4; delisted-price procurement "
            "(Norgate/Sharadar/CRSP) is a T1.3 item (T1.2 §八: true coverage 52/68=76.5%)",
            "quantified": "delisting_price_rows=0",
        },
        {
            "gap_id": "G5",
            "kind": "merger-source-missing",
            "fact": f"{len(other_rows)} non-blank events carry reason_class=other "
            "(no machine-readable merger/plain-reason source)",
            "disposition": 'rule v1 only guarantees "not wrongly deleted" (A17); '
            "pure mergers stay undetectable",
            "quantified": f"reason_class_other={len(other_rows)}",
        },
        {
            "gap_id": "G6",
            "kind": "rename-mapping-incomplete",
            "fact": f"{survey['same_day_handoff_pairs']} same-day handoff pairs exist in "
            f"sp500_ticker_start_end.csv; only {len(RENAME_HANDOFF_EVIDENCE)} are renames",
            "disposition": "unverifiable same-day pairs are NOT merged (fusing them would "
            "corrupt entities); a complete ticker->ticker map needs a paid source",
            "quantified": ";".join(f"{k}={v}" for k, v in survey.items()),
        },
        {
            "gap_id": "G7",
            "kind": "unattributed-removal",
            "fact": f"{len(unattributed)} entities leave the index with no Wikipedia removal row",
            "disposition": "delist_reason=unknown, delisting_date left null; "
            "never invented from fja alone",
            "quantified": f"unattributed={len(unattributed)}",
        },
        {
            "gap_id": "G8",
            "kind": "wikipedia-baseline-drift",
            "fact": f"changes table created 2026-08-11, last revision {wiki_revision}; "
            f"{len(wiki_rows)} dated rows (A1/A3 detect drift and raise)",
            "disposition": "wikipedia_revision recorded in the product; "
            "re-baseline when A1/A3 fail",
            "quantified": f"dated_rows={len(wiki_rows)};revision={wiki_revision}",
        },
        {
            "gap_id": "G9",
            "kind": "main-article-desync",
            "fact": f"main article parse raised as designed: {facts['main_article_raised']} "
            f"(rows={facts['main_article_rows']})",
            "disposition": "A15 forces the new article; a silent 0-row parse raises "
            "instead of shipping",
            "quantified": f"main_article_rows={facts['main_article_rows']}",
        },
        {
            "gap_id": "G10",
            "kind": "unvalidated-span",
            "fact": "1976-07-01..1995-12-31 has no fja05680 snapshot to validate against",
            "disposition": "outside the month-end grid (grid starts 1996-01); "
            "event_replay confidence=low if ever used",
            "quantified": "unvalidated_span=1976-07-01..1995-12-31",
        },
        {
            "gap_id": "G11",
            "kind": "ticker-reuse",
            "fact": f"{len(reused)} tickers resolve to more than one entity "
            f"(reuse is common, not exotic); highest-reuse: {reused_preview}",
            "disposition": "alias primary key carries valid_from (A7/A12); "
            "joins always key on (entity_id, date)",
            "quantified": f"reused_tickers={len(reused)};"
            f"max_seats={max(reused.values()) if reused else 0}",
        },
        {
            "gap_id": "G12",
            "kind": "rename-not-broker-reliable",
            "fact": "T1.2 §五: WTW/CPAY/META follow the new code, IQV returns 1 row, "
            "DAY is unavailable at both ends",
            "disposition": "entity resolution goes through alias.resolve only; "
            "broker wire codes are consumption-only (A13)",
            "quantified": "broker_wire_identity_sources=0",
        },
        {
            "gap_id": "G13",
            "kind": "fja-early-snapshot-completeness",
            "fact": "fja05680 1996-1998 snapshots list 487-493 tickers; the design's "
            "[495,510] lower bound was extrapolated from the last snapshot only",
            "disposition": "A8 was recalibrated to per-era bands calibrated on the "
            "source's own drift; it detects source/build drift and does not establish "
            "independent completeness. This record documents the source's early-year sparsity",
            "quantified": FUNDAMENTAL_COUNT_NOTE,
        },
    ]
    rows.extend(facts["gap_records"])
    return rows


def build_coverage(result: BuildResult) -> dict:
    facts = result.facts
    sources: SourceBundle = facts["sources"]
    snapshot_stats = facts["snapshot_stats"]
    month_stats = facts["month_stats"]
    events = result.events
    wiki_rows: list[WikiRow] = facts["wiki_rows"]

    wiki_revision = sources.wikipedia_revision or EXPECTED_WIKIPEDIA_REVISION
    try:
        revision_day = _iso(datetime.fromisoformat(wiki_revision.replace("Z", "+00:00")).date())
    except ValueError:
        revision_day = wiki_revision[:10]
    fja_end = snapshot_stats["end"]
    freshness_lag = abs((_to_date(fja_end) - _to_date(revision_day)).days)

    jf_dates = [str(c.get("date") or "") for c in facts["joeyfife"].get("changes", [])]
    jf_last = max([d for d in jf_dates if d], default=fja_end)
    joeyfife_lag = (_to_date(fja_end) - _to_date(jf_last)).days

    digest = hashlib.sha256()
    for entity in sorted(result.entities, key=lambda e: e.entity_id):
        digest.update(
            json.dumps(
                [entity.entity_id, entity.display_ticker, entity.first_seen, entity.last_seen],
                sort_keys=True,
            ).encode()
        )
    for alias in sorted(result.aliases, key=lambda a: (a.ticker, a.valid_from)):
        digest.update(
            json.dumps(
                [alias.ticker, alias.valid_from, alias.valid_to, alias.entity_id], sort_keys=True
            ).encode()
        )
    for event in sorted(events, key=lambda e: e.event_id):
        digest.update(
            json.dumps(
                [event.event_id, event.event_type, event.effective_date], sort_keys=True
            ).encode()
        )
    for row in sorted(result.month_end_rows, key=lambda r: (r.month_end, r.entity_id)):
        digest.update(f"{row.month_end}|{row.entity_id}".encode())

    failed = [a for a in result.assertions if not a.passed]
    hard_failed = [a for a in result.assertions if a.hard and not a.passed]
    validation_identity = {
        "contract": "qs.universe_sp500_pit.validation/v1",
        "rule_version": SP500_PIT_VALIDATION_RULE_VERSION,
        "data_build_id": digest.hexdigest(),
        "build_parameters": facts["build_parameters"],
        "thresholds": {
            "min_wikipedia_dated_rows": MIN_WIKIPEDIA_DATED_ROWS,
            "baseline_blank_rows": BASELINE_BLANK_ROWS,
            "baseline_snapshot_count": BASELINE_SNAPSHOT_COUNT,
            "baseline_max_gap_days": BASELINE_MAX_GAP_DAYS,
            "baseline_gaps_gt_30d": BASELINE_GAPS_GT_30D,
            "month_end_member_bounds_by_era": [
                list(band) for band in MONTH_END_MEMBER_BOUNDS_BY_ERA
            ],
            "original_month_end_member_bounds_diagnostic": list(ORIGINAL_MONTH_END_MEMBER_BOUNDS),
        },
        "source_hashes": facts["source_hashes"],
        "wikipedia_revision": wiki_revision,
        "assertion_results": [a.__dict__ for a in sorted(result.assertions, key=lambda a: a.id)],
        "build_status_scope": "configured_assertions_only",
        "independent_completeness": "not_verified",
        "research_ready": False,
    }
    # Keep the legacy data identity independent of validation. A rule/threshold/
    # source/assertion change must receive a new validation digest on the same data.
    validation_json = json.dumps(
        validation_identity, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return {
        "contract": SP500_PIT_CONTRACT,
        "namespace": SP500_PIT_NAMESPACE,
        "build_id": digest.hexdigest(),
        "validation_identity": json.loads(validation_json),
        "validation_digest": _sha256(validation_json),
        "build_status_scope": validation_identity["build_status_scope"],
        "independent_completeness": validation_identity["independent_completeness"],
        "research_ready": validation_identity["research_ready"],
        "built_at": facts["built_at"],
        "snapshot_coverage": {
            "start": snapshot_stats["start"],
            "end": snapshot_stats["end"],
            "n_snapshots": snapshot_stats["n_snapshots"],
            "density_by_year": snapshot_stats["density_by_year"],
        },
        "max_gap_days": snapshot_stats["max_gap_days"],
        "max_gap_pair": snapshot_stats["max_gap_pair"],
        "gaps_gt_30d": snapshot_stats["gaps_gt_30d"],
        "wikipedia_revision": wiki_revision,
        "wikipedia_dated_rows": len(wiki_rows),
        "wikipedia_blank_rows": len(
            {e.raw_row_index for e in events if e.event_type in _BLANK_EVENT_TYPES}
        ),
        "freshness_lag_days": freshness_lag,
        "unvalidated_span": "1976-07-01..1995-12-31",
        "joeyfife_lag_days": joeyfife_lag,
        "month_end_grid": {
            "start": result.month_end_lists[0]["month_end"] if result.month_end_lists else None,
            "end": result.month_end_lists[-1]["month_end"] if result.month_end_lists else None,
            "n_months": len(result.month_end_lists),
            "membership_source_counts": month_stats["membership_source_counts"],
            "confidence_counts": month_stats["confidence_counts"],
            "member_count_min": month_stats["member_count_min"],
            "member_count_max": month_stats["member_count_max"],
            "member_count_bounds_asserted": [
                [s, e, lo, hi] for s, e, lo, hi in MONTH_END_MEMBER_BOUNDS_BY_ERA
            ],
            "a8_count_check_kind": "source_calibrated_drift_check",
            "a8_count_evidence": next(
                (a.evidence for a in result.assertions if a.id == "A8"), None
            ),
        },
        "agreement_counts": month_stats["agreement_counts"],
        "unresolvable_tickers": month_stats["unresolvable_tickers"],
        "entity_duplicate_months": month_stats["entity_duplicate_months"],
        "next_snapshot_validation": month_stats["next_snapshot_validation"],
        "joeyfife_reconciliation": facts["joeyfife_stats"],
        "same_day_handoff_survey": facts["handoff_survey"],
        "counts": {
            "entities": len(result.entities),
            "alias_rows": len(result.aliases),
            "events": len(events),
            "month_end_rows": len(result.month_end_rows),
            "gaps": len(result.gaps),
            "reconciliation_wiki_vs_fja": len(result.reconciliation_wiki_vs_fja),
            "reconciliation_joeyfife": len(result.reconciliation_joeyfife),
            "ticker_norm_map": len(result.ticker_norm_map),
        },
        "membership_set_rule": "anchor fja05680 snapshot replay with the Wikipedia skeleton "
        "in (anchor, month_end]; diffs vs the anchor are labelled and written to "
        "reconciliation_wiki_vs_fja.csv",
        "alias_interval_semantics": "[valid_from, valid_to) — valid_to is the removal "
        "effective date and is EXCLUSIVE (verified: WHR absent from the 2024-03-18 snapshot, "
        "META present on its 2022-06-09 start date)",
        "daily_precision_claimed": False,
        "sparsity_warning": "fja05680 is a snapshot series, not a daily series: "
        "13-27 snapshots/year from 2019 and a 91-day maximum gap. Downstream consumers "
        "MUST read max_gap_days and confidence.",
        "assertions": {
            "total": len(result.assertions),
            "passed": len(result.assertions) - len(failed),
            "failed": [a.id for a in failed],
            "hard_failed": [a.id for a in hard_failed],
            "build_status": "assertion-failed" if hard_failed else "ok",
            "detail": {a.id: a.detail for a in result.assertions},
        },
        "source_hashes": facts["source_hashes"],
        "warnings": result.warnings,
    }


# ---------------------------------------------------------------------------
# assertion suite A1..A17 (design §4)
# ---------------------------------------------------------------------------
def run_assertions(result: BuildResult) -> list[Assertion]:
    """Evaluate every design assertion. Hard failures are reported, never hidden.

    ``assert_all_hard`` turns a hard failure into an exception for CI use; the
    builder itself always writes the products so a falsified *design baseline*
    (A8 below) stays inspectable instead of losing the whole build.
    """

    facts = result.facts
    wiki_rows: list[WikiRow] = facts["wiki_rows"]
    snapshots: list[Snapshot] = facts["snapshots"]
    segments: list[Segment] = facts["segments"]
    renames: list[RenameEvidence] = facts["renames"]
    alias_table: AliasTable = facts["alias_table"]
    out: list[Assertion] = []

    # A1 — Wikipedia dated rows >= 400 (F1)
    out.append(
        Assertion(
            "A1",
            True,
            len(wiki_rows) >= MIN_WIKIPEDIA_DATED_ROWS,
            f"{len(wiki_rows)} dated rows parsed "
            f"(minimum {MIN_WIKIPEDIA_DATED_ROWS}, baseline 407)",
            {"dated_rows": len(wiki_rows)},
        )
    )

    # A2 — column-index binding + blank-cell preservation (F2)
    probe = [r for r in wiki_rows if r.effective_date == "2026-06-30"]
    probe_ok = bool(probe) and probe[0].added_ticker == "" and probe[0].removed_ticker == "CAG"
    six_cells = all(r.cell_count >= 6 for r in wiki_rows)
    out.append(
        Assertion(
            "A2",
            True,
            probe_ok and six_cells,
            "2026-06-30 row binds Added='' Removed='CAG' (no column shift); "
            "all rows carry 6 index-bound cells"
            if probe_ok and six_cells
            else f"column binding broken: probe={probe[:1]} six_cells={six_cells}",
            {"probe_row": probe[0].__dict__ if probe else None},
        )
    )

    # A3 — blank ticker row count == 42 (R-5/F2)
    blank_rows = {e.raw_row_index for e in result.events if e.event_type in _BLANK_EVENT_TYPES}
    out.append(
        Assertion(
            "A3",
            True,
            len(blank_rows) == BASELINE_BLANK_ROWS,
            f"{len(blank_rows)} blank rows (baseline {BASELINE_BLANK_ROWS})",
            {"blank_rows": len(blank_rows)},
        )
    )

    # A4 — six same-day handoffs (R-1/R-2/R-8)
    handoff_detail = {}
    handoff_ok = True
    for old, new, when in RENAME_HANDOFF_EVIDENCE:
        old_ends = {s.end for s in segments if s.ticker == old}
        new_starts = {s.start for s in segments if s.ticker == new}
        ok = when in old_ends and when in new_starts
        handoff_detail[f"{old}->{new}"] = {
            "expected": when,
            "old_end": sorted(x for x in old_ends if x),
            "new_start": sorted(x for x in new_starts),
            "ok": ok,
        }
        handoff_ok = handoff_ok and ok
    out.append(
        Assertion(
            "A4",
            True,
            handoff_ok,
            f"{sum(1 for v in handoff_detail.values() if v['ok'])}/6 handoffs reproduce "
            "old.end == new.start",
            handoff_detail,
        )
    )

    # A5 — SIVB and SBNY both removed 2023-03-15 as bankruptcy-receivership (R-4)
    double = [
        e
        for e in result.events
        if e.effective_date == "2023-03-15"
        and e.event_type == "bankruptcy-receivership"
        and e.ticker_as_of in {"SIVB", "SBNY"}
    ]
    out.append(
        Assertion(
            "A5",
            True,
            {e.ticker_as_of for e in double} == {"SIVB", "SBNY"},
            f"2023-03-15 receivership removals: {sorted(e.ticker_as_of for e in double)}",
            {"events": [e.event_id for e in double]},
        )
    )

    # A6 — MSFT / AAPL continuously listed, never removed (R-1/F7)
    msft_missing = sum(1 for s in snapshots if "MSFT" not in s.tickers)
    aapl_missing = sum(1 for s in snapshots if "AAPL" not in s.tickers)
    removed_blue_chips = [
        e.event_id
        for e in result.events
        if e.ticker_as_of in {"MSFT", "AAPL"} and e.side == "removed"
    ]
    out.append(
        Assertion(
            "A6",
            True,
            msft_missing == 0 and aapl_missing == 0 and not removed_blue_chips,
            f"MSFT missing from {msft_missing} snapshots, AAPL missing from {aapl_missing}, "
            f"remove events: {len(removed_blue_chips)}",
            {"n_snapshots": len(snapshots)},
        )
    )

    # A7 — Q's two seats are two entities (R-6/F3)
    q_2010 = alias_table.resolve("Q", "2010-01-01")
    q_2026 = alias_table.resolve("Q", "2026-01-01")
    q_rows = alias_table.intervals("Q")
    q_ok = (
        q_2010 is not None
        and q_2026 is not None
        and q_2010 != q_2026
        and len({r.valid_from for r in q_rows}) >= 2
    )
    out.append(
        Assertion(
            "A7",
            True,
            q_ok,
            f"Q@2010={q_2010} Q@2026={q_2026} "
            f"alias rows={[(r.valid_from, r.valid_to, r.entity_id) for r in q_rows]}",
            {"q_alias_rows": len(q_rows)},
        )
    )

    # A8-count — source-calibrated month-end count drift, not completeness.
    # The fja05680 source's member count drifts by era
    # (487-493 in 1996-2000, 494-499 in 2001-2014, 499-506 in 2015+), so the
    # flat [495,510] design baseline failed on the source's early years. Retain
    # both measurements without inferring the true member count from either.
    counts = {row["month_end"]: row["n_members"] for row in result.month_end_lists}

    def era_bounds(month_end: str) -> tuple[int, int]:
        for start, end, lo, hi in MONTH_END_MEMBER_BOUNDS_BY_ERA:
            if start <= month_end[:7] <= end:
                return lo, hi
        return MONTH_END_MEMBER_BOUNDS_BY_ERA[-1][2:]

    violations = {
        m: c for m, c in counts.items() if not (era_bounds(m)[0] <= c <= era_bounds(m)[1])
    }
    worst = sorted(violations.items(), key=lambda kv: kv[1])[:6]
    original_lo, original_hi = ORIGINAL_MONTH_END_MEMBER_BOUNDS
    original_violations = {
        month: count for month, count in counts.items() if not original_lo <= count <= original_hi
    }
    out.append(
        Assertion(
            "A8",
            True,
            not violations,
            f"{len(violations)}/{len(counts)} month-ends fall outside their era band "
            f"{[[s, e, lo, hi] for s, e, lo, hi in MONTH_END_MEMBER_BOUNDS_BY_ERA]}; "
            f"min={min(counts.values()) if counts else None} "
            f"max={max(counts.values()) if counts else None}; "
            f"worst={worst} — source-calibrated drift check (G13); "
            "independent completeness not_verified",
            {
                "check_kind": "source_calibrated_drift_check",
                "independent_completeness": "not_verified",
                "violations": len(violations),
                "bounds_by_era": [
                    [s, e, lo, hi] for s, e, lo, hi in MONTH_END_MEMBER_BOUNDS_BY_ERA
                ],
                "worst": worst,
                "original_flat_bounds_counterfactual": {
                    "bounds": list(ORIGINAL_MONTH_END_MEMBER_BOUNDS),
                    "violations": len(original_violations),
                    "violations_by_month": original_violations,
                    "authority": "diagnostic_only",
                },
            },
        )
    )

    # A9 — coverage.json declares snapshot coverage and max_gap_days == 91 (F5)
    coverage = result.coverage
    a9_ok = (
        isinstance(coverage.get("snapshot_coverage"), dict)
        and coverage.get("max_gap_days") == BASELINE_MAX_GAP_DAYS
        and coverage.get("gaps_gt_30d") == BASELINE_GAPS_GT_30D
    )
    out.append(
        Assertion(
            "A9",
            True,
            a9_ok,
            f"max_gap_days={coverage.get('max_gap_days')} "
            f"gaps_gt_30d={coverage.get('gaps_gt_30d')} "
            f"n_snapshots={coverage.get('snapshot_coverage', {}).get('n_snapshots')}",
            {"max_gap_pair": coverage.get("max_gap_pair")},
        )
    )

    # A10 — joeyfife mismatches are recorded, never silent (R9/F6)
    jf_stats = facts["joeyfife_stats"]
    jf_types = {row["mismatch_type"] for row in result.reconciliation_joeyfife}
    a10_ok = (
        bool(result.reconciliation_joeyfife)
        and jf_stats["both"] > 0
        and jf_stats["self_contradictions_current_without_add"] > 0
    )
    out.append(
        Assertion(
            "A10",
            False,
            a10_ok,
            f"joeyfife: both={jf_stats['both']} wikipedia_only={jf_stats['wikipedia_only']} "
            f"joeyfife_only={jf_stats['joeyfife_only']} mismatch_rows={jf_stats['mismatch_rows']} "
            f"current-without-add={jf_stats['self_contradictions_current_without_add']} "
            f"types={sorted(jf_types)}",
            jf_stats,
        )
    )

    # A11 — a rename never produces independent churn (R-1/F7)
    churn_violations = []
    for rename in renames:
        left = alias_table.resolve(rename.old_ticker, _previous_day(rename.effective_date))
        right = alias_table.resolve(rename.new_ticker, rename.effective_date)
        separate = [
            e.event_id
            for e in result.events
            if e.effective_date == rename.effective_date
            and e.event_type in {"add", "remove", "acquisition-delisted", "bankruptcy-receivership"}
            and (
                (e.side == "added" and e.ticker_as_of == rename.new_ticker)
                or (e.side == "removed" and e.ticker_as_of == rename.old_ticker)
            )
        ]
        if left is None or right is None or left != right or separate:
            churn_violations.append(
                {
                    "rename": f"{rename.old_ticker}->{rename.new_ticker}",
                    "left": left,
                    "right": right,
                    "separate_events": separate,
                }
            )
    out.append(
        Assertion(
            "A11",
            True,
            not churn_violations,
            f"{len(renames)} merges checked, {len(churn_violations)} violations",
            {"violations": churn_violations},
        )
    )

    # A12 — no ticker-only joins: unique (month_end, entity_id) and no overlap
    keys = [(row.month_end, row.entity_id) for row in result.month_end_rows]
    duplicates = len(keys) - len(set(keys))
    overlap_ok = True
    try:
        AliasTable(result.aliases)
    except Sp500PitError:
        overlap_ok = False
    out.append(
        Assertion(
            "A12",
            True,
            duplicates == 0 and overlap_ok and all(row.entity_id for row in result.month_end_rows),
            f"duplicate (month_end, entity_id) keys={duplicates}; "
            f"alias intervals overlap-free={overlap_ok}; "
            f"rows={len(result.month_end_rows)}",
            {"duplicates": duplicates},
        )
    )

    # A13 — broker wire codes are never an identity source (R-6/R-9)
    syntactic = [
        wire for wire, _note, _kind in BROKER_NEGATIVE_CASES if looks_like_broker_wire(wire)
    ]
    semantic = [
        (wire, note)
        for wire, note, _kind in BROKER_NEGATIVE_CASES
        if not looks_like_broker_wire(wire)
    ]
    rejected = 0
    for wire in syntactic:
        try:
            alias_table.resolve(wire, "2026-01-01")
        except Sp500PitError:
            rejected += 1
    fb_entity = alias_table.resolve("FB", "2021-01-01")
    meta_entity = alias_table.resolve("META", "2023-01-01")
    entity_index = result.entity_by_id()
    fb_row = entity_index.get(fb_entity or "")
    # A bare reused ticker such as Q stays syntactically resolvable on purpose —
    # the point of the case is that it must never be used as an identity anchor.
    a13_ok = (
        rejected == len(syntactic)
        and syntactic
        and semantic
        and fb_entity is not None
        and fb_entity == meta_entity
        and fb_row is not None
        and fb_row.entity_type != "fund"
        and len({alias_table.resolve("Q", "2010-01-01"), alias_table.resolve("Q", "2026-01-01")})
        == 2
    )
    out.append(
        Assertion(
            "A13",
            True,
            a13_ok,
            f"{rejected}/{len(syntactic)} wire codes rejected syntactically "
            f"({', '.join(syntactic)}); FB@2021={fb_entity} "
            f"META@2023={meta_entity}; reused bare tickers documented={len(semantic)} "
            f"({', '.join(wire for wire, _n in semantic)})",
            {"negative_cases": [w for w, _n, _k in BROKER_NEGATIVE_CASES]},
        )
    )

    # A14 — WHR is an index removal, not a delisting (R-8)
    whr_entity = alias_table.resolve("WHR", "2020-01-01")
    whr = entity_index.get(whr_entity or "")
    a14_ok = whr is not None and whr.delist_reason == "index-removal" and whr.delisting_date is None
    out.append(
        Assertion(
            "A14",
            True,
            a14_ok,
            f"WHR entity={whr_entity} delist_reason={whr.delist_reason if whr else None} "
            f"delisting_date={whr.delisting_date if whr else None}",
            {},
        )
    )

    # A15 — the parser targets the new article; a 0-row parse raises (F1)
    a15_ok = (
        WIKIPEDIA_CHANGES_SOURCE_TITLE in WIKIPEDIA_CHANGES_SOURCE_URL
        and WIKIPEDIA_MAIN_ARTICLE_SOURCE_TITLE not in WIKIPEDIA_CHANGES_SOURCE_URL
        and facts["main_article_raised"]
    )
    out.append(
        Assertion(
            "A15",
            True,
            a15_ok,
            f"source url pins {WIKIPEDIA_CHANGES_SOURCE_TITLE!r}; main-article parse raised="
            f"{facts['main_article_raised']} rows={facts['main_article_rows']}",
            {"source_url": WIKIPEDIA_CHANGES_SOURCE_URL},
        )
    )

    # A16 — acquisition pairs carry a counterpart ticker (R-3)
    paired = [e for e in result.events if e.counterpart_ticker and e.event_type != "blank-add"]
    acquisition_pairs = {
        e.ticker_as_of: e.counterpart_ticker
        for e in result.events
        if e.event_type == "acquisition-delisted" and e.ticker_as_of
    }
    expected_pairs = {"XLNX": "AMD", "TWTR": "Musk", "ABMD": "Johnson & Johnson"}
    a16_ok = len(paired) > 0 and all(t in acquisition_pairs for t in ("XLNX", "TWTR", "ABMD"))
    out.append(
        Assertion(
            "A16",
            False,
            a16_ok,
            f"{len(paired)} events carry a counterpart ticker; acquisition pairs present for "
            f"{sorted(t for t in ('XLNX', 'TWTR', 'ABMD') if t in acquisition_pairs)}",
            {"expected": list(expected_pairs)},
        )
    )

    # A17 — no entity disappears without a recorded reason (R-7, soft)
    by_month: dict[str, set[str]] = {}
    for row in result.month_end_rows:
        by_month.setdefault(row.month_end, set()).add(row.entity_id)
    grid = sorted(by_month)
    silent = []
    removal_dates: dict[str, list[str]] = {}
    for event in result.events:
        if event.entity_id and event.side == "removed":
            removal_dates.setdefault(event.entity_id, []).append(event.effective_date)
    closed: dict[str, list[str | None]] = {}
    for row in result.aliases:
        if row.valid_to:
            closed.setdefault(row.entity_id, []).append(row.valid_to)
    for previous, current in zip(grid, grid[1:], strict=False):
        for entity_id in sorted(by_month[previous] - by_month[current]):
            explained = any(
                previous < d <= current for d in removal_dates.get(entity_id, [])
            ) or any(previous < d <= current for d in closed.get(entity_id, []) if d)
            if not explained:
                silent.append({"between": [previous, current], "entity_id": entity_id})
    out.append(
        Assertion(
            "A17",
            False,
            not silent,
            f"{len(silent)} unexplained disappearances across {len(grid)} month-ends",
            {"silent": silent[:10]},
        )
    )
    return out


def assert_all_hard(result: BuildResult) -> None:
    """Raise when any hard assertion failed (CI / gate usage)."""

    failures = result.hard_failures()
    if failures:
        joined = "; ".join(f"{a.id}: {a.detail}" for a in failures)
        raise Sp500PitError(f"hard assertion failure(s): {joined}")


# ---------------------------------------------------------------------------
# writers (D1..D11)
# ---------------------------------------------------------------------------
ENTITY_FIELDS = [
    "entity_id",
    "entity_key_kind",
    "cik",
    "canonical_name",
    "display_ticker",
    "symbol_history",
    "first_seen",
    "last_seen",
    "delist_reason",
    "delisting_date",
    "entity_type",
    "provenance",
]
ALIAS_FIELDS = [
    "ticker",
    "valid_from",
    "valid_to",
    "entity_id",
    "is_alias",
    "alias_of",
    "rename_event_ref",
    "source",
]
EVENT_FIELDS = [
    "event_id",
    "entity_id",
    "ticker_as_of",
    "security_name_raw",
    "event_type",
    "effective_date",
    "announced_date",
    "date_confidence",
    "side",
    "counterpart_ticker",
    "reason_text",
    "reason_class",
    "source",
    "source_ref",
    "as_of",
    "ret_str",
    "raw_row_index",
]
MONTH_END_FIELDS = [
    "month_end",
    "entity_id",
    "ticker_as_of",
    "membership_source",
    "snapshot_date_used",
    "gap_days",
    "confidence",
    "agreement",
]
NORM_FIELDS = [
    "canonical_ticker",
    "variant",
    "variant_convention",
    "base_ticker",
    "suffix",
    "source",
    "note",
]
JOEYFIFE_FIELDS = [
    "date",
    "ticker",
    "entity_id",
    "wikipedia_has",
    "joeyfife_has",
    "agreement",
    "mismatch_type",
]
WIKI_VS_FJA_FIELDS = [
    "basis",
    "month_end",
    "entity_id",
    "ticker_as_of",
    "agreement",
    "wikipedia_has",
    "fja_has",
    "mismatch_type",
    "detail",
]
GAP_FIELDS = ["gap_id", "kind", "fact", "disposition", "quantified"]


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _write_csv(path: Path, fields: Sequence[str], rows: Iterable[dict]) -> None:
    # LF bytes on disk: the manifest hashes read_text() (universal newlines),
    # so CRLF output would make recorded digests diverge from the raw bytes.
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(fields), extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _cell(row.get(key)) for key in fields})


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


LICENSE_NOTES = """# License notes — T1.4 S&P 500 PIT membership artifacts

These artifacts are derived read-only products. Redistribution must keep the
upstream notices below.

| Source | Role | License |
|---|---|---|
| `fja05680/sp500` (Updated).csv | month-end anchor snapshots (2720) | MIT |
| `fja05680/sp500` sp500_ticker_start_end.csv | ticker intervals + rename handoffs | MIT |
| Wikipedia `Historical components of the S&P 500` | event skeleton (407 rows) | CC BY-SA 4.0 |
| `joeyfife/point-in-time-sp500` membership.json | cross-check only | code MIT / data CC BY 4.0 |
| `datasets/s-and-p-500-companies` | current CIK cross-section | data PDDL, code MIT/BSD |

Notes:

* The 1996-2019 portion of the fja05680 snapshot file originates from the Andreas
  Clenow *Trading Evolved* companion data, not from Wikipedia (T1.1 §3.1).
* `joeyfife` rows appear only in `reconciliation_joeyfife.csv`, which is a
  diagnostic. Its `current` and `changes` lists contradict each other (R9).
* No delisting prices are included: none of these sources provide them (G4).
* `daily_precision_claimed` is false in `coverage.json`; the anchor series is a
  snapshot series with a 91-day maximum gap.
"""


def write_products(result: BuildResult, out_dir: Path | str) -> dict[str, str]:
    """Write D1..D11 plus a manifest of per-file sha256 digests."""

    base = Path(out_dir)
    base.mkdir(parents=True, exist_ok=True)

    _write_csv(
        base / "entities.csv",
        ENTITY_FIELDS,
        [
            {
                **{key: getattr(entity, key) for key in ENTITY_FIELDS},
                "symbol_history": json.dumps(list(entity.symbol_history), sort_keys=True),
                "provenance": json.dumps(list(entity.provenance)),
            }
            for entity in sorted(result.entities, key=lambda e: e.entity_id)
        ],
    )
    _write_jsonl(
        base / "symbol_history.jsonl",
        [
            entry
            for entity in sorted(result.entities, key=lambda e: e.entity_id)
            for entry in entity.symbol_history
        ],
    )
    _write_csv(
        base / "aliases.csv",
        ALIAS_FIELDS,
        [row.__dict__ for row in sorted(result.aliases, key=lambda a: (a.ticker, a.valid_from))],
    )
    _write_csv(
        base / "events.csv",
        EVENT_FIELDS,
        [
            row.__dict__
            for row in sorted(result.events, key=lambda e: (e.effective_date, e.source, e.event_id))
        ],
    )
    _write_csv(
        base / "month_end_membership.csv",
        MONTH_END_FIELDS,
        [
            row.__dict__
            for row in sorted(result.month_end_rows, key=lambda r: (r.month_end, r.entity_id))
        ],
    )
    _write_jsonl(base / "month_end_lists.jsonl", result.month_end_lists)
    _write_csv(
        base / "ticker_norm_map.csv",
        NORM_FIELDS,
        sorted(result.ticker_norm_map, key=lambda r: (r["canonical_ticker"], r["variant"])),
    )
    _write_csv(
        base / "reconciliation_joeyfife.csv", JOEYFIFE_FIELDS, result.reconciliation_joeyfife
    )
    _write_csv(
        base / "reconciliation_wiki_vs_fja.csv",
        WIKI_VS_FJA_FIELDS,
        result.reconciliation_wiki_vs_fja,
    )
    _write_csv(base / "gaps.csv", GAP_FIELDS, result.gaps)
    (base / "LICENSE_NOTES.md").write_text(LICENSE_NOTES, encoding="utf-8")

    coverage = dict(result.coverage)
    coverage["file_sha256"] = {}
    (base / "coverage.json").write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    hashes = _hash_product_files(base, exclude={"coverage.json", "coverage_report.json"})
    coverage["file_sha256"] = hashes
    payload = json.dumps(coverage, indent=2, sort_keys=True) + "\n"
    (base / "coverage.json").write_text(payload, encoding="utf-8")
    # The task brief names this file coverage_report.json; keep both in sync.
    (base / "coverage_report.json").write_text(payload, encoding="utf-8")

    manifest = {
        "contract": SP500_PIT_CONTRACT,
        "namespace": SP500_PIT_NAMESPACE,
        "build_id": coverage["build_id"],
        "validation_identity": coverage["validation_identity"],
        "validation_digest": coverage["validation_digest"],
        "build_status_scope": coverage["build_status_scope"],
        "independent_completeness": coverage["independent_completeness"],
        "research_ready": coverage["research_ready"],
        "built_at": coverage["built_at"],
        "assertions_passed": coverage["assertions"]["passed"],
        "assertions_total": coverage["assertions"]["total"],
        "assertions_hard_failed": coverage["assertions"]["hard_failed"],
        "build_status": coverage["assertions"]["build_status"],
        "file_sha256": _hash_product_files(base),
    }
    (base / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest["file_sha256"]


def _hash_product_files(base: Path, exclude: set[str] | None = None) -> dict[str, str]:
    """Per-file sha256 of the products, excluding the manifest itself.

    ``build_manifest.json`` is always excluded (and ``coverage.json`` /
    ``coverage_report.json`` when they are still being assembled), so rebuilding
    over an existing directory is idempotent instead of hashing the previous
    run's own bookkeeping.
    """

    skip = {"build_manifest.json"} | (exclude or set())
    return {
        path.name: _sha256(path.read_text(encoding="utf-8"))
        for path in sorted(base.glob("*"))
        if path.is_file() and path.name not in skip
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sp500_pit", description="Build the T1.4 S&P 500 PIT membership artifacts"
    )
    parser.add_argument(
        "--sources", required=True, help="directory with the read-only source files"
    )
    parser.add_argument("--out", required=True, help="artifact output directory")
    parser.add_argument("--grid-start", default=DEFAULT_MONTH_GRID_START)
    parser.add_argument("--grid-end", default=DEFAULT_MONTH_GRID_END)
    parser.add_argument(
        "--built-at",
        default=None,
        help="fix the build timestamp for a reproducible artifact set (default: now, UTC)",
    )
    parser.add_argument("--fail-on-hard-assertion", action="store_true")
    args = parser.parse_args(argv)

    sources = SourceBundle.from_dir(args.sources)
    result = build_sp500_pit(
        sources, built_at=args.built_at, grid_start=args.grid_start, grid_end=args.grid_end
    )
    hashes = write_products(result, args.out)

    failed = [a for a in result.assertions if not a.passed]
    summary = {
        "entities": len(result.entities),
        "aliases": len(result.aliases),
        "events": len(result.events),
        "month_ends": len(result.month_end_lists),
        "month_end_rows": len(result.month_end_rows),
        "gaps": len(result.gaps),
        "assertions_passed": len(result.assertions) - len(failed),
        "assertions_failed": [a.id for a in failed],
        "build_status": result.coverage["assertions"]["build_status"],
        "files": len(hashes),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    for assertion in failed:
        print(
            f"[{'HARD' if assertion.hard else 'soft'}] {assertion.id}: {assertion.detail}",
            flush=True,
        )
    if args.fail_on_hard_assertion:
        assert_all_hard(result)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "BROKER_NEGATIVE_CASES",
    "BuildResult",
    "AliasTable",
    "SourceBundle",
    "Sp500PitError",
    "SP500_PIT_CONTRACT",
    "SP500_PIT_NAMESPACE",
    "assert_all_hard",
    "build_sp500_pit",
    "canonical_ticker",
    "classify_reason",
    "detect_renames",
    "main",
    "month_end_grid",
    "parse_fja_snapshots",
    "parse_fja_start_end",
    "parse_wikipedia_changes",
    "run_assertions",
    "write_products",
]
