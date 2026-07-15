import { CandidateApprovalListState } from "@/components/hermes/approvals/CandidateApprovalListState";
import { Card, StatusPill } from "@/components/ui/primitives";
import { getAgentCandidates } from "@/lib/api";
import {
  asCandidateApprovalBinding,
  candidateBindingTone,
  candidateDigestPresentation,
} from "@/lib/hermes/candidatePresentation";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { getServerLocale } from "@/lib/serverLocale";

/**
 * Hermes Approvals: digest-aware candidate evidence only.
 *
 * The generic platform review endpoint is not the supported Scene-B entry
 * point. Browser mutations stay hard-disabled until an HQA Gate 1 exact
 * binding and a same-origin authenticated/CSRF-protected BFF exist.
 */
export default async function HermesApprovalsPage() {
  const locale = await getServerLocale();
  const workbench = hermesWorkbenchCopy(locale);
  const candidates = await getAgentCandidates();
  const isZh = locale === "zh";

  const text = {
    binding: isZh ? "绑定" : "binding",
    integrity: isZh ? "完整性" : "integrity",
    status: isZh ? "状态" : "status",
    migrationEvidence: isZh ? "迁移证据，不能审批" : "Migration evidence only — cannot approve",
    corrupt: isZh ? "完整性失败" : "Integrity failed",
    noPreview: isZh ? "无源码预览" : "No source preview",
    gate2Note: isZh
      ? "本页只展示研究审批项的完整性、状态与摘要；不会从网页提交 Gate 2。"
      : "This page shows research-approval integrity, state, and digest evidence only; it does not submit Gate 2 from the browser.",
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

      {candidates.apiError || candidates.candidates.length === 0 ? (
        <CandidateApprovalListState candidates={candidates} locale={locale} />
      ) : (
        <ul className="space-y-3">
          {candidates.candidates.map((candidate) => {
            const binding = asCandidateApprovalBinding(candidate.approval_binding);
            const digest = candidateDigestPresentation(candidate);
            return (
              <li key={candidate.candidate_id}>
                <article
                  className="rounded-lg border border-border-subtle bg-[var(--color-stream-surface)] p-4"
                  data-hermes-approval-id={candidate.candidate_id}
                  data-hermes-approval-binding={binding ?? "null"}
                  data-hermes-integrity={candidate.integrity_state ?? "unknown"}
                  data-hermes-approval-enabled={
                    candidate.approval_enabled === true ? "true" : "false"
                  }
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="break-all font-data-mono text-sm font-semibold text-text-primary">
                        {candidate.candidate_id}
                      </h3>
                      {candidate.goal ? (
                        <p className="mt-2 font-body-sm text-text-secondary">
                          {candidate.goal}
                        </p>
                      ) : null}
                      {candidate.artifact_type ? (
                        <p className="mt-1 font-data-mono text-xs text-text-secondary">
                          {candidate.artifact_type}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      <StatusPill
                        label={text.binding}
                        value={binding ?? "—"}
                        tone={candidateBindingTone(binding)}
                      />
                      {candidate.integrity_state ? (
                        <StatusPill
                          label={text.integrity}
                          value={candidate.integrity_state}
                          tone={
                            candidate.integrity_state === "verified"
                              ? "success"
                              : candidate.integrity_state === "migration_required"
                                ? "warning"
                                : "danger"
                          }
                        />
                      ) : null}
                      {candidate.status ? (
                        <StatusPill
                          label={text.status}
                          value={candidate.status}
                          tone={candidateBindingTone(
                            asCandidateApprovalBinding(candidate.status),
                          )}
                        />
                      ) : null}
                    </div>
                  </div>

                  {digest.kind === "authoritative" ? (
                    <p className="mt-3 font-data-mono text-[10px] text-text-secondary">
                      <span className="opacity-70">manifest_digest </span>
                      <code className="break-all">{digest.digest}</code>
                    </p>
                  ) : null}

                  {digest.kind === "migration_evidence" ? (
                    <div className="mt-3 rounded-lg border border-warning/40 bg-warning/5 p-3">
                      <p className="font-body-sm font-semibold text-warning">
                        {text.migrationEvidence}
                      </p>
                      <p className="mt-1 break-all font-data-mono text-[10px] text-text-secondary">
                        observed_manifest_digest{" "}
                        <code className="break-all">{digest.digest}</code>
                      </p>
                    </div>
                  ) : null}

                  {digest.kind === "corrupt" ? (
                    <div className="mt-3 rounded-lg border border-danger/40 bg-danger/5 p-3">
                      <p className="font-body-sm font-semibold text-danger">
                        {text.corrupt}
                      </p>
                      <p className="mt-1 font-data-mono text-xs text-danger">
                        {digest.errorCode}
                      </p>
                      <p className="mt-1 font-body-sm text-text-secondary">
                        {text.noPreview}
                      </p>
                    </div>
                  ) : null}
                </article>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
