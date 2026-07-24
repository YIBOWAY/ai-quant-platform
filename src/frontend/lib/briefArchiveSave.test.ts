import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiPost } from "./apiClient";
import type { BriefArchivePayload, BriefSourceWatermark } from "./briefArchive";

vi.mock("./apiClient", () => ({ apiPost: vi.fn() }));

const mockedApiPost = vi.mocked(apiPost);

const payload: BriefArchivePayload = {
  schema_version: "brief_snapshot_v1",
  title: "每日晨报",
  issue_date: "2026-07-14",
  locale: "zh",
  generated_at: "2026-07-14T08:30:00Z",
  lede: "平台当日事实快照。",
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
  market_note: "行情暂不可用。",
  ai_news: [],
  hermes_log: [],
  warnings: ["market unavailable"],
};

const sourceWatermark: BriefSourceWatermark = {
  captured_at: "2026-07-14T08:30:00Z",
  sources: [
    {
      name: "market",
      status: "unavailable",
      as_of: null,
      detail: "market unavailable",
    },
  ],
};

describe("createBriefArchive", () => {
  beforeEach(() => {
    mockedApiPost.mockReset();
  });

  it("posts the complete bound snapshot and returns its durable public id", async () => {
    mockedApiPost.mockResolvedValue({
      issue: {
        issue_id: "issue-1",
        public_id: "brf_20260714_saved",
        issue_date: "2026-07-14",
        locale: "zh",
        status: "published",
      },
      snapshot: {
        snapshot_id: "snapshot-1",
        version: 1,
        payload,
        source_watermark: sourceWatermark,
      },
      warnings: [],
    });
    const { createBriefArchive } = await import("./briefArchiveSave");

    const result = await createBriefArchive(payload, sourceWatermark);

    expect(mockedApiPost).toHaveBeenCalledWith("/api/brief/issues/generate", {
      issue_date: "2026-07-14",
      locale: "zh",
      payload,
      source_watermark: sourceWatermark,
    });
    expect(result.issue.public_id).toBe("brf_20260714_saved");
    expect(result.snapshot.payload).toEqual(payload);
  });
});
