import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getResearchEvaluation, refreshPaperEvaluation, refreshResearchEvaluation,
  type PaperEvaluation, type ResearchEvaluation,
} from "@/lib/researchEvaluation";
import { ItemEvaluationSummary, ResearchEvaluationView } from "./ResearchEvaluationView";
import { getFactorScorecards, type FactorScorecards } from "@/lib/factorScorecards";

const calls = vi.hoisted(() => ({ events: [] as string[], get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/apiClient", () => ({ apiRequest: calls.get }));
vi.mock("@/lib/hermes/workspaceClient", () => ({
  ensureOwnerSession: async () => { calls.events.push("owner"); },
  ownerPostJson: async (path: string, body: unknown) => {
    calls.events.push("post"); calls.post(path, body); return { status: "updating" };
  },
}));

const points = [
  { date: "2021-01-04", equity: 100000, benchmark: 100000 },
  { date: "2021-01-05", equity: 100300, benchmark: 100100 },
];
const row = (key: string, sharpe: number | null, frequency = "daily") => ({
  key, status: "available", rule: "实际固定规则", frequency,
  metrics: { sharpe, total_return: 0.15, annualized_return: 0.05, max_drawdown: 0.07 },
  benchmark_metrics: { sharpe: 0.8, total_return: 0.2, annualized_return: 0.06, max_drawdown: 0.09 },
  curve: points, by_year: [],
});

it("reads full strategy validation without offering the incompatible factor rerun", () => {
  const key = "research:strategy-" + "a".repeat(24);
  const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" researchKey={key} initialReport={{ status: "ready", key,
    progress: "", source: { mode: "strategy_definition", title: "每周反转 Top5", description: "每周保留自己的仓位规则",
    evidence: [{ engine: "platform", metrics: { total_return: 0.2, sharpe: 0.8 }, note: "原始历史指标" }],
    links: [{ label: "查看这份策略的规则与验证", href: "/strategy-library?strategy=strategy-abc#strategy-strategy-abc" }] } }}/>);
  expect(html).toContain("每周反转 Top5");
  expect(html).toContain("20.00%");
  expect(html).toContain("原始历史指标");
  expect(html).not.toContain("运行真实数据评价");
  expect(html).not.toContain("加入研究因子的模型");
});
const report: ResearchEvaluation = {
  status: "ready", key: null, progress: "已完成", reference: { rows: [row("factor:momentum", 1.1111), row("factor:rsi", 2.2222)] },
  source: { data_start: "2018-01-02", data_end: "2026-09-04" },
};

beforeEach(() => { calls.events.length = 0; calls.get.mockReset(); calls.post.mockReset(); });

