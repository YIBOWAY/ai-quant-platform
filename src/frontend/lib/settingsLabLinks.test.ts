import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { buildNavSections, sectionsForSurface } from "@/lib/navConfig";

const source = readFileSync(path.join(process.cwd(), "app/settings/page.tsx"), "utf8");
const labBlock = source.slice(
  source.indexOf("const labHrefs"),
  source.indexOf("] as const"),
);

describe("settings lab links", () => {
  it("does not list sidebar pages as off-sidebar labs", () => {
    const sidebarRoutes = sectionsForSurface(
      buildNavSections({ shellEnabled: true }),
      "sidebar",
    ).flatMap((section) => section.items.map((item) => item.href));
    expect(sidebarRoutes).toContain("/options-screener");
    expect(sidebarRoutes).toContain("/options-radar");
    expect(sidebarRoutes).toContain("/options-buyside");
    expect(sidebarRoutes).toContain("/ai-news");

    for (const href of [
      "/options-screener",
      "/options-radar",
      "/options-buyside",
      "/ai-news",
    ]) {
      expect(labBlock).not.toContain(`"${href}"`);
    }
    expect(labBlock).not.toContain("/options-tools");
    expect(labBlock).toContain("/polymarket");
    expect(source).toContain("不进默认侧栏");
  });
});
