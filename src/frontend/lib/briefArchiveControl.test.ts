import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { BriefArchiveControl } from "@/components/brief/BriefArchiveControl";
import { BriefDailyChange } from "@/components/brief/BriefDailyChange";
import { BriefPerformanceChart } from "@/components/brief/BriefPerformanceChart";
import { BriefPerformanceRangeSelector } from "@/components/brief/BriefPerformanceRangeSelector";
import {
  normalizeBriefIssueEnvelope,
  type BriefArchivePayload,
  type BriefSourceWatermark,
} from "./briefArchive";
import {
  buildBriefPerformanceSnapshot,
  parseBriefPerformanceRange,
  resolveBriefArchiveBlockedReason,
  selectBriefPerformanceResponse,
  selectBriefPerformanceSeries,
} from "./briefPerformance";

const payload = {
  schema_version: "brief_snapshot_v1",
  title: "每日晨报",
  issue_date: "2026-07-14",
  locale: "zh",
  generated_at: "2026-07-14T08:30:00Z",
  lede: "事实摘要",
  account: {
    account_id: "default",
    base_currency: "USD",
    equity: 1,
    cash: 1,
    pnl_abs: 0,
    pnl_pct: 0,
    invested_pct: 0,
    price_source: { kind: "file", as_of: null },
    positions: [],
  },
  paper_equity: [],
  markets: [],
  market_note: "无行情",
  ai_news: [],
  hermes_log: [],
  warnings: [],
} satisfies BriefArchivePayload;

const watermark = {
  captured_at: "2026-07-14T08:30:00Z",
  sources: [],
} satisfies BriefSourceWatermark;

describe("BriefArchiveControl", () => {
  it("blocks a new archive when the 3m performance master request failed", () => {
    expect(resolveBriefArchiveBlockedReason(null, "performance unavailable")).toBe(
      "performance unavailable",
    );
    expect(resolveBriefArchiveBlockedReason("account unavailable", null)).toBe(
      "account unavailable",
    );
  });

  it("disables persistence when a critical factual source is unavailable", () => {
    const html = renderToStaticMarkup(
      createElement(BriefArchiveControl, {
        initialPublicId: null,
        locale: "zh",
        payload,
        sourceWatermark: watermark,
        disabledReason: "模拟账户不可用，不能归档",
      }),
    );

    expect(html).toContain("disabled");
    expect(html).toContain("模拟账户不可用，不能归档");
  });

  it("renders archive history links when prior issues exist", () => {
    const html = renderToStaticMarkup(
      createElement(BriefArchiveControl, {
        history: [
          { publicId: "brf_20260714_kxsm9b", issueDate: "2026-07-14" },
          { publicId: "brf_20260710_3yz4rm", issueDate: "2026-07-10" },
        ],
        initialPublicId: null,
        locale: "zh",
        payload,
        sourceWatermark: watermark,
      }),
    );

    expect(html).toContain("brief-archive-history");
    expect(html).toContain("历史归档");
    expect(html).toContain("/zh/brief/brf_20260714_kxsm9b");
    expect(html).toContain("2026-07-14");
    expect(html).toContain("2026-07-10");
  });

  it("keeps old v1 archives readable when additive fields are absent or null", () => {
    const archive = normalizeBriefIssueEnvelope({
      issue: {
        issue_id: "issue-legacy",
        public_id: "brf_legacy",
        issue_date: "2026-07-14",
        locale: "zh",
        status: "published",
      },
      snapshot: {
        snapshot_id: "snapshot-legacy",
        version: 1,
        payload: { ...payload, performance: null },
        source_watermark: {
          captured_at: watermark.captured_at,
          sources: [
            {
              name: "paper_account",
              status: "available",
              as_of: null,
              detail: "file",
              provider: null,
              served_from: null,
            },
          ],
        },
      },
      warnings: [],
    });

    expect(archive.payload).not.toBeNull();
    expect(archive.payload?.performance).toBeNull();
    expect(archive.sourceWatermark?.sources[0]?.provider).toBeNull();
  });
});

