import { describe, expect, it } from "vitest";

import { isSampleSource, selectDisplayRun, shouldIncludeSampleRuns } from "./runSource";

describe("runSource helpers", () => {
  it("detects synthetic sample source labels", () => {
    expect(isSampleSource("sample (tiingo: missing token)")).toBe(true);
    expect(isSampleSource("futu")).toBe(false);
  });

  it("parses include_sample query params", () => {
    expect(shouldIncludeSampleRuns({ include_sample: "1" })).toBe(true);
    expect(shouldIncludeSampleRuns({ include_sample: ["true"] })).toBe(true);
    expect(shouldIncludeSampleRuns({ include_sample: "0" })).toBe(false);
  });

  it("selects the newest non-sample run unless sample runs are included", () => {
    const sample = { id: "sample", source: "sample" };
    const real = { id: "real", source: "tiingo" };

    expect(selectDisplayRun([sample, real])).toBe(real);
    expect(selectDisplayRun([sample, real], true)).toBe(sample);
  });
});
