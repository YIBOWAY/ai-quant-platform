import { describe, expect, it } from "vitest";

import { buildStrategyPayload } from "./strategyPayload";

describe("buildStrategyPayload", () => {
  it("normalizes strategy catalog form values from schema field types", () => {
    const fields = {
      symbols: { type: "symbol_list", default: ["SPY"] },
      lookback: { type: "integer", default: 20 },
      threshold: { type: "number", default: 0.5 },
      max_positions: { type: "integer_or_null", default: null },
      factor_weights: { type: "factor_weight_map", default: { momentum: 1 } },
      provider: { type: "provider", default: "futu" },
    };

    const payload = buildStrategyPayload(fields, {
      symbols: " AAPL, MSFT ,, QQQ ",
      lookback: "30",
      threshold: "0.75",
      max_positions: "",
      factor_weights: { momentum: 2, quality: 0.5 },
    });

    expect(payload).toEqual({
      symbols: ["AAPL", "MSFT", "QQQ"],
      lookback: 30,
      threshold: 0.75,
      max_positions: null,
      factor_weights: { momentum: 2, quality: 0.5 },
      provider: "futu",
    });
  });
});
