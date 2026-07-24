import { Card } from "@/components/ui/primitives";
import type { AgentCandidatesResponse } from "@/lib/api";
import type { Locale } from "@/lib/locale";

export type CandidateApprovalListStateProps = {
  candidates: AgentCandidatesResponse;
  locale: Locale;
};

/**
 * Renders candidate-source states that must not be confused with list data.
 * A null result means the caller has actual candidate rows to render.
 */
export function CandidateApprovalListState({
  candidates,
  locale,
}: CandidateApprovalListStateProps) {
  const isZh = locale === "zh";
  if (candidates.apiError) {
    return (
      <div data-hermes-candidates-unavailable>
        <Card className="border-danger/40 bg-danger/5">
          <p className="font-body-sm font-semibold text-danger">
            {isZh ? "候选列表不可用" : "Candidate list unavailable"}
          </p>
          <p className="mt-1 font-body-sm text-text-secondary">
            {isZh
              ? "当前无法判断是否存在待审批项；这不是空列表。"
              : "Approval availability cannot be determined; this is not an empty list."}
          </p>
          <p className="mt-2 break-words font-data-mono text-xs text-danger">
            {candidates.apiError}
          </p>
        </Card>
      </div>
    );
  }

  if (candidates.candidates.length > 0) return null;
  return (
    <div data-hermes-candidates-empty>
      <Card className="bg-[var(--color-stream-surface)]">
        <p className="font-body-sm font-semibold text-text-primary">
          {isZh ? "暂无研究审批项" : "No research approval items"}
        </p>
        <p className="mt-1 font-body-sm text-text-secondary">
          {isZh
            ? "候选 API 已成功返回空列表。本页不提供批准或拒绝。"
            : "The candidate API returned an empty list. This page cannot approve or reject."}
        </p>
      </Card>
    </div>
  );
}
