import { describe, expect, it } from "vitest";
import { buildAsiaRadarNote, formatPercentPoints } from "./briefAsiaRadarNote";
import type { AsiaRadarSummary } from "./asiaRadar";

function summary(overrides: Partial<AsiaRadarSummary> = {}): AsiaRadarSummary {
  return {
    schema_version: "1.1",
    provider: "futu",
    as_of: "2026-08-10",
    timezone: "America/New_York",
    fetched_at: "2026-08-10T20:00:00Z",
    provenance: "futu_cache",
    status: "available",
    market_count: 12,
    winner_symbols: ["EWY", "EWT", "THD"],
    laggard_symbols: ["EIDO", "INDA", "EPHE"],
    spread_pct: 59.3739,
    top_ytd_symbol: "EWY",
    top_ytd_pct: 59.5774,
    bottom_ytd_symbol: "EIDO",
    bottom_ytd_pct: -30.9421,
    markets: [],
    ...overrides,
  };
}

describe("formatPercentPoints", () => {
  it("formats already-percent values without multiplying by 100", () => {
    expect(formatPercentPoints(59.3739)).toBe("59.4%");
    expect(formatPercentPoints(0.5, 2)).toBe("0.50%");
  });
});

describe("buildAsiaRadarNote", () => {
  it("renders zh note with percent-point spread (not 5937%)", () => {
    const note = buildAsiaRadarNote({ summary: summary() }, "zh");
    expect(note).toContain("EWY/EWT/THD");
    expect(note).toContain("EIDO/INDA/EPHE");
    expect(note).toContain("59.4%");
    expect(note).not.toContain("5937");
  });

  it("renders en note with percent-point spread", () => {
    const note = buildAsiaRadarNote({ summary: summary() }, "en");
    expect(note).toContain("59.4%");
    expect(note).not.toMatch(/5937/);
  });

  it("falls back when summary unavailable", () => {
    expect(buildAsiaRadarNote({ summary: summary({ status: "unavailable" }) }, "zh")).toContain(
      "暂不可用",
    );
  });
});
