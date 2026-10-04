"use client";

import Link from "next/link";
import type { Locale } from "@/lib/locale";
import type { MarketCrossSectionRow } from "@/lib/marketCrossSection";
import { watchHref } from "@/lib/watchPanes";

export type WatchPeriod = "week_pct" | "month_pct" | "ytd_pct";

export const watchPeriodLabels = {
  zh: { week_pct: "近 5 个交易日", month_pct: "近 21 个交易日", ytd_pct: "年初至今" },
  en: { week_pct: "Last 5 sessions", month_pct: "Last 21 sessions", ytd_pct: "Year to date" },
} as const;

export function MarketPulse({
  rows,
  period,
  onPeriodChange,
  locale,
}: {
  rows: MarketCrossSectionRow[];
  period: WatchPeriod;
  onPeriodChange: (period: WatchPeriod) => void;
  locale: Locale;
}) {
  const ranked = [...rows].sort((a, b) => b.returns[period] - a.returns[period]);
  const leader = ranked[0];
  const laggard = ranked.at(-1);
  const positive = rows.filter((row) => row.returns[period] > 0).length;
  const negative = rows.filter((row) => row.returns[period] < 0).length;
  const bothUp = rows.filter((row) => row.returns.week_pct > 0 && row.returns.month_pct > 0).length;
  const bothDown = rows.filter((row) => row.returns.week_pct < 0 && row.returns.month_pct < 0).length;
  const diverging = rows.filter((row) => row.returns.week_pct * row.returns.month_pct < 0).length;
  const zh = locale === "zh";
  return (
    <section aria-label={zh ? "关注摘要" : "Watch summary"} className="border-b border-border-subtle pb-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">{zh ? "这一段，谁在走强" : "Where strength is emerging"}</h2>
        <div role="group" aria-label={zh ? "比较周期" : "Comparison period"} className="flex flex-wrap gap-1">
          {(Object.keys(watchPeriodLabels[locale]) as WatchPeriod[]).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={period === value}
              onClick={() => onPeriodChange(value)}
              className={`rounded-md px-3 py-2 text-xs transition ${period === value ? "bg-warning/10 text-warning" : "text-text-secondary hover:text-text-primary"}`}
            >
              {watchPeriodLabels[locale][value]}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-5 grid gap-6 sm:grid-cols-3" data-watch-pulse={period}>
        <div>
          <p className="text-xs text-text-secondary">{zh ? "观察标的中上涨的数量" : "Advancing symbols in this group"}</p>
          <p className="mt-2 font-mono text-3xl tabular-nums">{positive}<span className="text-lg text-text-secondary"> / {rows.length}</span></p>
          <p className="mt-2 text-xs text-text-secondary">{zh ? `${negative} 只下跌 · ${rows.length - positive - negative} 只持平` : `${negative} declining · ${rows.length - positive - negative} flat`}</p>
        </div>
        {[{ row: leader, label: zh ? "相对最强" : "Strongest" }, { row: laggard, label: zh ? "相对最弱" : "Weakest" }].map(({ row, label }) => {
          return (
            <div key={label}>
              <p className="text-xs text-text-secondary">{label}</p>
              {row ? <>
                <Link prefetch={false} className="mt-2 inline-flex items-baseline gap-3 font-mono text-2xl hover:text-warning" href={watchHref("quotes", locale, { symbol: row.symbol, provider: "futu" })}>
                  {row.symbol}
                  <span className={`text-lg ${row.returns[period] >= 0 ? "text-accent-success" : "text-accent-danger"}`}>
                    {row.returns[period] >= 0 ? "+" : ""}{row.returns[period].toFixed(2)}%
                  </span>
                </Link>
                <p className="mt-2 text-xs leading-5 text-text-secondary">{zh
                  ? `近5日 ${row.returns.week_pct.toFixed(2)}% · 近21日 ${row.returns.month_pct.toFixed(2)}% · 年内最大回撤 ${row.max_drawdown_pct.toFixed(1)}%`
                  : `5D ${row.returns.week_pct.toFixed(2)}% · 21D ${row.returns.month_pct.toFixed(2)}% · YTD max drawdown ${row.max_drawdown_pct.toFixed(1)}%`}</p>
              </> : <p className="mt-2 text-text-secondary">—</p>}
            </div>
          );
        })}
      </div>
      <p className="mt-5 text-xs leading-5 text-text-secondary">
        {rows.length ? (zh
          ? `已比较这组 ${rows.length} 个标的：${bothUp} 个近5日与近21日都上涨，${bothDown} 个都下跌，${diverging} 个方向相反，${rows.length - bothUp - bothDown - diverging} 个至少一个周期持平。`
          : `Across these ${rows.length} symbols, ${bothUp} rose over both 5 and 21 sessions, ${bothDown} fell over both, ${diverging} moved in opposite directions, and ${rows.length - bothUp - bothDown - diverging} had a flat period.`)
          : (zh ? "当前没有可比较的行情数据。" : "No price data is available for comparison.")}
      </p>
    </section>
  );
}
