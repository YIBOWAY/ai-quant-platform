import type {
  AgentCandidateDetailResponse,
  AgentCandidatesResponse,
} from "../api";

export type CandidateReadWarning =
  | "candidate_list_degraded"
  | "candidate_list_truncated"
  | "candidate_evidence_truncated";

export type NormalizedCandidateListResponse = AgentCandidatesResponse & {
  candidateReadWarning?: CandidateReadWarning;
};

export type NormalizedCandidateDetailResponse =
  AgentCandidateDetailResponse & {
    candidateReadWarning?: CandidateReadWarning;
  };

type CandidateSummary = AgentCandidatesResponse["candidates"][number];

const DIGEST_PATTERN = /^[0-9a-f]{64}$/;
const CANDIDATE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$/;
const STATUS_VALUES = new Set(["pending", "approved", "rejected"]);
const BINDING_VALUES = new Set([
  "pending",
  "approved",
  "rejected",
  "legacy_unbound",
]);
const INTEGRITY_VALUES = new Set([
  "verified",
  "migration_required",
  "corrupt",
]);
const MAX_CANDIDATES = 200;
const MAX_EVENTS = 100;
const MAX_EVENT_CHARS = 4_096;
const MAX_SOURCE_CHARS = 65_536;
const MAX_METADATA_CHARS = 65_536;
const MAX_GOAL_CHARS = 4_096;
const MAX_ARTIFACT_TYPE_CHARS = 256;
const MAX_ERROR_CHARS = 1_024;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNullableBoundedString(
  value: unknown,
  maxChars: number,
): value is string | null {
  return value === null || (typeof value === "string" && value.length <= maxChars);
}

function boundedError(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const bounded = value.slice(0, MAX_ERROR_CHARS);
  return bounded.length > 0 ? bounded : "candidate_upstream_error";
}

function isStatus(value: unknown): value is CandidateSummary["status"] {
  return value === null || (typeof value === "string" && STATUS_VALUES.has(value));
}

function isBinding(
  value: unknown,
): value is CandidateSummary["approval_binding"] {
  return value === null || (typeof value === "string" && BINDING_VALUES.has(value));
}

function digestOrNull(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && DIGEST_PATTERN.test(value));
}

function hasConsistentEvidence(value: {
  integrity_state: CandidateSummary["integrity_state"];
  manifest_digest: string | null;
  observed_manifest_digest: string | null;
  approval_binding: CandidateSummary["approval_binding"];
  approval_enabled: boolean;
  integrity_error_code: string | null;
  status: CandidateSummary["status"];
}): boolean {
  if (value.integrity_state === "verified") {
    if (value.approval_binding === "legacy_unbound") {
      return (
        value.manifest_digest !== null &&
        DIGEST_PATTERN.test(value.manifest_digest) &&
        value.observed_manifest_digest === null &&
        value.integrity_error_code === null &&
        value.status === null &&
        value.approval_enabled === false
      );
    }
    return (
      value.manifest_digest !== null &&
      DIGEST_PATTERN.test(value.manifest_digest) &&
      value.observed_manifest_digest === null &&
      value.integrity_error_code === null &&
      value.approval_binding !== null &&
      value.status === value.approval_binding &&
      value.approval_enabled === (value.approval_binding === "pending")
    );
  }
  if (value.integrity_state === "migration_required") {
    return (
      value.manifest_digest === null &&
      value.observed_manifest_digest !== null &&
      DIGEST_PATTERN.test(value.observed_manifest_digest) &&
      value.approval_binding === "legacy_unbound" &&
      value.approval_enabled === false &&
      value.integrity_error_code === null &&
      value.status !== null
    );
  }
  return (
    value.manifest_digest === null &&
    value.observed_manifest_digest === null &&
    value.approval_binding === null &&
    value.approval_enabled === false &&
    value.status === null &&
    typeof value.integrity_error_code === "string" &&
    value.integrity_error_code.length > 0 &&
    value.integrity_error_code.length <= MAX_ERROR_CHARS
  );
}

