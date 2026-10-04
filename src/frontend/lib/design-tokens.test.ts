import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const globalsCss = readFileSync(path.join(process.cwd(), "app/globals.css"), "utf8");

describe("editorial design tokens", () => {
  it("defines the additive paper, Hermes stream, layout, and editorial radius tokens", () => {
    const expectedTokens = [
      "--color-bg-base: #111315;",
      "--color-bg-sidebar: #17191c;",
      "--color-bg-sidebar-muted: #222529;",
      "--color-bg-surface: #1b1e21;",
      "--color-bg-surface-muted: #24282c;",
      "--color-paper-ink: var(--color-bg-base);",
      "--color-paper-surface: var(--color-bg-surface);",
      "--color-paper-surface-muted: var(--color-bg-surface-muted);",
      "--color-ink: #e2e8f0;",
      "--color-ink-secondary: #94a0b2;",
      "--color-editorial-rule: #2f3947;",
      "--color-editorial-accent: #d6b37c;",
      "--color-editorial-up: #2fbf87;",
      "--color-editorial-down: #f2555f;",
      "--color-hermes: #d6b37c;",
      "--color-hermes-glow: rgba(214, 179, 124, 0.15);",
      "--color-stream-bg: var(--color-bg-base);",
      "--color-stream-surface: var(--color-bg-surface);",
      "--color-stream-surface-2: var(--color-bg-surface-muted);",
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
    expect(css).toContain("--spacing-hermes-composer-min: 142px");
    expect(css).toContain("--spacing-hermes-content-max: 1180px");
    expect(css).toContain("--color-hermes-attention:");
    expect(css).toContain("--color-hermes-canvas:");
    expect(css).toContain(".app-touch-target");
    expect(css).toContain(":focus-visible");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });

  it("defines the shared motion duration/easing contract for state continuity", () => {
    expect(globalsCss).toContain("--duration-motion-micro: 120ms");
    expect(globalsCss).toContain("--duration-motion-short: 220ms");
    expect(globalsCss).toContain("--duration-motion-medium: 420ms");
    expect(globalsCss).toContain("--ease-motion-out: cubic-bezier(0.16, 1, 0.3, 1)");
    expect(globalsCss).toContain("--ease-motion-in: cubic-bezier(0.7, 0, 0.84, 0)");
    expect(globalsCss).toContain(".motion-data-hold");
    expect(globalsCss).toContain(".motion-panel-enter");
  });
});

describe("status color tokens used by market dashboards", () => {
  it("defines every accent/status token referenced by components so Tailwind never drops them", () => {
    // A missing --color-* token makes Tailwind v4 silently drop the utility,
    // which once rendered the K-shape laggard series invisible.
    for (const token of [
      "--color-accent-success:",
      "--color-accent-danger:",
      "--color-warning:",
      "--color-danger:",
      "--color-info:",
      "--color-bg-base:",
      "--color-bg-surface:",
    ]) {
      expect(globalsCss).toContain(token);
    }
  });
});
