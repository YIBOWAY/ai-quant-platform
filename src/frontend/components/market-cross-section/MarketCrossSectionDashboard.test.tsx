import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  MarketCrossSectionDashboard,
  MarketCrossSectionUnavailable,
} from "./MarketCrossSectionDashboard";
import type { MarketCrossSectionResponse } from "@/lib/marketCrossSection";

function payload(): MarketCrossSectionResponse {
  const symbols = ["SPY", "QQQ", "SOXX", "IGV"];
  return {
    schema_version: "1.0",
    provider: "futu",
    as_of: "2026-08-07",
    timezone: "America/New_York",
    fetched_at: "2026-08-07T21:30:00+00:00",
    provenance: "futu",
    basket: "ai_watch",
    basket_label: { en: "AI / semis watch", zh: "AI / 半导体关注" },
    methodology: { k_shape: "none" },
    rows: symbols.map((symbol, index) => ({
      symbol,
      rank: index + 1,
      returns: {
        week_pct: 1 - index,
        month_pct: 2 - index,
        ytd_pct: 10 - index,
      },
      volatility_pct: 20 + index,
      max_drawdown_pct: -4 - index,
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
  it("renders the heatmap cards and ranking with truthful badges", () => {
    const html = renderToStaticMarkup(
      <MarketCrossSectionDashboard
        basket="ai_watch"
        data={payload()}
        locale="zh"
      />,
    );

    expect(html.match(/data-market-card=/g)).toHaveLength(4);
    expect(html.match(/data-chart-provenance="real"/g)).toHaveLength(2);
    expect(html).toContain("Futu 真实行情");
    expect(html).toContain("2026-08-07");
    expect(html).toContain("美股时段");
    expect(html).toContain("SOXX");
    expect(html).toContain("YTD 热力图");
    expect(html).toContain("横截面表");
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
