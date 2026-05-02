import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { DataExplorerControls } from "@/components/forms/DataExplorerControls";
import { getMarketDataHistory, getSymbols } from "@/lib/api";

function closeBarHeight(close: number, min: number, max: number) {
  if (max <= min) {
    return 50;
  }
  return 10 + ((close - min) / (max - min)) * 80;
}

type DataExplorerProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function single(value: string | string[] | undefined, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

export default async function DataExplorer({ searchParams }: DataExplorerProps) {
  const params = (await searchParams) ?? {};
  const symbol = single(params.symbol, "SPY").toUpperCase();
  const start = single(params.start, "2024-01-02");
  const end = single(params.end, "2024-01-12");
  const freq = single(params.freq, "1d");
  const provider = single(params.provider, "futu");
  const [symbols, ohlcv] = await Promise.all([
    getSymbols(),
    getMarketDataHistory(symbol, start, end, freq, provider),
  ]);
  const latest = ohlcv.rows.at(-1);
  const closes = ohlcv.rows.map((row) => row.close);
  const minClose = closes.length ? Math.min(...closes) : 0;
  const maxClose = closes.length ? Math.max(...closes) : 0;

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex-none border-b border-border-subtle bg-bg-surface p-4">
        <ErrorBanner messages={[symbols.apiError, ohlcv.apiError]} />
        <div className="flex flex-wrap items-end justify-between gap-4">
          <DataExplorerControls
            symbols={symbols.symbols}
            initial={{
              symbol: ohlcv.symbol,
              start,
              end,
              freq:
                freq === "1h" || freq === "30m" || freq === "15m" || freq === "5m" || freq === "1m"
                  ? freq
                  : "1d",
              provider: provider === "sample" || provider === "tiingo" ? provider : "futu",
            }}
          />

          <div className="flex items-center gap-3">
            <DataSourceBadge source={ohlcv.source} />
            <span className="font-data-mono text-[10px] uppercase text-text-secondary">
              rows: {ohlcv.rows.length}
            </span>
            <span className="font-data-mono text-[10px] uppercase text-text-secondary">
              freq: {ohlcv.frequency}
            </span>
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-1 flex-col border-r border-border-subtle">
          <div className="flex-1 bg-surface p-4">
            <div className="mb-4 flex items-start justify-between">
              <div>
                <div className="flex items-baseline gap-2 font-headline-lg text-text-primary">
                  {ohlcv.symbol} <span className="font-data-mono text-data-mono text-text-secondary">USD</span>
                </div>
                <div className="mt-1 flex gap-4 font-data-mono text-data-mono">
                  <span className="text-accent-success">O: {latest?.open.toFixed(2) ?? "--"}</span>
                  <span className="text-accent-success">H: {latest?.high.toFixed(2) ?? "--"}</span>
                  <span className="text-danger">L: {latest?.low.toFixed(2) ?? "--"}</span>
                  <span className="text-text-primary">C: {latest?.close.toFixed(2) ?? "--"}</span>
                </div>
              </div>
            </div>

            {ohlcv.rows.length ? (
              <div className="flex h-[360px] items-end gap-1 rounded border border-border-subtle bg-surface-muted p-4">
                {ohlcv.rows.map((row) => {
                  const up = row.close >= row.open;
                  return (
                    <div
                      key={row.timestamp}
                      className="flex min-w-3 flex-1 flex-col items-center justify-end gap-1"
                      title={`${row.timestamp} close=${row.close}`}
                    >
                      <div
                        className={up ? "w-full bg-accent-success" : "w-full bg-danger"}
                        style={{ height: `${closeBarHeight(row.close, minClose, maxClose)}%` }}
                      />
                      <span className="max-w-16 truncate font-data-mono text-[9px] text-text-secondary">
                        {row.timestamp.slice(5, 10)}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyState
                title="No OHLCV rows"
                description="The backend returned no rows for the selected symbol and range."
              />
            )}
          </div>

          <div className="h-1/3 border-t border-border-subtle bg-bg-surface">
            <div className="flex items-center justify-between border-b border-border-subtle bg-surface-container-low px-4 py-2">
              <span className="font-label-caps uppercase text-text-secondary">Raw Data Feed</span>
              <DataSourceBadge source={ohlcv.source} />
            </div>
            <div className="h-[calc(100%-41px)] overflow-auto p-4">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-border-subtle">
                    <th className="pb-2 font-label-caps text-text-secondary">TIMESTAMP (UTC)</th>
                    <th className="pb-2 text-right font-label-caps text-text-secondary">OPEN</th>
                    <th className="pb-2 text-right font-label-caps text-text-secondary">HIGH</th>
                    <th className="pb-2 text-right font-label-caps text-text-secondary">LOW</th>
                    <th className="pb-2 text-right font-label-caps text-text-secondary">CLOSE</th>
                    <th className="pb-2 text-right font-label-caps text-text-secondary">VOLUME</th>
                  </tr>
                </thead>
                <tbody className="font-data-mono text-data-mono text-text-primary">
                  {ohlcv.rows.map((row) => (
                    <tr
                      className="border-b border-border-subtle/50 hover:bg-surface-muted"
                      key={row.timestamp}
                    >
                      <td className="py-2">{row.timestamp}</td>
                      <td className="py-2 text-right">{row.open.toFixed(2)}</td>
                      <td className="py-2 text-right">{row.high.toFixed(2)}</td>
                      <td className="py-2 text-right">{row.low.toFixed(2)}</td>
                      <td className="py-2 text-right text-accent-success">{row.close.toFixed(2)}</td>
                      <td className="py-2 text-right text-text-secondary">
                        {row.volume.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="flex w-[300px] flex-col gap-4 overflow-y-auto bg-bg-surface p-4">
          <h3 className="font-label-caps uppercase text-text-secondary">Data Quality Metrics</h3>
          <div className="rounded border border-border-subtle bg-surface-muted p-3">
            <div className="font-label-caps text-text-secondary">Fetched At</div>
            <div className="mt-2 break-all font-data-mono text-[11px] text-text-primary">
              {ohlcv.metadata.fetched_at ?? "--"}
            </div>
          </div>
          <EmptyState
            title="Quality report not connected"
            description="Coverage, missing-day and anomaly checks are waiting for /api/data/quality."
          />
          <EmptyState
            title="Detailed audit log unavailable"
            description="Data audit timelines are scheduled in FIX_PLAN P2-5."
          />
        </div>
      </div>
    </div>
  );
}
