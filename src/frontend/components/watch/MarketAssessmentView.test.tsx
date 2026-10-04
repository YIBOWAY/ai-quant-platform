import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarketAssessmentPanel, marketFactorSection } from "./MarketAssessmentView";
import type { MarketAssessment } from "@/lib/marketAssessment";

const aiAnalysis = { model: "grok-4.5", reasoning_effort: "high" as const, input_digest: "current", generated_at: "2026-09-05T03:01:00Z", summary: "估值与价格信号存在差异。", actions: ["当前数据不支持仅凭估值高就判断马上崩盘。"], scenarios: ["跌破长期均线会改变当前结论。"], evidence_refs: ["us.cape"] };

const assessment: MarketAssessment = {
  scope: "us", status: "partial", as_of: "2026-09-04", updated_at: "2026-09-05T03:00:00Z", input_digest: "current",
  score: 60, scores: { pressure: 20, valuation: 90, bubble: null }, coverage: { available: 1, total: 2, weight_pct: 60 },
  factors: [{ key: "us.cape", label: "席勒市盈率", value: 40, unit: "倍", score: 90, weight: 60, status: "available", source_url: "https://example.com/cape", source_date: "2026-09-01", meaning: "长期估值处于较高位置。" }, { key: "us.vix_level", label: "VIX波动压力", value: 16, unit: "点", score: 20, weight: 15, status: "available", source_url: null, source_date: "2026-09-04", meaning: "已计算本次波动水平。" }],
  rule_assessment: { headline: "估值偏高，当前下跌压力有限", stance: "价格与估值信号已分别计算。", reasons: ["已检查：SPY和QQQ均未跌破200日均线。"], watch_next: ["旧待办不应继续展示。"], invalidations: ["旧固定条件不应继续展示。"] },
  ai_analysis: aiAnalysis,
  ai_error: null, market_rows: [],
};
const render = (data: MarketAssessment) => renderToStaticMarkup(createElement(MarketAssessmentPanel, { assessment: data, locale: "zh", busy: false, error: "", onRefresh() {} }));

describe("market assessment presentation", () => {
  it("connects the conclusion, actionable conditions and Grok interpretation to dated evidence", () => {
    const html = render(assessment);
    for (const text of ["估值偏高，当前下跌压力有限", "系统已完成的检查", "估值与价格信号存在差异", "席勒市盈率", "2026-09-01", 'href="https://example.com/cape"', "推理强度", "high", "每日 17:05"]) expect(html).toContain(text);
    expect(html).toContain("60%");
    expect(html).toContain("更新数据与 Grok 研判");
    expect(html.indexOf("估值与价格信号存在差异")).toBeLessThan(html.indexOf("系统已完成的检查"));
    expect(html).not.toContain("旧待办不应继续展示");
    expect(html).not.toContain("旧固定条件不应继续展示");
    expect(html).not.toContain("接下来怎么做");
  });
  it("does not show an earlier AI opinion as if it describes the current data", () => {
    const html = render({ ...assessment, ai_analysis: { ...assessment.ai_analysis!, input_digest: "older" } });
    expect(html).not.toContain("估值与价格信号存在差异");
    expect(html).toContain("尚未生成与这份数据匹配的 AI 解读");
    expect(html).toContain("已检查：SPY和QQQ均未跌破200日均线");
    expect(html).toContain('data-assessment-ai="unavailable"');
  });
  it("keeps missing scores unknown rather than showing zero risk", () => {
    const html = render({ ...assessment, score: null, scores: { pressure: null, valuation: null, bubble: null }, coverage: { available: 0, total: 2, weight_pct: 0 }, factors: [], ai_analysis: null });
    expect(html).toContain("综合观察评分 — / 100");
    expect(html).not.toContain("综合观察评分 0 / 100");
  });
  it("does not label an initial empty response as a completed check or an AI result", () => {
    const html = render({ ...assessment, input_digest: null, score: null, coverage: { available: 0, total: 0, weight_pct: 0 }, factors: [], ai_analysis: null });
    expect(html).toContain("AI 解读尚未生成");
    expect(html).not.toContain("系统已完成的检查");
    expect(html).not.toContain("data-assessment-checks");
  });
  it("shows a failed refresh even when the last matching AI result is retained", () => {
    const html = render({ ...assessment, status: "failed", ai_error: "公开估值更新失败" });
    expect(html).toContain("公开估值更新失败");
    expect(html).toContain("下方保留上次已生成的研判");
    expect(html).toContain("估值与价格信号存在差异");
    expect(html).toContain("上次 AI 解读");
    expect(html).toContain('data-assessment-ai="previous"');
  });

  it("groups market and macro indicators locally and keeps the selected tab accessible", () => {
    const html = render(assessment);
    const market = html.split('data-factor-panel="market"')[1].split('data-factor-panel="macro"')[0];
    const macro = html.split('data-factor-panel="macro"')[1];
    expect(market).toContain("VIX波动压力");
    expect(market).not.toContain("席勒市盈率");
    expect(macro).toContain("席勒市盈率");
    expect(macro).not.toContain("VIX波动压力");
    expect(html).toContain('data-factor-tab="market" aria-selected="true"');
    expect(html).toContain("行情与波动");
    expect(html).toContain("宏观与估值");
    expect(marketFactorSection("us.buffett")).toBe("macro");
    expect(marketFactorSection("us.yield_spread")).toBe("macro");
    expect(marketFactorSection("EWY.pe")).toBe("macro");
    expect(marketFactorSection("EWY.extension")).toBe("market");
  });

  it("separates Asian issuer dates from price dates and preserves missing values", () => {
    const html = render({ ...assessment, scope: "asia", factors: [
      { ...assessment.factors[0], key: "EWY.pe", label: "韩国ETF持仓PE", source_date: "2026-09-02" },
      { ...assessment.factors[1], key: "EWY.trend", label: "韩国趋势压力", source_date: "2026-09-04" },
    ], market_rows: [{ symbol: "EWY", label: "韩国", score: null, valuation_score: null, pressure_score: 20, pe: null, pb: null, trend_deviation_pct: 5, drawdown_pct: null, source_url: null, source_date: "2026-09-02", status: "partial" }] });
    const market = html.split('data-factor-panel="market"')[1].split('data-factor-panel="macro"')[0];
    const macro = html.split('data-factor-panel="macro"')[1];
    expect(html).toContain("ETF估值");
    expect(market).toContain("2026-09-04");
    expect(market).not.toContain("2026-09-02");
    expect(macro).toContain("2026-09-02");
    expect(macro).not.toContain("2026-09-04");
    expect(html).not.toContain("—%");
  });
});
