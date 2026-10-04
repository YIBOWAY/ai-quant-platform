import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ArtifactShelf } from "@/components/hermes";
import { TodayAutomation, TodayResults } from "@/components/hermes/today";
import {
  artifactStatusLabel,
  humanizeReasonCode,
} from "@/components/hermes/artifacts/formatters";
import {
  ArtifactFeed,
  artifactFeedReadState,
} from "@/components/hermes/artifacts/ArtifactFeed";
import type {
  HermesArtifactShelfEnvelope,
  HermesResultsResponse,
} from "./api";
import {
  buildAutomation,
  buildHqaConclusions,
  buildUnifiedResultsPreview,
  pickLatestAutomation,
} from "./hermes/viewModel";
import {
  healthyArtifacts,
  degradedArtifacts,
} from "./hermes/viewModelFixtures";

const availableShelf = {
  schema_version: "1.0",
  read_status: "available",
  as_of: "2026-07-12T01:00:00Z",
  items: [
    {
      id: "risk:2026-07-12T00:50:00Z",
      kind: "portfolio_risk",
      occurred_at: "2026-07-12T00:50:00Z",
      quality: "available",
      status: "available",
      data: {
        account_id: "default",
        ledger_split: false,
        currency: "USD",
        gross_value: 315.32,
        gross_pct_equity: 0.000315,
        largest_symbol: "AAPL",
        top1_gross_pct: 1,
        historical_status: "available",
        benchmark: "SPY",
        betas: [
          {
            aligned_return_count: 274,
            benchmark: "SPY",
            first_return_date: "2025-06-06",
            last_return_date: "2026-07-10",
            reason: null,
            status: "available",
            symbol: "AAPL",
            value: 0.858,
          },
        ],
        reason_codes: [],
        limitations: ["historical_relationship_not_forecast"],
      },
    },
    {
      id: "prediction:pred-20260712-0001",
      kind: "prediction",
      occurred_at: "2026-07-12T00:40:00Z",
      quality: "available",
      status: "open",
      data: {
        prediction_id: "pred-20260712-0001",
        state: "open",
        symbol: "AAPL",
        direction: "up",
        confidence: 0.7,
        horizon_date: "2026-07-19",
        rationale: "Momentum remains positive.",
        outcome_return: null,
        direction_brier: null,
      },
    },
    {
      id: "foresight:mf-20260712-0001",
      kind: "market_foresight",
      occurred_at: "2026-07-12T00:30:00Z",
      quality: "available",
      status: "available",
      data: {
        run_id: "mf-20260712-0001",
        summary: "One candidate prediction is ready for human review.",
        candidate_count: 1,
        candidates: [
          {
            id: "mfp_candidate_001",
            symbol: "MSFT",
            direction: "flat",
            confidence: 0.58,
            horizon_date: "2026-07-19",
            falsifier: "The first eligible close leaves the flat band.",
            rationale: "A bounded validation candidate.",
            entry_session_date: "2026-07-11",
            entry_close: 510.05,
            provider: "futu",
            adjustment: "qfq",
            proposal_only: true,
            requires_human_confirmation: true,
            trading_allowed: false,
          },
        ],
      },
    },
  ],
  sources: [
    {
      kind: "portfolio_risk",
      status: "available",
      latest_at: "2026-07-12T00:50:00Z",
      reason_code: null,
    },
    {
      kind: "prediction",
      status: "available",
      latest_at: "2026-07-12T00:40:00Z",
      reason_code: null,
    },
    {
      kind: "market_foresight",
      status: "available",
      latest_at: "2026-07-12T00:30:00Z",
      reason_code: null,
    },
  ],
  warnings: [],
} satisfies HermesArtifactShelfEnvelope;

const emptyUnifiedResults = {
  read_status: "empty",
  total: 0,
  total_is_exact: true,
  limit: 5,
  offset: 0,
  has_more: false,
  items: [],
  sources: [],
  warnings: [],
} satisfies HermesResultsResponse;

