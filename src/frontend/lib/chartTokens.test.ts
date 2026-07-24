import { describe, expect, it } from "vitest";
import {
  editorialChartTheme,
  readCssVar,
  terminalChartTheme,
  type ChartTheme,
} from "@/lib/chartTokens";

const chartThemeKeys = [
  "background",
  "text",
  "grid",
  "rechartsGrid",
  "border",
  "up",
  "down",
  "volumeUp",
  "volumeDown",
  "strategy",
  "benchmark",
  "ic",
  "rankIc",
  "positive",
  "negative",
  "axis",
  "tick",
  "tooltipBg",
  "tooltipBorder",
  "tooltipText",
  "tooltipBorderRadius",
  "legendText",
] satisfies (keyof ChartTheme)[];

describe("chart theme tokens", () => {
  it("preserves the terminal chart literal colors used by existing charts", () => {
    expect(terminalChartTheme).toEqual({
      background: "#111827",
      text: "#94A3B8",
      grid: "rgba(148, 163, 184, 0.10)",
      rechartsGrid: "rgba(148, 163, 184, 0.12)",
      border: "rgba(148, 163, 184, 0.22)",
      up: "#00C896",
      down: "#FF4D4F",
      volumeUp: "rgba(0, 200, 150, 0.32)",
      volumeDown: "rgba(255, 77, 79, 0.32)",
      strategy: "#00C896",
      benchmark: "#60A5FA",
      ic: "#60A5FA",
      rankIc: "#00C896",
      positive: "#00C896",
      negative: "#FF4D4F",
      axis: "#64748B",
      tick: "#94A3B8",
      tooltipBg: "#111827",
      tooltipBorder: "rgba(148, 163, 184, 0.24)",
      tooltipText: "#E2E8F0",
      tooltipBorderRadius: 8,
      legendText: "#CBD5E1",
    });
  });

  it("defines the warm editorial chart theme values", () => {
    expect(editorialChartTheme).toMatchObject({
      background: "#1A1916",
      up: "#2E9E6A",
      down: "#C84A52",
      benchmark: "#7B8FD0",
      tooltipBorderRadius: 2,
      tooltipText: "#EDE7DA",
    });
  });

  it("defines every ChartTheme field for both shipped themes", () => {
    for (const theme of [terminalChartTheme, editorialChartTheme]) {
      for (const key of chartThemeKeys) {
        expect(theme[key]).toBeDefined();
      }
    }
  });

  it("returns the fallback when reading CSS variables without a browser window", () => {
    expect(readCssVar("--color-chart-up", "#123456")).toBe("#123456");
  });
});
