import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const safetyStripPath = path.join(process.cwd(), "components/SafetyStrip.tsx");
const serverApiPath = path.join(process.cwd(), "lib/serverApi.ts");

describe("SafetyStrip provider-free SSR authority", () => {
  it("uses settings safety and fails closed when that projection is unavailable", () => {
    const source = readFileSync(safetyStripPath, "utf8");

    expect(source).toContain("getCachedSettings()");
    expect(source).toContain("getCachedEffectivePaperSafety()");
    expect(source).not.toContain("getCachedHealth");
    expect(source).not.toContain("/api/health");
    expect(source).toContain(
      'status: settings.apiError || !settings.safety ? "unavailable" : "available"',
    );
    expect(source).toContain("settings.apiError ? undefined : settings.safety");
    expect(source).toContain("health.status");
    expect(source).toContain("paperSafety.effective");
    expect(source).toContain("paperSafety.canonical_account_frozen");
    expect(source).toContain("paperSafety.current_paper_authority_epoch");
  });

  it("caches both provider-free safety getters on the server", () => {
    const source = readFileSync(serverApiPath, "utf8");

    expect(source).toContain("getEffectivePaperSafety");
    expect(source).toContain("getCachedSettings = cache(getSettings)");
    expect(source).toContain(
      "getCachedEffectivePaperSafety = cache(getEffectivePaperSafety)",
    );
  });
});