const availableUnifiedResults = {
  read_status: "available",
  total: 1,
  total_is_exact: true,
  limit: 5,
  offset: 0,
  has_more: false,
  items: [
    {
      kind: "backtest",
      resource_id: "backtest-wave3-001",
      display_title: "AAPL momentum backtest",
      summary: "2026-01-01 → 2026-06-30 · provider futu",
      status: "completed",
      occurred_at: "2026-07-15T08:00:00Z",
      source: "platform_runs",
      authority: "platform_run_artifact",
      freshness: "fresh",
      read_status: "available",
      detail_href: "/api/hermes/results/backtest/backtest-wave3-001",
      original_href: "/api/backtest/runs/backtest-wave3-001",
      run_links: [],
    },
  ],
  sources: [
    {
      source: "platform_runs",
      read_status: "available",
      item_count: 1,
    },
  ],
  warnings: [],
} as unknown as HermesResultsResponse;

const unavailableUnifiedResults = {
  read_status: "unavailable",
  total: null,
  total_is_exact: false,
  limit: 5,
  offset: 0,
  has_more: false,
  items: [],
  sources: [],
  warnings: [
    {
      source: "results_catalog",
      code: "api_unavailable",
      kind: null,
      resource_id: null,
    },
  ],
  apiError: "api_unavailable",
} satisfies HermesResultsResponse;

describe("Hermes Chinese limitation copy", () => {
  it("does not expose live portfolio limitation prose in English", () => {
    expect(humanizeReasonCode("no risk policy thresholds configured", "zh")).toBe(
      "未配置风险阈值",
    );
    expect(humanizeReasonCode("account base currency only no fx conversion", "zh")).toBe(
      "仅按账户本位币统计，未做汇率换算",
    );
    expect(humanizeReasonCode("price_freshness_age_unavailable", "zh")).toBe(
      "无法确认价格时效",
    );
    expect(humanizeReasonCode("unknown internal limitation", "zh")).toBe("其他技术限制");
    expect(artifactStatusLabel("available", "zh")).toBe("可用");
    expect(artifactStatusLabel("degraded", "zh")).toBe("已降级");
  });
});

