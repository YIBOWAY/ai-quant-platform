import { formatPercent, getBacktests, getBenchmark } from "@/lib/api";

export default async function Backtest() {
  const [backtests, benchmark] = await Promise.all([
    getBacktests(),
    getBenchmark("SPY", "2024-01-02", "2024-01-12"),
  ]);
  const latest = backtests.backtests[0];

  return (
    <div className="flex-1 flex h-full overflow-hidden bg-base relative">
      {/* Left Config Panel */}
      <aside className="w-[320px] bg-bg-surface border-r border-border-subtle flex flex-col h-full overflow-y-auto">
        <div className="p-4 border-b border-border-subtle">
          <h2 className="font-headline-lg text-text-primary mb-1">Backtest Config</h2>
          <p className="font-body-sm text-text-secondary">
            {latest?.id ?? "No API backtest yet"} vs {benchmark.symbol}
          </p>
        </div>

        <div className="p-4 flex flex-col gap-6">
          {/* Date Range */}
          <div className="flex flex-col gap-2">
            <label className="font-label-caps text-text-secondary">Timeframe</label>
            <div className="grid grid-cols-2 gap-2">
              <input className="bg-surface-muted border border-border-subtle text-text-primary rounded px-2 py-1.5 font-data-mono focus:border-info focus:ring-1 focus:ring-info text-xs" type="date" defaultValue="2020-01-01" />
              <input className="bg-surface-muted border border-border-subtle text-text-primary rounded px-2 py-1.5 font-data-mono focus:border-info focus:ring-1 focus:ring-info text-xs" type="date" defaultValue="2023-12-31" />
            </div>
          </div>

          {/* Initial Capital */}
          <div className="flex flex-col gap-2">
            <label className="font-label-caps text-text-secondary">Initial Capital (USD)</label>
            <input className="bg-surface-muted border border-border-subtle text-text-primary rounded px-3 py-1.5 font-data-mono focus:border-info focus:ring-1 focus:ring-info text-right" type="text" defaultValue="1,000,000" />
          </div>

          {/* Universe */}
          <div className="flex flex-col gap-2">
            <label className="font-label-caps text-text-secondary">Universe Selection</label>
            <select className="bg-surface-muted border border-border-subtle text-text-primary rounded px-3 py-1.5 font-body-sm focus:border-info focus:ring-1 focus:ring-info">
              <option>S&amp;P 500 (Liquid)</option>
              <option>Russell 2000</option>
              <option>Custom List: Tech Heavy</option>
            </select>
          </div>

          {/* Friction Models */}
          <div className="flex flex-col gap-3 pt-2 border-t border-border-subtle">
            <label className="font-label-caps text-text-secondary">Friction Models</label>
            <div className="flex items-center justify-between">
              <span className="font-body-sm text-text-primary">Commission</span>
              <div className="flex items-center gap-1">
                <input className="w-16 bg-surface-muted border border-border-subtle text-text-primary rounded px-2 py-1 font-data-mono text-xs text-right" type="text" defaultValue="0.005" />
                <span className="font-data-mono text-text-secondary text-xs">bps</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-body-sm text-text-primary">Slippage</span>
              <div className="flex items-center gap-1">
                <input className="w-16 bg-surface-muted border border-border-subtle text-text-primary rounded px-2 py-1 font-data-mono text-xs text-right" type="text" defaultValue="0.01" />
                <span className="font-data-mono text-text-secondary text-xs">%</span>
              </div>
            </div>
          </div>

          {/* Toggles */}
          <div className="flex flex-col gap-3 pt-2 border-t border-border-subtle">
            <label className="font-label-caps text-text-secondary">Execution Settings</label>
            <label className="flex items-center justify-between cursor-pointer">
              <span className="font-body-sm text-text-primary">Reinvest Dividends</span>
              <div className="relative">
                <input checked readOnly className="sr-only" type="checkbox" />
                <div className="block bg-accent-success w-8 h-4 rounded-full"></div>
                <div className="absolute right-[2px] top-[2px] bg-bg-surface w-3 h-3 rounded-full transition"></div>
              </div>
            </label>
            <label className="flex items-center justify-between cursor-pointer">
              <span className="font-body-sm text-text-primary">Margin enabled</span>
              <div className="relative">
                <input className="sr-only" type="checkbox" />
                <div className="block bg-surface-muted border border-border-subtle w-8 h-4 rounded-full"></div>
                <div className="absolute left-[2px] top-[2px] bg-text-secondary w-3 h-3 rounded-full transition"></div>
              </div>
            </label>
          </div>

          <button className="mt-4 w-full py-2 bg-accent-success text-on-primary font-body-sm font-semibold rounded hover:bg-primary-fixed transition-colors">
            Run Backtest
          </button>
        </div>
      </aside>

      {/* Main Canvas */}
      <div className="flex-1 flex flex-col p-4 gap-4 overflow-y-auto">
        {/* KPI Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="bg-bg-surface border border-border-subtle rounded p-3 flex flex-col gap-1">
            <span className="font-label-caps text-text-secondary">Total Return</span>
            <div className="flex items-baseline gap-2">
              <span className="font-data-mono text-accent-success text-lg font-bold">
                {formatPercent(latest?.metrics?.total_return)}
              </span>
            </div>
            <span className="font-data-mono text-text-secondary text-[10px]">
              BMK: {formatPercent(benchmark.metrics.total_return)}
            </span>
          </div>

          <div className="bg-bg-surface border border-border-subtle rounded p-3 flex flex-col gap-1">
            <span className="font-label-caps text-text-secondary">Sharpe Ratio</span>
            <div className="flex items-baseline gap-2">
              <span className="font-data-mono text-text-primary text-lg font-bold">
                {latest?.metrics?.sharpe?.toFixed(2) ?? "--"}
              </span>
            </div>
            <span className="font-data-mono text-text-secondary text-[10px]">
              BMK: {benchmark.metrics.sharpe.toFixed(2)}
            </span>
          </div>

          <div className="bg-bg-surface border border-border-subtle rounded p-3 flex flex-col gap-1">
            <span className="font-label-caps text-text-secondary">Max Drawdown</span>
            <div className="flex items-baseline gap-2">
              <span className="font-data-mono text-danger text-lg font-bold">
                {formatPercent(latest?.metrics?.max_drawdown)}
              </span>
            </div>
            <span className="font-data-mono text-text-secondary text-[10px]">
              BMK: {formatPercent(benchmark.metrics.max_drawdown)}
            </span>
          </div>

          <div className="bg-bg-surface border border-border-subtle rounded p-3 flex flex-col gap-1">
            <span className="font-label-caps text-text-secondary">Win Rate</span>
            <div className="flex items-baseline gap-2">
              <span className="font-data-mono text-text-primary text-lg font-bold">54.2%</span>
            </div>
            <span className="font-data-mono text-text-secondary text-[10px]">Trades: 1,240</span>
          </div>

          <div className="bg-bg-surface border border-border-subtle rounded p-3 flex flex-col gap-1">
            <span className="font-label-caps text-text-secondary">Alpha (Ann.)</span>
            <div className="flex items-baseline gap-2">
              <span className="font-data-mono text-accent-success text-lg font-bold">8.4%</span>
            </div>
            <span className="font-data-mono text-text-secondary text-[10px]">Beta: 0.85</span>
          </div>

          <div className="bg-bg-surface border border-border-subtle rounded p-3 flex flex-col gap-1">
            <span className="font-label-caps text-text-secondary">Turnover (Ann.)</span>
            <div className="flex items-baseline gap-2">
              <span className="font-data-mono text-text-primary text-lg font-bold">120%</span>
            </div>
            <span className="font-data-mono text-text-secondary text-[10px]">Avg Hold: 4.2d</span>
          </div>
        </div>

        {/* Main Chart Area */}
        <div className="bg-bg-surface border border-border-subtle rounded flex flex-col min-h-[400px]">
          <div className="p-3 border-b border-border-subtle flex justify-between items-center">
            <h3 className="font-label-caps text-text-primary">Cumulative Equity Curve</h3>
            <div className="flex gap-4">
              <div className="flex items-center gap-2">
                <div className="w-3 h-1 bg-accent-success"></div>
                <span className="font-data-mono text-text-secondary text-[10px]">Strategy</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-1 bg-surface-muted border-t border-border-subtle"></div>
                <span className="font-data-mono text-text-secondary text-[10px]">Benchmark</span>
              </div>
            </div>
          </div>

          {/* Fake Chart Canvas */}
          <div className="flex-1 relative p-4 bg-surface-container-lowest">
            <div className="absolute left-4 top-4 bottom-8 w-12 flex flex-col justify-between text-[10px] font-data-mono text-text-secondary border-r border-border-subtle pr-2 text-right">
              <span>1.5</span>
              <span>1.4</span>
              <span>1.3</span>
              <span>1.2</span>
              <span>1.1</span>
              <span>1.0</span>
            </div>
            <div className="absolute left-16 right-4 bottom-2 h-6 flex justify-between text-[10px] font-data-mono text-text-secondary border-t border-border-subtle pt-2">
              <span>2020</span>
              <span>2021</span>
              <span>2022</span>
              <span>2023</span>
            </div>
            <svg className="absolute left-16 right-4 top-4 bottom-8 w-[calc(100%-80px)] h-[calc(100%-48px)]" preserveAspectRatio="none" viewBox="0 0 1000 100">
              <line stroke="#1F2937" strokeDasharray="4" strokeWidth="1" x1="0" x2="1000" y1="20" y2="20"></line>
              <line stroke="#1F2937" strokeDasharray="4" strokeWidth="1" x1="0" x2="1000" y1="40" y2="40"></line>
              <line stroke="#1F2937" strokeDasharray="4" strokeWidth="1" x1="0" x2="1000" y1="60" y2="60"></line>
              <line stroke="#1F2937" strokeDasharray="4" strokeWidth="1" x1="0" x2="1000" y1="80" y2="80"></line>

              <polyline fill="none" points="0,100 100,95 200,85 300,90 400,70 500,80 600,60 700,40 800,50 900,30 1000,20" stroke="#4B5563" strokeWidth="1.5"></polyline>
              <polyline fill="none" points="0,100 100,90 200,75 300,80 400,50 500,55 600,30 700,25 800,15 900,10 1000,5" stroke="#00C896" strokeWidth="2.5"></polyline>
            </svg>
          </div>
        </div>

        {/* Bottom Split Area */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 h-[300px]">
          {/* Weight Heatmap */}
          <div className="bg-bg-surface border border-border-subtle rounded flex flex-col">
            <div className="p-3 border-b border-border-subtle">
              <h3 className="font-label-caps text-text-primary">Sector Exposure Heatmap</h3>
            </div>
            <div className="flex-1 p-3 grid grid-cols-4 grid-rows-3 gap-1 bg-surface-container-lowest">
              <div className="bg-accent-success/80 flex items-center justify-center p-1 font-data-mono text-[10px] text-on-primary"><span className="truncate">TECH (24%)</span></div>
              <div className="bg-accent-success/60 flex items-center justify-center p-1 font-data-mono text-[10px] text-on-primary"><span className="truncate">FIN (18%)</span></div>
              <div className="bg-danger/40 flex items-center justify-center p-1 font-data-mono text-[10px] text-text-primary"><span className="truncate">HLTH (-12%)</span></div>
              <div className="bg-accent-success/20 flex items-center justify-center p-1 font-data-mono text-[10px] text-text-primary"><span className="truncate">CONS (5%)</span></div>
              <div className="bg-danger/80 flex items-center justify-center p-1 font-data-mono text-[10px] text-on-primary"><span className="truncate">ENGY (-20%)</span></div>
              <div className="bg-surface-muted flex items-center justify-center p-1 font-data-mono text-[10px] text-text-secondary"><span className="truncate">UTIL (0%)</span></div>
              <div className="bg-accent-success/40 flex items-center justify-center p-1 font-data-mono text-[10px] text-on-primary"><span className="truncate">INDU (10%)</span></div>
              <div className="bg-danger/60 flex items-center justify-center p-1 font-data-mono text-[10px] text-on-primary"><span className="truncate">MATR (-15%)</span></div>
              <div className="bg-accent-success/30 flex items-center justify-center p-1 font-data-mono text-[10px] text-text-primary"><span className="truncate">COMM (8%)</span></div>
              <div className="bg-danger/20 flex items-center justify-center p-1 font-data-mono text-[10px] text-text-primary"><span className="truncate">REAL (-4%)</span></div>
              <div className="bg-surface-muted flex items-center justify-center p-1 border border-border-subtle font-data-mono text-[10px] text-text-secondary"><span className="truncate">CASH (14%)</span></div>
              <div className="bg-surface-muted flex items-center justify-center p-1 font-data-mono text-[10px] text-text-secondary"><span className="truncate">--</span></div>
            </div>
          </div>

          {/* Order/Fill Table */}
          <div className="bg-bg-surface border border-border-subtle rounded flex flex-col overflow-hidden">
            <div className="p-3 border-b border-border-subtle">
              <h3 className="font-label-caps text-text-primary">Recent Fills</h3>
            </div>
            <div className="flex-1 overflow-auto bg-surface-container-lowest">
              <table className="w-full text-left border-collapse">
                <thead className="bg-surface-muted font-label-caps text-[10px] text-text-secondary sticky top-0">
                  <tr>
                    <th className="py-2 px-3 font-normal whitespace-nowrap">Date/Time</th>
                    <th className="py-2 px-3 font-normal">Symbol</th>
                    <th className="py-2 px-3 font-normal">Side</th>
                    <th className="py-2 px-3 font-normal text-right">Qty</th>
                    <th className="py-2 px-3 font-normal text-right">Price</th>
                  </tr>
                </thead>
                <tbody className="font-data-mono text-[11px] text-text-primary divide-y divide-border-subtle">
                  <tr className="hover:bg-surface">
                    <td className="py-1.5 px-3 text-text-secondary whitespace-nowrap">23-12-31 15:59</td>
                    <td className="py-1.5 px-3">AAPL</td>
                    <td className="py-1.5 px-3 text-accent-success">BUY</td>
                    <td className="py-1.5 px-3 text-right">450</td>
                    <td className="py-1.5 px-3 text-right">192.45</td>
                  </tr>
                  <tr className="hover:bg-surface">
                    <td className="py-1.5 px-3 text-text-secondary whitespace-nowrap">23-12-31 15:58</td>
                    <td className="py-1.5 px-3">MSFT</td>
                    <td className="py-1.5 px-3 text-danger">SELL</td>
                    <td className="py-1.5 px-3 text-right">210</td>
                    <td className="py-1.5 px-3 text-right">375.20</td>
                  </tr>
                  <tr className="hover:bg-surface">
                    <td className="py-1.5 px-3 text-text-secondary whitespace-nowrap">23-12-31 14:30</td>
                    <td className="py-1.5 px-3">NVDA</td>
                    <td className="py-1.5 px-3 text-accent-success">BUY</td>
                    <td className="py-1.5 px-3 text-right">125</td>
                    <td className="py-1.5 px-3 text-right">495.10</td>
                  </tr>
                  <tr className="hover:bg-surface">
                    <td className="py-1.5 px-3 text-text-secondary whitespace-nowrap">23-12-30 10:15</td>
                    <td className="py-1.5 px-3">XOM</td>
                    <td className="py-1.5 px-3 text-danger">SELL</td>
                    <td className="py-1.5 px-3 text-right">800</td>
                    <td className="py-1.5 px-3 text-right">101.55</td>
                  </tr>
                  <tr className="hover:bg-surface">
                    <td className="py-1.5 px-3 text-text-secondary whitespace-nowrap">23-12-30 09:45</td>
                    <td className="py-1.5 px-3">JPM</td>
                    <td className="py-1.5 px-3 text-accent-success">BUY</td>
                    <td className="py-1.5 px-3 text-right">300</td>
                    <td className="py-1.5 px-3 text-right">168.90</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
