import { ApiClientError, apiRequestOnce } from "./apiClient";
import { ensureOwnerSession, ownerPostJson } from "./hermes/workspaceClient";

const SOURCE_DIGEST = /^[0-9a-f]{64}$/i;

export type VerifiedLibraryCandidate = {
  candidate_id: string;
  source_digest: string;
  status: "verified";
  sleeve_id: null;
  objective?: string;
  factor_id?: string;
  universe?: string[];
  display_name?: string;
  display_name_zh?: string;
  summary_zh?: string;
  dsr?: Record<string, unknown> | null;
  activation_eligibility: {
    eligible: boolean;
    reason: string | null;
  };
  created_at?: string;
};

type RemoteBook = {
  candidates?: unknown[];
};

export type LibraryHangResult = {
  already_hung: boolean;
  candidate_id: string;
  sleeve_id: string | null;
  source_digest: string;
  status: string;
};

function isVerifiedLibraryCandidate(value: unknown): value is VerifiedLibraryCandidate {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  const activation = candidate.activation_eligibility;
  return (
    typeof candidate.candidate_id === "string" &&
    candidate.candidate_id.length > 0 &&
    candidate.status === "verified" &&
    candidate.sleeve_id === null &&
    typeof candidate.source_digest === "string" &&
    SOURCE_DIGEST.test(candidate.source_digest) &&
    activation !== null &&
    typeof activation === "object" &&
    !Array.isArray(activation) &&
    typeof (activation as Record<string, unknown>).eligible === "boolean" &&
    (typeof (activation as Record<string, unknown>).reason === "string" ||
      (activation as Record<string, unknown>).reason === null)
  );
}

export async function loadVerifiedLibraryCandidates(): Promise<VerifiedLibraryCandidate[]> {
  const book = await apiRequestOnce<RemoteBook>("/api/assistant/remote/book");
  return (book.candidates ?? []).filter(isVerifiedLibraryCandidate);
}

export type LibraryHangResolution =
  | "resolved_hung"
  | "still_verified"
  | "still_unknown";

export async function resolveLibraryHangOutcome(candidate: {
  candidate_id: string;
  source_digest: string;
}): Promise<LibraryHangResolution> {
  const book = await apiRequestOnce<RemoteBook>("/api/assistant/remote/book");
  const observed = (book.candidates ?? []).find(
    (value) =>
      value !== null &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      (value as Record<string, unknown>).candidate_id === candidate.candidate_id,
  );
  if (observed === undefined) return "still_unknown";
  const row = observed as Record<string, unknown>;
  if (row.source_digest !== candidate.source_digest) return "still_unknown";
  if (row.status === "hung" && typeof row.sleeve_id === "string" && row.sleeve_id) {
    return "resolved_hung";
  }
  if (row.status === "verified" && row.sleeve_id === null) {
    return "still_verified";
  }
  return "still_unknown";
}

export async function hangLibraryCandidate(candidate: {
  candidate_id: string;
  source_digest: string;
}): Promise<LibraryHangResult> {
  await ensureOwnerSession();
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 15_000);
  try {
    return await ownerPostJson<LibraryHangResult>(
      "/api/assistant/remote/hang",
      {
        candidate_id: candidate.candidate_id,
        expected_source_digest: candidate.source_digest,
      },
      controller.signal,
    );
  } catch (error) {
    const status =
      error && typeof error === "object" && "status" in error
        ? Number((error as { status?: unknown }).status)
        : undefined;
    const code =
      error && typeof error === "object" && "code" in error
        ? String((error as { code?: unknown }).code ?? "")
        : "";
    const uncertain =
      controller.signal.aborted ||
      typeof status !== "number" ||
      !Number.isFinite(status) ||
      (typeof status === "number" && status >= 500) ||
      [
        "hang_account_outcome_unknown",
        "hang_book_persist_failed",
        "hang_sleeve_pending",
        "hang_sleeve_activation_failed",
      ].includes(code);
    if (uncertain) {
      throw new ApiClientError(
        "Activation outcome is unknown. Refresh the candidate book before deciding whether to retry.",
        status,
        "outcome_unknown",
      );
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}
