import { Bot, Cpu, Network, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { HermesParityBanner } from "@/components/HermesParityBanner";
import {
  Card,
  SectionTitle,
  StatusPill,
  TerminalSplitShell,
} from "@/components/ui/primitives";
import {
  getAgentCandidateDetail,
  getAgentCandidates,
  getFactors,
} from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Legacy Research Surface",
    title: "Agent Studio · Read-only",
    inertNote: "Transitional candidate inspection only. This page cannot create or review candidates.",
    safetyTitle: "Inspection only · no Scene-B authority",
    safetyBody:
      "Candidate source and audit records are displayed as text. Task submission and approve/reject controls are intentionally unavailable; the supported Scene-B workflow must pass HQA Gate 1–3.",
    openHermes: "Open Hermes workbench",
    candidatePool: "Candidate Pool",
    candidatePoolHint: "Pending files awaiting manual review.",
    noCandidatesTitle: "No candidates",
    noCandidatesDesc: "No candidate artifacts are available for read-only inspection.",
    candidateUnavailableTitle: "Candidate repository unavailable",
    candidateUnavailableDesc:
      "The candidate repository could not be read. This is not an empty candidate pool; restore repository access and retry.",
    registryContext: "Registry Context",
    registeredFactors: "Registered factors",
    selected: "Selected",
    noCandidateSelected: "No candidate selected",
    sourcePreviewNote: "Source preview is read as text only; the frontend never imports or executes it.",
    manualReviewRequired: "review outside this page",
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
    status: "status",
    type: "type",
  },
  zh: {
    eyebrow: "旧研究界面",
    title: "智能体工作室 · 只读",
    inertNote: "这里只保留过渡期候选检查，不能创建或审批候选。",
    safetyTitle: "仅供检查 · 不构成 Scene-B 权威",
    safetyBody:
      "这里只以文本展示候选源码和审计记录。任务提交与批准/拒绝控件已明确关闭；受支持的 Scene-B 流程必须经过 HQA Gate 1–3。",
    openHermes: "打开 Hermes 工作台",
    candidatePool: "候选池",
    candidatePoolHint: "等待人工复核的待处理文件。",
    noCandidatesTitle: "暂无候选",
    noCandidatesDesc: "当前没有可供只读检查的候选产物。",
    candidateUnavailableTitle: "候选仓库不可用",
    candidateUnavailableDesc:
      "当前无法读取候选仓库。这并不代表候选池为空；请恢复仓库访问后重试。",
    registryContext: "注册表上下文",
    registeredFactors: "已注册因子",
    selected: "已选择",
    noCandidateSelected: "未选择候选",
    sourcePreviewNote: "源码预览仅以文本方式读取，不会由前端导入或执行。",
    manualReviewRequired: "请在本页之外复核",
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
  const [candidates, factors] = await Promise.all([
    getAgentCandidates(),
    getFactors(),
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
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <section>
            <SectionTitle title={text.candidatePool} hint={text.candidatePoolHint} />
            {candidates.apiError ? (
              <div data-agent-candidates-unavailable>
                <EmptyState
                  title={text.candidateUnavailableTitle}
                  description={text.candidateUnavailableDesc}
                />
              </div>
            ) : candidates.candidates.length ? (
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
        <div className="border-b border-border-subtle px-4 py-3">
          <HermesParityBanner locale={locale} />
        </div>
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
              latestDetail?.apiError,
            ]}
          />

          <Card tone="warning" className="flex items-start gap-3">
            <ShieldCheck size={18} className="mt-0.5 shrink-0 text-warning" />
            <div>
              <h2 className="font-label-caps text-warning">{text.safetyTitle}</h2>
              <p className="mt-1 font-body-sm text-text-secondary">{text.safetyBody}</p>
              <Link
                href={`/${locale}/hermes`}
                className="mt-3 inline-flex rounded-lg border border-info/40 bg-info/10 px-3 py-2 font-data-mono text-xs text-info transition-colors hover:bg-info/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
              >
                {text.openHermes}
              </Link>
            </div>
          </Card>

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
