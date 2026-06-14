import { describe, expect, it } from "vitest";

import { normalizeEquity } from "./equity";

describe("normalizeEquity", () => {
  it("joins strategy and benchmark rows by timestamp", () => {
    const rows = normalizeEquity(
      [
        { timestamp: "2024-01-02T00:00:00Z", equity: 100 },
        { timestamp: "2024-01-03T00:00:00Z", equity: 110 },
      ],
      [
        { timestamp: "2024-01-03T00:00:00Z", equity: 210 },
        { timestamp: "2024-01-04T00:00:00Z", equity: 220 },
      ],
    );

    expect(rows).toEqual([
      { timestamp: "2024-01-02", strategy: 1, benchmark: null },
      { timestamp: "2024-01-03", strategy: 1.1, benchmark: 1 },
    ]);
  });

  it("returns no rows when strategy equity has no positive anchor", () => {
    expect(normalizeEquity([{ timestamp: "2024-01-02", equity: 0 }])).toEqual([]);
  });
});
