import type { BacktestJobStateResponse, BacktestRunResponse } from "@/lib/api";
import { ApiClientError, apiRequest } from "@/lib/apiClient";

type BacktestDetailLike = Partial<BacktestRunResponse> & {
  id?: string;
  metadata?: Record<string, unknown>;
};

type WaitForBacktestJobOptions = {
  pollIntervalMs?: number;
  timeoutMs?: number;
};

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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

function normalizeCompletedRun(
  payload: BacktestJobStateResponse,
  detail: BacktestDetailLike,
): BacktestRunResponse {
  return {
    ...detail,
    kind: "backtest",
    status: "completed",
    run_id:
      detail.run_id ??
      detail.id ??
      (typeof detail.metadata?.run_id === "string" ? detail.metadata.run_id : payload.run_id),
  } as BacktestRunResponse;
}

async function fetchCompletedRun(payload: BacktestJobStateResponse) {
  const detail = await apiRequest<BacktestDetailLike>(
    payload.result_url ?? `/api/backtests/${payload.run_id}`,
  );
  return normalizeCompletedRun(payload, detail);
}

export async function waitForBacktestJob(
  payload: BacktestJobStateResponse,
  options: WaitForBacktestJobOptions = {},
) {
  const pollIntervalMs = options.pollIntervalMs ?? 1000;
  const startedAt = Date.now();
  let current = payload;
  while (true) {
    if (current.status === "completed") {
      return fetchCompletedRun(current);
    }
    if (current.status === "failed" || current.status === "cancelled") {
      throw new ApiClientError(jobErrorMessage(current));
    }
    if (options.timeoutMs !== undefined && Date.now() - startedAt >= options.timeoutMs) {
      throw new ApiClientError(`Backtest job did not finish within ${options.timeoutMs}ms.`);
    }
    await sleep(pollIntervalMs);
    current = await apiRequest<BacktestJobStateResponse>(current.poll_url);
  }
}
