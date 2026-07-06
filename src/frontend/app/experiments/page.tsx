import { Beaker } from "lucide-react";
import Link from "next/link";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { ExperimentRunForm } from "@/components/forms/ExperimentRunForm";
import { ExperimentTabs } from "@/components/forms/ExperimentTabs";
import {
  Card,
  MetricStat,
  PageHeader,
  StatusPill,
  TerminalSplitShell,
} from "@/components/ui/primitives";
import { getBacktests, getExperimentDetail, getExperiments } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    sidebarTitle: "Experiments",
    sidebarSubtitle: "Local experiment directories. Click one to inspect it.",
    best: "best",
    latestChip: "latest",
    noExperimentsTitle: "No experiments",
    noExperimentsDescription: "Run an experiment to populate this list.",
    eyebrow: "Parameter sweeps",
    resultsTitle: "Experiment Results",
    resultsSubtitle:
      "Parameter sweeps over the selected OHLCV source for comparing lookback and Top N settings. Read-only research, no live trading.",
    localBadge: "local",
    mLocal: "Local runs",
    mLatest: "Selected",
    mBest: "Best run",
    mBacktests: "Backtests",
    sourceLabel: "Source",
  },
  zh: {
    sidebarTitle: "实验管理",
    sidebarSubtitle: "本地实验目录，点击查看详情。",
    best: "最佳",
    latestChip: "最新",
    noExperimentsTitle: "暂无实验",
    noExperimentsDescription: "运行一个实验以填充此列表。",
    eyebrow: "参数扫描",
    resultsTitle: "实验结果",
    resultsSubtitle: "使用所选 OHLCV 数据源做参数扫描，对比 lookback 与 Top N 设置。仅供研究查阅，不涉及实盘交易。",
    localBadge: "本地",
    mLocal: "本地运行",
    mLatest: "当前选中",
    mBest: "最佳运行",
    mBacktests: "回测",
    sourceLabel: "数据源",
  },
} as const;

export default async function Experiments({
  searchParams,
}: {
  searchParams?: Promise<{ experiment?: string }>;
}) {
  const locale = await getServerLocale();
  const text = copy[locale];
  const requestedId = (await searchParams)?.experiment;
  const [experiments, backtests] = await Promise.all([getExperiments(), getBacktests()]);
  const latestExperiment = experiments.experiments[0];
  const selectedExperiment =
    experiments.experiments.find((experiment) => experiment.id === requestedId) ?? latestExperiment;
  const experimentDetail = selectedExperiment
    ? await getExperimentDetail(selectedExperiment.id)
    : null;

  return (
    <TerminalSplitShell
      sidebar={
        <>
        <div className="border-b border-border-subtle bg-surface-dim p-4">
          <h2 className="font-headline-lg text-text-primary">{text.sidebarTitle}</h2>
          <p className="mt-1 font-body-sm text-text-secondary">{text.sidebarSubtitle}</p>
        </div>
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
          <ExperimentRunForm locale={locale} />
          {experiments.experiments.length ? (
            <ul className="flex flex-col gap-2">
              {experiments.experiments.map((experiment) => {
                const isLatest = experiment.id === latestExperiment?.id;
                const isSelected = experiment.id === selectedExperiment?.id;
                return (
                  <li key={experiment.id}>
                    <Link
                      aria-current={isSelected ? "true" : undefined}
                      className="block rounded-lg transition-opacity hover:opacity-90"
                      href={`?experiment=${encodeURIComponent(experiment.id)}`}
                    >
                      <Card
                        padded={false}
                        tone={isSelected ? "success" : "neutral"}
                        className="p-3"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="break-all font-data-mono text-xs text-text-primary">
                            {experiment.id}
                          </div>
                          {isLatest ? (
                            <span className="shrink-0 rounded-lg border border-info/40 bg-info/10 px-1.5 py-0.5 font-data-mono text-[10px] uppercase text-info">
                              {text.latestChip}
                            </span>
                          ) : null}
                        </div>
                        <div className="mt-2 font-data-mono text-[11px] text-text-secondary">
                          {text.best}: {experiment.best_run_id ?? "--"}
                        </div>
                        <div className="mt-1 truncate font-body-sm text-text-secondary" title={experiment.path}>
                          {experiment.path}
                        </div>
                      </Card>
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState
              title={text.noExperimentsTitle}
              description={text.noExperimentsDescription}
            />
          )}
        </div>
        </>
      }
      sidebarClassName="lg:w-[320px]"
      mainClassName="gap-0 p-0"
    >

        <div className="border-b border-border-subtle bg-surface-dim px-6 py-5">
          <PageHeader
            eyebrow={text.eyebrow}
            title={text.resultsTitle}
            subtitle={text.resultsSubtitle}
            icon={<Beaker className="text-accent-success" size={22} />}
            actions={
              <StatusPill
                label={text.localBadge}
                value={experiments.experiments.length}
                tone="info"
              />
            }
          />
          <div className="mt-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
            <MetricStat label={text.mLocal} value={experiments.experiments.length} />
            <MetricStat
              label={text.mLatest}
              value={<span className="break-all">{selectedExperiment?.id ?? "--"}</span>}
            />
            <MetricStat
              label={text.mBest}
              value={<span className="break-all">{selectedExperiment?.best_run_id ?? "--"}</span>}
              tone={selectedExperiment?.best_run_id ? "success" : "neutral"}
            />
            <MetricStat label={text.mBacktests} value={backtests.backtests.length} />
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-6">
          <ErrorBanner
            messages={[experiments.apiError, backtests.apiError, experimentDetail?.apiError]}
          />
          <ExperimentTabs detail={experimentDetail} experiment={selectedExperiment} locale={locale} />
        </div>
    </TerminalSplitShell>
  );
}
