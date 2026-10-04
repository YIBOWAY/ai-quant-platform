"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, BarChart3, ChevronDown, Globe2, RefreshCw, TrendingUp } from "lucide-react";
import Link from "next/link";
import { MarketPulse, watchPeriodLabels, type WatchPeriod } from "@/components/watch/MarketPulse";
import { watchHref } from "@/lib/watchPanes";
import { MarketAssessmentView } from "@/components/watch/MarketAssessmentView";

import {
  getAsiaRadarOverview,
  type AsiaRadarDriverBasket,
  type AsiaRadarLocalIndex,
  type AsiaRadarMarket,
  type AsiaRadarOverview,
} from "@/lib/asiaRadar";
import type { Locale } from "@/lib/locale";

const copy = {
  en: {
    eyebrow: "ASIA MARKET PULSE",
    title: "Asia Valuation",
    subtitle: "Compare Asian market valuations and price pressure, with sources, risk factors and conditional suggestions.",
    loading: "Reading 12 ETF histories from Futu OpenD…",
    unavailable: "Asia Radar is unavailable",
    unavailableHint: "No substitute curve was used. Restore Futu OpenD and retry.",
    retry: "Retry Futu",
    real: "Futu real market data",
    proxy: "ETF proxy",
    asOf: "as of",
    timezone: "US session",
    cached: "cached bar",
    live: "live Futu",
    heatmap: "Regional strength",
    heatmapHint: "12 US-listed ETF proxies in USD, using completed US sessions. Select a market to inspect it below.",
    ranking: "Cross-market ranking",
    rankingHint: "Ordered by the selected return period; volatility and drawdown describe the risk alongside the move.",
    kShape: "Dynamic K-shape divergence",
    kShapeHint: "Daily top-three and bottom-three YTD basket averages.",
    kShapeEmpty: "No YTD K-shape series yet for the current calendar year.",
    winner: "Winner basket",
    laggard: "Laggard basket",
    week: "Week",
    month: "Month",
    ytd: "YTD",
    volatility: "63D volatility",
    drawdown: "YTD max drawdown",
    detail: "Market detail",
    index: "Index",
    etfProxy: "ETF proxy",
    drivers: "Leading drivers",
    localIndex: "Local index",
    localSession: "local trading day",
    windowReturn: "Window return",
    sessions: "sessions",
    indexNote:
      "Display-only: each lane keeps its own currency, trading calendar, and vertical scale. The local index is never blended into the USD ETF proxy metrics.",
    indexPendingTitle: "Local index not connected",
    indexErrorTitle: "Local index temporarily unavailable",
    indexErrorHint: "No substitute curve was used; the ETF proxy tab is unaffected.",
    indexErrorReasonPrefix: "Provider error",
    indexReasonPermission:
      "The Futu account has no A-share index quote permission; CSI 300 (SH.000300) unlocks once it is enabled in Futu.",
    indexReasonFormat:
      "Futu OpenD does not support this market's index code format; a dedicated channel (TWSE / Twelve Data) is planned.",
    indexReasonChannel: "No verified local index channel for this market yet.",
    indexReasonMissing: "Local index data was not loaded for this market.",
    driverBasketNote:
      "Unweighted leader display — not an index substitute and never blended into the USD ETF proxy metrics. Each leader keeps its own provider, currency, trading calendar, and vertical scale.",
    driverUsAdr: "US ADR",
    driverHkLocal: "HK local",
    driverPendingTitle: "Driver basket not connected",
    driverErrorTitle: "Driver basket temporarily unavailable",
    driverErrorHint: "No substitute basket or ETF proxy curve was used; the ETF proxy tab is unaffected.",
    driverReasonNoListing:
      "Samsung Electronics and SK Hynix have no liquid US listing; no verified leader channel for this market yet.",
    driverReasonPermission:
      "The Futu account has no A-share quote permission; A-share leaders unlock once it is enabled in Futu.",
    driverReasonFormat:
      "The verified channels do not support this market's leader code format yet.",
    driverReasonChannel: "No verified leader data channel for this market yet.",
    driverReasonMissing: "Driver basket data was not loaded for this market.",
    driverLeaderErrorPrefix: "Leader unavailable",
    close: "Latest close",
    methodology: "Methodology",
    readOnly: "Read-only market research. Not investment advice and no trading action is available here.",
  },
  zh: {
    eyebrow: "区域市场表现",
    title: "亚洲泡沫",
    subtitle: "哪些市场估值偏高，上涨是否伴随更大风险？结合基金发行人估值与真实行情，解释当前需要关注什么。",
    loading: "正在从 Futu OpenD 读取 12 只 ETF 日线…",
    unavailable: "亚洲雷达暂不可用",
    unavailableHint: "未使用替代曲线。请恢复 Futu OpenD 后重试。",
    retry: "重试 Futu",
    real: "Futu 真实行情",
    proxy: "ETF 代理",
    asOf: "截至",
    timezone: "美股时段",
    cached: "缓存 bar",
    live: "实时 Futu",
    heatmap: "区域强弱",
    heatmapHint: "12 只美股上市 ETF，以美元和已收盘的美股交易日比较。选择一个市场，查看下方详情。",
    ranking: "跨市场排名",
    rankingHint: "按所选周期收益排序，同时对照波动与回撤。",
    kShape: "动态 K 型分化",
    kShapeHint: "比较年内涨幅前三名与后三名市场的平均表现。",
    kShapeEmpty: "当前自然年尚无可用的 K 型序列。",
    winner: "涨幅前三名市场",
    laggard: "涨幅后三名市场",
    week: "周",
    month: "月",
    ytd: "YTD",
    volatility: "63 日波动",
    drawdown: "YTD 最大回撤",
    detail: "市场详情",
    index: "指数",
    etfProxy: "ETF 代理",
    drivers: "龙头驱动",
    localIndex: "本地指数",
    localSession: "本地交易日",
    windowReturn: "区间收益",
    sessions: "个交易日",
    indexNote:
      "仅作展示对照：两条序列各自使用本地币种、本地交易日历，并各自独立缩放；指数不与美元 ETF 代理混合计算任何指标。",
    indexPendingTitle: "本地指数待接入",
    indexErrorTitle: "本地指数暂不可用",
    indexErrorHint: "未用任何替代曲线冒充指数；ETF 代理页签不受影响。",
    indexErrorReasonPrefix: "数据源错误",
    indexReasonPermission:
      "Futu 账户未开通 A 股指数行情权限；开通后可接入沪深300（SH.000300）。",
    indexReasonFormat:
      "Futu OpenD 不支持该市场的指数代码格式，待接入专用通道（TWSE / Twelve Data）。",
    indexReasonChannel: "该市场指数暂无已验证的本地数据通道。",
    indexReasonMissing: "该市场的本地指数数据未加载。",
    driverBasketNote:
      "相关股票分别展示，不与指数或 ETF 合并计算。每只股票标明来源、币种和交易日期。",
    driverUsAdr: "美股 ADR",
    driverHkLocal: "港股本地",
    driverPendingTitle: "相关股票数据待接入",
    driverErrorTitle: "相关股票数据暂不可用",
    driverErrorHint: "当前无法读取相关股票数据，可以查看该市场的 ETF。",
    driverReasonNoListing:
      "三星电子与 SK 海力士无流动性充足的美国上市凭证，该市场暂无已验证的龙头数据通道。",
    driverReasonPermission:
      "Futu 账户未开通 A 股行情权限；开通后可接入 A 股龙头。",
    driverReasonFormat: "已验证通道暂不支持该市场的龙头代码格式。",
    driverReasonChannel: "该市场暂无已验证的龙头数据通道。",
    driverReasonMissing: "该市场的相关股票数据未加载。",
    driverLeaderErrorPrefix: "龙头暂不可用",
    close: "最新收盘",
    methodology: "计算方法",
    readOnly: "仅供只读市场研究，不构成投资建议，本页不提供任何交易操作。",
  },
} as const;

