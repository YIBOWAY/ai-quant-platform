import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getSymbols: vi.fn(),
  getMarketDataHistory: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, ...api };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/zh/watch",
  useSearchParams: () => new URLSearchParams(),
}));

import { asiaRadarTitle } from "@/components/asia-radar/AsiaRadarDashboard";
import { marketCrossSectionTitle } from "@/components/market-cross-section/MarketCrossSectionDashboard";
import { dataExplorerTitle } from "@/components/watch/DataExplorerView";
import { WatchMonitor } from "@/components/watch/WatchMonitor";

describe("WatchMonitor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getSymbols.mockResolvedValue({
      symbols: ["SPY"],
      source: "fallback",
      apiError: null,
    });
    api.getMarketDataHistory.mockResolvedValue({
      symbol: "SPY",
      ticker: "SPY",
      source: "fallback",
      frequency: "1d",
      row_count: 0,
      rows: [],
      metadata: {
        provider: "fallback",
        requested_provider: "sample",
        fetched_at: null,
      },
      apiError: "Futu provider unavailable",
    });
  });

  it("keeps all pane links available and loads the active quote view", async () => {
    const tree = await WatchMonitor({
      locale: "zh",
      pane: "quotes",
      params: {},
    });
    const html = renderToStaticMarkup(createElement(() => tree));

    expect(dataExplorerTitle).toEqual({ en: "Symbol Charts", zh: "个股行情" });
    expect(marketCrossSectionTitle).toEqual({ en: "US Risk", zh: "美股风险" });
    expect(asiaRadarTitle).toEqual({ en: "Asia Valuation", zh: "亚洲泡沫" });
    expect(html).toContain(dataExplorerTitle.zh);
    expect(html).toContain(marketCrossSectionTitle.zh);
    expect(html).toContain(asiaRadarTitle.zh);
    expect(html).toContain('data-testid="watch-monitor"');
    expect(html).toContain('data-watch-pane="quotes"');
    expect(html).toContain('data-watch-pane="cross"');
    expect(html).toContain('data-watch-pane="radar"');
    expect(html).toContain('data-testid="data-explorer-scroll-region"');
    expect(api.getSymbols).not.toHaveBeenCalled(); // Company lookup now uses the shared catalog input.
    expect(api.getMarketDataHistory).toHaveBeenCalledOnce();
  });

  it.each(["cross", "radar"] as const)("does not request unrelated quote data on %s", async (pane) => {
    api.getMarketDataHistory.mockRejectedValue(new Error("Quote provider must not run"));
    const tree = await WatchMonitor({ locale: "zh", pane });
    const html = renderToStaticMarkup(createElement(() => tree));
    expect(api.getSymbols).not.toHaveBeenCalled();
    expect(api.getMarketDataHistory).not.toHaveBeenCalled();
    expect(html).not.toContain('data-testid="data-explorer-scroll-region"');
    expect(html.match(/data-watch-capability=/g)).toHaveLength(1);
  });
  it("opens US risk by default while preserving direct symbol links", async () => {
    const main = await WatchMonitor({ locale: "zh" });
    const html = renderToStaticMarkup(createElement(() => main));
    expect(html).toContain('aria-current="page"');
    expect(html).toContain('data-watch-capability="美股风险"');
    expect(api.getMarketDataHistory).not.toHaveBeenCalled();
    const symbol = await WatchMonitor({ locale: "zh", params: { symbol: "META", provider: "futu" } });
    expect(renderToStaticMarkup(createElement(() => symbol))).toContain('data-watch-capability="个股行情"');
    expect(api.getMarketDataHistory).toHaveBeenCalledOnce();
  });
});
