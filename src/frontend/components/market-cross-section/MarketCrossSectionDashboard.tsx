"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, BarChart3, ChevronDown, Grid3X3, RefreshCw } from "lucide-react";
import Link from "next/link";
import { MarketPulse, watchPeriodLabels, type WatchPeriod } from "@/components/watch/MarketPulse";
import { watchHref } from "@/lib/watchPanes";
import { MarketRiskPanel } from "@/components/watch/MarketRiskPanel";
import { MarketAssessmentView } from "@/components/watch/MarketAssessmentView";

import {
  getMarketCrossSectionSafe,
  type MarketCrossSectionProvenance,
  type MarketCrossSectionResponse,
} from "@/lib/marketCrossSection";
import type { Locale } from "@/lib/locale";

const copy = {
  en: {
    eyebrow: "RELATIVE STRENGTH",
    title: "US Risk",
    subtitle: "Assess valuation, macro conditions and market pressure, with clear evidence and conditional suggestions.",
    loading: "Reading cross-section from Futu OpenD…",
    unavailable: "Market cross-section is unavailable",
    unavailableHint: "No substitute curve was used. Restore Futu OpenD and retry.",
    retry: "Retry Futu",
    real: "Futu real market data",
    cached: "cached bar",
    live: "live Futu",
    asOf: "as of",
    timezone: "US session",
    heatmap: "Return heatmap",
    heatmapHint: "Color and ranking follow the selected comparison period.",
    table: "Cross-section table",
    tableHint: "Click a symbol to inspect its price and volume. Weekly and monthly direction reveal persistence or reversal.",
    basket: "Compare",
    aiWatch: "AI / semis watch",
    usSectors: "US sector ETFs",
    week: "Week",
    month: "Month",
    ytd: "YTD",
    volatility: "63D volatility",
    drawdown: "YTD max drawdown",
    methodology: "Methodology",
    readOnly: "Read-only market research. Not investment advice and no trading action is available here.",
  },
  zh: {
    eyebrow: "近期强弱与轮动",
    title: "美股风险",
    subtitle: "现在贵不贵，风险在累积还是缓和？结合估值、宏观与市场压力，给出有依据的判断。",
    loading: "正在从 Futu OpenD 读取横截面…",
    unavailable: "市场横截面暂不可用",
    unavailableHint: "未使用替代曲线。请恢复 Futu OpenD 后重试。",
    retry: "重试 Futu",
    real: "Futu 真实行情",
    cached: "缓存 bar",
    live: "实时 Futu",
    asOf: "截至",
    timezone: "美股时段",
    heatmap: "收益热力图",
    heatmapHint: "颜色与排名跟随上方选择的比较周期。",
    table: "横截面表",
    tableHint: "点击代码查看量价；周、月同向可继续跟踪，方向相反时先核对反弹或回落。",
    basket: "观察范围",
    aiWatch: "AI / 半导体关注",
    usSectors: "美股板块 ETF",
    week: "周",
    month: "月",
    ytd: "YTD",
    volatility: "63 日波动",
    drawdown: "YTD 最大回撤",
    methodology: "计算方法",
    readOnly: "仅供只读市场研究，不构成投资建议，本页不提供任何交易操作。",
  },
} as const;

export const marketCrossSectionTitle = {
  en: copy.en.title,
  zh: copy.zh.title,
} as const;

export type MarketCrossSectionBasket = "ai_watch" | "us_sectors";

