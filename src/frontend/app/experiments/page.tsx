import { Filter, Clock, Database, SlidersHorizontal, Download, Play, FileJson, Target } from "lucide-react";
import { getBacktests, getExperiments } from "@/lib/api";

export default async function Experiments() {
  const [experiments, backtests] = await Promise.all([getExperiments(), getBacktests()]);
  const latestExperiment = experiments.experiments[0];
  const latestBacktest = backtests.backtests[0];

  return (
    <div className="flex w-full h-full bg-base overflow-hidden">
      {/* Left Panel: Experiment List */}
      <aside className="w-[320px] border-r border-border-subtle bg-surface flex flex-col h-full shrink-0">
        <div className="p-4 border-b border-border-subtle flex items-center justify-between bg-surface-dim">
          <h2 className="font-headline-lg text-text-primary">Experiments</h2>
          <button className="p-1 text-text-secondary hover:text-text-primary rounded hover:bg-surface-variant transition-colors">
            <Filter size={18} />
          </button>
        </div>
        <div className="px-4 py-3 border-b border-border-subtle bg-surface">
          <input
            className="w-full bg-surface-container border border-outline-variant rounded pl-3 pr-3 py-1 font-body-sm text-text-primary focus:border-outline focus:ring-0 placeholder-text-secondary"
            placeholder="Filter runs by ID or agent..."
            type="text"
          />
        </div>
        <div className="flex-1 overflow-y-auto">
          {/* Experiment Item: Active */}
          <div className="p-4 border-b border-border-subtle bg-surface-container cursor-pointer border-l-2 border-l-primary hover:bg-surface-container-high transition-colors">
            <div className="flex justify-between items-start mb-2">
              <span className="font-data-mono text-primary font-bold">
                {latestExperiment?.id ?? "NO-EXP"}
              </span>
              <div className="flex items-center gap-1 bg-surface-variant px-1.5 py-0.5 rounded">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-success"></span>
                <span className="font-label-caps text-text-secondary uppercase">Done</span>
              </div>
            </div>
            <div className="font-body-sm text-text-primary font-medium mb-1 truncate">
              {latestExperiment?.path ?? "No local experiment directory yet"}
            </div>
            <div className="font-label-caps text-text-secondary uppercase mb-3 flex gap-2">
              <span>Agent Studio</span> • <span>2h ago</span>
            </div>
            <div className="grid grid-cols-2 gap-2 mt-2">
              <div className="bg-surface-container-low border border-border-subtle rounded p-2">
                <div className="font-label-caps text-text-secondary uppercase mb-0.5">Sharpe</div>
                <div className="font-data-mono text-text-primary">
                  {latestBacktest?.metrics?.sharpe?.toFixed(2) ?? "--"}
                </div>
              </div>
              <div className="bg-surface-container-low border border-border-subtle rounded p-2">
                <div className="font-label-caps text-text-secondary uppercase mb-0.5">Max DD</div>
                <div className="font-data-mono text-warning">
                  {latestBacktest?.metrics?.max_drawdown?.toFixed(4) ?? "--"}
                </div>
              </div>
            </div>
          </div>

          {/* Experiment Item: Inactive */}
          <div className="p-4 border-b border-border-subtle bg-surface cursor-pointer hover:bg-surface-container transition-colors border-l-2 border-l-transparent">
            <div className="flex justify-between items-start mb-2">
              <span className="font-data-mono text-text-secondary">EXP-8923</span>
              <div className="flex items-center gap-1 bg-surface-variant px-1.5 py-0.5 rounded">
                <span className="w-1.5 h-1.5 rounded-full bg-danger"></span>
                <span className="font-label-caps text-text-secondary uppercase">Failed</span>
              </div>
            </div>
            <div className="font-body-sm text-text-primary font-medium mb-1 truncate">Vol_Arb_DeepQ_V2</div>
            <div className="font-label-caps text-text-secondary uppercase mb-3 flex gap-2">
              <span>Factor Lab</span> • <span>5h ago</span>
            </div>
            <div className="grid grid-cols-2 gap-2 mt-2 opacity-50">
              <div className="bg-surface-container-low border border-border-subtle rounded p-2">
                <div className="font-label-caps text-text-secondary uppercase mb-0.5">Sharpe</div>
                <div className="font-data-mono text-text-primary">--</div>
              </div>
              <div className="bg-surface-container-low border border-border-subtle rounded p-2">
                <div className="font-label-caps text-text-secondary uppercase mb-0.5">Max DD</div>
                <div className="font-data-mono text-text-primary">--</div>
              </div>
            </div>
          </div>

          {/* Experiment Item: Running */}
          <div className="p-4 border-b border-border-subtle bg-surface cursor-pointer hover:bg-surface-container transition-colors border-l-2 border-l-transparent">
            <div className="flex justify-between items-start mb-2">
              <span className="font-data-mono text-text-secondary">EXP-8925</span>
              <div className="flex items-center gap-1 bg-surface-variant px-1.5 py-0.5 rounded">
                <span className="w-1.5 h-1.5 rounded-full bg-info animate-pulse"></span>
                <span className="font-label-caps text-text-secondary uppercase">Running</span>
              </div>
            </div>
            <div className="font-body-sm text-text-primary font-medium mb-1 truncate">MeanRev_LGBM_Optim</div>
            <div className="font-label-caps text-text-secondary uppercase mb-3 flex gap-2">
              <span>Agent Studio</span> • <span>10m elapsed</span>
            </div>
            <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden mt-3">
              <div className="bg-info h-full w-[45%]"></div>
            </div>
            <div className="text-right font-data-mono text-[10px] text-text-secondary mt-1">Fold 3/10</div>
          </div>
        </div>
      </aside>

      {/* Right Panel: Data Canvas */}
      <section className="flex-1 flex flex-col min-w-0 bg-base overflow-hidden">
        {/* Canvas Header */}
        <div className="px-6 py-5 border-b border-border-subtle bg-surface-dim">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3 mb-1">
                <h1 className="font-headline-xl text-text-primary">
                  API Experiments
                </h1>
                <span className="bg-surface-muted border border-border-subtle text-text-secondary font-data-mono text-code-sm px-2 py-0.5 rounded">
                  {experiments.experiments.length} local
                </span>
              </div>
              <div className="flex items-center gap-4 text-text-secondary font-body-sm">
                <span className="flex items-center gap-1"><Clock size={14} /> 02:14:35</span>
                <span className="flex items-center gap-1"><Database size={14} /> /api/experiments</span>
                <span className="flex items-center gap-1"><SlidersHorizontal size={14} /> {backtests.backtests.length} backtests</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button className="flex items-center gap-2 px-3 py-1.5 border border-border-subtle bg-surface text-text-primary rounded hover:bg-surface-variant transition-colors font-body-sm">
                <Download size={16} /> Export
              </button>
              <button className="flex items-center gap-2 px-3 py-1.5 border border-accent-success text-accent-success bg-accent-success/5 rounded hover:bg-accent-success/10 transition-colors font-body-sm font-medium">
                <Play size={16} /> Register Agent
              </button>
            </div>
          </div>
          {/* Tabs */}
          <div className="flex items-center gap-6 mt-6 border-b border-border-subtle">
            <button className="pb-3 text-primary border-b-2 border-primary font-body-sm font-medium">Sweep heatmap</button>
            <button className="pb-3 text-text-secondary hover:text-text-primary border-b-2 border-transparent transition-colors font-body-sm">Walk-forward folds</button>
            <button className="pb-3 text-text-secondary hover:text-text-primary border-b-2 border-transparent transition-colors font-body-sm">Run comparison</button>
            <button className="pb-3 text-text-secondary hover:text-text-primary border-b-2 border-transparent transition-colors font-body-sm flex items-center gap-1">
              <FileJson size={14} /> Agent summary
            </button>
          </div>
        </div>

        {/* Canvas Content Area */}
        <div className="flex-1 p-6 overflow-y-auto bg-base">
          {/* Filters/Controls Bar for Heatmap */}
          <div className="flex flex-wrap gap-4 items-center justify-between mb-6 bg-surface p-3 rounded border border-border-subtle">
            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex flex-col gap-1">
                <label className="font-label-caps text-text-secondary">Z-Axis Metric</label>
                <select className="bg-surface-container border border-outline-variant text-text-primary font-body-sm rounded py-1 pl-2 pr-8 focus:ring-0 focus:border-primary">
                  <option>Sharpe Ratio</option>
                  <option>Sortino Ratio</option>
                  <option>Max Drawdown</option>
                </select>
              </div>
              <div className="w-px h-8 bg-border-subtle hidden md:block"></div>
              <div className="flex flex-col gap-1">
                <label className="font-label-caps text-text-secondary">X-Axis Parameter</label>
                <select className="bg-surface-container border border-outline-variant text-text-primary font-body-sm rounded py-1 pl-2 pr-8 focus:ring-0 focus:border-primary">
                  <option>learning_rate</option>
                  <option>max_depth</option>
                  <option>n_estimators</option>
                </select>
              </div>
              <span className="text-text-secondary text-[16px] hidden lg:block">x</span>
              <div className="flex flex-col gap-1">
                <label className="font-label-caps text-text-secondary">Y-Axis Parameter</label>
                <select className="bg-surface-container border border-outline-variant text-text-primary font-body-sm rounded py-1 pl-2 pr-8 focus:ring-0 focus:border-primary">
                  <option>max_depth</option>
                  <option>learning_rate</option>
                  <option>subsample</option>
                </select>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="font-label-caps text-text-secondary">Interpolate</span>
              <div className="w-8 h-4 bg-surface-variant rounded-full relative cursor-pointer border border-outline-variant">
                <div className="w-3 h-3 bg-text-secondary rounded-full absolute left-[2px] top-[1px]"></div>
              </div>
            </div>
          </div>

          {/* Matrix Visualization Box */}
          <div className="bg-surface border border-border-subtle rounded p-6 flex flex-col">
            <div className="flex flex-wrap gap-4 justify-between items-center mb-6">
              <h3 className="font-headline-lg text-text-primary">Parameter Topography</h3>
              {/* Legend */}
              <div className="flex items-center gap-2">
                <span className="font-label-caps text-text-secondary">Poor</span>
                <div className="flex w-32 h-2 rounded-full overflow-hidden">
                  <div className="flex-1 bg-surface-container-low"></div>
                  <div className="flex-1 bg-surface-container-high"></div>
                  <div className="flex-1 bg-primary/20"></div>
                  <div className="flex-1 bg-primary/50"></div>
                  <div className="flex-1 bg-primary"></div>
                </div>
                <span className="font-label-caps text-text-secondary">Optimal</span>
              </div>
            </div>

            {/* The Matrix */}
            <div className="flex-1 flex min-h-[400px]">
              {/* Y-Axis Labels */}
              <div className="flex flex-col justify-between pr-4 py-2 border-r border-border-subtle shrink-0 items-end">
                <span className="font-data-mono text-text-secondary block">9</span>
                <span className="font-data-mono text-text-secondary block">7</span>
                <span className="font-data-mono text-text-secondary block">5</span>
                <span className="font-data-mono text-text-secondary block">3</span>
                <div className="mt-4 font-label-caps text-text-secondary tracking-widest text-right rotate-180" style={{ writingMode: "vertical-rl" }}>MAX_DEPTH</div>
              </div>

              {/* Grid Area */}
              <div className="flex-1 pl-1 flex flex-col">
                <div className="flex-1 grid grid-cols-5 grid-rows-4 gap-1 p-1 bg-surface-muted rounded">
                  {/* Row 9 */}
                  <div className="bg-danger/20 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-surface-container border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary/30 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary/60 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary/90 border border-primary hover:border-text-primary cursor-crosshair relative group transition-all"></div>

                  {/* Row 7 */}
                  <div className="bg-danger/30 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-surface-container-high border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary/50 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary border border-primary shadow-[0_0_10px_rgba(66,229,176,0.3)] hover:border-text-primary cursor-crosshair relative group transition-all z-10 flex items-center justify-center">
                    <Target className="text-surface-dim" size={16} />
                  </div>
                  <div className="bg-primary/80 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>

                  {/* Row 5 */}
                  <div className="bg-surface-container-low border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary/20 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary/40 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary/70 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary/50 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>

                  {/* Row 3 */}
                  <div className="bg-surface-container-lowest border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-surface-container-lowest border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-surface-container border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary/20 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                  <div className="bg-primary/30 border border-border-subtle hover:border-text-primary cursor-crosshair relative group transition-all"></div>
                </div>
                {/* X-Axis Labels */}
                <div className="flex justify-between px-2 pt-4 border-t border-border-subtle mt-1">
                  <span className="font-data-mono text-text-secondary w-1/5 text-center">0.001</span>
                  <span className="font-data-mono text-text-secondary w-1/5 text-center">0.005</span>
                  <span className="font-data-mono text-text-secondary w-1/5 text-center">0.010</span>
                  <span className="font-data-mono text-text-secondary w-1/5 text-center">0.050</span>
                  <span className="font-data-mono text-text-secondary w-1/5 text-center">0.100</span>
                </div>
                <div className="mt-2 text-center font-label-caps text-text-secondary tracking-widest">LEARNING_RATE</div>
              </div>
            </div>
          </div>

          {/* Selected Cell Details Panel */}
          <div className="mt-6 bg-surface-muted border border-border-subtle rounded p-4 flex flex-col lg:flex-row gap-4 lg:items-center justify-between shadow-sm">
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <Target className="text-primary" size={20} />
                <span className="font-label-caps text-text-primary uppercase tracking-wider">Global Optimum</span>
              </div>
              <div className="w-px h-6 bg-border-subtle hidden md:block"></div>
              <div className="font-data-mono text-code-sm text-text-secondary">
                <span className="text-primary mr-1">lr:</span>0.050 <span className="mx-2 text-border-subtle">|</span>
                <span className="text-primary mr-1">depth:</span>7
              </div>
            </div>
            <div className="flex items-center gap-8">
              <div className="flex flex-col items-end">
                <span className="font-label-caps text-text-secondary uppercase">Sharpe</span>
                <span className="font-data-mono text-accent-success font-bold">2.14</span>
              </div>
              <div className="flex flex-col items-end">
                <span className="font-label-caps text-text-secondary uppercase">Drawdown</span>
                <span className="font-data-mono text-warning">-12.4%</span>
              </div>
              <button className="px-4 py-1.5 bg-surface border border-border-subtle text-text-primary hover:bg-surface-variant transition-colors rounded font-body-sm">
                View JSON
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
