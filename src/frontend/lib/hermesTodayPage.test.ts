import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HermesResultsResponse } from "@/lib/api";
import {
  gatewayFixture,
  healthyArtifacts,
} from "@/lib/hermes/viewModelFixtures";

const api = vi.hoisted(() => ({
  getAgentCandidates: vi.fn(),
  getHermesArtifacts: vi.fn(),
  getHermesGatewayStatus: vi.fn(),
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
import {
  HermesTodayOverviewSection,
  HermesTodaySecondarySection,
} from "@/app/hermes/today-sections";

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

describe("Hermes Today server page (UI-1 Direction A)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getAgentCandidates.mockResolvedValue({ candidates: [] });
    api.getHermesArtifacts.mockResolvedValue(healthyArtifacts);
    api.getHermesGatewayStatus.mockResolvedValue(gatewayFixture());
    api.getHermesResults.mockResolvedValue(platformResults);
  });

  it("renders both Suspense boundaries with chunked skeleton fallbacks", async () => {
    const page = await HermesWorkbenchPage();
    const html = renderToStaticMarkup(createElement(() => page));

    expect(html).toContain('data-hermes-today-skeleton="overview"');
    expect(html).toContain('data-hermes-today-skeleton="secondary"');
  });

  it("overview boundary fetches candidates + artifacts + gateway in parallel", async () => {
    const section = await HermesTodayOverviewSection({ locale: "zh" });
    const html = renderToStaticMarkup(createElement(() => section));

    expect(api.getAgentCandidates).toHaveBeenCalledOnce();
    expect(api.getHermesArtifacts).toHaveBeenCalledOnce();
    expect(api.getHermesGatewayStatus).toHaveBeenCalledOnce();
    expect(html).toContain('data-testid="hermes-today-state"');
    expect(html).toContain("Hermes 在线");
    expect(html).toContain("自动化");
  });

  it("secondary boundary renders the merged five-item results list and automation lane", async () => {
    const section = await HermesTodaySecondarySection({ locale: "zh" });
    const html = renderToStaticMarkup(createElement(() => section));

    expect(api.getHermesResults).toHaveBeenCalledWith({ limit: 5, offset: 0 });
    expect(html).toContain("AAPL 页面接线回测");
    expect(html).toContain("最近结果");
    expect(html).toContain("/zh/hermes/results/backtest/backtest-wave3-page");
    expect(html).toContain("自动化 4/4 正常");
    // Automation renders exactly once (no artifact-card duplicate).
    expect(html.match(/data-hermes-automation-summary/g)).toHaveLength(1);
  });
});
