import { describe, expect, it } from "vitest";

import { composeBriefLede, hungSleeveMark, marketBarsAsOf, officialHungCount } from "./briefLede";

describe("brief lede honesty", () => {
  it("treats a missing hung_count as book unavailable", () => {
    expect(officialHungCount({ apiError: "down" })).toEqual({
      hungCount: 0,
      bookAvailable: false,
    });
    expect(officialHungCount({})).toEqual({ hungCount: 0, bookAvailable: false });
  });

  it("leads with the market note when the official book is empty", () => {
    const lede = composeBriefLede({
      locale: "zh",
      hungCount: 0,
      bookAvailable: true,
      equity: "$1",
      paperReturn: "▲ 1.00%",
      performanceLabel: "近 7 日",
      marketNote: "今日四个观察指数中 0/4 收涨。",
      asiaRadarNote: "",
      digestCount: 2,
      marketAsOf: "2026-08-14",
    });
    expect(lede.startsWith("市场方面，")).toBe(true);
    expect(lede).toContain("模拟账户总资产");
    expect(lede).toContain("行情截至 2026-08-14");
    expect(lede).not.toContain("模拟盘权益报");
  });

  it("keeps hung observation language only when hung_count is positive", () => {
    const lede = composeBriefLede({
      locale: "zh",
      hungCount: 1,
      bookAvailable: true,
      equity: "$101,234.50",
      paperReturn: "▲ 1.00%",
      performanceLabel: "近 7 日",
      marketNote: "今日四个观察指数中 1/4 收涨。",
      asiaRadarNote: "",
      digestCount: 1,
      marketAsOf: "2026-08-14",
      sleeveEquity: "$10,000.00",
      sleeveObservation: "尚无成交",
    });
    expect(lede).toContain("已启用 1 条模拟策略");
    expect(lede).toContain("最近可用策略估值 $10,000.00");
    expect(lede).toContain("尚无成交");
    expect(lede).not.toContain("今晨");
    expect(lede).toContain("不代表实时资产");
    expect(lede).toContain("模拟账户总资产");
    expect(lede).toContain("历史停用策略持仓");
    expect(lede).not.toMatch(/化石|平台市场手记|已挂观察/);
    expect(lede).not.toContain("已挂观察权益报");
  });

  it("marks hung sleeves from the effect NAV instead of remaining cash", () => {
    const mark = hungSleeveMark(
      1,
      {
        hung_count: 1,
        observation_day_count: 1,
        empty: false,
        sleeve_equity: 10_009.637481431073,
        sleeve_equity_status: "available",
        sleeve_return_pct: 0,
        spy_status: "available",
        as_of: "2026-08-19",
        covered_sleeve_count: 1,
        return_method: "net_profit_over_allocated_capital",
        valuation_day_count: 1,
        valuation_status: "complete",
        series: [],
      },
      "zh",
    );
    expect(mark.equity).toBe("$10,009.64");
    expect(mark.observation).toBe("估值截至 2026-08-19 · 覆盖 1/1 条 · 成交 1 日 · 累计盈亏 / 累计投入 ▲ 0.00%");
  });

  it("distinguishes an unavailable booked effect from no observation", () => {
    const mark = hungSleeveMark(
      1,
      {
        hung_count: 1,
        observation_day_count: 1,
        empty: false,
        sleeve_equity: null,
        sleeve_equity_status: "unavailable",
        sleeve_equity_reason: "strategy_price_unavailable",
        return_method: "unavailable",
        valuation_day_count: 0,
        valuation_status: "unavailable",
        sleeve_return_pct: null,
        spy_status: "unavailable",
        series: [],
      },
      "zh",
    );

    expect(mark.equity).toBe("暂不可用");
    expect(mark.observation).toBe("1 日 · 效果暂不可用");
    expect(mark.observation).not.toBe("尚未入账");
  });

  it("uses not booked only for a true zero-day empty effect", () => {
    const mark = hungSleeveMark(
      1,
      {
        hung_count: 1,
        return_method: "unavailable",
        valuation_day_count: 0,
        valuation_status: "unavailable",
        observation_day_count: 0,
        empty: true,
        sleeve_equity: null,
        sleeve_equity_status: "empty",
        sleeve_return_pct: null,
        spy_status: "empty",
        series: [],
      },
      "zh",
    );

    expect(mark.equity).toBe("暂不可用");
    expect(mark.observation).toBe("尚无成交");
    expect(mark.observation).not.toBe("效果暂不可用");
  });

  it("dates cash-only valuation without inventing a trading return sample", () => {
    const mark = hungSleeveMark(1, {
      hung_count: 1, observation_day_count: 0, empty: false,
      sleeve_equity: 10000, sleeve_equity_status: "available", sleeve_return_pct: null,
      as_of: "2026-09-10", covered_sleeve_count: 1,
      return_method: "unavailable", spy_status: "unavailable", series: [],
      valuation_day_count: 1, valuation_status: "complete",
    }, "zh");
    expect(mark.equity).toBe("$10,000.00");
    expect(mark.observation).toContain("估值截至 2026-09-10 · 覆盖 1/1 条");
    expect(mark.observation).toContain("暂无交易收益样本");
    expect(mark.observation).not.toContain("0.00%");
  });

  it.each([
    ["api error", { apiError: "down" }],
    ["book/effect mismatch", { hung_count: 2 }],
  ])("marks %s as unavailable instead of not booked", (_label, override) => {
    const mark = hungSleeveMark(
      1,
      {
        hung_count: 1,
        return_method: "unavailable",
        valuation_day_count: 0,
        valuation_status: "unavailable",
        observation_day_count: 0,
        empty: true,
        sleeve_equity: null,
        sleeve_equity_status: "empty",
        sleeve_return_pct: null,
        spy_status: "empty",
        series: [],
        ...override,
      },
      "zh",
    );

    expect(mark.equity).toBe("暂不可用");
    expect(mark.observation).toBe("效果暂不可用");
    expect(mark.observation).not.toBe("尚未入账");
  });

  it("picks the latest calendar day from market bars", () => {
    expect(marketBarsAsOf(["2026-08-11T00:00:00Z", "2026-08-14T20:00:00Z"])).toBe(
      "2026-08-14",
    );
  });
});
