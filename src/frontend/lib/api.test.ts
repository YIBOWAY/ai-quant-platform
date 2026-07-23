import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getAgentCandidateDetail,
  getAiHotItems,
  getFactorLabDashboard,
  getHermesResultDetail,
  getHermesResults,
  type FactorLabResponse,
} from "./api";

const factorLabPayload = {
  source: "sample",
  benchmark_symbol: "SPY",
  universe: {
    id: "technology",
    name: "Technology",
    description: "",
    symbols: ["NVDA"],
    benchmark_symbol: "SPY",
  },
  factors: [],
  guardrails: {},
  cache: {},
  cross_sectional: { engine: "cross_sectional_health", rows: [] },
  timing: { engine: "single_symbol_timing", symbol: "NVDA", rows: [] },
};

function factorLabGuardrailSummary(payload: FactorLabResponse) {
  return `${payload.guardrails.walk_forward.fold_count}:${payload.guardrails.leakage_audit.status}`;
}

describe("getFactorLabDashboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("passes the full Factor Lab query to the backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(factorLabPayload), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getFactorLabDashboard({
      provider: "tiingo",
      universeId: "technology",
      symbol: "nvda",
      benchmarkSymbol: "spy",
      start: "2023-01-03",
      end: "2023-12-29",
      lookback: 63,
      forceRefresh: true,
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.pathname).toBe("/api/factors/lab");
    expect(Object.fromEntries(url.searchParams.entries())).toMatchObject({
      provider: "tiingo",
      universe_id: "technology",
      symbol: "NVDA",
      benchmark_symbol: "SPY",
      start: "2023-01-03",
      end: "2023-12-29",
      lookback: "63",
      force_refresh: "true",
    });
  });

  it("exposes typed guardrail fields to frontend callers", () => {
    expect(
      factorLabGuardrailSummary({
        ...factorLabPayload,
        guardrails: {
          exploratory_only: true,
          warning: "review before promotion",
          walk_forward: {
            enabled: true,
            train_bars: 60,
            validation_bars: 20,
            step_bars: 20,
            fold_count: 3,
          },
          leakage_audit: {
            status: "basic_passed",
            checked: true,
            rule: "tradeable_ts must be later than signal_ts",
          },
        },
        cache: {
          status: "recomputed",
          path: "data/factor_lab/factor_lab_cache.json",
          key: {
            provider: "sample",
            universe_id: "technology",
            symbol: "NVDA",
            benchmark_symbol: "SPY",
            start: "2023-01-03",
            end: "2023-12-29",
            lookback: 63,
          },
        },
      }),
    ).toBe("3:basic_passed");
  });
});

describe("getAiHotItems", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("passes the AI HOT feed query to the backend without contacting the upstream provider", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          provider: "aihot",
          provider_beta: true,
          fetched_at: "2026-06-28T00:00:00Z",
          count: 0,
          has_next: false,
          next_cursor: null,
          items: [],
          warnings: [],
          research_safety: {
            research_only: true,
            not_investment_advice: true,
            does_not_trigger_trading: true,
            verify_original_source: true,
          },
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAiHotItems({
      mode: "all",
      category: "ai-models",
      q: "OpenAI",
      since: "2026-06-28T00:00:00Z",
      cursor: "opaque-cursor",
      take: 25,
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.pathname).toBe("/api/news/items");
    expect(Object.fromEntries(url.searchParams.entries())).toEqual({
      mode: "all",
      category: "ai-models",
      q: "OpenAI",
      since: "2026-06-28T00:00:00Z",
      cursor: "opaque-cursor",
      take: "25",
    });
  });
});

describe("getAgentCandidateDetail", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("encodes a deep-linked candidate id as one path segment", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          candidate_id: "factor with spaces/and-slash",
          metadata: null,
          source_preview: null,
          audit: [],
          reviews: [],
          integrity_state: "corrupt",
          manifest_digest: null,
          observed_manifest_digest: null,
          approval_binding: null,
          approval_enabled: false,
          integrity_error_code: "candidate_not_found",
          status: null,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAgentCandidateDetail("factor with spaces/and-slash");

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://127.0.0.1:8765/api/agent/candidates/factor%20with%20spaces%2Fand-slash",
    );
  });
});

