import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const layoutTsx = readFileSync(path.join(process.cwd(), "app/layout.tsx"), "utf8");
const globalsCss = readFileSync(path.join(process.cwd(), "app/globals.css"), "utf8");
const iconPath = path.join(process.cwd(), "app/icon.svg");

describe("root layout metadata", () => {
  it("generates locale-aware title and description via getServerLocale", () => {
    expect(layoutTsx).toContain("export async function generateMetadata");
    expect(layoutTsx).toContain("getServerLocale()");
    // zh keeps the established title; en gets a real translation instead of
    // falling back to Chinese in the browser tab.
    expect(layoutTsx).toContain("今日 · 研究 · 模拟 · 个人量化助手");
    expect(layoutTsx).toContain("本地个人量化助手：今日、研究、模拟三本账");
    expect(layoutTsx).toContain("Today · Research · Paper · Personal Quant Assistant");
    expect(layoutTsx).not.toContain("export const metadata");
  });
});

describe("app icon", () => {
  it("ships an app/icon.svg so Next serves a favicon", () => {
    expect(existsSync(iconPath)).toBe(true);
    const icon = readFileSync(iconPath, "utf8");
    expect(icon).toContain("<svg");
  });

  it("uses the --color-hermes brand color from globals.css", () => {
    const hermesColor = globalsCss.match(/--color-hermes:\s*(#[0-9a-fA-F]{6});/)?.[1];
    expect(hermesColor).toBeTruthy();
    const icon = readFileSync(iconPath, "utf8");
    expect(icon).toContain(hermesColor);
  });
});
