import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiPost } from "./apiClient";

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
});