describe("getHermesResults", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends only bounded, explicit read-only filters and pagination", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "empty",
          total: 0,
          total_is_exact: true,
          limit: 100,
          offset: 0,
          has_more: false,
          items: [],
          sources: [],
          warnings: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getHermesResults({
      kind: "backtest",
      source: "platform_runs",
      status: " completed ",
      search: " alpha ",
      limit: 500,
      offset: -3,
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.pathname).toBe("/api/hermes/results");
    expect(Object.fromEntries(url.searchParams.entries())).toEqual({
      limit: "100",
      offset: "0",
      kind: "backtest",
      status: "completed",
      source: "platform_runs",
      search: "alpha",
    });
  });

  it("preserves an explicitly unknown total instead of inventing zero", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "degraded",
          total: null,
          total_is_exact: false,
          limit: 20,
          offset: 0,
          has_more: true,
          items: [],
          sources: [
            {
              source: "platform_runs",
              read_status: "unavailable",
              item_count: 0,
            },
          ],
          warnings: [
            {
              source: "platform_runs",
              code: "source_scan_limit_exceeded",
              kind: "factor",
              resource_id: null,
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResults();

    expect(result.apiError).toBeUndefined();
    expect(result.total).toBeNull();
    expect(result.total_is_exact).toBe(false);
    expect(result.has_more).toBe(true);
  });

  it("accepts an exact empty page whose offset is beyond the final result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "available",
          total: 22,
          total_is_exact: true,
          limit: 20,
          offset: 100,
          has_more: false,
          items: [],
          sources: [
            {
              source: "platform_runs",
              read_status: "available",
              item_count: 22,
            },
          ],
          warnings: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResults({ limit: 20, offset: 100 });

    expect(result).toMatchObject({
      read_status: "available",
      total: 22,
      total_is_exact: true,
      limit: 20,
      offset: 100,
      has_more: false,
      items: [],
    });
    expect(result).not.toHaveProperty("apiError");
  });

  it("fails closed when an exact reachable page omits its results", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "available",
          total: 22,
          total_is_exact: true,
          limit: 20,
          offset: 0,
          has_more: false,
          items: [],
          sources: [
            {
              source: "platform_runs",
              read_status: "available",
              item_count: 22,
            },
          ],
          warnings: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResults({ limit: 20, offset: 0 });

    expect(result).toMatchObject({
      read_status: "unavailable",
      total: null,
      total_is_exact: false,
      items: [],
      apiError: "results_response_invalid",
    });
  });

  it("fetches one validated result identity as two encoded path segments", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "missing",
          item: null,
          resource: null,
          warnings: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getHermesResultDetail("factor_candidate", "candidate.v3-safe_01");

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://127.0.0.1:8765/api/hermes/results/factor_candidate/candidate.v3-safe_01",
    );
  });

  it("fails closed without a request when a result identity is not route-safe", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResultDetail(
      "not_a_kind" as "backtest",
      "../escape",
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result).toMatchObject({
      read_status: "unavailable",
      item: null,
      resource: null,
      apiError: "invalid_result_identity",
      warnings: [{ code: "invalid_result_identity" }],
    });
  });

  it("fails closed when a successful catalog response contains unsafe evidence", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "available",
          total: 1,
          total_is_exact: true,
          limit: 20,
          offset: 0,
          has_more: false,
          items: [
            {
              kind: "backtest",
              resource_id: "../escape",
              display_title: "Unsafe path result",
              summary: null,
              status: "completed",
              occurred_at: "2026-07-15T08:30:00Z",
              source: "platform_runs",
              authority: "platform_run_artifact",
              freshness: "not_applicable",
              read_status: "available",
              detail_href: "/api/hermes/results/backtest/../escape",
              original_href: "/api/backtests/../escape",
              run_links: null,
            },
          ],
          sources: [],
          warnings: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResults();

    expect(result).toMatchObject({
      read_status: "unavailable",
      total: null,
      total_is_exact: false,
      items: [],
      apiError: "results_response_invalid",
      warnings: [{ code: "results_response_invalid" }],
    });
  });

  it("withholds a detail payload that is bound to a different result identity", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "available",
          item: {
            kind: "backtest",
            resource_id: "different-safe-id",
            display_title: "Different result",
            summary: null,
            status: "completed",
            occurred_at: "2026-07-15T08:30:00Z",
            source: "platform_runs",
            authority: "platform_run_artifact",
            freshness: "not_applicable",
            read_status: "available",
            detail_href:
              "/api/hermes/results/backtest/different-safe-id",
            original_href: "/api/backtests/different-safe-id",
            run_links: null,
          },
          resource: { secret: "must-not-render" },
          warnings: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResultDetail("backtest", "expected-safe-id");

    expect(result).toMatchObject({
      read_status: "unavailable",
      item: null,
      resource: null,
      apiError: "results_response_invalid",
    });
    expect(JSON.stringify(result)).not.toContain("must-not-render");
  });

  it("treats any non-string apiError field as an invalid catalog response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "empty",
          total: 0,
          total_is_exact: true,
          limit: 20,
          offset: 0,
          has_more: false,
          items: [],
          sources: [],
          warnings: [],
          apiError: { message: "must not coexist with healthy evidence" },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResults();

    expect(result).toMatchObject({
      read_status: "unavailable",
      items: [],
      apiError: "results_response_invalid",
    });
  });

  it("treats any non-string apiError field as an invalid detail response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "missing",
          item: null,
          resource: null,
          warnings: [],
          apiError: 503,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResultDetail("backtest", "expected-safe-id");

    expect(result).toMatchObject({
      read_status: "unavailable",
      item: null,
      resource: null,
      apiError: "results_response_invalid",
    });
  });

  it("withholds a detail resource larger than the frontend render bound", async () => {
    const resourceId = "bounded-safe-id";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "available",
          item: {
            kind: "backtest",
            resource_id: resourceId,
            display_title: "Bounded result",
            summary: null,
            status: "completed",
            occurred_at: "2026-07-15T08:30:00Z",
            source: "platform_runs",
            authority: "platform_run_artifact",
            freshness: "not_applicable",
            read_status: "available",
            detail_href: `/api/hermes/results/backtest/${resourceId}`,
            original_href: `/api/backtests/${resourceId}`,
            run_links: null,
          },
          resource: { payload: "x".repeat(1_048_577) },
          warnings: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResultDetail("backtest", resourceId);

    expect(result).toMatchObject({
      read_status: "unavailable",
      item: null,
      resource: null,
      apiError: "results_response_invalid",
    });
  });

  it("accepts a degraded detail whose oversized resource was withheld by the BFF", async () => {
    const resourceId = "server-bounded-safe-id";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "degraded",
          item: {
            kind: "factor",
            resource_id: resourceId,
            display_title: "Bounded factor result",
            summary: "The original detail remains available through its authoritative link.",
            status: "completed",
            occurred_at: "2026-07-15T08:30:00Z",
            source: "platform_runs",
            authority: "platform_run_artifact",
            freshness: "not_applicable",
            read_status: "available",
            detail_href: `/api/hermes/results/factor/${resourceId}`,
            original_href: `/api/factors/${resourceId}`,
            run_links: [],
          },
          resource: null,
          warnings: [
            {
              source: "platform_runs",
              code: "resource_payload_too_large",
              kind: "factor",
              resource_id: resourceId,
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResultDetail("factor", resourceId);

    expect(result).toMatchObject({
      read_status: "degraded",
      item: { resource_id: resourceId },
      resource: null,
      warnings: [{ code: "resource_payload_too_large" }],
    });
    expect(result).not.toHaveProperty("apiError");
  });

  it("rejects an available detail state without an authoritative item and resource", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          read_status: "available",
          item: null,
          resource: null,
          warnings: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getHermesResultDetail("backtest", "expected-safe-id");

    expect(result).toMatchObject({
      read_status: "unavailable",
      item: null,
      resource: null,
      apiError: "results_response_invalid",
    });
  });
});
