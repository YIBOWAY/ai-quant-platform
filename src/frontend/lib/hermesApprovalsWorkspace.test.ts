import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CandidateApprovalWorkspace } from "@/components/hermes/approvals/CandidateApprovalWorkspace";
import type {
  AgentCandidateDetailResponse,
  AgentCandidatesResponse,
} from "./api";
import { resolveCandidateSelection } from "./hermes/candidateSelection";

const digestA = "a".repeat(64);
const digestB = "b".repeat(64);

function candidate(
  candidateId: string,
  overrides: Partial<AgentCandidatesResponse["candidates"][number]> = {},
): AgentCandidatesResponse["candidates"][number] {
  return {
    candidate_id: candidateId,
    goal: `Research ${candidateId}`,
    artifact_type: "factor",
    universe: ["AAPL", "MSFT"],
    status: "pending",
    integrity_state: "verified",
    manifest_digest: digestA,
    observed_manifest_digest: null,
    approval_binding: "pending",
    approval_enabled: true,
    integrity_error_code: null,
    ...overrides,
  };
}

function detail(
  candidateId: string,
  overrides: Partial<AgentCandidateDetailResponse> = {},
): AgentCandidateDetailResponse {
  return {
    candidate_id: candidateId,
    metadata: { task_type: "propose-factor" },
    source_preview: "def compute_factor(frame):\n    return frame.close.pct_change()",
    audit: ["candidate_created", "gate_1_bound"],
    reviews: ["human review pending"],
    evidence_truncated: false,
    integrity_state: "verified",
    manifest_digest: digestA,
    observed_manifest_digest: null,
    approval_binding: "pending",
    approval_enabled: true,
    integrity_error_code: null,
    status: "pending",
    ...overrides,
  };
}

describe("resolveCandidateSelection", () => {
  const candidates = [candidate("candidate-one"), candidate("candidate-two")];

  it("uses a query-param candidate instead of forcing the first row", () => {
    expect(resolveCandidateSelection(candidates, "candidate-two")).toBe("candidate-two");
  });

  it("normalizes repeated query params and falls back to the first row", () => {
    expect(resolveCandidateSelection(candidates, ["", "candidate-two"])).toBe(
      "candidate-two",
    );
    expect(resolveCandidateSelection(candidates, undefined)).toBe("candidate-one");
  });

  it("keeps an explicit deep-link id even when the list endpoint is unavailable", () => {
    expect(resolveCandidateSelection([], "direct-candidate")).toBe("direct-candidate");
  });
});