describe("Hermes Today hierarchy (UI-1 Direction A)", () => {
  it("merges recent results into one bounded list with kind tags and detail links", () => {
    const html = renderToStaticMarkup(
      createElement(TodayResults, {
        preview: buildUnifiedResultsPreview(availableUnifiedResults),
        hqaConclusions: buildHqaConclusions(healthyArtifacts),
        locale: "zh",
      }),
    );

    expect(html).toContain("最近结果");
    expect(html).toContain("回测");
    expect(html).toContain("已完成");
    expect(html).not.toContain("AAPL momentum backtest");
    expect(html).not.toContain(">backtest<");
    expect(html).toContain("/zh/hermes/results/backtest/backtest-wave3-001");
    expect(html).toContain("查看全部");
    expect(html).toContain('href="/zh/hermes/results"');
    // One list only — the artifact-feed duplicate preview is not rendered.
    expect(html).not.toContain("HQA 结论产物");
  });

  it("labels stale automation as an expired historical snapshot", () => {
    const preview = buildUnifiedResultsPreview({
      ...availableUnifiedResults,
      items: [
        {
          ...availableUnifiedResults.items[0],
          kind: "automation_status",
          resource_id: "automation_status:cd47dc43c404f7b3730fcce2",
          display_title: "Automation · fresh",
          summary: "4 scheduled jobs",
          freshness: "stale",
          occurred_at: "2026-08-17T09:07:25Z",
        },
      ],
    } as unknown as HermesResultsResponse);
    const html = renderToStaticMarkup(
      createElement(TodayResults, { preview, hqaConclusions: [], locale: "zh" }),
    );

    expect(html).toContain("自动化历史快照");
    expect(html).toContain("历史快照 · 已过期");
    expect(html).not.toContain("Automation · fresh");
    expect(html).not.toContain("4 scheduled jobs");
  });

  it("shows an unknown catalog state in one honest line, then the independent feed", () => {
    const preview = buildUnifiedResultsPreview(unavailableUnifiedResults);
    const html = renderToStaticMarkup(
      createElement(TodayResults, {
        preview,
        hqaConclusions: buildHqaConclusions(healthyArtifacts),
        locale: "zh",
      }),
    );

    expect(preview.total).toBeNull();
    expect(html).toContain("结果目录当前不可用");
    expect(html).toContain("结果来源异常");
    expect(html).not.toContain("api_unavailable");
    expect(html).toContain("以下条目来自独立的只读产物 feed");
    expect(html).toContain("data-hermes-result-id");
    expect(html).not.toContain("今天还没有新的研究结果");
  });

  it("does not present a degraded zero-item catalog as known empty", () => {
    const preview = buildUnifiedResultsPreview({
      ...emptyUnifiedResults,
      read_status: "degraded",
      warnings: [
        {
          source: "platform_runs",
          code: "source_scan_incomplete",
          kind: null,
          resource_id: null,
        },
      ],
    });
    const html = renderToStaticMarkup(
      createElement(TodayResults, {
        preview,
        hqaConclusions: buildHqaConclusions(healthyArtifacts),
        locale: "zh",
      }),
    );

    expect(preview.total).toBeNull();
    expect(html).toContain("可能延迟");
    expect(html).toContain("统一结果目录已降级");
    expect(html).toContain("结果来源异常");
    expect(html).not.toContain("source_scan_incomplete");
    expect(html).not.toContain("今天还没有新的研究结果");
  });

  it("collapses healthy automation to one row and expands exceptions on demand", () => {
    const healthy = renderToStaticMarkup(
      createElement(TodayAutomation, {
        summary: buildAutomation(healthyArtifacts),
        artifact: pickLatestAutomation(healthyArtifacts.items),
        locale: "zh",
      }),
    );
    expect(healthy).toContain("自动化 4/4 正常");
    expect(healthy).toContain("每日收盘研究 · 时效巡检 · 每周复盘 · 通知投递");
    expect(healthy).toContain("上次成功");
    expect(healthy).not.toContain("data-hermes-automation-exception");
    expect(healthy).not.toContain("0 9 * * 0</");

    const degraded = renderToStaticMarkup(
      createElement(TodayAutomation, {
        summary: buildAutomation(degradedArtifacts),
        artifact: pickLatestAutomation(degradedArtifacts.items),
        locale: "zh",
      }),
    );
    expect(degraded).toContain("自动化 3/4 正常");
    expect(degraded).toContain('data-hermes-automation-exception="weekly"');
    expect(degraded).toContain('open=""');
    expect(degraded).toContain("<details");
    expect(degraded).toContain("超过时效窗口");
  });

  it("does not present a stale automation artifact as currently healthy", () => {
    const html = renderToStaticMarkup(
      createElement(TodayAutomation, {
        summary: buildAutomation(healthyArtifacts),
        artifact: pickLatestAutomation(healthyArtifacts.items),
        locale: "zh",
        stale: true,
      }),
    );
    expect(html).toContain("历史快照 · 已过期");
    expect(html).toContain("每日收盘");
    expect(html).not.toContain("daily_close");
    expect(html).not.toContain("4/4 fresh");
    expect(html).not.toContain("自动化 4/4 正常");
  });
});

