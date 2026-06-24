import type { BacktestJobStateResponse, BacktestRunResponse } from "@/lib/api";
import { ApiClientError, apiRequest } from "@/lib/apiClient";

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function isBacktestJobState(payload: unknown): payload is BacktestJobStateResponse {
  return typeof payload === "object" && payload !== null && "poll_url" in payload;
}

function jobErrorMessage(payload: BacktestJobStateResponse) {
  const error = payload.error;
  if (error && typeof error.message === "string") {
    return error.message;
  }
  if (error && typeof error.code === "string") {
    return error.code;
  }
  return `Backtest job ended with status ${payload.status}`;
}

async function fetchCompletedRun(payload: BacktestJobStateResponse) {
  return apiRequest<BacktestRunResponse>(
    payload.result_url ?? `/api/backtests/${payload.run_id}`,
  );
}

export async function waitForBacktestJob(payload: BacktestJobStateResponse) {
  let current = payload;
  for (let attempt = 0; attempt < 300; attempt += 1) {
    if (current.status === "completed") {
      return fetchCompletedRun(current);
    }
    if (current.status === "failed" || current.status === "cancelled") {
      throw new ApiClientError(jobErrorMessage(current));
    }
    await sleep(1000);
    current = await apiRequest<BacktestJobStateResponse>(current.poll_url);
  }
  throw new ApiClientError("Backtest job did not finish within 5 minutes.");
}
