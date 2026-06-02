import Link from "next/link";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { SyntheticMetricsWarning } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { EquityComparisonChart } from "@/components/EquityComparisonChart";
import { ErrorBanner } from "@/components/ErrorBanner";
import { formatPercent, getBacktestDetail } from "@/lib/api";

type BacktestRunDetailPageProps = {
  params?: Promise<{ runId?: string }>;
};

export default async function BacktestRunDetailPage({ params }: BacktestRunDetailPageProps) {
  const runId = (await params)?.runId ?? "";
  const detail = await getBacktestDetail(runId);
  const metadata = detail.metadata ?? {};
  const source = typeof metadata.source === "string" ? metadata.source : undefined;
  const metrics = asRecord(
    detail.metrics && Object.keys(detail.metrics).length ? detail.metrics : metadata.metrics,
  );
  const chartRows = normalizeEquity(detail.equity_curve);
  const warnings = arrayOfStrings(metadata.warnings);

  return (
    <main className="h-full overflow-y-auto bg-bg-base p-5">
      <ErrorBanner messages={[detail.apiError]} />
      <div className="mb-4">
        <SyntheticMetricsWarning source={source} />
      </div>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4 border-b border-border-subtle pb-4">
        <div>
          <p className="font-label-caps uppercase text-text-secondary">Backtest</p>
          <h1 className="mt-1 font-headline-xl text-text-primary">Backtest Run Detail</h1>
          <p className="mt-1 font-data-mono text-text-secondary">{runId}</p>
          {source ? (
            <div className="mt-3">
              <DataSourceBadge source={source} />
            </div>
          ) : null}
        </div>
        <Link className="rounded border border-border-subtle px-3 py-2 font-body-sm text-text-primary" href="/backtest">
          Back to Backtest
        </Link>
      </header>

      <section className="mb-4 grid gap-3 md:grid-cols-3">
        <Metric label="Total Return" value={formatPercent(toNumber(metrics?.total_return))} />
        <Metric label="Sharpe" value={num(toNumber(metrics?.sharpe), 2)} />
        <Metric label="Max Drawdown" value={formatPercent(toNumber(metrics?.max_drawdown))} danger />
      </section>
      <WarningsPanel warnings={warnings} />

      <section className="mb-4 rounded border border-border-subtle bg-bg-surface p-4">
        <h2 className="font-label-caps text-text-primary">Equity Curve</h2>
        <p className="mt-1 font-body-sm text-text-secondary">Saved equity curve for this run.</p>
        <div className="mt-3">
          {chartRows.length ? (
            <EquityComparisonChart rows={chartRows} />
          ) : (
            <EmptyState
              title="No equity curve rows"
              description="This run has metadata, but no saved equity curve table was found."
            />
          )}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <DataPreviewTable
          description="Metrics JSON saved with this run."
          emptyDescription="No metrics were found for this run."
          emptyTitle="Metrics unavailable"
          rows={metricsRows(metrics)}
          title="Metrics"
        />
        <DataPreviewTable
          description="Run request and saved output paths."
          emptyDescription="Metadata is empty for this run."
          emptyTitle="Metadata unavailable"
          rows={objectRows(metadata)}
          title="Metadata"
        />
        <DataPreviewTable
          description="Simulated trades from this backtest run."
          emptyDescription="No trade blotter rows were saved for this run."
          emptyTitle="Trade Blotter"
          rows={detail.trade_blotter}
          title="Trade Blotter"
        />
        <DataPreviewTable
          description="Orders submitted by this backtest run."
          emptyDescription="No order rows were saved for this run."
          emptyTitle="Orders"
          rows={detail.orders}
          title="Orders"
        />
        <div className="lg:col-span-2">
          <DataPreviewTable
            description="Position rows saved by this backtest run."
            emptyDescription="No position rows were saved for this run."
            emptyTitle="Positions"
            rows={detail.positions}
            title="Positions"
          />
        </div>
        <div className="lg:col-span-2">
          <DataPreviewTable
            description="Per-name contribution to this run's P&L (mark-to-market on held quantity)."
            emptyDescription="No attribution rows were saved for this run."
            emptyTitle="Return Attribution"
            rows={detail.attribution}
            title="Return Attribution"
          />
        </div>
      </section>
    </main>
  );
}

function WarningsPanel({ warnings }: { warnings: string[] }) {
  if (!warnings.length) {
    return null;
  }
  return (
    <section className="mb-4 rounded border border-warning/40 bg-warning/10 p-4 text-warning">
      <h2 className="font-label-caps">Run notes</h2>
      <ul className="mt-2 space-y-1 font-body-sm">
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </section>
  );
}

function Metric({ label, value, danger = false }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-3">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className={`mt-2 font-data-mono text-lg font-bold ${danger ? "text-danger" : "text-text-primary"}`}>
        {value}
      </div>
    </div>
  );
}

function arrayOfStrings(value: unknown) {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function normalizeEquity(rows: Array<Record<string, unknown>>) {
  const parsed = rows
    .map((row, index) => ({
      timestamp: String(row.timestamp ?? `row-${index + 1}`).slice(0, 10),
      value: toNumber(row.equity),
    }))
    .filter((row): row is { timestamp: string; value: number } => row.value !== undefined);
  const first = parsed.find((row) => row.value > 0)?.value;
  if (!first) {
    return [];
  }
  return parsed.map((row) => ({ timestamp: row.timestamp, strategy: row.value / first }));
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
