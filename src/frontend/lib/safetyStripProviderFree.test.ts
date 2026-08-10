import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const safetyBadgePath = path.join(process.cwd(), "components/SafetyBadge.tsx");
const serverApiPath = path.join(process.cwd(), "lib/serverApi.ts");

describe("SafetyBadge provider-free SSR authority", () => {
  it("uses settings safety and fails closed when that projection is unavailable", () => {
    const source = readFileSync(safetyBadgePath, "utf8");

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
    expect(source).toContain("getCachedBriefMarketDataHistory = unstable_cache(");
    expect(source).toContain("getCachedBriefPaperAccountPerformance = unstable_cache(");
    expect(source).toContain("getCachedBriefPaperAccount = unstable_cache(");
    expect(source).toContain("getCachedBriefPaperAccountEquityCurve = unstable_cache(");
    expect(source).toContain("revalidate: 60");
    expect(source).toContain("revalidate: 5");
    expect(source).toContain("revalidate: 1");
    expect(source).toContain(
      "getCachedEffectivePaperSafety = cache(getEffectivePaperSafety)",
    );
  });
});
