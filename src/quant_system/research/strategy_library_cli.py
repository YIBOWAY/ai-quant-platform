"""Hermes-facing strategy library commands with compact, non-sensitive receipts."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import quote

from pydantic import ValidationError

from quant_system.api.routes.strategy_library import (
    BacktestImport,
    ComposeStrategy,
    StrategyAction,
    StudyImport,
)
from quant_system.config.settings import load_settings
from quant_system.research import strategy_library as service

CONTRACT = "hqa.strategy_library/v1"
_MAX_JSON_BYTES = 65_536
_CODE = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
_METRICS = ("total_return", "annualized_return", "sharpe", "max_drawdown", "turnover")
_FRONTEND = "http://127.0.0.1:3001/zh"


class _ArgumentError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unrecognized argument values, which may be sensitive.
        raise _ArgumentError("strategy_cli_arguments_invalid")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Read, save and explicitly validate fixed strategy versions.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    commands.add_parser("list", help="Read saved strategy summaries.")
    commands.add_parser("factor-options", help="Read registered and frozen formula options.")
    show = commands.add_parser("show", help="Read one exact strategy version.")
    show.add_argument("strategy_id")
    study = commands.add_parser("import-study", help="Save one observed, available study item.")
    study.add_argument("run_id")
    study.add_argument("profile_id")
    study.add_argument("--title")
    backtest = commands.add_parser("import-backtest", help="Save an existing real-data backtest.")
    backtest.add_argument("run_id")
    backtest.add_argument("--title")
    commands.add_parser("compose", help="Read one strict ComposeStrategy JSON object from stdin.")
    for name in ("validate", "enable"):
        action = commands.add_parser(name, help="Explicit digest-bound " + name + " operation.")
        action.add_argument("strategy_id")
        action.add_argument("--expected-digest", required=True)
    return parser


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value: Any):
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def _reason(value: Any) -> str | None:
    if value is None:
        return None
    candidate = value if isinstance(value, str) else _object(value).get("code")
    return (
        candidate
        if isinstance(candidate, str) and _CODE.fullmatch(candidate)
        else "detail_unavailable"
    )


def _validation(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    comparison, gates = _object(value.get("comparison")), _object(value.get("gates"))
    dsr, cost = _object(gates.get("dsr")), _object(gates.get("cost"))
    signal = _object(value.get("signal_analysis"))
    return {
        "run_id": value.get("run_id"),
        "definition_digest": value.get("definition_digest"),
        "start": value.get("start"),
        "end": value.get("end"),
        "simulation_allocation_usd": _number(value.get("simulation_allocation_usd")),
        "platform_metrics": {
            key: _number(_object(value.get("platform_metrics")).get(key)) for key in _METRICS
        },
        # Sibling of platform_metrics: the nested active blocks must not pass through
        # _METRICS, whose numeric whitelist would silently turn them into None.
        "active_metrics": _object(value.get("active_metrics")),
        "comparison": {
            "accepted": comparison.get("accepted") is True,
            "daily_return_correlation": _number(comparison.get("daily_return_correlation")),
            "terminal_nav_difference_bps": _number(comparison.get("terminal_nav_difference_bps")),
        },
        "gates": {
            "dsr_passed": dsr.get("passed") is True,
            "cost_passed": cost.get("passed") is True,
            "max_hung_correlation": _number(gates.get("max_hung_correlation")),
        },
        "signal_analysis": {
            "status": signal.get("status"),
            "rank_ic": _number(_object(_object(signal.get("score")).get("all")).get("rank_ic")),
            "ridge_status": _object(signal.get("ridge")).get("status"),
        },
        "blockers": [_reason(item) for item in value.get("blockers", [])],
        "historical_scope": value.get("historical_scope"),
        "forward_status": value.get("forward_status"),
    }


def _factor(value: dict) -> dict:
    return {
        key: value.get(key)
        for key in (
            "factor_id",
            "label",
            "expression",
            "lookback",
            "direction",
            "weight",
            "factor_version",
            "source_digest",
        )
        if key in value
    }


def _entry(value: dict) -> dict:
    identifier = str(value.get("strategy_id", ""))
    definition, origin = _object(value.get("definition")), _object(value.get("origin"))
    links = {
        "strategy": f"{_FRONTEND}/strategy-library?strategy={quote(identifier, safe='')}",
        "record": "http://127.0.0.1:8765/api/strategy-library/" + quote(identifier, safe=""),
    }
    if origin.get("type") == "backtest" and origin.get("run_id"):
        links["origin"] = f"{_FRONTEND}/backtest/{quote(str(origin['run_id']), safe='')}"
    elif origin.get("type") == "study" and origin.get("run_id") and origin.get("profile_id"):
        links["origin"] = (
            "http://127.0.0.1:8765/api/strategy-studies/"
            + quote(str(origin["run_id"]), safe="")
            + "/profiles/"
            + quote(str(origin["profile_id"]), safe="")
        )
    if value.get("sleeve_id"):
        links["paper"] = f"{_FRONTEND}/paper-trading"
    recipe = {
        key: definition.get(key)
        for key in (
            "kind",
            "symbols",
            "benchmark_symbol",
            "rebalance",
            "top_n",
            "normalization",
            "max_weight_per_symbol",
            "target_gross_exposure",
            "min_order_value",
            "history_start",
            "whole_share_orders",
            "commission_bps",
            "slippage_bps",
        )
        if key in definition
    }
    recipe["factors"] = [_factor(item) for item in definition.get("factors", [])]
    if definition.get("formula"):
        recipe["formula"] = {
            key: _object(definition["formula"]).get(key)
            for key in (
                "expression",
                "lookback",
                "eligibility_window",
                "require_monthly_history",
            )
        }
    return {
        "strategy_id": identifier,
        "title": value.get("title"),
        "definition_digest": value.get("definition_digest"),
        "status": value.get("status"),
        "created_at": value.get("created_at"),
        "definition": recipe,
        "candidate_id": value.get("candidate_id"),
        "sleeve_id": value.get("sleeve_id"),
        "execution_ready": value.get("execution_ready"),
        "activation_blockers": [_reason(item) for item in value.get("activation_blockers", [])],
        "validation": _validation(value.get("validation")),
        "error": _reason(value.get("error")),
        "links": links,
    }


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("strategy_compose_duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("strategy_compose_nonfinite_json")


def _compose_input(stream: TextIO) -> ComposeStrategy:
    text = stream.read(_MAX_JSON_BYTES + 1)
    if len(text.encode("utf-8")) > _MAX_JSON_BYTES:
        raise ValueError("strategy_compose_input_too_large")
    try:
        raw = json.loads(text, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ValueError("strategy_compose_json_invalid") from exc
    return ComposeStrategy.model_validate(raw)


def _dispatch(args, settings, stream):
    if args.command == "list":
        return {"items": [_entry(item) for item in service.list_strategies(settings)["items"]]}
    if args.command == "factor-options":
        return {
            "factors": [
                {
                    **_factor(item),
                    "origin": item.get("origin") if isinstance(item.get("origin"), str) else None,
                }
                for item in service.factor_options(settings)["factors"]
            ]
        }
    if args.command == "show":
        result = service.read_strategy(settings, args.strategy_id)
    elif args.command == "import-study":
        request = StudyImport(run_id=args.run_id, profile_id=args.profile_id, title=args.title)
        result = service.import_study(
            settings, request.run_id, request.profile_id, title=request.title
        )
    elif args.command == "import-backtest":
        request = BacktestImport(run_id=args.run_id, title=args.title)
        result = service.import_backtest(settings, request.run_id, title=request.title)
    elif args.command == "compose":
        request = _compose_input(stream)
        result = service.compose_strategy(settings, request.model_dump(mode="json"))
    else:
        request = StrategyAction(expected_digest=args.expected_digest)
        action = (
            service.validate_strategy if args.command == "validate" else service.enable_strategy
        )
        result = action(settings, args.strategy_id, request.expected_digest)
    return _entry(result)


def main(argv=None, *, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    stream, output = (
        stdin if stdin is not None else sys.stdin,
        stdout if stdout is not None else sys.stdout,
    )
    action = None
    try:
        args = build_parser().parse_args(argv)
        action = args.command
        # Domain functions own all effects and gates. Their verbose diagnostics
        # are not a Hermes receipt and must not leak into structured output.
        with (
            open(os.devnull, "w") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            settings = load_settings().model_copy(deep=True)
            if not settings.data.data_dir.is_absolute():
                settings.data.data_dir = (
                    Path(__file__).resolve().parents[3] / settings.data.data_dir
                )
            result = _dispatch(args, settings, stream)
        failed = action in {"validate", "enable"} and result.get("status") in {
            "validation_failed",
            "stale",
        }
        if action == "enable" and not (
            result.get("status") == "paper_running" and result.get("sleeve_id")
        ):
            failed = True
            result["error"] = result.get("error") or "strategy_enable_not_confirmed"
        payload = {"contract": CONTRACT, "action": action, "ok": not failed, **result}
        code = 1 if failed else 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        error = (
            "strategy_request_schema_invalid"
            if isinstance(exc, ValidationError)
            else "strategy_record_not_found"
            if isinstance(exc, FileNotFoundError)
            else _reason(str(exc))
        )
        payload = {
            "contract": CONTRACT,
            "action": action,
            "ok": False,
            "status": "error",
            "error": error,
        }
        code = 2
    except KeyboardInterrupt:
        payload = {
            "contract": CONTRACT,
            "action": action,
            "ok": False,
            "status": "outcome_unknown",
            "error": "strategy_cli_interrupted",
        }
        code = 130
    except Exception as exc:
        payload = {
            "contract": CONTRACT,
            "action": action,
            "ok": False,
            "status": "error",
            "error": "strategy_cli_failed",
            "error_type": type(exc).__name__,
        }
        code = 2
    output.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
