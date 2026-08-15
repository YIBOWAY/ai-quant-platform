import { describe, expect, it } from "vitest";

import type { PaperStrategyConfigResponse } from "./api";
import {
  formatStrategyConfigOptionLabel,
  hasStrategyConfigNameConflict,
  suggestNextStrategyConfigName,
} from "./paperStrategySleeves";

function config(
  id: string,
  name: string,
  version = 1,
  createdAt = "2026-06-26T08:29:16.000Z",
): PaperStrategyConfigResponse {
  return {
    strategy_config_id: id,
    version,
    name,
    description: "",
    strategy_id: "cross_sectional_top_n",
    universe_id: null,
    symbols: ["SPY", "QQQ"],
    factor_ids: [],
    weights: {},
    lookback: 20,
    top_n: 2,
    rebalance_frequency: "daily",
    max_weight_per_symbol: 1,
    min_order_value: 0,
    data_provider: "futu",
    execution_timing: "next_open",
    created_at: createdAt,
    updated_at: createdAt,
    archived: false,
    tags: [],
    metadata: {},
  };
}

describe("paper strategy sleeve UI helpers", () => {
  it("keeps duplicate config option labels distinguishable", () => {
    const configs = [
      config("strategy-config-aaa111bbb222", "动量策略仓配置"),
      config("strategy-config-ccc333ddd444", "动量策略仓配置"),
    ];

    expect(formatStrategyConfigOptionLabel(configs[0], configs)).toBe(
      "动量策略仓配置 v1 · aaa111",
    );
    expect(formatStrategyConfigOptionLabel(configs[1], configs)).toBe(
      "动量策略仓配置 v1 · ccc333",
    );
  });

  it("detects active config names that only differ by case or whitespace", () => {
    const configs = [config("strategy-config-aaa111bbb222", "Sleeve Top-N")];

    expect(hasStrategyConfigNameConflict(" sleeve top-n ", configs)).toBe(true);
  });

  it("suggests the next readable config name after creation", () => {
    const configs = [
      config("strategy-config-aaa111bbb222", "动量策略仓配置"),
      config("strategy-config-ccc333ddd444", "动量策略仓配置 2"),
    ];

    expect(suggestNextStrategyConfigName("动量策略仓配置", configs)).toBe(
      "动量策略仓配置 3",
    );
  });
});
