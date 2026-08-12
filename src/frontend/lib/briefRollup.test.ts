import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildBriefRollupListPath,
  buildBriefRollupPath,
  buildBriefRollupSidebarGroups,
  getBriefRollup,
  listBriefRollups,
  normalizeBriefRollupEnvelope,
  type BriefRollupEnvelope,
  type BriefRollupPayload,
} from "./briefRollup";

function jsonResponse(payload: unknown, status = 200, statusText = "OK") {
  return new Response(JSON.stringify(payload), {
    status,
    statusText,
    headers: { "content-type": "application/json" },
  });
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const weeklyPayload: BriefRollupPayload = {
  schema_version: "brief_rollup_v1",
  kind: "weekly",
  period_key: "2026-W33",
  locale: "zh",
  title: "第 33 周 AI 周报",
  date_range: { start: "2026-08-10", end: "2026-08-16" },
  main_storyline: "本周模拟盘围绕半导体与防御板块再平衡。",
  stats: {
    daily_count: 5,
    event_count: 17,
    equity_start: 100_000,
    equity_end: 101_234.5,
    period_change_pct: 1.23,
  },
  topics: [
    {
      index: 1,
      title: "半导体领涨",
      synthesis: "SOXX 相对 IGV 偏强。",
      source_items: [
        {
          id: "news-1",
          title: "Chip demand rises",
          url: "https://example.com/chips",
          source: "example",
          published_at: "2026-08-12T01:00:00Z",
          issue_date: "2026-08-12",
        },
      ],
    },
  ],
  account_summary: { base_currency: "USD" },
  provenance: {
    model: "xai/grok-4",
    critic_model: "xai/grok-4-critic",
    generated_at: "2026-08-16T09:00:00Z",
    source_issue_public_ids: ["brf_20260810_aaa"],
    facts_digest: "sha256:deadbeef",
  },
  warnings: [],
};

const weeklyEnvelope: BriefRollupEnvelope = {
  issue: {
    public_id: "brw_20260810_x1y2z3",
    kind: "weekly",
    period_key: "2026-W33",
    period_start: "2026-08-10",
    period_end: "2026-08-16",
    locale: "zh",
    status: "published",
  },
  snapshot: {
    snapshot_id: "snap_1",
    version: 1,
    payload: weeklyPayload as unknown as Record<string, unknown>,
  },
  warnings: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("brief rollup paths", () => {
  it("builds the rollup list path with kind, locale, and limit", () => {
    expect(buildBriefRollupListPath("weekly", "zh", 30)).toBe(
      "/api/brief/rollups?kind=weekly&locale=zh&limit=30",
    );
    expect(buildBriefRollupListPath("monthly", "en")).toBe(
      "/api/brief/rollups?kind=monthly&locale=en&limit=30",
    );
    expect(buildBriefRollupListPath("weekly", "")).toContain("locale=zh");
  });

  it("builds the rollup detail path from an encoded public id", () => {
    expect(buildBriefRollupPath("brw_20260810_x1y2z3")).toBe(
      "/api/brief/rollups/brw_20260810_x1y2z3",
    );
    const publicId = "brw 2026/08/10?x=1";
    expect(buildBriefRollupPath(publicId)).toBe(
      `/api/brief/rollups/${encodeURIComponent(publicId)}`,
    );
  });
});

describe("listBriefRollups", () => {
  it("requests the rollups endpoint and returns the typed list", async () => {
    const fetchMock = stubFetch(
      jsonResponse({
        kind: "weekly",
        locale: "zh",
        total: 1,
        items: [
          {
            public_id: "brw_20260810_x1y2z3",
            kind: "weekly",
            period_key: "2026-W33",
            period_start: "2026-08-10",
            period_end: "2026-08-16",
            locale: "zh",
            status: "published",
            title: "第 33 周 AI 周报",
            snippet: "本周主线：半导体走强。",
          },
        ],
      }),
    );

    const response = await listBriefRollups("weekly", "zh", 30);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/brief/rollups?kind=weekly&locale=zh&limit=30",
    );
    expect(response.total).toBe(1);
    expect(response.items[0]?.period_key).toBe("2026-W33");
    expect(response.apiError).toBeUndefined();
  });

  it("returns an empty fallback with the backend detail on failure", async () => {
    stubFetch(
      jsonResponse(
        { detail: { code: "brief_rollup_unavailable", message: "Rollup store offline." } },
        503,
        "Service Unavailable",
      ),
    );

    const response = await listBriefRollups("monthly", "zh", 30);

    expect(response.items).toEqual([]);
    expect(response.total).toBe(0);
    expect(response.kind).toBe("monthly");
    expect(response.apiError).toContain("[brief_rollup_unavailable]");
  });
});

describe("getBriefRollup", () => {
  it("requests the rollup detail endpoint and returns the envelope", async () => {
    const fetchMock = stubFetch(jsonResponse(weeklyEnvelope));

    const envelope = await getBriefRollup("brw_20260810_x1y2z3");

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/brief/rollups/brw_20260810_x1y2z3",
    );
    expect(envelope.issue.period_key).toBe("2026-W33");
    expect(envelope.snapshot.version).toBe(1);
  });

  it("returns an unavailable fallback with detail on 404", async () => {
    stubFetch(
      jsonResponse(
        { detail: { code: "brief_rollup_not_found", message: "Rollup was not found." } },
        404,
        "Not Found",
      ),
    );

    const envelope = await getBriefRollup("brw_20260810_missing");

    expect(envelope.issue.status).toBe("unavailable");
    expect(envelope.issue.public_id).toBe("brw_20260810_missing");
    expect(envelope.snapshot.version).toBe(0);
    expect(envelope.warnings).toContain("Brief rollup is unavailable.");
    expect(envelope.apiError).toContain("[brief_rollup_not_found]");
  });

  it("derives the fallback kind from the public id prefix", async () => {
    stubFetch(jsonResponse({ detail: "offline" }, 503, "Service Unavailable"));

    const monthly = await getBriefRollup("brm_202608_d4e5f6");
    expect(monthly.issue.kind).toBe("monthly");
    const weekly = await getBriefRollup("brw_20260810_x1y2z3");
    expect(weekly.issue.kind).toBe("weekly");
  });
});

