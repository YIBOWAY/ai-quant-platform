import Link from "next/link";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { SyntheticMetricsWarning } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { EquityComparisonChart } from "@/components/EquityComparisonChart";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Card, MetricStat, PageHeader, SectionTitle, StatusPill } from "@/components/ui/primitives";
import { formatPercent, getBacktestDetail } from "@/lib/api";
import { normalizeEquity } from "@/lib/equity";
import { localizePath } from "@/lib/locale";
import { getServerLocale } from "@/lib/serverLocale";

// Note: the English page title, "Metrics", and "Trade Blotter" strings are
// asserted by e2e specs (run-detail-routes.spec.ts) — keep them verbatim.
const copy = {
  en: {
    eyebrow: "Backtest",
    title: "Backtest Run Detail",
    back: "Back to Backtest",
    totalReturn: "Total Return",
    sharpe: "Sharpe",
    maxDrawdown: "Max Drawdown",
    runNotes: "Run notes",
    equityTitle: "Equity Curve Comparison",
    equityHint: (symbol: string) => `Strategy vs ${symbol} benchmark (both normalized to 1.0).`,
    benchmarkFailed: (symbol: string) => `Benchmark ${symbol} unavailable; showing strategy only.`,
    strategy: "Strategy",
    benchmark: "Benchmark",
    noEquityTitle: "No equity curve rows",
    noEquityDesc: "This run has metadata, but no saved equity curve table was found.",
    window: "Window",
    provider: "Provider",
    universe: "Universe",
    metricsTitle: "Metrics",
    metricsDesc: "Metrics JSON saved with this run.",
    metricsEmptyTitle: "Metrics unavailable",
    metricsEmptyDesc: "No metrics were found for this run.",
    metadataTitle: "Metadata",
    metadataDesc: "Run request and saved output paths.",
    metadataEmptyTitle: "Metadata unavailable",
    metadataEmptyDesc: "Metadata is empty for this run.",
    blotterTitle: "Trade Blotter",
    blotterDesc: "Simulated trades from this backtest run.",
    blotterEmptyTitle: "Trade Blotter",
    blotterEmptyDesc: "No trade blotter rows were saved for this run.",
    ordersTitle: "Orders",
    ordersDesc: "Orders submitted by this backtest run.",
    ordersEmptyTitle: "Orders",
    ordersEmptyDesc: "No order rows were saved for this run.",
    positionsTitle: "Positions",
    positionsDesc: "Position rows saved by this backtest run.",
    positionsEmptyTitle: "Positions",
    positionsEmptyDesc: "No position rows were saved for this run.",
    attributionTitle: "Return Attribution",
    attributionDesc: "Per-name contribution to this run's P&L (mark-to-market on held quantity).",
    attributionEmptyTitle: "Return Attribution",
    attributionEmptyDesc: "No attribution rows were saved for this run.",
  },
  zh: {
    eyebrow: "回测",
    title: "回测运行详情",
    back: "返回回测",
    totalReturn: "总收益",
    sharpe: "夏普",
    maxDrawdown: "最大回撤",
    runNotes: "运行备注",
    equityTitle: "权益曲线对比",
    equityHint: (symbol: string) => `策略 vs 基准 ${symbol}（均归一化到 1.0）。`,
    benchmarkFailed: (symbol: string) => `基准 ${symbol} 读取失败，仅显示策略曲线。`,
    strategy: "策略",
    benchmark: "基准",
    noEquityTitle: "暂无权益曲线数据",
    noEquityDesc: "该运行有元数据，但没有保存权益曲线表。",
    window: "区间",
    provider: "数据源",
    universe: "股票池",
    metricsTitle: "指标",
    metricsDesc: "该运行保存的指标 JSON。",
    metricsEmptyTitle: "暂无指标",
    metricsEmptyDesc: "未找到该运行的指标。",
    metadataTitle: "元数据",
    metadataDesc: "运行请求与保存的输出路径。",
    metadataEmptyTitle: "暂无元数据",
    metadataEmptyDesc: "该运行的元数据为空。",
    blotterTitle: "成交记录",
    blotterDesc: "该回测运行的模拟成交。",
    blotterEmptyTitle: "成交记录",
    blotterEmptyDesc: "该运行没有保存成交记录。",
    ordersTitle: "订单",
    ordersDesc: "该回测运行提交的订单。",
    ordersEmptyTitle: "订单",
    ordersEmptyDesc: "该运行没有保存订单。",
    positionsTitle: "持仓",
    positionsDesc: "该回测运行保存的持仓行。",
    positionsEmptyTitle: "持仓",
    positionsEmptyDesc: "该运行没有保存持仓。",
    attributionTitle: "收益归因",
    attributionDesc: "各标的对本次运行盈亏的贡献（按持有数量盯市）。",
    attributionEmptyTitle: "收益归因",
    attributionEmptyDesc: "该运行没有保存归因数据。",
  },
} as const;

type BacktestRunDetailPageProps = {
  params?: Promise<{ runId?: string }>;
};

