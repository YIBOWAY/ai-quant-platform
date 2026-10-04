import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarketRiskPanel } from "./MarketRiskPanel";
import type { MarketRiskResponse } from "@/lib/marketCrossSection";

describe("MarketRiskPanel", () => {
  it("keeps stale term data unavailable with its original date instead of displaying zero or normal", () => {
    const risk: MarketRiskResponse = {
      status: "unavailable", expected_session: "2026-09-04", trend_extension_pct: 15,
      attention_count: 0, unavailable_count: 1,
      observations: [{ key: "vix_term", symbol: "VIX / VIX3M", source: "public_cache", as_of: "2026-07-17", value: null, threshold: 1, status: "unavailable", reason: "volatility_stale" }],
    };
    const html = renderToStaticMarkup(<MarketRiskPanel risk={risk} locale="zh" />);
    expect(html).toContain('data-market-risk="unavailable"');
    expect(html).toContain("2026-07-17");
    expect(html).toContain("波动数据过期");
    expect(html).toContain("当前观察范围的价格和波动");
    expect(html).toContain("不是崩盘预测");
    expect(html).not.toContain("0.00");
    expect(html).not.toContain("未触发观察规则");
  });

  it("shows the observed pressure and threshold in English, and has an honest missing-response state", () => {
    const risk: MarketRiskResponse = {
      status: "attention", expected_session: "2026-09-04", trend_extension_pct: 15,
      attention_count: 1, unavailable_count: 0,
      observations: [{ key: "drawdown_252d", symbol: "SPY", source: "futu_cache", as_of: "2026-09-04", value: -12.5, threshold: -10, status: "attention", reason: "drawdown_pressure" }],
    };
    const html = renderToStaticMarkup(<MarketRiskPanel risk={risk} locale="en" />);
    expect(html).toContain("Pressure observed");
    expect(html).toContain("-12.50%");
    expect(html).toContain("≤ -10%");
    expect(html).toContain("Futu · cache · QFQ");
    const missing = renderToStaticMarkup(<MarketRiskPanel locale="zh" />);
    expect(missing).toContain('data-market-risk="unavailable"');
    expect(missing).toContain("不能据此判断市场正常");
  });
});
