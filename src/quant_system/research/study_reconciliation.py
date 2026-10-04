"""Observational cash/lot reconciliation from saved research fills and prices."""

import math
from collections import defaultdict

import pandas as pd

from quant_system.research.reference_backtests import INITIAL_CASH


def reconcile_saved_study(study: dict, prices: pd.DataFrame, as_of: str | None) -> dict:
    curve = study.get("curve", [])
    if not as_of and curve:
        as_of = curve[-1]["date"]
    expected = next((row for row in curve if row["date"] == as_of), None)
    if expected is None or "trades" not in study:
        return {"status": "unavailable", "reason": "该日缺少已保存权益或成交记录"}
    initial_cash = float(study.get("evaluation_initial_cash", INITIAL_CASH))
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        return {"status": "unavailable", "reason": "初始资金无效"}
    cash, commissions, buys, sells = initial_cash, 0.0, 0.0, 0.0
    quantities = defaultdict(float)
    net_flows = defaultdict(float)
    for trade in study["trades"]:
        if trade["date"] > as_of:
            continue
        side = trade["side"]
        quantity, price, fee = (
            float(trade[key]) for key in ("quantity", "fill_price", "commission")
        )
        if side not in {"buy", "sell"} or not all(
            math.isfinite(x) and x >= 0 for x in (quantity, price, fee)
        ):
            return {"status": "unavailable", "reason": "已保存成交字段无效"}
        amount = quantity * price
        sign = 1 if side == "buy" else -1
        quantities[trade["symbol"]] += sign * quantity
        cash -= sign * amount + fee
        net_flows[trade["symbol"]] -= sign * amount + fee
        commissions += fee
        if side == "buy":
            buys += amount
        else:
            sells += amount
    dates = pd.to_datetime(prices.timestamp, utc=True).dt.strftime("%Y-%m-%d")
    closing = prices.loc[dates == as_of].set_index("symbol").close
    positions = []
    for symbol, quantity in sorted(quantities.items()):
        if abs(quantity) < 1e-9:
            continue
        if quantity < 0 or symbol not in closing.index or closing.index.duplicated().any():
            return {"status": "unavailable", "reason": "持仓或该日收盘价证据不完整"}
        price = float(closing[symbol])
        if not math.isfinite(price) or price <= 0:
            return {"status": "unavailable", "reason": "该日收盘价无效"}
        positions.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "close": price,
                "market_value": quantity * price,
            }
        )
    market_value = sum(row["market_value"] for row in positions)
    for position in positions:
        net_flows[position["symbol"]] += position["market_value"]
    equity = cash + market_value
    reported = float(expected["equity"])
    difference = equity - reported
    return {
        "status": "matched" if abs(difference) <= max(0.01, abs(reported) * 1e-10) else "mismatch",
        "as_of": as_of,
        "initial_cash": initial_cash,
        "cash": cash,
        "market_value": market_value,
        "equity": equity,
        "reported_equity": reported,
        "difference": difference,
        "commissions": commissions,
        "buy_notional": buys,
        "sell_notional": sells,
        "positions": positions,
        "attribution": sorted(
            [{"symbol": symbol, "net_profit": amount} for symbol, amount in net_flows.items()],
            key=lambda row: row["net_profit"],
            reverse=True,
        ),
        "method": "已保存成交逐笔重建现金和股数，按同一行情快照当日收盘盯市；未强制平仓",
    }
