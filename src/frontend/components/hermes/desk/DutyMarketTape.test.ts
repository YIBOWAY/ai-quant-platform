import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  acceptDutyHistory,
  asOfFromLastBar,
  DUTY_TAPE_SYMBOLS,
  rebaseClosesToZeroPercent,
  rejectedHistorySource,
  walkSeries,
} from "./DutyMarketTape";

const source = readFileSync(
  path.join(process.cwd(), "components/hermes/desk/DutyMarketTape.tsx"),
  "utf8",
);

describe("DutyMarketTape history contract", () => {
  it("baskets SPY QQQ SOXX and asks history with provider=futu", () => {
    expect(DUTY_TAPE_SYMBOLS).toEqual(["SPY", "QQQ", "SOXX"]);
    expect(source).toContain('getMarketDataHistory(');
    expect(source).toContain('"futu"');
    expect(source).toContain('freq = "1d"');
    expect(source).not.toContain("/api/ohlcv");
    expect(source).not.toContain("desk-preview");
    expect(source).not.toContain("PaperWatch");
    expect(source).not.toContain("preview-data");
  });

  it("rejects a source that starts with sample", () => {
    expect(rejectedHistorySource("sample")).toBe(true);
    expect(rejectedHistorySource("sample (ohlcv)")).toBe(true);
    expect(rejectedHistorySource("futu")).toBe(false);
    expect(
      acceptDutyHistory({
        source: "sample (ohlcv)",
        metadata: { provider: "sample" },
        rows: [{ timestamp: "2026-08-14T00:00:00+00:00", close: 100 }],
      }),
    ).toBe(false);
    expect(
      acceptDutyHistory({
        source: "futu",
        metadata: { provider: "futu" },
        rows: [{ timestamp: "2026-08-14T00:00:00+00:00", close: 100 }],
      }),
    ).toBe(true);
  });

  it("rebases closes so the first day is 0%", () => {
    const percents = rebaseClosesToZeroPercent([100, 110, 90]);
    expect(percents[0]).toBe(0);
    expect(percents[1]).toBeCloseTo(10, 10);
    expect(percents[2]).toBeCloseTo(-10, 10);
  });

  it("takes as-of from the last bar timestamp", () => {
    expect(
      asOfFromLastBar([
        { timestamp: "2026-06-01T00:00:00+00:00" },
        { timestamp: "2026-08-14T00:00:00+00:00" },
      ]),
    ).toBe("2026-08-14");
  });

  it("walks a series so the first revealed point is the first value", () => {
    const walked = walkSeries([0, 10, -10], 0);
    expect(walked.values[0]).toBe(0);
    expect(walked.headValue).toBe(0);
  });

  it("keeps a single-bar series finite throughout the reveal animation", () => {
    const walked = walkSeries([0], 0.75);
    expect(walked).toEqual({ values: [0], headIndex: 0, headValue: 0 });
  });
});