describe("normalizeBriefRollupEnvelope", () => {
  it("parses a valid brief_rollup_v1 payload", () => {
    const view = normalizeBriefRollupEnvelope(weeklyEnvelope);

    expect(view.title).toBe("第 33 周 AI 周报");
    expect(view.kind).toBe("weekly");
    expect(view.periodKey).toBe("2026-W33");
    expect(view.payload).not.toBeNull();
    expect(view.payload?.stats.daily_count).toBe(5);
    expect(view.payload?.topics[0]?.source_items[0]?.url).toBe("https://example.com/chips");
    expect(view.payload?.provenance.source_issue_public_ids).toEqual(["brf_20260810_aaa"]);
    expect(view.warnings).toEqual([]);
  });

  it("refuses an invalid payload instead of fabricating a document", () => {
    const view = normalizeBriefRollupEnvelope({
      ...weeklyEnvelope,
      snapshot: { snapshot_id: "snap_bad", version: 1, payload: { title: "broken" } },
    });

    expect(view.payload).toBeNull();
    expect(view.title).toBe("broken");
    expect(view.warnings).toContain(
      "Archived rollup snapshot does not contain a valid rollup payload.",
    );
  });

  it("keeps unavailable fallbacks free of payload and extra warnings", () => {
    const view = normalizeBriefRollupEnvelope({
      issue: {
        public_id: "brw_missing",
        kind: "weekly",
        period_key: "",
        period_start: "",
        period_end: "",
        locale: "",
        status: "unavailable",
      },
      snapshot: { snapshot_id: "", version: 0, payload: {} },
      warnings: ["Brief rollup is unavailable."],
      apiError: "[brief_rollup_not_found] Rollup was not found.",
    });

    expect(view.payload).toBeNull();
    expect(view.title).toBe("brw_missing");
    expect(view.warnings).toEqual(["Brief rollup is unavailable."]);
    expect(view.apiError).toContain("brief_rollup_not_found");
  });
});

describe("buildBriefRollupSidebarGroups", () => {
  it("groups weekly rollups by the month of period_start, newest first", () => {
    const groups = buildBriefRollupSidebarGroups(
      [
        {
          public_id: "brw_20260720_j4k5l6",
          kind: "weekly",
          period_key: "2026-W30",
          period_start: "2026-07-20",
          period_end: "2026-07-26",
          locale: "zh",
          status: "published",
          title: "W30",
          snippet: "",
        },
        {
          public_id: "brw_20260810_x1y2z3",
          kind: "weekly",
          period_key: "2026-W33",
          period_start: "2026-08-10",
          period_end: "2026-08-16",
          locale: "zh",
          status: "published",
          title: "W33",
          snippet: "",
        },
        {
          public_id: "brw_20260803_a1b2c3",
          kind: "weekly",
          period_key: "2026-W32",
          period_start: "2026-08-03",
          period_end: "2026-08-09",
          locale: "zh",
          status: "published",
          title: "W32",
          snippet: "",
        },
      ],
      "weekly",
    );

    expect(groups.map((group) => group.key)).toEqual(["2026-08", "2026-07"]);
    expect(groups[0]?.entries.map((entry) => entry.public_id)).toEqual([
      "brw_20260810_x1y2z3",
      "brw_20260803_a1b2c3",
    ]);
    expect(groups[0]?.entries[0]?.iso_week).toBe("2026-W33");
    expect(groups[0]?.entries[0]?.month).toBeNull();
  });

  it("groups monthly rollups by the year of period_start, newest first", () => {
    const groups = buildBriefRollupSidebarGroups(
      [
        {
          public_id: "brm_202607_g7h8i9",
          kind: "monthly",
          period_key: "2026-07",
          period_start: "2026-07-01",
          period_end: "2026-07-31",
          locale: "zh",
          status: "published",
          title: "2026-07",
          snippet: "",
        },
        {
          public_id: "brm_202511_z0",
          kind: "monthly",
          period_key: "2025-11",
          period_start: "2025-11-01",
          period_end: "2025-11-30",
          locale: "zh",
          status: "published",
          title: "2025-11",
          snippet: "",
        },
        {
          public_id: "brm_202608_d4e5f6",
          kind: "monthly",
          period_key: "2026-08",
          period_start: "2026-08-01",
          period_end: "2026-08-31",
          locale: "zh",
          status: "published",
          title: "2026-08",
          snippet: "",
        },
      ],
      "monthly",
    );

    expect(groups.map((group) => group.key)).toEqual(["2026", "2025"]);
    expect(groups[0]?.entries.map((entry) => entry.public_id)).toEqual([
      "brm_202608_d4e5f6",
      "brm_202607_g7h8i9",
    ]);
    expect(groups[0]?.entries[0]?.month).toBe("2026-08");
    expect(groups[0]?.entries[0]?.iso_week).toBeNull();
  });
});
