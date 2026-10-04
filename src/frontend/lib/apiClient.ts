// An explicit NEXT_PUBLIC_QUANT_API_BASE_URL always wins (the coo preview
// points it at its own origin). Otherwise browser callers go through the
// same-origin /api rewrite from next.config.ts so dev servers on any port
// avoid CORS, while server-side SSR fetch keeps the absolute local backend
// address (Node cannot resolve relative URLs).
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_QUANT_API_BASE_URL ??
  (typeof window === "undefined" ? "http://127.0.0.1:8765" : "");

const DEFAULT_TIMEOUT_MS = 180_000;

export class ApiClientError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly outcome: "definitive_failure" | "outcome_unknown" =
      "definitive_failure",
  ) {
    super(
      outcome === "outcome_unknown" ? `[outcome_unknown] ${message}` : message,
    );
    this.name = "ApiClientError";
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function parseError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (payload.detail && typeof payload.detail === "object") {
      const detail = payload.detail as Record<string, unknown>;
      const message = typeof detail.message === "string" ? detail.message : "";
      const code = typeof detail.code === "string" ? `[${detail.code}] ` : "";
      if (message) {
        return `${code}${message}`;
      }
    }
    return JSON.stringify(payload.detail ?? payload);
  } catch {
    return response.statusText || "API request failed";
  }
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  retryCount = 0,
): Promise<T> {
  const method = String(init.method ?? "GET").toUpperCase();
  const mayRetry = method === "GET";
  const controller = new AbortController();
  const externalSignal = init.signal;
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", () => controller.abort(), {
        once: true,
      });
    }
  }
  const timeoutId =
    typeof window !== "undefined"
      ? window.setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS)
      : (setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS) as unknown as number);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "omit",
      signal: controller.signal,
      headers: {
        accept: "application/json",
        ...(init.body ? { "content-type": "application/json" } : {}),
        ...init.headers,
      },
    });

    if (!response.ok) {
      if (response.status >= 500 && mayRetry && retryCount < 1) {
        await sleep(80 + Math.random() * 120);
        return apiRequest<T>(path, init, retryCount + 1);
      }
      throw new ApiClientError(
        await parseError(response),
        response.status,
        response.status >= 500 && !mayRetry
          ? "outcome_unknown"
          : "definitive_failure",
      );
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error;
    }
    const aborted =
      (error instanceof DOMException && error.name === "AbortError") ||
      controller.signal.aborted;
    if (aborted) {
      throw new ApiClientError(
        `Request timed out after ${Math.round(DEFAULT_TIMEOUT_MS / 1000)}s. The backend may be waiting on an external provider (e.g. Futu OpenD).`,
        undefined,
        mayRetry ? "definitive_failure" : "outcome_unknown",
      );
    }
    if (mayRetry && retryCount < 1) {
      await sleep(80 + Math.random() * 120);
      return apiRequest<T>(path, init, retryCount + 1);
    }
    throw new ApiClientError(
      error instanceof Error ? error.message : "API unavailable",
      undefined,
      mayRetry ? "definitive_failure" : "outcome_unknown",
    );
  } finally {
    clearTimeout(timeoutId);
  }
}

/** One observable GET attempt for authorities where retry would blur unavailable vs pending. */
export function apiRequestOnce<T>(path: string, init: RequestInit = {}) {
  return apiRequest<T>(path, init, 1);
}

export function apiPost<T>(path: string, body: unknown) {
  return apiRequest<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function splitSymbols(value: string) {
  return value
    .split(",")
    .map((symbol) => symbol.trim().toUpperCase())
    .filter(Boolean);
}
