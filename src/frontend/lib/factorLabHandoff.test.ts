import { describe, expect, it } from "vitest";

import { buildFactorLabBacktestHref } from "./factorLabHandoff";

describe("buildFactorLabBacktestHref", () => {
  it("carries the current Factor Lab context into the Backtester form", () => {
    expect(
      buildFactorLabBacktestHref({
        provider: "tiingo",
        universeId: "nasdaq100",
        benchmarkSymbol: "QQQ",
        start: "2023-01-03",
        end: "2023-12-29",
        lookback: 63,
        factorIds: ["momentum", "volatility", "liquidity"],
        locale: "en",
      }),
    ).toBe(
      "/en/backtest?provider=tiingo&universe_id=nasdaq100&benchmark_symbol=QQQ&start=2023-01-03&end=2023-12-29&lookback=63&factor_ids=momentum%2Cvolatility%2Cliquidity",
    );
  });

  it("normalizes symbols and preserves localized routes", () => {
    expect(
      buildFactorLabBacktestHref({
        provider: "futu",
        universeId: "etf",
        benchmarkSymbol: "qqq",
        start: "2024-01-02",
        end: "2024-12-31",
        lookback: 20,
        factorIds: ["rsi"],
        locale: "zh",
      }),
    ).toBe(
      "/zh/backtest?provider=futu&universe_id=etf&benchmark_symbol=QQQ&start=2024-01-02&end=2024-12-31&lookback=20&factor_ids=rsi",
    );
  });
});
