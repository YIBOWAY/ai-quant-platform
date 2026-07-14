import type { AgentCandidateDetailResponse } from "@/lib/api";

const MANIFEST_DIGEST_RE = /^[0-9a-f]{64}$/;

export type ReviewableCandidateDetail = AgentCandidateDetailResponse & {
  manifest_digest: string;
};

/**
 * Gate 2 CAS readiness: approval must be enabled, binding/status pending,
 * integrity verified, and manifest_digest a full 64-hex authority digest.
 * Callers must re-fetch detail before approve/reject; never invent digests
 * from list rows alone.
 */
export function canReviewCandidateDetail(
  detail: AgentCandidateDetailResponse | undefined | null,
): detail is ReviewableCandidateDetail {
  if (!detail) return false;
  if (detail.approval_enabled !== true) return false;
  if (detail.status !== "pending") return false;
  if (detail.integrity_state !== "verified") return false;
  if (detail.approval_binding !== "pending") return false;
  const digest = detail.manifest_digest;
  return typeof digest === "string" && MANIFEST_DIGEST_RE.test(digest);
}

/**
 * List-row gate for showing Approve/Reject entry controls.
 * Dialog still re-fetches detail and re-validates via canReviewCandidateDetail.
 * migration_required / corrupt / approval_enabled≠true never get controls.
 */
export function listRowShowsGate2Controls(candidate: {
  approval_enabled?: boolean | null;
  status?: string | null;
  integrity_state?: string | null;
}): boolean {
  return (
    candidate.approval_enabled === true &&
    candidate.status === "pending" &&
    candidate.integrity_state === "verified"
  );
}
