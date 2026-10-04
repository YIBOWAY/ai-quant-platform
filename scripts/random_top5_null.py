#!/usr/bin/env python3
"""Null distribution for random Top-N monthly selection inside a saved study universe.

Purpose: give the 2026-09-14 alpha-research-reset plan a reproducible receipt for
statements such as "random Top-5 Sharpe spans 0.56-1.11" and "random pairs of
long-only Top-5 sleeves correlate ~0.7 on raw returns". Read-only on the saved
study run; writes only to --output-dir.

Simplified engine (documented, not the product engine): month-end close signal,
next-session open fill, equal weight, one-way cost = commission+slippage bps on
traded notional, daily NAV marked at close, Sharpe = mean/std(ddof=1)*sqrt(252),
rf = 0. The 12-2 momentum rule is re-implemented only as a sanity anchor; the
official study metrics are read from the saved profile JSON.

Usage:
  ./.venv/bin/python scripts/random_top5_null.py \
      --run-dir <deployment-mirror>/data/strategy_studies/runs/<study-run> \
      --output-dir artifacts/random-top5-null-<date> [--n 2000 --seed 7]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROFILE = "stocks_momentum_12_2"
TOP_N = 5


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ols_resid(y: np.ndarray, x: np.ndarray) -> tuple[float, float, np.ndarray]:
    X = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(beta[0]), float(beta[1]), y - X @ beta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--pairs", type=int, default=3000)
    args = ap.parse_args()

    run = Path(args.run_dir)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    profile = json.loads((run / f"{PROFILE}.json").read_text())
    syms = list(profile["profile"]["symbols"])
    bench = profile["profile"].get("benchmark_symbol", "SPY")
    cost = (
        (profile["costs"]["commission_bps"] + profile["costs"]["slippage_bps"]) / 1e4
        if "costs" in profile
        and isinstance(profile["costs"], dict)
        and "commission_bps" in profile["costs"]
        else 0.0006
    )
    official = profile["metrics"]
    peer = profile.get("peer_metrics", {})
    start, end = profile["start"][:10], profile["end"][:10]

    prices_path = run / "prices.parquet"
    p = pd.read_parquet(prices_path)
    p["date"] = pd.to_datetime(p["timestamp"]).dt.tz_localize(None).dt.normalize()
    close_all = (
        p[p.symbol.isin(syms)]
        .pivot(index="date", columns="symbol", values="close")
        .sort_index()[syms]
    )
    open_all = (
        p[p.symbol.isin(syms)]
        .pivot(index="date", columns="symbol", values="open")
        .sort_index()[syms]
    )
    close_all = close_all.loc[:end].dropna(how="any")
    close = close_all.loc[start:]
    openp = open_all.loc[close.index]
    dates = close.index
    spy = (
        p[p.symbol == bench]
        .set_index("date")["close"]
        .sort_index()
        .reindex(dates)
        .pct_change()
        .iloc[1:]
        .values
    )

    all_dates = close_all.index
    month_ends = pd.DatetimeIndex(
        pd.Series(all_dates, index=all_dates)
        .groupby([all_dates.year, all_dates.month])
        .last()
        .values
    )
    exec_idx = [
        dates.get_loc(d) + 1 for d in month_ends if d in dates and dates.get_loc(d) + 1 < len(dates)
    ]

    cl, op = close.values, openp.values
    n_sym = len(syms)

    def run_weights(weights: dict[int, np.ndarray]):
        nav = np.empty(len(dates))
        nav[0] = 1.0
        hold = np.zeros(n_sym)
        cash = 1.0
        for i in range(1, len(dates)):
            if i in weights:
                hold = hold * (op[i] / cl[i - 1])
                total = cash + hold.sum()
                target = weights[i] * total
                fee = np.abs(target - hold).sum() * cost
                hold = target * (cl[i] / op[i])
                cash = total - target.sum() - fee
            else:
                hold = hold * (cl[i] / cl[i - 1])
            nav[i] = cash + hold.sum()
        r = np.diff(nav) / nav[:-1]
        years = (dates[-1] - dates[0]).days / 365.25
        return {
            "total_return": float(nav[-1] - 1),
            "annualized_return": float(nav[-1] ** (1 / years) - 1),
            "sharpe": float(r.mean() / r.std(ddof=1) * np.sqrt(252)),
            "max_drawdown": float(-(nav / np.maximum.accumulate(nav) - 1).min()),
        }, r

    def momentum_weights():
        w = {}
        for i in exec_idx:
            sig = dates[i - 1]
            me = month_ends[month_ends <= sig]
            if len(me) < 13:
                continue
            mom = close_all.loc[me[-2]] / close_all.loc[me[-13]] - 1
            top = set(mom.sort_values(ascending=False).index[:TOP_N])
            w[i] = np.array([1 / TOP_N if s in top else 0.0 for s in syms])
        return w

    mom_w = momentum_weights()
    first_exec = min(mom_w)
    m_mom, r_mom = run_weights(mom_w)
    m_ew, r_ew = run_weights({i: np.full(n_sym, 1 / n_sym) for i in exec_idx if i >= first_exec})

    rng = np.random.default_rng(args.seed)
    rows, returns = [], []
    for _ in range(args.n):
        w = {}
        for i in exec_idx:
            if i < first_exec:
                continue
            pick = rng.choice(n_sym, TOP_N, replace=False)
            vec = np.zeros(n_sym)
            vec[pick] = 1 / TOP_N
            w[i] = vec
        m, r = run_weights(w)
        rows.append(m)
        returns.append(r)
    df = pd.DataFrame(rows)
    R = np.vstack(returns)

    # correlation of random sleeves with the momentum sleeve, raw and SPY-residual
    _, _, res_mom = ols_resid(r_mom, spy)
    raw_vs_mom, res_vs_mom = [], []
    resid_all = np.empty_like(R)
    for k in range(R.shape[0]):
        raw_vs_mom.append(np.corrcoef(R[k], r_mom)[0, 1])
        _, _, res_k = ols_resid(R[k], spy)
        resid_all[k] = res_k
        res_vs_mom.append(np.corrcoef(res_k, res_mom)[0, 1])
    raw_vs_mom, res_vs_mom = np.array(raw_vs_mom), np.array(res_vs_mom)

    # random pairs of random sleeves
    pair_raw, pair_res = [], []
    for _ in range(args.pairs):
        a, b = rng.choice(R.shape[0], 2, replace=False)
        pair_raw.append(np.corrcoef(R[a], R[b])[0, 1])
        pair_res.append(np.corrcoef(resid_all[a], resid_all[b])[0, 1])
    pair_raw, pair_res = np.array(pair_raw), np.array(pair_res)

    sh = df.sharpe.values
    best_of = {}
    for k in (5, 16, 50):
        best = np.array([rng.choice(sh, k, replace=False).max() for _ in range(5000)])
        best_of[str(k)] = {
            "median": float(np.median(best)),
            "p05": float(np.percentile(best, 5)),
            "p95": float(np.percentile(best, 95)),
        }

    # official study curve: SPY beta/alpha and active return vs the saved peer (equal weight)
    curve = pd.DataFrame(profile["curve"])
    curve["date"] = pd.to_datetime(curve["date"])
    curve = curve.set_index("date").sort_index()
    spy_full = p[p.symbol == bench].set_index("date")["close"].sort_index()
    cr = pd.DataFrame(
        {
            "strategy": curve["equity"].pct_change(),
            "peer": curve["peer"].pct_change(),
            "spy": spy_full.reindex(curve.index).pct_change(),
        }
    ).dropna()
    alpha_d, beta_spy, resid = ols_resid(cr["strategy"].values, cr["spy"].values)
    X = np.column_stack([np.ones(len(cr)), cr["spy"].values])
    s2 = float(resid @ resid) / (len(cr) - 2)
    se_alpha = float(np.sqrt(s2 * np.linalg.inv(X.T @ X)[0, 0]))
    active = (cr["strategy"] - cr["peer"]).values
    official_regression = {
        "beta_spy": beta_spy,
        "alpha_annualized": alpha_d * 252,
        "t_alpha": alpha_d / se_alpha,
        "active_return_vs_peer_annualized": float(active.mean() * 252),
        "information_ratio_vs_peer": float(active.mean() / active.std(ddof=1) * np.sqrt(252)),
        "tracking_error_vs_peer": float(active.std(ddof=1) * np.sqrt(252)),
        "obs": int(len(cr)),
    }

    years = (dates[-1] - dates[0]).days / 365.25
    q = df.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    summary = {
        "generated_for": "docs/plans/2026-09-14-alpha-research-reset.md (HQA)",
        "run_dir": str(run),
        "prices_sha256": sha256(prices_path),
        "profile_sha256": sha256(run / f"{PROFILE}.json"),
        "script_sha256": sha256(Path(__file__)),
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "seed": args.seed,
        "n_random": args.n,
        "n_pairs": args.pairs,
        "universe": syms,
        "eval_window": [str(dates[0].date()), str(dates[-1].date())],
        "eval_days": int(len(dates)),
        "rebalances": int(len([i for i in exec_idx if i >= first_exec])),
        "one_way_cost": cost,
        "official_study_metrics": {
            k: official[k] for k in ("total_return", "annualized_return", "sharpe", "max_drawdown")
        },
        "official_peer_equal_weight": {
            k: peer.get(k) for k in ("total_return", "annualized_return", "sharpe", "max_drawdown")
        },
        "official_curve_regression": official_regression,
        "simplified_engine_momentum": m_mom,
        "simplified_engine_equal_weight": m_ew,
        "random_top5_quantiles": {
            str(k): {c: float(v) for c, v in row.items()} for k, row in q.iterrows()
        },
        "p_random_sharpe_ge_official_momentum": float((sh >= official["sharpe"]).mean()),
        "p_random_sharpe_ge_simplified_momentum": float((sh >= m_mom["sharpe"]).mean()),
        "p_random_sharpe_ge_peer_equal_weight": float((sh >= peer.get("sharpe", np.nan)).mean())
        if peer.get("sharpe")
        else None,
        "p_random_sharpe_ge_1_16": float((sh >= 1.16).mean()),
        "best_of_k_random_sharpe": best_of,
        "corr_random_vs_momentum_raw": {
            "median": float(np.median(raw_vs_mom)),
            "p05": float(np.percentile(raw_vs_mom, 5)),
            "p95": float(np.percentile(raw_vs_mom, 95)),
            "share_gt_0_7": float((raw_vs_mom > 0.7).mean()),
        },
        "corr_random_vs_momentum_spy_residual": {
            "median": float(np.median(res_vs_mom)),
            "p05": float(np.percentile(res_vs_mom, 5)),
            "p95": float(np.percentile(res_vs_mom, 95)),
            "share_gt_0_7": float((res_vs_mom > 0.7).mean()),
        },
        "corr_random_pairs_raw": {
            "median": float(np.median(pair_raw)),
            "p05": float(np.percentile(pair_raw, 5)),
            "p95": float(np.percentile(pair_raw, 95)),
            "share_gt_0_7": float((pair_raw > 0.7).mean()),
        },
        "corr_random_pairs_spy_residual": {
            "median": float(np.median(pair_res)),
            "p05": float(np.percentile(pair_res, 5)),
            "p95": float(np.percentile(pair_res, 95)),
            "share_gt_0_7": float((pair_res > 0.7).mean()),
        },
        "standard_errors": {
            "lo2002_sharpe_se_at_sr_1_0": float(np.sqrt((1 + 0.5) / years)),
            "lo2002_sharpe_se_at_sr_0_8": float(np.sqrt((1 + 0.5 * 0.64) / years)),
            "mean_rank_ic_se_n24": float(1 / np.sqrt(n_sym - 1) / np.sqrt(len(mom_w))),
            "mean_rank_ic_se_n100": float(1 / np.sqrt(99) / np.sqrt(len(mom_w))),
            "mean_rank_ic_se_n500": float(1 / np.sqrt(499) / np.sqrt(len(mom_w))),
            "note": "Analytic approximations (iid); block-bootstrap versions are a Phase 2 task.",
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    df.to_csv(out / "random-top5-metrics.csv", index=False)
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "official_study_metrics",
                    "simplified_engine_momentum",
                    "simplified_engine_equal_weight",
                    "random_top5_quantiles",
                    "p_random_sharpe_ge_official_momentum",
                    "best_of_k_random_sharpe",
                    "corr_random_vs_momentum_raw",
                    "corr_random_vs_momentum_spy_residual",
                    "corr_random_pairs_raw",
                    "corr_random_pairs_spy_residual",
                    "standard_errors",
                )
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
