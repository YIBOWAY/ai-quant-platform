import { describe, expect, it } from "vitest";

import { summarizeExperimentStrategy } from "./experimentSummary";

describe("summarizeExperimentStrategy", () => {
  it("summarizes persisted factor blend weights and directions", () => {
    const summary = summarizeExperimentStrategy({
      factor_blend: {
        rebalance_every_n_bars: 2,
        factors: [
          { factor_id: "momentum_63d", weight: 1, direction: "higher_is_better" },
          { factor_id: "volatility_20d", weight: 0.5, direction: "lower_is_better" },
        ],
      },
    });

    expect(summary).toMatchObject({
      factorCount: 2,
      rebalanceEveryNBars: 2,
      totalAbsoluteWeight: 1.5,
      factors: [
        {
          factorId: "momentum_63d",
          weight: 1,
          weightLabel: "1.00x",
          direction: "higher_is_better",
          directionLabel: "higher is better",
        },
        {
          factorId: "volatility_20d",
          weight: 0.5,
          weightLabel: "0.50x",
          direction: "lower_is_better",
          directionLabel: "lower is better",
        },
      ],
    });
  });

  it("returns an empty summary for older experiment configs without factor_blend", () => {
    expect(summarizeExperimentStrategy({ experiment_name: "legacy" })).toEqual({
      factorCount: 0,
      factors: [],
      rebalanceEveryNBars: null,
      totalAbsoluteWeight: 0,
    });
  });
});
