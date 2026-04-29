import { getFactors } from "@/lib/api";

export default async function FactorLab() {
  const factors = await getFactors();
  const firstFactor = factors.factors[0];

  return (
    <main className="p-container-padding h-full overflow-y-auto flex gap-6">
      {/* Config Sidebar */}
      <aside className="w-[300px] flex-shrink-0 flex flex-col gap-6">
        <div className="bg-bg-surface border border-border-subtle rounded p-4">
          <h2 className="font-headline-lg text-text-primary mb-4">Factor Definition</h2>
          <div className="flex flex-col gap-stack-gap">
            <div className="flex flex-col gap-1">
              <label className="font-label-caps text-text-secondary">UNIVERSE</label>
              <select className="bg-surface-muted border border-border-subtle rounded text-text-mono font-data-mono px-3 py-2 w-full focus:outline-none focus:border-accent-success appearance-none">
                <option>SPY_QQQ_SAMPLE</option>
                <option>ETF_SAMPLE</option>
                <option>LOCAL_CACHE</option>
              </select>
            </div>
            <div className="flex flex-col gap-1 mt-2">
              <label className="font-label-caps text-text-secondary">PRIMARY DATASET</label>
              <select className="bg-surface-muted border border-border-subtle rounded text-text-mono font-data-mono px-3 py-2 w-full focus:outline-none focus:border-accent-success appearance-none">
                <option>PRICE_VOLUME_OHLCV</option>
                <option>API: /api/factors</option>
                <option>API: /api/ohlcv</option>
              </select>
            </div>
            <div className="flex flex-col gap-1 mt-2">
              <label className="font-label-caps text-text-secondary">EXPRESSION</label>
              <div className="bg-surface-muted border border-border-subtle rounded p-3 relative group">
                <div className="absolute top-0 right-0 bg-zinc-800 text-zinc-400 text-[9px] px-2 py-0.5 rounded-bl font-mono">
                  Py
                </div>
                <pre className="font-code-sm text-text-mono whitespace-pre-wrap mt-2">
                  {firstFactor?.factor_id ?? "No factor loaded"} / lookback {firstFactor?.lookback ?? "--"}
                </pre>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-bg-surface border border-border-subtle rounded p-4">
          <h2 className="font-headline-lg text-text-primary mb-4">Analysis Config</h2>
          <div className="flex flex-col gap-stack-gap">
            <div className="flex justify-between items-center">
              <label className="font-label-caps text-text-secondary">FORWARD RETURN</label>
              <span className="font-data-mono text-text-mono bg-surface-muted px-2 py-0.5 rounded border border-border-subtle">
                {factors.factors.length} factors
              </span>
            </div>
            <div className="flex justify-between items-center mt-2">
              <label className="font-label-caps text-text-secondary">QUINTILES</label>
              <span className="font-data-mono text-text-mono bg-surface-muted px-2 py-0.5 rounded border border-border-subtle">
                {factors.safety?.dry_run ? "dry-run" : "unknown"}
              </span>
            </div>
            <div className="flex justify-between items-center mt-2">
              <label className="font-label-caps text-text-secondary">SECTOR NEUTRAL</label>
              <div className="w-8 h-4 bg-accent-success rounded-full relative cursor-pointer opacity-50">
                <div className="w-3 h-3 bg-bg-base rounded-full absolute top-[2px] left-[2px] transition-transform translate-x-4"></div>
              </div>
            </div>
            <div className="flex justify-between items-center mt-2">
              <label className="font-label-caps text-text-secondary">DECAY OVERLAY</label>
              <div className="w-8 h-4 bg-surface-muted border border-border-subtle rounded-full relative cursor-pointer">
                <div className="w-3 h-3 bg-text-secondary rounded-full absolute top-[2px] left-[2px] transition-transform"></div>
              </div>
            </div>
          </div>
          <button className="w-full mt-6 py-2 bg-zinc-800 hover:bg-zinc-700 text-text-primary rounded text-xs font-mono font-bold tracking-tight uppercase transition-colors border border-border-subtle">
            Run Analysis
          </button>
        </div>
      </aside>

      {/* Primary Data Area (4 Quadrants) */}
      <div className="flex-1 grid grid-cols-2 grid-rows-2 gap-4">
        {/* Quad 1: IC / Rank IC */}
        <div className="bg-bg-surface border border-border-subtle rounded flex flex-col">
          <div className="p-3 border-b border-border-subtle flex justify-between items-center bg-surface-container-low">
            <h3 className="font-label-caps text-text-secondary">INFORMATION COEFFICIENT (ROLLING 30D)</h3>
            <div className="flex gap-2">
              <span className="font-data-mono text-[10px] text-accent-success bg-accent-success/10 px-1.5 py-0.5 rounded border border-accent-success/30">
                MEAN: 0.042
              </span>
            </div>
          </div>
          <div className="flex-1 p-4 relative flex items-end">
            <div className="absolute inset-0 p-4 flex items-end opacity-60">
              <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 100">
                <defs>
                  <linearGradient id="ic-grad" x1="0%" x2="0%" y1="0%" y2="100%">
                    <stop offset="0%" stopColor="#00C896" stopOpacity="0.8"></stop>
                    <stop offset="100%" stopColor="#0B1220" stopOpacity="0"></stop>
                  </linearGradient>
                </defs>
                <path d="M0,80 Q10,70 20,85 T40,60 T60,75 T80,50 T100,65 L100,100 L0,100 Z" fill="url(#ic-grad)" opacity="0.2"></path>
                <path d="M0,80 Q10,70 20,85 T40,60 T60,75 T80,50 T100,65" fill="none" stroke="#00C896" strokeWidth="1.5"></path>
                <line stroke="#3c4a43" strokeDasharray="2,2" strokeWidth="0.5" x1="0" x2="100" y1="70" y2="70"></line>
              </svg>
            </div>
          </div>
        </div>

        {/* Quad 2: Factor Returns */}
        <div className="bg-bg-surface border border-border-subtle rounded flex flex-col">
          <div className="p-3 border-b border-border-subtle flex justify-between items-center bg-surface-container-low">
            <h3 className="font-label-caps text-text-secondary">CUMULATIVE FACTOR RETURN (LONG/SHORT)</h3>
            <div className="flex gap-2">
              <span className="font-data-mono text-[10px] text-text-secondary">SHARPE: 1.8</span>
            </div>
          </div>
          <div className="flex-1 p-4 relative flex items-end">
            <div className="absolute inset-0 p-4 flex items-end opacity-80">
              <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 100">
                <path d="M0,90 Q20,85 40,70 T80,40 T100,20" fill="none" stroke="#60A5FA" strokeWidth="1.5"></path>
                <path d="M0,90 Q20,88 40,80 T80,75 T100,65" fill="none" stroke="#3c4a43" strokeDasharray="2,2" strokeWidth="1"></path>
              </svg>
            </div>
          </div>
        </div>

        {/* Quad 3: Quintile Returns Bar */}
        <div className="bg-bg-surface border border-border-subtle rounded flex flex-col">
          <div className="p-3 border-b border-border-subtle flex justify-between items-center bg-surface-container-low">
            <h3 className="font-label-caps text-text-secondary">MEAN FORWARD RETURNS BY QUINTILE</h3>
          </div>
          <div className="flex-1 p-4 flex items-end justify-between gap-2">
            <div className="w-full h-full flex flex-col justify-end items-center group relative">
              <div className="w-full bg-danger/80 border border-danger h-[20%] transition-all hover:bg-danger"></div>
              <span className="text-[9px] font-mono text-text-secondary mt-1">Q1</span>
            </div>
            <div className="w-full h-full flex flex-col justify-end items-center group relative">
              <div className="w-full bg-warning/80 border border-warning h-[40%] transition-all hover:bg-warning"></div>
              <span className="text-[9px] font-mono text-text-secondary mt-1">Q2</span>
            </div>
            <div className="w-full h-full flex flex-col justify-end items-center group relative">
              <div className="w-full bg-surface-muted border border-border-subtle h-[15%] transition-all hover:bg-surface-container-high"></div>
              <span className="text-[9px] font-mono text-text-secondary mt-1">Q3</span>
            </div>
            <div className="w-full h-full flex flex-col justify-end items-center group relative">
              <div className="w-full bg-info/80 border border-info h-[60%] transition-all hover:bg-info"></div>
              <span className="text-[9px] font-mono text-text-secondary mt-1">Q4</span>
            </div>
            <div className="w-full h-full flex flex-col justify-end items-center group relative">
              <div className="w-full bg-accent-success/80 border border-accent-success h-[90%] transition-all hover:bg-accent-success"></div>
              <span className="text-[9px] font-mono text-text-secondary mt-1">Q5</span>
            </div>
          </div>
        </div>

        {/* Quad 4: Distribution Histogram */}
        <div className="bg-bg-surface border border-border-subtle rounded flex flex-col">
          <div className="p-3 border-b border-border-subtle flex justify-between items-center bg-surface-container-low">
            <h3 className="font-label-caps text-text-secondary">CROSS-SECTIONAL DISTRIBUTION (LATEST)</h3>
            <span className="font-data-mono text-[10px] text-text-secondary">SKEW: -0.12</span>
          </div>
          <div className="flex-1 p-4 flex items-end gap-0.5">
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[5%]"></div>
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[15%]"></div>
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[30%]"></div>
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[55%]"></div>
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[80%]"></div>
            <div className="flex-1 bg-accent-success/40 border border-accent-success h-[100%] relative">
              <div className="absolute -top-6 left-1/2 -translate-x-1/2 bg-zinc-800 text-[9px] font-mono px-1 rounded border border-zinc-700">MEDIAN</div>
              <div className="absolute top-0 bottom-0 left-1/2 border-l border-accent-success border-dashed w-px h-full"></div>
            </div>
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[85%]"></div>
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[60%]"></div>
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[35%]"></div>
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[20%]"></div>
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[8%]"></div>
            <div className="flex-1 bg-surface-muted border border-border-subtle h-[2%]"></div>
          </div>
        </div>
      </div>
    </main>
  );
}
