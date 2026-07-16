import type { CandidateSummary } from "@/lib/api";

/**
 * Resolve the read-only Approvals selection without coupling it to list order.
 *
 * An explicit deep link remains authoritative even if the catalog read failed:
 * the detail endpoint can still give the user a precise not-found/unavailable
 * result. With no explicit id, the first catalog row is the predictable default.
 */
export function resolveCandidateSelection(
  candidates: CandidateSummary[],
  requested: string | string[] | undefined,
): string | null {
  const requestedValues = Array.isArray(requested) ? requested : [requested];
  const explicit = requestedValues.find(
    (value): value is string => typeof value === "string" && value.trim().length > 0,
  );
  return explicit?.trim() ?? candidates[0]?.candidate_id ?? null;
}
