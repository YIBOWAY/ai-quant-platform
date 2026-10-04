import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const safetyBadgePath = path.join(process.cwd(), "components/SafetyBadge.tsx");

describe("SafetyBadge responsive copy", () => {
  it("keeps a compact visible badge while the full safety contract stays reachable", () => {
    const source = readFileSync(safetyBadgePath, "utf8");

    expect(source).toContain("mobileStatus");
    expect(source).toContain("desktopStatus");
    expect(source).toContain("badgeLabel");
    expect(source).toContain("<details");
    expect(source).toContain("paperOnly");
    expect(source).toContain("liveDisabled");
    expect(source).toContain("killSwitchOn");
    expect(source).toContain("paperObservationOn");
    expect(source).toContain("health.status");
    expect(source).toContain('const apiStatus = health.status === "available" ? text.available : text.unavailable');
    expect(source).toContain("{ label: text.api, value: apiStatus }");
    expect(source).not.toContain("${text.api} ${health.status}");
  });
});
