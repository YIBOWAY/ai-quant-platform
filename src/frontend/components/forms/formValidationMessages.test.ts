import { describe, expect, it } from "vitest";

import { buildBacktestSchema } from "./BacktestForm";
import { buildExperimentSchema } from "./ExperimentRunForm";
import { buildPmSchema } from "./PMRunForm";

const validBacktest = {
  symbols: "SPY,QQQ",
  universe_id: "etf",
  strategy_id: "cross_sectional_top_n",
  benchmark_symbol: "SPY",
  factor_ids: ["momentum"],
  weights: { momentum: 1 },
  start: "2024-01-02",
  end: "2024-02-15",
  provider: "futu",
  lookback: 20,
  top_n: 3,
  initial_cash: 100000,
  commission_bps: 1,
  slippage_bps: 5,
  min_order_value: 0,
  whole_share_orders: false,
  rebalance_frequency: "every_bar",
  max_weight_per_symbol: "",
};

const validExperiment = {
  symbols: "SPY,QQQ,IWM,DIA",
  start: "2024-01-02",
  end: "2024-02-15",
  provider: "futu",
  lookbacks: "3,5,10",
  top_ns: "1,2",
  walk_forward_enabled: false,
  walk_forward_train_bars: 12,
  walk_forward_validation_bars: 5,
  walk_forward_step_bars: 5,
  initial_cash: 100000,
  commission_bps: 1,
  slippage_bps: 5,
};

const validPm = {
  provider: "polymarket",
  cache_mode: "prefer_cache",
  min_edge_bps: 200,
  max_capital_per_leg: 1000,
  capital_limit: 1000,
  max_legs: 3,
  max_markets: 20,
  fee_bps: 0,
};

function issueMessages(result: { success: boolean; error?: { issues: Array<{ message: string }> } }) {
  expect(result.success).toBe(false);
  return result.error?.issues.map((issue) => issue.message) ?? [];
}

describe("BacktestForm schema messages", () => {
  it.each(["en", "zh"] as const)("rejects a reversed date range before submission in %s", (locale) => {
    const result = buildBacktestSchema(locale).safeParse({
      ...validBacktest, start: "2024-02-01", end: "2024-01-01",
    });
    expect(issueMessages(result)).toContain(locale === "zh"
      ? "结束日期不能早于开始日期"
      : "End date must be on or after start date");
    expect(result.error?.issues[0].path).toEqual(["end"]);
  });

  it("reports localized zh messages for invalid input", () => {
    const messages = issueMessages(
      buildBacktestSchema("zh").safeParse({
        ...validBacktest,
        universe_id: "",
        strategy_id: "",
        benchmark_symbol: "",
        factor_ids: [],
        start: "",
        end: "",
        lookback: Number.NaN,
        top_n: 0,
        initial_cash: -1,
        commission_bps: -1,
        max_weight_per_symbol: "2",
      }),
    );

    expect(messages).toContain("请选择股票池");
    expect(messages).toContain("请选择策略");
    expect(messages).toContain("请输入基准");
    expect(messages).toContain("请至少选择一个因子");
    expect(messages).toContain("请选择开始日期");
    expect(messages).toContain("请选择结束日期");
    expect(messages).toContain("请输入有效数字");
    expect(messages).toContain("请输入正整数");
    expect(messages).toContain("请输入大于 0 的数字");
    expect(messages).toContain("请输入不小于 0 的数字");
    expect(messages).toContain("请输入 0 到 1 之间的权重");
  });

  it("keeps English messages for the en locale", () => {
    const messages = issueMessages(
      buildBacktestSchema("en").safeParse({
        ...validBacktest,
        universe_id: "",
        factor_ids: [],
        start: "",
        lookback: Number.NaN,
        max_weight_per_symbol: "2",
      }),
    );

    expect(messages).toContain("Select a universe");
    expect(messages).toContain("Select at least one factor");
    expect(messages).toContain("Start date is required");
    expect(messages).toContain("Enter a valid number");
    expect(messages).toContain("Enter a weight between 0 and 1");
  });

  it.each(["en", "zh"] as const)("accepts a valid payload in %s", (locale) => {
    expect(buildBacktestSchema(locale).safeParse(validBacktest).success).toBe(true);
  });
});

describe("ExperimentRunForm schema messages", () => {
  it("reports localized zh messages for invalid input", () => {
    const messages = issueMessages(
      buildExperimentSchema("zh").safeParse({
        ...validExperiment,
        symbols: "",
        start: "",
        end: "",
        lookbacks: "",
        top_ns: "",
        walk_forward_train_bars: 0,
        initial_cash: Number.NaN,
      }),
    );

    expect(messages).toContain("请至少输入两个标的");
    expect(messages).toContain("请选择开始日期");
    expect(messages).toContain("请选择结束日期");
    expect(messages).toContain("请至少输入一个回看窗口");
    expect(messages).toContain("请至少输入一个 Top N");
    expect(messages).toContain("请输入正整数");
    expect(messages).toContain("请输入有效数字");
  });

  it("keeps English messages for the en locale", () => {
    const messages = issueMessages(
      buildExperimentSchema("en").safeParse({
        ...validExperiment,
        symbols: "",
        lookbacks: "",
        walk_forward_step_bars: 0,
      }),
    );

    expect(messages).toContain("Enter at least two symbols");
    expect(messages).toContain("Enter at least one lookback");
    expect(messages).toContain("Enter a positive integer");
  });

  it.each(["en", "zh"] as const)("accepts a valid payload in %s", (locale) => {
    expect(buildExperimentSchema(locale).safeParse(validExperiment).success).toBe(true);
  });
});

describe("PMRunForm schema messages", () => {
  it("reports localized zh messages for invalid input", () => {
    const messages = issueMessages(
      buildPmSchema("zh").safeParse({
        ...validPm,
        min_edge_bps: -1,
        max_legs: 0,
        fee_bps: Number.NaN,
      }),
    );

    expect(messages).toContain("请输入不小于 0 的数字");
    expect(messages).toContain("请输入正整数");
    expect(messages).toContain("请输入有效数字");
  });

  it("keeps English messages for the en locale", () => {
    const messages = issueMessages(
      buildPmSchema("en").safeParse({
        ...validPm,
        capital_limit: -1,
        max_markets: 0,
      }),
    );

    expect(messages).toContain("Enter a non-negative number");
    expect(messages).toContain("Enter a positive integer");
  });

  it.each(["en", "zh"] as const)("accepts a valid payload in %s", (locale) => {
    expect(buildPmSchema(locale).safeParse(validPm).success).toBe(true);
  });
});
