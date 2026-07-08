import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const safetyStripPath = path.join(process.cwd(), "components/SafetyStrip.tsx");

describe("SafetyStrip responsive copy", () => {
  it("keeps compact mobile status visible without dropping the desktop safety contract", () => {
    const source = readFileSync(safetyStripPath, "utf8");

    expect(source).toContain("mobileStatus");
    expect(source).toContain("desktopStatus");
    expect(source).toContain("sm:hidden");
    expect(source).toContain("hidden sm:inline");
    expect(source).toContain("paperOnly");
    expect(source).toContain("liveDisabled");
    expect(source).toContain("killSwitchOn");
    expect(source).toContain("health.status");
  });
});
