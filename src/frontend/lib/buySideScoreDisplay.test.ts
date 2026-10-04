import { expect, it } from "vitest";

import { formatBuySideScoreLine } from "@/lib/buySideScoreDisplay";

const fixture = {
  score: 72.4,
  buyer_friendliness_score: 84,
  liquidity_score: 88,
  iv_crash_risk_score: 35,
  risk_reward: 2.5,
  theta_burn_7d_pct: 0.12,
};

it("prints total and component scores in Chinese", () => {
  const line = formatBuySideScoreLine(fixture, "zh");
  expect(line).toContain("总分 72");
  expect(line).toContain("买方友好 84");
  expect(line).toContain("流动性 88");
  expect(line).toContain("IV挤压风险 35");
  expect(line).toContain("盈亏比 2.50");
  expect(line).toContain("7日theta 12.0%");
});

it("prints -- for null component scores", () => {
  const line = formatBuySideScoreLine(
    {
      score: 50,
      buyer_friendliness_score: null,
      liquidity_score: undefined,
      iv_crash_risk_score: null,
      risk_reward: null,
      theta_burn_7d_pct: null,
    },
    "zh",
  );
  expect(line).toContain("总分 50");
  expect(line).toContain("买方友好 --");
  expect(line).toContain("流动性 --");
  expect(line).toContain("IV挤压风险 --");
  expect(line).toContain("盈亏比 --");
  expect(line).toContain("7日theta --");
});
