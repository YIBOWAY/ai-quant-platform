import { createElement } from "react";
import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { HermesParityBanner } from "@/components/HermesParityBanner";

const LEGACY_PAGES = [
  "app/factor-lab/page.tsx",
  "app/backtest/page.tsx",
  "app/experiments/page.tsx",
  "app/agent-studio/page.tsx",
] as const;

describe("HermesParityBanner", () => {
  it("renders ZH honest parity copy with locale-aware Hermes home link", () => {
    const html = renderToStaticMarkup(
      createElement(HermesParityBanner, { locale: "zh" }),
    );

    expect(html).toContain('data-testid="hermes-parity-banner"');
    expect(html).toContain("Hermes 工作台是默认研究入口");
    expect(html).toContain("不代表本页已退役");
    expect(html).toContain('href="/zh/hermes"');
    expect(html).toContain("border-info");
    expect(html).toContain("text-info");
  });

  it("renders EN honest parity copy with locale-aware Hermes home link", () => {
    const html = renderToStaticMarkup(
      createElement(HermesParityBanner, { locale: "en" }),
    );

    expect(html).toContain("default research entry");
    expect(html).toContain("does not mean this page is retired");
    expect(html).toContain('href="/en/hermes"');
  });
});

describe("legacy research pages host HermesParityBanner", () => {
  it.each(LEGACY_PAGES)("%s imports and renders HermesParityBanner", (rel) => {
    const source = readFileSync(path.join(process.cwd(), rel), "utf8");
    expect(source).toContain("HermesParityBanner");
    expect(source).toContain("<HermesParityBanner");
  });
});
