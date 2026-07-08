import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const globalsCss = readFileSync(path.join(process.cwd(), "app/globals.css"), "utf8");

describe("editorial design tokens", () => {
  it("defines the additive paper, Hermes stream, layout, and editorial radius tokens", () => {
    const expectedTokens = [
      "--color-paper-ink: #14130F;",
      "--color-paper-surface: #1A1916;",
      "--color-paper-surface-muted: #222019;",
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
      "--font-editorial-serif: var(--font-serif, 'Source Serif 4'), Georgia, 'Noto Serif SC', 'Songti SC', serif;",
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
});
