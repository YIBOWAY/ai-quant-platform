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
    await expect(AgentStudio()).rejects.toThrow(
      "redirect:/zh/hermes/approvals",
    );

    expect(mocks.redirect).toHaveBeenCalledWith("/zh/hermes/approvals");
    expect(mocks.getAgentCandidates).not.toHaveBeenCalled();
    expect(mocks.getAgentCandidateDetail).not.toHaveBeenCalled();
    expect(mocks.getFactors).not.toHaveBeenCalled();
  });
});