describe("Hermes artifact shelf", () => {
  it("treats api errors and corrupt runtime status as unavailable truth states", () => {
    const apiFailedShelf = {
      ...availableShelf,
      read_status: "empty",
      items: [],
      sources: [],
      warnings: [],
      apiError: "503: artifact feed unavailable",
    } satisfies HermesArtifactShelfEnvelope;
    const corruptShelf = {
      ...availableShelf,
      read_status: "corrupt",
      items: [],
      warnings: [{ source: "prediction", code: "ledger_corrupt" }],
    } as unknown as HermesArtifactShelfEnvelope;

    expect(artifactFeedReadState(apiFailedShelf)).toBe("unavailable");
    expect(artifactFeedReadState(corruptShelf)).toBe("unavailable");

    const apiFailedMarkup = renderToStaticMarkup(
      createElement(ArtifactFeed, { envelope: apiFailedShelf, locale: "en" }),
    );
    const corruptMarkup = renderToStaticMarkup(
      createElement(ArtifactFeed, { envelope: corruptShelf, locale: "en" }),
    );

    expect(apiFailedMarkup).toContain("Artifacts unavailable");
    expect(apiFailedMarkup).toContain("503: artifact feed unavailable");
    expect(apiFailedMarkup).not.toContain("No research artifacts yet");
    expect(corruptMarkup).toContain("Artifacts unavailable");
    expect(corruptMarkup).toContain("prediction · ledger_corrupt");
    expect(corruptMarkup).not.toContain("No research artifacts yet");
  });

  it("fails closed when read_status is unknown or missing at runtime", () => {
    const unknownShelf = {
      ...availableShelf,
      read_status: "failed",
      items: [],
      warnings: [],
    } as unknown as HermesArtifactShelfEnvelope;
    const missingShelf = {
      ...availableShelf,
      items: [],
      warnings: [],
    } as unknown as HermesArtifactShelfEnvelope;
    delete (missingShelf as { read_status?: string }).read_status;

    expect(artifactFeedReadState(unknownShelf)).toBe("unavailable");
    expect(artifactFeedReadState(missingShelf)).toBe("unavailable");

    for (const envelope of [unknownShelf, missingShelf]) {
      const markup = renderToStaticMarkup(
        createElement(ArtifactFeed, { envelope, locale: "en" }),
      );
      expect(markup).toContain("Artifacts unavailable");
      expect(markup).toContain("artifact_feed · read_status_invalid");
      expect(markup).not.toContain("No research artifacts yet");
    }
  });

  it("renders schema 1.1 weekly, opportunity, and degraded automation cards explicitly", () => {
    const automationShelf = {
      schema_version: "1.1",
      read_status: "available",
      as_of: "2026-07-12T01:00:00Z",
      items: [
        {
          id: "weekly-2026-W28",
          kind: "weekly_review",
          occurred_at: "2026-07-12T00:59:00Z",
          quality: "available",
          status: "available",
          data: {
            week_id: "2026-W28",
            period_start: "2026-07-05T00:00:00Z",
            period_end: "2026-07-12T00:00:00Z",
            safety_alert_count: 1,
            unique_signal_count: 3,
            review_draft_count: 2,
            review_confirmed_count: 1,
            prediction_created_count: 0,
            prediction_scored_count: 0,
            prediction_hit_count: 0,
            mean_direction_brier: null,
            opportunity_observed_count: 4,
            opportunity_missed_count: 1,
            opportunity_coverage_unknown_count: 1,
            limitations: ["read_only_research_summary"],
            proposal_only: true,
            trading_allowed: false,
          },
        },
        {
          id: "opportunities-2026-W28",
          kind: "opportunity_summary",
          occurred_at: "2026-07-12T00:58:00Z",
          quality: "available",
          status: "available",
          data: {
            window_start: "2026-07-05T00:00:00Z",
            window_end: "2026-07-12T00:00:00Z",
            total_count: 4,
            resolution_counts: {
              open: 1,
              deferred: 0,
              acted: 1,
              action_failed: 0,
              declined: 0,
              missed: 1,
              expired_coverage_unknown: 1,
              not_actionable: 0,
              unknown: 0,
            },
            miss_reason_counts: {
              no_decision: 1,
              act_without_action: 0,
              defer_expired: 0,
            },
            proposal_only: true,
            trading_allowed: false,
          },
        },
        {
          id: "automation-latest",
          kind: "automation_status",
          occurred_at: "2026-07-12T00:57:00Z",
          quality: "degraded",
          status: "degraded",
          data: {
            checked_at: "2026-07-12T00:57:00Z",
            overall_status: "degraded",
            jobs: [
              {
                job_id: "weekly",
                expected_schedule: "0 9 * * 0",
                timezone: "Asia/Shanghai",
                freshness_budget_seconds: 691200,
                last_attempt_at: null,
                last_success_at: null,
                fresh_until: null,
                status: "never_run",
                reason_code: "never_run",
                last_run_id: null,
                notification_status: "queued",
              },
            ],
            proposal_only: true,
            trading_allowed: false,
          },
        },
      ],
      sources: [
        ...availableShelf.sources,
        {
          kind: "weekly_review",
          status: "available",
          latest_at: "2026-07-12T00:59:00Z",
          reason_code: null,
        },
        {
          kind: "opportunity_summary",
          status: "available",
          latest_at: "2026-07-12T00:58:00Z",
          reason_code: null,
        },
        {
          kind: "automation_status",
          status: "available",
          latest_at: "2026-07-12T00:57:00Z",
          reason_code: null,
        },
      ],
      warnings: [],
    } satisfies HermesArtifactShelfEnvelope;

    const english = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: automationShelf, locale: "en" }),
    );
    const chinese = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: automationShelf, locale: "zh" }),
    );

    expect(english).toContain("Weekly review · 2026-W28");
    expect(english).toContain("No scored predictions yet");
    expect(english).toContain("Opportunity review");
    expect(english.match(/>Period</g)).toHaveLength(2);
    expect(english).toContain("Missed opportunities");
    expect(english).toContain("Action failed");
    expect(english).toContain("Not actionable");
    expect(english).toContain("Automation status");
    expect(english).toContain("Degraded · attention required");
    expect(english).toContain("Never run");
    expect(english).toContain("Freshness budget");
    expect(english).toContain("Fresh until");
    expect(english).toContain("Queued");
    expect(english).toContain("<details");
    expect(english).toContain('data-hermes-automation-exception="weekly"');
    expect(english).not.toContain(">Market foresight</h3>");
    expect(english.match(/<article/g)).toHaveLength(3);

    expect(chinese).toContain("周报复盘 · 2026-W28");
    expect(chinese).toContain("暂无已评分预测");
    expect(chinese).toContain("机会复盘");
    expect(chinese.match(/>统计区间</g)).toHaveLength(2);
    expect(chinese).toContain("错过机会");
    expect(chinese).toContain("行动失败");
    expect(chinese).toContain("不可行动");
    expect(chinese).toContain("自动化状态");
    expect(chinese).toContain("已降级 · 需要检查");
    expect(chinese).toContain("从未运行");
    expect(chinese).toContain("时效预算");
    expect(chinese).toContain("保鲜截止");
    expect(chinese).toContain("排队中");
    expect(chinese).not.toContain(">市场推演</h3>");
  });

  it("shows that an empty prediction ledger is connected but has no entries", () => {
    const shelfWithoutPredictions = {
      ...availableShelf,
      items: availableShelf.items.filter((item) => item.kind !== "prediction"),
      sources: availableShelf.sources.map((source) =>
        source.kind === "prediction"
          ? { ...source, status: "empty", latest_at: null }
          : source,
      ),
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: shelfWithoutPredictions, locale: "en" }),
    );

    expect(markup).toContain('aria-label="Artifact source status"');
    expect(markup).toContain("Portfolio risk source");
    expect(markup).toContain("Prediction ledger");
    expect(markup).toContain("Market foresight source");
    expect(markup).toContain("empty");
  });

  it("shows prediction direction and scored outcome metrics", () => {
    const scoredPredictionShelf = {
      ...availableShelf,
      items: [
        {
          id: "prediction:pred-20260701-0001",
          kind: "prediction",
          occurred_at: "2026-07-12T00:45:00Z",
          quality: "available",
          status: "scored",
          data: {
            prediction_id: "pred-20260701-0001",
            state: "scored",
            symbol: "AAPL",
            direction: "down",
            confidence: 0.7,
            horizon_date: "2026-07-11",
            rationale: "A bounded scored prediction.",
            outcome_return: -0.025,
            direction_brier: 0.09,
          },
        },
      ],
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: scoredPredictionShelf, locale: "en" }),
    );

    expect(markup).toContain("Direction");
    expect(markup).toContain("down");
    expect(markup).toContain("Outcome return");
    expect(markup).toContain("-2.5%");
    expect(markup).toContain("Direction Brier");
    expect(markup).toContain("0.090");
  });

  it("renders all three artifact kinds as an accessible chronological list", () => {
    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: availableShelf, locale: "en" }),
    );

    expect(markup).toContain("Portfolio risk");
    expect(markup).toContain("Prediction · AAPL");
    expect(markup).toContain("Market foresight");
    expect(markup).toContain("Proposal only · human confirmation required");
    expect(markup).toContain('aria-label="Foresight prediction candidates"');
    expect(markup).toContain("MSFT");
    expect(markup).toContain("flat");
    expect(markup).toContain("58%");
    expect(markup).toContain("2026-07-19");
    expect(markup.match(/<article/g)).toHaveLength(3);
    expect(markup.match(/<li><article/g)).toHaveLength(3);
    expect(markup.match(/<h3/g)).toHaveLength(3);
    expect(markup.match(/<time/g)).toHaveLength(3);
    expect(markup).toContain('dateTime="2026-07-12T00:50:00Z"');
    expect(markup).toContain("available");
  });

  it("distinguishes a healthy empty shelf from a failed artifact read", () => {
    const emptyShelf = {
      ...availableShelf,
      read_status: "empty",
      as_of: null,
      items: [],
      sources: [],
      warnings: [{ source: "artifact_feed", code: "feed_not_built" }],
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: emptyShelf, locale: "en" }),
    );

    expect(markup).toContain("No research artifacts yet");
    expect(markup).toContain("Hermes jobs can populate this read-only shelf");
    expect(markup).not.toContain("Artifacts unavailable");
  });

  it("keeps healthy artifacts visible while announcing a degraded source", () => {
    const degradedShelf = {
      ...availableShelf,
      read_status: "degraded",
      sources: availableShelf.sources.map((source) =>
        source.kind === "prediction"
          ? { ...source, status: "unavailable", reason_code: "ledger_corrupt" }
          : source,
      ),
      warnings: [{ source: "prediction", code: "ledger_corrupt" }],
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: degradedShelf, locale: "en" }),
    );

    expect(markup).toContain("Artifact shelf is degraded");
    expect(markup).toContain("prediction · ledger_corrupt");
    expect(markup).toContain("Portfolio risk");
    expect(markup.match(/<article/g)).toHaveLength(3);
    expect(markup).toContain('role="status"');
  });

  it("shows an explicit no-usable-artifacts state when a degraded read returns no items", () => {
    const degradedEmptyShelf = {
      ...availableShelf,
      read_status: "degraded",
      as_of: null,
      items: [],
      sources: availableShelf.sources.map((source) => ({
        ...source,
        status: "unavailable",
        reason_code: "artifact_source_unreadable",
      })),
      warnings: [{ source: "artifact_feed", code: "artifact_source_unreadable" }],
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: degradedEmptyShelf, locale: "en" }),
    );

    expect(markup).toContain("Artifact shelf is degraded");
    expect(markup).toContain("No usable artifacts are available");
    expect(markup).not.toContain('aria-label="Research artifact timeline"');
  });

  it("renders an explicit unavailable state instead of an empty shelf", () => {
    const unavailableShelf = {
      ...availableShelf,
      read_status: "unavailable",
      as_of: null,
      items: [],
      sources: availableShelf.sources.map((source) => ({
        ...source,
        status: "unavailable",
        reason_code: "artifact_source_unreadable",
      })),
      warnings: [{ source: "artifact_feed", code: "artifact_source_unreadable" }],
      apiError: "503: artifact feed is unavailable",
    } satisfies HermesArtifactShelfEnvelope;

    const markup = renderToStaticMarkup(
      createElement(ArtifactShelf, { envelope: unavailableShelf, locale: "en" }),
    );

    expect(markup).toContain("Artifacts unavailable");
    expect(markup).toContain("artifact_feed · artifact_source_unreadable");
    expect(markup).toContain('role="alert"');
    expect(markup).not.toContain("No research artifacts yet");
    expect(markup).not.toContain("<article");
  });
});
