import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  AsiaRadarDashboard,
  AsiaRadarUnavailable,
  LocalIndexPanel,
} from "./AsiaRadarDashboard";
import type { AsiaRadarLocalIndex, AsiaRadarMarket, AsiaRadarOverview } from "@/lib/asiaRadar";

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

function availableIndex(
  symbol: string,
  nameEn: string,
  nameZh: string,
  currency: string,
  timezone: string,
): AsiaRadarLocalIndex {
  return {
    status: "available",
    index_symbol: symbol,
    index_name_en: nameEn,
    index_name_zh: nameZh,
    currency,
    timezone,
    as_of: "2026-02-12",
    provider: "futu",
    provenance: "futu",
    fetched_at: "2026-02-12T09:00:00+00:00",
    adjustment: "qfq",
    series: [
      { date: "2026-02-10", close: 20000, indexed_return_pct: 0 },
      { date: "2026-02-11", close: 20200, indexed_return_pct: 1 },
      { date: "2026-02-12", close: 20100, indexed_return_pct: 0.5 },
    ],
    reason_code: null,
    reason: null,
    provider_code: null,
  };
}

function pendingIndex(
  reasonCode: string | null,
  nameEn: string | null,
  nameZh: string | null,
): AsiaRadarLocalIndex {
  return {
    status: "unavailable",
    index_symbol: null,
    index_name_en: nameEn,
    index_name_zh: nameZh,
    currency: null,
    timezone: null,
    as_of: null,
    provider: null,
    provenance: null,
    fetched_at: null,
    adjustment: null,
    series: [],
    reason_code: reasonCode,
    reason: "backend detail",
    provider_code: null,
  };
}

function localIndexFor(symbol: string): AsiaRadarLocalIndex {
  if (symbol === "EWH") {
    return availableIndex("HK.800000", "Hang Seng Index", "恒生指数", "HKD", "Asia/Hong_Kong");
  }
  if (symbol === "EWJ") {
    return availableIndex("JP..N225", "Nikkei 225", "日经 225 指数", "JPY", "Asia/Tokyo");
  }
  if (symbol === "ASHR") {
    return pendingIndex("permission_not_granted", "CSI 300", "沪深300");
  }
  if (symbol === "EWY" || symbol === "EWT") {
    return pendingIndex("market_format_unsupported", null, null);
  }
  return pendingIndex("no_verified_channel", null, null);
}

function marketFixture(symbol: string, index: number): AsiaRadarMarket {
  return {
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
    local_index: localIndexFor(symbol),
  };
}

function overview(): AsiaRadarOverview {
  return {
    schema_version: "1.2",
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
    markets: symbols.map((symbol, index) => marketFixture(symbol, index)),
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

describe("LocalIndexPanel", () => {
  function marketWithIndex(symbol: string, localIndex: AsiaRadarLocalIndex) {
    const market = marketFixture(symbol, 0);
    market.local_index = localIndex;
    return market;
  }

  it("renders an available local index with badges, chart and ETF contrast (zh)", () => {
    const html = renderToStaticMarkup(
      <LocalIndexPanel
        locale="zh"
        market={marketWithIndex(
          "EWH",
          availableIndex("HK.800000", "Hang Seng Index", "恒生指数", "HKD", "Asia/Hong_Kong"),
        )}
      />,
    );

    expect(html).toContain('data-local-index-state="available"');
    expect(html).toContain("本地指数");
    expect(html).toContain("恒生指数");
    expect(html).toContain("HK.800000");
    expect(html).toContain("HKD");
    expect(html).toContain("本地交易日");
    expect(html).toContain("Asia/Hong_Kong");
    expect(html).toContain("2026-02-12");
    // index lane and ETF proxy lane render as two separate charts
    expect(html.match(/data-local-index-chart/g)).toHaveLength(2);
    expect(html).toContain("ETF 代理");
    expect(html).toContain("USD");
    expect(html).toContain("America/New_York");
    expect(html).toContain("区间收益");
    // the never-blended discipline is stated on the panel
    expect(html).toContain("不与美元 ETF 代理混合计算任何指标");
  });

  it("renders the English locale for the available index panel", () => {
    const html = renderToStaticMarkup(
      <LocalIndexPanel
        locale="en"
        market={marketWithIndex(
          "EWJ",
          availableIndex("JP..N225", "Nikkei 225", "日经 225 指数", "JPY", "Asia/Tokyo"),
        )}
      />,
    );

    expect(html).toContain("Local index");
    expect(html).toContain("Nikkei 225");
    expect(html).toContain("JP..N225");
    expect(html).toContain("JPY");
    expect(html).toContain("local trading day");
    expect(html).toContain("Asia/Tokyo");
    expect(html).toContain("never blended into the USD ETF proxy metrics");
  });

  it("keeps an explicit pending empty state with reason for markets without an index (zh)", () => {
    const html = renderToStaticMarkup(
      <LocalIndexPanel
        locale="zh"
        market={marketWithIndex("EWY", pendingIndex("market_format_unsupported", "KOSPI", "KOSPI 指数"))}
      />,
    );

    expect(html).toContain('data-local-index-state="pending"');
    expect(html).toContain("本地指数待接入");
    expect(html).toContain("KOSPI 指数");
    expect(html).toContain("Futu OpenD 不支持该市场的指数代码格式");
    expect(html).not.toContain("<polyline");
  });

  it("localizes the permission pending reason for China A-shares", () => {
    const zh = renderToStaticMarkup(
      <LocalIndexPanel
        locale="zh"
        market={marketWithIndex("ASHR", pendingIndex("permission_not_granted", "CSI 300", "沪深300"))}
      />,
    );
    expect(zh).toContain("Futu 账户未开通 A 股指数行情权限");
    expect(zh).toContain("沪深300");

    const en = renderToStaticMarkup(
      <LocalIndexPanel
        locale="en"
        market={marketWithIndex("ASHR", pendingIndex("permission_not_granted", "CSI 300", "沪深300"))}
      />,
    );
    expect(en).toContain("Local index not connected");
    expect(en).toContain("no A-share index quote permission");
  });

  it("renders a provider failure as an explicit error state, never a substitute curve", () => {
    const failed: AsiaRadarLocalIndex = {
      ...pendingIndex(null, null, null),
      index_symbol: "HK.800000",
      index_name_en: "Hang Seng Index",
      index_name_zh: "恒生指数",
      currency: "HKD",
      timezone: "Asia/Hong_Kong",
      provider: "futu",
      reason_code: "provider_error",
      reason: "unable to connect to OpenD at 127.0.0.1:11111",
      provider_code: "opend_unavailable",
    };
    const html = renderToStaticMarkup(
      <LocalIndexPanel locale="zh" market={marketWithIndex("EWH", failed)} />,
    );

    expect(html).toContain('data-local-index-state="provider_error"');
    expect(html).toContain("本地指数暂不可用");
    expect(html).toContain("HK.800000");
    // Raw backend internals (host/port) stay behind the details disclosure;
    // the headline shows only the curated copy plus the provider code.
    expect(html).toContain("数据源错误");
    expect(html).toContain("opend_unavailable");
    expect(html).toContain("<details");
    expect(html).toContain("unable to connect to OpenD");
    expect(html).toContain("未用任何替代曲线冒充指数");
    expect(html).not.toContain("<polyline");
    expect(html.toLowerCase()).not.toContain("sample");
  });
});
