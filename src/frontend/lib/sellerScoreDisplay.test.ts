import { expect, it } from "vitest";

import { formatSellerScoreLine } from "@/lib/sellerScoreDisplay";

const fixture = {
  yield_score: 50,
  liquidity_score: 100,
  delta_safety_score: 75,
  iv_edge_score: 50,
  iv_rank_score: null,
  composite: 72.2,
  weights_used: { yield: 0.3, liquidity: 0.25, delta_safety: 0.2, iv_edge: 0.15 },
};

it("prints composite and five legs in Chinese", () => {
  expect(formatSellerScoreLine(fixture, "zh")).toContain("72");
  expect(formatSellerScoreLine(fixture, "zh")).toContain("IVR --");
});
