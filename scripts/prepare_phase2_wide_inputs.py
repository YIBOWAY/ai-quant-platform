"""Freeze a new research input overlay from existing, read-only provider files.

No network, strategy mutation, scorecard calculation or account writes. Provider
availability is never relabeled as a legal listing date. Unknown securities are
retained in denominators and explicitly quarantined.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd

from quant_system.research.wide_universe import file_digest, load_wide_universe

US_EXCHANGES = {"NYSE", "NASDAQ", "NYSE MKT", "AMEX", "NYSE ARCA", "PINK", "OTCBB", "BATS"}


def descriptor(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": file_digest(path)}


def select_symbol_source(
    symbol: str,
    old: Path,
    new: Path,
    futu: Path,
    renames: dict,
    *,
    equity_identity_symbols: set[str] | None = None,
) -> dict:
    """Prefer an identified old Tiingo series, then new Tiingo, then Futu.

    Each selection is one whole file. No row-wise provider fallback is possible.
    The caller supplies reviewed issuer mappings, never just a same-name guess.
    """
    rejected = []
    successor = renames.get(symbol, {}).get("successor", symbol)
    for root in (old, new):
        file = root / f"{symbol}.parquet"
        if not file.is_file() and successor != symbol:
            file = root / f"{successor}.parquet"
        if not file.is_file():
            continue
        meta_file = root / "meta" / f"{successor}.json"
        if not meta_file.is_file():
            meta_file = root / "meta" / f"{symbol}.json"
        if not meta_file.is_file():
            rejected.append({"path": str(file), "reason": "provider_metadata_missing"})
            continue
        meta = json.loads(meta_file.read_text())
        name = str(meta.get("name", ""))
        reason = None
        if symbol != "SPY" and re.search(
            r"\bETF\b|GRANITESHARES|DEFIANCE|DIREXION|PROSHARES", name.upper()
        ):
            reason = "metadata_reused_etf"
        elif meta.get("exchangeCode") not in US_EXCHANGES:
            reason = "non_us_or_unknown_exchange"
        elif meta.get("ticker", "").upper() not in {symbol, successor}:
            reason = "metadata_ticker_mismatch"
        elif not name:
            reason = "provider_name_missing"
        if reason:
            rejected.append({"path": str(file), "reason": reason, "meta": descriptor(meta_file)})
            continue
        return {
            "source": "tiingo",
            "adjustment": "tiingo_adjusted_ohlcv",
            "file": file,
            "meta_file": meta_file,
            "metadata": meta,
            "source_symbol": successor,
            "listing_date": None,
            "data_available_from": meta.get("startDate"),
            "rejected": rejected,
        }
    futu_symbol = (
        successor if successor != symbol and (futu / f"{successor}.parquet").is_file() else symbol
    )
    file, meta_file = futu / f"{futu_symbol}.parquet", futu / f"{futu_symbol}.metadata.json"
    if file.is_file() and meta_file.is_file():
        receipt = json.loads(meta_file.read_text())
        meta = receipt.get("metadata") or {}
        if (
            receipt.get("status") == "available"
            and meta.get("stock_id")
            and (
                meta.get("stock_type") == "STOCK"
                or symbol == "SPY"
                or (
                    meta.get("stock_type") == "ETF" and symbol in (equity_identity_symbols or set())
                )
            )
            and meta.get("delisting") is not True
            and meta.get("code") == f"US.{futu_symbol}"
            and str(meta.get("exchange_type", "")).startswith("US_")
        ):
            if receipt.get("sha256") != file_digest(file):
                raise ValueError(f"futu_receipt_digest_mismatch:{symbol}")
            return {
                "source": "futu",
                "adjustment": "futu_qfq",
                "file": file,
                "meta_file": meta_file,
                "metadata": meta,
                "source_symbol": futu_symbol,
                "listing_date": meta.get("listing_date")
                if meta.get("listing_date") not in {None, "", "1970-01-01"}
                else None,
                "data_available_from": str(receipt.get("first", ""))[:10] or None,
                "rejected": rejected,
            }
        rejected.append(
            {
                "path": str(file),
                "reason": "futu_security_identity_unconfirmed",
                "meta": descriptor(meta_file),
            }
        )
    elif meta_file.is_file():
        receipt = json.loads(meta_file.read_text())
        rejected.append(
            {
                "path": str(file),
                "reason": receipt.get("reason", "futu_unavailable"),
                "meta": descriptor(meta_file),
            }
        )
    return {"source": None, "rejected": rejected, "reason": "no_identified_whole_symbol_source"}


def build_membership_overlay(original: pd.DataFrame, renames: dict) -> tuple[pd.DataFrame, list]:
    """Unify only reviewed issuer lineages and remove same-snapshot duplicates."""
    result = original.copy()
    result["source_entity_id"] = result.entity_id
    groups = {}
    for old, item in renames.items():
        successor = item["successor"]
        groups[old] = successor
        if item.get("intermediate"):
            groups[item["intermediate"]] = successor

    def canonical(symbol):
        seen = set()
        while symbol in groups and symbol not in seen:
            seen.add(symbol)
            symbol = groups[symbol]
        return symbol

    involved = set(groups) | set(groups.values())
    mask = result.ticker_as_of.isin(involved)
    if all("source_entity_ids" in item for item in renames.values()):
        allowed = {}
        for old, item in renames.items():
            allowed.setdefault(old, set()).update(item["source_entity_ids"])
            allowed.setdefault(item["successor"], set()).update(item["successor_entity_ids"])
            if item.get("intermediate"):
                mid = item["intermediate"]
                allowed.setdefault(mid, set()).update(
                    renames.get(mid, {}).get("source_entity_ids", [])
                )
        mask &= pd.Series(
            [
                entity in allowed.get(symbol, set())
                for symbol, entity in zip(result.ticker_as_of, result.entity_id, strict=True)
            ],
            index=result.index,
        )
    result.loc[mask, "entity_id"] = result.loc[mask, "ticker_as_of"].map(
        lambda s: f"E:OFFICIAL_LINEAGE:{canonical(s)}"
    )
    actions = []
    duplicate = result[result.duplicated(["month_end", "entity_id"], keep=False)]
    drop = []
    for (month, entity), rows in duplicate.groupby(["month_end", "entity_id"]):
        # Prefer the code known to be in effect on this snapshot. We retain the
        # original row and source identity alongside every deterministic choice.
        ranks = {}
        for index, row in rows.iterrows():
            record = renames.get(row.ticker_as_of)
            if record and month < record["effective_date"]:
                ranks[index] = 0
            else:
                ranks[index] = 1
        keep = sorted(ranks, key=lambda i: (ranks[i], result.loc[i, "ticker_as_of"]))[0]
        for index, row in rows.iterrows():
            if index != keep:
                drop.append(index)
                actions.append(
                    {
                        "month_end": month,
                        "entity_id": entity,
                        "kept": result.loc[keep, "ticker_as_of"],
                        "removed_duplicate": row.ticker_as_of,
                        "reason": "official_same_issuer_duplicate_snapshot",
                    }
                )
    return result.drop(index=drop).reset_index(drop=True), actions


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def membership_price_window_mismatch(
    symbol: str,
    observed_first: str,
    observed_last: str,
    membership_first: str,
    membership_last: str,
) -> str | None:
    """Quarantine reason when observed prices miss a member's whole membership window.

    Both bounds are ISO dates, so a lexicographic comparison is a date comparison. The
    benchmark is exempt: its membership column is a stand-in, not an index era.
    """
    if symbol == "SPY":
        return None
    if observed_first > membership_last:
        return "price_history_starts_after_membership"
    if observed_last < membership_first:
        return "price_history_ends_before_membership"
    return None


DUAL_CLASS_BREADTH_NOTE = (
    "Multi-class issuers (several listed classes sharing one issuer, e.g. GOOG/GOOGL) are "
    "counted as separate listed securities in month-end universe breadth; an issuer-level "
    "exposure is neither netted nor weighted by this count."
)

_CIK_ENTITY = re.compile(r"^(E:CIK\d+)(?::.*)?$")


def issuer_prefix(entity_id: str) -> str:
    """Issuer key of a membership entity id.

    Only CIK-rooted ids carry an issuer/class split (E:CIK0001652044:GOOG -> E:CIK0001652044).
    Ids with no CIK (E:X:<slug>, E:OFFICIAL_LINEAGE:<ticker>) are their own issuer, or
    unrelated symbols would collapse into one fake issuer and be registered as classes of
    the same company.
    """
    match = _CIK_ENTITY.match(str(entity_id))
    return match.group(1) if match else str(entity_id)


def same_issuer_dual_class_registrations(overlay: pd.DataFrame) -> list[dict]:
    """List same-issuer, same-snapshot multi-class tickers instead of leaving them implicit.

    The overlay keeps one entity per listed class, so nothing is folded and no result is
    recomputed here: this only registers the multi-class situation for downstream readers
    and states the breadth basis the frozen width was produced under.
    """
    basis = overlay.source_entity_id if "source_entity_id" in overlay else overlay.entity_id
    grouped = overlay.assign(
        issuer=[issuer_prefix(value) for value in basis]
    ).groupby(["month_end", "issuer"])["ticker_as_of"]
    return [
        {"month_end": str(month), "issuer": issuer, "tickers": sorted(set(tickers))}
        for (month, issuer), tickers in grouped.agg(lambda codes: list(codes)).items()
        if len(set(tickers)) > 1
    ]


def prepare_inputs(
    platform_root: Path,
    hqa_root: Path,
    identity_review: Path,
    cross_source_check: Path,
    out: Path,
    *,
    as_of: str = "2026-09-18",
    identity_supplement: Path | None = None,
) -> dict:
    """Freeze the observed source set once and run its input audit only."""
    if out.exists():
        raise FileExistsError(out)
    review = json.loads(identity_review.read_text())
    renames = dict(review["verified_mappings"])
    if identity_supplement is not None:
        renames.update(json.loads(identity_supplement.read_text())["verified_mappings"])
    artifacts = platform_root / "artifacts"
    old, new, futu = (
        artifacts / "t13-tiingo-panel-2026-09-17",
        artifacts / "phase2-current-prices-20260920",
        artifacts / "phase2-futu-prices-20260920",
    )
    membership_file = artifacts / "t14-sp500-membership-2026-09-16/month_end_membership.csv"
    original = pd.read_csv(membership_file)
    aliases_file = artifacts / "t14-sp500-membership-2026-09-16/aliases.csv"
    aliases = pd.read_csv(aliases_file)
    renames = {old: dict(item) for old, item in renames.items()}
    for old_code, item in renames.items():
        proven_aliases = aliases[
            aliases.ticker.eq(old_code)
            & aliases.alias_of.eq(item["successor"])
            & aliases.is_alias.eq(True)
        ]
        source_rows = original[
            original.ticker_as_of.eq(old_code) & original.month_end.lt(item["effective_date"])
        ]
        item["source_entity_ids"] = sorted(
            set(proven_aliases.entity_id if len(proven_aliases) else source_rows.entity_id)
        )
        item["successor_entity_ids"] = sorted(
            set(original.loc[original.ticker_as_of.eq(item["successor"]), "entity_id"])
        )
    constituents_file = (
        artifacts / "t14-sp500-membership-2026-09-16/sources/current_constituents.csv"
    )
    constituents = pd.read_csv(constituents_file)
    reits = set(
        constituents.loc[constituents["GICS Sub-Industry"].str.contains("REIT", na=False), "Symbol"]
    )
    relevant = original[original.month_end.between("2015-12-01", "2026-08-31")].copy()
    overlay, actions = build_membership_overlay(relevant, renames)
    multi_class = same_issuer_dual_class_registrations(overlay)
    source_audit = (
        hqa_root / "evidence/2026-09-20-independent-plan-review/manifest_panel_v5-audit.json"
    )
    audit = json.loads(source_audit.read_text())
    exclusions, prices, identity_rows, selection = {}, {}, [], []
    out.mkdir(parents=True, exist_ok=False)
    evidence_file = out / "identity-evidence.json"
    quarantine = dict(review.get("quarantine", {}))
    for symbol, count in overlay.groupby("ticker_as_of").entity_id.nunique().items():
        if count > 1:
            quarantine[symbol] = "multiple_security_eras_require_separate_identity_evidence"
    raw_rekeys = json.loads((old / "rename_rekey.json").read_text())
    for symbol, item in raw_rekeys["applied"].items():
        if renames.get(symbol, {}).get("successor") != item["successor"]:
            quarantine[symbol] = "rekey_issuer_lineage_not_officially_verified"
    known_symbols = sorted(set(overlay.ticker_as_of) | {"SPY"})
    for symbol in known_symbols:
        rows = overlay[overlay.ticker_as_of == symbol]
        entity = str(rows.entity_id.iloc[0]) if len(rows) else "benchmark:SPY"
        symbol_renames = renames
        if symbol in renames and not set(rows.source_entity_id).issubset(
            set(renames[symbol]["source_entity_ids"])
        ):
            symbol_renames = {key: value for key, value in renames.items() if key != symbol}
        source = select_symbol_source(
            symbol, old, new, futu, symbol_renames, equity_identity_symbols=reits
        )
        entry = {
            "symbol": symbol,
            "entity_id": entity,
            "source": source["source"],
            "rejected": source["rejected"],
        }
        if symbol in quarantine or source["source"] is None:
            entry["status"] = "quarantined"
            entry["reason"] = quarantine.get(symbol, source.get("reason"))
            exclusions[symbol] = {"reason": entry["reason"]}
            selection.append(entry)
            continue
        frame = pd.read_parquet(source["file"])
        date_column = "date" if source["source"] == "tiingo" else "timestamp"
        days = pd.to_datetime(frame[date_column], utc=True)
        actual_first, actual_last = days.min().date().isoformat(), days.max().date().isoformat()
        window_reason = membership_price_window_mismatch(
            symbol, actual_first, actual_last, rows.month_end.min(), rows.month_end.max()
        )
        if window_reason:
            entry.update(status="quarantined", reason=window_reason)
            exclusions[symbol] = {"reason": entry["reason"]}
            selection.append(entry)
            continue
        listing_date = source["listing_date"]
        listing_evidence = None
        # A separate actual provider listing observation may support a Tiingo
        # selection; availability startDate never takes its place.
        listing_file = futu / f"{symbol}.metadata.json"
        if not listing_date and listing_file.is_file():
            other = json.loads(listing_file.read_text())
            meta = other.get("metadata") or {}
            if other.get("status") == "available" and meta.get("code") == f"US.{symbol}":
                listing_date = (
                    meta.get("listing_date")
                    if meta.get("listing_date") not in {None, "", "1970-01-01"}
                    else None
                )
                listing_evidence = descriptor(listing_file)
        knowledge_rows = original[
            original.ticker_as_of.eq(symbol) & original.entity_id.isin(set(rows.source_entity_id))
        ]
        knowledge_column = (
            "snapshot_date_used" if "snapshot_date_used" in knowledge_rows else "month_end"
        )
        knowledge_dates = knowledge_rows[knowledge_column].dropna()
        first_known = str(knowledge_dates.min()) if len(knowledge_dates) else actual_first
        eligible = (
            max(actual_first, listing_date) if listing_date else max(actual_first, first_known)
        )
        if symbol != "SPY" and eligible > rows.month_end.max():
            entry.update(status="quarantined", reason="listing_or_eligibility_after_membership")
            exclusions[symbol] = {"reason": entry["reason"]}
            selection.append(entry)
            continue
        selected = {
            **descriptor(source["file"]),
            "source": source["source"],
            "adjustment": source["adjustment"],
            "meta": descriptor(source["meta_file"]),
        }
        if source["source_symbol"] != symbol:
            selected["source_symbol"] = source["source_symbol"]
        prices[symbol] = selected
        identity_rows.append(
            {
                "entity_id": entity,
                "ticker": symbol,
                "eligible_not_before": eligible,
                "eligible_not_after": None,
                "identity_status": "official_rename_lineage"
                if symbol in symbol_renames
                else "provider_stock_identity",
                "listing_date": listing_date,
                "listing_status": "provider_listing_date" if listing_date else "unknown",
                "ticker_validity_status": "not_independently_verified",
                "data_available_from": source["data_available_from"],
                "first_price": actual_first,
                "first_membership_knowledge": first_known,
                "eligibility_basis": "provider_listing_date_and_first_price"
                if listing_date
                else "max_first_price_first_membership_knowledge",
            }
        )
        entry.update(
            status="selected",
            file=selected,
            listing_date=listing_date,
            listing_evidence=listing_evidence,
            eligible_not_before=eligible,
            observed_first=actual_first,
            observed_last=actual_last,
            identity_scope="provider_identity_plus_reviewed_lineage_not_complete_legal_history",
        )
        selection.append(entry)
    _write_json(
        evidence_file,
        {
            "schema_version": "qs.phase2_identity_evidence/v1",
            "official_review": descriptor(identity_review),
            "official_supplement": descriptor(identity_supplement) if identity_supplement else None,
            "original_membership": descriptor(membership_file),
            "source_aliases": descriptor(aliases_file),
            "issuer_bound_rename_mappings": renames,
            "original_rekeys": descriptor(old / "rename_rekey.json"),
            "reit_instrument_identity_source": descriptor(constituents_file),
            "source_audit": descriptor(source_audit),
            "membership_overlay_actions": actions,
            "selections": selection,
        },
    )
    for value in exclusions.values():
        value["evidence"] = descriptor(evidence_file)
    for value in prices.values():
        if value.get("source_symbol"):
            value["identity_evidence"] = descriptor(evidence_file)
    overlay_file, identity_file, calendar_file = (
        out / "membership-overlay.csv",
        out / "research-identity.csv",
        out / "calendar.csv",
    )
    overlay.to_csv(overlay_file, index=False)
    pd.DataFrame(identity_rows).to_csv(identity_file, index=False)
    calendar = xcals.get_calendar("XNYS", start="2014-11-01", end=as_of)
    sessions = calendar.sessions
    pd.DataFrame({"date": sessions.strftime("%Y-%m-%d")}).to_csv(calendar_file, index=False)
    manifest = {
        "schema_version": "qs.wide_inputs/v1",
        "provider": "mixed_explicit",
        "adjustment": "per_symbol_explicit",
        "signal_window": ["2016-01-01", "2026-08-31"],
        "as_of": as_of,
        "usage_restrictions": audit["usage_restrictions"]
        + audit["restriction_clarifications"]
        + review["known_limits"]
        + [DUAL_CLASS_BREADTH_NOTE],
        "membership": descriptor(overlay_file),
        "calendar": descriptor(calendar_file),
        "calendar_source": {
            "name": "XNYS",
            "library": "exchange_calendars",
            "version": xcals.__version__,
        },
        "research_identity": descriptor(identity_file),
        "identity_evidence": descriptor(evidence_file),
        "cross_source_check": descriptor(cross_source_check),
        "prices": prices,
        "exclusions": exclusions,
        "same_issuer_dual_class": {
            "basis": (
                "issuer prefix of the original membership entity_id "
                "over the deduplicated overlay"
            ),
            "breadth_rule": "each listed class is a separate security in the width count",
            "entries": multi_class,
            "issuer_month_count": len(multi_class),
            "ticker_count": len({ticker for item in multi_class for ticker in item["tickers"]}),
        },
        "independent_membership_completeness": "not_verified",
        "terminal_returns": "not_verified",
        "frozen_acceptance": {"month_end_width": 300, "monthly_full_member_price_coverage": 0.90},
        "builder_sha256": file_digest(Path(__file__)),
        "source_policy": "old_identified_tiingo_then_new_tiingo_then_futu_whole_symbol_no_splice",
    }
    manifest_file = out / "input-manifest.json"
    _write_json(manifest_file, manifest)
    loaded = load_wide_universe(manifest_file, mode="diagnostic")
    _write_json(out / "input-audit.json", loaded.report)
    summary = {
        "manifest": str(manifest_file),
        "selected": len(prices),
        "quarantined": len(exclusions),
        "official_rekey_entries": len(raw_rekeys["applied"]),
        "deduplicated_membership_rows": len(actions),
        "formal_ready": loaded.report["formal_ready"],
        "blocking_reasons": loaded.report["blocking_reasons"],
        "source_groups": loaded.report["source_groups"],
        "admission_authority": False,
    }
    _write_json(out / "summary.json", summary)
    _write_json(
        out / "output-digests.json",
        {f.name: file_digest(f) for f in sorted(out.iterdir()) if f.is_file()},
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform-root", type=Path, required=True)
    parser.add_argument("--hqa-root", type=Path, required=True)
    parser.add_argument("--identity-review", type=Path, required=True)
    parser.add_argument("--identity-supplement", type=Path)
    parser.add_argument("--cross-source-check", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--as-of", default="2026-09-18")
    args = parser.parse_args()
    print(
        json.dumps(
            prepare_inputs(
                args.platform_root,
                args.hqa_root,
                args.identity_review,
                args.cross_source_check,
                args.out,
                as_of=args.as_of,
                identity_supplement=args.identity_supplement,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
