import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const briefPagePath = path.join(process.cwd(), "app/brief/page.tsx");
const positionMapPagePath = path.join(
  process.cwd(),
  "app/position-map/page.tsx",
);
const positionMapWorkspacePath = path.join(
  process.cwd(),
  "components/position-map/PositionMapWorkspace.tsx",
);

function readSource(sourcePath: string) {
  return readFileSync(sourcePath, "utf8");
}

describe("Brief and Position Map provider-free safety authority", () => {
  it("uses cached settings and never reaches the provider-coupled health route", () => {
    for (const source of [
      readSource(briefPagePath),
      readSource(positionMapPagePath),
    ]) {
      expect(source).toContain("getCachedSettings()");
      expect(source).not.toContain("getCachedHealth");
      expect(source).not.toContain("/api/health");
      expect(source).toContain(
        "settings.apiError || !settings.safety ? null : settings.safety",
      );
    }
  });

  it("renders missing safety facts as unavailable instead of safe defaults", () => {
    const page = readSource(positionMapPagePath);
    const workspace = readSource(positionMapWorkspacePath);

    expect(page).toContain(
      "paperTrading: settingsSafety?.paper_trading ?? null",
    );
    expect(page).toContain(
      "liveTrading: settingsSafety?.live_trading_enabled ?? null",
    );
    expect(page).not.toContain("paper_trading ?? true");
    expect(page).not.toContain("live_trading_enabled ?? false");
    expect(workspace).toContain("formatSafetyValue");
    expect(workspace).toContain("text.safetyUnavailable");
    expect(workspace).toContain("text.safetyNotPaperOnly");
  });
});
