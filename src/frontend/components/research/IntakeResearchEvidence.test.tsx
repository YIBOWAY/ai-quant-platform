import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { StrategyLibraryEntry } from "@/lib/strategyLibrary";
import { IntakeResearchEvidence } from "./IntakeResearchEvidence";

// Artificial display fixtures only; never presented as market observations.
const evidence = {
  schema: "intake_evaluation_chain/v1", job_id: "artificial-job", definition_digest: "test-digest", variant: "augmented",
  research_design: { local_factor: { expression: "$close", direction: "higher_is_better" },
    inherited_defaults: ["symbols", "factor_weights"], frozen_before_evaluation: false },
  factor_evaluation: { status: "ready", lookback: 20, horizons: { "1": { ic: { rank_ic_mean: 0.1234, n_days: 30 }, quantiles: { quantile_monotonic: false } } },
    stability: { status: "ready", by_year: [{ year: 2024, horizon: 1, rank_ic_mean: 0.2 }, { year: 2025, horizon: 1, rank_ic_mean: -0.1 }] },
    redundancy: { max_abs_factor_correlation: 0.8 } },
  portfolio_increment: { status: "failed", checks: [{ metric: "sharpe", baseline: 0.8, augmented: 0.7, improvement: -0.1, minimum: 0.05, passed: false }] },
  admission: { mode: "parallel", variants: [{ variant: "augmented", status: "validation_failed", validation_run_id: "artificial-validation", blockers: ["dsr_failed"] }] },
};
const entry: StrategyLibraryEntry = {
  strategy_id: "artificial-strategy", title: "Artificial display fixture", status: "validation_failed",
  created_at: "2026-09-23T00:00:00Z", definition_digest: "test-digest", research_evidence: evidence,
  definition: { kind: "factor_blend", symbols: ["AAPL"], benchmark_symbol: "SPY", rebalance: "monthly", top_n: 1 },
  validation: null, origin: { type: "compose", run_id: "artificial-run" },
};

describe("intake evidence stages", () => {
  it("keeps a locally completed but rejected result distinct from material readiness", () => {
    const html = renderToStaticMarkup(<IntakeResearchEvidence entry={entry} locale="zh"/>);
    for (const label of ["材料可送测", "本地验证", "准入", "原准入检查未通过", "新规则仅并列对照", "单因子的收益", "该项未达标", "0.1234", "跨时段稳定性", "事后补充", "以下项目沿用默认值"]) expect(html).toContain(label);
    expect(html).not.toContain("已分配");
    expect(html).toContain("不等于独立留出通过");
  });

  it("does not borrow metrics from a different implementation identity", () => {
    const html = renderToStaticMarkup(<IntakeResearchEvidence entry={{ ...entry, definition_digest: "different-version" }} locale="zh"/>);
    expect(html).toContain("研究与页面版本身份不一致");
    expect(html).not.toContain("0.1234");
    expect(html).not.toContain("-0.1000");
  });

  it("leaves missing historic factor evidence unavailable without inventing results", () => {
    const old = { ...entry, research_evidence: { ...evidence, factor_evaluation: { status: "not_evaluated", reason: "factor_scorecard_not_recorded_for_this_input" } } };
    const html = renderToStaticMarkup(<IntakeResearchEvidence entry={old} locale="zh"/>);
    expect(html).toContain("该输入尚无因子级记分卡");
    expect(html).not.toContain("0.1234");
    expect(html).toContain("0.8000");
    expect(html).toContain("原准入检查未通过");
  });

  it("attributes the added factor correctly on a reused baseline page", () => {
    const baseline = { ...entry, research_evidence: { ...evidence, variant: "baseline", research_design: { ...evidence.research_design, portfolio: { symbols: ["AAPL"], selection: "bottom", top_n: 1, factor_weights: { formula_added: 1 } } } } };
    const html = renderToStaticMarkup(<IntakeResearchEvidence entry={baseline} locale="zh"/>);
    expect(html).toContain("原组合没有包含它");
    expect(html).toContain("比较对象：加入因子后的完整组合");
    expect(html).toContain("最低分 1");
    expect(html).toContain("formula_added: 1");
    expect(html).not.toContain("Top 1");
  });
});
