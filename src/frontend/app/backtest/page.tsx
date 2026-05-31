import Link from "next/link";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { EquityComparisonChart } from "@/components/EquityComparisonChart";
import { ErrorBanner } from "@/components/ErrorBanner";
import { BacktestForm, type BacktestFormInitialValues } from "@/components/forms/BacktestForm";
import {
  formatPercent,
  getBacktestDetail,
  getBacktests,
  getBenchmark,
} from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    configTitle: "Backtest Config",
    configSubtitle: "Interactive run controls are connected in P0-4.",
    latestRun: "Latest run",
    noBacktest: "No API backtest yet",
    openAria: (id: string) => `Open ${id}`,
    openRun: "Open run",
    benchmark: "Benchmark",
    totalReturn: "Total Return",
    bmk: "BMK",
    sharpeRatio: "Sharpe Ratio",
    maxDrawdown: "Max Drawdown",
    strategyVsBenchmark: "Strategy vs Benchmark",
    normalizedDesc: "Normalized equity curves from the newest backtest and benchmark API.",
    strategy: "Strategy",
    noEquityTitle: "No equity curve rows",
    noEquityDesc: "Run a backtest to compare the strategy with the benchmark curve.",
    tradeBlotterTitle: "Trade Blotter",
    tradeBlotterDesc: "Latest simulated trades from the newest backtest run.",
    tradeBlotterEmptyTitle: "Trade blotter unavailable",
    tradeBlotterEmptyDesc: "No backtest detail has been created yet.",
    ordersTitle: "Orders",
    ordersDesc: "Submitted orders from the newest backtest run.",
    ordersEmptyTitle: "Order table unavailable",
    ordersEmptyDesc: "Orders appear after the backtest engine writes a run.",
  },
  zh: {
    configTitle: "回测配置",
    configSubtitle: "交互式运行控制已在 P0-4 阶段接入。",
    latestRun: "最新运行",
    noBacktest: "暂无 API 回测",
    openAria: (id: string) => `打开 ${id}`,
    openRun: "打开运行",
    benchmark: "基准",
    totalReturn: "总收益",
    bmk: "基准",
    sharpeRatio: "夏普比率",
    maxDrawdown: "最大回撤",
    strategyVsBenchmark: "策略 vs 基准",
    normalizedDesc: "来自最新回测与基准 API 的归一化权益曲线。",
    strategy: "策略",
    noEquityTitle: "暂无权益曲线数据",
    noEquityDesc: "运行一次回测以将策略与基准曲线进行对比。",
    tradeBlotterTitle: "成交记录",
    tradeBlotterDesc: "来自最新回测运行的模拟成交。",
    tradeBlotterEmptyTitle: "暂无成交记录",
    tradeBlotterEmptyDesc: "尚未生成任何回测明细。",
    ordersTitle: "订单",
    ordersDesc: "来自最新回测运行的已提交订单。",
    ordersEmptyTitle: "暂无订单表",
    ordersEmptyDesc: "回测引擎写入运行后将显示订单。",
  },
} as const;

type BacktestPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function Backtest({ searchParams }: BacktestPageProps) {
  const params = (await searchParams) ?? {};
  const locale = await getServerLocale(params);
  const text = copy[locale];
  const initialValues = backtestInitialValuesFromSearch(params);
  const backtests = await getBacktests();
  const latest = backtests.backtests[0];
  const detail = latest ? await getBacktestDetail(latest.id) : null;
  const latestRequest =
    detail && typeof detail.metadata === "object" && detail.metadata !== null
      ? (detail.metadata.request as
          | { symbols?: string[]; start?: string; end?: string }
          | undefined)
      : undefined;
  const benchmarkSymbol =
    Array.isArray(latestRequest?.symbols) && latestRequest.symbols.length
      ? latestRequest.symbols[0]
      : "SPY";
  const benchmarkStart =
    typeof latestRequest?.start === "string" ? latestRequest.start : "2024-01-02";
  const benchmarkEnd =
    typeof latestRequest?.end === "string" ? latestRequest.end : "2024-01-12";
  const benchmark = await getBenchmark(
    benchmarkSymbol,
    benchmarkStart,
    benchmarkEnd,
  );
  const comparisonRows = buildComparisonRows(detail?.equity_curve ?? [], benchmark.equity_curve);

  return (
    <div className="flex h-full flex-1 overflow-hidden bg-base">
      <aside className="flex h-full w-[320px] flex-col overflow-y-auto border-r border-border-subtle bg-bg-surface">
        <div className="border-b border-border-subtle p-4">
          <h2 className="font-headline-lg text-text-primary">{text.configTitle}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">
            {text.configSubtitle}
          </p>
        </div>
        <div className="flex flex-col gap-4 p-4">
          <div className="rounded border border-border-subtle bg-surface-muted p-3">
            <div className="font-label-caps text-text-secondary">{text.latestRun}</div>
            <div className="mt-2 truncate font-data-mono text-text-primary">
              {latest?.id ?? text.noBacktest}
            </div>
            {latest?.source ? (
              <div className="mt-2">
                <DataSourceBadge source={latest.source} />
              </div>
            ) : null}
            {latest ? (
              <Link
                aria-label={text.openAria(latest.id)}
                className="mt-3 inline-flex rounded border border-border-subtle px-3 py-1.5 font-body-sm text-info"
                href={`/backtest/${latest.id}`}
              >
                {text.openRun}
              </Link>
            ) : null}
          </div>
          <div className="rounded border border-border-subtle bg-surface-muted p-3">
            <div className="font-label-caps text-text-secondary">{text.benchmark}</div>
            <div className="mt-2 font-data-mono text-text-primary">{benchmark.symbol}</div>
            <div className="mt-2">
              <DataSourceBadge source={benchmark.source} />
            </div>
          </div>
          <BacktestForm initialValues={initialValues} locale={locale} />
        </div>
      </aside>

      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <ErrorBanner messages={[backtests.apiError, benchmark.apiError, detail?.apiError]} />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded border border-border-subtle bg-bg-surface p-3">
            <span className="font-label-caps text-text-secondary">{text.totalReturn}</span>
            <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">
              {formatPercent(latest?.metrics?.total_return)}
            </div>
            <span className="font-data-mono text-[10px] text-text-secondary">
              {text.bmk}: {formatPercent(benchmark.metrics.total_return)}
            </span>
          </div>
          <div className="rounded border border-border-subtle bg-bg-surface p-3">
            <span className="font-label-caps text-text-secondary">{text.sharpeRatio}</span>
            <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">
              {latest?.metrics?.sharpe?.toFixed(2) ?? "--"}
            </div>
            <span className="font-data-mono text-[10px] text-text-secondary">
              {text.bmk}: {benchmark.metrics.sharpe.toFixed(2)}
            </span>
          </div>
          <div className="rounded border border-border-subtle bg-bg-surface p-3">
            <span className="font-label-caps text-text-secondary">{text.maxDrawdown}</span>
            <div className="mt-2 font-data-mono text-lg font-bold text-danger">
              {formatPercent(latest?.metrics?.max_drawdown)}
            </div>
            <span className="font-data-mono text-[10px] text-text-secondary">
              {text.bmk}: {formatPercent(benchmark.metrics.max_drawdown)}
            </span>
          </div>
        </div>

        <section className="rounded border border-border-subtle bg-bg-surface p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-label-caps text-text-primary">{text.strategyVsBenchmark}</h3>
              <p className="mt-1 font-body-sm text-text-secondary">
                {text.normalizedDesc}
              </p>
            </div>
            <div className="flex gap-4 font-data-mono text-[11px]">
              <span className="text-accent-success">{text.strategy}</span>
              <span className="text-info">{text.benchmark}</span>
            </div>
          </div>
          {comparisonRows.length ? (
            <EquityComparisonChart rows={comparisonRows} />
          ) : (
            <EmptyState
              title={text.noEquityTitle}
              description={text.noEquityDesc}
            />
          )}
        </section>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <DataPreviewTable
            title={text.tradeBlotterTitle}
            description={text.tradeBlotterDesc}
            rows={detail?.trade_blotter ?? []}
            emptyTitle={text.tradeBlotterEmptyTitle}
            emptyDescription={text.tradeBlotterEmptyDesc}
          />
          <div className="lg:col-span-2">
            <DataPreviewTable
              title={text.ordersTitle}
              description={text.ordersDesc}
              rows={detail?.orders ?? []}
              emptyTitle={text.ordersEmptyTitle}
              emptyDescription={text.ordersEmptyDesc}
            />
          </div>
        </section>
      </div>
    </div>
  );
}

function backtestInitialValuesFromSearch(
  params: Record<string, string | string[] | undefined>,
): BacktestFormInitialValues {
  const provider = stringParam(params.provider);
  const initialValues: BacktestFormInitialValues = {};
  const symbols = stringParam(params.symbols);
  if (symbols) {
    initialValues.symbols = symbols;
  }
  for (const key of ["start", "end"] as const) {
    const value = stringParam(params[key]);
    if (value) {
      initialValues[key] = value;
    }
  }
  if (provider === "sample" || provider === "futu" || provider === "tiingo") {
    initialValues.provider = provider;
  }
  for (const key of [
    "lookback",
    "top_n",
    "initial_cash",
    "commission_bps",
    "slippage_bps",
  ] as const) {
    const value = numberParam(params[key]);
    if (value !== undefined) {
      initialValues[key] = value;
    }
  }
  return initialValues;
}

function stringParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function numberParam(value: string | string[] | undefined) {
  const parsed = Number(stringParam(value));
  return Number.isFinite(parsed) ? parsed : undefined;
}

function buildComparisonRows(
  strategyRows: Array<Record<string, unknown>>,
  benchmarkRows: Array<{ timestamp: string; equity: number }>,
) {
  const strategy = normalizeSeries(
    strategyRows.map((point, index) => ({
      timestamp: String(point.timestamp ?? `row-${index}`),
      value: Number(point.equity ?? 0),
    })),
  );
  const benchmark = normalizeSeries(
    benchmarkRows.map((point) => ({
      timestamp: point.timestamp,
      value: point.equity,
    })),
  );
  const count = Math.max(strategy.length, benchmark.length);
  return Array.from({ length: count }, (_item, index) => ({
    timestamp:
      strategy[index]?.timestamp?.slice(0, 10) ??
      benchmark[index]?.timestamp?.slice(0, 10) ??
      `row-${index + 1}`,
    strategy: strategy[index]?.value ?? null,
    benchmark: benchmark[index]?.value ?? null,
  }));
}

function normalizeSeries(rows: Array<{ timestamp: string; value: number }>) {
  const first = rows.find((row) => Number.isFinite(row.value) && row.value > 0)?.value;
  if (!first) {
    return [];
  }
  return rows
    .filter((row) => Number.isFinite(row.value))
    .map((row) => ({
      timestamp: row.timestamp,
      value: row.value / first,
    }));
}
