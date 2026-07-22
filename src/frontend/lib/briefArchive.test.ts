import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

const archivePagePath = path.join(process.cwd(), "app/brief/[publicId]/page.tsx");

describe("brief archive API contract", () => {
  it("builds the brief issue path from the public id", async () => {
    const { buildBriefIssuePath } = await import("./briefArchive");

    expect(buildBriefIssuePath("brf_20260708_7k3f2")).toBe(
      "/api/brief/issues/brf_20260708_7k3f2",
    );
  });

  it("encodes special characters in public ids", async () => {
    const { buildBriefIssuePath } = await import("./briefArchive");
    const publicId = "brf 2026/07/08?x=1&region=us";

    expect(buildBriefIssuePath(publicId)).toBe(`/api/brief/issues/${encodeURIComponent(publicId)}`);
  });

  it("builds the latest brief issue path from locale", async () => {
    const { buildLatestBriefIssuePath } = await import("./briefArchive");

    expect(buildLatestBriefIssuePath("zh")).toBe("/api/brief/issues/latest?locale=zh");
    expect(buildLatestBriefIssuePath("en")).toBe("/api/brief/issues/latest?locale=en");
    expect(buildLatestBriefIssuePath("")).toBe("/api/brief/issues/latest?locale=zh");
  });

  it("builds the issue list path with explicit pagination", async () => {
    const { buildBriefIssueListPath } = await import("./briefArchive");

    expect(buildBriefIssueListPath("zh", 30, 0)).toBe(
      "/api/brief/issues?locale=zh&limit=30&offset=0",
    );
  });

  it("normalizes the issue envelope into archive display data", async () => {
    const { normalizeBriefIssueEnvelope } = await import("./briefArchive");

    expect(
      normalizeBriefIssueEnvelope({
        issue: {
          issue_id: "iss_1",
          public_id: "brf_20260708_7k3f2",
          issue_date: "2026-07-08",
          locale: "zh",
          status: "published",
        },
        snapshot: {
          snapshot_id: "snap_1",
          version: 3,
          payload: { title: "Hermes Morning Brief" },
          source_watermark: { paper_account: "2026-07-08T08:00:00Z" },
        },
        warnings: ["sample warning"],
      }),
    ).toMatchObject({
      title: "Hermes Morning Brief",
      issueDate: "2026-07-08",
      version: 3,
      sourceWatermarkEntries: [["paper_account", "2026-07-08T08:00:00Z"]],
      warnings: [
        "sample warning",
        "Archived snapshot does not contain a valid factual payload.",
      ],
    });
  });

  it("preserves every factual section from a v1 archived snapshot", async () => {
    const { normalizeBriefIssueEnvelope } = await import("./briefArchive");
    const payload = {
      schema_version: "brief_snapshot_v1" as const,
      title: "每日晨报",
      issue_date: "2026-07-14",
      locale: "zh" as const,
      generated_at: "2026-07-14T08:30:00+08:00",
      lede: "平台当日事实快照。",
      account: {
        account_id: "default",
        base_currency: "USD",
        equity: 101_234.5,
        cash: 61_234.5,
        pnl_abs: 1_234.5,
        pnl_pct: 0.01234,
        invested_pct: 0.4,
        price_source: { kind: "futu", as_of: "2026-07-14T08:29:00+08:00" },
        positions: [
          {
            symbol: "AAPL",
            quantity: 10,
            avg_cost: 200,
            last_price: 210,
            market_value: 2_100,
            weight: 0.0207,
            unrealized_pnl: 100,
            price_kind: "realtime",
            price_as_of: "2026-07-14T08:29:00+08:00",
          },
        ],
      },
      paper_equity: [
        {
          timestamp: "2026-07-14T08:29:00+08:00",
          equity: 101_234.5,
          cash: 61_234.5,
          market_value: 40_000,
          source: "current_quote",
        },
      ],
      markets: [
        {
          symbol: "SPY",
          last: 620.2,
          change_pct: 0.004,
          source: "futu",
          as_of: "2026-07-14T00:00:00Z",
        },
      ],
      market_note: "SPY 小幅上涨。",
      ai_news: [
        {
          id: "news-1",
          title: "A new model was released",
          url: "https://example.com/news-1",
          source: "example",
          published_at: "2026-07-14T01:00:00Z",
          summary: "A factual summary.",
          category: "models",
          score: 9.1,
        },
      ],
      hermes_log: [
        {
          timestamp: "2026-07-14T02:00:00Z",
          status: "ok" as const,
          text: "Hermes completed backtest",
          href: "/hermes/results/run-1",
          summary: "run-1",
        },
      ],
      warnings: ["AI HOT response came from local cache."],
    };

    const archive = normalizeBriefIssueEnvelope({
      issue: {
        issue_id: "iss_1",
        public_id: "brf_20260714_real",
        issue_date: "2026-07-14",
        locale: "zh",
        status: "published",
      },
      snapshot: {
        snapshot_id: "snap_1",
        version: 1,
        payload,
        source_watermark: {
          captured_at: "2026-07-14T08:30:00+08:00",
          sources: [
            {
              name: "ai_news",
              status: "stale",
              as_of: "2026-07-14T08:00:00+08:00",
              detail: "local cache",
            },
          ],
        },
      },
      warnings: [],
    });

    expect(archive.payload).toEqual(payload);
    expect(archive.payload?.account.positions[0]?.symbol).toBe("AAPL");
    expect(archive.payload?.markets[0]?.last).toBe(620.2);
    expect(archive.payload?.ai_news[0]?.title).toBe("A new model was released");
    expect(archive.payload?.hermes_log[0]?.summary).toBe("run-1");
    expect(archive.sourceWatermark?.sources[0]?.status).toBe("stale");
  });

  it("refuses to present the legacy empty-section placeholder as a real archive", async () => {
    const { normalizeBriefIssueEnvelope } = await import("./briefArchive");

    const archive = normalizeBriefIssueEnvelope({
      issue: {
        issue_id: "iss_legacy",
        public_id: "brf_20260708_legacy",
        issue_date: "2026-07-08",
        locale: "zh",
        status: "published",
      },
      snapshot: {
        snapshot_id: "snap_legacy",
        version: 1,
        payload: {
          title: "每日晨报",
          issue_date: "2026-07-08",
          sections: { market: [], ai_news: [], paper_equity: [], hermes_log: [] },
        },
        source_watermark: {},
      },
      warnings: [],
    });

    expect(archive.payload).toBeNull();
    expect(archive.warnings).toContain("Archived snapshot does not contain a valid factual payload.");
  });

  it("builds a generate request whose identity is bound to the snapshot", async () => {
    const { buildBriefGenerateRequest } = await import("./briefArchive");
    const payload = {
      schema_version: "brief_snapshot_v1" as const,
      title: "Daily Morning Brief",
      issue_date: "2026-07-14",
      locale: "en" as const,
      generated_at: "2026-07-14T08:30:00Z",
      lede: "Daily facts.",
      account: {
        account_id: "default",
        base_currency: "USD",
        equity: 100,
        cash: 100,
        pnl_abs: 0,
        pnl_pct: 0,
        invested_pct: 0,
        price_source: { kind: "unavailable", as_of: null },
        positions: [],
      },
      paper_equity: [],
      markets: [],
      market_note: "Market data unavailable.",
      ai_news: [],
      hermes_log: [],
      warnings: ["market unavailable"],
    };
    const watermark = { captured_at: "2026-07-14T08:30:00Z", sources: [] };

    expect(buildBriefGenerateRequest(payload, watermark)).toEqual({
      issue_date: "2026-07-14",
      locale: "en",
      payload,
      source_watermark: watermark,
    });
  });
});

