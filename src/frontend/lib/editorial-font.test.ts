import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const layoutTsx = readFileSync(path.join(process.cwd(), "app/layout.tsx"), "utf8");

describe("editorial font setup", () => {
  it("imports the editorial serif fonts from next/font/google", () => {
    const googleFontImport = layoutTsx.match(/import\s+\{([^}]+)\}\s+from\s+['"]next\/font\/google['"];/);

    expect(googleFontImport?.[1]).toContain("Inter");
    expect(googleFontImport?.[1]).toContain("JetBrains_Mono");
    expect(googleFontImport?.[1]).toContain("Source_Serif_4");
    expect(googleFontImport?.[1]).toContain("Noto_Serif_SC");
  });

  it("configures the editorial serif font variables", () => {
    expect(layoutTsx).toMatch(/Source_Serif_4\(\{[\s\S]*variable:\s*['"]--font-serif['"][\s\S]*\}\)/);
    expect(layoutTsx).toMatch(/Noto_Serif_SC\(\{[\s\S]*variable:\s*['"]--font-serif-sc['"][\s\S]*\}\)/);
  });

  it("keeps the existing html font variables and adds the editorial serif variables", () => {
    const htmlTag = layoutTsx.match(/<html[\s\S]*?>/)?.[0] ?? "";

    expect(htmlTag).toContain("dark");
    expect(htmlTag).toContain("inter.variable");
    expect(htmlTag).toContain("jetbrainsMono.variable");
    expect(htmlTag).toContain("sourceSerif.variable");
    expect(htmlTag).toContain("notoSerifSC.variable");
  });
});
