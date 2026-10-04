import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { OptionsScreenerCandidate, OptionsScreenerResult } from "@/lib/api";
import {
  CandidateDetail,
  OptionsScreenerResults,
  partitionScreenerCandidates,
} from "./OptionsScreenerResults";

function candidate(overrides: Partial<OptionsScreenerCandidate> = {}): OptionsScreenerCandidate {
  return {
    symbol: "US.INTC260919P00020000",
    underlying: "US.INTC",
    strategy_type: "sell_put",
    option_type: "PUT",
    expiry: "2026-09-19",
    strike: 20,
    underlying_price: 24.2,
    bid: 4.1,
    ask: 4.3,
    mid: 4.2,
    volume: 12,
    open_interest: 1500,
    implied_volatility: 0.55,
    historical_volatility: 0.4,
    hv_iv_ratio: 0.72,
    delta: -0.28,
    days_to_expiry: 25,
    annualized_yield: 0.35,
    spread_pct: 0.048,
    iv_rank: 42,
    earnings_date: "2026-10-24",
    earnings_in_window: false,
    ex_dividend_date: null,
    ex_dividend_in_window: false,
    extrinsic_value: 4.2,
    gross_annualized_yield: 0.61,
    pop: 0.72,
    otm_pct: 0.17,
    breakeven: 15.8,
    take_profit_50_price: 2.1,
    manage_at_21_dte: "2026-08-29",
    expected_value: 0.9,
    excess_annualized_ev: 0.12,
    liquidity_factor: 0.9,
    recommendation_score: 0.108,
    recommendation_score_model: "seller_ev_liquidity_v1",
    hard_gate_passed: true,
    recommendation_rejection_reasons: [],
    market_regime: "Normal",
    market_regime_penalty: 0,
    rating: "Strong",
    notes: [],
    seller_score: { composite: 78, weights_used: { yield: 0.3 } },
    ...overrides,
  };
}

function result(
  candidates: OptionsScreenerCandidate[],
  overrides: Partial<OptionsScreenerResult> = {},
): OptionsScreenerResult {
  return {
    ticker: "INTC",
    provider: "futu",
    strategy_type: "sell_put",
    scanned_expirations: ["2026-08-21", "2026-09-19"],
    expiration_count: 2,
    underlying_price: 24.2,
    historical_volatility: 0.4,
    ema_21: 23.5,
    sma_50: 22.8,
    hv_iv_threshold: 1.2,
    hv_iv_pass_count: 3,
    hv_iv_contract_count: 5,
    market_regime: "Normal",
    market_regime_penalty: 0,
    candidates,
    rejected_count: 12,
    rejection_summary: { "delta above limit": 7 },
    assumptions: [],
    ...overrides,
  };
}

function render(
  value: OptionsScreenerResult,
  locale: "en" | "zh" = "zh",
  showRejected = false,
) {
  return renderToStaticMarkup(
    <OptionsScreenerResults locale={locale} result={value} showRejected={showRejected} />,
  );
}

describe("partitionScreenerCandidates", () => {
  it("keeps only hard-gate-passed non-Avoid rows as eligible, sorted by score desc", () => {
    const low = candidate({ symbol: "LOW", recommendation_score: 0.05 });
    const high = candidate({ symbol: "HIGH", recommendation_score: 0.12 });
    const gateFailed = candidate({
      symbol: "GATED",
      hard_gate_passed: false,
      recommendation_score: null,
      recommendation_rejection_reasons: ["earnings_within_dte"],
    });
    const avoid = candidate({ symbol: "AVOID", rating: "Avoid" });

    const { eligible, rejected } = partitionScreenerCandidates([low, gateFailed, high, avoid]);

    expect(eligible.map((item) => item.symbol)).toEqual(["HIGH", "LOW"]);
    expect(rejected.map((item) => item.symbol)).toEqual(["GATED", "AVOID"]);
  });
});

