import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  UnifiedResultDetail,
  UnifiedResultsIndex,
} from "@/components/hermes/results";
import type {
  HermesResultDetailEnvelope,
  HermesResultItem,
  HermesResultsEnvelope,
  HermesResultsFilterModel,
  HermesResultsPaginationModel,
} from "./resultsTypes";
import { hermesResultKey } from "./resultsTypes";

const backtest: HermesResultItem = {
  kind: "backtest",
  resource_id: "backtest-run-20260715",
  display_title: "AAPL momentum backtest",
  summary: "AAPL · 2026-01-01 to 2026-06-30 · Futu",
  status: "completed",
  occurred_at: "2026-07-15T08:30:00Z",
  source: "platform_runs",
  authority: "platform_run_artifact",
  freshness: "not_applicable",
  read_status: "available",
  detail_href: "/api/hermes/results/backtest/backtest-run-20260715",
  original_href: "/api/backtests/backtest-run-20260715",
  run_links: null,
};

function envelope(
  overrides: Partial<HermesResultsEnvelope> = {},
): HermesResultsEnvelope {
  return {
    read_status: "available",
    total: 1,
    total_is_exact: true,
    limit: 20,
    offset: 0,
    has_more: false,
    items: [backtest],
    sources: [
      { source: "platform_runs", read_status: "available", item_count: 1 },
      { source: "platform_run_links", read_status: "empty", item_count: 0 },
    ],
    warnings: [],
    ...overrides,
  };
}

const filters: HermesResultsFilterModel = {
  activeSummary: "Backtest · all sources",
  clearHref: "/en/hermes/results",
  search: {
    action: "/en/hermes/results",
    value: "alpha",
    hiddenFields: [{ name: "kind", value: "backtest" }],
  },
  groups: [
    {
      key: "kind",
      label: "Result type",
      options: [
        {
          key: "all",
          label: "All",
          href: "/en/hermes/results",
          active: false,
        },
        {
          key: "backtest",
          label: "Backtest",
          href: "/en/hermes/results?kind=backtest",
          active: true,
          count: 1,
        },
      ],
    },
  ],
};

const pagination: HermesResultsPaginationModel = {
  previousHref: null,
  nextHref: null,
};

