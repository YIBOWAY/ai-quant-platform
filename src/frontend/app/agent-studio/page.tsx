import { Bot, Cpu, Network, ShieldCheck } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { AgentTaskForm } from "@/components/forms/AgentTaskForm";
import {
  Card,
  SectionTitle,
  StatusPill,
  TerminalSplitShell,
} from "@/components/ui/primitives";
import {
  getAgentCandidateDetail,
  getAgentCandidates,
  getAgentLlmConfig,
  getFactors,
} from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Research Agents",
    title: "Agent Studio",
    inertNote: "Candidates are inert files until manual review.",
    safetyTitle: "Plain-text by default · explicit CLI load only",
    safetyBody:
      "Agent candidates are written to disk as plain text. Approval only records manual review; candidate factor code is loaded only by the explicit CLI flag and still passes backend safety checks before registration.",
    candidatePool: "Candidate Pool",
    candidatePoolHint: "Pending files awaiting manual review.",
    noCandidatesTitle: "No candidates",
    noCandidatesDesc: "Run an agent task to create a pending candidate.",
    registryContext: "Registry Context",
    registeredFactors: "Registered factors",
    selected: "Selected",
    noCandidateSelected: "No candidate selected",
    sourcePreviewNote: "Source preview is read as text only; the frontend never imports or executes it.",
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
    llm: "LLM",
    model: "Model",
    apiKey: "API key",
    keySet: "set",
    keyUnset: "unset",
    none: "none",
    status: "status",
    type: "type",
  },
  zh: {
    eyebrow: "研究智能体",
    title: "智能体工作室",
    inertNote: "候选在人工复核前仅为惰性文件。",
    safetyTitle: "默认纯文本 · 仅显式 CLI 加载",
    safetyBody:
      "智能体候选以纯文本写入磁盘。批准只记录人工复核；候选因子代码只有在显式 CLI 参数开启时才会加载，并且注册前仍会通过后端安全检查。",
    candidatePool: "候选池",
    candidatePoolHint: "等待人工复核的待处理文件。",
    noCandidatesTitle: "暂无候选",
    noCandidatesDesc: "运行一个智能体任务以创建待处理的候选。",
    registryContext: "注册表上下文",
    registeredFactors: "已注册因子",
    selected: "已选择",
    noCandidateSelected: "未选择候选",
    sourcePreviewNote: "源码预览仅以文本方式读取，不会由前端导入或执行。",
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
    llm: "LLM",
    model: "模型",
    apiKey: "API 密钥",
    keySet: "已设置",
    keyUnset: "未设置",
    none: "无",
    status: "状态",
    type: "类型",
  },
} as const;

type Tone = "neutral" | "success" | "warning" | "danger" | "info";

