import { afterEach, describe, expect, it, vi } from "vitest";

import { getAsiaRadarOverview } from "./asiaRadar";

describe("Asia Radar API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("always requests the dedicated endpoint with provider=futu", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          schema_version: "1.0",
          provider: "futu",
          as_of: "2026-02-13",
          fetched_at: "2026-02-13T09:30:00+00:00",
          methodology: {},
          markets: [],
          k_shape: { winners: [], laggards: [], series: [] },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getAsiaRadarOverview();

    expect(result.provider).toBe("futu");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/asia-radar\/overview\?provider=futu$/),
      expect.objectContaining({ cache: "no-store" }),
    );
  });
});

