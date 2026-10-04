import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { localizePath } from "@/lib/locale";

const source = readFileSync(
  path.join(process.cwd(), "components/forms/ExperimentTabs.tsx"),
  "utf8",
);

describe("ExperimentTabs Send to Backtest link", () => {
  it("routes the backtest handoff through localizePath", () => {
    expect(source).toContain('from "@/lib/locale"');
    expect(source).toContain("localizePath");
    expect(source).toMatch(/localizePath\(\s*buildBacktestHref\(/);
    // The bare handoff path must not reach the Link directly.
    expect(source).not.toContain("const backtestHref = buildBacktestHref(");
  });

  it("localizePath prefixes the handoff href with the active locale", () => {
    const href = "/backtest?symbols=SPY%2CQQQ&start=2024-01-02";
    expect(localizePath(href, "zh")).toBe(`/zh${href}`);
    expect(localizePath(href, "en")).toBe(`/en${href}`);
  });
});
