import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HermesResultsResponse } from "@/lib/api";
import { healthyArtifacts } from "@/lib/hermes/viewModelFixtures";

const api = vi.hoisted(() => ({
  getAgentCandidates: vi.fn(),
  getHermesArtifacts: vi.fn(),
  getHermesResults: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, ...api };
});

vi.mock("@/lib/serverLocale", () => ({
  getServerLocale: vi.fn(async () => "zh" as const),
}));

import HermesWorkbenchPage from "@/app/hermes/page";

const platformResults = {
  read_status: "available",
  total: 1,
  total_is_exact: true,
  limit: 5,
  offset: 0,
  has_more: false,
  items: [
    {
      kind: "backtest",
      resource_id: "backtest-wave3-page",
      display_title: "AAPL 页面接线回测",
      summary: "只读统一目录预览",
      status: "completed",
      occurred_at: "2026-07-15T08:00:00Z",
      source: "platform_runs",
      authority: "platform_run_artifact",
      freshness: "fresh",
      read_status: "available",
      detail_href: "/api/hermes/results/backtest/backtest-wave3-page",
      original_href: "/api/backtest/runs/backtest-wave3-page",
      run_links: [],
    },
  ],
  sources: [
    { source: "platform_runs", read_status: "available", item_count: 1 },
  ],
  warnings: [],
} as unknown as HermesResultsResponse;

describe("Hermes Today server page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getAgentCandidates.mockResolvedValue({ candidates: [] });
    api.getHermesArtifacts.mockResolvedValue(healthyArtifacts);
    api.getHermesResults.mockResolvedValue(platformResults);
  });

  it("loads and renders a five-item GET-only unified-results preview", async () => {
    const page = await HermesWorkbenchPage();
    const html = renderToStaticMarkup(createElement(() => page));

    expect(api.getHermesResults).toHaveBeenCalledWith({ limit: 5, offset: 0 });
    expect(api.getAgentCandidates).toHaveBeenCalledOnce();
    expect(api.getHermesArtifacts).toHaveBeenCalledOnce();
    expect(html).toContain("AAPL 页面接线回测");
    expect(html).toContain("HQA 结论产物");
  });
});
