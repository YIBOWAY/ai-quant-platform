import { Cpu, Sparkles } from "lucide-react";
import { ArtifactShelf } from "@/components/hermes";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { SectionTitle, StatusPill } from "@/components/ui/primitives";
import { getAgentCandidates, getHermesArtifacts } from "@/lib/api";
import { getServerLocale } from "@/lib/serverLocale";

const copy = {
  en: {
    eyebrow: "Research",
    title: "Hermes workbench",
    subtitle: "Artifact-first read-only research workbench. Submit remains disabled.",
    candidates: "Candidates",
    candidatesHint: "Read-only context from /api/agent/candidates.",
    noCandidatesTitle: "No candidates yet",
    noCandidatesDesc: "Agent Studio can produce pending candidates; Hermes only displays them.",
    candidatesLoadFailedTitle: "Candidates unavailable",
    candidatesLoadFailedDesc: "Could not load agent candidates. Retry after the backend recovers.",
    type: "type",
    status: "status",
  },
  zh: {
    eyebrow: "研究",
    title: "Hermes 工作台",
    subtitle: "以产物为先的只读研究工作台。提交仍保持禁用。",
    candidates: "候选",
    candidatesHint: "来自 /api/agent/candidates 的只读上下文。",
    noCandidatesTitle: "暂无候选",
    noCandidatesDesc: "可在智能体工作室生成待处理候选；Hermes 仅展示。",
    candidatesLoadFailedTitle: "候选不可用",
    candidatesLoadFailedDesc: "无法加载智能体候选。请在后端恢复后重试。",
    type: "类型",
    status: "状态",
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

export default async function HermesWorkbenchPage() {
  const locale = await getServerLocale();
  const text = copy[locale];
  const [candidates, artifacts] = await Promise.all([
    getAgentCandidates(),
    getHermesArtifacts(),
  ]);

  return (
    <div className="flex min-h-0 w-full flex-col gap-4 lg:flex-row">
      <aside
        className="flex w-full shrink-0 flex-col rounded-lg border border-border-subtle bg-bg-surface lg:w-[var(--spacing-rail-width)] lg:min-w-[208px] lg:max-w-[300px]"
        data-hermes-rail="true"
      >
        <div className="border-b border-border-subtle p-4">
          <SectionTitle title={text.candidates} hint={text.candidatesHint} />
        </div>
        <div className="space-y-2 p-3">
          <ErrorBanner locale={locale} messages={[candidates.apiError]} />
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
          ) : candidates.apiError ? (
            <EmptyState
              title={text.candidatesLoadFailedTitle}
              description={text.candidatesLoadFailedDesc}
            />
          ) : (
            <EmptyState title={text.noCandidatesTitle} description={text.noCandidatesDesc} />
          )}
        </div>
      </aside>

      <div className="min-w-0 flex-1 space-y-4">
        <header className="space-y-2">
          <p className="font-label-caps uppercase text-text-secondary">{text.eyebrow}</p>
          <div className="flex items-center gap-2">
            <Sparkles size={18} className="text-[var(--color-hermes)]" />
            <h1 className="font-headline-lg text-text-primary">{text.title}</h1>
          </div>
          <p className="font-body-sm text-text-secondary">{text.subtitle}</p>
        </header>

        <ArtifactShelf envelope={artifacts} locale={locale} />
      </div>
    </div>
  );
}
