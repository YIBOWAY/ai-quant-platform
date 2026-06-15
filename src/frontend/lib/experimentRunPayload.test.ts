import { describe, expect, it } from "vitest";

import { buildExperimentRunPayload, providerFromExperimentSource } from "./experimentRunPayload";

describe("buildExperimentRunPayload", () => {
  it("preserves the selected data provider instead of forcing sample", () => {
    expect(
      buildExperimentRunPayload({
        symbols: "SPY, QQQ",
        start: "2024-01-02",
        end: "2024-02-15",
        provider: "tiingo",
        lookbacks: "3,5",
        top_ns: "1,2",
        initial_cash: 100000,
        commission_bps: 1,
        slippage_bps: 5,
      }),
    ).toMatchObject({
      symbols: ["SPY", "QQQ"],
      provider: "tiingo",
      lookbacks: [3, 5],
      top_ns: [1, 2],
    });
  });

  it("maps persisted experiment sources back to backtest providers", () => {
    expect(providerFromExperimentSource("tiingo")).toBe("tiingo");
    expect(providerFromExperimentSource("tiingo: daily cache")).toBe("tiingo");
    expect(providerFromExperimentSource("futu")).toBe("futu");
    expect(providerFromExperimentSource("sample")).toBe("sample");
    expect(providerFromExperimentSource(undefined)).toBe("sample");
  });
});
