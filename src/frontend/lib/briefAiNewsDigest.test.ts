import { describe, expect, it } from "vitest";
import {
  buildBriefAiNewsDigest,
  mapDigestToAiNewsSourceEntry,
  mapDigestToBriefAiNews,
} from "./briefAiNewsDigest";

const sampleItem = {
  id: "n1",
  title: "Model ships",
  url: "https://example.com/n1",
  source: "wire",
  published_at: "2026-07-14T08:00:00+08:00",
  summary: "A release note.",
  category: "models",
  score: 0.91,
};

describe("mapDigestToBriefAiNews", () => {
  it("maps valid items and does not hardcode aihot as the only provider", () => {
    const items = mapDigestToBriefAiNews({
      provider: "longbridge",
      served_from: "failover",
      items: [sampleItem],
    });

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      id: "n1",
      title: "Model ships",
      url: "https://example.com/n1",
      source: "wire",
      summary: "A release note.",
      category: "models",
      score: 0.91,
    });
  });

  it("returns empty ai_news on apiError without throwing", () => {
    expect(
      mapDigestToBriefAiNews({
        apiError: "upstream timeout",
        provider: "aihot",
        items: [sampleItem],
      }),
    ).toEqual([]);
  });

  it("returns empty ai_news when items are empty", () => {
    expect(
      mapDigestToBriefAiNews({
        provider: "aihot",
        items: [],
      }),
    ).toEqual([]);
  });
});

describe("mapDigestToAiNewsSourceEntry", () => {
  it("includes provider, served_from, and short warnings join", () => {
    const entry = mapDigestToAiNewsSourceEntry({
      provider: "longbridge",
      served_from: "cache",
      fetched_at: "2026-07-14T08:05:00+08:00",
      warnings: ["stale cache", "retry once", "ignored third"],
      items: [sampleItem],
    });

    expect(entry).toMatchObject({
      name: "ai_news",
      status: "stale",
      provider: "longbridge",
      served_from: "cache",
    });
    expect(entry.detail).toBe("longbridge/cache; stale cache; retry once");
    expect(entry.as_of).toBeTruthy();
  });

  it("prefers apiError in detail and marks unavailable", () => {
    const entry = mapDigestToAiNewsSourceEntry({
      apiError: "news facade down",
      provider: "aihot",
      served_from: "primary",
      warnings: ["stale"],
      items: [],
    });

    expect(entry.status).toBe("unavailable");
    expect(entry.detail).toBe("news facade down");
    expect(entry.provider).toBe("aihot");
    expect(entry.served_from).toBe("primary");
  });
});

describe("buildBriefAiNewsDigest", () => {
  it("pairs archive rows with auto-facade watermark metadata", () => {
    const digest = buildBriefAiNewsDigest({
      provider: "aihot",
      served_from: "primary",
      items: [sampleItem],
    });

    expect(digest.items).toHaveLength(1);
    expect(digest.source.provider).toBe("aihot");
    expect(digest.source.served_from).toBe("primary");
    expect(digest.source.detail).toBe("aihot/primary");
  });
});