describe("CandidateApprovalWorkspace", () => {
  it("shows registered and promoted factor context before Agent Studio cutover", () => {
    const html = renderToStaticMarkup(
      createElement(CandidateApprovalWorkspace, {
        candidates: { candidates: [] },
        selectedCandidateId: null,
        detail: null,
        locale: "en",
        registry: {
          readStatus: "available",
          registeredCount: 17,
          promotedFactorIds: ["agent_candidate_wave2_sceneb_mom20_v3"],
          truncated: false,
          error: null,
        },
      }),
    );

    expect(html).toContain("Promoted registry context");
    expect(html).toContain(">17</strong> registered");
    expect(html).toContain(">1</strong> promoted");
    expect(html).toContain("agent_candidate_wave2_sceneb_mom20_v3");
  });

  it("marks registry context unavailable instead of showing a false zero", () => {
    const html = renderToStaticMarkup(
      createElement(CandidateApprovalWorkspace, {
        candidates: { candidates: [] },
        selectedCandidateId: null,
        detail: null,
        locale: "en",
        registry: {
          readStatus: "unavailable",
          registeredCount: 0,
          promotedFactorIds: [],
          truncated: false,
          error: "factor registry unavailable",
        },
      }),
    );

    expect(html).toContain("Promoted registry unavailable");
    expect(html).not.toContain("0 registered");
  });

  it("selects any candidate and renders its complete read-only evidence", () => {
    const candidates = {
      candidates: [candidate("candidate-one"), candidate("candidate-two")],
    } satisfies AgentCandidatesResponse;
    const html = renderToStaticMarkup(
      createElement(CandidateApprovalWorkspace, {
        candidates,
        selectedCandidateId: "candidate-two",
        detail: detail("candidate-two"),
        locale: "en",
      }),
    );

    expect(html).toContain('data-hermes-selected-candidate="candidate-two"');
    expect(html).toContain('aria-current="page"');
    expect(html).toContain(
      'href="/en/hermes/approvals?candidate=candidate-two"',
    );
    expect(html).toContain("def compute_factor(frame):");
    expect(html).toContain("candidate_created");
    expect(html).toContain("human review pending");
    expect(html).toContain(digestA);
    expect(html).toContain("propose-factor");
    expect(html).toContain("platform review primitive");
    expect(html).toContain("available · not HQA Gate 2 proof");
    expect(html).not.toContain("yes · CLI only");

    // The workbench is a GET-only evidence reader. No browser Gate 2 surface
    // may silently reappear while adding candidate-detail parity.
    expect(html).not.toContain("<form");
    expect(html).not.toContain("<button");
    expect(html).not.toContain("data-hermes-gate2-controls");
    expect(html).not.toContain("/review");
  });

  it("labels migration evidence without presenting it as an authoritative digest", () => {
    const migrating = candidate("legacy-candidate", {
      integrity_state: "migration_required",
      manifest_digest: null,
      observed_manifest_digest: digestB,
      approval_binding: "legacy_unbound",
      approval_enabled: false,
    });
    const html = renderToStaticMarkup(
      createElement(CandidateApprovalWorkspace, {
        candidates: { candidates: [migrating] },
        selectedCandidateId: migrating.candidate_id,
        detail: detail(migrating.candidate_id, {
          integrity_state: "migration_required",
          manifest_digest: null,
          observed_manifest_digest: digestB,
          approval_binding: "legacy_unbound",
          approval_enabled: false,
        }),
        locale: "en",
      }),
    );

    expect(html).toContain("Migration evidence only");
    expect(html).toContain("observed_manifest_digest");
    expect(html).toContain(digestB);
    expect(html).not.toContain(`manifest_digest</span><code>${digestB}`);
  });

  it("fails closed for corrupt details and never exposes their source preview", () => {
    const corrupt = candidate("corrupt-candidate", {
      integrity_state: "corrupt",
      manifest_digest: null,
      approval_binding: null,
      approval_enabled: false,
      integrity_error_code: "candidate_manifest_corrupt",
    });
    const html = renderToStaticMarkup(
      createElement(CandidateApprovalWorkspace, {
        candidates: { candidates: [corrupt] },
        selectedCandidateId: corrupt.candidate_id,
        detail: detail(corrupt.candidate_id, {
          source_preview: "MUST_NOT_RENDER",
          integrity_state: "corrupt",
          manifest_digest: null,
          approval_binding: null,
          approval_enabled: false,
          integrity_error_code: "candidate_manifest_corrupt",
        }),
        locale: "en",
      }),
    );

    expect(html).toContain("Integrity verification failed");
    expect(html).toContain("candidate_manifest_corrupt");
    expect(html).toContain("Source preview withheld");
    expect(html).not.toContain("MUST_NOT_RENDER");
  });

  it("fails closed when normalized evidence reports a cross-field inconsistency", () => {
    const selected = candidate("candidate-one");
    const html = renderToStaticMarkup(
      createElement(CandidateApprovalWorkspace, {
        candidates: { candidates: [selected] },
        selectedCandidateId: selected.candidate_id,
        detail: detail(selected.candidate_id, {
          apiError: "candidate_evidence_inconsistent",
          source_preview: null,
          integrity_state: "corrupt",
          manifest_digest: null,
          approval_binding: null,
          approval_enabled: false,
          integrity_error_code: "candidate_evidence_inconsistent",
          status: null,
        }),
        locale: "en",
      }),
    );

    expect(html).toContain("Candidate detail unavailable");
    expect(html).toContain("candidate_evidence_inconsistent");
    expect(html).not.toContain("Authoritative manifest digest");
  });

  it("makes every bounded evidence scroller keyboard focusable", () => {
    const selected = candidate("candidate-one");
    const html = renderToStaticMarkup(
      createElement(CandidateApprovalWorkspace, {
        candidates: { candidates: [selected] },
        selectedCandidateId: selected.candidate_id,
        detail: detail(selected.candidate_id),
        locale: "en",
      }),
    );

    expect(html).toContain('data-hermes-candidate-source="true" tabindex="0"');
    expect(html).toContain('data-hermes-candidate-metadata="true" tabindex="0"');
  });

  it("distinguishes a detail read failure from an empty candidate list", () => {
    const selected = candidate("candidate-one");
    const html = renderToStaticMarkup(
      createElement(CandidateApprovalWorkspace, {
        candidates: { candidates: [selected] },
        selectedCandidateId: selected.candidate_id,
        detail: detail(selected.candidate_id, {
          apiError: "404: candidate not found",
        }),
        locale: "en",
      }),
    );

    expect(html).toContain("Candidate detail unavailable");
    expect(html).toContain("404: candidate not found");
    expect(html).not.toContain("No research approval items");
  });
});
