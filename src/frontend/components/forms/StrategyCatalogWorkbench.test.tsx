import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { StrategyCatalogWorkbench } from "./StrategyCatalogWorkbench";
import type { ReversalMomentumReplicationRunResponse, StrategyMetadata } from "@/lib/api";

vi.mock("@/lib/hydration", () => ({ useIsHydrated: () => true }));

describe("strategy draft execution boundary", () => {
  it("does not offer a runnable backtest or invented factor controls for an executorless draft", () => {
    const html = renderToStaticMarkup(<StrategyCatalogWorkbench locale="zh" universes={[]} factors={[]} strategies={[{
      id: "drift_regime_reversal_top_n_v1", name: "Draft", display_name_zh: "研究草稿", description: "", paper_source: null,
      runnable: false, execution_blocker: "strategy_executor_unavailable", result_type: "backtest", run_endpoint: "/api/backtests/run",
      default_payload: { provider: "futu", factor_ids: ["missing_factor"] },
      parameter_schema: { fields: { factor_ids: { type: "factor_multi_select" } } },
    }]}/>);
    expect(html).toContain("尚无执行器，不能运行");
    expect(html).not.toContain("未命名因子");
    expect(html).not.toContain("同时可在独立的回测器中运行");
    expect(html).toMatch(/<button[^>]+disabled=""[^>]*>运行策略<\/button>/);
  });
});

const savedStrategy: StrategyMetadata = {
  id: "reversal_momentum", name: "Reversal", description: "", paper_source: null,
  result_type: "replication", run_endpoint: "/api/replications/reversal-momentum/run",
  default_payload: { provider: "futu", symbols: ["DEFAULT"], start: "2023-01-01", end: "2026-01-01", initial_cash: 1, top_n: 3 },
  parameter_schema: { fields: {
    provider: { type: "provider", default: "futu" },
    symbols: { type: "symbol_list", default: ["DEFAULT"] },
    start: { type: "date" }, end: { type: "date" },
    initial_cash: { type: "number", default: 1 },
    top_n: { type: "integer_or_null", default: 3 },
  } },
};
const savedResult: ReversalMomentumReplicationRunResponse = {
  run_id: "saved-replication", source: "sample", result_type: "replication",
  request: { provider: "sample", symbols: ["SPY", "QQQ"], start: "2024-01-02", end: "2024-03-29", initial_cash: 10000, top_n: null },
  paper: {}, methodology: {}, metrics: {}, diagnostics: {}, equity_curve: [],
  monthly_returns: [], positions: [], legs: [], warnings: [], paths: {}, artifact_path: "saved-replication/result.json",
};

describe("saved strategy request identity", () => {
  it("renders saved source, dates, symbols and explicit null instead of current defaults", () => {
    const html = renderToStaticMarkup(<StrategyCatalogWorkbench locale="zh" universes={[]} factors={[]}
      strategies={[savedStrategy]} initialStrategyId="reversal_momentum" initialResult={savedResult} futuReachable={false} />);
    expect(html).toContain('<option value="sample" selected="">');
    expect(html).toContain('>SPY,QQQ</textarea>');
    expect(html).toContain('value="2024-01-02"');
    expect(html).toContain('value="2024-03-29"');
    expect(html).not.toContain('value="DEFAULT"');
    expect(html).not.toContain('value="3"');
  });

  it("keeps legacy results readable but does not offer an unbound default rerun", () => {
    const legacy = { ...savedResult, request: undefined } as unknown as ReversalMomentumReplicationRunResponse;
    const html = renderToStaticMarkup(<StrategyCatalogWorkbench locale="zh" universes={[]} factors={[]}
      strategies={[savedStrategy]} initialResult={legacy} />);
    expect(html).toContain("原运行参数缺失");
    expect(html).toMatch(/<button[^>]+disabled=""[^>]*>运行策略<\/button>/);
  });

  it.each(["provider", "top_n", "initial_cash"])("does not fill a missing saved %s with today's default", (field) => {
    const request = { ...savedResult.request };
    delete request[field];
    const html = renderToStaticMarkup(<StrategyCatalogWorkbench locale="zh" universes={[]} factors={[]}
      strategies={[savedStrategy]} initialResult={{ ...savedResult, request }} futuReachable={false} />);
    expect(html).toContain("原运行参数缺失");
    expect(html).toMatch(/<button[^>]+disabled=""[^>]*>运行策略<\/button>/);
  });

  it("does not substitute another strategy when the saved strategy is missing from the catalog", () => {
    const other = { ...savedStrategy, id: "cross_sectional_top_n", result_type: "backtest" };
    const html = renderToStaticMarkup(<StrategyCatalogWorkbench locale="zh" universes={[]} factors={[]}
      strategies={[other]} initialStrategyId="reversal_momentum" initialResult={savedResult} />);
    expect(html).toContain("当前不可用");
    expect(html).toMatch(/<button[^>]+disabled=""[^>]*>运行策略<\/button>/);
  });
});
