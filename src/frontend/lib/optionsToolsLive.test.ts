import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  calculateLiveGreeks,
  liveResearchHealthCheck,
  rankLiveStrategies,
  simulateLiveCallSpread,
} from "./optionsToolsLive";

const apiClientMock = vi.hoisted(() => ({
  apiPost: vi.fn(),
  apiRequest: vi.fn(),
}));

vi.mock("@/lib/apiClient", () => apiClientMock);

function mockLiveContext() {
  apiClientMock.apiRequest.mockImplementation(async (path: string) => {
    if (path === "/api/options/snapshot/SPY") {
      return {
        ticker: "SPY",
        price: 101,
        nearest_expiry: "2026-06-18",
        atm_iv: 25,
        hv_30d: 0.19,
        iv_rank: 64,
      };
    }

    if (path === "/api/options/chain?ticker=SPY&expiration=2026-06-18&option_type=ALL") {
      return {
        ticker: "SPY",
        expiration: "2026-06-18",
        contracts: [
          {
            option_type: "CALL",
            strike: 95,
            bid: 7,
            ask: 7.4,
            implied_volatility: 0.24,
          },
          {
            option_type: "CALL",
            strike: 100,
            bid: 2.4,
            ask: 2.6,
            implied_volatility: 25,
          },
          {
            option_type: "CALL",
            strike: 105,
            bid: 1.2,
            ask: 1.3,
            implied_volatility: 27,
          },
          {
            option_type: "PUT",
            strike: 100,
            bid: 1.8,
            ask: 2,
            implied_volatility: 0.28,
          },
          {
            option_type: "CALL",
            strike: null,
            bid: 3,
            ask: 3.4,
            implied_volatility: 0.3,
          },
        ],
      };
    }

    throw new Error(`Unexpected request: ${path}`);
  });
}

describe("optionsToolsLive", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-16T08:00:00"));
    apiClientMock.apiPost.mockReset();
    apiClientMock.apiRequest.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("builds a greeks request from the nearest live at-the-money call", async () => {
    mockLiveContext();
    apiClientMock.apiPost.mockResolvedValue({ success: true });

    const result = await calculateLiveGreeks(" spy ");

    expect(result.contract).toMatchObject({
      option_type: "CALL",
      strike: 100,
      expiry: "2026-06-18",
    });
    expect(apiClientMock.apiPost).toHaveBeenCalledWith("/api/options/tools/greeks", {
      spot: 101,
      strike: 100,
      expiry_days: 2,
      iv: 0.25,
      option_type: "call",
    });
  });

  it("builds a bull call spread from adjacent usable live calls", async () => {
    mockLiveContext();
    apiClientMock.apiPost.mockResolvedValue({ success: true });

    await simulateLiveCallSpread("SPY");

    expect(apiClientMock.apiPost).toHaveBeenCalledWith("/api/options/tools/simulate", {
      symbol: "SPY",
      spot: 101,
      legs: [
        {
          action: "buy",
          option_type: "call",
          strike: 100,
          expiry_days: 2,
          iv: 0.25,
          entry_price: 2.5,
        },
        {
          action: "sell",
          option_type: "call",
          strike: 105,
          expiry_days: 2,
          iv: 0.27,
          entry_price: 1.25,
        },
      ],
    });
  });

  it("posts sorted live strikes around spot for strategy ranking", async () => {
    mockLiveContext();
    apiClientMock.apiPost.mockResolvedValue({ success: true });

    await rankLiveStrategies("SPY");

    expect(apiClientMock.apiPost).toHaveBeenCalledWith("/api/options/tools/strategy/rank", {
      market_view: "bullish",
      spot: 101,
      expiry_days: 2,
      strikes: [95, 100, 105],
      iv: 0.25,
      symbol: "SPY",
    });
  });

  it("normalizes research health check tickers and uses the current local date", async () => {
    apiClientMock.apiPost.mockResolvedValue({ success: true });

    await liveResearchHealthCheck(" qqq ");

    expect(apiClientMock.apiPost).toHaveBeenCalledWith("/api/options/tools/health-check", {
      profiles: [
        {
          ticker: "QQQ",
          updated_at: "2026-06-16",
          thesis: "local research watch",
        },
      ],
    });
  });

  it("rejects blank tickers before calling the backend", async () => {
    await expect(liveResearchHealthCheck("   ")).rejects.toThrow("Ticker is required.");
    expect(apiClientMock.apiPost).not.toHaveBeenCalled();
    expect(apiClientMock.apiRequest).not.toHaveBeenCalled();
  });
});
