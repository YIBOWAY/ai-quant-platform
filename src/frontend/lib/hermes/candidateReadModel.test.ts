import { describe, expect, it } from "vitest";

import {
  normalizeCandidateDetailResponse,
  normalizeCandidateListResponse,
} from "./candidateReadModel";

const digest = "a".repeat(64);

function validSummary(candidateId = "candidate-one") {
  return {
    candidate_id: candidateId,
    goal: "Research momentum",
    artifact_type: "factor",
    universe: ["AAPL"],
    status: "pending",
    integrity_state: "verified",
    manifest_digest: digest,
    observed_manifest_digest: null,
    approval_binding: "pending",
    approval_enabled: true,
    integrity_error_code: null,
  };
}

function validDetail(candidateId = "candidate-one") {
  return {
    candidate_id: candidateId,
    metadata: { task_type: "propose-factor" },
    source_preview: "def factor():\n    return 1",
    audit: ["candidate_created"],
    reviews: ["pending human review"],
    evidence_truncated: false,
    integrity_state: "verified",
    manifest_digest: digest,
    observed_manifest_digest: null,
    approval_binding: "pending",
    approval_enabled: true,
    integrity_error_code: null,
    status: "pending",
  };
}

describe("normalizeCandidateListResponse", () => {
  it("keeps verified legacy-unbound rows visible but non-authorizing", () => {
    const legacy = {
      ...validSummary("candidate-unbound"),
      status: null,
      approval_binding: "legacy_unbound",
      approval_enabled: false,
    };

    const result = normalizeCandidateListResponse({ candidates: [legacy] });

    expect(result.candidates).toHaveLength(1);
    expect(result.candidates[0]).toMatchObject({
      candidate_id: "candidate-unbound",
      status: null,
      approval_binding: "legacy_unbound",
      approval_enabled: false,
    });
  });
  it("keeps healthy rows while failing closed around malformed list rows", () => {
    const result = normalizeCandidateListResponse({
      candidates: [validSummary(), { candidate_id: "broken" }],
    });

    expect(result.candidates.map((item) => item.candidate_id)).toEqual([
      "candidate-one",
    ]);
    expect(result.candidateReadWarning).toBe("candidate_list_degraded");
  });

  it("turns a structurally invalid 200 payload into an unavailable envelope", () => {
    const result = normalizeCandidateListResponse({ candidates: null });

    expect(result.candidates).toEqual([]);
    expect(result.apiError).toBe("candidate_response_invalid");
  });

  it.each(["goal", "artifact_type", "integrity_error_code"] as const)(
    "drops rows with an unbounded %s field before SSR",
    (field) => {
      const corrupt = {
        ...validSummary("candidate-corrupt"),
        status: null,
        integrity_state: "corrupt",
        manifest_digest: null,
        observed_manifest_digest: null,
        approval_binding: null,
        approval_enabled: false,
        integrity_error_code: "manifest_unreadable",
        [field]: "x".repeat(70_000),
      };
      const result = normalizeCandidateListResponse({
        candidates: [validSummary(), corrupt],
      });

      expect(result.candidates.map((item) => item.candidate_id)).toEqual([
        "candidate-one",
      ]);
      expect(result.candidateReadWarning).toBe("candidate_list_degraded");
    },
  );

  it("bounds an upstream list error before it reaches SSR", () => {
    const result = normalizeCandidateListResponse({
      candidates: [validSummary()],
      apiError: "e".repeat(70_000),
    });

    expect(result.candidates).toEqual([]);
    expect(result.apiError?.length).toBeLessThanOrEqual(1_024);
  });

  it("fails closed when a list apiError has a malformed type", () => {
    const result = normalizeCandidateListResponse({
      candidates: [validSummary()],
      apiError: { code: "candidate_repository_unavailable" },
    });

    expect(result.candidates).toEqual([]);
    expect(result.apiError).toBe("candidate_response_invalid");
  });
});

