import { describe, expect, it } from "vitest";

import type { HermesResultsEnvelope } from "./resultsTypes";
import {
  hermesResultKey,
  isHermesResultResourceId,
  parseHermesResultRouteResourceId,
} from "./resultsTypes";
import {
  buildHermesOriginalResultHref,
  buildHermesResultsPageModel,
  parseHermesResultsSearchParams,
} from "./resultsRouting";

describe("parseHermesResultsSearchParams", () => {
  it("accepts only bounded catalog filters and pagination", () => {
    expect(
      parseHermesResultsSearchParams({
        kind: ["backtest", "paper"],
        source: "platform_runs",
        status: " completed ",
        search: " alpha ",
        limit: "500",
        offset: "-7",
      }),
    ).toEqual({
      kind: "backtest",
      source: "platform_runs",
      status: "completed",
      search: "alpha",
      limit: 100,
      offset: 0,
    });

    expect(
      parseHermesResultsSearchParams({
        kind: "not-a-kind",
        source: "not-a-source",
        status: " ",
        search: "x".repeat(257),
        limit: "not-a-number",
        offset: "12.5",
      }),
    ).toEqual({ limit: 20, offset: 0 });
  });
});

describe("isHermesResultResourceId", () => {
  it("accepts canonical HQA kind:digest identities without admitting paths", () => {
    expect(
      isHermesResultResourceId(
        "portfolio-risk:9b32027c89f395f39cba368a",
      ),
    ).toBe(true);
    expect(isHermesResultResourceId("../private")).toBe(false);
    expect(isHermesResultResourceId("safe/child")).toBe(false);
  });

  it("decodes exactly one safe route segment for HQA identities", () => {
    expect(
      parseHermesResultRouteResourceId(
        "portfolio-risk%3A9b32027c89f395f39cba368a",
      ),
    ).toBe("portfolio-risk:9b32027c89f395f39cba368a");
    expect(
      parseHermesResultRouteResourceId(
        "portfolio-risk%253A9b32027c89f395f39cba368a",
      ),
    ).toBeNull();
    expect(parseHermesResultRouteResourceId("safe%2Fchild")).toBeNull();
    expect(parseHermesResultRouteResourceId("bad%ZZvalue")).toBeNull();
  });
});

describe("buildHermesResultsPageModel", () => {
  it("builds localized result, filter, and pagination hrefs without losing active filters", () => {
    const envelope: HermesResultsEnvelope = {
      read_status: "available",
      total: 45,
      total_is_exact: true,
      limit: 20,
      offset: 20,
      has_more: true,
      items: [
        {
          kind: "backtest",
          resource_id: "backtest-20260715-safe",
          display_title: "Safe backtest",
          summary: null,
          status: "completed",
          occurred_at: "2026-07-15T08:30:00Z",
          source: "platform_runs",
          authority: "platform_run_artifact",
          freshness: "not_applicable",
          read_status: "available",
          detail_href:
            "/api/hermes/results/backtest/backtest-20260715-safe",
          original_href: "/api/backtests/backtest-20260715-safe",
          run_links: null,
        },
      ],
      sources: [],
      warnings: [],
    };
    const query = parseHermesResultsSearchParams({
      kind: "backtest",
      source: "platform_runs",
      status: "completed",
      search: "alpha",
      limit: "20",
      offset: "20",
    });

    const model = buildHermesResultsPageModel({
      envelope,
      locale: "zh",
      query,
    });

    const item = envelope.items[0];
    expect(model.itemHrefs[hermesResultKey(item)]).toBe(
      "/zh/hermes/results/backtest/backtest-20260715-safe",
    );
    expect(new URL(model.pagination.previousHref!, "http://local").searchParams).toEqual(
      new URLSearchParams({
        kind: "backtest",
        status: "completed",
        source: "platform_runs",
        search: "alpha",
      }),
    );
    expect(new URL(model.pagination.nextHref!, "http://local").searchParams).toEqual(
      new URLSearchParams({
        kind: "backtest",
        status: "completed",
        source: "platform_runs",
        search: "alpha",
        offset: "40",
      }),
    );
    expect(model.filters.activeSummary).toContain("回测");
    expect(model.filters.activeSummary).toContain("completed");
    expect(model.filters.clearHref).toBe("/zh/hermes/results");
    expect(model.filters.search).toEqual({
      action: "/zh/hermes/results",
      value: "alpha",
      hiddenFields: [
        { name: "kind", value: "backtest" },
        { name: "status", value: "completed" },
        { name: "source", value: "platform_runs" },
      ],
    });

    const kindGroup = model.filters.groups.find((group) => group.key === "kind");
    const sourceGroup = model.filters.groups.find(
      (group) => group.key === "source",
    );
    expect(kindGroup?.options.find((option) => option.key === "backtest")?.active).toBe(
      true,
    );
    expect(sourceGroup?.options.find((option) => option.key === "platform_runs")?.active).toBe(
      true,
    );
  });

  it("returns an out-of-range page directly to the last valid exact page", () => {
    const envelope: HermesResultsEnvelope = {
      read_status: "available",
      total: 22,
      total_is_exact: true,
      limit: 20,
      offset: 100,
      has_more: false,
      items: [],
      sources: [],
      warnings: [],
    };
    const query = parseHermesResultsSearchParams({
      limit: "20",
      offset: "100",
    });

    const model = buildHermesResultsPageModel({
      envelope,
      locale: "zh",
      query,
    });

    expect(new URL(model.pagination.previousHref!, "http://local").searchParams).toEqual(
      new URLSearchParams({ offset: "20" }),
    );
  });

  it("links only known authoritative result identities to existing localized views", () => {
    const base = {
      resource_id: "result-safe_01",
      display_title: "Safe result",
      summary: null,
      status: "completed",
      occurred_at: "2026-07-15T08:30:00Z",
      freshness: "not_applicable" as const,
      read_status: "available" as const,
      detail_href: "/api/hermes/results/backtest/result-safe_01",
      original_href: "/api/backtests/result-safe_01",
      run_links: null,
    };

    expect(
      buildHermesOriginalResultHref(
        {
          ...base,
          kind: "backtest",
          source: "platform_runs",
          authority: "platform_run_artifact",
        },
        "en",
      ),
    ).toBe("/en/backtest/result-safe_01");
    expect(
      buildHermesOriginalResultHref(
        {
          ...base,
          kind: "factor_candidate",
          source: "platform_candidates",
          authority: "platform_candidate_repository",
        },
        "zh",
      ),
    ).toBe("/zh/hermes/approvals?candidate=result-safe_01");
    expect(
      buildHermesOriginalResultHref(
        {
          ...base,
          kind: "portfolio_risk",
          source: "hqa_artifact_feed",
          authority: "hqa_artifact_manifest",
        },
        "en",
      ),
    ).toBeNull();
    expect(
      buildHermesOriginalResultHref(
        {
          ...base,
          resource_id: "../unsafe",
          kind: "backtest",
          source: "platform_runs",
          authority: "platform_run_artifact",
        },
        "en",
      ),
    ).toBeNull();
  });
});