function normalizeSummary(value: unknown): CandidateSummary | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.candidate_id !== "string" ||
    !CANDIDATE_ID_PATTERN.test(value.candidate_id) ||
    !isNullableBoundedString(value.goal, MAX_GOAL_CHARS) ||
    !isNullableBoundedString(value.artifact_type, MAX_ARTIFACT_TYPE_CHARS) ||
    !isStatus(value.status) ||
    typeof value.integrity_state !== "string" ||
    !INTEGRITY_VALUES.has(value.integrity_state) ||
    !digestOrNull(value.manifest_digest) ||
    !digestOrNull(value.observed_manifest_digest) ||
    !isBinding(value.approval_binding) ||
    typeof value.approval_enabled !== "boolean" ||
    !(
      value.evidence_truncated === undefined ||
      typeof value.evidence_truncated === "boolean"
    ) ||
    !isNullableBoundedString(value.integrity_error_code, MAX_ERROR_CHARS) ||
    !(
      value.universe === null ||
      (Array.isArray(value.universe) &&
        value.universe.length <= 100 &&
        value.universe.every(
          (item) => typeof item === "string" && item.length <= 128,
        ))
    )
  ) {
    return null;
  }

  const candidate = {
    candidate_id: value.candidate_id,
    goal: value.goal,
    artifact_type: value.artifact_type,
    universe: value.universe,
    status: value.status,
    integrity_state: value.integrity_state,
    manifest_digest: value.manifest_digest,
    observed_manifest_digest: value.observed_manifest_digest,
    approval_binding: value.approval_binding,
    approval_enabled: value.approval_enabled,
    integrity_error_code: value.integrity_error_code,
  } as CandidateSummary;
  return hasConsistentEvidence(candidate) ? candidate : null;
}

function envelopeFields(value: Record<string, unknown>) {
  const apiError = boundedError(value.apiError);
  return {
    ...(apiError ? { apiError } : {}),
    ...(isRecord(value.safety)
      ? {
          safety:
            value.safety as NonNullable<AgentCandidatesResponse["safety"]>,
        }
      : {}),
  };
}

export function normalizeCandidateListResponse(
  value: unknown,
): NormalizedCandidateListResponse {
  if (!isRecord(value) || !Array.isArray(value.candidates)) {
    return { candidates: [], apiError: "candidate_response_invalid" };
  }
  if (Object.prototype.hasOwnProperty.call(value, "apiError")) {
    const apiError = boundedError(value.apiError);
    return {
      candidates: [],
      apiError: apiError ?? "candidate_response_invalid",
      ...(isRecord(value.safety)
        ? {
            safety:
              value.safety as NonNullable<AgentCandidatesResponse["safety"]>,
          }
        : {}),
    };
  }

  const normalized = value.candidates
    .map(normalizeSummary)
    .filter((item): item is CandidateSummary => item !== null);
  const invalidRows = normalized.length !== value.candidates.length;
  const truncated = normalized.length > MAX_CANDIDATES;
  return {
    candidates: normalized.slice(0, MAX_CANDIDATES),
    ...envelopeFields(value),
    ...(invalidRows
      ? { candidateReadWarning: "candidate_list_degraded" as const }
      : truncated
        ? { candidateReadWarning: "candidate_list_truncated" as const }
        : {}),
  };
}

function failureDetail(
  expectedCandidateId: string,
  error: string,
): NormalizedCandidateDetailResponse {
  const bounded = boundedError(error) ?? "candidate_response_invalid";
  return {
    candidate_id: expectedCandidateId,
    metadata: null,
    source_preview: null,
    audit: [],
    reviews: [],
    evidence_truncated: false,
    integrity_state: "corrupt",
    manifest_digest: null,
    observed_manifest_digest: null,
    approval_binding: null,
    approval_enabled: false,
    integrity_error_code: bounded,
    status: null,
    apiError: bounded,
  };
}

