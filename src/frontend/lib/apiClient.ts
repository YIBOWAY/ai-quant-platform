export const API_BASE_URL =
  process.env.NEXT_PUBLIC_QUANT_API_BASE_URL ?? "http://127.0.0.1:8765";

const DEFAULT_TIMEOUT_MS = 180_000;

export class ApiClientError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function parseError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
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
      if (response.status >= 500 && retryCount < 1) {
        await sleep(80 + Math.random() * 120);
        return apiRequest<T>(path, init, retryCount + 1);
      }
      throw new ApiClientError(await parseError(response), response.status);
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
      );
    }
    if (retryCount < 1) {
      await sleep(80 + Math.random() * 120);
      return apiRequest<T>(path, init, retryCount + 1);
    }
    throw new ApiClientError(error instanceof Error ? error.message : "API unavailable");
  } finally {
    clearTimeout(timeoutId);
  }
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