describe("normalizeCandidateDetailResponse", () => {
  it("keeps verified legacy-unbound detail visible but non-authorizing", () => {
    const result = normalizeCandidateDetailResponse(
      {
        ...validDetail("candidate-unbound"),
        status: null,
        approval_binding: "legacy_unbound",
        approval_enabled: false,
      },
      "candidate-unbound",
    );

    expect(result.apiError).toBeUndefined();
    expect(result.approval_binding).toBe("legacy_unbound");
    expect(result.approval_enabled).toBe(false);
  });
  it.each([
    {
      name: "invalid digest",
      change: { manifest_digest: "not-a-sha256" },
    },
    {
      name: "status and binding mismatch",
      change: { status: "approved", approval_binding: "pending" },
    },
    {
      name: "approval flag inconsistent with binding",
      change: { approval_enabled: false, approval_binding: "pending" },
    },
    {
      name: "invalid audit shape",
      change: { audit: null },
    },
  ])("withholds inconsistent evidence: $name", ({ change }) => {
    const result = normalizeCandidateDetailResponse(
      { ...validDetail(), ...change },
      "candidate-one",
    );

    expect(result.apiError).toBe("candidate_evidence_inconsistent");
    expect(result.integrity_state).toBe("corrupt");
    expect(result.source_preview).toBeNull();
    expect(result.approval_enabled).toBe(false);
    expect(result.manifest_digest).toBeNull();
  });

  it("bounds untrusted evidence before it reaches SSR", () => {
    const result = normalizeCandidateDetailResponse(
      {
        ...validDetail(),
        source_preview: "x".repeat(80_000),
        audit: Array.from({ length: 140 }, (_, index) => `audit-${index}`),
        reviews: Array.from({ length: 140 }, (_, index) => `review-${index}`),
        metadata: { payload: "m".repeat(80_000) },
      },
      "candidate-one",
    );

    expect(result.source_preview?.length).toBeLessThanOrEqual(65_536);
    expect(result.audit).toHaveLength(100);
    expect(result.reviews).toHaveLength(100);
    expect(result.metadata).toBeNull();
    expect(result.candidateReadWarning).toBe("candidate_evidence_truncated");
  });

  it("preserves an upstream failure without reclassifying it as healthy evidence", () => {
    const result = normalizeCandidateDetailResponse(
      {
        ...validDetail(),
        apiError: "503: repository unavailable",
      },
      "candidate-one",
    );

    expect(result.apiError).toBe("503: repository unavailable");
    expect(result.source_preview).toBeNull();
    expect(result.approval_enabled).toBe(false);
  });

  it("bounds an upstream detail failure before reusing it as corrupt evidence", () => {
    const result = normalizeCandidateDetailResponse(
      { ...validDetail(), apiError: "e".repeat(70_000) },
      "candidate-one",
    );

    expect(result.apiError?.length).toBeLessThanOrEqual(1_024);
    expect(result.integrity_error_code?.length).toBeLessThanOrEqual(1_024);
  });

  it("fails closed when a detail apiError has a malformed type", () => {
    const result = normalizeCandidateDetailResponse(
      {
        ...validDetail(),
        apiError: { code: "candidate_repository_unavailable" },
      },
      "candidate-one",
    );

    expect(result.apiError).toBe("candidate_response_invalid");
    expect(result.source_preview).toBeNull();
    expect(result.approval_enabled).toBe(false);
  });

  it("rejects a corrupt payload that still carries an observed digest", () => {
    const result = normalizeCandidateDetailResponse(
      {
        ...validDetail(),
        status: null,
        integrity_state: "corrupt",
        manifest_digest: null,
        observed_manifest_digest: digest,
        approval_binding: null,
        approval_enabled: false,
        integrity_error_code: "manifest_unreadable",
      },
      "candidate-one",
    );

    expect(result.apiError).toBe("candidate_evidence_inconsistent");
    expect(result.observed_manifest_digest).toBeNull();
  });

  it("rejects migration evidence without the backend-required legacy status", () => {
    const result = normalizeCandidateDetailResponse(
      {
        ...validDetail(),
        status: null,
        integrity_state: "migration_required",
        manifest_digest: null,
        observed_manifest_digest: digest,
        approval_binding: "legacy_unbound",
        approval_enabled: false,
        integrity_error_code: null,
      },
      "candidate-one",
    );

    expect(result.apiError).toBe("candidate_evidence_inconsistent");
    expect(result.source_preview).toBeNull();
  });
});
