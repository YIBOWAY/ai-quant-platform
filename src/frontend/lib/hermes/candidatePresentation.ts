import type { AgentCandidatesResponse } from "@/lib/api";
import type { Tone } from "@/components/hermes/artifacts/formatters";

/**
 * Digest-aware approval_binding members from the candidate read contract.
 * Exhaustive presentation must cover every member including null.
 */
export type CandidateApprovalBinding =
  | "pending"
  | "approved"
  | "rejected"
  | "legacy_unbound"
  | null;

export type CandidateDigestPresentation =
  | { kind: "authoritative"; digest: string }
  | { kind: "migration_evidence"; digest: string }
  | { kind: "corrupt"; errorCode: string }
  | { kind: "none" };

function assertNever(value: never): never {
  throw new Error(`Unexpected approval_binding: ${JSON.stringify(value)}`);
}

/**
 * Map digest-aware approval_binding to a StatusPill tone.
 * Exhaustive over CandidateApprovalBinding — never a legacy-vs-warning binary.
 */
export function candidateBindingTone(
  binding: CandidateApprovalBinding,
): Tone {
  switch (binding) {
    case "pending":
      return "warning";
    case "approved":
      return "success";
    case "rejected":
      return "danger";
    case "legacy_unbound":
      return "danger";
    case null:
      return "neutral";
    default:
      return assertNever(binding);
  }
}

/**
 * Preserve the locked digest-aware API member without widening the contract.
 */
export function asCandidateApprovalBinding(
  value: AgentCandidatesResponse["candidates"][number]["approval_binding"],
): CandidateApprovalBinding {
  return value;
}

/**
 * Digest display rules for F2 read-only Approvals:
 * - verified + authoritative manifest_digest → show digest code
 * - migration_required → observed_manifest_digest as migration evidence only
 * - corrupt → stable error code, no digest preview
 */
export function candidateDigestPresentation(candidate: {
  integrity_state: AgentCandidatesResponse["candidates"][number]["integrity_state"];
  manifest_digest: string | null;
  observed_manifest_digest: string | null;
  integrity_error_code: string | null;
}): CandidateDigestPresentation {
  const integrity = candidate.integrity_state;

  if (integrity === "verified") {
    const digest = candidate.manifest_digest;
    if (typeof digest === "string" && digest.length > 0) {
      return { kind: "authoritative", digest };
    }
    return { kind: "none" };
  }

  if (integrity === "migration_required") {
    const observed = candidate.observed_manifest_digest;
    if (typeof observed === "string" && observed.length > 0) {
      return { kind: "migration_evidence", digest: observed };
    }
    return { kind: "none" };
  }

  if (integrity === "corrupt") {
    return {
      kind: "corrupt",
      errorCode: candidate.integrity_error_code ?? "corrupt",
    };
  }

  return { kind: "none" };
}
