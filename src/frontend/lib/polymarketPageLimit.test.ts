import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  path.join(process.cwd(), "app/polymarket/page.tsx"),
  "utf8",
);

describe("polymarket page limit param", () => {
  it("falls back instead of forwarding a NaN limit to the API", () => {
    // ?limit=abc must not reach getPredictionMarkets as NaN.
    expect(source).toContain("Number.parseInt(");
    expect(source).toMatch(/Number\.isFinite\(parsedLimit\)\s*\?\s*parsedLimit\s*:\s*6/);
    expect(source).not.toContain("getPredictionMarkets(provider, cacheMode, Number.parseInt");
  });
});
