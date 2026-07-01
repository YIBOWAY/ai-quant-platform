import { afterEach, describe, expect, it, vi } from "vitest";

import { getAiHotItems, getFactorLabDashboard, type FactorLabResponse } from "./api";

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
    expect(url.pathname).toBe("/api/news/aihot/items");
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
