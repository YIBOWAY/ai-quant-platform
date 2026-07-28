import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const frontendRoot = process.cwd();

const hermesLinkFiles = [
  "components/hermes/approvals/CandidateApprovalWorkspace.tsx",
  "components/hermes/gates/WorkbenchGateSurfacesPanel.tsx",
  "components/hermes/results/UnifiedResultDetail.tsx",
  "components/hermes/results/UnifiedResultsIndex.tsx",
  "components/hermes/shell/HermesInternalNav.tsx",
  "components/hermes/today/RecentResults.tsx",
  "components/hermes/today/TodayAttention.tsx",
  "components/hermes/today/TodayGreeting.tsx",
  "components/hermes/today/TodayResults.tsx",
  "components/hermes/today/TodayRunning.tsx",
];

function nextLinkTags(relativePath: string): string[] {
  const source = readFileSync(path.join(frontendRoot, relativePath), "utf8");
  return source.match(/<Link\b[\s\S]*?>/g) ?? [];
}

describe("Hermes workbench navigation prefetch policy", () => {
  it("disables automatic prefetch on every Hermes-local Next Link", () => {
    for (const relativePath of hermesLinkFiles) {
      const tags = nextLinkTags(relativePath);
      expect(tags.length, relativePath).toBeGreaterThan(0);
      for (const tag of tags) {
        expect(tag, `${relativePath}: ${tag}`).toContain("prefetch={false}");
      }
    }
  });

  it("disables shared-shell prefetch only while a Hermes route is active", () => {
    for (const relativePath of ["components/Sidebar.tsx", "components/TopBar.tsx"]) {
      const source = readFileSync(path.join(frontendRoot, relativePath), "utf8");
      const tags = nextLinkTags(relativePath);
      expect(source).toContain(
        'activePath === "/hermes" || activePath.startsWith("/hermes/")',
      );
      expect(tags.length, relativePath).toBeGreaterThan(0);
      for (const tag of tags) {
        expect(tag, `${relativePath}: ${tag}`).toContain(
          "prefetch={disableNavigationPrefetch ? false : undefined}",
        );
      }
    }
  });

  it("serves provider-free settings from the GET-only browser fixture", () => {
    const source = readFileSync(
      path.join(frontendRoot, "tests/support/hermes-fixture-api.mjs"),
      "utf8",
    );
    expect(source).toContain('"/api/settings"');
    expect(source).toContain("safety: validated.health.safety");
  });
});
