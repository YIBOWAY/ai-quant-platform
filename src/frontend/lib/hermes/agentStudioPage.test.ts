import { readFileSync } from "node:fs";
import path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getAgentCandidateDetail: vi.fn(),
  getAgentCandidates: vi.fn(),
  getFactors: vi.fn(),
  redirect: vi.fn((href: string) => {
    throw new Error(`redirect:${href}`);
  }),
}));

vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));
vi.mock("@/lib/serverLocale", () => ({
  getServerLocale: vi.fn(async () => "zh" as const),
}));
vi.mock("@/lib/hermes/featureFlags", () => ({
  hermesFeatureFlags: () => ({ agentStudioRedirect: true }),
}));
vi.mock("@/lib/api", () => ({
  getAgentCandidateDetail: mocks.getAgentCandidateDetail,
  getAgentCandidates: mocks.getAgentCandidates,
  getFactors: mocks.getFactors,
}));

import AgentStudio from "@/app/agent-studio/page";

describe("Agent Studio page-scoped cutover", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("redirects before reading any legacy candidate or factor endpoint", async () => {
    await expect(AgentStudio({})).rejects.toThrow(
      "redirect:/zh/library",
    );

    expect(mocks.redirect).toHaveBeenCalledWith("/zh/library");
    expect(mocks.getAgentCandidates).not.toHaveBeenCalled();
    expect(mocks.getAgentCandidateDetail).not.toHaveBeenCalled();
    expect(mocks.getFactors).not.toHaveBeenCalled();
  });
});

describe("Agent Studio read-only candidate selection", () => {
  const source = readFileSync(
    path.join(process.cwd(), "app/agent-studio/page.tsx"),
    "utf8",
  );

  it("selects the requested candidate instead of always the first one", () => {
    expect(source).toContain("searchParams");
    expect(source).toContain("requestedCandidateId");
    expect(source).toContain("candidate.candidate_id === requestedCandidateId");
    expect(source).toContain("?? candidates.candidates[0]");
    expect(source).toContain(
      "getAgentCandidateDetail(selectedCandidate.candidate_id)",
    );
  });

  it("makes every pool entry a localized read-only link with selected state", () => {
    expect(source).toContain('aria-current={isSelected ? "true" : undefined}');
    expect(source).toContain("/agent-studio?candidate=${encodeURIComponent(candidate.candidate_id)}");
    expect(source).toContain("localizePath(");
    expect(source).not.toContain("onClick");
    expect(source).not.toContain("useMutation");
  });
});
