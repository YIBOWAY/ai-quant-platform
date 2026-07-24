import { describe, expect, it } from "vitest";

import { buildPromotedRegistryContext } from "./promotedRegistry";

describe("buildPromotedRegistryContext", () => {
  it("reports bounded promoted registry provenance separately from built-ins", () => {
    const result = buildPromotedRegistryContext({
      factors: [
        { factor_id: "builtin_momentum", origin: "builtin" },
        { factor_id: "agent_candidate_wave2_sceneb_mom20_v3", origin: "promoted" },
      ],
    });

    expect(result).toEqual({
      readStatus: "available",
      registeredCount: 2,
      promotedFactorIds: ["agent_candidate_wave2_sceneb_mom20_v3"],
      truncated: false,
      error: null,
    });
  });

  it("does not present an unavailable registry as an empty healthy catalog", () => {
    const result = buildPromotedRegistryContext({
      factors: [],
      apiError: "e".repeat(70_000),
    });

    expect(result.readStatus).toBe("unavailable");
    expect(result.registeredCount).toBe(0);
    expect(result.promotedFactorIds).toEqual([]);
    expect(result.error?.length).toBeLessThanOrEqual(1_024);
  });

  it("fails closed around malformed factor provenance", () => {
    const result = buildPromotedRegistryContext({
      factors: [{ factor_id: "candidate-without-origin" }],
    });

    expect(result.readStatus).toBe("unavailable");
    expect(result.error).toBe("factor_registry_response_invalid");
  });
});
