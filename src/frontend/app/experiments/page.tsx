import { Clock, Database, FileJson, SlidersHorizontal } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ExperimentTabs } from "@/components/forms/ExperimentTabs";
import { getBacktests, getExperimentDetail, getExperiments } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    sidebarTitle: "Experiments",
    sidebarSubtitle: "Local experiment directories.",
    best: "best",
    noExperimentsTitle: "No experiments",
    noExperimentsDescription: "Run an experiment to populate this list.",
    resultsTitle: "Experiment Results",
    localBadge: "local",
    latest: "latest",
    backtestsLabel: "backtests",
    tabSweep: "Sweep heatmap",
    tabFolds: "Walk-forward folds",
    tabRuns: "Run comparison",
    tabSummary: "Agent summary",
  },
  zh: {
    sidebarTitle: "实验管理",
    sidebarSubtitle: "本地实验目录。",
    best: "最佳",
    noExperimentsTitle: "暂无实验",
    noExperimentsDescription: "运行一个实验以填充此列表。",
    resultsTitle: "实验结果",
    localBadge: "本地",
    latest: "最新",
    backtestsLabel: "回测",
    tabSweep: "参数扫描热力图",
    tabFolds: "滚动验证折",
    tabRuns: "运行对比",
    tabSummary: "代理摘要",
  },
} as const;

export default async function Experiments() {
  const locale = await getServerLocale();
  const text = copy[locale];
  const [experiments, backtests] = await Promise.all([getExperiments(), getBacktests()]);
  const latestExperiment = experiments.experiments[0];
  const experimentDetail = latestExperiment
    ? await getExperimentDetail(latestExperiment.id)
    : null;

  return (
    <div className="flex h-full w-full overflow-hidden bg-base">
      <aside className="flex h-full w-[320px] shrink-0 flex-col border-r border-border-subtle bg-surface">
        <div className="border-b border-border-subtle bg-surface-dim p-4">
          <h2 className="font-headline-lg text-text-primary">{text.sidebarTitle}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">{text.sidebarSubtitle}</p>
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
                  <div className="mt-2 font-data-mono text-[11px] text-text-secondary">
                    {text.best}: {experiment.best_run_id ?? "--"}
                  </div>
                  <div className="mt-1 truncate font-body-sm text-text-secondary">
                    {experiment.path}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title={text.noExperimentsTitle}
              description={text.noExperimentsDescription}
            />
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col overflow-hidden bg-base">
        <div className="border-b border-border-subtle bg-surface-dim px-6 py-5">
          <div className="flex items-start justify-between">
            <div>
              <div className="mb-1 flex items-center gap-3">
                <h1 className="font-headline-xl text-text-primary">{text.resultsTitle}</h1>
                <span className="rounded border border-border-subtle bg-surface-muted px-2 py-0.5 font-data-mono text-code-sm text-text-secondary">
                  {experiments.experiments.length} {text.localBadge}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-4 font-body-sm text-text-secondary">
                <span className="flex items-center gap-1">
                  <Clock size={14} /> {text.latest}: {latestExperiment?.id ?? "--"}
                </span>
                <span className="flex items-center gap-1">
                  <FileJson size={14} /> {text.best}: {latestExperiment?.best_run_id ?? "--"}
                </span>
                <span className="flex items-center gap-1">
                  <Database size={14} /> /api/experiments
                </span>
                <span className="flex items-center gap-1">
                  <SlidersHorizontal size={14} /> {backtests.backtests.length} {text.backtestsLabel}
                </span>
              </div>
            </div>
          </div>
          <div className="mt-6 flex items-center gap-6 border-b border-border-subtle">
            <span className="border-b-2 border-primary pb-3 font-body-sm font-medium text-primary">
              {text.tabSweep}
            </span>
            <span className="pb-3 font-body-sm text-text-secondary">{text.tabFolds}</span>
            <span className="pb-3 font-body-sm text-text-secondary">{text.tabRuns}</span>
            <span className="flex items-center gap-1 pb-3 font-body-sm text-text-secondary">
              <FileJson size={14} /> {text.tabSummary}
            </span>
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-6">
          <ErrorBanner
            messages={[experiments.apiError, backtests.apiError, experimentDetail?.apiError]}
          />
          <ExperimentTabs detail={experimentDetail} experiment={latestExperiment} locale={locale} />
        </div>
      </section>
    </div>
  );
}
