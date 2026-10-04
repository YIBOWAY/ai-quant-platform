import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

function readPage(name: "results") {
  return readFileSync(path.join(process.cwd(), `app/hermes/${name}/page.tsx`), "utf8");
}

describe("Hermes secondary-page artifact truth states", () => {
  it("removes the obsolete tasks page instead of presenting a second work queue", () => {
    expect(existsSync(path.join(process.cwd(), "app/hermes/tasks/page.tsx"))).toBe(false);
  });

  it("results delegates truth states to the unified catalog read model", () => {
    const source = readPage("results");

    expect(source).toContain("getHermesResults");
    expect(source).toContain("buildHermesResultsPageModel");
    expect(source).toContain("<UnifiedResultsIndex");
    expect(source).not.toContain("getHermesArtifacts");
  });

  it("moves the session index into the chat rail while keeping detail deep links", () => {
    const source = readFileSync(
      path.join(process.cwd(), "components/hermes/desk/HermesDeskChatRail.tsx"),
      "utf8",
    );
    expect(existsSync(path.join(process.cwd(), "app/hermes/sessions/page.tsx"))).toBe(false);
    expect(source).toContain("data-hermes-recent-sessions");
    expect(source).toContain("/hermes?hermes_session_id=${encodeURIComponent(session.id)}");
    expect(source).not.toContain("Safely closed");
    expect(source).not.toContain("安全关闭");
  });
});
