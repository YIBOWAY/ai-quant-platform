import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const globalsCss = readFileSync(path.join(process.cwd(), "app/globals.css"), "utf8");

describe("editorial design tokens", () => {
  it("defines the additive paper, Hermes stream, layout, and editorial radius tokens", () => {
    const expectedTokens = [
      "--color-bg-base: #12110E;",
      "--color-bg-sidebar: #1C1B20;",
      "--color-bg-sidebar-muted: #25242A;",
      "--color-bg-surface: #181714;",
      "--color-bg-surface-muted: #23211C;",
      "--color-paper-ink: var(--color-bg-base);",
      "--color-paper-surface: var(--color-bg-surface);",
      "--color-paper-surface-muted: var(--color-bg-surface-muted);",
      "--color-ink: #EDE7DA;",
      "--color-ink-secondary: #A39E92;",
      "--color-editorial-rule: #3A3733;",
      "--color-editorial-accent: #7B8FD0;",
      "--color-editorial-up: #2E9E6A;",
      "--color-editorial-down: #C84A52;",
      "--color-hermes: #9085E9;",
      "--color-hermes-glow: rgba(144, 133, 233, 0.4);",
      "--color-stream-bg: #17171C;",
      "--color-stream-surface: #1F1F27;",
      "--color-stream-surface-2: #262631;",
      "--font-editorial-serif: var(--font-serif), var(--font-serif-sc), Georgia, 'Songti SC', serif;",
      "--spacing-rail-width: 208px;",
      "--spacing-right-panel: 340px;",
      "--spacing-stream-max: 720px;",
      "--spacing-editorial-column: 1120px;",
      "--radius-editorial: 2px;",
    ];

    for (const token of expectedTokens) {
      expect(globalsCss).toContain(token);
    }
  });

  it("routes Chinese editorial text through the Next-hosted SC font variable", () => {
    expect(globalsCss).toContain("var(--font-serif-sc)");
  });
});

describe("Hermes shell accessibility and layout tokens", () => {
  it("defines Hermes content/composer spacing, attention/canvas colors, and a11y contracts", () => {
    const css = globalsCss;
    expect(css).toContain("--spacing-hermes-composer-min: 64px");
    expect(css).toContain("--spacing-hermes-content-max: 1180px");
    expect(css).toContain("--color-hermes-attention:");
    expect(css).toContain("--color-hermes-canvas:");
    expect(css).toContain(".app-touch-target");
    expect(css).toContain(":focus-visible");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
