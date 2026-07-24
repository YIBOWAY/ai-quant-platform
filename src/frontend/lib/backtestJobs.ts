import type { BacktestJobStateResponse, BacktestRunResponse } from "@/lib/api";
import { ApiClientError, apiRequest } from "@/lib/apiClient";

type BacktestDetailLike = Partial<BacktestRunResponse> & {
  id?: string;
  metadata?: Record<string, unknown>;
};

type WaitForBacktestJobOptions = {
  pollIntervalMs?: number;
  timeoutMs?: number;
  signal?: AbortSignal;
};

const DEFAULT_JOB_TIMEOUT_MS = 10 * 60 * 1000;

function pollingCancelledError() {
  return new ApiClientError("Backtest job polling was cancelled.");
}

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(pollingCancelledError());
      return;
    }
    const timeoutId = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timeoutId);
      reject(pollingCancelledError());
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
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

async function fetchCompletedRun(payload: BacktestJobStateResponse, signal?: AbortSignal) {
  const path = payload.result_url ?? `/api/backtests/${payload.run_id}`;
  const detail = signal
    ? await apiRequest<BacktestDetailLike>(path, { signal })
    : await apiRequest<BacktestDetailLike>(path);
  return normalizeCompletedRun(payload, detail);
}

export async function waitForBacktestJob(
  payload: BacktestJobStateResponse,
  options: WaitForBacktestJobOptions = {},
) {
  const pollIntervalMs = options.pollIntervalMs ?? 1000;
  const timeoutMs = options.timeoutMs ?? DEFAULT_JOB_TIMEOUT_MS;
  const startedAt = Date.now();
  let current = payload;
  while (true) {
    if (options.signal?.aborted) {
      throw pollingCancelledError();
    }
    if (current.status === "completed") {
      return fetchCompletedRun(current, options.signal);
    }
    if (current.status === "failed" || current.status === "cancelled") {
      throw new ApiClientError(jobErrorMessage(current));
    }
    if (Date.now() - startedAt >= timeoutMs) {
      throw new ApiClientError(`Backtest job did not finish within ${timeoutMs}ms.`);
    }
    await sleep(pollIntervalMs, options.signal);
    current = await apiRequest<BacktestJobStateResponse>(
      current.poll_url,
      options.signal ? { signal: options.signal } : {},
    );
  }
}
