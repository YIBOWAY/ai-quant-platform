import { EmptyState } from "@/components/EmptyState";
import { BacktestForm } from "@/components/forms/BacktestForm";
import { formatPercent, getBacktests, getBenchmark } from "@/lib/api";

export default async function Backtest() {
  const [backtests, benchmark] = await Promise.all([
    getBacktests(),
    getBenchmark("SPY", "2024-01-02", "2024-01-12"),
  ]);
  const latest = backtests.backtests[0];

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
          </div>
          <div className="rounded border border-border-subtle bg-surface-muted p-3">
            <div className="font-label-caps text-text-secondary">Benchmark</div>
            <div className="mt-2 font-data-mono text-text-primary">{benchmark.symbol}</div>
          </div>
          <BacktestForm />
        </div>
      </aside>

      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
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
                      style={{ width: `${Math.min(point.equity * 60, 100)}%` }}
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
          <EmptyState
            title="Strategy equity curve unavailable"
            description="Run a backtest to create a local equity curve under api_runs/backtests."
          />
          <EmptyState
            title="Order and fill table unavailable"
            description="No backtest detail has been selected yet."
          />
        </section>
      </div>
    </div>
  );
}