export function MarketCrossSectionView({
  initialBasket,
  locale,
}: {
  initialBasket?: MarketCrossSectionBasket;
  locale: Locale;
}) {
  const [basket, setBasket] = useState<MarketCrossSectionBasket>(initialBasket ?? "ai_watch");
  const [data, setData] = useState<MarketCrossSectionResponse | null>(null);
  const [error, setError] = useState("");
  const [requestId, setRequestId] = useState(0);

  useEffect(() => {
    let active = true;
    getMarketCrossSectionSafe({ basket })
      .then((envelope) => {
        if (!active) return;
        if (envelope.apiError || !envelope.crossSection) {
          setData(null);
          setError(envelope.apiError || "Market cross-section unavailable");
        } else {
          setError("");
          setData(envelope.crossSection);
        }
      });
    return () => {
      active = false;
    };
  }, [basket, requestId]);

  const handleBasketChange = (next: MarketCrossSectionBasket) => {
    if (next === basket) return;
    // Clear the old basket's rows while the new request is in flight so the
    // page never shows a new-basket highlight over stale old-basket data.
    setError("");
    setData(null);
    setBasket(next);
  };

  return <div className="h-full overflow-y-auto bg-bg-base text-text-primary">
    <header className="px-5 pb-4 pt-7 lg:px-8"><p className="text-xs tracking-wide text-[var(--color-hermes)]">{locale === "zh" ? "估值与市场风险" : "VALUATION & MARKET RISK"}</p><h1 className="mt-2 font-headline-xl">{copy[locale].title}</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-text-secondary">{copy[locale].subtitle}</p></header>
    <div className="px-5 pb-8 lg:px-8"><MarketAssessmentView scope="us" locale={locale} /></div>
    <details className="group/market-details mx-5 pb-8 lg:mx-8">
      <summary className="app-touch-target mb-5 flex cursor-pointer list-none items-center gap-3 rounded-lg border border-border-subtle bg-bg-surface px-4 py-4 text-sm text-text-primary transition-colors hover:border-[var(--color-hermes)] hover:bg-bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-hermes)] [&::-webkit-details-marker]:hidden">
        <BarChart3 size={18} className="shrink-0 text-[var(--color-hermes)]" aria-hidden="true" />
        <span className="font-medium">{locale === "zh" ? "价格、波动与板块对照" : "Price, volatility and sector details"}</span>
        <span className="ml-auto shrink-0 text-xs text-[var(--color-hermes)]"><span className="group-open/market-details:hidden">{locale === "zh" ? "展开" : "Expand"}</span><span className="hidden group-open/market-details:inline">{locale === "zh" ? "收起" : "Collapse"}</span></span>
        <ChevronDown size={17} className="shrink-0 transition-transform group-open/market-details:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
      </summary>
      {error ? (
      <MarketCrossSectionUnavailable
        locale={locale}
        message={error}
        onRetry={() => {
          setError("");
          setData(null);
          setRequestId((value) => value + 1);
        }}
      />
    ) : !data ? <MarketCrossSectionLoading locale={locale} /> : (
    <MarketCrossSectionDashboard
      basket={basket}
      data={data}
      locale={locale}
      onBasketChange={handleBasketChange}
    />
    )}</details>
  </div>;
}

