import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CandidateApprovalListState } from "@/components/hermes/approvals/CandidateApprovalListState";
import type { AgentCandidatesResponse } from "./api";

describe("Hermes Approvals candidate source state", () => {
  it("renders endpoint failure as unavailable rather than an empty approval list", () => {
    const candidates = {
      candidates: [],
      apiError: "503: candidate repository unavailable",
    } satisfies AgentCandidatesResponse;

    const html = renderToStaticMarkup(
      createElement(CandidateApprovalListState, {
        candidates,
        locale: "en",
      }),
    );

    expect(html).toContain("data-hermes-candidates-unavailable");
    expect(html).toContain("Candidate list unavailable");
    expect(html).toContain("503: candidate repository unavailable");
    expect(html).not.toContain("data-hermes-candidates-empty");
    expect(html).not.toContain("No research approval items");
  });

  it("renders a successful zero-row response as truly empty", () => {
    const candidates = { candidates: [] } satisfies AgentCandidatesResponse;

    const html = renderToStaticMarkup(
      createElement(CandidateApprovalListState, {
        candidates,
        locale: "en",
      }),
    );

    expect(html).toContain("data-hermes-candidates-empty");
    expect(html).toContain("No research approval items");
    expect(html).not.toContain("data-hermes-candidates-unavailable");
  });
});
