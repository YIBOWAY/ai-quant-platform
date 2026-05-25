import Link from "next/link";
import { BriefcaseBusiness, Layers, ShieldAlert } from "lucide-react";
import { DataPreviewTable } from "@/components/DataPreviewTable";
import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import {
  formatMoney,
  getBacktestDetail,
  getBacktests,
  getHealth,
  getPaperRunDetail,
  getPaperRuns,
  getSymbols,
  type PreviewRecord,
} from "@/lib/api";

type ExposureRow = {
  symbol: string;
  timestamp: string;
  quantity: number;
  price: number;
  marketValue: number;
  absValue: number;
  weight: number;
  side: "Long" | "Short";
};

export default async function PositionMapPage() {
  const [symbols, backtests, paperRuns, health] = await Promise.all([
    getSymbols(),
    getBacktests(),
    getPaperRuns(),
    getHealth(),
  ]);
  const latestBacktest = backtests.backtests[0];
  const latestPaperRun = paperRuns.paper_runs[0];
  const [backtestDetail, paperDetail] = await Promise.all([
    latestBacktest ? getBacktestDetail(latestBacktest.id) : null,
    latestPaperRun ? getPaperRunDetail(latestPaperRun.id) : null,
  ]);
  const exposureRows = latestExposure(backtestDetail?.positions ?? []);
  const totals = exposureTotals(exposureRows);
  const latestEquity = lastNumber(backtestDetail?.equity_curve ?? [], "equity");

  return (
    <main className="flex h-full flex-1 flex-col gap-4 overflow-y-auto p-container-padding">
      <ErrorBanner
        messages={[
          symbols.apiError,
          backtests.apiError,
          paperRuns.apiError,
          health.apiError,
          backtestDetail?.apiError,
          paperDetail?.apiError,
        ]}
      />

      <header className="border-b border-border-subtle pb-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Layers size={18} className="text-accent-success" />
              <h1 className="font-headline-xl text-text-primary">Position Map</h1>
            </div>
            <p className="mt-2 max-w-3xl font-body-sm text-text-secondary">
              Latest saved positions, exposure weights, and paper-trading safety state from local runs.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {latestBacktest ? (
              <Link
                className="rounded border border-border-subtle px-3 py-2 font-body-sm text-text-primary"
                href={`/backtest/${latestBacktest.id}`}
              >
                Open backtest
              </Link>
            ) : null}
            {latestPaperRun ? (
              <Link
                className="rounded border border-border-subtle px-3 py-2 font-body-sm text-text-primary"
                href={`/paper-trading/${latestPaperRun.id}`}
              >
                Open paper run
              </Link>
            ) : null}
          </div>
        </div>
      </header>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Portfolio Exposure" value={formatMoney(totals.grossExposure)} />
        <Metric label="Net Exposure" value={formatMoney(totals.netExposure)} />
        <Metric label="Open Symbols" value={String(exposureRows.length)} />
        <Metric label="Latest Equity" value={formatMoney(latestEquity)} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded border border-border-subtle bg-bg-surface p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-label-caps text-text-primary">Exposure by Symbol</h2>
              <p className="mt-1 font-body-sm text-text-secondary">
                Gross exposure weight from the newest saved backtest position timestamp.
              </p>
            </div>
            {latestBacktest?.source ? <DataSourceBadge source={latestBacktest.source} /> : null}
          </div>
          {exposureRows.length ? (
            <div className="space-y-3">
              {exposureRows.map((row) => (
                <div className="grid gap-2 md:grid-cols-[120px_1fr_110px]" key={row.symbol}>
                  <div>
                    <div className="font-data-mono text-text-primary">{row.symbol}</div>
                    <div className="font-label-caps text-text-secondary">{row.side}</div>
                  </div>
                  <div className="flex items-center">
                    <div className="h-3 w-full overflow-hidden rounded bg-surface-container">
                      <div
                        className={row.side === "Long" ? "h-full bg-accent-success" : "h-full bg-danger"}
                        style={{ width: `${Math.max(row.weight * 100, 2)}%` }}
                      />
                    </div>
                  </div>
                  <div className="text-right font-data-mono text-text-primary">
                    {(row.weight * 100).toFixed(1)}%
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No saved positions"
              description="Run a backtest to generate position rows for this map."
            />
          )}
        </div>

        <div className="rounded border border-border-subtle bg-bg-surface p-4">
          <div className="mb-4 flex items-center gap-2">
            <ShieldAlert size={18} className="text-warning" />
            <h2 className="font-label-caps text-text-primary">Paper Safety State</h2>
          </div>
          <div className="space-y-3 font-body-sm">
            <StatusRow label="paper_trading" value={String(health.safety?.paper_trading ?? true)} />
            <StatusRow
              label="live_trading_enabled"
              value={String(health.safety?.live_trading_enabled ?? false)}
            />
            <StatusRow label="kill_switch" value={String(health.safety?.kill_switch ?? true)} />
            <StatusRow label="latest paper run" value={latestPaperRun?.id ?? "none"} />
            <StatusRow
              label="risk breaches"
              value={String(latestPaperRun?.summary?.risk_breach_count ?? 0)}
              danger={(latestPaperRun?.summary?.risk_breach_count ?? 0) > 0}
            />
          </div>
          <div className="mt-4 flex items-center gap-2 rounded border border-border-subtle bg-surface-muted p-3 font-body-sm text-text-secondary">
            <BriefcaseBusiness size={16} />
            Read-only map from local simulation artifacts.
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <DataPreviewTable
          columns={["timestamp", "symbol", "quantity", "close_price", "market_value", "weight"]}
          description="Newest position row per symbol from the latest backtest."
          emptyDescription="No backtest position rows were found."
          emptyTitle="Latest Backtest Positions"
          rows={positionTableRows(exposureRows)}
          title="Latest Backtest Positions"
        />
        <DataPreviewTable
          columns={["symbol", "source"]}
          description="Symbols currently available from the local market-data API."
          emptyDescription="No local symbols were returned by the API."
          emptyTitle="Available Symbols"
          rows={symbols.symbols.map((symbol) => ({ symbol, source: symbols.source }))}
          title="Available Symbols"
        />
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-3">
      <div className="font-label-caps text-text-secondary">{label}</div>
      <div className="mt-2 font-data-mono text-lg font-bold text-text-primary">{value}</div>
    </div>
  );
}

function StatusRow({ label, value, danger = false }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border-subtle/50 pb-2">
      <span className="text-text-secondary">{label}</span>
      <span className={`text-right font-data-mono ${danger ? "text-danger" : "text-text-primary"}`}>
        {value}
      </span>
    </div>
  );
}

function latestExposure(rows: PreviewRecord[]): ExposureRow[] {
  const latestTimestamp = rows
    .map((row) => stringValue(row.timestamp))
    .filter(Boolean)
    .sort()
    .at(-1);
  if (!latestTimestamp) {
    return [];
  }
  const latestRows = rows.filter((row) => stringValue(row.timestamp) === latestTimestamp);
  const mapped = latestRows
    .map((row) => {
      const symbol = stringValue(row.symbol);
      const quantity = numberValue(row.quantity);
      const price = numberValue(row.close_price);
      const marketValue = numberValue(row.market_value) ?? (quantity ?? 0) * (price ?? 0);
      if (!symbol || quantity === undefined || price === undefined || !Number.isFinite(marketValue)) {
        return null;
      }
      return {
        symbol,
        timestamp: latestTimestamp,
        quantity,
        price,
        marketValue,
        absValue: Math.abs(marketValue),
        weight: 0,
        side: marketValue >= 0 ? "Long" : "Short",
      } satisfies ExposureRow;
    })
    .filter((row): row is ExposureRow => row !== null && row.absValue > 0);
  const gross = mapped.reduce((sum, row) => sum + row.absValue, 0);
  return mapped
    .map((row) => ({
      ...row,
      weight: gross > 0 ? row.absValue / gross : 0,
    }))
    .sort((left, right) => right.absValue - left.absValue || left.symbol.localeCompare(right.symbol));
}

function exposureTotals(rows: ExposureRow[]) {
  return {
    grossExposure: rows.reduce((sum, row) => sum + row.absValue, 0),
    netExposure: rows.reduce((sum, row) => sum + row.marketValue, 0),
  };
}

function positionTableRows(rows: ExposureRow[]) {
  return rows.map((row) => ({
    timestamp: row.timestamp,
    symbol: row.symbol,
    quantity: row.quantity,
    close_price: row.price,
    market_value: row.marketValue,
    weight: `${(row.weight * 100).toFixed(2)}%`,
  }));
}

function lastNumber(rows: PreviewRecord[], key: string) {
  for (const row of [...rows].reverse()) {
    const parsed = numberValue(row[key]);
    if (parsed !== undefined) {
      return parsed;
    }
  }
  return undefined;
}

function numberValue(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : "";
}
