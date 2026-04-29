import { Activity, ShieldAlert, Crosshair, Ban, Layers, AlertCircle } from "lucide-react";
import { formatMoney, getHealth, getPaperRuns } from "@/lib/api";

export default async function PaperTrading() {
  const [health, paperRuns] = await Promise.all([getHealth(), getPaperRuns()]);
  const latest = paperRuns.paper_runs[0]?.summary;

  return (
    <div className="flex-1 flex flex-col xl:flex-row h-full overflow-hidden bg-base">
      <div className="flex-1 p-4 lg:p-6 overflow-y-auto space-y-6">
        <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-surface border border-border-subtle rounded p-4 relative overflow-hidden group">
            <h3 className="font-label-caps text-text-secondary uppercase mb-2">Exposure (Net)</h3>
            <div className="flex items-baseline gap-2">
              <span className="font-data-mono text-headline-xl text-primary">
                {formatMoney(latest?.final_equity)}
              </span>
            </div>
            <div className="mt-4 w-full h-1.5 bg-surface-variant rounded-full overflow-hidden relative">
              <div className="absolute left-[50%] h-full w-[2px] bg-border-subtle z-10 -translate-x-1/2"></div>
              <div className="absolute left-[50%] h-full bg-primary" style={{ width: "15%" }}></div>
            </div>
          </div>

          <div className="bg-surface border border-border-subtle rounded p-4">
            <h3 className="font-label-caps text-text-secondary uppercase mb-2">Gross Leverage</h3>
            <div className="flex items-baseline gap-2">
              <span className="font-data-mono text-headline-xl text-warning">
                {latest?.order_count ?? 0}
              </span>
              <span className="font-data-mono text-[10px] text-text-secondary">orders</span>
            </div>
            <div className="mt-4 w-full h-1.5 bg-surface-variant rounded-full overflow-hidden">
              <div className="h-full bg-warning w-[73%]"></div>
            </div>
          </div>

          <div className="bg-surface border border-danger/30 rounded p-4 relative bg-danger/5">
            <h3 className="font-label-caps text-danger uppercase mb-2 flex items-center gap-2">
              <AlertCircle size={14} /> Value at Risk (99%)
            </h3>
            <div className="flex items-baseline gap-2">
              <span className="font-data-mono text-headline-xl text-danger">
                {latest?.risk_breach_count ?? 0}
              </span>
              <span className="font-data-mono text-[10px] text-danger bg-danger/10 px-1 py-0.5 rounded border border-danger/20">WARN</span>
            </div>
            <div className="mt-4 w-full h-1.5 bg-danger/20 rounded-full overflow-hidden">
              <div className="h-full bg-danger w-[85%]"></div>
            </div>
          </div>

          <div className="bg-surface border border-border-subtle rounded p-4">
            <h3 className="font-label-caps text-text-secondary uppercase mb-2">Active Limit Orders</h3>
            <div className="flex items-baseline gap-2">
              <span className="font-data-mono text-headline-xl text-text-primary">
                {latest?.trade_count ?? 0}
              </span>
            </div>
            <div className="mt-4 flex gap-1">
              <div className="w-1/2 h-1.5 bg-accent-success rounded-l-full"></div>
              <div className="w-1/2 h-1.5 bg-danger rounded-r-full"></div>
            </div>
          </div>
        </section>

        <section className="bg-surface border border-border-subtle rounded flex flex-col min-h-[300px]">
          <div className="p-4 border-b border-border-subtle flex justify-between items-center bg-surface-dim">
            <h2 className="font-headline-lg text-text-primary flex items-center gap-2">
              <Layers className="text-primary" size={18} /> Aggregate Book Configuration
            </h2>
          </div>
          <div className="p-4 grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="col-span-2">
              <h4 className="font-label-caps text-text-secondary border-b border-border-subtle pb-2 mb-4">Capital Allocation by Strategy</h4>
              <div className="space-y-4">
                <div className="flex flex-col gap-1">
                  <div className="flex justify-between">
                    <span className="font-data-mono text-text-primary text-sm">Backend Safety</span>
                    <span className="font-data-mono text-text-secondary text-sm">
                      kill_switch={String(health.safety?.kill_switch)}
                    </span>
                  </div>
                  <div className="w-full h-2 bg-surface-variant rounded-full overflow-hidden">
                    <div className="h-full bg-info w-[45%]"></div>
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <div className="flex justify-between">
                    <span className="font-data-mono text-text-primary text-sm">Live Trading</span>
                    <span className="font-data-mono text-text-secondary text-sm">
                      {String(health.safety?.live_trading_enabled)}
                    </span>
                  </div>
                  <div className="w-full h-2 bg-surface-variant rounded-full overflow-hidden">
                    <div className="h-full bg-warning w-[30%]"></div>
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <div className="flex justify-between">
                    <span className="font-data-mono text-text-primary text-sm">Paper Runs</span>
                    <span className="font-data-mono text-text-secondary text-sm">
                      {paperRuns.paper_runs.length}
                    </span>
                  </div>
                  <div className="w-full h-2 bg-surface-variant rounded-full overflow-hidden">
                    <div className="h-full bg-primary w-[15%]"></div>
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <div className="flex justify-between">
                    <span className="font-data-mono text-text-secondary text-sm">Unallocated Cash</span>
                    <span className="font-data-mono text-text-secondary text-sm">10% ($1.00M)</span>
                  </div>
                  <div className="w-full h-2 bg-surface-variant rounded-full border border-border-subtle overflow-hidden">
                    <div className="h-full bg-surface-dim w-[10%]"></div>
                  </div>
                </div>
              </div>
            </div>

            <div className="border-l border-border-subtle pl-6 flex flex-col justify-center">
              <h4 className="font-label-caps text-text-secondary border-b border-border-subtle pb-2 mb-4">Master Controls</h4>
              <button className="w-full py-3 bg-surface-variant border border-border-subtle text-text-primary hover:border-info hover:text-info rounded mb-4 font-label-caps tracking-widest transition-colors flex items-center justify-center gap-2">
                <Activity size={16} /> Rebalance Portfolio
              </button>
              <button className="w-full py-3 bg-surface-variant border border-border-subtle text-text-primary hover:border-warning hover:text-warning rounded font-label-caps tracking-widest transition-colors flex items-center justify-center gap-2">
                <Crosshair size={16} /> Force Liquidate (Selected)
              </button>
            </div>
          </div>
        </section>
      </div>

      <aside className="w-full xl:w-[320px] bg-bg-surface border-l border-border-subtle p-6 flex flex-col flex-shrink-0 relative overflow-hidden">
        <div className="absolute inset-0 bg-danger/5 pointer-events-none"></div>
        <div className="absolute top-0 bottom-0 left-0 w-1 bg-danger h-full"></div>

        <div className="relative z-10 flex flex-col h-full">
          <div className="flex items-center gap-2 text-danger mb-6 border-b border-danger/20 pb-4">
            <ShieldAlert size={20} />
            <h2 className="font-headline-lg uppercase tracking-wider">Risk Center</h2>
          </div>

          <div className="flex flex-col items-center justify-center py-6 mb-8 bg-surface-dim border border-danger/30 rounded-lg">
            <button className="w-40 h-40 rounded-full bg-surface-variant border-[10px] border-surface flex flex-col items-center justify-center hover:border-danger/30 hover:bg-danger/10 transition-all cursor-pointer shadow-[0_0_30px_rgba(255,100,100,0.1)] group">
               <Ban size={40} className="text-danger mb-2 group-hover:scale-110 transition-transform" />
               <span className="font-label-caps text-danger font-bold uppercase tracking-widest">Master<br/>Kill</span>
            </button>
            <p className="font-body-sm text-text-secondary text-center mt-6 px-4">
              halts all trading and cancels open orders immediately.
            </p>
          </div>

          <div className="space-y-4 flex-1">
            <h3 className="font-label-caps text-text-secondary">HARD LIMITS</h3>
            <div className="bg-surface rounded p-3 border border-border-subtle hover:border-danger/50 transition-colors">
              <div className="flex justify-between items-center mb-1">
                <span className="font-body-sm text-text-primary">Daily Drawdown</span>
                <div className="w-12 h-6 bg-danger/20 rounded-full relative cursor-pointer border border-danger">
                  <div className="absolute right-0.5 top-[2px] w-4 h-4 bg-danger rounded-full"></div>
                </div>
              </div>
              <div className="flex justify-between items-center mt-2 font-data-mono text-xs">
                <span className="text-text-secondary">Current: -2.1%</span>
                <span className="text-text-primary">Limit: -5.0%</span>
              </div>
            </div>

            <div className="bg-surface rounded p-3 border border-border-subtle hover:border-danger/50 transition-colors">
              <div className="flex justify-between items-center mb-1">
                <span className="font-body-sm text-text-primary">Concentration</span>
                <div className="w-12 h-6 bg-danger/20 rounded-full relative cursor-pointer border border-danger">
                  <div className="absolute right-0.5 top-[2px] w-4 h-4 bg-danger rounded-full"></div>
                </div>
              </div>
              <div className="flex justify-between items-center mt-2 font-data-mono text-xs">
                <span className="text-text-secondary">Max Asset: 12%</span>
                <span className="text-text-primary">Limit: 15.0%</span>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
