import {
  TrendingUp,
  CreditCard,
  Target,
  LineChart,
  Code,
  FlaskConical,
  ReceiptText,
  Filter,
  ArrowRight,
  Play,
  SlidersHorizontal,
  Download,
} from "lucide-react";
import {
  formatMoney,
  formatPercent,
  getAgentCandidates,
  getBacktests,
  getFactors,
  getHealth,
  getPaperRuns,
  getPredictionMarkets,
  getSymbols,
} from "@/lib/api";

export default async function Dashboard() {
  const [health, symbols, factors, backtests, paperRuns, candidates, predictionMarkets] =
    await Promise.all([
      getHealth(),
      getSymbols(),
      getFactors(),
      getBacktests(),
      getPaperRuns(),
      getAgentCandidates(),
      getPredictionMarkets(),
    ]);
  const latestBacktest = backtests.backtests[0];
  const latestPaper = paperRuns.paper_runs[0];
  const paperSummary = latestPaper?.summary;

  return (
    <div className="flex-1 flex flex-col xl:flex-row h-full overflow-hidden">
      {/* Center Canvas */}
      <div className="flex-1 p-gutter lg:p-container-padding overflow-y-auto space-y-6">
        {/* KPIs */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-bg-surface border border-border-subtle rounded-lg p-4 flex flex-col justify-between h-28 relative overflow-hidden group">
            <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
            <div className="flex justify-between items-start z-10">
              <h3 className="font-label-caps text-text-secondary uppercase">Registered Factors</h3>
              <TrendingUp className="text-primary" size={14} />
            </div>
            <div className="z-10 flex items-baseline gap-2">
              <span className="font-data-mono text-headline-xl text-text-primary">{factors.factors.length}</span>
              <span className="font-data-mono text-[10px] text-accent-success bg-accent-success/10 px-1.5 py-0.5 rounded-sm">
                API
              </span>
            </div>
          </div>

          <div className="bg-bg-surface border border-border-subtle rounded-lg p-4 flex flex-col justify-between h-28 relative overflow-hidden group">
            <div className="absolute inset-0 bg-gradient-to-br from-info/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
            <div className="flex justify-between items-start z-10">
              <h3 className="font-label-caps text-text-secondary uppercase">Paper Equity</h3>
              <CreditCard className="text-info" size={14} />
            </div>
            <div className="z-10 flex items-baseline gap-2">
              <span className="font-data-mono text-headline-xl text-text-primary">
                {formatMoney(paperSummary?.final_equity)}
              </span>
              <span className="font-data-mono text-[10px] text-accent-success bg-accent-success/10 px-1.5 py-0.5 rounded-sm">
                {paperRuns.paper_runs.length} runs
              </span>
            </div>
          </div>

          <div className="bg-bg-surface border border-border-subtle rounded-lg p-4 flex flex-col justify-between h-28 relative overflow-hidden group">
            <div className="absolute inset-0 bg-gradient-to-br from-warning/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
            <div className="flex justify-between items-start z-10">
              <h3 className="font-label-caps text-text-secondary uppercase">Agent Candidates</h3>
              <Target className="text-warning" size={14} />
            </div>
            <div className="z-10 flex items-baseline gap-2">
              <span className="font-data-mono text-headline-xl text-text-primary">{candidates.candidates.length}</span>
              <span className="font-data-mono text-[10px] text-text-secondary">pending pool</span>
            </div>
          </div>

          <div className="bg-bg-surface border border-border-subtle rounded-lg p-4 flex flex-col justify-between h-28 relative overflow-hidden group">
            <div className="absolute inset-0 bg-gradient-to-br from-danger/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
            <div className="flex justify-between items-start z-10">
              <h3 className="font-label-caps text-text-secondary uppercase">Latest Sharpe</h3>
              <LineChart className="text-text-secondary" size={14} />
            </div>
            <div className="z-10 flex items-baseline gap-2">
              <span className="font-data-mono text-headline-xl text-text-primary">
                {latestBacktest?.metrics?.sharpe?.toFixed(2) ?? "--"}
              </span>
              <span className="font-data-mono text-[10px] text-danger bg-danger/10 px-1.5 py-0.5 rounded-sm">
                {formatPercent(latestBacktest?.metrics?.max_drawdown)}
              </span>
            </div>
          </div>
        </section>

        {/* Main Content Area: Recent Runs */}
        <section className="space-y-4">
          <div className="flex items-center justify-between border-b border-border-subtle pb-2">
            <h2 className="font-headline-lg text-text-primary">Recent Operations</h2>
            <button className="text-primary hover:text-primary-fixed transition-colors font-label-caps flex items-center gap-1">
              View All <ArrowRight size={14} />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-bg-surface border border-border-subtle rounded-lg flex flex-col h-64 hover:border-border-subtle/80 transition-colors">
              <div className="p-3 border-b border-border-subtle flex justify-between items-center bg-bg-surface-muted/30">
                <div className="flex items-center gap-2">
                  <LineChart className="text-info" size={14} />
                  <span className="font-label-caps text-text-secondary">BACKTEST</span>
                </div>
                <span className="w-2 h-2 rounded-full bg-accent-success"></span>
              </div>
              <div className="p-4 flex-1 flex flex-col">
                <h4 className="font-body-md text-text-primary font-medium mb-1 truncate">
                  {latestBacktest?.id ?? "No backtest run yet"}
                </h4>
                <p className="font-code-sm text-text-secondary mb-4 truncate">Source: /api/backtests</p>
                <div className="mt-auto space-y-2">
                  <div className="flex justify-between items-end">
                    <span className="font-label-caps text-text-secondary">Return</span>
                    <span className="font-data-mono text-accent-success text-sm">
                      {formatPercent(latestBacktest?.metrics?.total_return)}
                    </span>
                  </div>
                  <div className="flex justify-between items-end">
                    <span className="font-label-caps text-text-secondary">Max DD</span>
                    <span className="font-data-mono text-danger text-sm">
                      {formatPercent(latestBacktest?.metrics?.max_drawdown)}
                    </span>
                  </div>
                  <div className="w-full h-1 bg-surface-variant rounded-full mt-2 overflow-hidden">
                    <div className="h-full bg-accent-success w-full"></div>
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-bg-surface border border-border-subtle rounded-lg flex flex-col h-64 hover:border-border-subtle/80 transition-colors">
              <div className="p-3 border-b border-border-subtle flex justify-between items-center bg-bg-surface-muted/30">
                <div className="flex items-center gap-2">
                  <FlaskConical className="text-warning" size={14} />
                  <span className="font-label-caps text-text-secondary">EXPERIMENT</span>
                </div>
                <span className="w-2 h-2 rounded-full bg-warning animate-pulse"></span>
              </div>
              <div className="p-4 flex-1 flex flex-col">
                <h4 className="font-body-md text-text-primary font-medium mb-1 truncate">
                  {symbols.symbols.join(", ")}
                </h4>
                <p className="font-code-sm text-text-secondary mb-4 truncate">Source: /api/symbols ({symbols.source})</p>
                <div className="mt-auto space-y-2">
                  <div className="flex justify-between items-end">
                    <span className="font-label-caps text-text-secondary">Progress</span>
                    <span className="font-data-mono text-text-primary text-sm">{symbols.symbols.length} symbols</span>
                  </div>
                  <div className="flex justify-between items-end">
                    <span className="font-label-caps text-text-secondary">Best Sharpe</span>
                    <span className="font-data-mono text-text-primary text-sm">{health.status}</span>
                  </div>
                  <div className="w-full h-1 bg-surface-variant rounded-full mt-2 overflow-hidden">
                    <div className="h-full bg-warning w-[45%]"></div>
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-bg-surface border border-border-subtle rounded-lg flex flex-col h-64 hover:border-primary/50 transition-colors shadow-[0_0_15px_rgba(0,200,150,0.05)]">
              <div className="p-3 border-b border-border-subtle flex justify-between items-center bg-primary/5">
                <div className="flex items-center gap-2">
                  <ReceiptText className="text-primary" size={14} />
                  <span className="font-label-caps text-primary">PAPER RUN</span>
                </div>
                <span className="w-2 h-2 rounded-full bg-accent-success"></span>
              </div>
              <div className="p-4 flex-1 flex flex-col">
                <h4 className="font-body-md text-text-primary font-medium mb-1 truncate">
                  {latestPaper?.id ?? "No paper run yet"}
                </h4>
                <p className="font-code-sm text-text-secondary mb-4 truncate">Source: /api/paper</p>
                <div className="mt-auto space-y-2">
                  <div className="flex justify-between items-end">
                    <span className="font-label-caps text-text-secondary">Uptime</span>
                    <span className="font-data-mono text-text-primary text-sm">
                      {paperSummary?.order_count ?? 0} orders
                    </span>
                  </div>
                  <div className="flex justify-between items-end">
                    <span className="font-label-caps text-text-secondary">Net PnL</span>
                    <span className="font-data-mono text-accent-success text-sm">
                      {formatMoney(paperSummary?.final_equity)}
                    </span>
                  </div>
                  <div className="w-full h-1 bg-surface-variant rounded-full mt-2 overflow-hidden">
                    <div className="h-full bg-primary w-full"></div>
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-bg-surface border border-border-subtle rounded-lg flex flex-col h-64 hover:border-border-subtle/80 transition-colors opacity-75">
              <div className="p-3 border-b border-border-subtle flex justify-between items-center bg-bg-surface-muted/30">
                <div className="flex items-center gap-2">
                  <Code className="text-text-secondary" size={14} />
                  <span className="font-label-caps text-text-secondary">AGENT BUILD</span>
                </div>
                <span className="w-2 h-2 rounded-full bg-danger"></span>
              </div>
              <div className="p-4 flex-1 flex flex-col">
                <h4 className="font-body-md text-text-primary font-medium mb-1 truncate">
                  {predictionMarkets.markets[0]?.question ?? "Prediction market sample"}
                </h4>
                <p className="font-code-sm text-text-secondary mb-4 truncate">Source: /api/prediction-market/markets</p>
                <div className="mt-auto space-y-2">
                  <div className="flex justify-between items-end">
                    <span className="font-label-caps text-text-secondary">Status</span>
                    <span className="font-data-mono text-danger text-sm">
                      {predictionMarkets.markets.length} markets
                    </span>
                  </div>
                  <div className="flex justify-between items-end">
                    <span className="font-label-caps text-text-secondary">Runtime</span>
                    <span className="font-data-mono text-text-primary text-sm">
                      {predictionMarkets.order_books.length} books
                    </span>
                  </div>
                  <div className="w-full h-1 bg-surface-variant rounded-full mt-2 overflow-hidden">
                    <div className="h-full bg-danger w-[15%]"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* System Log */}
        <section className="border border-border-subtle rounded-lg bg-bg-surface overflow-hidden">
          <div className="p-3 border-b border-border-subtle bg-bg-surface-muted/50 flex justify-between items-center">
            <h3 className="font-label-caps text-text-secondary">SYSTEM LOG</h3>
            <Filter className="text-text-secondary cursor-pointer" size={14} />
          </div>
          <div className="p-0 overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <tbody>
                <tr className="border-b border-border-subtle/50 hover:bg-bg-surface-muted/20">
                  <td className="py-2 px-4 font-data-mono text-xs text-text-secondary w-24">14:02:11</td>
                  <td className="py-2 px-4 font-body-sm text-text-primary whitespace-nowrap">
                    API health <span className="font-data-mono text-primary">{health.status}</span> from bind {health.safety?.bind_address}
                  </td>
                  <td className="py-2 px-4 font-data-mono text-xs text-right text-text-secondary">INFO</td>
                </tr>
                <tr className="border-b border-border-subtle/50 hover:bg-bg-surface-muted/20">
                  <td className="py-2 px-4 font-data-mono text-xs text-text-secondary w-24">14:00:05</td>
                  <td className="py-2 px-4 font-body-sm text-text-primary whitespace-nowrap">
                    Symbols loaded from <span className="font-data-mono text-info">/api/symbols</span>
                  </td>
                  <td className="py-2 px-4 font-data-mono text-xs text-right text-text-secondary">INFO</td>
                </tr>
                <tr className="hover:bg-bg-surface-muted/20">
                  <td className="py-2 px-4 font-data-mono text-xs text-text-secondary w-24">13:45:22</td>
                  <td className="py-2 px-4 font-body-sm text-danger whitespace-nowrap">
                    Live trading disabled by API safety footer.
                  </td>
                  <td className="py-2 px-4 font-data-mono text-xs text-right text-danger">WARN</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* Right Sidebar Config / Quick Actions */}
      <aside className="w-full xl:w-[320px] bg-bg-surface border-l border-border-subtle p-6 flex flex-col gap-6 flex-shrink-0 overflow-y-auto">
        <div>
          <h3 className="font-label-caps text-text-secondary mb-4 border-b border-border-subtle pb-2">
            QUICK ACTIONS
          </h3>
          <div className="space-y-3">
            <button className="w-full bg-bg-surface-muted border border-border-subtle hover:border-primary text-text-primary py-2 px-4 rounded font-body-sm transition-colors flex items-center gap-3 text-left">
              <Play className="text-primary" size={14} />
              Start New Backtest
            </button>
            <button className="w-full bg-bg-surface-muted border border-border-subtle hover:border-warning text-text-primary py-2 px-4 rounded font-body-sm transition-colors flex items-center gap-3 text-left">
              <SlidersHorizontal className="text-warning" size={14} />
              Hyperparameter Search
            </button>
            <button className="w-full bg-bg-surface-muted border border-border-subtle hover:border-info text-text-primary py-2 px-4 rounded font-body-sm transition-colors flex items-center gap-3 text-left">
              <Download className="text-info" size={14} />
              Export Data Snapshot
            </button>
          </div>
        </div>

        <div>
          <h3 className="font-label-caps text-text-secondary mb-4 border-b border-border-subtle pb-2">
            ENVIRONMENT STATE
          </h3>
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="font-body-sm text-text-primary">API Feed</span>
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-sm bg-bg-surface-muted border border-border-subtle">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-success"></span>
                <span className="font-data-mono text-[10px] text-text-secondary uppercase">
                  {health.status === "ok" ? "Connected" : "Offline"}
                </span>
              </div>
            </div>
            <div className="flex justify-between items-center">
              <span className="font-body-sm text-text-primary">Execution Engine</span>
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-sm bg-primary/10 border border-primary/30">
                <span className="w-1.5 h-1.5 rounded-full bg-primary"></span>
                <span className="font-data-mono text-[10px] text-primary uppercase">Paper</span>
              </div>
            </div>

            <div className="pt-4 border-t border-border-subtle">
              <div className="flex justify-between items-center mb-2">
                <span className="font-body-sm text-text-primary font-medium">Kill Switch</span>
                <div className="w-8 h-4 bg-danger/20 rounded-full relative cursor-not-allowed border border-danger/50">
                  <div className="absolute right-0.5 top-[1px] w-3 h-3 bg-danger rounded-full"></div>
                </div>
              </div>
              <p className="font-body-sm text-[11px] text-text-secondary leading-tight">
                Backend reports kill_switch={String(health.safety?.kill_switch)} and live_trading_enabled={String(health.safety?.live_trading_enabled)}.
              </p>
            </div>
          </div>
        </div>

        <div className="mt-auto pt-6">
          <div className="bg-bg-surface-muted border border-border-subtle rounded-lg p-4">
            <h4 className="font-label-caps text-text-secondary mb-2">RESOURCE USAGE</h4>
            <div className="space-y-3">
              <div>
                <div className="flex justify-between font-data-mono text-xs mb-1">
                  <span className="text-text-primary">CPU</span>
                  <span className="text-text-secondary">42%</span>
                </div>
                <div className="w-full h-1 bg-bg-base rounded-full overflow-hidden">
                  <div className="h-full bg-info w-[42%]"></div>
                </div>
              </div>
              <div>
                <div className="flex justify-between font-data-mono text-xs mb-1">
                  <span className="text-text-primary">RAM</span>
                  <span className="text-text-secondary">18.4GB / 32GB</span>
                </div>
                <div className="w-full h-1 bg-bg-base rounded-full overflow-hidden">
                  <div className="h-full bg-warning w-[65%]"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
