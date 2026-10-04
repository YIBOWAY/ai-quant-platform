import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

function source(file: string) {
  return readFileSync(path.join(process.cwd(), file), "utf8");
}

describe("Data explorer zh copy", () => {
  it("uses unambiguous month-count preset labels", () => {
    const controls = source("components/forms/DataExplorerControls.tsx");

    expect(controls).toContain(
      'presets: { "1个月": 30, "3个月": 90, "6个月": 180, "1年": 365 }',
    );
    expect(controls).not.toContain('"1月": 30');
    expect(controls).not.toContain('"3月": 90');
    expect(controls).not.toContain('"6月": 180');
  });

  it("localizes the frequency tag instead of leaking raw English", () => {
    const view = source("components/watch/DataExplorerView.tsx");

    expect(view).toContain('freq: "周期"');
    expect(view).toContain("{text.freq}: {ohlcv.frequency}");
    expect(view).not.toContain("· freq: {ohlcv.frequency}");
  });
});
