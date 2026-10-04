import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { BuySideRecommendation } from "@/lib/api";
import { leapsRollPrompt, strategyLabel } from "./BuySideOptionsAssistant";

function recommendation(
  strategy_type: BuySideRecommendation["strategy_type"],
  dte: number,
): BuySideRecommendation {
  return {
    strategy_type,
    score: 70,
    rank: 1,
    one_line_summary: "modeled decision support",
    key_reasons: [],
    key_risks: [],
    legs: [
      {
        symbol: "US.AAPL20260719C100000",
        option_type: "CALL",
        side: "long",
        expiry: "2026-07-19",
        strike: 100,
        quantity: 1,
        contract_size: 100,
        dte,
      },
    ],
    risk_attribution: {
      direction: 25,
      time: 25,
      volatility: 25,
      liquidity: 25,
    },
    primary_risk_source: "time",
    warnings: [],
  };
}

describe("LEAPS roll prompt", () => {
  it("appears below 90 DTE in both locales and stays absent at the boundary", () => {
    expect(leapsRollPrompt(recommendation("leaps_call", 89), "en")).toContain(
      "under 90 days",
    );
    expect(leapsRollPrompt(recommendation("leaps_call_spread", 89), "zh")).toContain(
      "不足 90 天",
    );
    expect(leapsRollPrompt(recommendation("leaps_call", 90), "en")).toBeNull();
    expect(leapsRollPrompt(recommendation("long_call", 30), "en")).toBeNull();
  });

  it("uses the shared actionable options error presentation", () => {
    const source = readFileSync(
      path.join(process.cwd(), "components/forms/BuySideOptionsAssistant.tsx"),
      "utf8",
    );
    expect(source).toContain("optionsErrorMessage(error, locale)");
    expect(source).toContain("optionsErrorMessage(mutation.error, locale)");
  });
});

describe("buy-side strategy labels", () => {
  it("localizes recommendation card titles and comparison rows", () => {
    expect(strategyLabel("long_call", "en")).toBe("Long Call");
    expect(strategyLabel("bull_call_spread", "en")).toBe("Bull Call Spread");
    expect(strategyLabel("leaps_call", "en")).toBe("LEAPS Call");
    expect(strategyLabel("leaps_call_spread", "en")).toBe("LEAPS Call Spread");
    expect(strategyLabel("long_call", "zh")).toBe("买入看涨");
    expect(strategyLabel("bull_call_spread", "zh")).toBe("牛市看涨价差");
    expect(strategyLabel("leaps_call", "zh")).toBe("LEAPS 看涨");
    expect(strategyLabel("leaps_call_spread", "zh")).toBe("LEAPS 看涨价差");
    expect(strategyLabel("unknown_strategy", "zh")).toBe("unknown_strategy");
  });

  it("passes the locale at both call sites", () => {
    const source = readFileSync(
      path.join(process.cwd(), "components/forms/BuySideOptionsAssistant.tsx"),
      "utf8",
    );
    expect(source.match(/strategyLabel\(item\.strategy_type, locale\)/g)).toHaveLength(2);
  });
});

describe("buy-side snapshot metrics", () => {
  it("drops the dead next-event card and the unimplemented max-loss-budget key", () => {
    const source = readFileSync(
      path.join(process.cwd(), "components/forms/BuySideOptionsAssistant.tsx"),
      "utf8",
    );
    expect(source).not.toContain("text.earnings");
    expect(source).not.toContain("maxLossBudget");
  });
});
