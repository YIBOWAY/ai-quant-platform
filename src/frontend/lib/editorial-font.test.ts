import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const layoutTsx = readFileSync(path.join(process.cwd(), "app/layout.tsx"), "utf8");

// The vendored woff2 files layout.tsx must reference (V1.4 offline build).
const VENDORED_FONTS = [
  "inter-var.woff2",
  "jetbrains-mono-var.woff2",
  "source-serif-4-400-normal.woff2",
  "source-serif-4-400-italic.woff2",
  "source-serif-4-600-normal.woff2",
  "source-serif-4-600-italic.woff2",
  "source-serif-4-700-normal.woff2",
  "source-serif-4-700-italic.woff2",
  "noto-serif-sc-400.woff2",
  "noto-serif-sc-700.woff2",
];

describe("editorial font setup (V1.4 offline / local fonts)", () => {
  it("loads fonts via next/font/local, not next/font/google", () => {
    expect(layoutTsx).toMatch(/import\s+localFont\s+from\s+['"]next\/font\/local['"];/);
    // Offline build must not depend on the network-fetching Google loader.
    expect(layoutTsx).not.toMatch(/from\s+['"]next\/font\/google['"]/);
  });

  it("configures the editorial serif font variables", () => {
    expect(layoutTsx).toMatch(/variable:\s*['"]--font-serif['"]/);
    expect(layoutTsx).toMatch(/variable:\s*['"]--font-serif-sc['"]/);
  });

  it("keeps the existing html font variables and adds the editorial serif variables", () => {
    const htmlTag = layoutTsx.match(/<html[\s\S]*?>/)?.[0] ?? "";

    expect(htmlTag).toContain("dark");
    expect(htmlTag).toContain("inter.variable");
    expect(htmlTag).toContain("jetbrainsMono.variable");
    expect(htmlTag).toContain("sourceSerif.variable");
    expect(htmlTag).toContain("notoSerifSC.variable");
  });

  it("references every vendored woff2 from layout.tsx", () => {
    for (const file of VENDORED_FONTS) {
      expect(layoutTsx).toContain(`./fonts/${file}`);
    }
  });

  it("vendored woff2 files exist on disk", () => {
    for (const file of VENDORED_FONTS) {
      const p = path.join(process.cwd(), "app", "fonts", file);
      expect(existsSync(p), `missing vendored font ${file}`).toBe(true);
    }
  });
});
