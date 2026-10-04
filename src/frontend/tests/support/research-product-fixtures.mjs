// Explicit browser protocol fixtures, never market observations or test alpha.
export const STRATEGY_ID = `strategy-${"a".repeat(24)}`;
export const RESEARCH_KEY = `research:${STRATEGY_ID}`;
const digest = "b".repeat(64);
export const collectionFixture = {
  generated_at: "2026-09-15T00:00:00Z", errors: [], excluded_sample_runs: 1,
  items: [{
    key: RESEARCH_KEY, id: STRATEGY_ID, kind: "research", name: "测试用每周反转组合", name_en: "Fixture weekly reversal",
    description: "仅为 E2E 界面协议构造，不代表真实回测。每周选两只股票，使用一半资金。",
    implementation_status: "implemented", source_digest: digest,
    intro: { status: "missing", source_digest: digest },
    universe: ["AAPL", "MSFT", "NVDA"], notes: ["E2E fixture · 不是真实收益"],
    evidence: [{ kind: "dual_engine", engine: "Platform", status: "verified", start: "2020-01-02", end: "2020-12-31", metrics: { total_return: 0.2, sharpe: 0.8123, max_drawdown: 0.1 }, note: "测试 Platform 原始字段" },
      { kind: "dual_engine", engine: "Qlib", status: "verified", metrics: {}, note: "测试 Qlib 没有汇总指标" }],
    links: [{ label: "查看这份策略的规则与验证", href: `/strategy-library?strategy=${STRATEGY_ID}#strategy-${STRATEGY_ID}` }],
    source_refs: [{ label: "strategy_definition", path: "fixture/definition.json", digest }],
  }, {
    key: "factor:fixture-momentum", id: "fixture-momentum", kind: "factor", name: "测试动量信号", name_en: "Fixture momentum",
    description: "测试信号，不将策略整体收益误当因子收益。", implementation_status: "implemented",
    source_digest: digest, intro: { status: "missing" }, universe: [], notes: [], links: [], source_refs: [],
    evidence: [{ kind: "factor_lab", engine: "Factor Lab", status: "historical", metrics: { ic_mean: 0.0357, sample_count: 200, coverage: 0.9, sharpe: 19.01 }, note: "测试因子 IC" }],
  }],
};
export const definitionEvaluationFixture = {
  status: "ready", key: RESEARCH_KEY, progress: "测试记录", warnings: ["E2E fixture · 不是真实收益"],
  source: { mode: "strategy_definition", title: "测试用每周反转组合", description: collectionFixture.items[0].description,
    evidence: collectionFixture.items[0].evidence, links: collectionFixture.items[0].links },
};
