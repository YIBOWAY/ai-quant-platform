import { describe, expect, it } from "vitest";

import {
  resultDisplayTitle,
  resultFreshnessLabel,
  resultReadStatusLabel,
  resultStatusLabel,
  resultSummaryText,
} from "./resultsPresentation";

describe("Hermes result presentation", () => {
  it("marks stale automation as an expired historical snapshot", () => {
    const item = {
      kind: "automation_status" as const,
      resource_id: "automation_status:cd47dc43c404f7b3730fcce2",
      display_title: "Automation · fresh",
      summary: "4 scheduled jobs",
      status: "available",
      freshness: "stale" as const,
      occurred_at: "2026-08-17T09:07:25Z",
    };

    expect(resultDisplayTitle(item, "zh")).toBe("自动化历史快照");
    expect(resultSummaryText(item, "zh")).toBe("该记录已经过期，不能代表当前自动化运行状态。");
    expect(resultFreshnessLabel("stale", "zh")).toBe("历史快照 · 已过期");
  });

  it("uses exact Chinese names for current legacy candidates and a kind fallback for future English titles", () => {
    expect(
      resultDisplayTitle(
        {
          kind: "factor_candidate",
          resource_id: "factor-reproduce_arxiv_1904_04912_classical_mul-6fc8e027a7",
          display_title: "reproduce arXiv 1904.04912 classical multi-scale MACD TSMOM",
          summary: "factor · SPY, QQQ",
          status: "approved",
          freshness: "not_applicable",
          occurred_at: "2026-08-10T09:34:38Z",
        },
        "zh",
      ),
    ).toBe("经典多周期 MACD 时间序列动量复现");

    const future = {
      kind: "factor_candidate" as const,
      resource_id: "factor-future-0123456789abcdef",
      display_title: "Future English-only generated candidate",
      summary: "English-only summary",
      display_title_zh: "成交量异动因子候选",
      summary_zh: "标的范围：SPY、QQQ",
      status: "approved",
      freshness: "not_applicable" as const,
      occurred_at: "2026-08-25T00:00:00Z",
    };
    expect(resultDisplayTitle(future, "zh")).toBe("成交量异动因子候选");
    expect(resultSummaryText(future, "zh")).toBe("标的范围：SPY、QQQ");
  });

  it("localizes known titles and every visible status token", () => {
    expect(
      resultDisplayTitle(
        {
          kind: "backtest",
          resource_id: "backtest-1",
          display_title: "cross_sectional_top_n · SPY, QQQ",
          summary: null,
          status: "completed",
          freshness: "not_applicable",
          occurred_at: "2026-08-25T00:00:00Z",
        },
        "zh",
      ),
    ).toBe("横截面 Top-N · SPY、QQQ");
    expect(resultStatusLabel("completed", "zh")).toBe("已完成");
    expect(resultStatusLabel("brand_new_internal_state", "zh")).toBe("状态待确认");
    expect(resultReadStatusLabel("available", "zh")).toBe("可读取");
  });
});
