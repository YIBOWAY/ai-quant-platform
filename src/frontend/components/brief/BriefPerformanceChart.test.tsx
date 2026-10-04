import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { PaperAccountPerformanceSeriesResponse } from "@/lib/api";
import { BriefPerformanceChart } from "./BriefPerformanceChart";

const series: PaperAccountPerformanceSeriesResponse[] = [
  {
    id: "paper",
    kind: "paper",
    label: "模拟盘",
    symbol: null,
    status: "partial",
    source: "paper_account_ledger+futu_qfq_1d",
    as_of: "2026-08-24T00:00:00Z",
    error_code: null,
    points: [
      { date: "2026-08-20", return_ratio: 0, equity: 10000, close: null },
      { date: "2026-08-24", return_ratio: 0.01, equity: 10100, close: null },
    ],
  },
  {
    id: "SPY",
    kind: "benchmark",
    label: "SPY",
    symbol: "SPY",
    status: "available",
    source: "futu_cache",
    as_of: "2026-08-24T00:00:00Z",
    error_code: null,
    points: [
      { date: "2026-08-20", return_ratio: 0, equity: null, close: 600 },
      { date: "2026-08-24", return_ratio: 0.02, equity: null, close: 612 },
    ],
  },
  {
    id: "QQQ",
    kind: "benchmark",
    label: "QQQ",
    symbol: "QQQ",
    status: "unavailable",
    source: null,
    as_of: null,
    error_code: "missing_sessions",
    points: [],
  },
];

describe("BriefPerformanceChart legend", () => {
  it("localizes the series status enum for zh", () => {
    const html = renderToStaticMarkup(
      createElement(BriefPerformanceChart, {
        ariaLabel: "收益曲线",
        emptyLabel: "暂无数据",
        locale: "zh",
        series,
      }),
    );

    expect(html).toContain("部分");
    expect(html).toContain("可用");
    expect(html).toContain("不可用");
    expect(html).not.toContain("partial");
    expect(html).not.toContain("unavailable");
  });

  it("keeps the English status labels by default", () => {
    const html = renderToStaticMarkup(
      createElement(BriefPerformanceChart, {
        ariaLabel: "performance",
        emptyLabel: "No data",
        series,
      }),
    );

    expect(html).toContain("partial");
    expect(html).toContain("available");
    expect(html).toContain("unavailable");
  });
});