function boundedEvents(
  value: unknown,
): { events: string[]; truncated: boolean } | null {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) {
    return null;
  }
  return {
    events: value
      .slice(0, MAX_EVENTS)
      .map((entry) => entry.slice(0, MAX_EVENT_CHARS)),
    truncated:
      value.length > MAX_EVENTS ||
      value.some((entry) => entry.length > MAX_EVENT_CHARS),
  };
}

export function normalizeCandidateDetailResponse(
  value: unknown,
  expectedCandidateId: string,
): NormalizedCandidateDetailResponse {
  if (!isRecord(value)) {
    return failureDetail(expectedCandidateId, "candidate_response_invalid");
  }
  if (Object.prototype.hasOwnProperty.call(value, "apiError")) {
    return failureDetail(
      expectedCandidateId,
      boundedError(value.apiError) ?? "candidate_response_invalid",
    );
  }
  const audit = boundedEvents(value.audit);
  const reviews = boundedEvents(value.reviews);
  if (
    value.candidate_id !== expectedCandidateId ||
    !CANDIDATE_ID_PATTERN.test(expectedCandidateId) ||
    !audit ||
    !reviews ||
    typeof value.integrity_state !== "string" ||
    !INTEGRITY_VALUES.has(value.integrity_state) ||
    !digestOrNull(value.manifest_digest) ||
    !digestOrNull(value.observed_manifest_digest) ||
    !isBinding(value.approval_binding) ||
    typeof value.approval_enabled !== "boolean" ||
    !isNullableBoundedString(value.integrity_error_code, MAX_ERROR_CHARS) ||
    !isStatus(value.status) ||
    typeof value.evidence_truncated !== "boolean" ||
    !isNullableString(value.source_preview) ||
    !(value.metadata === null || isRecord(value.metadata))
  ) {
    return failureDetail(
      expectedCandidateId,
      "candidate_evidence_inconsistent",
    );
  }

  const evidence = {
    integrity_state: value.integrity_state,
    manifest_digest: value.manifest_digest,
    observed_manifest_digest: value.observed_manifest_digest,
    approval_binding: value.approval_binding,
    approval_enabled: value.approval_enabled,
    integrity_error_code: value.integrity_error_code,
    status: value.status,
  } as Parameters<typeof hasConsistentEvidence>[0];
  if (!hasConsistentEvidence(evidence)) {
    return failureDetail(
      expectedCandidateId,
      "candidate_evidence_inconsistent",
    );
  }

  let metadata = value.metadata as Record<string, unknown> | null;
  let metadataTruncated = false;
  if (metadata !== null) {
    let serialized = "";
    try {
      serialized = JSON.stringify(metadata);
    } catch {
      return failureDetail(
        expectedCandidateId,
        "candidate_evidence_inconsistent",
      );
    }
    if (serialized.length > MAX_METADATA_CHARS) {
      metadata = null;
      metadataTruncated = true;
    }
  }

  const source = value.source_preview as string | null;
  const sourceTruncated =
    typeof source === "string" && source.length > MAX_SOURCE_CHARS;
  const candidateReadWarning =
    value.evidence_truncated === true ||
    sourceTruncated ||
    audit.truncated ||
    reviews.truncated ||
    metadataTruncated
      ? "candidate_evidence_truncated"
      : undefined;
  return {
    candidate_id: expectedCandidateId,
    metadata,
    source_preview:
      typeof source === "string" ? source.slice(0, MAX_SOURCE_CHARS) : null,
    audit: audit.events,
    reviews: reviews.events,
    evidence_truncated: value.evidence_truncated,
    ...evidence,
    ...envelopeFields(value),
    ...(candidateReadWarning ? { candidateReadWarning } : {}),
  };
}
