import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BacktestJobStateResponse } from "./api";
import { ApiClientError, apiRequest } from "./apiClient";
import { waitForBacktestJob } from "./backtestJobs";

vi.mock("./apiClient", async () => {
  const actual = await vi.importActual<typeof import("./apiClient")>("./apiClient");
  return {
    ...actual,
    apiRequest: vi.fn(),
  };
});

const mockedApiRequest = vi.mocked(apiRequest);

function jobState(status: BacktestJobStateResponse["status"]): BacktestJobStateResponse {
  return {
    run_id: "backtest-20260624T010203Z-testjob",
    kind: "backtest",
    status,
    poll_url: "/api/backtests/jobs/backtest-20260624T010203Z-testjob",
    result_url: "/api/backtests/backtest-20260624T010203Z-testjob",
  };
}

describe("waitForBacktestJob", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockedApiRequest.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("normalizes completed detail responses so callers keep the run id", async () => {
    mockedApiRequest.mockResolvedValueOnce({
      id: "backtest-20260624T010203Z-testjob",
      metadata: { run_id: "backtest-20260624T010203Z-testjob" },
      metrics: { total_return: 0.12 },
      equity_curve: [],
      benchmark: null,
      orders: [],
      positions: [],
      trade_blotter: [],
      attribution: [],
    });

    const result = await waitForBacktestJob(jobState("completed"));

    expect(result.run_id).toBe("backtest-20260624T010203Z-testjob");
    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/api/backtests/backtest-20260624T010203Z-testjob",
    );
  });

  it("does not impose a default five-minute polling cap", async () => {
    mockedApiRequest
      .mockResolvedValueOnce(jobState("running"))
      .mockResolvedValueOnce(jobState("completed"))
      .mockResolvedValueOnce({
        id: "backtest-20260624T010203Z-testjob",
        metadata: { run_id: "backtest-20260624T010203Z-testjob" },
        metrics: {},
        equity_curve: [],
        benchmark: null,
        orders: [],
        positions: [],
        trade_blotter: [],
        attribution: [],
      });

    const promise = waitForBacktestJob(jobState("running"), { pollIntervalMs: 1 });
    await vi.advanceTimersByTimeAsync(1);
    await vi.advanceTimersByTimeAsync(1);

    await expect(promise).resolves.toMatchObject({
      run_id: "backtest-20260624T010203Z-testjob",
    });
  });

  it("supports an explicit timeout for callers that need one", async () => {
    mockedApiRequest.mockResolvedValue(jobState("running"));

    const promise = waitForBacktestJob(jobState("running"), {
      pollIntervalMs: 1,
      timeoutMs: 2,
    });
    const assertion = expect(promise).rejects.toMatchObject({
      message: "Backtest job did not finish within 2ms.",
      name: "ApiClientError",
    } satisfies Partial<ApiClientError>);

    await vi.advanceTimersByTimeAsync(3);

    await assertion;
  });
});