describe("OptionsScreenerResults", () => {
  it("shows only fully-computed candidates in the main table and hides rejected rows by default", () => {
    const eligible = candidate();
    const gateFailed = candidate({
      symbol: "US.INTC260919P00021000",
      hard_gate_passed: false,
      recommendation_score: null,
      gross_annualized_yield: null,
      pop: null,
      recommendation_rejection_reasons: ["quote_stale"],
    });
    const html = render(result([eligible, gateFailed]), "zh", false);

    expect(html).toContain("US.INTC260919P00020000");
    expect(html).not.toContain("US.INTC260919P00021000");
    // The rejected section and its translated reason stay hidden by default.
    expect(html).not.toContain("未入选合约");
    expect(html).not.toContain("报价已过期");
  });

  it("renders a compact 12-column candidate table without the redundant extrinsic column", () => {
    const html = render(result([candidate()]), "zh", false);

    expect(html.match(/<th[ >]/g) ?? []).toHaveLength(12);
    for (const heading of ["合约", "到期 · DTE", "行权价", "中间价", "年化", "价差", "未平仓", "事件", "评分"]) {
      expect(html).toContain(heading);
    }
    // Extrinsic value moved into the expandable detail row; for OTM contracts it
    // always equals the mid price, so it is not a default column any more.
    expect(html).not.toContain("外在价值");
    expect(html).not.toContain("价外距离");
    // Rows render collapsed until the user opens the detail row.
    expect(html).toContain('aria-expanded="false"');
  });

  it("keeps missing truth values as placeholders instead of inventing numbers", () => {
    const html = render(result([candidate({ iv_rank: null })]), "zh", false);

    expect(html).toContain("--");
    expect(html).not.toContain("NaN");
  });

  it("lists gate-failed rows with translated reasons when rejected rows are requested", () => {
    const gateFailed = candidate({
      symbol: "US.INTC260919P00021000",
      hard_gate_passed: false,
      recommendation_score: null,
      gross_annualized_yield: null,
      rating: "Watch",
      recommendation_rejection_reasons: ["earnings_within_dte"],
    });
    const html = render(result([candidate(), gateFailed]), "zh", true);

    expect(html).toContain("未入选合约 (1)");
    expect(html).toContain("US.INTC260919P00021000");
    expect(html).toContain("到期前有财报");
    // Main table still has 12 columns; the rejected table adds 9 more headers.
    expect(html.match(/<th[ >]/g) ?? []).toHaveLength(21);
  });

  it("renders English copy for the redesigned table", () => {
    const gateFailed = candidate({
      symbol: "US.INTC260919P00021000",
      hard_gate_passed: false,
      recommendation_score: null,
      recommendation_rejection_reasons: ["delta_outside_range"],
    });
    const html = render(result([candidate(), gateFailed]), "en", true);

    expect(html).toContain("Expiry · DTE");
    expect(html).toContain("Annualized");
    expect(html).toContain("Not selected (1)");
    expect(html).toContain("delta_outside_range");
  });

  it("explains when filters matched rows but none passed the score hard gate", () => {
    const gateFailed = candidate({
      hard_gate_passed: false,
      recommendation_score: null,
      recommendation_rejection_reasons: ["spread_above_maximum"],
    });
    const html = render(result([gateFailed]), "zh", false);

    expect(html).toContain("没有合约同时满足全部条件");
    expect(html).toContain("勾选「显示未入选合约」并重新运行");
    expect(html).not.toContain("<table");
  });

  it("keeps the zero-candidate guidance when the backend returned no rows at all", () => {
    const html = render(result([], { rejected_count: 534 }), "zh", false);

    expect(html).toContain("已扫描 2 个到期日、过滤掉 534 个合约");
    expect(html).toContain("主要过滤原因");
    expect(html).toContain("Delta 超过上限");
  });

  it("labels displayed rejected rows as rejected and does not ask to enable them again", () => {
    const html = render(result([candidate({ hard_gate_passed: false, rating: "Avoid" })]), "zh", true);
    expect(html).not.toContain("通过了侧边栏筛选条件");
    expect(html).not.toContain("勾选「显示未入选合约」并重新运行");
    expect(html).toContain("下方已展示");
  });

  it("expands a row detail even when optional fields are null (regression: null ex-dividend crash)", () => {
    const sparse = candidate({
      ex_dividend_date: null,
      manage_at_21_dte: null,
      take_profit_50_price: null,
      notes: ["stale quote"],
    });
    const html = renderToStaticMarkup(<CandidateDetail candidate={sparse} locale="zh" />);

    expect(html).toContain("外在价值");
    expect(html).toContain("除息");
    expect(html).toContain("--");
    expect(html).toContain("报价过旧");
    expect(html).toContain("通过评分硬门");
  });
});

describe("screener preferences and premium estimates", () => {
  it("keeps preference failures outside eligible rows even if a stale rating says Strong", () => {
    const row = candidate({ screen_passed: false, preference_rejection_reasons: ["APR below minimum"] });
    expect(partitionScreenerCandidates([row]).eligible).toEqual([]);
  });

  it("shows full-scan disjoint counts and observations without calling them candidates", () => {
    const watch = candidate({ symbol: "OBSERVE-ONLY", screen_passed: false, rating: "Avoid",
      annualized_yield: 0.1183, bid_annualized_yield: .117,
      preference_rejection_reasons: ["APR below minimum"], notes: ["APR below minimum"] });
    const html = render(result([], { scanned_contract_count: 1042, hard_gate_rejected_count: 980,
      preference_rejected_count: 62, eligible_count: 0, watch_candidates: [watch],
      requested_min_apr: 15, apr_alternative_max_percent: 11.83 }));
    expect(html).toContain("全部符合");
    expect(html).toContain("1042");
    expect(html).toContain("980");
    expect(html).toContain("62");
    expect(html).toContain("仅供观察");
    expect(html).toContain("OBSERVE-ONLY");
    expect(html).toContain("11.83%");
    expect(html).toContain("系统没有自动降低条件");
    expect(html).not.toContain('aria-expanded="false"');
  });

  it("keeps unknown fees unknown and distinguishes fee-adjusted premium from strategy P&L", () => {
    const html = renderToStaticMarkup(<CandidateDetail locale="zh" candidate={candidate({
      bid_premium_per_contract: 200, bid_annualized_yield: .08,
      estimated_round_trip_fee_per_contract: null, fee_adjusted_bid_annualized_yield: null,
      quote_as_of: "2026-10-02T20:00:00Z",
    })} />);
    expect(html).toContain("未填写");
    expect(html).toContain("买一价扣费后权利金年化");
    expect(html).toContain("2026-10-02T20:00:00Z");
    expect(html).toContain("不含期权买回成本、指派和持股盈亏");
  });
});