describe("research evaluation presentation", () => {
  it("gives the research page a direct strategy and backtest title", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh"/>);
    expect(html).toContain("策略研究与回测</h1>");
    expect(html).toContain("逐期查看选股排名、目标持仓和成交");
    expect(calls.post).not.toHaveBeenCalled();
  });
  it("uses only the selected factor's matching reference metrics in a collection summary", () => {
    const html = renderToStaticMarkup(<ItemEvaluationSummary itemKey="factor:rsi" locale="zh" initialReport={report}/>);
    expect(html).toContain("2.2222");
    expect(html).not.toContain("1.1111");
    expect(html).toContain("QQQ");
    expect(html).toContain("factor=factor%3Arsi");
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("does not borrow another research report or present stale metrics as current", () => {
    const old = { ...report, status: "stale" as const };
    const html = renderToStaticMarkup(<ItemEvaluationSummary itemKey="factor:rsi" locale="zh" initialReport={old}/>);
    expect(html).toContain("代码已更新");
    expect(html).not.toContain("2.2222");
    const unrelated = renderToStaticMarkup(<ItemEvaluationSummary itemKey="research:artifact-b" locale="zh" initialReport={{ ...report, key: "research:artifact-a" }}/>);
    expect(unrelated).toContain("尚无可用的对应评价");
    expect(unrelated).not.toContain("1.1111");
  });

  it("keeps monthly gross results outside the net-cost comparison table", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="reference" initialReport={{ ...report, reference: {
      rows: [...(report.reference!.rows as unknown[]), row("strategy:reversal_momentum", 9.8765, "monthly")],
    } }}/>);
    expect(html).toContain("月频多空毛收益未计借券和成交成本");
    expect(html).not.toContain("9.8765");
    expect(html).toContain("月频毛收益");
    expect(html).toContain("佣金 1 bp、滑点 5 bp");
    expect(html).toContain('role="img"');
    expect(html).toContain("2021-01-04");
  });

  it("preserves real zero returns while keeping an undefined Sharpe empty", () => {
    const zero = row("factor:momentum", null);
    zero.metrics.total_return = 0;
    const html = renderToStaticMarkup(<ItemEvaluationSummary itemKey="factor:momentum" locale="zh" initialReport={{ ...report, reference: { rows: [zero] } }}/>);
    expect(html).toContain("0.00%");
    expect(html).toContain("—");
    expect(html).not.toContain("NaN");
  });

  it("reads actual Qlib rank_ic fields and renders a ready baseline's curve", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="rolling" initialReport={{
      ...report, rolling: {
        status: "ready", baseline: { ...row("baseline", 0.6543), status: "ready" },
        methodology: { model: "ridge", train_days: 504, valid_days: 126, test_days: 126, purge_days: 2 },
        folds: [{ status: "ready", segments: {
          train: { start: "2017-01-03", end: "2018-12-31" },
          valid: { start: "2019-01-04", end: "2019-06-28" },
          test: { start: "2019-07-03", end: "2019-12-31", n_rows: 1200, n_dates: 120 },
        }, baseline_signals: { test: { rank_ic: 0.0345, rank_ic_mean: 0.9876 } } }],
      },
    }}/>);
    expect(html).toContain("0.0345");
    expect(html).not.toContain("0.9876");
    expect(html).toContain("2017-01-03");
    expect(html).toContain("2019-07-03");
    expect(html).toContain("不证明公式发现过程已做到样本外");
    expect(html).toContain('role="img"');
  });

  it("shows partial paper analysis as valid content and does not multiply percentage fields again", () => {
    const paper: PaperEvaluation = { status: "partial", as_of: "2026-09-04", facts: {
      period: { start: "2026-08-21", end: "2026-09-04", observation_count: 3 },
      metrics: { sleeve_return_pct: 1.25, spy_return_pct: 2, commission_usd: 3.2, turnover: 1.3 },
      observation_series: [{ date: "2026-08-21", sleeve_pct: 0, spy_pct: 0 }, { date: "2026-09-04", sleeve_pct: 1.25, spy_pct: 2 }],
      window_comparison: { status: "not_comparable", reason: "两个区间长短不同，不作改善判断。" },
    }, analysis: { summary: "已记录净值增加，但不能判断预测能力变化。[performance]", model: "grok-4.6", reasoning_effort: "xhigh", observations: ["佣金是已记账金额。[costs]"], explanations: [], limitations: [] } };
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="paper" initialPaperReport={paper}/>);
    expect(html).toContain("已记录净值增加");
    expect(html).toContain("1.25%");
    expect(html).not.toContain("125.00%");
    expect(html).not.toContain('role="alert"');
    expect(html).toContain("不是完整日净值");
    expect(html).toContain("两个区间长短不同");
    expect(html).not.toContain("[performance]");
    expect(html).toContain("grok-4.6");
    const upgraded = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="paper" initialPaperReport={{ ...paper, facts: { ...paper.facts, performance_scope: "cumulative_sleeve_history_across_versions" } }}/>);
    expect(upgraded).toContain("不能当作新公式单独的业绩");
    expect(upgraded).toContain("旧持仓和盈亏已保留");
  });

  it("keeps archived partial facts visible when AI interpretation failed", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="paper"
      initialPaperReport={{ status: "failed", facts_status: "partial",
        interpretation_status: "failed", fact_archive_status: "archived",
        facts: { period: { observation_count: 4, valuation_count: 32 }, metrics: {} },
        analysis: null, error: "artificial AI failure" }}/>);
    expect(html).toContain("已单独封存");
    expect(html).toContain("AI 解读");
    expect(html).toContain("本次失败");
    expect(html).toContain("事实仍有缺项");
    expect(html).toContain("4");
    expect(html).not.toContain("没有成交");
  });

  it("separates historical and forward signal-only partitions without borrowing whole-period returns", () => {
    const itemKey = "research:artifact-one";
    const study: ResearchEvaluation = { ...report, key: itemKey, rolling: {
      selection_end: "2026-08-17", comparisons: [{ factor_id: "candidate::artifact-one",
        augmented: { ...row("candidate", 9.8765), metrics: { total_return: 8.7654, sharpe: 9.8765 } },
        partitions: {
          historical: { status: "available", n_dates: 900, n_rows: 9000, start: "2020-01-01", end: "2026-08-17", baseline_signal_metrics: { rank_ic: 0.0123 }, augmented_signal_metrics: { rank_ic: 0.0234 }, portfolio_status: "not_computed" },
          forward_oos: { status: "available", n_dates: 12, n_rows: 120, start: "2026-08-18", end: "2026-09-03", baseline_signal_metrics: { rank_ic: 0.0345 }, augmented_signal_metrics: { rank_ic: 0.0456 }, portfolio_status: "not_computed" },
        },
      }],
    } };
    const html = renderToStaticMarkup(<ItemEvaluationSummary itemKey={itemKey} locale="zh" initialReport={study}/>);
    expect(html).toContain("按原数据截止日期分开复核");
    expect(html).toContain("不代表数据从未参与研究");
    expect(html).toContain("2026-08-18");
    expect(html).toContain("0.0456");
    expect(html).toContain("未计算");
    expect(html).not.toContain("876.54%");
    expect(html).not.toContain("9.8765");
  });

  it("identifies duplicate information and missing prediction dates in the incremental view", () => {
    const data: ResearchEvaluation = { ...report, rolling: { status: "partial", comparisons: [{
      factor_id: "agent_candidate_wave2_sceneb_mom20_v3", duplicate_of: "momentum",
      note: "重复列会改变 Ridge 的有效正则化，不提供新增信号信息。", folds: [],
      baseline_features: ["momentum"], augmented_features: ["momentum", "agent_candidate_wave2_sceneb_mom20_v3"],
      baseline: { status: "unavailable", reason: "non_contiguous_test_predictions", prediction_coverage: { missing_dates: ["2024-01-05"] } },
      augmented: { status: "unavailable", reason: "non_contiguous_test_predictions", prediction_coverage: { missing_dates: ["2024-01-05"] } },
    }] } };
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="increment" initialReport={data}/>);
    expect(html).toContain("完全重复，不是新增信息");
    expect(html).toContain("Ridge");
    expect(html).toContain("2024-01-05");
    expect(html).toContain("未计算跨缺口的组合收益");
    expect(html).not.toContain('role="img"');
  });
});

