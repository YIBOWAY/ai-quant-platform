"""Digest-bound, read-only inputs for wide-universe factor evaluation.

Independence of membership, security lifetime and ticker validity is path-dependent.
With ``research_identity`` (the path the frozen wide run uses) the month-end membership
grid is the independent root: identity status and first-membership knowledge are derived
from that grid plus the reviewed issuer lineage, and per-symbol eligibility is that
first-membership knowledge, or an observed provider listing date when one exists. The
report marks this path ``identity_scope="research_eligibility_only"`` and
``entity_periods``/``ticker_periods`` are not read. Without ``research_identity`` those
two period tables are required and must not be inferred from membership.
No provider calls, account writes, forward filling, or implicit ticker substitutions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

MIN_FORMAL_WIDTH = 300
MIN_MONTHLY_COVERAGE = 0.90
# A month-end snapshot governs a signal day with at most a one-month lag, so staleness is
# measured in days rather than in calendar-month labels. Normal monthly use stays within
# ~31 days (previous month-end to the last session of the current month); 45 days clears
# that with margin, so the guard fires once the governing snapshot is over a month old.
SNAPSHOT_MAX_AGE_DAYS = 45
ADJUSTED_COLUMNS = {
    "adjOpen": "open",
    "adjHigh": "high",
    "adjLow": "low",
    "adjClose": "close",
    "adjVolume": "volume",
}


@dataclass
class WideUniverse:
    ohlcv: pd.DataFrame
    membership: pd.DataFrame
    calendar: pd.DatetimeIndex
    report: dict
    manifest: dict


def _verified_file(root: Path, descriptor: dict) -> Path:
    path = Path(descriptor["path"])
    path = path if path.is_absolute() else root / path
    if not path.is_file():
        raise ValueError(f"input_file_missing:{path.name}")
    if file_digest(path) != descriptor["sha256"]:
        raise ValueError(f"input_digest_mismatch:{path.name}")
    return path


def _dates(values) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(values, utc=True)).normalize()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_manifest_key:{key}")
        result[key] = value
    return result


def load_wide_universe(manifest_path: str | Path, *, mode: str = "diagnostic") -> WideUniverse:
    """Load frozen whole-symbol source files; formal mode rejects incomplete evidence.

    The manifest binds every consumed file, including the exchange calendar.
    With ``research_identity`` present the per-symbol eligibility, identity status and
    first-membership knowledge in that table are derived from the membership overlay
    rather than from independent lifetime sources, and ``entity_periods``/``ticker_periods``
    are not read. Without it, ``entity_periods`` (entity_id/listed_from/listed_to) and
    ``ticker_periods`` (entity_id/ticker/valid_from/valid_to) are required and must not be
    inferred from membership. Membership is last known month-end, never a future snapshot.
    """
    if mode not in {"diagnostic", "formal"}:
        raise ValueError("unknown_wide_universe_mode")
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(), object_pairs_hook=_unique_object)
    if manifest.get("schema_version") != "qs.wide_inputs/v1":
        raise ValueError("unsupported_input_manifest")
    provider = manifest.get("provider")
    source_adjustments = {
        "tiingo": "tiingo_adjusted_ohlcv",
        "futu": "futu_qfq",
        "mixed_explicit": "per_symbol_explicit",
    }
    if (
        provider not in source_adjustments
        or manifest.get("adjustment") != source_adjustments[provider]
    ):
        raise ValueError("explicit_adjusted_ohlcv_source_required")
    if provider == "mixed_explicit":
        if not manifest.get("cross_source_check"):
            raise ValueError("cross_source_check_required")
        _verified_file(path.parent, manifest["cross_source_check"])
    if (
        not isinstance(manifest.get("usage_restrictions"), list)
        or not manifest["usage_restrictions"]
    ):
        raise ValueError("usage_restrictions_required")
    start, end = _dates(manifest["signal_window"])
    if start > end:
        raise ValueError("invalid_signal_window")
    members = pd.read_csv(_verified_file(path.parent, manifest["membership"]))
    members["month_end"] = _dates(members.month_end)
    required = {"month_end", "entity_id", "ticker_as_of"}
    if not required.issubset(members) or members[list(required)].isna().any().any():
        raise ValueError("membership_identity_missing")
    if members.duplicated(["month_end", "ticker_as_of"]).any():
        raise ValueError("duplicate_membership_ticker")
    if members.duplicated(["month_end", "entity_id"]).any():
        raise ValueError("duplicate_membership_entity")
    calendar_frame = pd.read_csv(_verified_file(path.parent, manifest["calendar"]))
    calendar = _dates(calendar_frame.date)
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError("invalid_exchange_calendar")
    signal_days = calendar[(calendar >= start) & (calendar <= end)]
    if signal_days.empty:
        raise ValueError("empty_signal_calendar")
    snapshots = members.month_end.sort_values().unique()
    day_map = pd.merge_asof(
        pd.DataFrame({"signal_ts": signal_days}),
        pd.DataFrame({"month_end": snapshots}),
        left_on="signal_ts",
        right_on="month_end",
        direction="backward",
    )
    stale = day_map.month_end.isna() | (
        (day_map.signal_ts - day_map.month_end).dt.days > SNAPSHOT_MAX_AGE_DAYS
    )
    if stale.any():
        raise ValueError("membership_snapshot_missing_or_stale")
    membership = day_map.merge(members, on="month_end", validate="many_to_many")
    membership = membership.rename(columns={"ticker_as_of": "symbol"})
    original_membership = membership.copy()
    blocks = list(manifest.get("blocking_reasons", []))
    valid_identity = pd.Series(True, index=membership.index)
    entity_periods = None
    research_identity = None
    if manifest.get("research_identity"):
        research_identity = pd.read_csv(_verified_file(path.parent, manifest["research_identity"]))
        _verified_file(path.parent, manifest["identity_evidence"])
        needed = {
            "entity_id",
            "ticker",
            "eligible_not_before",
            "eligible_not_after",
            "identity_status",
            "listing_date",
            "listing_status",
            "ticker_validity_status",
        }
        if (
            not needed.issubset(research_identity)
            or research_identity.duplicated(["entity_id", "ticker"]).any()
        ):
            raise ValueError("invalid_research_identity_table")
        research_identity["eligible_not_before"] = _dates(research_identity.eligible_not_before)
        research_identity["eligible_not_after"] = pd.to_datetime(
            research_identity.eligible_not_after, utc=True
        )
        joined = membership.merge(
            research_identity,
            left_on=["entity_id", "symbol"],
            right_on=["entity_id", "ticker"],
            how="left",
            validate="many_to_one",
        )
        recognized = joined.identity_status.isin(
            ["provider_stock_identity", "official_rename_lineage"]
        )
        valid_identity = recognized & joined.signal_ts.ge(joined.eligible_not_before)
        valid_identity &= joined.eligible_not_after.isna() | joined.signal_ts.lt(
            joined.eligible_not_after
        )
        loaded = joined.symbol.isin(set(manifest["prices"]) - set(manifest.get("exclusions", {})))
        if (loaded & ~recognized).any():
            blocks.append("loaded_security_identity_unverified")
    for key in () if research_identity is not None else ("entity_periods", "ticker_periods"):
        if key not in manifest:
            blocks.append(f"{key}_unverified")
            continue
        periods = pd.read_csv(_verified_file(path.parent, manifest[key]))
        first, last = (
            ("listed_from", "listed_to") if key == "entity_periods" else ("valid_from", "valid_to")
        )
        columns = ["entity_id", first, last] + (["ticker"] if key == "ticker_periods" else [])
        if not set(columns).issubset(periods) or periods[["entity_id", first]].isna().any().any():
            raise ValueError(f"identity_period_fields_missing:{key}")
        periods[first] = _dates(periods[first])
        periods[last] = pd.to_datetime(periods[last], utc=True)
        if key == "entity_periods":
            entity_periods = periods
        if ((periods[last].notna()) & (periods[last] <= periods[first])).any():
            raise ValueError(f"invalid_identity_period:{key}")
        matched = pd.Series(0, index=membership.index)
        for row in periods.to_dict("records"):
            mask = membership.entity_id.eq(row["entity_id"]) & membership.signal_ts.ge(row[first])
            if key == "ticker_periods":
                mask &= membership.symbol.eq(row["ticker"])
            if pd.notna(row[last]):
                mask &= membership.signal_ts.lt(row[last])
            matched += mask.astype(int)
        if (matched > 1).any():
            raise ValueError(f"overlapping_identity_periods:{key}")
        valid_identity &= matched.eq(1)
    if not valid_identity.all() and research_identity is None:
        blocks.append("identity_period_mismatch")
    membership = membership.loc[valid_identity].reset_index(drop=True)
    limitations = []
    if research_identity is not None:
        limitations.append("historical_listing_or_ticker_periods_partially_unknown")
        limitations.append("conservative_research_eligibility_not_legal_listing_history")
    if provider == "mixed_explicit":
        limitations.append("cross_source_equivalence_not_universal")
    if manifest.get("independent_membership_completeness") != "verified":
        limitations.append("independent_membership_completeness_unverified")
    if manifest.get("terminal_returns") != "verified":
        limitations.append("terminal_returns_unverified")
    frames, inventory = [], []
    digest_symbols: dict[str, list[str]] = {}
    source_groups = {}
    universe = sorted(set(original_membership.symbol) | {"SPY"})
    for symbol in universe:
        exclusion = manifest.get("exclusions", {}).get(symbol)
        if exclusion:
            if not exclusion.get("reason") or not exclusion.get("evidence"):
                raise ValueError(f"exclusion_evidence_required:{symbol}")
            _verified_file(path.parent, exclusion["evidence"])
            inventory.append(
                {
                    "symbol": symbol,
                    "status": "quarantined",
                    "rows": 0,
                    "reason": exclusion["reason"],
                    "evidence": exclusion["evidence"],
                }
            )
            limitations.append(f"quarantined:{symbol}:{exclusion['reason']}")
            continue
        descriptor = manifest["prices"].get(symbol)
        if descriptor is None:
            inventory.append({"symbol": symbol, "status": "missing_file", "rows": 0})
            continue
        file = _verified_file(path.parent, descriptor)
        source = descriptor.get("source", provider)
        adjustment = descriptor.get("adjustment", manifest["adjustment"])
        if source not in {"tiingo", "futu"} or adjustment != source_adjustments[source]:
            raise ValueError(f"symbol_source_adjustment_missing_or_invalid:{symbol}")
        if provider != "mixed_explicit" and source != provider:
            raise ValueError(f"implicit_cross_source_panel:{symbol}")
        if descriptor.get("meta"):
            _verified_file(path.parent, descriptor["meta"])
        source_symbol = descriptor.get("source_symbol", symbol)
        if source_symbol != symbol:
            if not descriptor.get("identity_evidence"):
                raise ValueError(f"renamed_source_evidence_required:{symbol}")
            _verified_file(path.parent, descriptor["identity_evidence"])
        for other in digest_symbols.get(descriptor["sha256"], []):
            left = set(membership.loc[membership.symbol == symbol, "signal_ts"])
            right = set(membership.loc[membership.symbol == other, "signal_ts"])
            if left & right:
                raise ValueError(f"duplicate_price_identity:{other}:{symbol}")
        digest_symbols.setdefault(descriptor["sha256"], []).append(symbol)
        frame = pd.read_parquet(file)
        if source == "tiingo":
            if not {"date", *ADJUSTED_COLUMNS}.issubset(frame):
                raise ValueError(f"adjusted_ohlcv_missing:{symbol}")
            frame = frame[["date", *ADJUSTED_COLUMNS]].rename(
                columns={"date": "timestamp", **ADJUSTED_COLUMNS}
            )
        else:
            if "price_adjustment" not in frame or not frame.price_adjustment.eq("qfq").all():
                raise ValueError(f"futu_qfq_evidence_required:{symbol}")
            if (
                "symbol" in frame
                and not frame.symbol.astype(str).str.removeprefix("US.").eq(source_symbol).all()
            ):
                raise ValueError(f"price_symbol_identity_mismatch:{symbol}")
            if not {"timestamp", *ADJUSTED_COLUMNS.values()}.issubset(frame):
                raise ValueError(f"adjusted_ohlcv_missing:{symbol}")
            frame = frame[["timestamp", *ADJUSTED_COLUMNS.values()]].copy()
            limitations.append("futu_volume_basis_provider_native_not_cross_source_certified")
        frame["timestamp"] = _dates(frame.timestamp)
        frame["symbol"] = symbol
        if frame.timestamp.duplicated().any():
            raise ValueError(f"duplicate_price_rows:{symbol}")
        entity_ids = set(original_membership.loc[original_membership.symbol == symbol, "entity_id"])
        if len(entity_ids) > 1:
            raise ValueError(f"ticker_reuse_requires_separate_security_series:{symbol}")
        outside_entity = 0
        if research_identity is not None and symbol != "SPY":
            rows = research_identity[research_identity.ticker.eq(symbol)]
            if len(rows) != 1:
                raise ValueError(f"ambiguous_research_identity:{symbol}")
            identity = rows.iloc[0]
            valid_prices = frame.timestamp.ge(identity.eligible_not_before)
            if pd.notna(identity.eligible_not_after):
                valid_prices &= frame.timestamp.lt(identity.eligible_not_after)
            outside_entity = int((~valid_prices).sum())
            frame = frame.loc[valid_prices].copy()
        if entity_periods is not None and symbol != "SPY":
            valid_prices = pd.Series(False, index=frame.index)
            for period in entity_periods[entity_periods.entity_id.isin(entity_ids)].to_dict(
                "records"
            ):
                mask = frame.timestamp.ge(period["listed_from"])
                if pd.notna(period["listed_to"]):
                    mask &= frame.timestamp.lt(period["listed_to"])
                valid_prices |= mask
            outside_entity = int((~valid_prices).sum())
            frame = frame.loc[valid_prices].copy()
        values = frame[list(ADJUSTED_COLUMNS.values())].apply(pd.to_numeric, errors="coerce")
        good = np.isfinite(values).all(axis=1) & values[["open", "high", "low", "close"]].gt(0).all(
            axis=1
        )
        good &= values.volume.gt(0) & values.high.ge(values[["open", "low", "close"]].max(axis=1))
        good &= values.low.le(values[["open", "high", "close"]].min(axis=1))
        invalid = int((~good).sum())
        if invalid:
            limitations.append(f"invalid_or_zero_volume_rows:{symbol}")
        frame[list(values)] = values
        frame = frame.loc[good & frame.timestamp.isin(calendar)]
        group = source_groups.setdefault(
            source, {"symbols": 0, "rows": 0, "adjustment": adjustment}
        )
        group["symbols"] += 1
        group["rows"] += len(frame)
        frames.append(frame)
        inventory.append(
            {
                "symbol": symbol,
                "status": "loaded",
                "rows": len(frame),
                "invalid_or_zero_volume_rows": invalid,
                "outside_entity_period_rows": outside_entity,
                "sha256": descriptor["sha256"],
                "source": source,
                "adjustment": adjustment,
                "volume_basis": "tiingo_adjVolume"
                if source == "tiingo"
                else "futu_provider_native",
            }
        )
    ohlcv = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    )
    observed = ohlcv[["symbol", "timestamp"]].rename(columns={"timestamp": "signal_ts"})
    coverage = original_membership.merge(
        observed.assign(observed=True), on=["symbol", "signal_ts"], how="left"
    )
    coverage["observed"] = coverage.observed.eq(True)
    daily = coverage.groupby("signal_ts").agg(
        expected=("symbol", "size"), observed=("observed", "sum")
    )
    daily["fraction"] = daily.observed / daily.expected
    if not (ohlcv.symbol == "SPY").any():
        limitations.append("benchmark_missing")
    monthly = daily.groupby(daily.index.strftime("%Y-%m")).agg(
        expected_min=("expected", "min"),
        observed_min=("observed", "min"),
        observed_median=("observed", "median"),
        coverage_min=("fraction", "min"),
        expected_rows=("expected", "sum"),
        observed_rows=("observed", "sum"),
        month_end_observed=("observed", "last"),
    )
    monthly["daily_row_coverage"] = monthly.observed_rows / monthly.expected_rows
    if monthly.month_end_observed.min() < MIN_FORMAL_WIDTH:
        blocks.append("month_end_width_below_300")
    if monthly.daily_row_coverage.min() < MIN_MONTHLY_COVERAGE:
        blocks.append("monthly_full_member_price_coverage_below_90pct")
    report = {
        "schema_version": "qs.wide_input_report/v1",
        "authority": "diagnostic_only",
        "formal_ready": not blocks,
        "blocking_reasons": sorted(set(blocks)),
        "known_source_limits": sorted(set(limitations)),
        "research_status": "blocked"
        if blocks
        else ("partial_known_source_limits" if limitations else "ready"),
        "admission_authority": False,
        "input_manifest_sha256": file_digest(path),
        "provider": provider,
        "source_groups": source_groups,
        "identity_excluded_rows": int((~valid_identity).sum()),
        "identity_scope": "research_eligibility_only"
        if research_identity is not None
        else "separate_entity_and_ticker_periods",
        "adjustment": manifest["adjustment"],
        "usage_restrictions": manifest["usage_restrictions"],
        "universe_total": len(universe),
        "loaded": sum(x["status"] == "loaded" for x in inventory),
        "skipped": sum(x["status"] != "loaded" for x in inventory),
        "inventory": inventory,
        "monthly_coverage": monthly.reset_index(names="month").to_dict("records"),
        "minimum_month_end_width": MIN_FORMAL_WIDTH,
        "minimum_monthly_full_member_price_coverage": MIN_MONTHLY_COVERAGE,
    }
    if mode == "formal":
        if blocks:
            raise ValueError("formal_inputs_blocked:" + ",".join(sorted(set(blocks))))
        report["authority"] = "formal_research_only"
    return WideUniverse(
        ohlcv.sort_values(["symbol", "timestamp"]).reset_index(drop=True),
        membership,
        calendar,
        report,
        manifest,
    )


def file_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_fetch_plan(
    membership_path: str | Path,
    price_dirs: list[Path],
    *,
    start: str = "2016-01-01",
    end: str = "2026-08-31",
) -> dict:
    """Describe required history, including warmup and labels, without fetching it.

    Price presence is only inventory, never evidence of identity or completeness.
    The preceding snapshot is included because it controls early first-month days.
    """
    membership = pd.read_csv(membership_path)
    previous = membership.loc[membership.month_end < start, "month_end"].max()
    floor = previous if isinstance(previous, str) else start
    relevant = membership[membership.month_end.between(floor, end)]
    requests = []
    for symbol in sorted(set(relevant.ticker_as_of) | {"SPY"}):
        rows = relevant[relevant.ticker_as_of == symbol]
        first = max(start, str(rows.month_end.min())) if len(rows) else start
        last = min(end, str(rows.month_end.max())) if len(rows) else end
        # Month-end membership may remain active through the following month.
        effective_last = min(pd.Timestamp(end), pd.Timestamp(last) + pd.offsets.MonthEnd(1))
        request_start = (pd.Timestamp(first) - pd.DateOffset(months=14)).date().isoformat()
        request_end = (effective_last + pd.offsets.BDay(22)).date().isoformat()
        files = [p / f"{symbol}.parquet" for p in price_dirs if (p / f"{symbol}.parquet").exists()]
        item = {
            "symbol": symbol,
            "entity_ids": sorted(set(rows.entity_id.astype(str))),
            "first_membership_snapshot": str(rows.month_end.min()) if len(rows) else None,
            "last_membership_snapshot": str(rows.month_end.max()) if len(rows) else None,
            "request_start": request_start,
            "request_end": request_end,
            "reason": "missing_file" if not files else "verify_daily_coverage_and_identity",
            "existing_files": [str(p) for p in files],
        }
        if files:
            frame = pd.read_parquet(files[0], columns=["date"])
            dates = pd.to_datetime(frame.date, utc=True)
            item.update(
                observed_start=dates.min().date().isoformat() if len(dates) else None,
                observed_end=dates.max().date().isoformat() if len(dates) else None,
                observed_rows=len(dates),
                sha256=file_digest(files[0]),
            )
        requests.append(item)
    return {
        "schema_version": "qs.wide_fetch_plan/v1",
        "membership_sha256": file_digest(membership_path),
        "signal_window": [start, end],
        "member_symbol_count": relevant.ticker_as_of.nunique(),
        "missing_file_count": sum(r["reason"] == "missing_file" for r in requests),
        "requests": requests,
        "notes": [
            "Inventory only; identity is not certified.",
            "Request ends include unobserved future labels; never invent them.",
            "Dates are request bounds, not company listing or index membership dates.",
        ],
    }
