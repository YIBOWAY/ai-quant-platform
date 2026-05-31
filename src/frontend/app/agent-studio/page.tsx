import { Bot, Cpu, Network, ShieldCheck } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { AgentTaskForm } from "@/components/forms/AgentTaskForm";
import {
  getAgentCandidateDetail,
  getAgentCandidates,
  getAgentLlmConfig,
  getFactors,
} from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    title: "Agent Studio",
    inertNote: "Candidates are inert files until manual review.",
    candidatePool: "Candidate Pool",
    noCandidatesTitle: "No candidates",
    noCandidatesDesc: "Run an agent task to create a pending candidate.",
    registryContext: "Registry Context",
    registeredFactors: "Registered factors:",
    noCandidateSelected: "No candidate selected",
    sourcePreviewNote: "Source preview is read as text only. It is never imported or executed.",
    manualReviewRequired: "manual review required",
    sourcePreview: "Source Preview",
    sourcePreviewSub: "Latest candidate file read from disk as plain text only.",
    sourceNotLoadedTitle: "Source preview not loaded",
    sourceNotLoadedDesc:
      "Candidate source is shown only after loading a specific candidate detail as plain text.",
    auditTimeline: "Audit Timeline",
    auditEvents: "Audit Events",
    reviewEvents: "Review Events",
    noReviewRecords: "No review records yet.",
    auditPendingTitle: "Audit timeline pending",
    auditPendingDesc: "This candidate has no audit or review rows yet.",
  },
  zh: {
    title: "智能体工作室",
    inertNote: "候选在人工复核前仅为惰性文件。",
    candidatePool: "候选池",
    noCandidatesTitle: "暂无候选",
    noCandidatesDesc: "运行一个智能体任务以创建待处理的候选。",
    registryContext: "注册表上下文",
    registeredFactors: "已注册因子：",
    noCandidateSelected: "未选择候选",
    sourcePreviewNote: "源码预览仅以文本方式读取，绝不会被导入或执行。",
    manualReviewRequired: "需人工复核",
    sourcePreview: "源码预览",
    sourcePreviewSub: "最新候选文件仅以纯文本方式从磁盘读取。",
    sourceNotLoadedTitle: "源码预览未加载",
    sourceNotLoadedDesc: "仅在加载特定候选详情后，才会以纯文本方式显示候选源码。",
    auditTimeline: "审计时间线",
    auditEvents: "审计事件",
    reviewEvents: "复核事件",
    noReviewRecords: "暂无复核记录。",
    auditPendingTitle: "审计时间线待生成",
    auditPendingDesc: "该候选尚无审计或复核记录。",
  },
} as const;

