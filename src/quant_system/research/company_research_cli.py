"""Hermes company evidence tools. No order/account/research activation commands."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from typing import Any

from quant_system.config.settings import load_settings
from quant_system.data.providers.longbridge import (
    LongbridgeProviderError,
    normalize_longbridge_symbol,
)
from quant_system.research import company_research as service
from quant_system.research import data_source_checks

SECTION_KEYS = (
    "quote",
    "company",
    "income",
    "balance",
    "cashflow",
    "valuation",
    "segments",
    "dividends",
    "corporate_actions",
    "news",
    "filings",
    "consensus",
    "ratings",
    "insiders",
)
PROFILE_MAX_CHARS = 1500
SECTION_DATA_MAX_BYTES = 256 * 1024
_REPORT_FIELDS = (
    "schema_version",
    "symbol",
    "snapshot_id",
    "updated_at",
    "status",
    "stale",
    "source_policy",
    "headline",
    "summary",
    "research_ideas",
    "warnings",
    "error",
    "research_only",
    "pit_backtest_ready",
)


def _compact_report(document: dict[str, Any]) -> dict[str, Any]:
    result = {key: document[key] for key in _REPORT_FIELDS if key in document}
    result["projection"] = "compact"
    sections = []
    for source in document.get("sections", []):
        section = {key: value for key, value in source.items() if key != "data"}
        key = section.get("key")
        if key in SECTION_KEYS:
            section["detail"] = {"action": "section", "symbol": document["symbol"], "key": key}
        if key == "quote":
            section.update(data=source.get("data"), projection="full")
        elif key == "company":
            data = source.get("data")
            selected = {}
            if isinstance(data, dict):
                selected = {
                    "name": data.get("name") or data.get("company_name"),
                    "website": data.get("website"),
                }
                profile = data.get("profile")
                if isinstance(profile, str):
                    selected.update(
                        profile=profile[:PROFILE_MAX_CHARS],
                        profile_truncated=len(profile) > PROFILE_MAX_CHARS,
                        profile_original_chars=len(profile),
                        profile_limit_chars=PROFILE_MAX_CHARS,
                    )
            section.update(data=selected, projection="company_brief")
        else:
            section["projection"] = "metadata_only"
        sections.append(section)
    result["sections"] = sections
    financials = document.get("financials", {})
    if isinstance(financials, dict):
        summary = {
            key: financials[key]
            for key in ("status", "currency", "checks", "warnings")
            if key in financials
        }
        for key, limit in (("periods", 5), ("metrics", 8)):
            values = financials.get(key, [])
            summary[key] = values[:limit]
            summary[f"{key}_total"] = len(values)
            summary[f"{key}_truncated"] = len(values) > limit
        result["financials"] = summary
    return result


def _section_report(document: dict[str, Any], key: str) -> dict[str, Any]:
    result = {
        name: document[name]
        for name in (
            "schema_version",
            "symbol",
            "snapshot_id",
            "updated_at",
            "status",
            "stale",
            "source_policy",
            "error",
            "research_only",
            "pit_backtest_ready",
        )
        if name in document
    }
    result.update(projection="section", section_key=key)
    section = next((item for item in document.get("sections", []) if item.get("key") == key), None)
    if section is None:
        result["section"] = None
        if document.get("status") != "not_loaded":
            result.update(status="failed", error="section_not_available")
        return result
    raw_size = len(json.dumps(section.get("data"), ensure_ascii=False, allow_nan=False).encode())
    result.update(raw_size_bytes=raw_size, size_limit_bytes=SECTION_DATA_MAX_BYTES)
    if raw_size > SECTION_DATA_MAX_BYTES:
        result.update(
            status="failed",
            error="size_limit",
            section={name: value for name, value in section.items() if name != "data"},
        )
    else:
        result["section"] = section
    return result


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("company_cli_arguments_invalid")


def main(argv=None, *, stdout=None):
    output = stdout or sys.stdout
    try:
        parser = Parser(description=__doc__)
        actions = parser.add_subparsers(dest="action", required=True, parser_class=Parser)
        for action in ("show", "refresh", "check-sources"):
            actions.add_parser(action).add_argument("symbol")
        actions.add_parser("sources")
        actions.add_parser("compare").add_argument("symbols", nargs="+")
        detail = actions.add_parser("section")
        detail.add_argument("symbol")
        detail.add_argument("key", choices=SECTION_KEYS)
        args = parser.parse_args(argv)
        if args.action == "compare":
            if not 1 <= len(args.symbols) <= 4:
                raise ValueError("company_compare_limit")
            args.symbols = [normalize_longbridge_symbol(symbol) for symbol in args.symbols]
        elif hasattr(args, "symbol"):
            args.symbol = normalize_longbridge_symbol(args.symbol)
        with (
            open(os.devnull, "w") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            settings = load_settings()
            if args.action == "show":
                result = _compact_report(service.read_company(settings, args.symbol))
            elif args.action == "refresh":
                result = _compact_report(service.refresh_company(settings, args.symbol))
            elif args.action == "section":
                result = _section_report(service.read_company(settings, args.symbol), args.key)
            elif args.action == "sources":
                result = data_source_checks.read_checks(settings)
            elif args.action == "check-sources":
                lease = data_source_checks.begin_checks(settings, args.symbol)
                data_source_checks.finish_checks(settings, args.symbol, lease)
                result = data_source_checks.read_checks(settings)
            else:
                result = {
                    "projection": "compact",
                    "items": [
                        _compact_report(service.read_company(settings, symbol))
                        for symbol in args.symbols
                    ],
                }
        failed = result.get("status") == "failed"
        payload = {
            "contract": "hqa.company_research/v1",
            "action": args.action,
            "ok": not failed,
            **result,
        }
        code = 1 if failed else 0
    except (ValueError, LongbridgeProviderError) as exc:
        payload = {
            "contract": "hqa.company_research/v1",
            "ok": False,
            "status": "failed",
            "error": exc.code if isinstance(exc, LongbridgeProviderError) else "invalid_request",
        }
        code = 2
    except service.ResearchBusy:
        payload = {
            "contract": "hqa.company_research/v1",
            "ok": False,
            "status": "updating",
            "error": "refresh_busy",
        }
        code = 3
    except Exception:
        payload = {
            "contract": "hqa.company_research/v1",
            "ok": False,
            "status": "failed",
            "error": "company_research_unavailable",
        }
        code = 1
    output.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
