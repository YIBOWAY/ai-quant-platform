import { Search, Download, ZoomIn, ZoomOut } from "lucide-react";
import { getOhlcv, getSymbols } from "@/lib/api";

export default async function DataExplorer() {
  const [symbols, ohlcv] = await Promise.all([
    getSymbols(),
    getOhlcv("SPY", "2024-01-02", "2024-01-12"),
  ]);
  const latest = ohlcv.rows.at(-1);

  return (
    <div className="flex flex-col h-full overflow-hidden w-full">
      {/* Filter Bar */}
      <div className="flex-none p-4 border-b border-border-subtle bg-bg-surface flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex flex-col gap-1">
            <label className="font-label-caps text-text-secondary uppercase">Universe</label>
            <select className="bg-surface-muted border border-border-subtle rounded text-text-primary font-data-mono text-data-mono h-8 px-2 focus:border-info focus:ring-0">
              {symbols.symbols.map((symbol) => (
                <option key={symbol}>{symbol}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="font-label-caps text-text-secondary uppercase">Asset</label>
            <input className="bg-surface-muted border border-border-subtle rounded text-text-primary font-data-mono text-data-mono h-8 w-24 px-2 focus:border-info focus:ring-0" type="text" defaultValue={ohlcv.symbol} />
          </div>
          <div className="w-px h-8 bg-border-subtle mx-2"></div>
          <div className="flex flex-col gap-1">
            <label className="font-label-caps text-text-secondary uppercase">Date Range</label>
            <div className="flex items-center gap-2">
              <input className="bg-surface-muted border border-border-subtle rounded text-text-primary font-data-mono text-data-mono h-8 px-2 focus:border-info focus:ring-0" type="date" defaultValue="2024-01-02" />
              <span className="text-text-secondary">-</span>
              <input className="bg-surface-muted border border-border-subtle rounded text-text-primary font-data-mono text-data-mono h-8 px-2 focus:border-info focus:ring-0" type="date" defaultValue="2024-01-12" />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="font-label-caps text-text-secondary uppercase">Resolution</label>
            <select className="bg-surface-muted border border-border-subtle rounded text-text-primary font-data-mono text-data-mono h-8 px-2 focus:border-info focus:ring-0">
              <option>1D</option>
              <option>1H</option>
              <option>15M</option>
            </select>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="font-label-caps text-warning border border-warning/30 bg-warning/10 px-2 py-1 rounded">
            API source: {ohlcv.source} / rows: {ohlcv.rows.length}
          </span>
          <button className="h-8 px-3 border border-border-subtle rounded text-text-secondary hover:text-text-primary hover:border-text-primary transition-colors flex items-center gap-2 font-body-sm">
            <Download size={16} /> Export
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Chart Area */}
        <div className="flex-1 flex flex-col border-r border-border-subtle">
          <div className="flex-1 bg-surface relative p-4 flex flex-col">
            <div className="flex justify-between items-start mb-2">
              <div>
                <div className="font-headline-lg text-text-primary flex items-baseline gap-2">
                  {ohlcv.symbol} <span className="font-data-mono text-data-mono text-text-secondary">USD</span>
                </div>
                <div className="font-data-mono text-data-mono flex gap-4 mt-1">
                  <span className="text-accent-success">O: {latest?.open.toFixed(2) ?? "--"}</span>
                  <span className="text-accent-success">H: {latest?.high.toFixed(2) ?? "--"}</span>
                  <span className="text-danger">L: {latest?.low.toFixed(2) ?? "--"}</span>
                  <span className="text-text-primary">C: {latest?.close.toFixed(2) ?? "--"}</span>
                </div>
              </div>
              <div className="flex gap-2">
                <button className="w-6 h-6 flex items-center justify-center rounded bg-surface-muted border border-border-subtle text-text-secondary hover:text-text-primary">
                  <ZoomIn size={14} />
                </button>
                <button className="w-6 h-6 flex items-center justify-center rounded bg-surface-muted border border-border-subtle text-text-secondary hover:text-text-primary">
                  <ZoomOut size={14} />
                </button>
              </div>
            </div>

            {/* Decorative Chart Area */}
            <div className="flex-1 border border-border-subtle bg-surface-muted rounded relative overflow-hidden flex items-end">
              <div className="absolute inset-0 grid grid-cols-6 grid-rows-4 opacity-10">
                <div className="border-b border-r border-text-primary"></div>
                <div className="border-b border-r border-text-primary"></div>
                <div className="border-b border-r border-text-primary"></div>
                <div className="border-b border-r border-text-primary"></div>
                <div className="border-b border-r border-text-primary"></div>
                <div className="border-b border-text-primary"></div>
              </div>

              <div className="absolute bottom-16 left-0 right-12 top-4 flex items-end justify-between px-4">
                <div className="w-2 bg-accent-success h-32 relative"><div className="absolute w-px h-40 bg-accent-success left-1/2 -translate-x-1/2 bottom-[-10px]"></div></div>
                <div className="w-2 bg-danger h-24 relative mb-8"><div className="absolute w-px h-32 bg-danger left-1/2 -translate-x-1/2 bottom-[-5px]"></div></div>
                <div className="w-2 bg-accent-success h-40 relative"><div className="absolute w-px h-48 bg-accent-success left-1/2 -translate-x-1/2 bottom-[-15px]"></div></div>
                <div className="w-2 bg-danger h-16 relative mb-12"><div className="absolute w-px h-24 bg-danger left-1/2 -translate-x-1/2 bottom-0"></div></div>
                <div className="w-2 bg-accent-success h-48 relative"><div className="absolute w-px h-56 bg-accent-success left-1/2 -translate-x-1/2 bottom-[-20px]"></div></div>
              </div>

              <div className="w-full h-16 border-t border-border-subtle flex items-end justify-between px-4 pb-0 opacity-50">
                <div className="w-3 bg-accent-success h-8"></div>
                <div className="w-3 bg-danger h-12"></div>
                <div className="w-3 bg-accent-success h-6"></div>
                <div className="w-3 bg-danger h-16"></div>
                <div className="w-3 bg-accent-success h-10"></div>
              </div>

              <div className="absolute right-0 top-0 bottom-16 w-12 border-l border-border-subtle bg-bg-surface flex flex-col justify-between py-4 items-end pr-2 font-data-mono text-[10px] text-text-secondary">
                <span>195.0</span>
                <span>190.0</span>
                <span>185.0</span>
              </div>
            </div>
          </div>

          {/* Bottom OHLCV Table */}
          <div className="h-1/3 border-t border-border-subtle bg-bg-surface flex flex-col">
            <div className="px-4 py-2 border-b border-border-subtle bg-surface-container-low flex items-center justify-between">
              <span className="font-label-caps text-text-secondary uppercase">Raw Data Feed</span>
              <div className="flex gap-2 items-center">
                <span className="w-2 h-2 rounded-full bg-accent-success animate-pulse"></span>
                <span className="font-data-mono text-[10px] text-text-secondary">Live Sync</span>
              </div>
            </div>
            <div className="flex-1 overflow-auto p-4">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-border-subtle">
                    <th className="pb-2 font-label-caps text-text-secondary">TIMESTAMP (UTC)</th>
                    <th className="pb-2 font-label-caps text-text-secondary text-right">OPEN</th>
                    <th className="pb-2 font-label-caps text-text-secondary text-right">HIGH</th>
                    <th className="pb-2 font-label-caps text-text-secondary text-right">LOW</th>
                    <th className="pb-2 font-label-caps text-text-secondary text-right">CLOSE</th>
                    <th className="pb-2 font-label-caps text-text-secondary text-right">VOLUME</th>
                  </tr>
                </thead>
                <tbody className="font-data-mono text-data-mono text-text-primary">
                  {ohlcv.rows.slice(-6).map((row) => (
                    <tr className="border-b border-border-subtle/50 hover:bg-surface-muted" key={row.timestamp}>
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

        {/* Right Sidebar: Data Quality */}
        <div className="w-[300px] bg-bg-surface flex flex-col p-4 gap-6 overflow-y-auto">
          <div>
            <h3 className="font-label-caps text-text-secondary uppercase mb-4">Data Quality Metrics</h3>
            <div className="space-y-4">
              <div className="bg-surface-container-low border border-border-subtle p-3 rounded">
                <div className="flex justify-between items-center mb-1">
                  <span className="font-body-sm text-text-primary">Coverage</span>
                  <span className="font-data-mono text-accent-success">99.98%</span>
                </div>
                <div className="w-full bg-surface-muted h-1.5 rounded-full overflow-hidden">
                  <div className="bg-accent-success h-full w-[99.98%]"></div>
                </div>
              </div>

              <div className="bg-surface-container-low border border-border-subtle p-3 rounded">
                <div className="flex justify-between items-center mb-2">
                  <span className="font-body-sm text-text-primary">Missing Days</span>
                  <span className="font-data-mono text-warning">2</span>
                </div>
                <div className="font-data-mono text-[10px] text-text-secondary">
                  • 2023-01-16 (MLK Day)<br/>
                  • 2023-02-20 (Presidents&apos; Day)
                </div>
              </div>

              <div className="bg-surface-container-low border border-border-subtle p-3 rounded">
                <div className="flex justify-between items-center mb-1">
                  <span className="font-body-sm text-text-primary">Spike Detection</span>
                  <span className="font-data-mono text-text-primary">0 Anomalies</span>
                </div>
                <div className="font-body-sm text-text-secondary text-xs mt-1">
                  Z-Score threshold &gt; 3.0
                </div>
              </div>
            </div>
          </div>
          <div className="mt-auto">
            <button className="w-full py-2 border border-border-subtle rounded text-text-primary font-body-sm hover:bg-surface-muted transition-colors">
              View Detailed Audit Log
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
