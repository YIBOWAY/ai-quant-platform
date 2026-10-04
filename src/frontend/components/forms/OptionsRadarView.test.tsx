import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type {
  OptionsDailyScanResponse,
  OptionsDailyScanStatusResponse,
  OptionsDailyTaskStatus,
  OptionsRadarCandidate,
} from "@/lib/api";
import { candidateRowKey, OptionsRadarView } from "./OptionsRadarView";

const runDate = "2026-08-21";

function candidate(index: number): OptionsRadarCandidate {
  const suffix = String(index).padStart(2, "0");
  return {
    ticker: `T${suffix}`,
    sector: "ETF",
    strategy: "sell_put",
    symbol: `US.T${suffix}260925P00100000`,
    expiry: "2026-09-25",
    strike: 100,
    mid: 2.5,
    annualized_yield: 0.24,
    implied_volatility: 0.3,
    iv_rank: 55,
    iv_history_samples: 30,
    iv_rank_status: "ready",
    iv_measure: "atm30_straddle_iv_v1",
    delta: -0.25,
    open_interest: 800,
    spread_pct: 0.02,
    earnings_date: null,
    earnings_in_window: false,
    global_score: 8.75 - index * 0.01,
    market_regime: "Normal",
    market_regime_penalty: 0,
    days_to_expiry: 35,
    gross_annualized_yield: 0.24,
    pop: 0.75,
    otm_pct: 0.08,
    ex_dividend_date: null,
    ex_dividend_in_window: false,
    breakeven: 97.5,
    take_profit_50_price: 1.25,
    manage_at_21_dte: "2026-09-04",
    expected_value: 0.64,
    excess_annualized_ev: 0.18,
    liquidity_factor: 0.92,
    recommendation_score: 0.1656,
    recommendation_score_model: "seller_ev_liquidity_v1",
    hard_gate_passed: true,
    quote_as_of: "2026-08-21T19:59:00Z",
    extrinsic_value: 2.5,
    dividend_per_share: null,
  };
}

function renderRecommendationPage(
  response: OptionsDailyScanResponse,
  locale: "en" | "zh" = "en",
  taskStatus: OptionsDailyTaskStatus = {
    status: "completed",
    provider: "sample",
    run_date: runDate,
  },
) {
  const activeDate = response.run_date;
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["options-radar-dates"], {
    dates: [activeDate],
  });
  client.setQueryData<OptionsDailyScanStatusResponse>(["options-daily-task-status"], {
    exists: true,
    status_path: "daily_task_status.json",
    status: taskStatus,
  });
  client.setQueryData(
    ["options-radar", activeDate, "all", "", "", 20],
    response,
  );
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <OptionsRadarView initialDate={activeDate} locale={locale} />
    </QueryClientProvider>,
  );
}

function availableResponse(
  candidates: OptionsRadarCandidate[],
): OptionsDailyScanResponse {
  return {
    run_date: runDate,
    universe_size: 34,
    scanned_tickers: 34,
    failed_tickers: [],
    is_stale: false,
    snapshot_age_days: 0,
    expired_candidate_count: 0,
    status: "available",
    provider: "futu",
    as_of: "2026-08-21T20:00:00Z",
    risk_free_rate: 0.043,
    shortfall_count: 0,
    shortfall_reasons: {},
    candidate_count: candidates.length,
    candidates,
  };
}

// The API clears candidates and tags snapshot_stale when the saved snapshot is
// past its freshness window, while daily_task_status.json keeps the old count.
function staleClearedScan(): OptionsDailyScanResponse {
  return {
    ...availableResponse([candidate(0)]),
    is_stale: true,
    snapshot_age_days: 12,
    status: "unavailable",
    shortfall_count: 20,
    shortfall_reasons: { snapshot_stale: 1 },
    candidates: [],
    candidate_count: 0,
  };
}

const staleScanTaskStatus: OptionsDailyTaskStatus = {
  status: "completed",
  provider: "sample",
  run_date: runDate,
  steps: { scan: { candidate_count: 20 } },
};