describe("explicit evaluation requests", () => {
  it("reads the exact research key without creating a model or update request", async () => {
    calls.get.mockResolvedValue({ status: "not_started" });
    await getResearchEvaluation("research:artifact-one");
    expect(calls.get).toHaveBeenCalledWith("/api/research-evaluation?key=research%3Aartifact-one");
    expect(calls.post).not.toHaveBeenCalled();
    expect(calls.events).toEqual([]);
  });

  it("establishes the existing owner session before either explicit POST", async () => {
    await refreshResearchEvaluation("research:artifact-one");
    expect(calls.events).toEqual(["owner", "post"]);
    expect(calls.post).toHaveBeenLastCalledWith("/api/research-evaluation/refresh", { key: "research:artifact-one" });
    await refreshPaperEvaluation();
    expect(calls.events).toEqual(["owner", "post", "owner", "post"]);
    expect(calls.post).toHaveBeenLastCalledWith("/api/paper-evaluation/refresh", {});
  });
});

const scorecard: FactorScorecards = {
  schema_version: "factor_scorecard_v1", status: "ready", generated_at: "2026-09-18T00:00:00+00:00",
  stale: false, reason: null, progress: "",
  methodology: {
    price_basis: "open_to_open", horizons: [1, 5, 21], quantiles: 5, benchmark_symbol: "SPY",
    calendar: "union_observed_no_fill", gap_rules: "R-cal-1..8",
    nw_lag_rule: "min(max(h-1, floor(4*(T/100)^(2/9))), T-1)", costs: "none_evaluation_only",
    short_assumption: "做空腿假设无摩擦卖空（无 borrow/可得性/RegSHO）", tradeable_claim: false,
  },
  provenance: { methodology_version: "factor-eval-2", forward_return_schema_version: "forward_returns/v2",
    input_digest: "a".repeat(64), source_digest: "b".repeat(64), peer_factor_ids: ["momentum", "rsi"] },
  factors: [{
    factor_id: "momentum", direction: "higher_is_better",
    horizons: { "1": {
      ic: { ic_mean: 0.0123, rank_ic_mean: 0.0098, nw_t: 2.4567, nw_lag: 0, n_days: 240, coverage: 0.97 },
      long_short: { spread_annualized: 0.1534, spread_t_nw: 1.8765 },
      quantiles: { quantile_monotonic: true },
      turnover: { turnover_per_step: { top: 0.6123, bottom: 0.1122, mean: 0.3457 } },
    } },
    correlation: { max_abs_factor_correlation: 0.4321, max_correlation_factor_id: "rsi", n_peers: 2 },
    marginal_contribution: { status: "unavailable", marginal_sharpe_delta: null },
  }],
};

