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

type BacktestPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function Backtest({ searchParams }: BacktestPageProps) {
  const params = (await searchParams) ?? {};
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
          <h2 className="font-headline-lg text-text-primary">Backtest Config</h2>
          <p className="mt-1 font-body-sm text-text-secondary">
            Interactive run controls are connected in P0-4.
          </p>
        </div>
        <div className="flex flex-col gap-4 p-4">
          <div className="rounded border border-border-subtle bg-surface-muted p-3">
            <div className="font-label-caps text-text-secondary">Latest run</div>
            <div className="mt-2 truncate font-data-mono text-text-primary">
              {latest?.id ?? "No API backtest yet"}
            </div>
            {latest?.source ? (
              <div className="mt-2">
                <DataSourceBadge source={latest.source} />
              </div>
            ) : null}
            {latest ? (
              <Link
                aria-label={`Open ${latest.id}`}
                className="mt-3 inline-flex rounded border border-border-subtle px-3 py-1.5 font-body-sm text-info"
                href={`/backtest/${latest.id}`}
              >
                Open run
              </Link>
            ) : null}
          </div>
          <div className="rounded border border-border-subtle bg-surface-muted p-3">
            <div className="font-label-caps text-text-secondary">Benchmark</div>
            <div className="mt-2 font-data-mono text-text-primary">{benchmark.symbol}</div>
          </div>
          <BacktestForm initialValues={initialValues} />
        </div>
      </aside>

      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <ErrorBanner messages={[backtests.apiError, benchmark.apiError, detail?.apiError]} />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded border border-border-subtle bg-bg-surface p-3">
            <span className="font-label-caps text-text-secondary">Total Return</span>
            <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">
              {formatPercent(latest?.metrics?.total_return)}
            </div>
            <span className="font-data-mono text-[10px] text-text-secondary">
              BMK: {formatPercent(benchmark.metrics.total_return)}
            </span>
          </div>
          <div className="rounded border border-border-subtle bg-bg-surface p-3">
            <span className="font-label-caps text-text-secondary">Sharpe Ratio</span>
            <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">
              {latest?.metrics?.sharpe?.toFixed(2) ?? "--"}
            </div>
            <span className="font-data-mono text-[10px] text-text-secondary">
              BMK: {benchmark.metrics.sharpe.toFixed(2)}
            </span>
          </div>
          <div className="rounded border border-border-subtle bg-bg-surface p-3">
            <span className="font-label-caps text-text-secondary">Max Drawdown</span>
            <div className="mt-2 font-data-mono text-lg font-bold text-danger">
              {formatPercent(latest?.metrics?.max_drawdown)}
            </div>
            <span className="font-data-mono text-[10px] text-text-secondary">
              BMK: {formatPercent(benchmark.metrics.max_drawdown)}
            </span>
          </div>
        </div>

        <section className="rounded border border-border-subtle bg-bg-surface p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-label-caps text-text-primary">Strategy vs Benchmark</h3>
              <p className="mt-1 font-body-sm text-text-secondary">
                Normalized equity curves from the newest backtest and benchmark API.
              </p>
            </div>
            <div className="flex gap-4 font-data-mono text-[11px]">
              <span className="text-accent-success">Strategy</span>
              <span className="text-info">Benchmark</span>
            </div>
          </div>
          {comparisonRows.length ? (
            <EquityComparisonChart rows={comparisonRows} />
          ) : (
            <EmptyState
              title="No equity curve rows"
              description="Run a backtest to compare the strategy with the benchmark curve."
            />
          )}
        </section>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <DataPreviewTable
            title="Trade Blotter"
            description="Latest simulated trades from the newest backtest run."
            rows={detail?.trade_blotter ?? []}
            emptyTitle="Trade blotter unavailable"
            emptyDescription="No backtest detail has been created yet."
          />
          <div className="lg:col-span-2">
            <DataPreviewTable
              title="Orders"
              description="Submitted orders from the newest backtest run."
              rows={detail?.orders ?? []}
              emptyTitle="Order table unavailable"
              emptyDescription="Orders appear after the backtest engine writes a run."
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
