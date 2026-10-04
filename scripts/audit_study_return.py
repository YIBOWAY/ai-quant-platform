#!/usr/bin/env python3
"""Independently audit saved stocks_momentum_12_2 studies, without product imports.

Reference environment: CPython 3.11.15, pandas 2.3.3, numpy 1.26.4,
pyarrow 24.0.0. Install these exact versions for the recorded environment.
Reads only --run-dir and writes only --output-dir; no network or account access.
Signals and execution are reconstructed from prices, not copied from saved signals.
Saved signals/trades/curves are comparison evidence, never replay inputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path

import pandas as pd

INITIAL = 100_000.0
COMMISSION = 0.0001
SLIPPAGE = 0.0005
PROFILE = "stocks_momentum_12_2"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def month_before(month, offset):
    year, number = map(int, month.split("-"))
    ordinal = year * 12 + number - 1 - offset
    year, number = divmod(ordinal, 12)
    return f"{year:04d}-{number + 1:02d}"


def rank_from_prices(calendar, bars, symbols, start, end):
    """Holding month t: close[t-2] / close[t-13] - 1, calendar months."""
    month_ends = {}
    transitions = []
    for previous, current in zip(calendar[:-1], calendar[1:], strict=True):
        if previous[:7] != current[:7]:
            month_ends[previous[:7]] = previous
            if start <= current <= end:
                transitions.append((previous, current))
    rankings, schedule, periods = [], {}, []
    for signal_date, trade_date in transitions:
        holding_month = trade_date[:7]
        numerator_date = month_ends.get(month_before(holding_month, 2))
        denominator_date = month_ends.get(month_before(holding_month, 13))
        scores = []
        for symbol in symbols:
            complete = all(
                month_before(holding_month, n) in month_ends
                and symbol in bars[month_ends[month_before(holding_month, n)]]
                for n in range(1, 14)
            )
            if not complete:
                continue
            numerator = bars[numerator_date][symbol]["close"]
            denominator = bars[denominator_date][symbol]["close"]
            scores.append((symbol, numerator / denominator - 1, numerator, denominator))
        scores.sort(key=lambda pair: (-pair[1], pair[0]))
        chosen = [row[0] for row in scores[:5]] if len(scores) >= 5 else []
        schedule[trade_date] = {symbol: 0.2 for symbol in chosen}
        periods.append(
            {
                "signal_date": signal_date,
                "trade_date": trade_date,
                "numerator_date": numerator_date,
                "denominator_date": denominator_date,
                "eligible_count": len(scores),
                "selected": ",".join(chosen),
            }
        )
        for index, (symbol, score, numerator, denominator) in enumerate(scores, 1):
            rankings.append(
                {
                    "signal_date": signal_date,
                    "trade_date": trade_date,
                    "rank": index,
                    "symbol": symbol,
                    "score": score,
                    "numerator_date": numerator_date,
                    "numerator_close": numerator,
                    "denominator_date": denominator_date,
                    "denominator_close": denominator,
                    "selected": symbol in chosen,
                }
            )
    return rankings, schedule, periods


def apply_trade(holdings, cash, trade):
    symbol, quantity = trade["symbol"], trade["quantity"]
    gross = quantity * trade["fill_price"]
    if trade["side"] == "buy":
        holdings[symbol] = holdings.get(symbol, 0.0) + quantity
        cash -= gross + trade["commission"]
    else:
        holdings[symbol] = holdings.get(symbol, 0.0) - quantity
        cash += gross - trade["commission"]
    if abs(holdings[symbol]) < 1e-10:
        del holdings[symbol]
    return cash


def replay(calendar, bars, schedule, symbols):
    holdings, cash, previous_nav = {}, INITIAL, INITIAL
    previous_close = {}
    daily, trades, contributions, snapshots = [], [], [], []
    for date in calendar:
        todays = bars[date]
        incoming = dict(holdings)
        commissions, slippages = defaultdict(float), defaultdict(float)
        if date in schedule:
            at_open = cash + sum(q * todays[s]["open"] for s, q in holdings.items())
            desired = schedule[date]
            orders = []
            for symbol in sorted(set(holdings) | set(desired)):
                price = todays[symbol]["open"]
                delta_value = desired.get(symbol, 0.0) * at_open - holdings.get(symbol, 0.0) * price
                if delta_value:
                    orders.append((delta_value > 0, symbol, abs(delta_value) / price))
            orders.sort(key=lambda row: row[0])  # Sells first; alphabetical within each side.
            for buying, symbol, requested_quantity in orders:
                opening = todays[symbol]["open"]
                fill_price = opening * (1 + SLIPPAGE if buying else 1 - SLIPPAGE)
                allowed = (
                    max(cash / (fill_price * (1 + COMMISSION)), 0.0)
                    if buying
                    else holdings.get(symbol, 0.0)
                )
                quantity = min(requested_quantity, allowed)
                if quantity <= 0:
                    continue
                fee = quantity * fill_price * COMMISSION
                trade = {
                    "date": date,
                    "symbol": symbol,
                    "side": "buy" if buying else "sell",
                    "quantity": quantity,
                    "requested_price": opening,
                    "fill_price": fill_price,
                    "commission": fee,
                }
                cash = apply_trade(holdings, cash, trade)
                commissions[symbol] += fee
                slippages[symbol] += abs(fill_price - opening) * quantity
                trades.append(trade)
        nav = cash + sum(q * todays[s]["close"] for s, q in holdings.items())
        day_pnl = 0.0
        for symbol in sorted(set(incoming) | set(holdings)):
            opening, closing = todays[symbol]["open"], todays[symbol]["close"]
            overnight = incoming.get(symbol, 0.0) * (opening - previous_close.get(symbol, opening))
            intraday = holdings.get(symbol, 0.0) * (closing - opening)
            net_pnl = overnight + intraday - commissions[symbol] - slippages[symbol]
            day_pnl += net_pnl
            contributions.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "overnight_pnl": overnight,
                    "intraday_pnl": intraday,
                    "commission": commissions[symbol],
                    "slippage": slippages[symbol],
                    "net_pnl": net_pnl,
                }
            )
        if date in schedule:
            for symbol in symbols:
                snapshots.append(
                    {
                        "date": date,
                        "symbol": symbol,
                        "quantity": holdings.get(symbol, 0.0),
                        "close": todays[symbol]["close"],
                        "cash": cash,
                    }
                )
        daily.append(
            {
                "date": date,
                "cash": cash,
                "market_value": nav - cash,
                "nav": nav,
                "pnl": nav - previous_nav,
                "daily_return": nav / previous_nav - 1,
                "attribution_residual": nav - previous_nav - day_pnl,
                "gross_exposure": (nav - cash) / nav,
                "minimum_quantity": min(holdings.values(), default=0.0),
            }
        )
        previous_nav = nav
        previous_close = {s: row["close"] for s, row in todays.items()}
    return daily, trades, contributions, snapshots


def metrics(daily, trades):
    returns = [row["daily_return"] for row in daily]
    ending = daily[-1]["nav"]
    peak, drawdown = INITIAL, 0.0
    for row in daily:
        peak = max(peak, row["nav"])
        drawdown = max(drawdown, 1 - row["nav"] / peak)
    return {
        "total_return": ending / INITIAL - 1,
        "annualized_return": (ending / INITIAL) ** (252 / len(daily)) - 1,
        "volatility": statistics.pstdev(returns) * math.sqrt(252),
        "sharpe": statistics.mean(returns) / statistics.pstdev(returns) * math.sqrt(252),
        "max_drawdown": drawdown,
        "turnover": sum(t["quantity"] * t["fill_price"] for t in trades) / INITIAL,
    }


def audit(run_dir, output_dir):
    result_path, prices_path = run_dir / f"{PROFILE}.json", run_dir / "prices.parquet"
    source_hashes = {
        p.name: sha256(p) for p in (result_path, prices_path, run_dir / "protocol.json")
    }
    original = json.loads(result_path.read_text())
    assert original["profile"]["top_n"] == 5
    assert original["costs"]["commission_bps"] == 1.0
    assert original["costs"]["slippage_bps"] == 5.0
    symbols = list(original["profile"]["peer_symbols"])
    assert len(symbols) == 24 and len(set(symbols)) == 24
    frame = pd.read_parquet(prices_path)
    full_row_count = len(frame)
    frame = frame[frame.symbol.isin(symbols + ["SPY"])].copy()
    frame["date"] = pd.to_datetime(frame.timestamp, utc=True).dt.strftime("%Y-%m-%d")
    assert not frame.duplicated(["date", "symbol"]).any()
    assert set(frame.provider) == {"futu"} and set(frame.price_adjustment) == {"qfq"}
    assert set(frame.interval) == {"1d"}
    for column in ("open", "high", "low", "close"):
        assert all(math.isfinite(x) and x > 0 for x in frame[column])
    bars = defaultdict(dict)
    for row in frame.itertuples(index=False):
        bars[row.date][row.symbol] = {
            "open": row.open,
            "close": row.close,
            "high": row.high,
            "low": row.low,
        }
    calendar = sorted(row for row in bars if "SPY" in bars[row] and row <= original["end"])
    assert not (set(bars) - set(calendar))
    ranks, schedule, periods = rank_from_prices(
        calendar, bars, symbols, original["start"], original["end"]
    )
    evaluation_dates = [date for date in calendar if original["start"] <= date <= original["end"]]
    assert all(set(symbols).issubset(bars[date]) for date in evaluation_dates)
    daily, trades, contributions, snapshots = replay(evaluation_dates, bars, schedule, symbols)
    independently_computed = metrics(daily, trades)
    signal_by_date = {row["trade_date"]: row for row in original["signals"]}
    rank_by_date = defaultdict(list)
    for rank in ranks:
        rank_by_date[rank["trade_date"]].append(rank)
    signal_diffs = []
    for period in periods:
        date = period["trade_date"]
        saved = signal_by_date[date]
        saved_scores = {row["symbol"]: row["score"] for row in saved["scores"]}
        signal_diffs.append(
            {
                **period,
                "signal_date_equal": period["signal_date"] == saved["signal_date"],
                "targets_equal": schedule[date] == saved["targets"],
                "eligible_count_equal": period["eligible_count"] == saved["eligible_count"],
                "rank_order_equal": [r["symbol"] for r in rank_by_date[date]]
                == [r["symbol"] for r in saved["scores"]],
                "max_score_abs_diff": max(
                    abs(row["score"] - saved_scores[row["symbol"]]) for row in rank_by_date[date]
                ),
            }
        )
    saved_trades_by_key = {(t["date"], t["symbol"], t["side"]): t for t in original["trades"]}
    replay_trades_by_key = {(t["date"], t["symbol"], t["side"]): t for t in trades}
    trade_diffs = []
    for key in sorted(set(saved_trades_by_key) | set(replay_trades_by_key)):
        saved, computed = saved_trades_by_key.get(key, {}), replay_trades_by_key.get(key, {})
        row = dict(zip(("date", "symbol", "side"), key, strict=True))
        row["present_in_both"] = bool(saved and computed)
        for field in ("quantity", "requested_price", "fill_price", "commission"):
            row[field + "_abs_diff"] = abs(saved.get(field, 0) - computed.get(field, 0))
        trade_diffs.append(row)
    saved_by_date = defaultdict(list)
    for trade in original["trades"]:
        saved_by_date[trade["date"]].append(trade)
    saved_curve = {row["date"]: row["equity"] for row in original["curve"]}
    assert set(saved_curve) == set(evaluation_dates)
    saved_qty, saved_cash = {}, INITIAL
    computed_snapshots = {(r["date"], r["symbol"]): r for r in snapshots}
    snapshot_diffs = []
    for row in daily:
        date = row["date"]
        for trade in saved_by_date[date]:
            saved_cash = apply_trade(saved_qty, saved_cash, trade)
        saved_rebuilt = saved_cash + sum(q * bars[date][s]["close"] for s, q in saved_qty.items())
        row["saved_nav"] = saved_curve[date]
        row["nav_abs_diff"] = abs(row["nav"] - saved_curve[date])
        row["saved_ledger_nav_abs_diff"] = abs(saved_rebuilt - saved_curve[date])
        row["saved_ledger_cash_abs_diff"] = abs(row["cash"] - saved_cash)
        if date in schedule:
            for symbol in symbols:
                replayed = computed_snapshots[(date, symbol)]
                snapshot_diffs.append(
                    {
                        **replayed,
                        "saved_ledger_quantity": saved_qty.get(symbol, 0.0),
                        "quantity_abs_diff": abs(replayed["quantity"] - saved_qty.get(symbol, 0.0)),
                        "saved_ledger_cash": saved_cash,
                        "cash_abs_diff": abs(replayed["cash"] - saved_cash),
                    }
                )
    by_symbol, by_year_symbol = defaultdict(float, dict.fromkeys(symbols, 0.0)), defaultdict(float)
    for row in contributions:
        by_symbol[row["symbol"]] += row["net_pnl"]
        by_year_symbol[(row["date"][:4], row["symbol"])] += row["net_pnl"]
    total_pnl = daily[-1]["nav"] - INITIAL
    attribution = [
        {
            "symbol": s,
            "net_pnl": pnl,
            "return_contribution_percentage_points": pnl / INITIAL * 100,
            "share_of_net_pnl": pnl / total_pnl,
        }
        for s, pnl in sorted(by_symbol.items(), key=lambda item: -item[1])
    ]
    years = []
    for year in sorted({date[:4] for date in evaluation_dates}):
        group = [row for row in daily if row["date"].startswith(year)]
        first_nav = group[0]["nav"] - group[0]["pnl"]
        last_nav = group[-1]["nav"]
        ranked = sorted(
            ((s, v) for (y, s), v in by_year_symbol.items() if y == year), key=lambda item: -item[1]
        )
        years.append(
            {
                "year": year,
                "starting_nav": first_nav,
                "ending_nav": last_nav,
                "return": last_nav / first_nav - 1,
                "pnl": last_nav - first_nav,
                "largest_contributor": ranked[0][0],
                "largest_contributor_pnl": ranked[0][1],
            }
        )
    jumps = []
    ohlc_invalid = 0
    for symbol in symbols:
        prior = None
        for date in calendar:
            bar = bars[date].get(symbol)
            if bar is None:
                continue
            ohlc_invalid += int(
                bar["low"] > min(bar["open"], bar["close"]) + 1e-7
                or bar["high"] < max(bar["open"], bar["close"]) - 1e-7
            )
            if prior:
                jumps.append(
                    {
                        "date": date,
                        "symbol": symbol,
                        "previous_close": prior,
                        "open": bar["open"],
                        "close": bar["close"],
                        "close_return": bar["close"] / prior - 1,
                        "overnight_return": bar["open"] / prior - 1,
                    }
                )
            prior = bar["close"]
    jumps.sort(key=lambda row: -abs(row["close_return"]))
    commission = sum(t["commission"] for t in trades)
    slippage = sum(abs(t["fill_price"] - t["requested_price"]) * t["quantity"] for t in trades)
    summary = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir.resolve()),
        "source_hashes": source_hashes,
        "audit_script_sha256": sha256(Path(__file__)),
        "environment": {
            "python": platform.python_version(),
            **{p: version(p) for p in ("pandas", "numpy", "pyarrow")},
        },
        "scope": (
            "Independent historical accounting and signal replication; "
            "no alpha validation or production certification"
        ),
        "start": original["start"],
        "end": original["end"],
        "initial_cash": INITIAL,
        "ending_nav": daily[-1]["nav"],
        "session_count": len(daily),
        "signal_count": len(periods),
        "trade_count": len(trades),
        "saved_trade_count": len(original["trades"]),
        "metrics": independently_computed,
        "metric_deltas": {k: v - original["metrics"][k] for k, v in independently_computed.items()},
        "max_daily_nav_abs_diff": max(r["nav_abs_diff"] for r in daily),
        "max_saved_ledger_nav_abs_diff": max(r["saved_ledger_nav_abs_diff"] for r in daily),
        "max_cash_abs_diff": max(r["cash_abs_diff"] for r in snapshot_diffs),
        "max_position_quantity_abs_diff": max(r["quantity_abs_diff"] for r in snapshot_diffs),
        "max_trade_deltas": {
            field: max(r[field + "_abs_diff"] for r in trade_diffs)
            for field in ("quantity", "requested_price", "fill_price", "commission")
        },
        "unmatched_trades": sum(not r["present_in_both"] for r in trade_diffs),
        "signal_mismatches": sum(
            not all(
                r[k]
                for k in (
                    "targets_equal",
                    "signal_date_equal",
                    "eligible_count_equal",
                    "rank_order_equal",
                )
            )
            for r in signal_diffs
        ),
        "max_score_abs_diff": max(r["max_score_abs_diff"] for r in signal_diffs),
        "minimum_cash": min(r["cash"] for r in daily),
        "maximum_gross_exposure": max(r["gross_exposure"] for r in daily),
        "minimum_quantity": min(r["minimum_quantity"] for r in daily),
        "commission": commission,
        "slippage": slippage,
        "total_explicit_cost": commission + slippage,
        "commission_delta": commission - original["costs"]["commission"],
        "slippage_delta": slippage - original["costs"]["slippage"],
        "attribution_total": sum(by_symbol.values()),
        "attribution_residual": total_pnl - sum(by_symbol.values()),
        "maximum_daily_attribution_residual": max(abs(r["attribution_residual"]) for r in daily),
        "input_quality": {
            "full_saved_price_rows": full_row_count,
            "audited_price_rows": len(frame),
            "duplicates": 0,
            "missing_evaluation_bars": 0,
            "invalid_nonpositive_prices": 0,
            "ohlc_envelope_violations": ohlc_invalid,
            "absolute_close_jump_over_50pct": sum(abs(r["close_return"]) > 0.5 for r in jumps),
            "warning": (
                "QFQ snapshot only; no raw unadjusted series or "
                "corporate-action ledger is saved in this run. "
                "Jump inspection cannot certify adjustment correctness."
            ),
        },
        "latest_ranking": rank_by_date[periods[-1]["trade_date"]],
        "symbol_attribution": attribution,
        "yearly_attribution": years,
        "bias": {
            "membership_mode": original["profile"]["membership_mode"],
            "universe_snapshot_date": original["profile"]["universe_snapshot_date"],
            "symbols": symbols,
            "selection_bias_effect": (
                "unquantifiable without historical membership, "
                "delisted securities and a prespecified "
                "selection protocol"
            ),
        },
    }
    summary["accounting_replication_pass"] = (
        summary["max_daily_nav_abs_diff"] < 1e-6
        and summary["max_position_quantity_abs_diff"] < 1e-7
        and summary["signal_mismatches"] == 0
        and summary["unmatched_trades"] == 0
        and summary["maximum_daily_attribution_residual"] < 1e-6
        and summary["minimum_cash"] > -1e-6
        and summary["maximum_gross_exposure"] <= 1 + 1e-10
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "daily-nav-diff.csv", daily)
    write_csv(output_dir / "monthly-signals-diff.csv", signal_diffs)
    write_csv(output_dir / "all-monthly-rankings.csv", ranks)
    write_csv(output_dir / "latest-ranking.csv", summary["latest_ranking"])
    write_csv(output_dir / "trade-diff.csv", trade_diffs)
    write_csv(output_dir / "monthly-cash-position-diff.csv", snapshot_diffs)
    write_csv(output_dir / "independent-trades.csv", trades)
    write_csv(output_dir / "daily-symbol-attribution.csv", contributions)
    write_csv(output_dir / "symbol-attribution.csv", attribution)
    write_csv(output_dir / "yearly-attribution.csv", years)
    write_csv(output_dir / "largest-qfq-price-jumps.csv", jumps[:50])
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    assert source_hashes == {
        p.name: sha256(p) for p in (result_path, prices_path, run_dir / "protocol.json")
    }
    return summary


def compare_saved_runs(current_dir, previous_dir, output_dir):
    fields = ["open", "high", "low", "close", "volume"]
    current = pd.read_parquet(current_dir / "prices.parquet").set_index(["timestamp", "symbol"])
    previous = pd.read_parquet(previous_dir / "prices.parquet").set_index(["timestamp", "symbol"])
    common = previous.index.intersection(current.index)
    current_result = json.loads((current_dir / f"{PROFILE}.json").read_text())
    previous_result = json.loads((previous_dir / f"{PROFILE}.json").read_text())
    current_nav = {row["date"]: row["equity"] for row in current_result["curve"]}
    comparison = {
        "current_run": current_dir.name,
        "previous_run": previous_dir.name,
        "overlapping_price_rows": len(common),
        "max_price_or_volume_difference": (
            current.loc[common, fields] - previous.loc[common, fields]
        )
        .abs()
        .max()
        .to_dict(),
        "max_overlapping_saved_nav_difference": max(
            abs(row["equity"] - current_nav[row["date"]]) for row in previous_result["curve"]
        ),
        "added_dates": sorted(set(current_nav) - {r["date"] for r in previous_result["curve"]}),
        "added_trades": [
            trade for trade in current_result["trades"] if trade["date"] > previous_result["end"]
        ],
        "ending_nav_change": current_result["curve"][-1]["equity"]
        - previous_result["curve"][-1]["equity"],
    }
    (output_dir / "cross-run-diff.json").write_text(
        json.dumps(comparison, indent=2, allow_nan=False) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--compare-run-dir", type=Path)
    args = parser.parse_args()
    if (
        args.run_dir.resolve() == args.output_dir.resolve()
        or args.run_dir.resolve() in args.output_dir.resolve().parents
    ):
        parser.error("Output must be outside the saved run directory")
    summary = audit(args.run_dir, args.output_dir)
    if args.compare_run_dir:
        compare_saved_runs(args.run_dir, args.compare_run_dir, args.output_dir)
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "run_id",
                    "end",
                    "ending_nav",
                    "metrics",
                    "signal_count",
                    "trade_count",
                    "max_daily_nav_abs_diff",
                    "max_position_quantity_abs_diff",
                    "signal_mismatches",
                    "unmatched_trades",
                    "attribution_residual",
                    "accounting_replication_pass",
                )
            },
            indent=2,
        )
    )
    raise SystemExit(0 if summary["accounting_replication_pass"] else 1)


if __name__ == "__main__":
    main()