function statusTone(status: string | null | undefined): Tone {
  const normalized = (status ?? "").toLowerCase();
  if (normalized === "approved") return "success";
  if (normalized === "rejected") return "danger";
  if (normalized === "pending") return "warning";
  return "neutral";
}

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
    <TerminalSplitShell
      sidebar={
        <>
        <div className="border-b border-border-subtle bg-surface-dim p-4">
          <p className="font-label-caps uppercase text-text-secondary">{text.eyebrow}</p>
          <div className="mt-1 flex items-center gap-2">
            <Bot size={18} className="text-accent-success" />
            <h1 className="font-headline-lg text-text-primary">{text.title}</h1>
          </div>
          <p className="mt-2 font-body-sm text-text-secondary">{text.inertNote}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <StatusPill label={text.llm} value={llmConfig.provider} tone="info" />
            <StatusPill label={text.model} value={llmConfig.model ?? text.none} tone="neutral" />
            <StatusPill
              label={text.apiKey}
              value={llmConfig.has_api_key ? text.keySet : text.keyUnset}
              tone={llmConfig.has_api_key ? "success" : "neutral"}
            />
          </div>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <section>
            <SectionTitle title={text.candidatePool} hint={text.candidatePoolHint} />
            {candidates.candidates.length ? (
              <ul className="space-y-2">
                {candidates.candidates.map((candidate) => (
                  <li
                    key={candidate.candidate_id}
                    className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3"
                  >
                    <div className="flex items-center gap-2">
                      <Cpu size={14} className="shrink-0 text-text-secondary" />
                      <span className="truncate font-data-mono text-xs text-text-primary">
                        {candidate.candidate_id}
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <StatusPill
                        label={text.type}
                        value={candidate.artifact_type ?? "—"}
                        tone="neutral"
                      />
                      <StatusPill
                        label={text.status}
                        value={candidate.status ?? "—"}
                        tone={statusTone(candidate.status)}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title={text.noCandidatesTitle} description={text.noCandidatesDesc} />
            )}
          </section>
          <section>
            <SectionTitle title={text.registryContext} />
            <Card tone="info" padded={false} className="flex items-center gap-2 p-3">
              <Network size={14} className="shrink-0 text-info" />
              <span className="flex-1 font-body-sm text-text-secondary">
                {text.registeredFactors}
              </span>
              <span className="font-data-mono text-sm font-bold text-info">
                {factors.factors.length}
              </span>
            </Card>
          </section>
        </div>
        </>
      }
      sidebarClassName="lg:w-[300px]"
      mainClassName="gap-0 p-0"
    >

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-border-subtle bg-bg-surface px-4 py-3">
          <div className="flex min-w-0 items-center gap-2 font-data-mono text-sm text-text-primary">
            <span className="font-label-caps text-text-secondary">{text.selected}</span>
            <span className="truncate">
              {latestCandidate?.candidate_id ?? text.noCandidateSelected}
            </span>
          </div>
          <span className="flex shrink-0 items-center gap-1 rounded-lg border border-warning/40 bg-warning/10 px-2 py-1 font-data-mono text-[10px] uppercase text-warning">
            <ShieldCheck size={12} /> {text.manualReviewRequired}
          </span>
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

          <Card tone="warning" className="flex items-start gap-3">
            <ShieldCheck size={18} className="mt-0.5 shrink-0 text-warning" />
            <div>
              <h2 className="font-label-caps text-warning">{text.safetyTitle}</h2>
              <p className="mt-1 font-body-sm text-text-secondary">{text.safetyBody}</p>
            </div>
          </Card>

          <AgentTaskForm candidates={candidates.candidates} locale={locale} />

          {latestDetail?.source_preview ? (
            <Card>
              <SectionTitle
                title={text.sourcePreview}
                hint={text.sourcePreviewSub}
                right={
                  <span className="font-data-mono text-[10px] uppercase text-text-secondary">
                    {latestDetail.candidate_id}
                  </span>
                }
              />
              <pre className="max-h-80 overflow-auto rounded-lg border border-border-subtle bg-bg-surface-muted p-3 font-code-sm text-text-primary">
                {latestDetail.source_preview}
              </pre>
            </Card>
          ) : (
            <EmptyState
              title={text.sourceNotLoadedTitle}
              description={text.sourceNotLoadedDesc}
            />
          )}

          {latestDetail?.audit.length || latestDetail?.reviews.length ? (
            <Card>
              <SectionTitle title={text.auditTimeline} />
              <div className="grid gap-4 lg:grid-cols-2">
                <div>
                  <h3 className="font-label-caps text-text-secondary">{text.auditEvents}</h3>
                  <ul className="mt-2 space-y-2 font-data-mono text-xs text-text-primary">
                    {(latestDetail?.audit ?? []).slice(0, 12).map((entry, index) => (
                      <li
                        key={`audit-${index}`}
                        className="rounded-lg border border-border-subtle bg-bg-surface-muted p-2"
                      >
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
                        <li
                          key={`review-${index}`}
                          className="rounded-lg border border-border-subtle bg-bg-surface-muted p-2"
                        >
                          {entry}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 font-body-sm text-text-secondary">{text.noReviewRecords}</p>
                  )}
                </div>
              </div>
            </Card>
          ) : (
            <EmptyState
              title={text.auditPendingTitle}
              description={text.auditPendingDesc}
            />
          )}
        </div>
      </div>
    </TerminalSplitShell>
  );
}