describe("Brief performance", () => {
  const performance = {
    account_id: "default",
    account_exists: true,
    range: "3m" as const,
    granularity: "1d" as const,
    benchmarks: ["SPY", "QQQ"] as Array<"SPY" | "QQQ">,
    requested_start: "2026-04-27",
    requested_end: "2026-07-27",
    actual_start: "2026-04-28",
    actual_end: "2026-07-27",
    coverage_complete: true,
    series: [
      {
        id: "paper",
        kind: "paper" as const,
        label: "模拟盘",
        symbol: null,
        status: "available" as const,
        source: "paper_account_ledger+futu_qfq_1d",
        as_of: "2026-07-28T01:00:00Z",
        error_code: null,
        points: [
          { date: "2026-04-28", return_ratio: 0, equity: 1_000_000, close: null },
          { date: "2026-07-22", return_ratio: 0.04, equity: 1_040_000, close: null },
          { date: "2026-07-27", return_ratio: 0.05, equity: 1_050_000, close: null },
        ],
      },
      {
        id: "SPY",
        kind: "benchmark" as const,
        label: "SPY",
        symbol: "SPY",
        status: "available" as const,
        source: "futu_cache",
        as_of: "2026-07-28T01:00:00Z",
        error_code: null,
        points: [
          { date: "2026-04-28", return_ratio: 0, equity: null, close: 570 },
          { date: "2026-07-22", return_ratio: 0.07, equity: null, close: 609.9 },
          { date: "2026-07-27", return_ratio: 0.08, equity: null, close: 615.6 },
        ],
      },
      {
        id: "QQQ",
        kind: "benchmark" as const,
        label: "QQQ",
        symbol: "QQQ",
        status: "available" as const,
        source: "futu",
        as_of: "2026-07-28T01:00:00Z",
        error_code: null,
        points: [
          { date: "2026-04-28", return_ratio: 0, equity: null, close: 500 },
          { date: "2026-07-22", return_ratio: 0.09, equity: null, close: 545 },
          { date: "2026-07-27", return_ratio: 0.1, equity: null, close: 550 },
        ],
      },
    ],
    warnings: [],
  };

  it("parses the public range contract and archives a 3m master series", () => {
    expect(parseBriefPerformanceRange("1m")).toBe("1m");
    expect(parseBriefPerformanceRange("unknown")).toBe("7d");

    const snapshot = buildBriefPerformanceSnapshot(performance, "1m");

    expect(snapshot.selected_range).toBe("1m");
    expect(snapshot.master_range).toBe("3m");
    expect(snapshot.series).toHaveLength(3);
    expect(snapshot.series[0]?.points.at(-1)?.return_ratio).toBe(0.05);

    const selected = selectBriefPerformanceSeries(
      { ...snapshot, selected_range: "7d" },
    );
    expect(selected[0]?.points.map((point) => point.date)).toEqual([
      "2026-07-22",
      "2026-07-27",
    ]);
    expect(selected[0]?.points[0]?.return_ratio).toBe(0);
    expect(selected[0]?.points.at(-1)?.return_ratio).toBeCloseTo(
      1.05 / 1.04 - 1,
    );

    const response = selectBriefPerformanceResponse(performance, "7d");
    expect(response.range).toBe("7d");
    expect(response.requested_start).toBe("2026-07-21");
    expect(response.actual_start).toBe("2026-07-22");
    expect(response.actual_end).toBe("2026-07-27");
    expect(response.series[0]?.points).toEqual(selected[0]?.points);
  });

  it("renders localized range links and all three dated series", () => {
    const selector = renderToStaticMarkup(
      createElement(BriefPerformanceRangeSelector, {
        locale: "zh",
        selectedRange: "1m",
      }),
    );
    expect(selector).toContain("/zh/brief?range=7d");
    expect(selector).toContain("/zh/brief?range=1m");
    expect(selector).toContain("aria-current=\"page\"");

    const chart = renderToStaticMarkup(
      createElement(BriefPerformanceChart, {
        ariaLabel: "模拟盘与基准收益",
        emptyLabel: "暂无数据",
        series: performance.series,
      }),
    );
    expect(chart).toContain("data-series-id=\"paper\"");
    expect(chart).toContain("data-series-id=\"SPY\"");
    expect(chart).toContain("data-series-id=\"QQQ\"");
    expect(chart).toContain("2026-04-28");
    expect(chart).toContain("2026-07-27");
  });

  it("renders positive daily change green, negative red, and missing as unknown", () => {
    const positive = renderToStaticMarkup(
      createElement(BriefDailyChange, { value: 0.0125 }),
    );
    const negative = renderToStaticMarkup(
      createElement(BriefDailyChange, { value: -0.008 }),
    );
    const missing = renderToStaticMarkup(
      createElement(BriefDailyChange, { value: null }),
    );

    expect(positive).toContain("text-editorial-up");
    expect(positive).toContain("+1.25%");
    expect(negative).toContain("text-editorial-down");
    expect(negative).toContain("-0.80%");
    expect(missing).toContain("--");
  });
});
