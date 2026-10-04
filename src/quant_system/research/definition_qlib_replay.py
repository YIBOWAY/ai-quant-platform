"""Native Qlib execution of saved definition targets, independent of Platform fills.

No signal/factor is recomputed here. This verifies execution consistency only,
using Qlib's actual Exchange, SimulatorExecutor and Position on the same snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.d34.qlib_adapter import build_qlib_provider

ONE_WAY_COST = 0.0006
CONTRACT = "quant_system.definition_qlib_replay/v1"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _day(value) -> str:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("qlib_replay_invalid_date")
    return stamp.strftime("%Y-%m-%d")


def prepare_replay(prices: pd.DataFrame, result: dict) -> dict:
    """Reject unsupported input before Qlib can silently substitute a quote/calendar."""
    if result.get("status") != "available":
        raise ValueError("qlib_replay_platform_result_unavailable")
    definition = result["definition"]
    symbols = list(definition["symbols"])
    benchmark = definition["benchmark_symbol"]
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("qlib_replay_invalid_universe")
    if definition.get("whole_share_orders", False):
        raise ValueError("qlib_replay_fractional_shares_required")
    if definition.get("commission_bps", 1) != 1 or definition.get("slippage_bps", 5) != 5:
        raise ValueError("qlib_replay_unsupported_costs")
    if definition.get("execution_price", "next_open") != "next_open":
        raise ValueError("qlib_replay_next_open_required")
    initial = float(result.get("evaluation_initial_cash", definition["initial_cash"]))
    minimum = float(definition.get("min_order_value", 0))
    if not math.isfinite(initial) or initial <= 0 or not math.isfinite(minimum) or minimum < 0:
        raise ValueError("qlib_replay_invalid_cash_or_order_threshold")
    curve = result.get("curve", [])
    dates = [_day(row["date"]) for row in curve]
    if not dates or dates != sorted(set(dates)):
        raise ValueError("qlib_replay_invalid_platform_calendar")
    if any(not math.isfinite(float(row["equity"])) or row["equity"] <= 0 for row in curve):
        raise ValueError("qlib_replay_invalid_platform_nav")
    if dates[0] != _day(result["start"]) or dates[-1] != _day(result["end"]):
        raise ValueError("qlib_replay_platform_period_mismatch")
    required = {"timestamp", "symbol", "open", "high", "low", "close", "volume"}
    if prices.empty or not required.issubset(prices):
        raise ValueError("qlib_replay_prices_missing_fields")
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame.timestamp, utc=True).dt.strftime("%Y-%m-%d")
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("qlib_replay_duplicate_prices")
    for key, expected in (("provider", "futu"), ("price_adjustment", "qfq")):
        if key in frame and set(frame[key]) != {expected}:
            raise ValueError(f"qlib_replay_{key}_mismatch")
    benchmark_dates = sorted(
        frame.loc[
            (frame.symbol == benchmark) & frame.date.between(dates[0], dates[-1]), "date"
        ].tolist()
    )
    if benchmark_dates != dates:
        raise ValueError("qlib_replay_snapshot_calendar_mismatch")
    # Qlib's exchange calendar is the union of snapshot instruments. Extra
    # sessions would otherwise be returned and could be mistaken for observations.
    snapshot_dates = sorted(set(frame.loc[frame.date.between(dates[0], dates[-1]), "date"]))
    if snapshot_dates != dates:
        raise ValueError("qlib_replay_snapshot_extra_sessions")
    targets = {}
    quotes = frame.set_index(["date", "symbol"])
    for signal in result.get("signals", []):
        date = _day(signal["trade_date"])
        if date not in dates or date in targets:
            raise ValueError("qlib_replay_signal_date_mismatch")
        weights = signal.get("targets")
        if weights is not None:
            if not isinstance(weights, dict) or set(weights) - set(symbols):
                raise ValueError("qlib_replay_target_universe_mismatch")
            if any(not math.isfinite(float(w)) or float(w) < 0 for w in weights.values()):
                raise ValueError("qlib_replay_invalid_weights")
            if sum(float(w) for w in weights.values()) > 1 + 1e-10:
                raise ValueError("qlib_replay_leverage_not_supported")
            for symbol in weights:
                if (date, symbol) not in quotes.index:
                    raise ValueError(f"qlib_replay_missing_target_quote:{date}:{symbol}")
                for field in ("open", "close"):
                    price = float(quotes.loc[(date, symbol), field])
                    if not math.isfinite(price) or price <= 0:
                        raise ValueError(f"qlib_replay_invalid_target_{field}:{date}:{symbol}")
        targets[date] = weights
    if not targets:
        raise ValueError("qlib_replay_saved_signals_required")
    return {
        "dates": dates,
        "targets": targets,
        "symbols": symbols,
        "benchmark": benchmark,
        "initial_cash": initial,
        "min_order_value": minimum,
        "quotes": quotes,
        "definition": definition,
    }


def plan_open_orders(*, holdings, cash, opens, targets, min_order_value=0.0) -> list[dict]:
    """Size independent simple orders, without importing the Platform trading kernel."""
    if targets is None:
        return []
    symbols = sorted(set(holdings) | set(targets))
    if any(s not in opens or not math.isfinite(opens[s]) or opens[s] <= 0 for s in symbols):
        raise ValueError("qlib_replay_missing_open")
    if not math.isfinite(cash) or cash < -1e-7:
        raise ValueError("qlib_replay_invalid_position_cash")
    equity = cash + sum(quantity * opens[symbol] for symbol, quantity in holdings.items())
    legs = []
    for symbol in symbols:
        notional = equity * targets.get(symbol, 0) - holdings.get(symbol, 0) * opens[symbol]
        if abs(notional) < min_order_value or notional == 0:
            continue
        legs.append(
            {
                "symbol": symbol,
                "side": "buy" if notional > 0 else "sell",
                "quantity": abs(notional) / opens[symbol],
            }
        )
    legs.sort(key=lambda row: (row["side"] != "sell", row["symbol"]))
    remaining = max(cash, 0)
    orders = []
    for leg in legs:
        symbol, quantity = leg["symbol"], leg["quantity"]
        if leg["side"] == "sell":
            quantity = min(quantity, holdings.get(symbol, 0))
            remaining += quantity * opens[symbol] * (1 - ONE_WAY_COST)
        else:
            quantity = min(quantity, remaining / (opens[symbol] * (1 + ONE_WAY_COST)))
            remaining -= quantity * opens[symbol] * (1 + ONE_WAY_COST)
        # Qlib ignores trade values <= 1e-5. Do not count these as executions.
        if quantity * opens[symbol] > 1e-5:
            orders.append({**leg, "quantity": quantity})
    return orders


def _strategy(prepared):
    from qlib.backtest.decision import Order, TradeDecisionWO
    from qlib.strategy.base import BaseStrategy

    class SavedTargetStrategy(BaseStrategy):
        def __init__(self):
            super().__init__()
            self.fills = []

        def _quote(self, symbol, start, end, field):
            key = (_day(start), symbol)
            quotes = prepared["quotes"]
            if key not in quotes.index:
                raise ValueError(f"qlib_replay_missing_{field}:{key[0]}:{symbol}")
            raw = float(quotes.loc[key, field])
            if not math.isfinite(raw) or raw <= 0:
                raise ValueError(f"qlib_replay_invalid_{field}:{key[0]}:{symbol}")
            # Read the exact Qlib quote directly: Exchange.get_deal_price would
            # otherwise silently substitute close for a missing opening price.
            value = self.trade_exchange.quote.get_data(
                symbol, start, end, field="$" + field, method="ts_data_last"
            )
            if value is None or not math.isfinite(float(value)) or value <= 0:
                raise ValueError(f"qlib_replay_missing_provider_{field}:{key[0]}:{symbol}")
            if not math.isclose(raw, float(value), rel_tol=1e-6, abs_tol=1e-8):
                raise ValueError(f"qlib_replay_provider_quote_mismatch:{key[0]}:{symbol}")
            return float(value)

        def generate_trade_decision(self, execute_result=None):
            start, end = self.trade_calendar.get_step_time()
            day = _day(start)
            if day not in prepared["dates"]:
                raise ValueError("qlib_replay_unexpected_session")
            position = self.trade_position
            holdings = {s: float(position.get_stock_amount(s)) for s in position.get_stock_list()}
            targets = prepared["targets"].get(day)
            symbols = set(holdings) | set(targets or {})
            # Every held session must have a close; Qlib normally retains stale
            # marks for suspended/missing quotes, which this audit rejects.
            opens = {}
            for symbol in symbols:
                opens[symbol] = self._quote(symbol, start, end, "open")
                self._quote(symbol, start, end, "close")
            planned = plan_open_orders(
                holdings=holdings,
                cash=float(position.get_cash()),
                opens=opens,
                targets=targets,
                min_order_value=prepared["min_order_value"],
            )
            orders = [
                Order(
                    stock_id=row["symbol"],
                    amount=row["quantity"],
                    direction=Order.BUY if row["side"] == "buy" else Order.SELL,
                    start_time=start,
                    end_time=end,
                )
                for row in planned
            ]
            return TradeDecisionWO(orders, self)

        def post_exe_step(self, execute_result):
            for order, value, cost, price in execute_result or []:
                if order.deal_amount <= 0 or not math.isfinite(float(price)):
                    raise ValueError("qlib_replay_order_not_executed")
                self.fills.append(
                    {
                        "date": _day(order.start_time),
                        "symbol": order.stock_id,
                        "side": "buy" if order.direction == Order.BUY else "sell",
                        "quantity": float(order.deal_amount),
                        "fill_price": float(price),
                        "value": float(value),
                        "cost": float(cost),
                    }
                )

    return SavedTargetStrategy()


def normalize_qlib_report(report, positions, prepared):
    required = {"account", "cash", "return", "cost"}
    if report.empty or not required.issubset(report):
        raise ValueError("qlib_replay_empty_report")
    dates = [_day(day) for day in report.index]
    if dates != prepared["dates"]:
        raise ValueError("qlib_replay_return_calendar_mismatch")
    values = report[list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (report.account <= 0).any():
        raise ValueError("qlib_replay_nonfinite_report")
    equity = report.account.to_numpy(dtype=float)
    net_returns = report["return"].to_numpy(dtype=float) - report.cost.to_numpy(dtype=float)
    accounting_returns = equity / np.r_[prepared["initial_cash"], equity[:-1]] - 1
    if not np.allclose(net_returns, accounting_returns, rtol=0, atol=1e-10):
        raise ValueError("qlib_replay_account_returns_mismatch")
    if sorted(_day(day) for day in positions) != dates:
        raise ValueError("qlib_replay_position_calendar_mismatch")
    final = positions[max(positions)]
    terminal = float(final.calculate_value())
    if not math.isfinite(terminal) or not math.isclose(terminal, equity[-1], rel_tol=1e-12):
        raise ValueError("qlib_replay_terminal_position_mismatch")
    weights = {
        symbol: float(weight)
        for symbol, weight in final.get_stock_weight_dict(only_stock=False).items()
    }
    if (
        any(not math.isfinite(w) or w < 0 for w in weights.values())
        or sum(weights.values()) > 1 + 1e-7
    ):
        raise ValueError("qlib_replay_invalid_terminal_weights")
    return {
        "daily_returns": net_returns.tolist(),
        "return_dates": dates,
        "curve": [
            {"date": day, "equity": float(value), "cash": float(cash)}
            for day, value, cash in zip(dates, equity, report.cash, strict=True)
        ],
        "terminal_nav": terminal,
        "terminal_nav_unit": "USD",
        "terminal_nav_multiple": terminal / prepared["initial_cash"],
        "terminal_weights": weights,
        "terminal_cash": float(final.get_cash()),
    }


def replay_definition(
    prices_path: Path, result_path: Path, *, output_root: Path, qlib_repo: Path = Path("/opt/qlib")
) -> dict:
    import qlib
    from qlib.backtest.executor import SimulatorExecutor
    from qlib.contrib.evaluate import backtest_daily

    prices_path, result_path = Path(prices_path), Path(result_path)
    result = json.loads(result_path.read_text())
    prepared = prepare_replay(pd.read_parquet(prices_path), result)
    source_digest = _digest(prices_path)
    commit = (qlib_repo / ".hqa-upstream-commit").read_text().strip()
    receipt = build_qlib_provider(
        snapshot_id="snapshot-" + source_digest[:32],
        snapshot_digest=source_digest,
        snapshot_parquet=prices_path,
        qlib_repo=qlib_repo,
        qlib_commit=commit,
        output_root=output_root,
        python_executable=sys.executable,
    )
    qlib.init(
        provider_uri=str(receipt.provider_uri),
        region="us",
        kernels=1,
        expression_cache=None,
        dataset_cache=None,
    )
    strategy = _strategy(prepared)
    report, positions = backtest_daily(
        start_time=prepared["dates"][0],
        end_time=prepared["dates"][-1],
        strategy=strategy,
        executor=SimulatorExecutor(
            time_per_step="day", generate_portfolio_metrics=True, trade_type="serial"
        ),
        account=prepared["initial_cash"],
        benchmark=prepared["benchmark"],
        exchange_kwargs={
            "deal_price": "$open",
            "open_cost": ONE_WAY_COST,
            "close_cost": ONE_WAY_COST,
            "min_cost": 0,
            "trade_unit": None,
            "limit_threshold": None,
            "volume_threshold": None,
            "codes": sorted(set(prepared["symbols"]) | {prepared["benchmark"]}),
        },
    )
    return {
        "contract": CONTRACT,
        "status": "available",
        "engine": "qlib",
        "qlib_commit": commit,
        "qlib_version": qlib.__version__,
        **normalize_qlib_report(report, positions, prepared),
        "trades": strategy.fills,
        "universe": prepared["symbols"],
        "initial_cash": prepared["initial_cash"],
        "definition_digest": result.get(
            "definition_digest", prepared["definition"].get("content_digest")
        ),
        "execution": {
            "targets": "exact saved trade_date targets; no factor recomputation",
            "price": "$open",
            "mark": "$close",
            "fractional_shares": True,
            "order_sequence": "sell then buy; symbol ascending within side",
            "target_sizing": "opening cash plus existing holdings marked at open",
            "min_order_value": prepared["min_order_value"],
            "cash_limit": "per-order available cash including costs",
            "no_target": "hold",
            "empty_target": "liquidate",
            "terminal_liquidation": False,
        },
        "costs": {
            "one_way_bps": 6.0,
            "min_cost": 0,
            "total": sum(row["cost"] for row in strategy.fills),
            "platform_commission_bps": 1.0,
            "platform_slippage_bps": 5.0,
            "difference_note": (
                "Qlib charges 6bp at unshifted open. Platform shifts price by 5bp and charges "
                "1bp on the fill; the 0.0005bp multiplicative cross-term and binary32 provider "
                "prices preclude bitwise equality."
            ),
        },
        "scope": "execution_consistency_only_not_independent_alpha_validation",
        "source": {
            "replay_source_sha256": _digest(Path(__file__)),
            "prices_sha256": source_digest,
            "platform_result_sha256": _digest(result_path),
            "targets_sha256": _json_digest(prepared["targets"]),
        },
        "provider_receipt": {
            key: getattr(receipt, key)
            for key in (
                "contract",
                "snapshot_id",
                "snapshot_digest",
                "qlib_commit",
                "source_digest",
                "provider_digest",
                "future_calendar_boundary",
                "receipt_digest",
            )
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output = replay_definition(
            args.prices, args.result, output_root=args.output.parent / "qlib-cache"
        )
    except Exception as exc:  # noqa: BLE001 - write explicit failed replay, never fill missing data
        output = {
            "contract": CONTRACT,
            "status": "failed",
            "engine": "qlib",
            "error": f"{type(exc).__name__}: {exc}",
        }
        args.output.write_text(json.dumps(output, ensure_ascii=False, allow_nan=False))
        raise
    args.output.write_text(json.dumps(output, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
