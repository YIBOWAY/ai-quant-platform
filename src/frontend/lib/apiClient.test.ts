import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiPost, apiRequest, apiRequestOnce } from "./apiClient";

describe("apiClient errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("formats structured API detail objects as readable messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "replay_kill_switch_enabled",
              message: "Replay kill switch is enabled.",
            },
          }),
          {
            status: 409,
            headers: { "content-type": "application/json" },
          },
        ),
      ),
    );

    const expected: Partial<ApiClientError> = {
      status: 409,
      message: "[replay_kill_switch_enabled] Replay kill switch is enabled.",
    };

    await expect(apiPost("/api/paper/run", {})).rejects.toMatchObject(expected);
  });

  it.each([
    ["server error", () => Promise.resolve(new Response("error", { status: 503 }))],
    ["network disconnect", () => Promise.reject(new TypeError("network down"))],
    ["timeout", () => Promise.reject(new DOMException("aborted", "AbortError"))],
  ])("sends a non-idempotent POST once on %s and reports outcome unknown", async (_name, reply) => {
    const fetchMock = vi.fn().mockImplementation(reply);
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiPost("/api/assistant/remote/dispatch", {})).rejects.toMatchObject({
      outcome: "outcome_unknown",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("sends a definitive 4xx POST once", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("conflict", { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiPost("/api/assistant/remote/dispatch", {})).rejects.toMatchObject({
      outcome: "definitive_failure",
      status: 409,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps one bounded retry for GET", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("error", { status: 503 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/api/health", { method: "GET" })).resolves.toEqual({
      status: "ok",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps authority observation GETs to one physical fetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("error", { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequestOnce("/api/assistant/remote/book")).rejects.toMatchObject({
      status: 503,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("API_BASE_URL default", () => {
  const ENV_KEY = "NEXT_PUBLIC_QUANT_API_BASE_URL";
  let originalEnv: string | undefined;

  beforeEach(() => {
    originalEnv = process.env[ENV_KEY];
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    if (originalEnv === undefined) {
      delete process.env[ENV_KEY];
    } else {
      process.env[ENV_KEY] = originalEnv;
    }
    vi.resetModules();
  });

  it("keeps the absolute local backend address for server-side fetches", async () => {
    delete process.env[ENV_KEY];
    const serverModule = await import("./apiClient");
    expect(serverModule.API_BASE_URL).toBe("http://127.0.0.1:8765");
  });

  it("defaults browser fetches to the same-origin /api rewrite", async () => {
    delete process.env[ENV_KEY];
    vi.stubGlobal("window", {});
    const browserModule = await import("./apiClient");
    expect(browserModule.API_BASE_URL).toBe("");
  });

  it("keeps an explicit NEXT_PUBLIC_QUANT_API_BASE_URL untouched", async () => {
    process.env[ENV_KEY] = "http://127.0.0.1:3002";
    vi.stubGlobal("window", {});
    const previewModule = await import("./apiClient");
    expect(previewModule.API_BASE_URL).toBe("http://127.0.0.1:3002");
  });
});
