import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

function readPage(name: "tasks" | "results") {
  return readFileSync(path.join(process.cwd(), `app/hermes/${name}/page.tsx`), "utf8");
}

describe("Hermes secondary-page artifact truth states", () => {
  it("tasks prioritizes degraded and unavailable feed facts over a healthy empty state", () => {
    const source = readPage("tasks");

    expect(source).toContain("artifactFeedReadState");
    expect(source).toContain("feedHasIssue");
    expect(source).toContain("<ArtifactFeed");
    expect(source).toContain("data-hermes-tasks-feed-issue");
    expect(source).toContain("feedHasIssue ? null");
  });

  it("results delegates truth states to the unified catalog read model", () => {
    const source = readPage("results");

    expect(source).toContain("getHermesResults");
    expect(source).toContain("buildHermesResultsPageModel");
    expect(source).toContain("<UnifiedResultsIndex");
    expect(source).not.toContain("getHermesArtifacts");
  });
});
