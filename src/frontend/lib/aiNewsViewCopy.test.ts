import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  path.join(process.cwd(), "components/forms/AiNewsView.tsx"),
  "utf8",
);

describe("AI news header copy", () => {
  it("localizes the beta pill value instead of hardcoding ON", () => {
    expect(source).toContain('betaOn: "ON"');
    expect(source).toContain('betaOn: "开"');
    expect(source).toContain("? text.betaOn");
    expect(source).not.toContain('? "ON"');
  });

  it("localizes the daily Flashes section heading", () => {
    expect(source).toContain('flashes: "Flashes"');
    expect(source).toContain('flashes: "快讯"');
    expect(source).toContain("{text.flashes}");
    expect(source).not.toContain(">Flashes</h3>");
  });
});
