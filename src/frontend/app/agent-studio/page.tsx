import { Plus, Cpu, Network, PackageX, Sparkles, MessageSquare, Target } from "lucide-react";
import { getAgentCandidates, getFactors } from "@/lib/api";

export default async function AgentStudio() {
  const [candidates, factors] = await Promise.all([getAgentCandidates(), getFactors()]);
  const latestCandidate = candidates.candidates[0];

  return (
    <div className="flex h-full w-full overflow-hidden bg-base">
      <aside className="w-[280px] bg-surface flex flex-col h-full border-r border-border-subtle shrink-0">
        <div className="p-4 border-b border-border-subtle bg-surface-dim">
          <button className="w-full flex items-center justify-center gap-2 py-2 bg-primary/10 border border-primary/30 text-primary hover:bg-primary/20 transition-colors uppercase font-label-caps tracking-widest rounded">
            <Plus size={16} /> Candidate Pool ({candidates.candidates.length})
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          <div className="py-2">
            <h3 className="px-4 py-2 font-label-caps text-text-secondary">Core Strategies</h3>
            <ul className="space-y-0.5">
              <li>
                <div className="px-4 py-1.5 flex items-center gap-2 cursor-pointer bg-surface-container-high border-l-2 border-primary text-text-primary">
                  <Cpu size={14} className="text-primary" />
                  <span className="font-body-sm">
                    {latestCandidate?.candidate_id ?? "No candidate yet"}
                  </span>
                </div>
              </li>
              <li>
                <div className="px-4 py-1.5 flex items-center gap-2 cursor-pointer hover:bg-surface-variant border-l-2 border-transparent text-text-secondary transition-colors">
                  <Network size={14} />
                  <span className="font-body-sm">Registered factors: {factors.factors.length}</span>
                </div>
              </li>
            </ul>
          </div>
          <div className="py-2">
            <h3 className="px-4 py-2 font-label-caps text-text-secondary">AI Models</h3>
            <ul className="space-y-0.5">
              <li>
                <div className="px-4 py-1.5 flex items-center gap-2 cursor-pointer hover:bg-surface-variant border-l-2 border-transparent text-text-secondary transition-colors">
                  <Sparkles size={14} className="text-info" />
                  <span className="font-body-sm">Sentiment_LLM.py</span>
                </div>
              </li>
              <li>
                <div className="px-4 py-1.5 flex items-center gap-2 cursor-pointer hover:bg-surface-variant border-l-2 border-transparent text-text-secondary transition-colors flex justify-between">
                  <div className="flex items-center gap-2">
                    <PackageX size={14} className="text-danger" />
                    <span className="font-body-sm text-danger opacity-80 line-through">RL_Agent_v1.py</span>
                  </div>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <div className="h-10 border-b border-border-subtle bg-surface-dim flex px-2 overflow-x-auto">
          <div className="flex border-r border-border-subtle group cursor-pointer bg-surface relative">
            <div className="absolute top-0 left-0 right-0 h-[2px] bg-primary"></div>
            <div className="px-4 py-2 flex items-center gap-2">
              <Cpu size={14} className="text-primary" />
              <span className="font-data-mono text-sm text-text-primary">Momentum_v4.py</span>
            </div>
            <div className="w-8 flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-surface-variant">
              <span className="font-label-caps text-[10px]">x</span>
            </div>
          </div>
          <div className="flex border-r border-border-subtle group cursor-pointer hover:bg-surface transition-colors opacity-70 hover:opacity-100">
            <div className="px-4 py-2 flex items-center gap-2">
              <Sparkles size={14} className="text-info" />
              <span className="font-data-mono text-sm text-text-secondary">Sentiment_LLM.py</span>
            </div>
          </div>
        </div>

        <div className="h-12 border-b border-border-subtle bg-surface px-4 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-4">
             <span className="text-text-primary font-data-mono text-sm">
               {latestCandidate?.artifact_type ?? "candidate preview"}
             </span>
             <span className="bg-accent-success/20 text-accent-success font-data-mono text-[10px] px-1.5 py-0.5 rounded border border-accent-success/30">PASS</span>
          </div>
          <div className="flex items-center gap-3">
             <button className="font-label-caps text-text-secondary hover:text-text-primary">Format</button>
             <button className="font-label-caps text-text-secondary hover:text-text-primary px-3 py-1 border border-border-subtle rounded hover:bg-surface-variant flex gap-2"><Target size={14} /> Analyze</button>
          </div>
        </div>

        <div className="flex-1 flex relative">
          <div className="flex-1 bg-zinc-950 font-data-mono text-[13px] leading-relaxed p-4 overflow-y-auto">
<pre className="text-zinc-300">
<span className="text-primary">import</span> pandas <span className="text-primary">as</span> pd
<span className="text-primary">import</span> numpy <span className="text-primary">as</span> np
<span className="text-primary">from</span> pipeline <span className="text-primary">import</span> Strategy, Universe

<span className="text-primary">class</span> <span className="text-info">MomentumAlpha</span>(<span className="text-accent-success">Strategy</span>):
    <span className="text-text-secondary">&quot;&quot;&quot;
    Cross-sectional momentum strategy measuring returns
    over multiple lookback windows (1M, 3M, 6M)
    &quot;&quot;&quot;</span>

    <span className="text-primary">def</span> <span className="text-info">__init__</span>(self):
        super().<span className="text-info">__init__</span>()
        self.lookbacks = [21, 63, 126]  <span className="text-text-secondary"># Trading days</span>
        self.universe = Universe.<span className="text-warning">SPX500_LIQUID</span>

    <span className="text-primary">def</span> <span className="text-info">compute_alpha</span>(self, data: pd.DataFrame) -&gt; pd.Series:
        <span className="text-text-secondary"># Assuming data has unstacked close prices</span>
        returns = data.pct_change()

        alpha_scores = pd.Series(0, index=returns.columns)

        <span className="text-primary">for</span> lb <span className="text-primary">in</span> self.lookbacks:
            <span className="text-text-secondary"># Momentum: skip recent 1M for mean-reversion effects</span>
            if lb == 21:
                mom = returns.rolling(lb).mean().iloc[-1]
            else:
                <span className="text-text-secondary"># Skip recent month for longer lookbacks</span>
                mom = returns.iloc[-lb:-21].mean()

            <span className="text-text-secondary"># Cross-sectional rank normalization</span>
            ranked_mom = mom.rank(pct=True) - 0.5
            alpha_scores += ranked_mom

        <span className="text-text-secondary"># Z-score standardization</span>
        final_alpha = (alpha_scores - alpha_scores.mean()) / alpha_scores.std()

        <span className="text-primary">return</span> final_alpha
</pre>
          </div>

          <div className="w-[30px] border-l border-border-subtle bg-surface-dim flex flex-col items-center py-4 gap-4 shrink-0">
             <div className="w-5 h-5 rounded hover:bg-surface-variant flex items-center justify-center cursor-pointer text-text-secondary rotate-180" style={{ writingMode: 'vertical-rl' }}>
               <span className="font-label-caps text-xs tracking-wider">OUTLINE</span>
             </div>
             <div className="flex-1 w-px bg-border-subtle"></div>
          </div>
        </div>

        <div className="h-48 border-t border-border-subtle bg-surface flex flex-col shrink-0">
           <div className="flex items-center gap-4 px-4 h-8 border-b border-border-subtle bg-surface-dim">
              <button className="font-label-caps text-primary border-b border-primary h-full">TERMINAL</button>
              <button className="font-label-caps text-text-secondary hover:text-text-primary h-full">LINTER</button>
              <button className="font-label-caps text-text-secondary hover:text-text-primary h-full">AI ASSISTANT</button>
           </div>
           <div className="flex-1 p-3 font-data-mono text-xs bg-[#0B1220] overflow-y-auto text-text-secondary">
             <div><span className="text-accent-success">agent_studio</span><span className="text-primary">@qcore</span><span className="text-text-primary">:~ $</span> python -m pytest tests/test_momentum.py</div>
             <div>============================= test session starts ==============================</div>
             <div>platform linux -- Python 3.10.12, pytest-7.4.0</div>
             <div>rootdir: /app/strategies</div>
             <div>collected 3 items</div>
             <br/>
             <div>tests/test_momentum.py <span className="text-accent-success">...                                              [100%]</span></div>
             <br/>
             <div className="text-accent-success">============================== 3 passed in 0.42s ===============================</div>
             <div className="mt-2"><span className="text-accent-success">agent_studio</span><span className="text-primary">@qcore</span><span className="text-text-primary">:~ $</span> <span className="w-2 h-4 inline-block bg-primary animate-pulse relative top-1"></span></div>
           </div>
        </div>
      </div>
    </div>
  );
}
