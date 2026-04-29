import { DataSourceBadge } from "@/components/DataSourceBadge";
import { EmptyState } from "@/components/EmptyState";
import { getOhlcv, getSymbols } from "@/lib/api";

function closeBarHeight(close: number, min: number, max: number) {
  if (max <= min) {
    return 50;
  }
  return 10 + ((close - min) / (max - min)) * 80;
}

export default async function DataExplorer() {
  const [symbols, ohlcv] = await Promise.all([
    getSymbols(),
    getOhlcv("SPY", "2024-01-02", "2024-01-12"),
  ]);
  const latest = ohlcv.rows.at(-1);
  const closes = ohlcv.rows.map((row) => row.close);
  const minClose = closes.length ? Math.min(...closes) : 0;
  const maxClose = closes.length ? Math.max(...closes) : 0;

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex-none border-b border-border-subtle bg-bg-surface p-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex flex-col gap-1">
              <label className="font-label-caps uppercase text-text-secondary">Universe</label>
              <select className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info">
                {symbols.symbols.map((symbol) => (
                  <option key={symbol}>{symbol}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="font-label-caps uppercase text-text-secondary">Asset</label>
              <input
                className="h-8 w-24 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info"
                type="text"
                defaultValue={ohlcv.symbol}
                readOnly
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="font-label-caps uppercase text-text-secondary">Date Range</label>
              <div className="flex items-center gap-2">
                <input
                  className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info"
                  type="date"
                  defaultValue="2024-01-02"
                  readOnly
                />
                <span className="text-text-secondary">-</span>
                <input
                  className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info"
                  type="date"
                  defaultValue="2024-01-12"
                  readOnly
                />
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <DataSourceBadge source={ohlcv.source} />
            <span className="font-data-mono text-[10px] uppercase text-text-secondary">
              rows: {ohlcv.rows.length}
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
