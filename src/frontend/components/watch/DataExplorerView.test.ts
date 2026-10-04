import { describe, expect, it } from "vitest";
import { summarizeQuoteContext } from "./DataExplorerView";
import type { OhlcvRow } from "@/lib/api";

describe("quote context", () => {
  it("uses trading-session offsets and excludes the latest volume from its baseline", () => {
    const rows: OhlcvRow[] = Array.from({ length: 22 }, (_, i) => ({
      timestamp: `session-${i}`,
      open: 100 + i,
      high: 125,
      low: 95,
      close: 100 + i,
      volume: i === 21 ? 200 : 100,
    }));
    const summary = summarizeQuoteContext(rows);
    expect(summary.week).toBeCloseTo((121 / 116 - 1) * 100);
    expect(summary.month).toBeCloseTo(21);
    expect(summary.belowHigh).toBeCloseTo(-3.2);
    expect(summary.volumeRatio).toBe(2);
    expect(summarizeQuoteContext(rows.slice(0, 5)).week).toBeNull();
    expect(summarizeQuoteContext(rows.slice(0, 21)).month).toBeNull();
    expect(summarizeQuoteContext(rows.slice(0, 20)).volumeRatio).toBeNull();
    expect(Object.values(summarizeQuoteContext([]))).toEqual([null, null, null, null]);
  });
});
