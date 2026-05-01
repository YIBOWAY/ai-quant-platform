import { Clock, Database, FileJson, SlidersHorizontal } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ExperimentTabs } from "@/components/forms/ExperimentTabs";
import { getBacktests, getExperiments } from "@/lib/api";

export default async function Experiments() {
  const [experiments, backtests] = await Promise.all([getExperiments(), getBacktests()]);
  const latestExperiment = experiments.experiments[0];

  return (
    <div className="flex h-full w-full overflow-hidden bg-base">
      <aside className="flex h-full w-[320px] shrink-0 flex-col border-r border-border-subtle bg-surface">
        <div className="border-b border-border-subtle bg-surface-dim p-4">
          <h2 className="font-headline-lg text-text-primary">Experiments</h2>
          <p className="mt-1 font-body-sm text-text-secondary">Local experiment directories.</p>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {experiments.experiments.length ? (
            <ul className="space-y-3">
              {experiments.experiments.map((experiment) => (
                <li
                  key={experiment.id}
                  className="rounded border border-border-subtle bg-surface-container p-3"
                >
                  <div className="font-data-mono text-primary">{experiment.id}</div>
                  <div className="mt-1 truncate font-body-sm text-text-secondary">
                    {experiment.path}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No experiments"
              description="Run an experiment to populate this list."
            />
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col overflow-hidden bg-base">
        <div className="border-b border-border-subtle bg-surface-dim px-6 py-5">
          <div className="flex items-start justify-between">
            <div>
              <div className="mb-1 flex items-center gap-3">
                <h1 className="font-headline-xl text-text-primary">Experiment Results</h1>
                <span className="rounded border border-border-subtle bg-surface-muted px-2 py-0.5 font-data-mono text-code-sm text-text-secondary">
                  {experiments.experiments.length} local
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-4 font-body-sm text-text-secondary">
                <span className="flex items-center gap-1">
                  <Clock size={14} /> latest: {latestExperiment?.id ?? "--"}
                </span>
                <span className="flex items-center gap-1">
                  <Database size={14} /> /api/experiments
                </span>
                <span className="flex items-center gap-1">
                  <SlidersHorizontal size={14} /> {backtests.backtests.length} backtests
                </span>
              </div>
            </div>
          </div>
          <div className="mt-6 flex items-center gap-6 border-b border-border-subtle">
            <span className="border-b-2 border-primary pb-3 font-body-sm font-medium text-primary">
              Overview
            </span>
            <span className="flex items-center gap-1 pb-3 font-body-sm text-text-secondary">
              <FileJson size={14} /> Agent summary
            </span>
          </div>
        </div>

        <div className="grid flex-1 grid-cols-1 gap-4 overflow-y-auto p-6 lg:grid-cols-2">
          <div className="lg:col-span-2">
            <ErrorBanner messages={[experiments.apiError, backtests.apiError]} />
          </div>
          <ExperimentTabs />
          <EmptyState
            title="Sweep heatmap unavailable"
            description="No parameter sweep matrix is available from the current API response."
          />
          <EmptyState
            title="Walk-forward folds unavailable"
            description="Fold details are shown only after an experiment detail is selected."
          />
          <EmptyState
            title="Run comparison unavailable"
            description="Run comparison needs structured experiment run metadata."
          />
          <EmptyState
            title="Agent summary unavailable"
            description="agent_summary.json will be displayed when present in the experiment directory."
          />
        </div>
      </section>
    </div>
  );
}