describe("getBriefIssue", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests the read-only archive endpoint through the existing API getter surface", async () => {
    const { buildBriefIssuePath } = await import("./briefArchive");
    const { getBriefIssue } = await import("./api");
    const publicId = "brf 2026/07/08";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          issue: {
            issue_id: "iss_1",
            public_id: publicId,
            issue_date: "2026-07-08",
            locale: "zh",
            status: "published",
          },
          snapshot: {
            snapshot_id: "snap_1",
            version: 1,
            payload: { title: "Archived Brief" },
            source_watermark: {},
          },
          warnings: [],
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getBriefIssue(publicId);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toContain(buildBriefIssuePath(publicId));
  });

  it("returns an unavailable archive fallback when the backend rejects the archive read", async () => {
    const { getBriefIssue } = await import("./api");
    const publicId = "brf_20260708_missing";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "brief_not_found",
            message: "Brief archive issue was not found.",
          },
        }),
        {
          status: 404,
          statusText: "Not Found",
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const envelope = await getBriefIssue(publicId);

    expect(envelope.issue.public_id).toBe(publicId);
    expect(envelope.issue.status).toBe("unavailable");
    expect(envelope.snapshot.version).toBe(0);
    expect(envelope.warnings).toContain("Brief archive issue is unavailable.");
    expect(envelope.apiError).toContain("[brief_not_found]");
  });
});

