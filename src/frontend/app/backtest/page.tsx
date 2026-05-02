import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { BacktestForm } from "@/components/forms/BacktestForm";
import {
  formatPercent,
  getBacktestDetail,
  getBacktests,
  getBenchmark,
} from "@/lib/api";

function curveBarWidth(value: number, min: number, max: number) {
  if (max <= min) {
    return 40;
  }
  return 8 + ((value - min) / (max - min)) * 92;
}

export default async function Backtest() {
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
  const benchmarkProvider =
    latest?.source?.startsWith("futu")
      ? "futu"
      : latest?.source?.startsWith("tiingo")
        ? "tiingo"
        : "sample";
  const benchmark = await getBenchmark(
    benchmarkSymbol,
    benchmarkStart,
    benchmarkEnd,
    benchmarkProvider,
  );
  const strategyEquity = (detail?.equity_curve ?? []).map((point) => Number(point.equity ?? 0));
  const benchmarkEquity = benchmark.equity_curve.map((point) => point.equity);
  const strategyMin = strategyEquity.length ? Math.min(...strategyEquity) : 0;
  const strategyMax = strategyEquity.length ? Math.max(...strategyEquity) : 0;
  const benchmarkMin = benchmarkEquity.length ? Math.min(...benchmarkEquity) : 0;
  const benchmarkMax = benchmarkEquity.length ? Math.max(...benchmarkEquity) : 0;

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
          </div>
          <div className="rounded border border-border-subtle bg-surface-muted p-3">
            <div className="font-label-caps text-text-secondary">Benchmark</div>
            <div className="mt-2 font-data-mono text-text-primary">{benchmark.symbol}</div>
          </div>
          <BacktestForm />
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
          <h3 className="mb-3 font-label-caps text-text-primary">Benchmark Equity Curve</h3>
          {benchmark.equity_curve.length ? (
            <div className="space-y-2">
              {benchmark.equity_curve.map((point) => (
                <div key={point.timestamp} className="flex items-center gap-3 font-data-mono text-xs">
                  <span className="w-32 text-text-secondary">{point.timestamp}</span>
                  <div className="h-2 flex-1 rounded bg-surface-muted">
                    <div
                      className="h-2 rounded bg-info"
                      style={{
                        width: `${curveBarWidth(point.equity, benchmarkMin, benchmarkMax)}%`,
                      }}
                    />
                  </div>
                  <span className="w-16 text-right text-text-primary">
                    {point.equity.toFixed(4)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="No benchmark rows" description="Benchmark API returned no rows." />
          )}
        </section>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <section className="rounded border border-border-subtle bg-bg-surface p-4">
            <h3 className="mb-3 font-label-caps text-text-primary">Strategy Equity Curve</h3>
            {detail?.equity_curve.length ? (
              <div className="space-y-2">
                {detail.equity_curve.slice(0, 14).map((point, index) => {
                  const timestamp = String(point.timestamp ?? `row-${index}`);
                  const equity = Number(point.equity ?? 0);
                  return (
                    <div key={`${timestamp}-${index}`} className="flex items-center gap-3 font-data-mono text-xs">
                      <span className="w-32 truncate text-text-secondary">{timestamp}</span>
                      <div className="h-2 flex-1 rounded bg-surface-muted">
                        <div
                          className="h-2 rounded bg-accent-success"
                          style={{
                            width: `${curveBarWidth(equity, strategyMin, strategyMax)}%`,
                          }}
                        />
                      </div>
                      <span className="w-20 text-right text-text-primary">
                        {equity.toFixed(2)}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyState
                title="Strategy equity curve unavailable"
                description="Run a backtest to create a local equity curve under api_runs/backtests."
              />
            )}
          </section>
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