describe("UnifiedResultsIndex", () => {
  it("renders one available result with exact provenance and keyboard-reachable links", () => {
    const html = renderToStaticMarkup(
      createElement(UnifiedResultsIndex, {
        envelope: envelope(),
        locale: "en",
        itemHrefs: {
          [hermesResultKey(backtest)]:
            "/en/hermes/results/backtest/backtest-run-20260715",
        },
        filters,
        pagination,
      }),
    );

    expect(html).toContain("Unified results");
    expect(html).toContain("does not enumerate standalone Hermes runs");
    expect(html).toContain("AAPL momentum backtest");
    expect(html).toContain("AAPL · 2026-01-01 to 2026-06-30 · Futu");
    expect(html).toContain("backtest-run-20260715");
    expect(html).toContain("Platform run artifact");
    expect(html).toContain("Platform runs");
    expect(html).toContain('href="/en/hermes/results/backtest/backtest-run-20260715"');
    expect(html).toContain('href="/en/hermes/results?kind=backtest"');
    expect(html).toContain('aria-current="page"');
    expect(html).toContain('aria-label="Result filters"');
    expect(html).toContain('role="search"');
    expect(html).toContain('method="get"');
    expect(html).toContain('name="search"');
    expect(html).toContain('value="alpha"');
    expect(html).toContain('name="kind" value="backtest"');
    expect(html).toContain("Search results");
    expect(html).toContain('data-hermes-result-key="backtest:backtest-run-20260715"');
    expect(html).not.toContain('method="post"');
  });

  it("keeps degraded sources and corrupt or missing records visible with exact reasons", () => {
    const corrupt: HermesResultItem = {
      ...backtest,
      resource_id: "broken-run",
      status: "unknown",
      freshness: "unknown",
      read_status: "corrupt",
      detail_href: "/api/hermes/results/backtest/broken-run",
      original_href: "/api/backtests/broken-run",
    };
    const missing: HermesResultItem = {
      ...backtest,
      kind: "replication",
      resource_id: "missing-replication",
      status: "unknown",
      freshness: "unknown",
      read_status: "missing",
      detail_href: "/api/hermes/results/replication/missing-replication",
      original_href: "/api/replications/reversal-momentum/missing-replication",
    };
    const html = renderToStaticMarkup(
      createElement(UnifiedResultsIndex, {
        envelope: envelope({
          read_status: "degraded",
          total: 2,
          items: [corrupt, missing],
          sources: [
            { source: "platform_runs", read_status: "degraded", item_count: 2 },
            { source: "hqa_artifact_feed", read_status: "unavailable", item_count: 0 },
          ],
          warnings: [
            {
              source: "platform_runs",
              code: "result_corrupt",
              kind: "backtest",
              resource_id: "broken-run",
            },
            {
              source: "platform_runs",
              code: "result_missing",
              kind: "replication",
              resource_id: "missing-replication",
            },
          ],
        }),
        locale: "en",
        itemHrefs: {
          [hermesResultKey(corrupt)]: "/en/hermes/results/backtest/broken-run",
          [hermesResultKey(missing)]:
            "/en/hermes/results/replication/missing-replication",
        },
        filters,
        pagination,
      }),
    );

    expect(html).toContain('data-hermes-results-degraded="true"');
    expect(html).toContain("Some result sources are degraded");
    expect(html).toContain("platform_runs · result_corrupt · backtest · broken-run");
    expect(html).toContain("platform_runs · result_missing · replication · missing-replication");
    expect(html).toContain('data-hermes-result-read-status="corrupt"');
    expect(html).toContain('data-hermes-result-read-status="missing"');
    expect(html).toContain("HQA artifact feed");
    expect(html).toContain("unavailable · 0");
  });

  it("distinguishes a successful empty catalog from an unavailable catalog", () => {
    const emptyHtml = renderToStaticMarkup(
      createElement(UnifiedResultsIndex, {
        envelope: envelope({
          read_status: "empty",
          total: 0,
          items: [],
          sources: [
            { source: "platform_runs", read_status: "empty", item_count: 0 },
          ],
        }),
        locale: "en",
        itemHrefs: {},
        filters,
        pagination,
      }),
    );
    const unavailableHtml = renderToStaticMarkup(
      createElement(UnifiedResultsIndex, {
        envelope: envelope({
          read_status: "unavailable",
          total: 0,
          items: [],
          sources: [
            { source: "platform_runs", read_status: "unavailable", item_count: 0 },
          ],
          warnings: [
            {
              source: "platform_runs",
              code: "source_unavailable",
              kind: null,
              resource_id: null,
            },
          ],
          apiError: "503: results catalog unavailable",
        }),
        locale: "en",
        itemHrefs: {},
        filters,
        pagination,
      }),
    );

    expect(emptyHtml).toContain("data-hermes-results-empty");
    expect(emptyHtml).toContain("No unified results");
    expect(emptyHtml).not.toContain("Results catalog unavailable");
    expect(unavailableHtml).toContain("data-hermes-results-unavailable");
    expect(unavailableHtml).toContain('role="alert"');
    expect(unavailableHtml).toContain("Results catalog unavailable");
    expect(unavailableHtml).toContain("503: results catalog unavailable");
    expect(unavailableHtml).not.toContain("data-hermes-results-empty");
  });

  it("labels an inexact source count as unknown", () => {
    const html = renderToStaticMarkup(
      createElement(UnifiedResultsIndex, {
        envelope: envelope({
          read_status: "degraded",
          total: null,
          total_is_exact: false,
          has_more: false,
          warnings: [
            {
              source: "platform_runs",
              code: "source_scan_limit_exceeded",
              kind: "factor",
              resource_id: null,
            },
          ],
        }),
        locale: "zh",
        itemHrefs: {},
        filters,
        pagination,
      }),
    );

    expect(html).toContain("总数未知");
    expect(html).not.toContain("共 0");
  });

  it("renders exact previous and next pagination links with localized semantics", () => {
    const html = renderToStaticMarkup(
      createElement(UnifiedResultsIndex, {
        envelope: envelope({
          total: 43,
          limit: 20,
          offset: 20,
          has_more: true,
        }),
        locale: "zh",
        itemHrefs: {
          [hermesResultKey(backtest)]:
            "/zh/hermes/results/backtest/backtest-run-20260715",
        },
        filters: {
          activeSummary: null,
          clearHref: null,
          search: {
            action: "/zh/hermes/results",
            value: "",
            hiddenFields: [],
          },
          groups: [],
        },
        pagination: {
          previousHref: "/zh/hermes/results?limit=20&offset=0",
          nextHref: "/zh/hermes/results?limit=20&offset=40",
        },
      }),
    );

    expect(html).toContain('href="/zh/hermes/results?limit=20&amp;offset=0"');
    expect(html).toContain('href="/zh/hermes/results?limit=20&amp;offset=40"');
    expect(html).toContain('rel="prev"');
    expect(html).toContain('rel="next"');
    expect(html).toContain("上一页");
    expect(html).toContain("下一页");
    expect(html).toContain("当前显示 21–21 共 43");
  });

  it("renders a successful out-of-range empty page without an impossible range", () => {
    const html = renderToStaticMarkup(
      createElement(UnifiedResultsIndex, {
        envelope: envelope({
          read_status: "available",
          total: 22,
          limit: 20,
          offset: 100,
          has_more: false,
          items: [],
        }),
        locale: "zh",
        itemHrefs: {},
        filters,
        pagination: {
          previousHref: "/zh/hermes/results?limit=20&offset=20",
          nextHref: null,
        },
      }),
    );

    expect(html).toContain("data-hermes-results-out-of-range");
    expect(html).toContain("本页已超出结果范围");
    expect(html).toContain("当前页没有结果，请返回上一页或重新调整筛选条件。");
    expect(html).toContain("本页 0 条 · 共 22");
    expect(html).toContain('href="/zh/hermes/results?limit=20&amp;offset=20"');
    expect(html).not.toContain("data-hermes-results-unavailable");
    expect(html).not.toContain("101–100");
    expect(html).not.toContain("0–100");
  });

  it("keeps unavailable and known-empty exact-link states distinct in the index", () => {
    const knownEmpty: HermesResultItem = {
      ...backtest,
      resource_id: "backtest-known-empty",
      detail_href: "/api/hermes/results/backtest/backtest-known-empty",
      original_href: "/api/backtests/backtest-known-empty",
      run_links: [],
    };
    const html = renderToStaticMarkup(
      createElement(UnifiedResultsIndex, {
        envelope: envelope({ total: 2, items: [backtest, knownEmpty] }),
        locale: "en",
        itemHrefs: {},
        filters,
        pagination,
      }),
    );

    expect(html).toContain("data-hermes-result-run-links-state=\"unavailable\"");
    expect(html).toContain("link authority unavailable");
    expect(html).toContain("data-hermes-result-run-links-state=\"empty\"");
    expect(html).toContain("0 exact run links");
  });
});

