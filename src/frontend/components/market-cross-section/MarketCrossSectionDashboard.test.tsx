import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  MarketCrossSectionDashboard,
  MarketCrossSectionUnavailable,
} from "./MarketCrossSectionDashboard";
import type { MarketCrossSectionResponse } from "@/lib/marketCrossSection";

function payload(): MarketCrossSectionResponse {
  // Deliberately shuffled ranks: rows arrive out of order and the component
  // must re-sort by rank. If the sort is removed this fixture fails.
  const rows: Array<[string, number]> = [
    ["SPY", 2],
    ["QQQ", 4],
    ["SOXX", 1],
    ["IGV", 3],
  ];
  return {
    schema_version: "1.0",
    provider: "futu",
    as_of: "2026-08-07",
    timezone: "America/New_York",
    fetched_at: "2026-08-07T21:30:00+00:00",
    provenance: "futu",
    basket: "ai_watch",
    basket_label: { en: "AI watch (server label)", zh: "AI 关注（服务端下发）" },
    methodology: {
      week: "5 trading sessions",
      month: "21 trading sessions",
      ytd: "calendar year first available close through latest shared session",
      volatility: "63-session annualized realized volatility",
      drawdown: "calendar-year maximum drawdown through latest shared session",
    },
    rows: rows.map(([symbol, rank]) => ({
      symbol,
      rank,
      returns: {
        week_pct: 5 - rank,
        month_pct: 6 - rank,
        ytd_pct: 20 - rank * 3,
      },
      volatility_pct: 20 + rank,
      max_drawdown_pct: -4 - rank,
      history: [
        { date: "2026-08-06", close: 100, indexed_return_pct: 0 },
        { date: "2026-08-07", close: 101, indexed_return_pct: 1 },
      ],
      meta: {
        provider: "futu",
        symbol,
        currency: "USD",
        timezone: "America/New_York",
        as_of: "2026-08-07",
        adjustment: "qfq",
        provenance: "futu",
      },
    })),
  };
}

describe("MarketCrossSectionDashboard", () => {
  it("renders heatmap cards and table rows sorted by rank, not input order", () => {
    const html = renderToStaticMarkup(
      <MarketCrossSectionDashboard
        basket="ai_watch"
        data={payload()}
        locale="zh"
      />,
    );

    expect(html.match(/data-market-card=/g)).toHaveLength(4);
    const cardOrder = [...html.matchAll(/data-market-card="([A-Z]+)"/g)].map(
      (match) => match[1],
    );
    expect(cardOrder).toEqual(["SOXX", "SPY", "IGV", "QQQ"]);
    const tableRanks = [
      ...html.matchAll(/<td class="py-3 font-mono text-text-secondary">(\d+)<\/td>/g),
    ].map((match) => Number(match[1]));
    expect(tableRanks).toEqual([1, 2, 3, 4]);
  });

  it("renders truthful badges without a hardcoded ETF tag", () => {
    const html = renderToStaticMarkup(
      <MarketCrossSectionDashboard
        basket="ai_watch"
        data={payload()}
        locale="zh"
      />,
    );

    expect(html.match(/data-chart-provenance="real"/g)).toHaveLength(2);
    expect(html).toContain("Futu 真实行情");
    expect(html).toContain("2026-08-07");
    expect(html).toContain("美股时段");
    expect(html).toContain("YTD 热力图");
    expect(html).toContain("横截面表");
    // ai_watch holds individual stocks; no blanket "ETF" badge may appear.
    expect(html).not.toContain(">ETF<");
  });

  it("surfaces the backend basket_label and methodology instead of dropping them", () => {
    const html = renderToStaticMarkup(
      <MarketCrossSectionDashboard
        basket="ai_watch"
        data={payload()}
        locale="zh"
      />,
    );

    expect(html).toContain("AI 关注（服务端下发）");
    expect(html.match(/data-methodology-item=/g)).toHaveLength(5);
    expect(html).toContain("week: 5 trading sessions");
    expect(html).toContain("volatility: 63-session annualized realized volatility");
  });

  it("falls back to local basket copy when the backend label is absent", () => {
    const data = { ...payload(), basket_label: null };
    const html = renderToStaticMarkup(
      <MarketCrossSectionDashboard basket="ai_watch" data={data} locale="en" />,
    );

    expect(html).toContain("AI / semis watch");
  });

  it("renders a fail-closed provider error without any substitute curve", () => {
    const html = renderToStaticMarkup(
      <MarketCrossSectionUnavailable locale="zh" message="Futu OpenD unavailable" />,
    );

    expect(html).toContain("Futu OpenD unavailable");
    expect(html).toContain("未使用替代曲线");
    expect(html.toLowerCase()).not.toContain("sample");
  });
});