export const asiaRadarTitle = {
  en: copy.en.title,
  zh: copy.zh.title,
} as const;

type DetailTab = "index" | "proxy" | "drivers";

export function AsiaRadarView({ locale }: { locale: Locale }) {
  const [overview, setOverview] = useState<AsiaRadarOverview | null>(null);
  const [error, setError] = useState("");
  const [requestId, setRequestId] = useState(0);

  useEffect(() => {
    let active = true;
    getAsiaRadarOverview()
      .then((payload) => {
        if (active) setOverview(payload);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setOverview(null);
        setError(reason instanceof Error ? reason.message : "Futu provider unavailable");
      });
    return () => {
      active = false;
    };
  }, [requestId]);

  return <div className="h-full overflow-y-auto bg-bg-base text-text-primary">
    <header className="px-5 pb-4 pt-7 lg:px-8"><p className="text-xs tracking-wide text-[var(--color-hermes)]">{locale === "zh" ? "亚洲估值与泡沫观察" : "ASIA VALUATION & BUBBLE INDICATORS"}</p><h1 className="mt-2 font-headline-xl">{copy[locale].title}</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-text-secondary">{copy[locale].subtitle}</p></header>
    <div className="px-5 pb-8 lg:px-8"><MarketAssessmentView scope="asia" locale={locale} /></div>
    <details className="group/market-details mx-5 pb-8 lg:mx-8">
      <summary className="app-touch-target mb-5 flex cursor-pointer list-none items-center gap-3 rounded-lg border border-border-subtle bg-bg-surface px-4 py-4 text-sm text-text-primary transition-colors hover:border-[var(--color-hermes)] hover:bg-bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-hermes)] [&::-webkit-details-marker]:hidden">
        <BarChart3 size={18} className="shrink-0 text-[var(--color-hermes)]" aria-hidden="true" />
        <span className="font-medium">{locale === "zh" ? "各市场走势、指数与相关股票" : "Regional charts, indices and stocks"}</span>
        <span className="ml-auto shrink-0 text-xs text-[var(--color-hermes)]"><span className="group-open/market-details:hidden">{locale === "zh" ? "展开" : "Expand"}</span><span className="hidden group-open/market-details:inline">{locale === "zh" ? "收起" : "Collapse"}</span></span>
        <ChevronDown size={17} className="shrink-0 transition-transform group-open/market-details:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
      </summary>
    {error ? (
      <AsiaRadarUnavailable
        locale={locale}
        message={error}
        onRetry={() => {
          setError("");
          setOverview(null);
          setRequestId((value) => value + 1);
        }}
      />
    ) : !overview ? <AsiaRadarLoading locale={locale} /> : <AsiaRadarDashboard locale={locale} overview={overview} />}
    </details>
  </div>;
}

