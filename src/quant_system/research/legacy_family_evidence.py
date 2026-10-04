"""Read-only compatibility proof for archived, ledger-bound legacy evaluations.

Only CurrentFamilyResolver.legacy calls this adapter. It never grants current
execution identity, changes a historical definition, or appends a trial.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from pathlib import Path

import pandas as pd

from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2.family import COMPATIBILITY_SCHEMA, _compatibility_contract
from quant_system.research.strategy_definition import _digest, _profile_semantics
from quant_system.research.trials import universe_digest

# Existing account/cost audit tolerances, in USD and shares respectively.
ACCOUNTING_ATOL_USD = 1e-7
QUANTITY_ATOL = 1e-9
_FEE_DECLARATION = re.compile(
    r"无杠杆、无做空；单边佣金([0-9]+(?:\.[0-9]+)?)bp、滑点([0-9]+(?:\.[0-9]+)?)bp，"
    r"现金利息为0，未模拟税收和额外冲击。"
)
_DATA_DECLARATION = "Futu 1d QFQ不保证含分红再投资的总回报；无外汇转换，所有标的采用美元报价。"


def _require(condition, reason):
    if not condition:
        raise ValueError("legacy_family_" + reason)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _used_price(quotes, day, symbol):
    value = float(quotes[(day, symbol)])
    _require(_number(value) and value > 0, "used_price_invalid")
    return value


def _definition_contract(row, payload):
    raw = payload.get("definition")
    _require(isinstance(raw, dict) and raw.get("schema_version") == 1, "definition_schema_unproven")
    canonical = {k: v for k, v in raw.items() if k not in {"title", "content_digest"}}
    if raw.get("profile_snapshot") is not None:
        canonical["profile_snapshot"] = _profile_semantics(raw["profile_snapshot"])
    _require(
        _digest(canonical)
        == raw.get("content_digest")
        == payload.get("definition_digest")
        == row["metadata"].get("strategy_definition_digest")
        and isinstance(raw.get("source_fingerprints"), dict)
        and raw["source_fingerprints"],
        "definition_original_digest_mismatch",
    )
    # Do not instantiate today's schema or insert history_start into old v1.
    _require(
        raw.get("provider") == "futu"
        and raw.get("price_adjustment") == "qfq"
        and raw.get("interval") == "1d"
        and raw.get("calendar") == "NYSE"
        and raw.get("execution_price") == "next_open"
        and raw.get("cash_rule") == "unallocated_cash_zero_interest",
        "definition_market_or_cash_contract_unproven",
    )
    _require(
        raw.get("benchmark_symbol") == payload["profile"].get("benchmark_symbol")
        and raw.get("symbols") == payload["profile"].get("symbols")
        and universe_digest(raw["symbols"]) == row["universe_digest"],
        "definition_universe_or_benchmark_mismatch",
    )
    return raw["commission_bps"], raw["slippage_bps"], "frozen_definition_v1"


def _study_contract(payload):
    # These declarations are in the entire profile hashed into recorded-study's
    # run_id. Neither today's fee constants nor the unbound costs summary is proof.
    declarations = payload["profile"].get("limitations") or []
    fee = [
        match
        for line in declarations
        if isinstance(line, str) and (match := _FEE_DECLARATION.fullmatch(line))
    ]
    _require(
        len(fee) == 1 and _DATA_DECLARATION in declarations,
        "study_profile_cost_or_currency_contract_unbound",
    )
    return float(fee[0].group(1)), float(fee[0].group(2)), "ledger_hashed_profile_declarations"


def _accounting(payload, prices, initial, commission_bps, slippage_bps):
    curve, trades = payload["curve"], payload.get("trades")
    _require(isinstance(trades, list), "original_fills_missing")
    dates = [mark["date"] for mark in curve]
    _require(dates == sorted(set(dates)), "curve_calendar_invalid")
    bars = prices.copy()
    bars["date"] = pd.to_datetime(bars.timestamp, utc=True).dt.strftime("%Y-%m-%d")
    bars = bars.set_index(["date", "symbol"], verify_integrity=True)
    opens, closes = bars["open"].to_dict(), bars["close"].to_dict()
    grouped = {}
    for trade in trades:
        _require(
            trade.get("date") in dates
            and trade.get("side") in {"buy", "sell"}
            and trade.get("symbol") in payload["profile"]["symbols"],
            "fill_identity_invalid",
        )
        _require(
            all(
                _number(trade.get(k)) and trade[k] >= 0
                for k in ("quantity", "requested_price", "fill_price", "commission")
            )
            and trade["quantity"] > 0
            and trade["requested_price"] > 0,
            "fill_values_invalid",
        )
        opened = _used_price(opens, trade["date"], trade["symbol"])
        sign = 1 if trade["side"] == "buy" else -1
        _require(
            abs(trade["requested_price"] - opened) <= 1e-10
            and abs(trade["fill_price"] - opened * (1 + sign * slippage_bps / 10000)) <= 1e-10,
            "fill_price_contract_mismatch",
        )
        _require(
            abs(
                trade["commission"]
                - trade["quantity"] * trade["fill_price"] * commission_bps / 10000
            )
            <= ACCOUNTING_ATOL_USD,
            "fill_commission_contract_mismatch",
        )
        grouped.setdefault(trade["date"], []).append(trade)
    cash, held, errors = initial, {}, []
    for mark in curve:
        for trade in grouped.get(mark["date"], []):
            symbol = trade["symbol"]
            sign = 1 if trade["side"] == "buy" else -1
            cash -= sign * trade["quantity"] * trade["fill_price"] + trade["commission"]
            held[symbol] = held.get(symbol, 0.0) + sign * trade["quantity"]
            _require(
                _number(held[symbol]) and held[symbol] >= -QUANTITY_ATOL,
                "position_short_or_incomplete",
            )
        _require(_number(cash) and cash >= -ACCOUNTING_ATOL_USD, "cash_negative_or_nonfinite")
        nav = cash + math.fsum(
            quantity * _used_price(closes, mark["date"], symbol)
            for symbol, quantity in held.items()
            if quantity != 0
        )
        _require(
            _number(nav) and nav > 0 and _number(mark["equity"]) and mark["equity"] > 0,
            "nav_invalid",
        )
        error = abs(nav - mark["equity"])
        _require(_number(error), "nav_error_nonfinite")
        errors.append(error)
    _require(max(errors) <= ACCOUNTING_ATOL_USD, "nav_accounting_mismatch")
    benchmark = payload["profile"]["benchmark_symbol"]
    opened = _used_price(opens, dates[0], benchmark)
    fill = opened * (1 + slippage_bps / 10000)
    _require(_number(fill) and fill > 0, "benchmark_fill_invalid")
    quantity = initial / (fill * (1 + commission_bps / 10000))
    fee = quantity * fill * commission_bps / 10000
    remaining = initial - quantity * fill - fee
    _require(
        _number(quantity) and quantity > 0 and _number(fee) and _number(remaining),
        "benchmark_accounting_nonfinite",
    )
    benchmark_errors = []
    for day, mark in zip(dates, curve, strict=True):
        _require(_number(mark["benchmark"]) and mark["benchmark"] > 0, "benchmark_mark_invalid")
        nav = remaining + quantity * _used_price(closes, day, benchmark)
        _require(_number(nav) and nav > 0, "benchmark_nav_invalid")
        error = abs(nav - mark["benchmark"])
        _require(_number(error), "benchmark_error_nonfinite")
        benchmark_errors.append(error)
    _require(max(benchmark_errors) <= ACCOUNTING_ATOL_USD, "benchmark_not_proven_net_buy_and_hold")
    return {
        "method": "original_fills_cash_positions_close_nav/v1",
        "initial_cash": initial,
        "trades": len(trades),
        "sessions": len(curve),
        "accounting_atol_usd": ACCOUNTING_ATOL_USD,
        "rtol": 0,
        "max_nav_error_usd": max(errors),
        "max_benchmark_error_usd": max(benchmark_errors),
        "benchmark_method": "net_buy_and_hold",
    }


def recover_legacy_family_contract(data_root, row, payload):
    """Enrich authenticated old inputs; retain a specific gap on failed proof."""
    if not isinstance(payload, dict):
        return payload
    base = copy.deepcopy(payload)
    for key in ("family_contract", "family_evidence", "legacy_contract_reason"):
        base.pop(key, None)
    try:
        root = Path(data_root).resolve()
        row = row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row)
        proof = base["legacy_evidence"]
        _require(
            proof["original_trial"] == row and proof["run_id"] == row["metadata"]["run_id"],
            "trial_binding_mismatch",
        )
        files = dict(proof["files"])
        _require(files, "original_files_missing")
        for name, expected in files.items():
            path = Path(name).resolve(strict=True)
            _require(
                path.is_file() and path.is_relative_to(root) and _sha(path) == expected,
                "original_file_changed",
            )
        prices_paths = [Path(p) for p in files if Path(p).name == "prices.parquet"]
        _require(len(prices_paths) == 1, "original_prices_missing")
        prices_path = prices_paths[0]
        if proof["type"] == "recorded_study":
            _require(
                row["metadata"]["run_id"]
                == "recorded-study-"
                + _hash(
                    {
                        "profile": base["profile"],
                        "prices": files[str(prices_path)],
                        "curve": base["curve"],
                    }
                ),
                "study_input_binding_mismatch",
            )
            commission, slippage, origin = _study_contract(base)
        else:
            _require(proof["type"] == "validation_receipts", "producer_unsupported")
            commission, slippage, origin = _definition_contract(row, base)
        _require(all(_number(v) and v >= 0 for v in (commission, slippage)), "fees_invalid")
        _require(
            base.get("source") == "futu"
            and base.get("price_adjustment") == "qfq"
            and base.get("frequency") == "daily",
            "return_frequency_or_provider_mismatch",
        )
        for key in ("costs", "benchmark_costs"):
            costs = base.get(key) or {}
            _require(
                costs.get("commission_bps") == commission
                and costs.get("slippage_bps") == slippage
                and costs.get("cash_interest_rate") == 0,
                "reported_costs_contradict_bound_contract",
            )
        prices = pd.read_parquet(prices_path)
        interval = "interval" if "interval" in prices else "bar"
        _require(
            set(prices.provider) == {"futu"}
            and set(prices.price_adjustment) == {"qfq"}
            and set(prices[interval]) == {"1d"},
            "original_price_contract_mismatch",
        )
        total = row["total_return"]
        _require(_number(total) and total > -1, "bound_total_return_invalid")
        inferred = base["curve"][-1]["equity"] / (1 + total)
        initial = base.get("evaluation_initial_cash", inferred)
        _require(
            _number(initial) and initial > 0 and abs(initial - inferred) <= ACCOUNTING_ATOL_USD,
            "initial_cash_binding_mismatch",
        )
        reconstruction = _accounting(base, prices, initial, commission, slippage)
        reconstruction["initial_cash_source"] = (
            "original_evaluation_initial_cash"
            if "evaluation_initial_cash" in base
            else "ledger_total_return_and_bound_terminal_equity"
        )
        contract = _compatibility_contract(
            {
                "schema": COMPATIBILITY_SCHEMA,
                "return_definition": "arithmetic_net_active",
                "benchmark": {
                    "symbol": base["profile"]["benchmark_symbol"],
                    "method": reconstruction["benchmark_method"],
                },
                "frequency": base["frequency"],
                "cost_definition": {
                    "model": "proportional_bps",
                    "commission_bps": commission,
                    "slippage_bps": slippage,
                    "cash_interest": 0.0,
                },
                "market_data_contract": {
                    "provider": "futu",
                    "price_adjustment": "qfq",
                    "currency": "USD",
                    "bar": "1d",
                },
            }
        )
        _require(
            all(_sha(path) == expected for path, expected in files.items()),
            "original_changed_during_read",
        )
        return {
            **base,
            "evaluation_initial_cash": initial,
            # The compatibility projection and its exact legacy recheck must
            # use the same proved basis. Preserve the archived reader's old
            # default separately; never round the inferred value or alter files.
            "legacy_evidence": {
                **proof,
                "archived_reader_initial_cash": proof.get(
                    "archived_reader_initial_cash", proof["initial_cash"]
                ),
                "initial_cash": initial,
            },
            "family_contract": contract,
            "family_evidence": {
                "adapter": "ledger_bound_legacy_contract/v1",
                "trial_digest": _hash(row),
                "curve_digest": _hash(base["curve"]),
                "files": files,
                "contract_source": origin,
                "reconstruction": reconstruction,
                "current_execution_authority": False,
            },
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        return {**base, "legacy_contract_reason": str(exc)}
