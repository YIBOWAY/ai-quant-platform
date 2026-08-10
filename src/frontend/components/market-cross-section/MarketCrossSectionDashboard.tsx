"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, BarChart3, Grid3X3, RefreshCw } from "lucide-react";

import {
  getMarketCrossSectionSafe,
  type MarketCrossSectionProvenance,
  type MarketCrossSectionResponse,
  type MarketCrossSectionRow,
} from "@/lib/marketCrossSection";
import type { Locale } from "@/lib/locale";

const copy = {
  en: {
    eyebrow: "MARKET CROSS-SECTION",
    title: "Market Cross-Section",
    subtitle:
      "Read-only heatmap of a preset symbol universe over strict Futu 1d QFQ bars. No valuation estimates, no sample fallback.",
    loading: "Reading cross-section from Futu OpenD…",
    unavailable: "Market cross-section is unavailable",
    unavailableHint: "No substitute curve was used. Restore Futu OpenD and retry.",
    retry: "Retry Futu",
    real: "Futu real market data",
    cached: "cached bar",
    live: "live Futu",
    asOf: "as of",
    timezone: "US session",
    heatmap: "YTD heatmap",
    heatmapHint: "Color and order are calculated from current YTD returns.",
    table: "Cross-section table",
    tableHint: "Ranked by current YTD return.",
    basket: "Basket",
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
    eyebrow: "市场横截面",
    title: "市场横截面",
    subtitle: "基于严格 Futu 日线的预设标的篮子只读热力图；不提供估值估算，失败不回退 sample。",
    loading: "正在从 Futu OpenD 读取横截面…",
    unavailable: "市场横截面暂不可用",
    unavailableHint: "未使用替代曲线。请恢复 Futu OpenD 后重试。",
    retry: "重试 Futu",
    real: "Futu 真实行情",
    cached: "缓存 bar",
    live: "实时 Futu",
    asOf: "截至",
    timezone: "美股时段",
    heatmap: "YTD 热力图",
    heatmapHint: "颜色与顺序由当前 YTD 收益动态计算。",
    table: "横截面表",
    tableHint: "按当前 YTD 收益排名。",
    basket: "篮子",
    aiWatch: "AI / 半导体关注",
    usSectors: "美股板块 ETF",
    week: "周",
    month: "月",
    ytd: "YTD",
    volatility: "63 日波动",
    drawdown: "YTD 最大回撤",
    methodology: "口径",
    readOnly: "仅供只读市场研究，不构成投资建议，本页不提供任何交易操作。",
  },
} as const;

export function MarketCrossSectionView({ locale }: { locale: Locale }) {
  const [basket, setBasket] = useState<"ai_watch" | "us_sectors">("ai_watch");
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

  if (error) {
    return (
      <MarketCrossSectionUnavailable
        locale={locale}
        message={error}
        onRetry={() => {
          setError("");
          setData(null);
          setRequestId((value) => value + 1);
        }}
      />
    );
  }
  if (!data) return <MarketCrossSectionLoading locale={locale} />;
  return (
    <MarketCrossSectionDashboard
      basket={basket}
      data={data}
      locale={locale}
      onBasketChange={setBasket}
    />
  );
}

export function MarketCrossSectionDashboard({
  basket,
  data,
  locale,
  onBasketChange,
}: {
  basket: "ai_watch" | "us_sectors";
  data: MarketCrossSectionResponse;
  locale: Locale;
  onBasketChange?: (basket: "ai_watch" | "us_sectors") => void;
}) {
  const text = copy[locale];
  const ranked = useMemo(
    () => [...data.rows].sort((left, right) => left.rank - right.rank),
    [data.rows],
  );

  return (
    <div className="h-full overflow-y-auto bg-bg-base text-text-primary">
      <header className="border-b border-border-subtle px-4 pb-6 pt-6 lg:px-8">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="flex items-center gap-2 font-label-caps text-accent-success">
              <Grid3X3 size={15} />
              <span>{text.eyebrow}</span>
            </div>
            <h1 className="mt-2 font-headline-xl">{text.title}</h1>
            <p className="mt-2 max-w-3xl font-body-sm text-text-secondary">{text.subtitle}</p>
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
          ).map(([id, label]) => (
            <button
              className={`rounded-full border px-3 py-1.5 font-semibold transition ${
                basket === id
                  ? "border-accent-success/60 bg-accent-success/10 text-accent-success"
                  : "border-border-subtle text-text-secondary hover:border-white/25"
              }`}
              key={id}
              onClick={() => onBasketChange?.(id)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <div className="space-y-6 px-4 py-6 lg:px-8">
        <section className="rounded-2xl border border-border-subtle bg-bg-card p-4 lg:p-5">
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
            {ranked.map((row) => (
              <div
                className="rounded-xl border border-white/10 p-4"
                data-market-card={row.symbol}
                key={row.symbol}
                style={{ backgroundColor: heatColor(row.returns.ytd_pct) }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-mono text-xs text-white/65">#{row.rank}</div>
                    <div className="mt-1 text-base font-semibold text-white">{row.symbol}</div>
                  </div>
                  <span className="rounded-md bg-black/20 px-2 py-1 font-mono text-xs text-white">
                    ETF
                  </span>
                </div>
                <div className="mt-6 font-data-mono text-2xl font-semibold text-white">
                  {formatPct(row.returns.ytd_pct)}
                </div>
                <div className="mt-1 text-[11px] uppercase tracking-wider text-white/60">YTD</div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-border-subtle bg-bg-card p-4 lg:p-5">
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
                  <th>Symbol</th>
                  <th>{text.week}</th>
                  <th>{text.month}</th>
                  <th>{text.ytd}</th>
                  <th>{text.volatility}</th>
                  <th>{text.drawdown}</th>
                </tr>
              </thead>
              <tbody>
                {ranked.map((row) => (
                  <tr className="border-b border-border-subtle/60" key={row.symbol}>
                    <td className="py-3 font-mono text-text-secondary">{row.rank}</td>
                    <td className="font-semibold text-text-primary">{row.symbol}</td>
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
      <section className="w-full max-w-2xl rounded-2xl border border-accent-danger/40 bg-bg-card p-7">
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
      <span className="rounded-full border border-accent-success/40 bg-accent-success/10 px-2.5 py-1 font-semibold text-accent-success">
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
