import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  AsiaRadarDashboard,
  AsiaRadarUnavailable,
} from "./AsiaRadarDashboard";
import type { AsiaRadarOverview } from "@/lib/asiaRadar";

const symbols = [
  "EWY",
  "EWT",
  "EWJ",
  "ASHR",
  "INDA",
  "EIDO",
  "EWH",
  "EWS",
  "THD",
  "EWM",
  "EWA",
  "EPHE",
];

function overview(): AsiaRadarOverview {
  return {
    schema_version: "1.1",
    provider: "futu",
    as_of: "2026-02-13",
    timezone: "America/New_York",
    fetched_at: "2026-02-13T09:30:00+00:00",
    provenance: "futu",
    methodology: {
      week: "5 trading sessions",
      month: "21 trading sessions",
      ytd: "calendar year first available close through latest shared session",
      volatility: "63-session annualized realized volatility",
      drawdown: "calendar-year maximum drawdown through latest shared session",
      k_shape: "daily YTD cross-sectional top-three / bottom-three baskets",
    },
    markets: symbols.map((symbol, index) => ({
      market_id: symbol.toLowerCase(),
      name_en: symbol,
      name_zh: symbol,
      symbol,
      data_status: "real",
      market_coverage: "proxy",
      rank: index + 1,
      k_leg: index < 3 ? "winner" : index > 8 ? "laggard" : "middle",
      returns: {
        week_pct: 2 - index / 10,
        month_pct: 4 - index / 5,
        ytd_pct: 12 - index,
      },
      volatility_pct: 18 + index,
      max_drawdown_pct: -5 - index,
      history: [
        { date: "2026-02-12", close: 100, indexed_return_pct: 0 },
        { date: "2026-02-13", close: 101, indexed_return_pct: 1 },
      ],
      meta: {
        provider: "futu",
        symbol,
        currency: "USD",
        timezone: "America/New_York",
        as_of: "2026-02-13",
        adjustment: "qfq",
        provenance: "futu",
      },
    })),
    k_shape: {
      winners: ["EWY", "EWT", "EWJ"],
      laggards: ["EPHE", "EWA", "EWM"],
      series: [
        {
          date: "2026-02-12",
          winner_avg_pct: 8,
          laggard_avg_pct: -3,
          spread_pct: 11,
        },
        {
          date: "2026-02-13",
          winner_avg_pct: 9,
          laggard_avg_pct: -4,
          spread_pct: 13,
        },
      ],
    },
  };
}

describe("AsiaRadarDashboard", () => {
  it("shows the 12 real Futu ETF proxies, three truthful chart badges, and detail tabs", () => {
    const html = renderToStaticMarkup(
      <AsiaRadarDashboard locale="zh" overview={overview()} />,
    );

    expect(html.match(/data-market-card=/g)).toHaveLength(12);
    expect(html.match(/data-chart-provenance="real-proxy"/g)).toHaveLength(3);
    expect(html.match(/data-chart-title="visible"/g)).toHaveLength(3);
    expect(html).toContain("Futu 真实行情");
    expect(html).toContain("ETF 代理");
    expect(html).toContain("2026-02-13");
    expect(html).toContain("America/New_York");
    expect(html).toContain("指数");
    expect(html).toContain("ETF 代理");
    expect(html).toContain("龙头驱动");
    expect(html).toContain("EWY");
    expect(html).toContain("EPHE");
    // methodology copy is surfaced for auditability
    expect(html).toContain("top-three / bottom-three");
  });

  it("renders a fail-closed provider error without any sample curve", () => {
    const html = renderToStaticMarkup(
      <AsiaRadarUnavailable locale="zh" message="Futu OpenD unavailable" />,
    );

    expect(html).toContain("Futu OpenD unavailable");
    expect(html).toContain("未使用替代曲线");
    expect(html.toLowerCase()).not.toContain("sample");
    expect(html).not.toContain("<polyline");
  });

  it("renders dynamic winners/laggards from payload, not hardcoded names", () => {
    const payload = overview();
    payload.k_shape = {
      winners: ["THD", "EWM", "EPHE"],
      laggards: ["EWY", "EWT", "EWJ"],
      series: payload.k_shape.series,
    };
    const html = renderToStaticMarkup(
      <AsiaRadarDashboard locale="zh" overview={payload} />,
    );
    expect(html).toContain("THD · EWM · EPHE");
  });

  it("shows an honest empty state when the K-shape series is empty", () => {
    const payload = overview();
    payload.k_shape = { winners: [], laggards: [], series: [] };
    const html = renderToStaticMarkup(
      <AsiaRadarDashboard locale="zh" overview={payload} />,
    );
    expect(html).toContain("当前自然年尚无可用的 K 型序列");
    expect(html).not.toContain("spread +");
  });
});
