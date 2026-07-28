import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const safetyStripPath = path.join(process.cwd(), "components/SafetyStrip.tsx");
const serverApiPath = path.join(process.cwd(), "lib/serverApi.ts");

describe("SafetyStrip provider-free SSR authority", () => {
  it("uses settings safety and fails closed when that projection is unavailable", () => {
    const source = readFileSync(safetyStripPath, "utf8");

    expect(source).toContain("getCachedSettings()");
    expect(source).not.toContain("getCachedHealth");
    expect(source).not.toContain("/api/health");
    expect(source).toContain(
      'status: settings.apiError || !settings.safety ? "unavailable" : "available"',
    );
    expect(source).toContain("settings.apiError ? undefined : settings.safety");
    expect(source).toContain("health.status");
  });

  it("caches the provider-free settings getter on the server", () => {
    const source = readFileSync(serverApiPath, "utf8");

    expect(source).toContain('import { getHealth, getSettings } from "@/lib/api"');
    expect(source).toContain("getCachedSettings = cache(getSettings)");
  });
});
