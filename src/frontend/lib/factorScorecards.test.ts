import { beforeEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ events: [] as string[], get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/apiClient", () => ({ apiRequest: calls.get }));
vi.mock("@/lib/hermes/workspaceClient", () => ({
  ensureOwnerSession: async () => { calls.events.push("owner"); },
  ownerPostJson: async (path: string, body: unknown) => {
    calls.events.push("post"); calls.post(path, body); return { status: "updating" };
  },
}));

import { getFactorScorecards, refreshFactorScorecards } from "./factorScorecards";

beforeEach(() => { calls.events.length = 0; calls.get.mockReset(); calls.post.mockReset(); });

describe("factor scorecard requests", () => {
  it("reads the stored deck without triggering any mutation", async () => {
    calls.get.mockResolvedValue({ status: "unavailable" });
    await getFactorScorecards();
    expect(calls.get).toHaveBeenCalledWith("/api/factor-scorecards");
    expect(calls.post).not.toHaveBeenCalled();
    expect(calls.events).toEqual([]);
  });

  it("establishes the owner session before the explicit refresh POST", async () => {
    await refreshFactorScorecards({ provider: "sample", horizons: [1, 5, 21] });
    expect(calls.events).toEqual(["owner", "post"]);
    expect(calls.post).toHaveBeenCalledWith("/api/factor-scorecards/refresh", { provider: "sample", horizons: [1, 5, 21] });
  });
});