export default async function BacktestRunDetailPage({ params }: BacktestRunDetailPageProps) {
  const locale = await getServerLocale();
  const text = copy[locale];
  const runId = (await params)?.runId ?? "";
  const detail = await getBacktestDetail(runId);
  const metadata = detail.metadata ?? {};
  const request = asRecord(metadata.request);
  const source = typeof metadata.source === "string" ? metadata.source : undefined;
  const metrics = asRecord(
    detail.metrics && Object.keys(detail.metrics).length ? detail.metrics : metadata.metrics,
  );

  const benchmarkSymbol =
    typeof request.benchmark_symbol === "string" ? request.benchmark_symbol : "SPY";
  const benchmarkStart = typeof request.start === "string" ? request.start : undefined;
  const benchmarkEnd = typeof request.end === "string" ? request.end : undefined;
  const benchmarkProvider = typeof request.provider === "string" ? request.provider : undefined;
  const benchmark = detail.benchmark;

  const chartRows = normalizeEquity(detail.equity_curve, benchmark?.equity_curve);
  const benchmarkFailed = Boolean(benchmark?.apiError);
  const warnings = arrayOfStrings(metadata.warnings);
  const universeId = typeof request.universe_id === "string" ? request.universe_id : undefined;

  return (
    <main className="flex h-full flex-col gap-4 overflow-y-auto bg-bg-base p-5">
      <PageHeader
        eyebrow={text.eyebrow}
        title={text.title}
        subtitle={runId}
        actions={
          <Link
            className="rounded-lg border border-border-subtle px-3 py-2 font-body-sm text-text-primary"
            href={localizePath("/backtest", locale)}
          >
            {text.back}
          </Link>
        }
      />
      <ErrorBanner messages={[detail.apiError]} />
      <SyntheticMetricsWarning source={source} locale={locale} />
      <div className="flex flex-wrap items-center gap-2">
        {source ? <DataSourceBadge source={source} /> : null}
        {benchmarkStart && benchmarkEnd ? (
          <StatusPill label={text.window} value={`${benchmarkStart} → ${benchmarkEnd}`} />
        ) : null}
        {benchmarkProvider ? <StatusPill label={text.provider} value={benchmarkProvider} /> : null}
        {universeId ? <StatusPill label={text.universe} value={universeId} /> : null}
        <StatusPill label={text.benchmark} value={benchmarkSymbol} tone="info" />
      </div>

      <section className="grid gap-3 md:grid-cols-3">
        <MetricStat label={text.totalReturn} value={formatPercent(toNumber(metrics?.total_return))} />
        <MetricStat label={text.sharpe} value={num(toNumber(metrics?.sharpe), 2)} />
        <MetricStat
          label={text.maxDrawdown}
          value={formatPercent(toNumber(metrics?.max_drawdown))}
          tone="danger"
        />
      </section>
      <WarningsPanel title={text.runNotes} warnings={warnings} />

      <Card>
        <SectionTitle
          title={text.equityTitle}
          hint={
            chartRows.length
              ? benchmarkFailed
                ? text.benchmarkFailed(benchmarkSymbol)
                : text.equityHint(benchmarkSymbol)
              : undefined
          }
        />
        {benchmark?.source ? <DataSourceBadge source={benchmark.source} /> : null}
        {chartRows.length ? (
          <EquityComparisonChart
            rows={chartRows}
            labels={{ strategy: text.strategy, benchmark: `${text.benchmark} ${benchmarkSymbol}` }}
          />
        ) : (
          <EmptyState title={text.noEquityTitle} description={text.noEquityDesc} />
        )}
      </Card>

      <section className="grid gap-4 lg:grid-cols-2">
        <DataPreviewTable
          description={text.metricsDesc}
          emptyDescription={text.metricsEmptyDesc}
          emptyTitle={text.metricsEmptyTitle}
          rows={metricsRows(metrics)}
          title={text.metricsTitle}
        />
        <DataPreviewTable
          description={text.metadataDesc}
          emptyDescription={text.metadataEmptyDesc}
          emptyTitle={text.metadataEmptyTitle}
          rows={objectRows(metadata)}
          title={text.metadataTitle}
        />
        <DataPreviewTable
          description={text.blotterDesc}
          emptyDescription={text.blotterEmptyDesc}
          emptyTitle={text.blotterEmptyTitle}
          rows={detail.trade_blotter}
          title={text.blotterTitle}
        />
        <DataPreviewTable
          description={text.ordersDesc}
          emptyDescription={text.ordersEmptyDesc}
          emptyTitle={text.ordersEmptyTitle}
          rows={detail.orders}
          title={text.ordersTitle}
        />
        <div className="lg:col-span-2">
          <DataPreviewTable
            description={text.positionsDesc}
            emptyDescription={text.positionsEmptyDesc}
            emptyTitle={text.positionsEmptyTitle}
            rows={detail.positions}
            title={text.positionsTitle}
          />
        </div>
        <div className="lg:col-span-2">
          <DataPreviewTable
            description={text.attributionDesc}
            emptyDescription={text.attributionEmptyDesc}
            emptyTitle={text.attributionEmptyTitle}
            rows={detail.attribution}
            title={text.attributionTitle}
          />
        </div>
      </section>
    </main>
  );
}

function WarningsPanel({ title, warnings }: { title: string; warnings: string[] }) {
  if (!warnings.length) {
    return null;
  }
  return (
    <section className="rounded-lg border border-warning/40 bg-warning/10 p-4 text-warning">
      <h2 className="font-label-caps">{title}</h2>
      <ul className="mt-2 space-y-1 font-body-sm">
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </section>
  );
}

function arrayOfStrings(value: unknown) {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function metricsRows(metrics: unknown) {
  return objectRows(asRecord(metrics));
}

function objectRows(value: unknown) {
  return Object.entries(asRecord(value)).map(([key, item]) => ({
    key,
    value: typeof item === "object" && item !== null ? JSON.stringify(item) : item,
  }));
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function toNumber(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function num(value: number | undefined, digits = 2) {
  return value === undefined ? "--" : value.toFixed(digits);
}
