import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getStrategyStudies, getStrategyStudyProfile, refreshStrategyStudies, type StrategyStudies, type StrategyStudyDetail } from "@/lib/strategyStudies";
import { ResearchEvaluationView } from "./ResearchEvaluationView";
import { StrategyStudiesView, StudyCurve, StudySignalEvidence } from "./StrategyStudiesView";

const calls = vi.hoisted(() => ({ events: [] as string[], get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/apiClient", () => ({ apiRequest: calls.get }));
vi.mock("@/lib/hermes/workspaceClient", () => ({
  ensureOwnerSession: async () => { calls.events.push("owner"); },
  ownerPostJson: async (path: string, body: unknown) => { calls.events.push("post"); calls.post(path, body); return { status: "updating" }; },
}));

const profile = {
  id: "stocks_momentum_12_2", name: "跨行业股票月频动量", family: "stock_momentum",
  symbols: ["AAPL", "MSFT"], peer_symbols: ["AAPL", "MSFT"], symbol_labels: { AAPL: "苹果", MSFT: "微软" },
  benchmark_symbol: "SPY", formation: "12–2月，跳过最近1月", holding: "下月开盘调仓", rebalance: "monthly",
  rules: ["按信号选择股票"], limitations: ["静态现存股票名单存在幸存者偏差。"], sources: [{ title: "原作者方法", url: "https://example.com/method" }],
};
const result = {
  profile, status: "available", start: "2018-01-02", end: "2026-09-04",
  metrics: { total_return: 0.25, annualized_return: 0.028, sharpe: 0.5432, max_drawdown: 0.15, volatility: 0.18 },
  gross_metrics: { total_return: 0.31, annualized_return: 0.032, sharpe: 0.6432, max_drawdown: 0.12, volatility: 0.18 },
  benchmark_metrics: { total_return: 0.52, sharpe: 0.8 }, peer_metrics: { total_return: 0.23, sharpe: 0.4 },
  costs: { total: 456.78 }, benchmark_costs: { total: 60 }, peer_costs: { total: 125.89 },
  average_exposure: 0.95, average_risk_exposure: 0.9,
  curve: [{ date: "2018-01-02", equity: 99940, benchmark: 99940, peer: 99940 }, { date: "2026-09-04", equity: 125000, benchmark: 152000, peer: 123000 }],
  splits: { test: { label: "test", start: "2025-01-01", end: "2026-09-04", metrics: { total_return: -0.02, sharpe: -0.1 }, benchmark_metrics: { total_return: 0.1 }, peer_metrics: { total_return: 0.06 } } },
  by_year: [], evaluation_note: "固定规则时间分区，不声称历史完全未被查看。",
};
const report: StrategyStudies = { status: "ready", progress: "研究完成", profiles: [profile], results: [result], discovery: null };
beforeEach(() => { calls.events.length = 0; calls.get.mockReset(); calls.post.mockReset(); });

describe("purpose-specific research", () => {
  it("shows bound active performance with plain labels and uncertainty beside the selected strategy", () => {
    const comparison = { benchmark_symbol: "SPY", information_ratio: { value: .25, ci95_low: -.1, ci95_high: .6 },
      tracking_error: { annualized: .08 }, beta_alpha: { beta: .8, alpha_annualized: .03, alpha_nw_t: .9 },
      sharpe_se_ci: { ci95_low: .1, ci95_high: 1.1 }, block_bootstrap: { value: .1, ci95_low: -.2, ci95_high: .4 } };
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, results: [{ ...result,
      active_metrics: { schema_version: "active_metrics_v1", status: "ready", start: "2018-01-02", end: "2026-09-04", n_observations: 2182, vs_benchmark: comparison, vs_peer: { ...comparison, benchmark_symbol: "peer" } },
      active_metrics_evidence: { kind: "derived_sidecar", status: "ready", source_result_digest: "a".repeat(64) },
    }] }}/>);
    for (const term of ["相对基准表现的稳定度（IR）", "跟随基准涨跌的程度（β）", "扣除基准影响后的估计收益（α）", "95% 估计区间", "0.250", "0.800", "3.00%", "-0.200", "0.400", "不是未来收益的保证", "补充统计"]) expect(html).toContain(term);
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("explains an unbound active sidecar without filling missing estimates with zero", () => {
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, results: [{ ...result,
      active_metrics: null, active_metrics_evidence: { status: "unavailable", reason: "source_result_digest_mismatch" },
    }] }}/>);
    expect(html).toContain("主动评价与当前保存结果不匹配");
    expect(html).toContain("0.5432");
    expect(html).not.toContain("NaN");
  });

  it("defaults to purpose-led studies instead of the old ETF portfolio", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh"/>);
    expect(html).toContain("按用途研究");
    expect(html).toContain("先确定用途，再看回测");
    expect(html).toContain("原 ETF 诊断");
    expect(html).not.toContain("原 ETF 配置的诊断记录");
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("shows the exact symbols, rules, separate gross/net/peer evidence without choosing a winner", () => {
    const winner = { ...profile, id: "winner", name: "高收益方案" };
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, profiles: [winner, profile], results: [{ ...result, profile: winner, metrics: { sharpe: 99.9999 } }, result] }}/>);
    for (const term of ["AAPL", "苹果", "MSFT", "微软", "跳过最近1月", "同池等权", "幸存者偏差", "0.5432", "0.6432", "$456.78", "25.00%", "31.00%", "52.00%", "23.00%", "90.00%", "2025-01-01", "-2.00%", "原作者方法"]) expect(html).toContain(term);
    expect(html).toContain("99.9999");
    expect(html).toMatch(/aria-pressed="true"[^>]*><span>跨行业股票月频动量/);
    expect(html).toContain("2 套固定方案 · 对比总表");
    expect(html).toContain('role="img"');
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("keeps genuine zero and missing statistics distinct", () => {
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, results: [{ ...result, metrics: { total_return: 0, sharpe: null }, gross_metrics: {}, average_exposure: null, average_risk_exposure: null }] }}/>);
    expect(html).toContain("0.00%");
    expect(html).toContain("—");
    expect(html).not.toContain("NaN");
    expect(html).not.toContain("0.5432");
  });

  it("retains completed profiles alongside partial failures and labels old results", () => {
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, status: "stale", error: "另一个方案缺少价格", results: [result, { status: "failed", profile: { id: "other" } }] }}/>);
    expect(html).toContain("旧协议或旧代码");
    expect(html).toContain("另一个方案缺少价格");
    expect(html).toContain("0.5432");
    expect(html).not.toContain("历史运行记录中的错误");
  });

  it("shows Qlib's actual monthly signal fields separately from portfolio Sharpe", () => {
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, results: [{ ...result,
      signal_diagnostics: { engine: "Qlib calc_ic", all: { ic: 0.0123, rank_ic: 0.0234, rank_ic_ir: 0.0345, periods: 81, samples: 1944 }, splits: { test: { ic: 0.0011, rank_ic: -0.0022, rank_ic_ir: -0.0033, periods: 17, samples: 408 } } },
      latest_signal: { signal_date: "2026-08-31", trade_date: "2026-09-01", targets: {} },
    }] }}/>);
    for (const term of ["Qlib 信号评价", "0.0123", "0.0234", "0.0345", "-0.0022", "1944", "408", "不是组合收益或夏普率"]) expect(html).toContain(term);
    expect(html).toContain("全部退出，持有现金");
    expect(html).toContain("2026-09-01");
    expect(html).not.toContain("AAPL 100.00%");
  });

  it("shows all frozen proposals, rejections and losing test results", () => {
    const discoveryResult = { ...result, profile: { ...profile, id: "rdagent:one", proposal_id: "one" } };
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, discovery: {
      status: "frozen", evaluation_status: "evaluated", model: "openai/grok-4.6", reasoning_effort: "xhigh", training_end: "2021-12-31",
      proposals: [{ id: "one", title: "仍待验证", expression: "$close/Ref($close,21)", rationale: "训练期假说", status: "frozen" }, { id: "two", title: "重复方案", expression: "$close/Ref($close,21)", rationale: "重复测试", status: "rejected", reason: "duplicate_expression" }, { id: "three", title: "常数方案", status: "rejected", reason: "constant_expression" }], results: [discoveryResult],
    } }}/>);
    for (const term of ["仍待验证", "重复方案", "常数方案", "与已有公式重复", "公式为常数", "-2.00%", "2021-12-31", "grok-4.6", "xhigh", "$close/Ref($close,21)"]) expect(html).toContain(term);
    expect(html).toContain("已检验");
    expect(html).not.toContain("已冻结待检验");
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("does not turn a no-rebalance latest signal into a cash exit", () => {
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, results: [{ ...result, latest_signal: { signal_date: "2026-09-03", trade_date: "2026-09-04", targets: null, action: "hold" } }] }}/>);
    expect(html).toContain("本日不调仓，保持原持仓");
    expect(html).not.toContain("全部退出，持有现金");
  });

  it("does not bridge missing curve values with a fabricated price", () => {
    const html = renderToStaticMarkup(<StudyCurve zh benchmark="SPY" value={[
      { date: "2020-01-02", equity: 100, benchmark: 100, peer: 100 },
      { date: "2020-01-03", equity: null, benchmark: 102, peer: 103 },
      { date: "2020-01-06", equity: 105, benchmark: 104, peer: 103 },
    ]}/>);
    expect(html).toContain('d="M85.0,245.0  M915.0,30.0"');
    expect(html).not.toContain("NaN");
  });

  it("binds cumulative return to the named rotating portfolio and collapses its full universe", () => {
    const rotating = { ...profile, top_n: 5 };
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, profiles: [rotating], results: [{ ...result, profile: rotating, metrics: { total_return: 8.06 } }] }}/>);
    expect(html).toContain("806.00%");
    expect(html).toContain("每月重新排名、轮换 Top 5");
    expect(html).toContain("不是固定持有 5 只股票的收益");
    expect(html).toContain("因子 / 规则");
    expect(html).toContain("跨行业股票月频动量 · 回测收益");
    expect(html).toContain("2018-01-02");
    const universe = html.match(/<details[^>]*aria-label="候选池完整名单"[^>]*>/)?.[0];
    expect(universe).toBeDefined();
    expect(universe).not.toContain("open=");
  });

  it("uses the saved dynamic research window and keeps the original exploration dates", () => {
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, discovery: {
      status: "stale", evaluation_status: "stale", training_end: "2021-12-31",
      research_window: { training_start: "2018-01-01", training_end: "2026-09-08", data_watermark: "2026-09-08", mode: "retrospective", note: "历史研发窗口" },
      evaluation_scope: "retrospective_research_then_forward_observation",
      generated_at: "2026-09-07T09:19:23+00:00", evaluated_at: "2026-09-07T09:21:12+00:00",
      proposals: [{ id: "old", title: "历史提议", status: "frozen" }],
    } }}/>);
    expect(html).toContain("参考行情截至 2026-09-08");
    expect(html).toContain("原提议生成于 2026-09-07 09:19:23 UTC");
    expect(html).toContain("原评价保存于 2026-09-07 09:21:12 UTC");
    expect(html).toContain("保留的旧探索");
    expect(html).toContain("所有已看历史都属于研发与回顾性评价");
    expect(html).not.toContain("训练截至 2021-12-31");
  });

  it("labels old train/validation/test ranges as historical sections", () => {
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{ ...report, results: [{ ...result, splits: {
      train: { label: "train", start: "2018-01-01", end: "2021-12-31" },
      validation: { label: "validation", start: "2022-01-01", end: "2024-12-31" },
      test: result.splits.test,
    } }] }}/>);
    for (const label of ["历史分段 A", "历史分段 B", "历史分段 C", "2021-12-31"]) expect(html).toContain(label);
    for (const label of ["训练时间区间", "验证时间区间", "测试时间区间"]) expect(html).not.toContain(label);
  });

  it("shows saved Top 5 ranks, target weights and actual fills with cash reconciliation", () => {
    const scored = { ...profile, top_n: 5, symbol_labels: { AAPL: "苹果", MSFT: "微软", NVDA: "英伟达" } };
    const signal = { signal_date: "2026-08-31", trade_date: "2026-09-01", targets: { NVDA: 0.2, AAPL: 0.2, MSFT: 0.2, META: 0.2, AVGO: 0.2 }, scores: ["NVDA", "AAPL", "MSFT", "META", "AVGO", "ORCL"].map((symbol, i) => ({ symbol, score: 6 - i })) };
    const detail: StrategyStudyDetail = {
      run_id: "study-fixture", profile_id: profile.id, profile: scored, status: "available",
      signal_dates: ["2026-07-31", "2026-08-31"], selected_signal_date: "2026-08-31", signals: [signal],
      trades: [{ date: "2026-09-01", symbol: "NVDA", side: "buy", quantity: 12, fill_price: 100, commission: 1.2 }],
      reconciliation: { status: "matched", cash: 998.8, market_value: 101000, equity: 101998.8, as_of: "2026-09-01" }, source: {}, provenance: {},
    };
    const html = renderToStaticMarkup(<StudySignalEvidence detail={detail} signal={signal} profile={scored} zh/>);
    for (const term of ["当期排名前 5", "共 6 个满足历史条件", "英伟达", "形成期涨幅（12–2月动量）", "600.00%", "20.00%", "展开其余 1 个标的排名", "NVDA", "买入", "12.0000", "$100", "$1,200", "$1.2", "$998.8", "$101,998.8", "核对一致"]) expect(html).toContain(term);
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("does not invent cash or fees when the saved detail is missing", () => {
    const signal = { signal_date: "2026-08-31", trade_date: "2026-09-01", targets: {} };
    const html = renderToStaticMarkup(<StudySignalEvidence detail={null} signal={signal} profile={profile} zh/>);
    expect(html).toContain("成交与资金核对尚未取得");
    expect(html).not.toContain("$0");
    expect(html).not.toContain("核对一致");
    const legacy: StrategyStudyDetail = { run_id: "study-old", profile_id: profile.id, profile, status: "available", signal_dates: ["2026-08-31"], selected_signal_date: "2026-08-31", signals: [signal], trades: [], reconciliation: { status: "unavailable", reason: "缺少旧记录" }, source: {}, provenance: {} };
    const oldHtml = renderToStaticMarkup(<StudySignalEvidence detail={legacy} signal={signal} profile={profile} zh/>);
    expect(oldHtml).toContain("成交笔数与费用未知");
    expect(oldHtml).not.toContain("0 笔成交");
    expect(oldHtml).not.toContain("$0");
  });
});

describe("explicit study requests", () => {
  it("GET is read-only and does not acquire a write session", async () => {
    calls.get.mockResolvedValue({ status: "not_started" });
    await getStrategyStudies();
    expect(calls.get).toHaveBeenCalledWith("/api/strategy-studies");
    expect(calls.events).toEqual([]);
  });
  it("queries the exact saved run, profile and date without a write session", async () => {
    await getStrategyStudyProfile("study-saved", "rdagent:one", "2026-08-31");
    expect(calls.get).toHaveBeenCalledWith("/api/strategy-studies/study-saved/profiles/rdagent%3Aone?signal_date=2026-08-31");
    expect(calls.post).not.toHaveBeenCalled();
    expect(calls.events).toEqual([]);
  });
  it("requires the existing owner/CSRF flow and opts into discovery only explicitly", async () => {
    await refreshStrategyStudies();
    expect(calls.post).toHaveBeenLastCalledWith("/api/strategy-studies/refresh", { include_discovery: false });
    await refreshStrategyStudies(true);
    expect(calls.post).toHaveBeenLastCalledWith("/api/strategy-studies/refresh", { include_discovery: true });
    expect(calls.events).toEqual(["owner", "post", "owner", "post"]);
  });
});
