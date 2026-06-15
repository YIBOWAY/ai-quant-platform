import { describe, expect, it } from "vitest";

import { accountRebalanceStrategies } from "./accountRebalanceStrategies";
import type { StrategyMetadata } from "./api";

function strategy(
  id: string,
  supportsAccountRebalance: boolean | undefined,
): StrategyMetadata {
  return {
    id,
    name: id,
    description: "",
    paper_source: null,
    run_endpoint:
      id === "reversal_momentum"
        ? "/api/replications/reversal-momentum/run"
        : "/api/backtests/run",
    result_type: id === "reversal_momentum" ? "replication" : "backtest",
    parameter_schema: {},
    default_payload: {},
    supports_account_rebalance: supportsAccountRebalance,
  };
}

describe("accountRebalanceStrategies", () => {
  it("uses backend metadata to hide strategies that cannot rebalance the account", () => {
    const visible = accountRebalanceStrategies([
      strategy("cross_sectional_top_n", true),
      strategy("reversal_momentum", false),
      strategy("mean_reversion_top_n", true),
    ]);

    expect(visible.map((item) => item.id)).toEqual([
      "cross_sectional_top_n",
      "mean_reversion_top_n",
    ]);
  });

  it("keeps a conservative fallback when the strategy API is unavailable", () => {
    expect(accountRebalanceStrategies([]).map((item) => item.id)).toEqual([
      "cross_sectional_top_n",
      "mean_reversion_top_n",
    ]);
  });
});