describe("factor scorecard tab", () => {
  it("shows all frozen object names, source coverage and research limits without offering a provider rerun", () => {
    const definitions = Array.from({ length: 27 }, (_, i) => ({ factor_id: `frozen_${i}`, name_zh: `研究对象${i + 1}`, name_en: `Object ${i + 1}`, purpose_zh: `固定用途${i + 1}`, frequency: i > 23 ? "month_end" : "daily" }));
    const wide: FactorScorecards = { ...scorecard, status: "partial", run: { kind: "wide_universe", refresh_mode: "verify_saved_run" },
      wide_run: { signal_window: ["2016-01-01", "2026-08-31"], admission_authority: false },
      factor_catalog: definitions, factors: definitions.map(item => ({ factor_id: item.factor_id, horizons: {} })),
      data_acceptance: { loaded: 696, skipped: 50, formal_ready: true, source_groups: { tiingo: { symbols: 236 }, futu: { symbols: 460 } },
        monthly_coverage: [{ month: "2016-02", month_end_observed: 458, daily_row_coverage: 0.90496 }],
        known_source_limits: ["terminal_returns_unverified"] } };
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards" initialScorecardReport={wide}/>);
    expect(html).toContain("研究对象27");
    expect(html).toContain("固定用途27");
    expect(html).toContain("90.50%");
    expect(html).toContain("458");
    expect(html).toContain("Tiingo");
    expect(html).toContain("460");
    expect(html).toContain("退市最后一段收益");
    expect(html).toContain("校验已保存记分卡");
    expect(html).not.toContain("运行因子记分卡");
    expect(html).toContain("不代表策略已通过验证或已分配模拟资金");
  });

  it("explains why month-end labels have no annualized portfolio return", () => {
    const monthly: FactorScorecards = { ...scorecard, factors: [{ factor_id: "pmf_reversal_1m", horizons: { "1": { inference: { lag_unit: "signal_observations" }, ic: {}, long_short: { spread_annualized: null, spread_t_nw: 1.1, annualization_reason: "sparse_signal_calendar_not_a_daily_portfolio" } } }, marginal_contribution: { status: "not_evaluated", reason: "non_daily_signal_portfolio_required" } }] };
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards" initialScorecardReport={monthly}/>);
    expect(html).toContain("非日频信号未换算成年收益");
    expect(html).toContain("有效信号期");
    expect(html).toContain("NW lag 按信号期计数");
    expect(html).toContain("暂不计算边际贡献");
    expect(html).not.toContain("NaN");
  });

  it("separates an unrun portfolio comparison from missing samples in marginal contribution", () => {
    const deck = (marginal_contribution: unknown) => renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards" initialScorecardReport={{ ...scorecard, factors: [{ factor_id: "momentum", horizons: {}, marginal_contribution }] }}/>);
    const noSleeve = deck({ status: "unavailable", reason: "sleeve_returns_not_provided", marginal_sharpe_delta: null });
    expect(noSleeve).toContain("未做组合对比（未提供组合收益）");
    expect(noSleeve).toContain("没有提供组合收益序列");
    expect(noSleeve).not.toContain("数据或样本不足");
    const monthly = deck({ status: "not_evaluated", reason: "non_daily_signal_portfolio_required" });
    expect(monthly).toContain("暂不计算边际贡献");
    expect(monthly).not.toContain("未做组合对比");
    expect(monthly).not.toContain("数据或样本不足");
    expect(deck({ status: "unavailable", reason: "insufficient_paired_samples" })).toContain("数据或样本不足");
    const english = renderToStaticMarkup(<ResearchEvaluationView locale="en" initialTab="scorecards" initialScorecardReport={{ ...scorecard, factors: [{ factor_id: "momentum", horizons: {}, marginal_contribution: { status: "unavailable", reason: "sleeve_returns_not_provided" } }] }}/>);
    expect(english).toContain("Portfolio comparison not run (sleeve returns not provided)");
    expect(english).not.toContain("samples are insufficient");
  });

  it("shows the scorecard's own source and window instead of the research report's", () => {
    const own: FactorScorecards = { ...scorecard, status: "partial", run: { kind: "wide_universe" },
      wide_run: { signal_window: ["2016-01-01", "2026-08-31"] },
      data_acceptance: { formal_ready: true, loaded: 696, skipped: 50, provider: "mixed_explicit",
        authority: "formal_research_only", research_status: "ready", usage_restrictions: [],
        source_groups: {}, monthly_coverage: [], known_source_limits: [] } };
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards" initialScorecardReport={own} initialReport={report}/>);
    expect(html).toContain("数据来源 mixed_explicit · 2016-01-01 → 2026-08-31");
    expect(html).not.toContain("2018-01-02");
    const english = renderToStaticMarkup(<ResearchEvaluationView locale="en" initialTab="scorecards" initialScorecardReport={own} initialReport={report}/>);
    expect(english).toContain("Source mixed_explicit · 2016-01-01 → 2026-08-31");
    expect(english).not.toContain("2018-01-02");
  });

  it("carries the deck's own authority, research status and verbatim usage restrictions", () => {
    const restrictions = ["PCL/CAM: dual-block files; slice the reused tail (post-2025) before use",
      "ARNC/VIAC/DISCA: not usable (membership window has no data)"];
    const wide: FactorScorecards = { ...scorecard, status: "partial", run: { kind: "wide_universe" },
      wide_run: { signal_window: ["2016-01-01", "2026-08-31"] },
      factors: [{ factor_id: "momentum", horizons: {} }],
      data_acceptance: { formal_ready: true, loaded: 696, skipped: 50, provider: "mixed_explicit",
        authority: "formal_research_only", research_status: "partial_known_source_limits",
        usage_restrictions: restrictions, source_groups: {}, monthly_coverage: [], known_source_limits: [] } };
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards" initialScorecardReport={wide}/>);
    expect(html).toContain("formal_research_only");
    expect(html).toContain("partial_known_source_limits");
    expect(html).toContain("数据仅授权用于正式研究");
    expect(html).toContain("仍保留已知来源限制");
    expect(html).toContain("这份数据保留 2 条使用限制");
    for (const reason of restrictions) expect(html).toContain(reason);
    expect(html).not.toContain("隔离标的：PCL");
    const quarantined: FactorScorecards = { ...wide,
      data_acceptance: { ...wide.data_acceptance!, known_source_limits: ["quarantined:ADT:price_history_starts_after_membership"] } };
    const withQuarantine = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards" initialScorecardReport={quarantined}/>);
    expect(withQuarantine).toContain("隔离标的 ADT");
    expect(withQuarantine).toContain("技术原因原文：price_history_starts_after_membership");
    expect(withQuarantine).not.toContain("隔离标的：ADT");
    const english = renderToStaticMarkup(<ResearchEvaluationView locale="en" initialTab="scorecards" initialScorecardReport={wide}/>);
    expect(english).toContain("Data authority");
    expect(english).toContain("Research status");
    expect(english).toContain("Authorised for formal research only");
    expect(english).toContain("The dataset keeps 2 usage restrictions");
    expect(english).toContain(restrictions[0]);
  });

  it("renders the open-basis methodology, per-horizon inference and standing caveats", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards" initialScorecardReport={scorecard}/>);
    expect(html).toContain("因子记分卡");
    expect(html).toContain("open_to_open");
    expect(html).toContain("2.457");
    expect(html).toContain("15.34%");
    expect(html).toContain("0.432");
    expect(html).toContain("rsi");
    expect(html).toContain("无摩擦卖空");
    expect(html).toContain("可交易性");
    expect(html).toContain("否");
    expect(html).not.toContain("NaN");
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("never substitutes sample numbers for a missing deck", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards" initialScorecardReport={{
      ...scorecard, status: "unavailable", reason: "no_scorecard_run", factors: [], methodology: {}, provenance: {},
    }}/>);
    expect(html).toContain("尚无因子记分卡结果");
    expect(html).not.toContain("2.457");
  });

  it("labels the refresh action for the scorecard tab only", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="en" initialTab="scorecards" initialScorecardReport={scorecard}/>);
    expect(html).toContain("Factor scorecard");
    expect(html).toContain("Run factor scorecard");
    expect(html).not.toContain("Run real-data evaluation");
  });

  it("renders the stored mean turnover rather than a permanent dash", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="en" initialTab="scorecards" initialScorecardReport={scorecard}/>);
    expect(html).toContain("0.346");
    expect(html).not.toContain("0.612");
    expect(html).not.toContain("0.112");
  });

  it("keeps the legacy scalar turnover shape and blanks a block without a mean", () => {
    const legacy: FactorScorecards = { ...scorecard, factors: [{
      factor_id: "momentum", direction: "higher_is_better",
      horizons: {
        "1": { ic: {}, long_short: {}, quantiles: {}, turnover: { turnover_per_step: 0.34 } },
        "5": { ic: {}, long_short: {}, quantiles: {}, turnover: { turnover_per_step: { top: 0.5, bottom: 0.2 } } },
      },
    }] };
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="en" initialTab="scorecards" initialScorecardReport={legacy}/>);
    // Scope the assertion to the turnover cell (last <td> of the horizon row):
    // a page-wide em dash would be satisfied by any other blank cell.
    const turnoverCell = (markup: string, horizon: string) => {
      const row = markup.split("<tr").find(candidate => candidate.includes(`>${horizon}<`));
      if (!row) throw new Error(`horizon row ${horizon} missing`);
      const cells = row.split("<td").slice(1);
      const last = cells[cells.length - 1];
      return last.replace(/^[^>]*>/, "").split("</td>")[0].replace(/<[^>]*>/g, "").trim();
    };
    expect(turnoverCell(html, "1")).toBe("0.340");
    expect(turnoverCell(html, "5")).toBe("—");
  });

  it("shows the stored deck's generated_at in the tab header", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards" initialScorecardReport={scorecard}/>);
    expect(html).toContain("生成于");
    expect(html).toContain("2026-09-18 00:00:00 UTC");
  });

  it("renders the loading notice before any saved deck is read", () => {
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards"/>);
    expect(html).toContain("正在读取已保存结果…");
    expect(html).toContain("运行因子记分卡");
    expect(html).not.toContain('role="alert"');
  });

  it("surfaces a failed scorecard read as an alert", async () => {
    const failure = new Error("读取记分卡失败：network down");
    calls.get.mockRejectedValue(failure);
    await expect(getFactorScorecards()).rejects.toThrow("读取记分卡失败");

    const failed: FactorScorecards & { error: string } = {
      ...scorecard, status: "unavailable", error: failure.message,
    };
    const html = renderToStaticMarkup(<ResearchEvaluationView locale="zh" initialTab="scorecards" initialScorecardReport={failed}/>);
    expect(html).toContain('role="alert"');
    expect(html).toContain("读取记分卡失败：network down");
  });
});