export default async function AgentStudio() {
  const locale = await getServerLocale();
  const text = copy[locale];
  const [candidates, factors, llmConfig] = await Promise.all([
    getAgentCandidates(),
    getFactors(),
    getAgentLlmConfig(),
  ]);
  const latestCandidate = candidates.candidates[0];
  const latestDetail = latestCandidate
    ? await getAgentCandidateDetail(latestCandidate.candidate_id)
    : null;

  return (
    <div className="flex h-full w-full overflow-hidden bg-base">
      <aside className="flex h-full w-[300px] shrink-0 flex-col border-r border-border-subtle bg-surface">
        <div className="border-b border-border-subtle bg-surface-dim p-4">
          <h1 className="font-headline-lg text-text-primary">{text.title}</h1>
          <p className="mt-1 font-body-sm text-text-secondary">
            {text.inertNote}
          </p>
          <p className="mt-2 font-data-mono text-[10px] uppercase text-text-secondary">
            llm={llmConfig.provider} model={llmConfig.model ?? "none"} key=
            {llmConfig.has_api_key ? "set" : "unset"}
          </p>
        </div>
        <div className="flex-1 overflow-y-auto">
          <div className="border-b border-border-subtle p-4">
            <h3 className="mb-3 font-label-caps text-text-secondary">{text.candidatePool}</h3>
            {candidates.candidates.length ? (
              <ul className="space-y-2">
                {candidates.candidates.map((candidate) => (
                  <li
                    key={candidate.candidate_id}
                    className="rounded border border-border-subtle bg-surface-container-high p-3"
                  >
                    <div className="flex items-center gap-2">
                      <Cpu size={14} className="text-primary" />
                      <span className="truncate font-body-sm text-text-primary">
                        {candidate.candidate_id}
                      </span>
                    </div>
                    <div className="mt-2 font-data-mono text-[10px] uppercase text-text-secondary">
                      {candidate.artifact_type} · {candidate.status}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title={text.noCandidatesTitle}
                description={text.noCandidatesDesc}
              />
            )}
          </div>
          <div className="p-4">
            <h3 className="mb-3 font-label-caps text-text-secondary">{text.registryContext}</h3>
            <div className="flex items-center gap-2 rounded border border-border-subtle bg-surface-variant p-3">
              <Network size={14} className="text-info" />
              <span className="font-body-sm text-text-secondary">
                {text.registeredFactors} {factors.factors.length}
              </span>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-border-subtle bg-surface px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 font-data-mono text-sm text-text-primary">
                <Bot size={16} className="text-primary" />
                {latestCandidate?.candidate_id ?? text.noCandidateSelected}
              </div>
              <p className="mt-1 font-body-sm text-text-secondary">
                {text.sourcePreviewNote}
              </p>
            </div>
            <span className="flex items-center gap-1 rounded border border-warning/40 bg-warning/10 px-2 py-1 font-data-mono text-[10px] uppercase text-warning">
              <ShieldCheck size={12} /> {text.manualReviewRequired}
            </span>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <ErrorBanner
            messages={[
              candidates.apiError,
              factors.apiError,
              llmConfig.apiError,
              latestDetail?.apiError,
            ]}
          />
          <AgentTaskForm candidates={candidates.candidates} locale={locale} />
          {latestDetail?.source_preview ? (
            <section className="rounded border border-border-subtle bg-bg-surface p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h2 className="font-headline-lg text-text-primary">{text.sourcePreview}</h2>
                  <p className="mt-1 font-body-sm text-text-secondary">
                    {text.sourcePreviewSub}
                  </p>
                </div>
                <span className="font-data-mono text-[10px] uppercase text-text-secondary">
                  {latestDetail.candidate_id}
                </span>
              </div>
              <pre className="max-h-80 overflow-auto rounded border border-border-subtle bg-surface-muted p-3 font-code-sm text-text-primary">
                {latestDetail.source_preview}
              </pre>
            </section>
          ) : (
            <EmptyState
              title={text.sourceNotLoadedTitle}
              description={text.sourceNotLoadedDesc}
            />
          )}
          {latestDetail?.audit.length || latestDetail?.reviews.length ? (
            <section className="rounded border border-border-subtle bg-bg-surface p-4">
              <h2 className="font-headline-lg text-text-primary">{text.auditTimeline}</h2>
              <div className="mt-3 grid gap-4 lg:grid-cols-2">
                <div>
                  <h3 className="font-label-caps text-text-secondary">{text.auditEvents}</h3>
                  <ul className="mt-2 space-y-2 font-data-mono text-xs text-text-primary">
                    {(latestDetail?.audit ?? []).slice(0, 12).map((entry, index) => (
                      <li key={`audit-${index}`} className="rounded border border-border-subtle bg-surface-muted p-2">
                        {entry}
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3 className="font-label-caps text-text-secondary">{text.reviewEvents}</h3>
                  {(latestDetail?.reviews ?? []).length ? (
                    <ul className="mt-2 space-y-2 font-data-mono text-xs text-text-primary">
                      {latestDetail.reviews.slice(0, 12).map((entry, index) => (
                        <li key={`review-${index}`} className="rounded border border-border-subtle bg-surface-muted p-2">
                          {entry}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 font-body-sm text-text-secondary">{text.noReviewRecords}</p>
                  )}
                </div>
              </div>
            </section>
          ) : (
            <EmptyState
              title={text.auditPendingTitle}
              description={text.auditPendingDesc}
            />
          )}
        </div>
      </div>
    </div>
  );
}
