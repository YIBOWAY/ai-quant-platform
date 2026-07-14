import { CandidateApprovalListState } from "@/components/hermes/approvals/CandidateApprovalListState";
import { StatusPill } from "@/components/ui/primitives";
import { getAgentCandidates } from "@/lib/api";
import {
  asCandidateApprovalBinding,
  candidateBindingTone,
  candidateDigestPresentation,
} from "@/lib/hermes/candidatePresentation";
import { hermesWorkbenchCopy } from "@/lib/hermes/copy";
import { getServerLocale } from "@/lib/serverLocale";

/**
 * F2 Approvals: digest-aware candidate summaries, mutation-free.
 * No approve/reject controls in any integrity state.
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
    f2Note: isZh
      ? "F2 只读：不提供批准/拒绝控件。Gate 2 审批仍走既有人工 CAS 路径。"
      : "F2 read-only: no approve/reject controls. Gate 2 still uses the existing human CAS path.",
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
        <p className="font-body-sm text-text-secondary">{text.f2Note}</p>
      </header>

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
