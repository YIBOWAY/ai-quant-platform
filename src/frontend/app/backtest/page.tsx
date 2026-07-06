import Link from "next/link";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { SyntheticMetricsWarning } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { EquityComparisonChart } from "@/components/EquityComparisonChart";
import { ErrorBanner } from "@/components/ErrorBanner";
import { BacktestForm, type BacktestFormInitialValues } from "@/components/forms/BacktestForm";
import {
  Card,
  MetricStat,
  PageHeader,
  SectionTitle,
  TerminalSplitShell,
} from "@/components/ui/primitives";
import {
  formatPercent,
  getBacktestDetail,
  getBacktests,
  getFactors,
  getStrategies,
  getUniverses,
} from "@/lib/api";
import { normalizeEquity } from "@/lib/equity";
import { localizePath } from "@/lib/locale";
import { isSampleSource, selectDisplayRun, shouldIncludeSampleRuns } from "@/lib/runSource";
import { getCachedHealth } from "@/lib/serverApi";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Research Pipeline",
    title: "Backtest",
    subtitle:
      "Replay a strategy on historical data before trusting it in paper trading. Configure on the left; the newest run's results show on the right.",
    configTitle: "Backtest Config",
    latestRun: "Latest run",
    noBacktest: "No API backtest yet",
    openAria: (id: string) => `Open ${id}`,
    openRun: "Open run",
    benchmark: "Benchmark",
    totalReturn: "Total Return",
    bmk: (value: string) => `Benchmark: ${value}`,
    sharpeRatio: "Sharpe Ratio",
    maxDrawdown: "Max Drawdown",
    strategyVsBenchmark: "Strategy vs Benchmark",
    normalizedDesc: (symbol: string) =>
      `Normalized equity curves (both start at 1.0) from the newest run and benchmark ${symbol}.`,
    benchmarkFailed: (symbol: string) =>
      `Benchmark ${symbol} unavailable; showing strategy only.`,
    strategy: "Strategy",
    noEquityTitle: "No equity curve rows",
    noEquityDesc: "Run a backtest with the form on the left to compare it against the benchmark.",
    historyTitle: "Run History",
    historyDesc: "Recent backtest runs saved by the backend. Click an ID to open details.",
    historyEmptyTitle: "No saved runs",
    historyEmptyDesc: "Runs appear here after the backtest engine writes results.",
    runId: "Run ID",
    source: "Source",
    hiddenSamples: (count: number) =>
      `${count} sample run${count === 1 ? "" : "s"} hidden. Append ?include_sample=1 to the URL to show them.`,
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
    eyebrow: "研究流水线",
    title: "回测",
    subtitle: "在进入模拟交易之前，用历史数据重放策略验证想法。左侧配置参数，右侧展示最新一次运行的结果。",
    configTitle: "回测配置",
    latestRun: "最新运行",
    noBacktest: "暂无 API 回测",
    openAria: (id: string) => `打开 ${id}`,
    openRun: "打开运行",
    benchmark: "基准",
    totalReturn: "总收益",
    bmk: (value: string) => `基准：${value}`,
    sharpeRatio: "夏普比率",
    maxDrawdown: "最大回撤",
    strategyVsBenchmark: "策略 vs 基准",
    normalizedDesc: (symbol: string) =>
      `最新运行与基准 ${symbol} 的归一化权益曲线（均从 1.0 起步）。`,
    benchmarkFailed: (symbol: string) => `基准 ${symbol} 读取失败，仅显示策略曲线。`,
    strategy: "策略",
    noEquityTitle: "暂无权益曲线数据",
    noEquityDesc: "用左侧表单运行一次回测，即可与基准曲线对比。",
    historyTitle: "运行历史",
    historyDesc: "后端保存的近期回测运行，点击 ID 查看详情。",
    historyEmptyTitle: "暂无保存的运行",
    historyEmptyDesc: "回测引擎写入结果后将在这里列出。",
    runId: "运行 ID",
    source: "数据来源",
    hiddenSamples: (count: number) =>
      `已隐藏 ${count} 条样例运行。在 URL 加 ?include_sample=1 可显示。`,
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
  const [backtests, strategies, universes, factors, health] = await Promise.all([
    getBacktests(),
    getStrategies(),
    getUniverses(),
    getFactors(),
    getCachedHealth(),
  ]);
  const futuReachable = health.futu_opend?.reachable !== false;
  const includeSample = shouldIncludeSampleRuns(params);
  const allRuns = backtests.backtests;
  const visibleRuns = includeSample ? allRuns : allRuns.filter((run) => !isSampleSource(run.source));
  const hiddenSampleCount = allRuns.length - visibleRuns.length;
  const latest = selectDisplayRun(allRuns, includeSample);
  const detail = latest ? await getBacktestDetail(latest.id) : null;
  const latestRequest =
    detail && typeof detail.metadata === "object" && detail.metadata !== null
      ? (detail.metadata.request as
          | { benchmark_symbol?: string; provider?: string; start?: string; end?: string }
          | undefined)
      : undefined;
  const benchmarkSymbol =
    typeof latestRequest?.benchmark_symbol === "string" ? latestRequest.benchmark_symbol : "SPY";
  const benchmark = detail?.benchmark ?? null;
  const benchmarkFailed = Boolean(benchmark?.apiError) || Boolean(detail && !benchmark?.equity_curve?.length);
  const benchmarkTotalReturn = metricNumber(benchmark?.metrics?.total_return);
  const benchmarkSharpe = metricNumber(benchmark?.metrics?.sharpe);
  const benchmarkMaxDrawdown = metricNumber(benchmark?.metrics?.max_drawdown);
  const comparisonRows = normalizeEquity(detail?.equity_curve ?? [], benchmark?.equity_curve);

  return (
    <TerminalSplitShell
      sidebar={
        <>
          <div className="border-b border-border-subtle p-4">
            <h2 className="font-headline-lg text-text-primary">{text.configTitle}</h2>
          </div>
          <div className="flex flex-col gap-4 p-4">
            <div className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
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
                  className="mt-3 inline-flex rounded-lg border border-border-subtle px-3 py-1.5 font-body-sm text-info focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
                  href={localizePath(`/backtest/${latest.id}`, locale)}
                >
                  {text.openRun}
                </Link>
              ) : null}
            </div>
            <BacktestForm
              factors={factors.factors}
              initialValues={initialValues}
              locale={locale}
              strategies={strategies.strategies}
              universes={universes.universes}
              futuReachable={futuReachable}
            />
          </div>
        </>
      }
      sidebarClassName="lg:w-[320px]"
    >
      <PageHeader eyebrow={text.eyebrow} title={text.title} subtitle={text.subtitle} />
        <ErrorBanner
          messages={[
            backtests.apiError,
            strategies.apiError,
            universes.apiError,
            factors.apiError,
            detail?.apiError,
          ]}
        />
        <SyntheticMetricsWarning source={latest?.source} locale={locale} />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <MetricStat
            label={text.totalReturn}
            value={formatPercent(latest?.metrics?.total_return)}
            delta={
              benchmarkTotalReturn !== undefined
                ? text.bmk(formatPercent(benchmarkTotalReturn))
                : undefined
            }
          />
          <MetricStat
            label={text.sharpeRatio}
            value={latest?.metrics?.sharpe?.toFixed(2) ?? "--"}
            delta={benchmarkSharpe !== undefined ? text.bmk(benchmarkSharpe.toFixed(2)) : undefined}
          />
          <MetricStat
            label={text.maxDrawdown}
            value={formatPercent(latest?.metrics?.max_drawdown)}
            tone="danger"
            delta={
              benchmarkMaxDrawdown !== undefined
                ? text.bmk(formatPercent(benchmarkMaxDrawdown))
                : undefined
            }
          />
        </div>

        <Card>
          <SectionTitle
            title={text.strategyVsBenchmark}
            hint={
              benchmarkFailed ? text.benchmarkFailed(benchmarkSymbol) : text.normalizedDesc(benchmarkSymbol)
            }
          />
          {benchmark?.source ? <DataSourceBadge source={benchmark.source} /> : null}
          {comparisonRows.length ? (
            <EquityComparisonChart
              rows={comparisonRows}
              labels={{ strategy: text.strategy, benchmark: `${text.benchmark} ${benchmarkSymbol}` }}
            />
          ) : (
            <EmptyState title={text.noEquityTitle} description={text.noEquityDesc} />
          )}
        </Card>

        <Card>
          <SectionTitle title={text.historyTitle} hint={text.historyDesc} />
          {visibleRuns.length ? (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse font-body-sm">
                <thead>
                  <tr className="border-b border-border-subtle text-left">
                    <th className="px-2 py-2 font-label-caps text-text-secondary">{text.runId}</th>
                    <th className="px-2 py-2 font-label-caps text-text-secondary">{text.source}</th>
                    <th className="px-2 py-2 text-right font-label-caps text-text-secondary">
                      {text.totalReturn}
                    </th>
                    <th className="px-2 py-2 text-right font-label-caps text-text-secondary">
                      {text.sharpeRatio}
                    </th>
                    <th className="px-2 py-2 text-right font-label-caps text-text-secondary">
                      {text.maxDrawdown}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRuns.slice(0, 10).map((run) => (
                    <tr key={run.id} className="border-b border-border-subtle/60">
                      <td className="px-2 py-2">
                        <Link
                          className="font-data-mono text-info"
                          href={localizePath(`/backtest/${run.id}`, locale)}
                        >
                          {run.id}
                        </Link>
                      </td>
                      <td className="px-2 py-2">
                        {run.source ? <DataSourceBadge source={run.source} /> : "--"}
                      </td>
                      <td className="px-2 py-2 text-right font-data-mono text-text-primary">
                        {formatPercent(run.metrics?.total_return)}
                      </td>
                      <td className="px-2 py-2 text-right font-data-mono text-text-primary">
                        {run.metrics?.sharpe?.toFixed(2) ?? "--"}
                      </td>
                      <td className="px-2 py-2 text-right font-data-mono text-danger">
                        {formatPercent(run.metrics?.max_drawdown)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title={text.historyEmptyTitle} description={text.historyEmptyDesc} />
          )}
          {hiddenSampleCount > 0 ? (
            <p className="mt-3 font-body-sm text-text-secondary">
              {text.hiddenSamples(hiddenSampleCount)}
            </p>
          ) : null}
        </Card>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <DataPreviewTable
            title={text.tradeBlotterTitle}
            description={text.tradeBlotterDesc}
            rows={detail?.trade_blotter ?? []}
            emptyTitle={text.tradeBlotterEmptyTitle}
            emptyDescription={text.tradeBlotterEmptyDesc}
          />
          <DataPreviewTable
            title={text.ordersTitle}
            description={text.ordersDesc}
            rows={detail?.orders ?? []}
            emptyTitle={text.ordersEmptyTitle}
            emptyDescription={text.ordersEmptyDesc}
          />
        </section>
    </TerminalSplitShell>
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
  const universeId = stringParam(params.universe_id);
  if (universeId) {
    initialValues.universe_id = universeId;
  }
  const strategyId = stringParam(params.strategy_id);
  if (strategyId) {
    initialValues.strategy_id = strategyId;
  }
  const benchmarkSymbol = stringParam(params.benchmark_symbol);
  if (benchmarkSymbol) {
    initialValues.benchmark_symbol = benchmarkSymbol;
  }
  const factorIds = stringParam(params.factor_ids);
  if (factorIds) {
    initialValues.factor_ids = factorIds
      .split(",")
      .map((factorId) => factorId.trim())
      .filter(Boolean);
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

function metricNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
