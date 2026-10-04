import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  calculateLiveGreeks,
  liveBullPutSignal,
  liveEarningsCrush,
  liveHedgeAdvisor,
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
        atm_iv: 0.25,
        hv_30d: 0.19,
        iv_rank: 64,
        iv_rank_source: "local_hv_proxy",
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
            implied_volatility: 24,
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
            implied_volatility: 28,
          },
          {
            option_type: "CALL",
            strike: null,
            bid: 3,
            ask: 3.4,
            implied_volatility: 30,
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

  it("converts low Futu percentage IV exactly once instead of guessing its unit", async () => {
    mockLiveContext();
    const originalRequest = apiClientMock.apiRequest.getMockImplementation()!;
    apiClientMock.apiRequest.mockImplementation(async (path: string) => {
      const response = await originalRequest(path);
      if (response.contracts) response.contracts.forEach((contract: { implied_volatility: number }) => { contract.implied_volatility = 0.5; });
      return response;
    });
    apiClientMock.apiPost.mockResolvedValue({ success: true });
    await calculateLiveGreeks("SPY");
    expect(apiClientMock.apiPost).toHaveBeenCalledWith("/api/options/tools/greeks", expect.objectContaining({ iv: 0.005 }));
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

  it("requests the saved research profile without fabricating a date or thesis", async () => {
    apiClientMock.apiPost.mockResolvedValue({ success: true });

    await liveResearchHealthCheck(" qqq ");

    expect(apiClientMock.apiPost).toHaveBeenCalledWith("/api/options/tools/health-check", {
      ticker: "QQQ",
    });
  });

  it("does not turn an HV proxy or incomplete fear score into an entry signal", async () => {
    mockLiveContext();
    apiClientMock.apiPost.mockResolvedValue({ fear_score: null, status: "unavailable" });
    await expect(liveBullPutSignal("SPY")).rejects.toThrow("insufficient_fear_inputs");
    expect(apiClientMock.apiPost).toHaveBeenCalledExactlyOnceWith("/api/options/tools/fear-score", { iv_rank: null });
  });

  it("does not supply a made-up empty event history as a completed earnings study", async () => {
    mockLiveContext();
    apiClientMock.apiPost.mockResolvedValue({ success: true, sample_count: 0 });
    await liveEarningsCrush("SPY");
    expect(apiClientMock.apiPost).toHaveBeenCalledWith("/api/options/tools/earnings-crush", { ticker: "SPY", current_iv: 0.25 });
  });

  it("builds a hedge-advisor request from live chain data and supplied holdings", async () => {
    mockLiveContext();
    apiClientMock.apiPost.mockResolvedValue({ success: true });

    await liveHedgeAdvisor(" spy ", {
      shares: 250,
      costBasis: 96.5,
      purpose: "protect",
    });

    expect(apiClientMock.apiPost).toHaveBeenCalledWith("/api/options/tools/hedge-advisor", {
      ticker: "SPY",
      shares: 250,
      cost_basis: 96.5,
      spot: 101,
      purpose: "protect",
      contracts: expect.arrayContaining([
        expect.objectContaining({ option_type: "PUT", strike: 100, expiry: "2026-06-18" }),
        expect.objectContaining({ option_type: "CALL", strike: 105, expiry: "2026-06-18" }),
      ]),
    });
  });

  it("rejects fractional shares before fetching rather than silently truncating them", async () => {
    await expect(liveHedgeAdvisor("SPY", { shares: 1.5, costBasis: 96.5 })).rejects.toThrow("positive_integer_shares_required");
    expect(apiClientMock.apiRequest).not.toHaveBeenCalled();
    expect(apiClientMock.apiPost).not.toHaveBeenCalled();
  });

  it("rejects blank tickers before calling the backend", async () => {
    await expect(liveResearchHealthCheck("   ")).rejects.toThrow("Ticker is required.");
    expect(apiClientMock.apiPost).not.toHaveBeenCalled();
    expect(apiClientMock.apiRequest).not.toHaveBeenCalled();
  });
});
