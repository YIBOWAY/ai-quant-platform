import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  canEnableSavedStrategy, discoverySaveSource, enableSavedStrategy, getStrategyLibrary,
  strategyIssueText,
  saveStrategyVersion, strategyLibraryNeedsPoll, strategyOriginHref, studySaveSource,
  validateSavedStrategy, type StrategyLibraryEntry,
  composeStrategy, getStrategyFactorOptions, parseStrategySymbols,
  type StrategyComposeRequest, type StrategyFactorOption,
  PERFORMANCE_SCOPE_CUMULATIVE_SLEEVE_HISTORY,
} from "@/lib/strategyLibrary";
import { ACTIVATION_PREFLIGHT_ON_ENABLE, candidatePresentation } from "@/lib/hermes/candidatePresentation";
import { StrategyStudiesView } from "./StrategyStudiesView";
import { AdmissionEvidence, FactorComposer, FactorContribution, SaveStrategyButton, StrategyLibraryPanel, WaitingResearchMaterials } from "./StrategyLibraryPanel";

const calls = vi.hoisted(() => ({ events: [] as string[], get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/apiClient", () => ({ apiRequest: calls.get }));
vi.mock("@/lib/hermes/workspaceClient", () => ({
  ensureOwnerSession: async () => { calls.events.push("owner"); },
  ownerPostJson: async (path: string, body: unknown) => {
    calls.events.push("post"); return calls.post(path, body);
  },
}));

const digest = "a".repeat(64);
function entry(overrides: Partial<StrategyLibraryEntry> = {}): StrategyLibraryEntry {
  return {
    strategy_id: "saved-one", title: "每周双因子组合", definition_digest: digest,
    created_at: "2026-09-09T08:00:00Z", status: "draft", candidate_id: null,
    sleeve_id: null, validation: null,
    origin: { type: "backtest", run_id: "backtest-original" },
    definition: {
      kind: "factor_blend", symbols: ["AAPL", "MSFT", "NVDA"], benchmark_symbol: "SPY",
      rebalance: "weekly", top_n: 2, max_weight_per_symbol: 0.3, target_gross_exposure: 0.6,
      factors: [
        { factor_id: "momentum", lookback: 21, direction: "higher_is_better", weight: 0.7 },
        { factor_id: "volatility", lookback: 63, direction: "lower_is_better", weight: 0.3 },
      ],
    },
    ...overrides,
  };
}
const validated = () => entry({
  status: "validated", candidate_id: "candidate-one",
  validation: { definition_digest: digest, comparison: { accepted: true }, blockers: [],
    simulation_allocation_usd: 10_000, start: "2022-01-03", end: "2026-09-08",
    platform_metrics: { total_return: 0, sharpe: null, max_drawdown: 0.1 } },
});

beforeEach(() => { calls.events.length = 0; calls.get.mockReset(); calls.post.mockReset(); });

describe("fixed strategy library", () => {
  it("shows a completed rejected baseline comparison while retaining its canonical draft state", () => {
    const baseline = entry({ research_evidence: {
      variant: "baseline", definition_digest: digest,
      admission: { mode: "parallel", variants: [{ variant: "baseline", status: "validation_failed", validation_run_id: "artificial-run", blockers: ["dsr_failed"] }] },
    } });
    const html = renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={[baseline]}/>);
    expect(html).toContain("已保存 · 待验证");
    expect(html).toContain("本轮对照验证已完成");
    expect(html).toContain("原策略条目状态未更新");
    expect(html).toContain("原准入检查未通过");
    expect(baseline.status).toBe("draft");
    const unverified = entry({ research_evidence: { ...baseline.research_evidence, definition_digest: "wrong" } });
    expect(renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={[unverified]}/>)).not.toContain("本轮对照验证已完成");
  });
  it("keeps missing-data proposals visible without turning them into executable strategies", () => {
    const html = renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={[]} initialDataNeeds={[{
      job_id: "artificial-waiting-job", proposal_id: "Original-Book-to-Market", status: "waiting_data",
      expression: "$book_to_market", executable_strategy_count: 0,
      research_design: { source_title: "Original source", data_needs: [{ fields: ["book_to_market", "filing_available_at"] }] },
    }]}/>);
    for (const text of ["等待数据的研究材料", "0 个可执行策略", "未完成本地验证", "$book_to_market", "filing_available_at", "Original source", "不自动替换成价量代理"]) expect(html).toContain(text);
    expect(html).not.toMatch(/<button[^>]*>启用/);
    expect(html).not.toContain('id="strategy-');
    expect(calls.post).not.toHaveBeenCalled();
    expect(renderToStaticMarkup(<WaitingResearchMaterials locale="zh" items={[]} error="unavailable"/>)).toContain("不能据此判断没有待补材料");
  });
  it("explains incomplete admission checks without hiding unknown error codes", () => {
    expect(strategyIssueText("qualification_data:qualification_dataset_unsupported", "zh"))
      .toContain("本次数据集不在已验证范围内");
    expect(strategyIssueText("qualification_review:new_unknown_code", "zh"))
      .toBe("计算规则检查尚未取得有效结果：new_unknown_code");
    expect(strategyIssueText("qualification_data:qualification_dataset_unsupported", "en"))
      .toBe("qualification_data:qualification_dataset_unsupported");
  });
  it("shows parallel admission as a comparison, never as allocated cash or a passed check", () => {
    const html = renderToStaticMarkup(<AdmissionEvidence locale="zh" receipt={{ mode: "parallel", status: "not_evaluated", validated_tier: "T0", reasons: ["qualification_missing"] }}/>);
    expect(html).toContain("新旧检查并列对照");
    expect(html).toContain("检查材料尚不完整");
    expect(html).toContain("不改变原准入结论");
    expect(html).not.toContain("已分配");
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("keeps a tier separate from funding and leaves legacy records unchanged", () => {
    expect(renderToStaticMarkup(<AdmissionEvidence locale="zh"/>)).toBe("");
    const html = renderToStaticMarkup(<AdmissionEvidence locale="en" receipt={{ mode: "authoritative", status: "passed", validated_tier: "T2", reasons: [] }}/>);
    expect(html).toContain("Checks passed");
    expect(html).toContain("not a cash allocation or a fill");
  });

  it("preserves replaced history without offering another allocation", () => {
    const old = { ...validated(), status: "superseded" as const, sleeve_id: "same-sleeve", performance_scope: PERFORMANCE_SCOPE_CUMULATIVE_SLEEVE_HISTORY, activation_blockers: ["strategy_version_replaced"] };
    expect(canEnableSavedStrategy(old)).toBe(false);
    const html = renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={[old]}/>);
    expect(html).toContain("已由新版本接续");
    expect(html).toContain("不能作为新公式单独的成绩");
    expect(html).not.toMatch(/<button\b[^>]*>启用 \$10,000 模拟<\/button>/);
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("pins the cumulative sleeve scope to the value the backend reports", () => {
    expect(PERFORMANCE_SCOPE_CUMULATIVE_SLEEVE_HISTORY).toBe("cumulative_sleeve_history_across_versions");
    const panelSource = readFileSync(path.join(process.cwd(), "components/research/StrategyLibraryPanel.tsx"), "utf8");
    expect(panelSource).toContain("entry.performance_scope === PERFORMANCE_SCOPE_CUMULATIVE_SLEEVE_HISTORY");
    expect(panelSource).not.toContain('performance_scope === "cumulative_sleeve_history_across_versions"');
    const superseded = { ...validated(), status: "superseded" as const, sleeve_id: "same-sleeve", performance_scope: "unknown_future_scope" };
    expect(renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={[superseded]}/>)).not.toContain("不能作为新公式单独的成绩");
  });

  it("keeps the named main region filled when every saved version reads as stale", () => {
    const stale = [entry({ strategy_id: "stale-one", status: "stale" }), entry({ strategy_id: "stale-two", status: "stale" })];
    const html = renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={stale}/>);
    const main = html.split('aria-label="已保存策略"')[1]?.split("</section>")[0] ?? "";
    expect(main).toContain("历史版本，保留原结果");
    expect(main).toContain('id="strategy-stale-one"');
    expect(main).toContain('id="strategy-stale-two"');
    expect(main).toContain("原始验证与成交结果不会删除");
    expect(html).toContain("实现或参数已变化");
    expect(html).not.toContain("NaN");

    const english = renderToStaticMarkup(<StrategyLibraryPanel locale="en" initialItems={stale}/>);
    const englishMain = english.split('aria-label="Saved strategies"')[1]?.split("</section>")[0] ?? "";
    expect(englishMain).toContain("Historical versions — original results retained");
    expect(englishMain).toContain('id="strategy-stale-one"');
  });

  it("still folds historical versions away when a current version exists", () => {
    const html = renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={[entry(), entry({ strategy_id: "stale-one", status: "stale" })]}/>);
    const main = html.split('aria-label="已保存策略"')[1]?.split("</section>")[0] ?? "";
    expect(main).toContain('id="strategy-saved-one"');
    expect(main).not.toContain('id="strategy-stale-one"');
    expect(html).toContain("历史版本，保留原结果");
    expect(html).toContain("<details");
  });

  it("does not send a version replacement through the new-capital enable action", () => {
    const replacement = { ...validated(), admission_v2: {
      mode: "authoritative", status: "passed", validated_tier: "T2",
      intent_kind: "replacement", target_sleeve_id: "existing-sleeve",
    } };
    expect(canEnableSavedStrategy(replacement)).toBe(false);
    expect(() => enableSavedStrategy(replacement)).toThrow("strategy_validation_required");
    const html = renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={[replacement]}/>);
    expect(html).toContain("更新现有模拟仓的规则");
    expect(html).toContain("existing-sleeve");
    expect(html).not.toMatch(/<button\b[^>]*>启用 \$10,000 模拟<\/button>/);
    expect(html).not.toContain("完整验证记录尚未确认");
    expect(calls.events).toEqual([]);
    expect(calls.post).not.toHaveBeenCalled();
  });
  it("keeps saved, validated and running states distinct without submitting on render", () => {
    const html = renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={[
      entry(), validated(), entry({ strategy_id: "running", status: "paper_running", sleeve_id: "sleeve-one" }),
    ]}/>);
    for (const value of ["我的策略", "已保存 · 待验证", "验证通过 · 待启用", "已启用 · 运行证据另列", "每周调仓", "Top 2", "60.00%", "30.00%", "回看", "21", "63", "越低越优", "未分配模拟资金", "启用不代表已经成交", "0.00%", "10.00%", "—"]) expect(html).toContain(value);
    expect(html).toContain('href="/zh/backtest/backtest-original"');
    expect(html).toContain("启用 $10,000 模拟");
    expect(html).not.toContain("NaN");
    expect(calls.post).not.toHaveBeenCalled();
    expect(calls.get).not.toHaveBeenCalled();
  });

  it("does not enable a saved, failed, mismatched or incomplete version", () => {
    const rows = [entry(), entry({ status: "validation_failed" }),
      entry({ status: "validated" }),
      { ...validated(), validation: { definition_digest: "b".repeat(64), comparison: { accepted: true } } },
      { ...validated(), validation: { ...validated().validation, blockers: ["dsr_below_threshold"] } },
    ];
    for (const value of rows) {
      expect(canEnableSavedStrategy(value)).toBe(false);
      expect(() => enableSavedStrategy(value)).toThrow("strategy_validation_required");
    }
    expect(calls.post).not.toHaveBeenCalled();
    const html = renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={rows}/>);
    expect(html).toContain("策略质量检查未通过");
    expect(html).toContain("完整验证记录尚未确认");
    expect(html).toMatch(/disabled=""[^>]*>启用 \$10,000 模拟/);
  });

  it("reads only saved records and polls only an actual validating state", async () => {
    calls.get.mockResolvedValue({ items: [entry()] });
    await getStrategyLibrary();
    expect(calls.get).toHaveBeenCalledWith("/api/strategy-library", { signal: undefined });
    expect(calls.post).not.toHaveBeenCalled();
    expect(strategyLibraryNeedsPoll([entry()])).toBe(false);
    expect(strategyLibraryNeedsPoll([validated()])).toBe(false);
    expect(strategyLibraryNeedsPoll([entry({ status: "validation_failed" })])).toBe(false);
    expect(strategyLibraryNeedsPoll([entry({ status: "validating" })])).toBe(true);
  });

  it("bootstraps owner identity before one digest-bound validate or enable POST", async () => {
    calls.post.mockResolvedValue(entry({ status: "validating" }));
    await validateSavedStrategy(entry());
    expect(calls.events).toEqual(["owner", "post"]);
    expect(calls.post).toHaveBeenCalledTimes(1);
    expect(calls.post).toHaveBeenCalledWith("/api/strategy-library/saved-one/validate", { expected_digest: digest });
    calls.events.length = 0; calls.post.mockReset(); calls.post.mockResolvedValue(entry({ status: "paper_running" }));
    await enableSavedStrategy(validated());
    expect(calls.events).toEqual(["owner", "post"]);
    expect(calls.post).toHaveBeenCalledTimes(1);
    expect(calls.post).toHaveBeenCalledWith("/api/strategy-library/saved-one/enable", { expected_digest: digest });
  });

  it("does not retry a timeout or ambiguous mutation failure", async () => {
    calls.post.mockRejectedValue(Object.assign(new Error("network timeout"), { status: 504 }));
    await expect(validateSavedStrategy(entry())).rejects.toMatchObject({ outcomeUnknown: true });
    expect(calls.post).toHaveBeenCalledTimes(1);
    expect(calls.events).toEqual(["owner", "post"]);
  });

  it("imports a completed profile from a partial report without granting qualification", async () => {
    const source = studySaveSource("partial-run", "profile-one", "available");
    expect(source).toEqual({ type: "study", runId: "partial-run", profileId: "profile-one" });
    calls.post.mockResolvedValue(entry());
    await saveStrategyVersion(source!, " 固定月调方案 ");
    expect(calls.post).toHaveBeenCalledWith("/api/strategy-library/import-study", {
      run_id: "partial-run", profile_id: "profile-one", title: "固定月调方案",
    });
    expect(calls.post).toHaveBeenCalledTimes(1);
    expect(studySaveSource("partial-run", "profile-two", "failed")).toBeNull();
    const html = renderToStaticMarkup(<StrategyStudiesView locale="zh" initialReport={{
      status: "partial", progress: "一项已完成", run_id: "partial-run", profiles: [{ id: "profile-one", name: "已完成一项", family: "stock_momentum", symbols: ["SPY"], peer_symbols: ["SPY"] }],
      results: [{ status: "available", profile: { id: "profile-one", name: "已完成一项", symbols: ["SPY"], peer_symbols: ["SPY"] } }],
    }}/>);
    expect(html).toContain("保存到我的策略");
    expect(html).toContain("到“我的策略”验证后");
  });

  it("binds old discovery saves to their original run and refuses a missing origin", async () => {
    const result = { status: "available", profile: { id: "rdagent:old", proposal_id: "old" } };
    const source = discoverySaveSource({ origin_run_id: "original-run", run_id: "new-run" }, result);
    expect(source).toEqual({ type: "study", runId: "original-run", profileId: "rdagent:old" });
    expect(discoverySaveSource({ run_id: "new-run" }, result)).toBeNull();
    calls.post.mockResolvedValue(entry());
    await saveStrategyVersion(source!);
    expect(calls.post).toHaveBeenCalledWith("/api/strategy-library/import-study", {
      run_id: "original-run", profile_id: "rdagent:old",
    });
    expect(strategyOriginHref(entry({ origin: { type: "study", run_id: "original-run", profile_id: "rdagent:old" } }), "zh"))
      .toBe("/api/strategy-studies/original-run/profiles/rdagent%3Aold");
  });

  it("saves an existing backtest by its run identity without rewriting form parameters", async () => {
    calls.post.mockResolvedValue(entry());
    await saveStrategyVersion({ type: "backtest", runId: "backtest-original" });
    expect(calls.post).toHaveBeenCalledWith("/api/strategy-library/import-backtest", { run_id: "backtest-original" });
    expect(calls.events).toEqual(["owner", "post"]);
    const html = renderToStaticMarkup(<SaveStrategyButton locale="zh" source={null}/>);
    expect(html).toContain('disabled=""');
    expect(html).toContain("保存到我的策略");
  });

  it("shows registered and saved formula components without calling a model or saving", () => {
    const options: StrategyFactorOption[] = [
      { factor_id: "momentum", label: "动量", expression: null, lookback: 21, direction: "higher_is_better", origin: "registered" },
      { factor_id: "formula_1234", label: "已保存短期反转", expression: "-($close/Ref($close,5))", lookback: 6, direction: "higher_is_better", origin: "saved_formula" },
    ];
    const html = renderToStaticMarkup(<FactorComposer locale="zh" initialOptions={options} onSaved={vi.fn()}/>);
    for (const value of ["组合因子", "已保存短期反转", "注册因子", "已保存公式", "完整历史（日）", "回看（日）", "评分权重", "不是下单持仓比例", "股票池代码，逗号分隔", "每日", "每周", "每月", "百分位排名", "标准分", "单标的持仓上限", "总仓位上限", "保存组合，等待验证", "保存不会启动调参、验证或模拟运行", "-($close/Ref($close,5))"]) expect(html).toContain(value);
    expect(calls.post).not.toHaveBeenCalled();
    expect(calls.get).not.toHaveBeenCalled();
  });

  it("links formula sources to the matching highlighted strategy on this page", () => {
    const source = entry();
    const options: StrategyFactorOption[] = [{
      factor_id: "formula_source", label: "来源公式", expression: "$close/Ref($close,21)",
      lookback: 22, direction: "higher_is_better", origin: "saved_formula",
      source_refs: [{ strategy_id: source.strategy_id, title: source.title }],
    }];
    const composer = renderToStaticMarkup(<FactorComposer locale="zh" initialOptions={options} onSaved={vi.fn()}/>);
    const library = renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={[source]}/>);
    expect(composer).toContain(`href="#strategy-${source.strategy_id}"`);
    expect(composer).not.toContain("?strategy=");
    expect(library).toContain(`id="strategy-${source.strategy_id}"`);
    expect(library).toContain("target:bg-[var(--color-hermes-glow)]");
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("posts a fixed formula plus registered factor composition exactly once and only saves", async () => {
    const request: StrategyComposeRequest = {
      kind: "factor_blend", title: "新公式组合", symbols: parseStrategySymbols("aapl, MSFT，NVDA"),
      benchmark_symbol: "SPY", rebalance: "weekly", top_n: 2, normalization: "rank",
      max_weight_per_symbol: 0.3, target_gross_exposure: 0.6, min_order_value: 10,
      factors: [
        { factor_id: "momentum", expression: null, lookback: 21, direction: "higher_is_better", weight: 0.5 },
        { factor_id: "formula_1234", expression: "-($close/Ref($close,5))", lookback: 6, direction: "higher_is_better", weight: 0.5 },
      ],
    };
    calls.post.mockResolvedValue(entry({ origin: { type: "compose", run_id: "" } }));
    const saved = await composeStrategy(request);
    expect(calls.events).toEqual(["owner", "post"]);
    expect(calls.post).toHaveBeenCalledExactlyOnceWith("/api/strategy-library/compose", request);
    expect(saved.status).toBe("draft");
    expect(request.factors[1].expression).toBe("-($close/Ref($close,5))");
    const html = renderToStaticMarkup(<StrategyLibraryPanel locale="zh" initialItems={[saved]}/>);
    expect(html).toContain("自定义因子组合");
    expect(html).not.toContain("原研究记录");
  });

  it("rejects empty or invalid compositions before owner bootstrap and POST", () => {
    const request: StrategyComposeRequest = {
      kind: "factor_blend", title: "组合", symbols: ["AAPL", "MSFT"], benchmark_symbol: "SPY",
      rebalance: "monthly", top_n: 1, normalization: "zscore", max_weight_per_symbol: 1,
      target_gross_exposure: 1, min_order_value: 0,
      factors: [{ factor_id: "momentum", expression: null, lookback: 21, direction: "higher_is_better", weight: 1 }],
    };
    expect(() => parseStrategySymbols("AAPL, AAPL")).toThrow("symbols_invalid");
    expect(() => composeStrategy({ ...request, title: "" })).toThrow("title_required");
    expect(() => composeStrategy({ ...request, factors: [] })).toThrow("factors_invalid");
    expect(() => composeStrategy({ ...request, top_n: 3 })).toThrow("symbols_invalid");
    expect(() => composeStrategy({ ...request, target_gross_exposure: 2 })).toThrow("limits_invalid");
    expect(() => composeStrategy({ ...request, factors: [{ ...request.factors[0], weight: 0 }] })).toThrow("factors_invalid");
    expect(calls.events).toEqual([]);
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("fetches factor options through the read-only endpoint", async () => {
    calls.get.mockResolvedValue({ factors: [] });
    await getStrategyFactorOptions();
    expect(calls.get).toHaveBeenCalledExactlyOnceWith("/api/strategy-library/factor-options", { signal: undefined });
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("keeps factor contributions and the Ridge challenger separate from paper rules", () => {
    const html = renderToStaticMarkup(<FactorContribution locale="zh" analysis={{
      status: "available", score: { all: { rank_ic: 0.023, samples: 600 }, recent: { rank_ic: -0.01 } },
      components: [{ factor_id: "momentum", all: { rank_ic: 0.013 }, recent: { rank_ic: 0 } }],
      leave_one_out: [{ factor_id: "momentum", rank_ic_delta_full_minus_without: -0.005, paired_samples: 540 }],
      ridge: { status: "available", fixed_score_metrics: { rank_ic: 0.021 }, ridge_metrics: { rank_ic: 0.034 }, rank_ic_delta: 0.013, matched_samples: 480, folds: [{}, {}] },
    }}/>);
    for (const value of ["因子贡献与学习模型对照", "不等于策略收益", "0.023", "-0.010", "0.013", "0.000", "-0.005", "540", "0.021", "0.034", "480", "不会自动改动当前因子权重", "Ridge 学习模型对照"]) expect(html).toContain(value);
    expect(calls.post).not.toHaveBeenCalled();
  });

  it("explains unavailable contribution and learning-model data instead of fabricating zero", () => {
    const html = renderToStaticMarkup(<FactorContribution locale="zh" analysis={null}/>);
    expect(html).toContain("尚未提供因子贡献分析");
    expect(html).toContain("尚无可用的学习模型对照结果");
    expect(html).not.toContain("0.000");
    expect(html).not.toContain("NaN");
  });
});

// candidatePresentation's own suite sits outside this fix's file scope, so its
// activation-note mapping is covered here against the marker the backend emits.
describe("candidate activation notes", () => {
  const preflight = { candidate_id: "artifact-preflight", status: "verified",
    activation_eligibility: { eligible: true, reason: ACTIVATION_PREFLIGHT_ON_ENABLE } };
  it("announces the enable-time preflight without the denial wording", () => {
    expect(candidatePresentation(preflight, "zh").activationNote).toContain("首次启用时将执行完整资格预检");
    expect(candidatePresentation(preflight, "en").activationNote).toContain("full eligibility preflight");
    for (const locale of ["zh", "en"] as const) {
      const note = candidatePresentation(preflight, locale).activationNote;
      expect(note).not.toContain("仅供研究复核");
      expect(note).not.toContain("Research review only");
      expect(note).not.toContain("不允许启用");
      expect(note).not.toContain("does not allow");
    }
  });
  it("keeps the existing denial wording for every other eligibility reason", () => {
    expect(candidatePresentation({ activation_eligibility: { eligible: false, reason: "dsr_failed" } }, "zh").activationNote)
      .toBe("仅供研究复核；统计稳健性未通过当前要求。");
    expect(candidatePresentation({ activation_eligibility: { eligible: false, reason: "unmapped_future_reason" } }, "en").activationNote)
      .toBe("Research review only; current validation does not allow simulated running.");
    expect(candidatePresentation({ activation_eligibility: { eligible: true, reason: "dsr_failed" } }, "zh").activationNote).toBeUndefined();
    expect(candidatePresentation({}, "zh").activationNote).toBeUndefined();
  });
});