describe("UnifiedResultDetail", () => {
  it("renders an available resource with exact provenance and Hermes run links", () => {
    const linkedItem: HermesResultItem = {
      ...backtest,
      run_links: [
        {
          command_id: "cmd-01HQA",
          relation: "output",
          hermes_session_id: "session-local-42",
          hermes_run_id: "run-hermes-99",
          link_digest:
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          source_event_id: "event-42",
          observed_at: "2026-07-15T08:31:00Z",
        },
      ],
    };
    const detail: HermesResultDetailEnvelope = {
      read_status: "available",
      item: linkedItem,
      resource: {
        metrics: { total_return: 0.12, sharpe: 1.4 },
        provider: "futu",
      },
      warnings: [],
    };
    const html = renderToStaticMarkup(
      createElement(UnifiedResultDetail, {
        envelope: detail,
        locale: "en",
        backHref: "/en/hermes/results",
        originalResourceHref: "/en/backtest/backtest-run-20260715",
      }),
    );

    expect(html).toContain('data-hermes-result-detail="backtest:backtest-run-20260715"');
    expect(html).toContain("Backtest");
    expect(html).toContain("AAPL momentum backtest");
    expect(html).toContain("AAPL · 2026-01-01 to 2026-06-30 · Futu");
    expect(html).toContain("Platform run artifact");
    expect(html).toContain("/api/hermes/results/backtest/backtest-run-20260715");
    expect(html).toContain("/api/backtests/backtest-run-20260715");
    expect(html).toContain('href="/en/backtest/backtest-run-20260715"');
    expect(html).toContain("cmd-01HQA");
    expect(html).toContain("session-local-42");
    expect(html).toContain("run-hermes-99");
    expect(html).toContain(
      "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    );
    expect(html).toContain("event-42");
    expect(html).toContain("output");
    expect(html).toContain("total_return");
    expect(html).toContain("0.12");
    expect(html).toContain('data-hermes-result-resource="true"');
    expect(html).toContain('tabindex="0"');
    expect(html).not.toContain("<form");
    expect(html).not.toContain("<button");
  });

  it("distinguishes unavailable exact-link authority from a known empty lookup", () => {
    const renderRunLinkState = (runLinks: HermesResultItem["run_links"]) =>
      renderToStaticMarkup(
        createElement(UnifiedResultDetail, {
          envelope: {
            read_status: "available",
            item: { ...backtest, run_links: runLinks },
            resource: { status: "completed" },
            warnings: [],
          } satisfies HermesResultDetailEnvelope,
          locale: "en",
          backHref: "/en/hermes/results",
        }),
      );

    const unavailableHtml = renderRunLinkState(null);
    const omittedHtml = renderRunLinkState(undefined);
    const emptyHtml = renderRunLinkState([]);

    expect(unavailableHtml).toContain("data-hermes-result-run-links-unavailable");
    expect(unavailableHtml).toContain("Exact Hermes run-link authority is unavailable");
    expect(unavailableHtml).not.toContain("data-hermes-result-run-links-empty");
    expect(omittedHtml).toContain("data-hermes-result-run-links-unavailable");
    expect(omittedHtml).not.toContain("data-hermes-result-run-links-empty");
    expect(emptyHtml).toContain("data-hermes-result-run-links-empty");
    expect(emptyHtml).toContain("The exact-link lookup completed");
    expect(emptyHtml).not.toContain("data-hermes-result-run-links-unavailable");
  });

  it("fails closed for missing, corrupt, or unavailable resources while preserving degraded evidence", () => {
    const missingHtml = renderToStaticMarkup(
      createElement(UnifiedResultDetail, {
        envelope: {
          read_status: "missing",
          item: null,
          resource: null,
          warnings: [
            {
              source: "platform_runs",
              code: "result_not_found",
              kind: "backtest",
              resource_id: "missing-run",
            },
          ],
        } satisfies HermesResultDetailEnvelope,
        locale: "en",
        backHref: "/en/hermes/results",
      }),
    );
    const corruptHtml = renderToStaticMarkup(
      createElement(UnifiedResultDetail, {
        envelope: {
          read_status: "corrupt",
          item: null,
          resource: null,
          warnings: [
            {
              source: "platform_experiments",
              code: "result_corrupt",
              kind: "experiment",
              resource_id: "broken-experiment",
            },
          ],
        } satisfies HermesResultDetailEnvelope,
        locale: "zh",
        backHref: "/zh/hermes/results",
      }),
    );
    const unavailableHtml = renderToStaticMarkup(
      createElement(UnifiedResultDetail, {
        envelope: {
          read_status: "unavailable",
          item: null,
          resource: null,
          warnings: [
            {
              source: "hqa_artifact_feed",
              code: "source_unavailable",
              kind: "weekly_review",
              resource_id: "weekly-2026-W29",
            },
          ],
          apiError: "503: local resource adapter unavailable",
        } satisfies HermesResultDetailEnvelope,
        locale: "en",
        backHref: "/en/hermes/results",
      }),
    );
    const degradedItem: HermesResultItem = {
      ...backtest,
      kind: "factor_candidate",
      resource_id: "legacy-factor",
      source: "platform_candidates",
      authority: "platform_candidate_repository",
      status: "pending",
      freshness: "not_applicable",
      read_status: "degraded",
      detail_href: "/api/hermes/results/factor_candidate/legacy-factor",
      original_href: "/api/agent/candidates/legacy-factor",
    };
    const degradedHtml = renderToStaticMarkup(
      createElement(UnifiedResultDetail, {
        envelope: {
          read_status: "degraded",
          item: degradedItem,
          resource: { integrity_state: "migration_required" },
          warnings: [
            {
              source: "platform_candidates",
              code: "candidate_migration_required",
              kind: "factor_candidate",
              resource_id: "legacy-factor",
            },
          ],
        } satisfies HermesResultDetailEnvelope,
        locale: "zh",
        backHref: "/zh/hermes/results",
      }),
    );

    expect(missingHtml).toContain('data-hermes-result-detail-failure="missing"');
    expect(missingHtml).toContain("Result resource not found");
    expect(missingHtml).toContain("platform_runs · result_not_found · backtest · missing-run");
    expect(corruptHtml).toContain('data-hermes-result-detail-failure="corrupt"');
    expect(corruptHtml).toContain("结果资源已损坏");
    expect(corruptHtml).toContain("载荷已安全隐藏");
    expect(unavailableHtml).toContain('data-hermes-result-detail-failure="unavailable"');
    expect(unavailableHtml).toContain("Result source unavailable");
    expect(unavailableHtml).toContain("503: local resource adapter unavailable");
    expect(degradedHtml).toContain('data-hermes-result-detail-degraded="true"');
    expect(degradedHtml).toContain("结果详情已降级");
    expect(degradedHtml).toContain("candidate_migration_required");
    expect(degradedHtml).toContain("migration_required");
    expect(degradedHtml).toContain("data-hermes-result-resource");
    for (const html of [missingHtml, corruptHtml, unavailableHtml]) {
      expect(html).not.toContain("data-hermes-result-resource");
    }
  });
});