export function AsiaRadarDashboard({
  locale,
  overview,
}: {
  locale: Locale;
  overview: AsiaRadarOverview;
}) {
  const text = copy[locale];
  const [period, setPeriod] = useState<WatchPeriod>("week_pct");
  const ranked = useMemo(
    () => [...overview.markets].sort((left, right) => right.returns[period] - left.returns[period]),
    [overview.markets, period],
  );
  const [selectedSymbol, setSelectedSymbol] = useState(ranked[0]?.symbol ?? "");
  const [tab, setTab] = useState<DetailTab>("proxy");
  const selected =
    overview.markets.find((market) => market.symbol === selectedSymbol) ?? ranked[0];

  return (
    <div className="h-full overflow-y-auto bg-bg-base text-text-primary">
      <header className="border-b border-border-subtle px-4 pb-6 pt-6 lg:px-8">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="flex items-center gap-2 font-label-caps text-warning">
              <Globe2 size={15} />
              <span>{text.eyebrow}</span>
            </div>
            <h2 className="mt-2 text-xl font-semibold">{locale === "zh" ? "亚洲市场走势对照" : "Asian market performance"}</h2>
          </div>
          <ProvenanceBadges
            locale={locale}
            asOf={overview.as_of}
            compact={false}
            provenance={overview.provenance}
            timezone={overview.timezone}
          />
        </div>
      </header>

      <div className="space-y-6 px-4 py-6 lg:px-8">
        <MarketPulse rows={overview.markets} period={period} onPeriodChange={setPeriod} locale={locale} />
        <section>
          <ChartHeader
            asOf={overview.as_of}
            icon={<Globe2 size={17} />}
            locale={locale}
            title={text.heatmap}
            hint={text.heatmapHint}
            provenance={overview.provenance}
            timezone={overview.timezone}
          />
          <div className="mt-5 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-4">
            {ranked.map((market, index) => (
              <button
                className={`rounded-md border p-3 text-left transition hover:border-warning/50 ${selected?.symbol === market.symbol ? "border-warning/70" : "border-border-subtle"}`}
                data-market-card={market.symbol}
                aria-pressed={selected?.symbol === market.symbol}
                key={market.symbol}
                onClick={() => {
                  setSelectedSymbol(market.symbol);
                  document.getElementById("asia-market-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
                style={{ backgroundColor: heatColor(market.returns[period]) }}
                type="button"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-mono text-[10px] text-white/65">#{index + 1}</div>
                    <div className="mt-1 text-sm font-semibold text-white">
                      {locale === "zh" ? market.name_zh : market.name_en}
                    </div>
                  </div>
                  <span className="font-mono text-xs text-white/70">
                    {market.symbol}
                  </span>
                </div>
                <div className="mt-3 font-data-mono text-xl font-semibold text-white">
                  {formatPct(market.returns[period])}
                </div>
                <div className="mt-1 text-[10px] text-white/60">{watchPeriodLabels[locale][period]}</div>
              </button>
            ))}
          </div>
        </section>

        {selected ? (
          <div id="asia-market-detail" className="scroll-mt-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-xs">
              <span className="text-text-secondary">{locale === "zh" ? "继续核对这个市场" : "Investigate this market"}</span>
              <Link prefetch={false} className="text-warning hover:underline" href={watchHref("quotes", locale, { symbol: selected.symbol, provider: "futu" })}>
                {locale === "zh" ? `查看 ${selected.symbol} K 线与成交量 →` : `Inspect ${selected.symbol} price and volume →`}
              </Link>
            </div>
            <MarketDetail locale={locale} market={selected} methodology={overview.methodology} onTabChange={setTab} tab={tab} />
          </div>
        ) : null}

        <details className="border-t border-border-subtle pt-5">
          <summary className="cursor-pointer text-sm text-text-secondary">{locale === "zh" ? "展开完整排名与年内分化" : "Full ranking and year-to-date divergence"}</summary>
        <div className="mt-5 grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <section className="min-w-0">
            <ChartHeader
              asOf={overview.as_of}
              icon={<BarChart3 size={17} />}
              locale={locale}
              title={text.ranking}
              hint={text.rankingHint}
              provenance={overview.provenance}
              timezone={overview.timezone}
            />
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[540px] text-left text-xs">
                <thead className="border-b border-border-subtle font-label-caps text-text-secondary">
                  <tr>
                    <th className="py-3">#</th>
                    <th>{locale === "zh" ? "市场 / ETF" : "Market / ETF"}</th>
                    <th>{text.week}</th>
                    <th>{text.month}</th>
                    <th>{text.ytd}</th>
                    <th>{text.volatility}</th>
                    <th>{text.drawdown}</th>
                  </tr>
                </thead>
                <tbody>
                  {ranked.map((market, index) => (
                    <tr className="border-b border-border-subtle/60" key={market.symbol}>
                      <td className="py-3 font-mono text-text-secondary">{index + 1}</td>
                      <td>
                        <button
                          className="text-left font-semibold text-text-primary hover:text-accent-success"
                          onClick={() => setSelectedSymbol(market.symbol)}
                          type="button"
                        >
                          {market.symbol} · {locale === "zh" ? market.name_zh : market.name_en}
                        </button>
                      </td>
                      <MetricCell value={market.returns.week_pct} />
                      <MetricCell value={market.returns.month_pct} />
                      <MetricCell value={market.returns.ytd_pct} />
                      <td className="font-mono text-text-secondary">{market.volatility_pct.toFixed(1)}%</td>
                      <td className="font-mono text-accent-danger">{market.max_drawdown_pct.toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="min-w-0">
            <ChartHeader
              asOf={overview.as_of}
              icon={<TrendingUp size={17} />}
              locale={locale}
              title={text.kShape}
              hint={text.kShapeHint}
              provenance={overview.provenance}
              timezone={overview.timezone}
            />
            <KShapeChart locale={locale} overview={overview} />
          </section>
        </div>
        </details>

        <footer className="border-t border-border-subtle py-5 text-xs text-text-secondary">
          {text.readOnly}
        </footer>
      </div>
    </div>
  );
}

export function AsiaRadarUnavailable({
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

function AsiaRadarLoading({ locale }: { locale: Locale }) {
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
  provenance?: "futu" | "futu_cache";
  timezone?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3" data-chart-provenance="real-proxy">
      <div>
        <h2
          className="flex items-center gap-2 text-base font-semibold text-text-primary"
          data-chart-title="visible"
        >
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
  provenance?: "futu" | "futu_cache";
  timezone?: string;
}) {
  const text = copy[locale];
  return (
    <div className={`flex flex-wrap items-center gap-2 ${compact ? "text-[10px]" : "text-xs"}`}>
      <span className="font-medium text-text-secondary">
        {text.real}
      </span>
      <span className="font-medium text-text-secondary">
        {text.proxy}
      </span>
      {provenance ? (
        <span className="rounded-full border border-border-subtle px-2.5 py-1 font-mono text-text-secondary">
          {provenance === "futu_cache" ? text.cached : text.live}
        </span>
      ) : null}
      <span className="font-mono text-text-secondary">{text.asOf} {asOf}</span>
      {timezone ? (
        <span className="font-mono text-text-secondary">{text.timezone}</span>
      ) : null}
    </div>
  );
}

function KShapeChart({
  locale,
  overview,
}: {
  locale: Locale;
  overview: AsiaRadarOverview;
}) {
  const text = copy[locale];
  if (!overview.k_shape.series.length) {
    return (
      <div className="mt-5 rounded-xl border border-dashed border-border-subtle p-5 text-sm text-text-secondary">
        {text.kShapeEmpty}
      </div>
    );
  }
  const values = overview.k_shape.series.flatMap((point) => [
    point.winner_avg_pct,
    point.laggard_avg_pct,
  ]);
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(0, ...values);
  const winnerPoints = polylinePoints(
    overview.k_shape.series.map((point) => point.winner_avg_pct),
    minimum,
    maximum,
  );
  const laggardPoints = polylinePoints(
    overview.k_shape.series.map((point) => point.laggard_avg_pct),
    minimum,
    maximum,
  );
  return (
    <div className="mt-5">
      <div className="flex flex-wrap gap-4 text-xs">
        <span className="text-accent-success">● {text.winner}: {overview.k_shape.winners.join(" · ")}</span>
        <span className="text-accent-danger">● {text.laggard}: {overview.k_shape.laggards.join(" · ")}</span>
      </div>
      <svg
        aria-label={text.kShape}
        className="mt-4 h-[250px] w-full overflow-visible rounded-xl bg-bg-base/50"
        role="img"
        viewBox="0 0 720 240"
      >
        <line stroke="currentColor" strokeOpacity="0.15" x1="24" x2="696" y1="120" y2="120" />
        <polyline fill="none" points={winnerPoints} stroke="var(--color-accent-success)" strokeWidth="3" />
        <polyline fill="none" points={laggardPoints} stroke="var(--color-accent-danger)" strokeWidth="3" />
      </svg>
      <div className="mt-2 text-right font-mono text-xs text-text-secondary">
        spread {formatPct(overview.k_shape.series.at(-1)?.spread_pct ?? 0)}
      </div>
    </div>
  );
}

function MarketDetail({
  locale,
  market,
  methodology,
  onTabChange,
  tab,
}: {
  locale: Locale;
  market: AsiaRadarMarket;
  methodology: Record<string, string>;
  onTabChange: (tab: DetailTab) => void;
  tab: DetailTab;
}) {
  const text = copy[locale];
  const tabs: Array<[DetailTab, string]> = [
    ["index", text.index],
    ["proxy", text.etfProxy],
    ["drivers", text.drivers],
  ];
  const latestClose = market.history.at(-1)?.close;
  return (
    <section className="rounded-2xl border border-border-subtle bg-bg-surface p-4 lg:p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="font-label-caps text-text-secondary">{text.detail}</div>
          <h2 className="mt-1 text-xl font-semibold text-text-primary">
            {locale === "zh" ? market.name_zh : market.name_en} · {market.symbol}
          </h2>
        </div>
        <div className="font-mono text-xs text-text-secondary">
          {market.meta.provider} · {market.meta.currency} · {market.meta.adjustment.toUpperCase()} · {market.meta.as_of} · {market.meta.timezone}
        </div>
      </div>
      <div className="mt-5 flex gap-1 border-b border-border-subtle" role="tablist">
        {tabs.map(([id, label]) => (
          <button
            aria-selected={tab === id}
            className={`px-4 py-3 text-sm ${tab === id ? "border-b-2 border-accent-success text-text-primary" : "text-text-secondary"}`}
            key={id}
            onClick={() => onTabChange(id)}
            role="tab"
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
      <div className="min-h-36 py-5" role="tabpanel">
        {tab === "index" ? <LocalIndexPanel locale={locale} market={market} /> : null}
        {tab === "drivers" ? <DriverBasketPanel locale={locale} market={market} /> : null}
        {tab === "proxy" ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <DetailMetric label={text.close} value={latestClose == null ? "—" : `${latestClose.toFixed(2)} USD`} />
            <DetailMetric label={text.week} value={formatPct(market.returns.week_pct)} />
            <DetailMetric label={text.month} value={formatPct(market.returns.month_pct)} />
            <DetailMetric label={text.volatility} value={`${market.volatility_pct.toFixed(1)}%`} />
            <DetailMetric label={text.drawdown} value={`${market.max_drawdown_pct.toFixed(1)}%`} />
          </div>
        ) : null}
      </div>
      <details className="border-t border-border-subtle pt-4 text-xs text-text-secondary">
        <summary className="cursor-pointer">{text.methodology}</summary>
        <p className="mt-2">
          {market.meta.symbol}: provider={market.meta.provider}, adjustment={market.meta.adjustment}, as_of={market.meta.as_of}, timezone={market.meta.timezone}, provenance={market.meta.provenance}
        </p>
        <ul className="mt-3 space-y-1 font-mono text-[11px]">
          <li>week: {methodology.week}</li>
          <li>month: {methodology.month}</li>
          <li>ytd: {methodology.ytd}</li>
          <li>volatility: {methodology.volatility}</li>
          <li>drawdown: {methodology.drawdown}</li>
          <li>k_shape: {methodology.k_shape}</li>
        </ul>
      </details>
    </section>
  );
}

export function LocalIndexPanel({
  locale,
  market,
}: {
  locale: Locale;
  market: AsiaRadarMarket;
}) {
  const text = copy[locale];
  const index = market.local_index;
  if (!index) {
    return (
      <PendingIndexDetail
        locale={locale}
        name={null}
        reason={text.indexReasonMissing}
      />
    );
  }
  if (index.status !== "available") {
    const name = locale === "zh" ? index.index_name_zh : index.index_name_en;
    if (index.reason_code === "provider_error") {
      return (
        <div
          className="rounded-xl border border-accent-danger/40 bg-bg-base/40 p-5"
          data-local-index-state="provider_error"
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-accent-danger">
            <AlertTriangle size={15} /> {text.indexErrorTitle}
          </div>
          <div className="mt-2 font-mono text-xs text-text-secondary">
            {name} · {index.index_symbol}
          </div>
          <p className="mt-2 font-mono text-xs text-accent-danger">
            {text.indexErrorReasonPrefix}
            {index.provider_code ? ` · ${index.provider_code}` : ""}
          </p>
          <p className="mt-2 text-xs text-text-secondary">{text.indexErrorHint}</p>
          {index.reason ? (
            <details className="mt-2 text-[10px] text-text-secondary">
              <summary className="cursor-pointer font-mono">{text.methodology}</summary>
              <p className="mt-1 break-all font-mono">{index.reason}</p>
            </details>
          ) : null}
        </div>
      );
    }
    return (
      <PendingIndexDetail
        locale={locale}
        name={name}
        reason={localIndexReasonCopy(text, index)}
      />
    );
  }

  const series = index.series;
  const lastPoint = series.at(-1);
  const indexName = locale === "zh" ? index.index_name_zh : index.index_name_en;
  const etfLast = market.history.at(-1);
  return (
    <div data-local-index-state="available">
      <div className="flex flex-wrap items-center gap-2 text-[10px]">
        <span className="rounded-full border border-warning/40 bg-warning/10 px-2.5 py-1 font-semibold text-warning">
          {text.localIndex}
        </span>
        <span className="rounded-full border border-border-subtle px-2.5 py-1 font-mono text-text-secondary">
          {index.index_symbol} · {index.currency}
        </span>
        <span className="rounded-full border border-border-subtle px-2.5 py-1 font-mono text-text-secondary">
          {text.localSession} · {index.timezone}
        </span>
        {index.provenance ? (
          <span className="rounded-full border border-border-subtle px-2.5 py-1 font-mono text-text-secondary">
            {index.provenance === "futu_cache" ? text.cached : text.live}
          </span>
        ) : null}
        <span className="font-mono text-text-secondary">
          {text.asOf} {index.as_of}
        </span>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-border-subtle bg-bg-base/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-semibold text-text-primary">
              {indexName} · {index.index_symbol}
            </span>
            <span className="font-mono text-warning">
              {text.localIndex} · {index.currency}
            </span>
          </div>
          <Sparkline
            label={`${indexName} ${text.localIndex}`}
            stroke="var(--color-warning)"
            values={series.map((point) => point.indexed_return_pct)}
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 font-mono text-xs text-text-secondary">
            <span>
              {text.close}: {lastPoint ? `${lastPoint.close.toFixed(2)} ${index.currency}` : "—"}
            </span>
            <ReturnValue locale={locale} value={lastPoint?.indexed_return_pct ?? null} />
          </div>
          <div className="mt-1 font-mono text-[10px] text-text-secondary">
            {series.length} {text.sessions} · {text.localSession} · {index.timezone}
          </div>
        </div>
        <div className="rounded-xl border border-border-subtle bg-bg-base/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-semibold text-text-primary">
              {market.symbol} · {text.etfProxy}
            </span>
            <span className="font-mono text-info">{text.etfProxy} · USD</span>
          </div>
          <Sparkline
            label={`${market.symbol} ${text.etfProxy}`}
            stroke="var(--color-info)"
            values={market.history.map((point) => point.indexed_return_pct)}
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 font-mono text-xs text-text-secondary">
            <span>
              {text.close}: {etfLast ? `${etfLast.close.toFixed(2)} USD` : "—"}
            </span>
            <ReturnValue locale={locale} value={etfLast?.indexed_return_pct ?? null} />
          </div>
          <div className="mt-1 font-mono text-[10px] text-text-secondary">
            {market.history.length} {text.sessions} · {market.meta.timezone}
          </div>
        </div>
      </div>
      <p className="mt-3 text-xs text-text-secondary">{text.indexNote}</p>
    </div>
  );
}

export function DriverBasketPanel({
  locale,
  market,
}: {
  locale: Locale;
  market: AsiaRadarMarket;
}) {
  const text = copy[locale];
  const basket = market.driver_basket;
  if (!basket) {
    return <PendingDriverDetail locale={locale} reason={text.driverReasonMissing} />;
  }
  if (basket.status !== "available") {
    if (basket.reason_code === "provider_error") {
      return (
        <div
          className="rounded-xl border border-accent-danger/40 bg-bg-base/40 p-5"
          data-driver-basket-state="provider_error"
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-accent-danger">
            <AlertTriangle size={15} /> {text.driverErrorTitle}
          </div>
          <div className="mt-2 font-mono text-xs text-text-secondary">
            {locale === "zh" ? "相关龙头股票" : basket.label_en}
          </div>
          <p className="mt-2 font-mono text-xs text-accent-danger">
            {text.indexErrorReasonPrefix}
            {basket.provider_code ? ` · ${basket.provider_code}` : ""}
          </p>
          {basket.leaders.length ? (
            <ul className="mt-2 space-y-1 font-mono text-[11px] text-text-secondary">
              {basket.leaders.map((leader) => (
                <li key={leader.symbol}>
                  {leader.symbol} · {text.driverLeaderErrorPrefix}
                  {leader.provider_code ? ` · ${leader.provider_code}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="mt-2 text-xs text-text-secondary">{text.driverErrorHint}</p>
          {basket.reason ? (
            <details className="mt-2 text-[10px] text-text-secondary">
              <summary className="cursor-pointer font-mono">{text.methodology}</summary>
              <p className="mt-1 break-all font-mono">{basket.reason}</p>
            </details>
          ) : null}
        </div>
      );
    }
    return (
      <PendingDriverDetail
        locale={locale}
        reason={driverBasketReasonCopy(text, basket)}
      />
    );
  }

  return (
    <div data-driver-basket-state="available">
      <div className="flex flex-wrap items-center gap-2 text-[10px]">
        <span className="rounded-full border border-warning/40 bg-warning/10 px-2.5 py-1 font-semibold text-warning">
          {locale === "zh" ? "相关龙头股票" : basket.label_en}
        </span>
        <span className="rounded-full border border-border-subtle px-2.5 py-1 font-mono text-text-secondary">
          {basket.basket_note}
        </span>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {basket.leaders.map((leader) => {
          const leaderName = locale === "zh" ? leader.name_zh : leader.name_en;
          const listingBadge =
            leader.listing === "us_adr" ? text.driverUsAdr : text.driverHkLocal;
          if (leader.status !== "available") {
            return (
              <div
                className="rounded-xl border border-accent-danger/40 bg-bg-base/40 p-4"
                data-driver-basket-leader="unavailable"
                key={leader.symbol}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className="font-semibold text-text-primary">
                    {leaderName} · {leader.symbol}
                  </span>
                  <span className="font-mono text-accent-danger">
                    {text.driverLeaderErrorPrefix}
                    {leader.provider_code ? ` · ${leader.provider_code}` : ""}
                  </span>
                </div>
                {leader.reason ? (
                  <p className="mt-2 font-mono text-[10px] text-text-secondary">
                    {leader.reason}
                  </p>
                ) : null}
              </div>
            );
          }
          const lastPoint = leader.series.at(-1);
          return (
            <div
              className="rounded-xl border border-border-subtle bg-bg-base/40 p-4"
              data-driver-basket-leader="available"
              key={leader.symbol}
            >
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="font-semibold text-text-primary">
                  {leaderName} · {leader.symbol}
                </span>
                <span className="font-mono text-warning">
                  {listingBadge} · {leader.currency}
                </span>
              </div>
              <Sparkline
                chartAttr="data-driver-basket-chart"
                label={`${leaderName} ${leader.symbol}`}
                stroke={
                  leader.listing === "us_adr"
                    ? "var(--color-accent-success)"
                    : "var(--color-warning)"
                }
                values={leader.series.map((point) => point.indexed_return_pct)}
              />
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 font-mono text-xs text-text-secondary">
                <span>
                  {text.close}:{" "}
                  {lastPoint ? `${lastPoint.close.toFixed(2)} ${leader.currency}` : "—"}
                </span>
                <ReturnValue locale={locale} value={lastPoint?.indexed_return_pct ?? null} />
              </div>
              <div className="mt-1 font-mono text-[10px] text-text-secondary">
                {leader.series.length} {text.sessions} · {leader.provider}
                {leader.provenance ? ` · ${leader.provenance}` : ""} · {text.asOf}{" "}
                {leader.as_of} · {leader.timezone}
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-text-secondary">{text.driverBasketNote}</p>
    </div>
  );
}

function PendingDriverDetail({
  locale,
  reason,
}: {
  locale: Locale;
  reason: string;
}) {
  const text = copy[locale];
  return (
    <div
      className="rounded-xl border border-dashed border-border-subtle p-5"
      data-driver-basket-state="pending"
    >
      <div className="text-sm font-semibold text-text-secondary">
        {text.driverPendingTitle}
      </div>
      <p className="mt-2 text-sm text-text-secondary">{reason}</p>
    </div>
  );
}

function driverBasketReasonCopy(
  text: (typeof copy)[Locale],
  basket: AsiaRadarDriverBasket,
): string {
  switch (basket.reason_code) {
    case "no_liquid_us_listing":
      return text.driverReasonNoListing;
    case "permission_not_granted":
      return text.driverReasonPermission;
    case "market_format_unsupported":
      return text.driverReasonFormat;
    case "no_verified_channel":
      return text.driverReasonChannel;
    default:
      return basket.reason ?? text.driverReasonMissing;
  }
}

function ReturnValue({
  locale,
  value,
}: {
  locale: Locale;
  value: number | null;
}) {
  const text = copy[locale];
  if (value == null) return <span>{text.windowReturn} —</span>;
  return (
    <span className={value >= 0 ? "text-accent-success" : "text-accent-danger"}>
      {text.windowReturn} {formatPct(value)}
    </span>
  );
}

function PendingIndexDetail({
  locale,
  name,
  reason,
}: {
  locale: Locale;
  name: string | null;
  reason: string;
}) {
  const text = copy[locale];
  return (
    <div
      className="rounded-xl border border-dashed border-border-subtle p-5"
      data-local-index-state="pending"
    >
      <div className="text-sm font-semibold text-text-secondary">
        {text.indexPendingTitle}
      </div>
      {name ? (
        <div className="mt-1 font-mono text-xs text-text-secondary">{name}</div>
      ) : null}
      <p className="mt-2 text-sm text-text-secondary">{reason}</p>
    </div>
  );
}

function localIndexReasonCopy(
  text: (typeof copy)[Locale],
  index: AsiaRadarLocalIndex,
): string {
  switch (index.reason_code) {
    case "permission_not_granted":
      return text.indexReasonPermission;
    case "market_format_unsupported":
      return text.indexReasonFormat;
    case "no_verified_channel":
      return text.indexReasonChannel;
    default:
      return index.reason ?? text.indexReasonMissing;
  }
}

function Sparkline({
  chartAttr,
  label,
  stroke,
  values,
}: {
  chartAttr?: string;
  label: string;
  stroke: string;
  values: number[];
}) {
  if (!values.length) return null;
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(0, ...values);
  const points = polylinePoints(values, minimum, maximum);
  const markerProps: Record<string, string> = chartAttr
    ? { [chartAttr]: "" }
    : { "data-local-index-chart": "" };
  return (
    <svg
      aria-label={label}
      className="mt-3 h-[150px] w-full overflow-visible rounded-xl bg-bg-base/50"
      {...markerProps}
      role="img"
      viewBox="0 0 720 240"
    >
      <line
        stroke="currentColor"
        strokeOpacity={0.15}
        x1={24}
        x2={696}
        y1={120}
        y2={120}
      />
      <polyline fill="none" points={points} stroke={stroke} strokeWidth={3} />
    </svg>
  );
}

function DetailMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border-subtle bg-bg-base/40 p-4">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="mt-2 font-data-mono text-lg">{value}</div>
    </div>
  );
}

function MetricCell({ value }: { value: number }) {
  return <td className={`font-mono ${value >= 0 ? "text-accent-success" : "text-accent-danger"}`}>{formatPct(value)}</td>;
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

function polylinePoints(values: number[], minimum: number, maximum: number) {
  if (!values.length) return "";
  const span = Math.max(1, maximum - minimum);
  return values
    .map((value, index) => {
      const x = values.length === 1 ? 360 : 24 + (index / (values.length - 1)) * 672;
      const y = 216 - ((value - minimum) / span) * 192;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}
