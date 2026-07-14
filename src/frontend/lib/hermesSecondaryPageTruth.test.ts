import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

function readPage(name: "tasks" | "results") {
  return readFileSync(path.join(process.cwd(), `app/hermes/${name}/page.tsx`), "utf8");
}

describe("Hermes secondary-page artifact truth states", () => {
  it.each(["tasks", "results"] as const)(
    "%s prioritizes degraded and unavailable feed facts over a healthy empty state",
    (name) => {
      const source = readPage(name);

      expect(source).toContain("artifactFeedReadState");
      expect(source).toContain("feedHasIssue");
      expect(source).toContain("<ArtifactFeed");
      expect(source).toContain(`data-hermes-${name}-feed-issue`);
      expect(source).toContain("feedHasIssue ? null");
    },
  );
});
