import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { MarketCrossSectionRow } from "@/lib/marketCrossSection";
import { MarketPulse } from "./MarketPulse";

function row(symbol: string, week_pct: number, month_pct: number): MarketCrossSectionRow {
  return { symbol, rank: 1, returns: { week_pct, month_pct, ytd_pct: 10 }, volatility_pct: 20, max_drawdown_pct: -12.5, history: [], meta: { provider: "futu", symbol, currency: "USD", timezone: "America/New_York", as_of: "2026-09-04", adjustment: "qfq", provenance: "futu" } };
}

describe("MarketPulse completed comparisons", () => {
  it("reports actual aligned, divergent and flat periods instead of assigning checks to the user", () => {
    const html = renderToStaticMarkup(<MarketPulse locale="zh" period="week_pct" onPeriodChange={() => {}} rows={[row("SPY", 1, 2), row("QQQ", -1, -2), row("NVDA", 3, -4), row("META", 0, 1)]} />);
    expect(html).toContain("已比较这组 4 个标的：1 个近5日与近21日都上涨，1 个都下跌，1 个方向相反，1 个至少一个周期持平");
    expect(html).toContain("近5日 3.00% · 近21日 -4.00% · 年内最大回撤 -12.5%");
    expect(html).toContain("symbol=NVDA&amp;provider=futu");
    expect(html).not.toContain("先核对");
  });

  it("does not claim a completed comparison without any rows", () => {
    const html = renderToStaticMarkup(<MarketPulse locale="zh" period="week_pct" onPeriodChange={() => {}} rows={[]} />);
    expect(html).toContain("当前没有可比较的行情数据");
    expect(html).not.toContain("已比较");
  });
});
