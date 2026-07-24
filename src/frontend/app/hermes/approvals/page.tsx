import { CandidateApprovalWorkspace } from "@/components/hermes/approvals/CandidateApprovalWorkspace";
import { Card } from "@/components/ui/primitives";
import { getAgentCandidateDetail, getAgentCandidates, getFactors } from "@/lib/api";
import { resolveCandidateSelection } from "@/lib/hermes/candidateSelection";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { buildPromotedRegistryContext } from "@/lib/hermes/promotedRegistry";
import { getServerLocale } from "@/lib/serverLocale";

/**
 * Hermes Approvals: digest-aware candidate evidence only.
 *
 * The generic platform review endpoint is not the supported Scene-B entry
 * point. Browser mutations stay hard-disabled until an HQA Gate 1 exact
 * binding and a same-origin authenticated/CSRF-protected BFF exist.
 */
type HermesApprovalsPageProps = {
  searchParams?: Promise<{ candidate?: string | string[] }>;
};

export default async function HermesApprovalsPage({
  searchParams,
}: HermesApprovalsPageProps) {
  const locale = await getServerLocale();
  const workbench = hermesWorkbenchCopy(locale);
  const [candidates, factors] = await Promise.all([
    getAgentCandidates(),
    getFactors(),
  ]);
  const registry = buildPromotedRegistryContext(factors);
  const requestedCandidate = (await searchParams)?.candidate;
  const selectedCandidateId = resolveCandidateSelection(
    candidates.candidates,
    requestedCandidate,
  );
  const detail = selectedCandidateId
    ? await getAgentCandidateDetail(selectedCandidateId)
    : null;
  const isZh = locale === "zh";

  const text = {
    gate2Note: isZh
      ? "选择任意候选，查看源码、审计、复核与摘要证据；网页不会提交 Gate 2。"
      : "Choose any candidate to inspect source, audit, review, and digest evidence; the browser never submits Gate 2.",
    writeClosedTitle: isZh
      ? "网页审批写端已安全关闭"
      : "Browser approval mutations are safely disabled",
    writeClosedBody: isZh
      ? "当前网页无法证明 HQA Gate 1 exact binding，也尚未具备同源会话与 CSRF 边界。请继续通过受支持的 HQA Scene-B CLI 完成人工 CAS；平台通用 review API 不能单独代表 Scene-B Gate 2。"
      : "The browser cannot yet prove the HQA Gate 1 exact binding and does not have the required same-origin session and CSRF boundary. Use the supported HQA Scene-B CLI for human CAS; the generic platform review API alone is not Scene-B Gate 2.",
  };

  return (
    <section
      aria-labelledby="hermes-approvals-title"
      className="space-y-4"
      data-hermes-approvals
    >
      <header className="space-y-2">
        <p className="font-label-caps uppercase text-text-secondary">
          {isZh ? "待我确认" : "Approvals"}
        </p>
        <h1 className="font-headline-lg text-text-primary" id="hermes-approvals-title">
          {isZh ? "待我确认" : "Approvals"}
        </h1>
        <p className="font-body-sm text-text-secondary">{text.gate2Note}</p>
      </header>

      <Card className="border-warning/30 bg-warning/5" tone="warning">
        <p className="font-body-sm font-semibold text-text-primary">
          {text.writeClosedTitle}
        </p>
        <p className="mt-1 font-body-sm text-text-secondary">
          {text.writeClosedBody}
        </p>
      </Card>

      <h2 className="font-label-caps text-text-secondary">
        {workbench.labels.researchApproval}
      </h2>

      <CandidateApprovalWorkspace
        candidates={candidates}
        detail={detail}
        locale={locale}
        registry={registry}
        selectedCandidateId={selectedCandidateId}
      />
    </section>
  );
}
