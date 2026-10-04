import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const source = (relative: string) =>
  readFileSync(path.join(root, relative), "utf8");

describe("retired research products are absent", () => {
  it("removes the D34 workbench, paper remote panel, gates and approvals route", () => {
    for (const relative of [
      "components/hermes/d34/D34ResearchWorkbench.tsx",
      "components/hermes/d34/index.ts",
      "components/forms/AssistantRemotePanel.tsx",
      "components/hermes/gates/WorkbenchGateSurfacesPanel.tsx",
      "components/hermes/approvals/WorkbenchCommandApprovalsPanel.tsx",
      "app/hermes/approvals/page.tsx",
    ]) {
      expect(existsSync(path.join(root, relative)), relative).toBe(false);
    }
    expect(source("app/hermes/page.tsx")).not.toContain("D34ResearchWorkbench");
    expect(source("app/paper-trading/page.tsx")).not.toContain("AssistantRemotePanel");
    expect(source("lib/hermes/routes.ts")).not.toContain("approvals");
  });

  it("keeps the replacement product chain explicit", () => {
    const hermes = source("components/hermes/desk/HermesDeskChatRail.tsx");
    const library = source("components/library/LibraryWorkbench.tsx");
    const libraryClient = source("lib/researchLibrary.ts");
    expect(hermes).toContain("Research and simulation updates stay in this conversation");
    expect(hermes).toContain("PlatformResearchResultCard");
    expect(library).toContain("hangLibraryCandidate");
    expect(libraryClient).toContain("expected_source_digest");
  });
});