describe("getLatestBriefIssue", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests the latest archive endpoint with locale", async () => {
    const { buildLatestBriefIssuePath } = await import("./briefArchive");
    const { getLatestBriefIssue } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          issue: {
            issue_id: "iss_1",
            public_id: "brf_20260708_7k3f2",
            issue_date: "2026-07-08",
            locale: "zh",
            status: "published",
          },
          snapshot: {
            snapshot_id: "snap_1",
            version: 1,
            payload: { title: "Archived Brief" },
            source_watermark: {},
          },
          warnings: [],
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getLatestBriefIssue({ locale: "zh" });

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toContain(buildLatestBriefIssuePath("zh"));
  });

  it("returns unavailable fallback with empty public_id on 404", async () => {
    const { getLatestBriefIssue } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "brief_not_found",
            message: "No brief archive issue was found for the requested locale.",
          },
        }),
        {
          status: 404,
          statusText: "Not Found",
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const envelope = await getLatestBriefIssue({ locale: "zh" });

    expect(envelope.issue.public_id).toBe("");
    expect(envelope.issue.locale).toBe("zh");
    expect(envelope.issue.status).toBe("unavailable");
    expect(envelope.snapshot.version).toBe(0);
    expect(envelope.warnings).toContain("Brief archive issue is unavailable.");
    expect(envelope.apiError).toContain("[brief_not_found]");
  });

  it("returns unavailable fallback with empty public_id on 503", async () => {
    const { getLatestBriefIssue } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "brief_database_unavailable",
            message: "Brief archive database is unavailable.",
          },
        }),
        {
          status: 503,
          statusText: "Service Unavailable",
          headers: { "content-type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const envelope = await getLatestBriefIssue({ locale: "en" });

    expect(envelope.issue.public_id).toBe("");
    expect(envelope.issue.locale).toBe("en");
    expect(envelope.issue.status).toBe("unavailable");
    expect(envelope.warnings).toContain("Brief archive issue is unavailable.");
    expect(envelope.apiError).toContain("[brief_database_unavailable]");
  });
});

describe("/brief/[publicId] archive page contract", () => {
  it("uses a read-only archive getter and renders the archived envelope fields", () => {
    const source = readFileSync(archivePagePath, "utf8");

    expect(source).toContain("type Props = { params: Promise<{ publicId: string }> }");
    expect(source).toMatch(/getBriefIssue|buildBriefIssuePath/);
    expect(source).toContain("snapshot.payload.title");
    expect(source).toContain("issue.issue_date");
    expect(source).toContain("archive.payload.account");
    expect(source).toContain("archive.payload.markets");
    expect(source).toContain("archive.payload.ai_news");
    expect(source).toContain("archive.payload.hermes_log");
    expect(source).toContain("bg-paper-ink");
    expect(source).toContain("text-ink");
    expect(source).toContain("font-editorial-display");

    expect(source).not.toContain("apiRequest");
    expect(source).not.toContain("apiPost");
    expect(source).not.toContain("POST");
    expect(source).not.toContain("/brief/issues/generate");
    expect(source).not.toContain("fetch(");
  });
});
