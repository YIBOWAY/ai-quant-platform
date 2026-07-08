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
      warnings: ["sample warning"],
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

describe("/brief/[publicId] archive page contract", () => {
  it("uses a read-only archive getter and renders the archived envelope fields", () => {
    const source = readFileSync(archivePagePath, "utf8");

    expect(source).toContain("type Props = { params: Promise<{ publicId: string }> }");
    expect(source).toMatch(/getBriefIssue|buildBriefIssuePath/);
    expect(source).toContain("snapshot.payload.title");
    expect(source).toContain("issue.issue_date");
    expect(source).toContain("bg-paper-ink");
    expect(source).toContain("text-ink");
    expect(source).toContain("font-editorial-display");

    expect(source).not.toContain("apiRequest");
    expect(source).not.toContain("POST");
    expect(source).not.toContain("generate");
    expect(source).not.toContain("fetch(");
  });
});