export function MarketCrossSectionDashboard({
  basket,
  data,
  locale,
  onBasketChange,
}: {
  basket: MarketCrossSectionBasket;
  data: MarketCrossSectionResponse;
  locale: Locale;
  onBasketChange?: (basket: MarketCrossSectionBasket) => void;
}) {
  const text = copy[locale];
  const [period, setPeriod] = useState<WatchPeriod>("week_pct");
  const ranked = useMemo(
    () => [...data.rows].sort((left, right) => right.returns[period] - left.returns[period]),
    [data.rows, period],
  );

  return (
    <div className="h-full overflow-y-auto bg-bg-base text-text-primary">
      <header className="border-b border-border-subtle px-4 pb-6 pt-6 lg:px-8">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="flex items-center gap-2 font-label-caps text-warning">
              <Grid3X3 size={15} />
              <span>{text.eyebrow}</span>
            </div>
            <h2 className="mt-2 text-xl font-semibold">{locale === "zh" ? "价格与板块比较" : "Price and sector comparison"}</h2>
          </div>
          <ProvenanceBadges
            asOf={data.as_of}
            compact={false}
            locale={locale}
            provenance={data.provenance}
            timezone={data.timezone}
          />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <span className="font-label-caps text-text-secondary">{text.basket}</span>
          {(
            [
              ["ai_watch", text.aiWatch],
              ["us_sectors", text.usSectors],
            ] as const
          ).map(([id, fallback]) => {
            // Prefer the backend-issued basket_label for the loaded basket;
            // fall back to local copy when the field is absent (custom
            // cross-sections) or for the inactive pill.
            const label =
              basket === id && data.basket_label ? data.basket_label[locale] : fallback;
            return (
              <button
                aria-pressed={basket === id}
                className={`rounded-md border px-3 py-2 font-semibold transition ${
                  basket === id
                    ? "border-warning/40 bg-warning/10 text-warning"
                    : "border-border-subtle text-text-secondary hover:border-white/25"
                }`}
                data-basket-pill={id}
                key={id}
                onClick={() => onBasketChange?.(id)}
                type="button"
              >
                {label}
              </button>
            );
          })}
        </div>
      </header>

      <div className="space-y-6 px-4 py-6 lg:px-8">
        <MarketRiskPanel risk={data.risk_observations} locale={locale} />
        <MarketPulse rows={data.rows} period={period} onPeriodChange={setPeriod} locale={locale} />
        <details className="border-b border-border-subtle pb-5">
          <summary className="cursor-pointer text-sm text-text-secondary">{text.heatmap} · {watchPeriodLabels[locale][period]}</summary>
          <div className="pt-4">
          <ChartHeader
            asOf={data.as_of}
            icon={<Grid3X3 size={17} />}
            locale={locale}
            title={text.heatmap}
            hint={text.heatmapHint}
            provenance={data.provenance}
            timezone={data.timezone}
          />
          <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {ranked.map((row, index) => (
              <Link
                prefetch={false}
                className="rounded-md border border-white/10 p-3 transition hover:border-warning/50"
                data-market-card={row.symbol}
                key={row.symbol}
                href={watchHref("quotes", locale, { symbol: row.symbol, provider: "futu" })}
                style={{ backgroundColor: heatColor(row.returns[period]) }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-mono text-xs text-white/65">#{index + 1}</div>
                    <div className="mt-1 text-base font-semibold text-white">{row.symbol}</div>
                  </div>
                </div>
                <div className="mt-3 font-data-mono text-xl font-semibold text-white">
                  {formatPct(row.returns[period])}
                </div>
                <div className="mt-1 text-[11px] text-white/60">{watchPeriodLabels[locale][period]}</div>
              </Link>
            ))}
          </div>
          </div>
        </details>

        <section>
          <ChartHeader
            asOf={data.as_of}
            icon={<BarChart3 size={17} />}
            locale={locale}
            title={text.table}
            hint={text.tableHint}
            provenance={data.provenance}
            timezone={data.timezone}
          />
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-xs">
              <thead className="border-b border-border-subtle font-label-caps text-text-secondary">
                <tr>
                  <th className="py-3">#</th>
                  <th>{locale === "zh" ? "标的" : "Symbol"}</th>
                  <th>{text.week}</th>
                  <th>{text.month}</th>
                  <th>{text.ytd}</th>
                  <th>{text.volatility}</th>
                  <th>{text.drawdown}</th>
                </tr>
              </thead>
              <tbody>
                {ranked.map((row, index) => (
                  <tr className="border-b border-border-subtle/60 hover:bg-bg-surface" key={row.symbol}>
                    <td className="py-3 font-mono text-text-secondary">{index + 1}</td>
                    <td className="font-semibold text-text-primary"><Link prefetch={false} className="inline-block py-2 hover:text-warning" href={watchHref("quotes", locale, { symbol: row.symbol, provider: "futu" })}>{row.symbol} ↗</Link></td>
                    <MetricCell value={row.returns.week_pct} />
                    <MetricCell value={row.returns.month_pct} />
                    <MetricCell value={row.returns.ytd_pct} />
                    <td className="font-mono text-text-secondary">{row.volatility_pct.toFixed(1)}%</td>
                    <td className="font-mono text-accent-danger">{row.max_drawdown_pct.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <footer className="border-t border-border-subtle py-5 text-xs text-text-secondary">
          <details className="mb-4 rounded-xl border border-border-subtle bg-bg-surface p-4">
            <summary className="cursor-pointer font-semibold text-text-primary">
              {text.methodology}
            </summary>
            <ul className="mt-3 space-y-1 font-mono text-[11px]">
              {Object.entries(data.methodology).map(([key, value]) => (
                <li data-methodology-item={key} key={key}>
                  {key}: {value}
                </li>
              ))}
            </ul>
          </details>
          {text.readOnly}
        </footer>
      </div>
    </div>
  );
}

export function MarketCrossSectionUnavailable({
  locale,
  message,
  onRetry,
}: {
  locale: Locale;
  message: string;
  onRetry?: () => void;
}) {
  const text = copy[locale];
  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-6 text-text-primary">
      <section className="w-full max-w-2xl rounded-2xl border border-accent-danger/40 bg-bg-surface p-7">
        <AlertTriangle className="text-accent-danger" size={26} />
        <h1 className="mt-4 font-headline-lg">{text.unavailable}</h1>
        <p className="mt-3 font-mono text-sm text-accent-danger">{message}</p>
        <p className="mt-3 text-sm text-text-secondary">{text.unavailableHint}</p>
        {onRetry ? (
          <button
            className="mt-6 inline-flex items-center gap-2 rounded-lg border border-border-subtle px-4 py-2 text-sm hover:border-accent-success"
            onClick={onRetry}
            type="button"
          >
            <RefreshCw size={15} /> {text.retry}
          </button>
        ) : null}
      </section>
    </div>
  );
}

function MarketCrossSectionLoading({ locale }: { locale: Locale }) {
  return (
    <div className="flex h-full items-center justify-center text-sm text-text-secondary">
      <RefreshCw className="mr-3 animate-spin" size={17} /> {copy[locale].loading}
    </div>
  );
}

function ChartHeader({
  asOf,
  hint,
  icon,
  locale,
  title,
  provenance,
  timezone,
}: {
  asOf: string;
  hint: string;
  icon: React.ReactNode;
  locale: Locale;
  title: string;
  provenance?: MarketCrossSectionProvenance;
  timezone?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3" data-chart-provenance="real">
      <div>
        <h2 className="flex items-center gap-2 text-base font-semibold text-text-primary" data-chart-title="visible">
          {icon}{title}
        </h2>
        <p className="mt-1 text-xs text-text-secondary">{hint}</p>
      </div>
      <ProvenanceBadges
        asOf={asOf}
        compact
        locale={locale}
        provenance={provenance}
        timezone={timezone}
      />
    </div>
  );
}

function ProvenanceBadges({
  asOf,
  compact,
  locale,
  provenance,
  timezone,
}: {
  asOf: string;
  compact: boolean;
  locale: Locale;
  provenance?: MarketCrossSectionProvenance;
  timezone?: string;
}) {
  const text = copy[locale];
  return (
    <div className={`flex flex-wrap items-center gap-2 ${compact ? "text-[10px]" : "text-xs"}`}>
      <span className="font-medium text-text-secondary">
        {text.real}
      </span>
      {provenance ? (
        <span className="rounded-full border border-border-subtle px-2.5 py-1 font-mono text-text-secondary">
          {provenance === "futu_cache" ? text.cached : text.live}
        </span>
      ) : null}
      <span className="font-mono text-text-secondary">{text.asOf} {asOf}</span>
      {timezone ? <span className="font-mono text-text-secondary">{text.timezone}</span> : null}
    </div>
  );
}

function MetricCell({ value }: { value: number }) {
  return (
    <td className={`font-mono ${value >= 0 ? "text-accent-success" : "text-accent-danger"}`}>
      {formatPct(value)}
    </td>
  );
}

function formatPct(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function heatColor(value: number) {
  const intensity = Math.min(0.58, 0.18 + Math.abs(value) / 45);
  return value >= 0
    ? `rgba(19, 122, 82, ${intensity})`
    : `rgba(154, 48, 61, ${intensity})`;
}