describe("OptionsRadarView recommendations", () => {
  it("offers an immediate refresh while explaining the 22:00 automatic update", () => {
    const html = renderRecommendationPage(availableResponse([]), "zh");

    expect(html).toContain("立即更新今日推荐");
    expect(html).toContain("每天 22:00 自动更新，也可以现在更新");
    expect(html).not.toContain("页面不手工补跑");
    expect(html).not.toContain(">刷新列表<");
  });

  it("shows scan progress while keeping the previous recommendation visible", () => {
    const html = renderRecommendationPage(
      availableResponse([candidate(0)]),
      "zh",
      {
        status: "running",
        current_step: "scan",
        target_session: "2026-08-25",
        started_at: "2026-08-25T09:00:00Z",
        scanned_tickers: 12,
        total_tickers: 34,
      },
    );

    expect(html).toContain("正在更新");
    expect(html).toContain("扫描期权");
    expect(html).toContain("目标交易日 2026-08-25");
    expect(html).toContain("12/34");
    expect(html).toContain('aria-live="off">耗时');
    expect(html).toContain(">T00<");
  });

  it("gives distinct Chinese labels to the two healthcare source sectors", () => {
    const html = renderRecommendationPage(availableResponse([]), "zh");

    expect(html.match(/>医疗保健<\/option>/g)).toHaveLength(1);
    expect(html).toContain(">医疗健康</option>");
  });

  it("allows covered-call filtering now that dividend evidence is checked per contract", () => {
    const html = renderRecommendationPage(availableResponse([]));

    expect(html).toContain(
      '<option value="covered_call">Covered Call</option>',
    );
    expect(html).toContain("At most 2 contracts per symbol");
  });

  it("shows Futu provenance, the deep link, and at most 20 rows", () => {
    const html = renderRecommendationPage(
      availableResponse(Array.from({ length: 21 }, (_, index) => candidate(index))),
    );

    expect(html).toContain("Options Recommendations");
    expect(html).toContain(">Available<");
    expect(html).not.toContain(">available<");
    expect(html).toContain("futu");
    expect(html).toContain("2026-08-21T20:00:00Z");
    expect(html).toContain("/options-radar/T00?");
    expect(html).toContain(">T19<");
    expect(html).not.toContain(">T20<");
  });

  it("uses a compact Chinese table and explains a warming IV rank", () => {
    const warmingCandidate = {
      ...candidate(0),
      iv_rank: null,
      iv_history_samples: 7,
      iv_rank_status: "warming" as const,
    };
    const html = renderRecommendationPage(
      availableResponse([warmingCandidate]),
      "zh",
    );

    expect(html).toContain("到期/剩余天数");
    expect(html).toContain("权利金");
    expect(html).toContain("年化收益");
    expect(html).toContain("流动性");
    expect(html).toContain("事件");
    expect(html).toContain("卖出看跌");
    expect(html).toContain("积累中 7/30");
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain(">POP≈<");
    expect(html).not.toContain(">虚值幅度<");
  });

  it("caps warming history at 30 and only shows an IV rank when ready", () => {
    const warmingCandidate = {
      ...candidate(0),
      iv_rank: 42,
      iv_history_samples: 300,
      iv_rank_status: "warming" as const,
    };
    const readyCandidate = {
      ...candidate(1),
      iv_rank: 61.5,
      iv_history_samples: 300,
      iv_rank_status: "ready" as const,
    };
    const html = renderRecommendationPage(
      availableResponse([warmingCandidate, readyCandidate]),
      "zh",
    );

    expect(html).toContain("积累中 30/30");
    expect(html).not.toContain("积累中 300/30");
    expect(html).toContain(">61.5<");
  });

  it("distinguishes an honest empty scan and keeps exclusions in scan details", () => {
    const html = renderRecommendationPage({
      ...availableResponse([]),
      status: "empty",
      shortfall_count: 20,
      shortfall_reasons: {
        earnings_in_dte_window: 7,
        missing_quote: 13,
      },
    });

    expect(html).toContain("No compliant recommendations");
    expect(html).toContain("View scan details");
    expect(html).not.toContain("earnings_in_dte_window: 7");
    expect(html).not.toContain("missing_quote: 13");
    expect(html).not.toContain("<tbody");
  });

  it("renders an available snapshot with no returned rows as an honest empty result", () => {
    const html = renderRecommendationPage(availableResponse([]));

    expect(html).toContain(">No recommendations<");
    expect(html).toContain("No compliant recommendations");
    expect(html).not.toContain("No daily scan snapshot found");
  });

  it("marks a sample-backed response unavailable and never presents its rows as recommendations", () => {
    const html = renderRecommendationPage({
      ...availableResponse([candidate(0)]),
      provider: "sample",
      shortfall_count: 20,
      shortfall_reasons: { real_futu_snapshot_unavailable: 20 },
    });

    expect(html).toContain("Recommendations unavailable");
    expect(html).toContain("sample / not real");
    expect(html).toContain("No Futu-backed recommendation rows are shown");
    expect(html).not.toContain(">T00<");
    expect(html).not.toContain("<tbody");
  });

  it("keeps successful rows when a 33-of-34 scan only partially completes", () => {
    const html = renderRecommendationPage({
      ...availableResponse([candidate(0)]),
      scanned_tickers: 33,
      failed_tickers: [["BRK.B", "provider_failed"]],
      shortfall_count: 19,
      shortfall_reasons: { universe_scan_incomplete: 1 },
    });

    expect(html).toContain("Partially completed");
    expect(html).toContain("Scanned 33/34");
    expect(html).toContain(">T00<");
    expect(html).not.toContain("Recommendations unavailable");
  });

  it("keeps the previous result visible when the latest update fails", () => {
    const html = renderRecommendationPage(
      availableResponse([candidate(0)]),
      "zh",
      {
        status: "failed",
        current_step: "scan",
        target_session: "2026-08-25",
        failed_step: "scan",
        error: "provider_failed",
      },
    );

    expect(html).toContain("本次更新失败，仍显示上一份有效结果");
    expect(html).toContain("立即更新今日推荐");
    expect(html).toContain(">T00<");
  });

  it("gives one actionable empty state when no snapshot exists", () => {
    const html = renderRecommendationPage(
      {
        ...availableResponse([]),
        run_date: "",
        status: "unavailable",
        provider: null,
        as_of: null,
        universe_size: 0,
        scanned_tickers: 0,
        shortfall_count: 0,
      },
      "zh",
      {},
    );

    expect(html).toContain("还没有推荐数据");
    expect(html).toContain("立即更新今日推荐");
    expect(html).not.toContain("推荐不可用");
  });

  it("obeys API stale status even when run_date equals the browser day", () => {
    const today = new Date();
    const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const html = renderRecommendationPage({
      ...availableResponse([candidate(0)]),
      run_date: todayIso,
      as_of: "2026-07-02T13:30:00Z",
      is_stale: true,
      snapshot_age_days: 50,
    });

    expect(html).toContain("This is an old snapshot");
    expect(html).not.toContain("Showing today's scan");
    expect(html).toContain("text-danger");
  });

  it("explains a cleared stale snapshot instead of falling back to the generic unavailable copy", () => {
    const html = renderRecommendationPage(staleClearedScan(), "zh", staleScanTaskStatus);

    expect(html).toContain("快照已过期");
    expect(html).toContain("今日尚无新鲜可交易推荐");
    expect(html).toContain("本次结果已清空");
    expect(html).toContain("自动流程每日 22:00 运行");
    expect(html).not.toContain("期权数据暂不可用");
    expect(html).not.toContain("snapshot_stale");
    expect(html).not.toContain(">T00<");
  });

  it("shows one candidate count that matches the rows the API actually returned", () => {
    const html = renderRecommendationPage(staleClearedScan(), "zh", staleScanTaskStatus);

    expect(html).not.toContain("候选: 20");
    expect(html).toContain("候选: 0");
  });

  it("turns a legacy snapshot code into an actionable scheduled-scan message", () => {
    const html = renderRecommendationPage(
      {
        ...availableResponse([]),
        status: "unavailable",
        shortfall_count: 20,
        shortfall_reasons: { legacy_snapshot_contract: 1 },
      },
      "zh",
    );

    expect(html).toContain("这是旧版快照");
    expect(html).toContain("立即更新今日推荐");
    expect(html).not.toContain("23:00");
    expect(html).not.toContain("legacy_snapshot_contract");
    expect(html).not.toContain(">unavailable<");
  });

  it("localizes the en status pill for legacy and stale snapshots instead of leaking raw enums", () => {
    const legacy = renderRecommendationPage({
      ...availableResponse([]),
      status: "unavailable",
      shortfall_count: 20,
      shortfall_reasons: { legacy_snapshot_contract: 1 },
    });

    expect(legacy).toContain(">Update needed<");
    expect(legacy).not.toContain(">unavailable<");

    const stale = renderRecommendationPage({
      ...availableResponse([candidate(0)]),
      is_stale: true,
      snapshot_age_days: 3,
    });

    expect(stale).toContain(">Update needed<");
    expect(stale).not.toContain(">unavailable<");
  });

  it("keys candidate rows by the stable contract tuple, not the raw symbol", () => {
    const first = candidate(0);
    const sameTickerOtherExpiry = {
      ...candidate(0),
      symbol: "US.T00261016P00100000",
      expiry: "2026-10-16",
    };
    const sameContractOtherStrike = { ...candidate(0), strike: 105 };

    expect(candidateRowKey(first)).toBe("US.T00260925P00100000|2026-09-25|100|sell_put");
    expect(candidateRowKey(first)).not.toBe(candidateRowKey(sameTickerOtherExpiry));
    expect(candidateRowKey(first)).not.toBe(candidateRowKey(sameContractOtherStrike));
  });

  it("keeps prior scan rows while filters refetch and uses structural loading hold", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const source = readFileSync(join(process.cwd(), "components/forms/OptionsRadarView.tsx"), "utf8");
    expect(source).toContain("keepPreviousData");
    expect(source).toContain("placeholderData: keepPreviousData");
    expect(source).toContain("motion-data-hold");
    expect(source).toContain("LoadingSkeleton");
    expect(source).toContain("scanInitialLoading");
    // Numeric truth values stay unanimated (no number pop / spring on yields).
    expect(source).not.toContain("animate-bounce");
    expect(source).not.toContain("NumberFlow");
    // The scan-details disclosure is a 44px touch target, not a bare text link.
    expect(source).toMatch(
      /aria-controls="options-scan-details"[\s\S]*?app-touch-target[\s\S]*?scanDetails/,
    );
  });
});
