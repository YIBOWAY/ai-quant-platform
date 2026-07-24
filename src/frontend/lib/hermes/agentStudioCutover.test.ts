import { describe, expect, it } from "vitest";

import { agentStudioCutoverHref } from "./agentStudioCutover";

describe("agentStudioCutoverHref", () => {
  it("is off by default and localizes the reversible cutover target", () => {
    expect(agentStudioCutoverHref(false, "zh")).toBeNull();
    expect(agentStudioCutoverHref(false, "en")).toBeNull();
    expect(agentStudioCutoverHref(true, "zh")).toBe("/zh/hermes/approvals");
    expect(agentStudioCutoverHref(true, "en")).toBe("/en/hermes/approvals");
  });
});
