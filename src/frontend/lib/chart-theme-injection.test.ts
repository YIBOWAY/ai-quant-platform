import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const chartFiles = {
  candlestick: "components/CandlestickChart.tsx",
  equityComparison: "components/EquityComparisonChart.tsx",
  factorRun: "components/FactorRunCharts.tsx",
} as const;

function readChartFile(file: keyof typeof chartFiles) {
  return readFileSync(path.join(process.cwd(), chartFiles[file]), "utf8");
}

describe("chart theme injection", () => {
  it("imports the shared chart token module in each chart file", () => {
    for (const file of Object.keys(chartFiles) as (keyof typeof chartFiles)[]) {
      expect(readChartFile(file)).toContain('from "@/lib/chartTokens"');
    }
  });

  it("adds a ChartTheme prop to each chart component type", () => {
    expect(readChartFile("candlestick")).toContain("theme?: ChartTheme");
    expect(readChartFile("equityComparison")).toContain("theme?: ChartTheme");
    expect(readChartFile("factorRun")).toContain("theme?: ChartTheme");
  });

  it("defaults every exported chart component to terminalChartTheme", () => {
    expect(readChartFile("candlestick")).toMatch(
      /export function CandlestickChart\([^)]*theme = terminalChartTheme/,
    );
    expect(readChartFile("equityComparison")).toMatch(
      /export function EquityComparisonChart\([^)]*theme = terminalChartTheme/,
    );
    expect(readChartFile("factorRun")).toMatch(
      /export function ICLineChart\([^)]*theme = terminalChartTheme/,
    );
    expect(readChartFile("factorRun")).toMatch(
      /export function QuantileReturnChart\([^)]*theme = terminalChartTheme/,
    );
  });

  it("removes the old local chart color constants", () => {
    expect(readChartFile("candlestick")).not.toContain("const CHART_COLORS =");
    expect(readChartFile("equityComparison")).not.toContain("const COLORS =");
    expect(readChartFile("factorRun")).not.toContain("const COLORS =");
  });

  it("routes candlestick chart rendering through the injected theme", () => {
    const source = readChartFile("candlestick");

    expect(source).toContain("theme.grid");
    expect(source).toContain("theme.text");
    expect(source).toContain("theme.volumeUp");
  });

  it("keeps candlestick chart lifecycle independent from theme object identity", () => {
    const source = readChartFile("candlestick");

    expect(source).not.toContain("[fixedHeight, theme]");
    expect(source).not.toContain("normalizeRows(rows, theme)");
    expect(source).toContain("normalizeRows(rows, theme.volumeUp, theme.volumeDown)");
    expect(source).toContain("[rows, theme.volumeUp, theme.volumeDown]");
  });

  it("applies candlestick theme changes through refs with primitive dependencies", () => {
    const source = readChartFile("candlestick");

    expect(source).toContain(
      "applyThemeToChart(chartRef.current, candleSeriesRef.current, volumeSeriesRef.current, currentTheme);",
    );
    expect(source).toContain("chart?.applyOptions({");
    expect(source).toContain("candleSeries?.applyOptions({");
    expect(source).toContain("volumeSeries?.applyOptions({");
    expect(source).toContain(`[
    theme.background,
    theme.text,
    theme.grid,
    theme.border,
    theme.up,
    theme.down,
    theme.volumeUp,
    theme.volumeDown,
  ]`);
  });

  it("seeds recreated candlestick chart instances from latest theme and chart data refs", () => {
    const source = readChartFile("candlestick");

    expect(source).toContain("const latestThemeRef = useRef(theme);");
    expect(source).toContain("const latestChartDataRef = useRef(chartData);");
    expect(source).toContain("latestThemeRef.current = theme;");
    expect(source).toContain("latestChartDataRef.current = chartData;");
    expect(source).toContain("applyThemeToChart(chart, candleSeries, volumeSeries, latestThemeRef.current);");
    expect(source).toContain(
      "applyChartDataToChart(chart, candleSeries, volumeSeries, latestChartDataRef.current);",
    );

    const refAssignmentIndex = source.indexOf("volumeSeriesRef.current = volumeSeries;");
    const themeSeedIndex = source.indexOf(
      "applyThemeToChart(chart, candleSeries, volumeSeries, latestThemeRef.current);",
    );
    const dataSeedIndex = source.indexOf(
      "applyChartDataToChart(chart, candleSeries, volumeSeries, latestChartDataRef.current);",
    );

    expect(themeSeedIndex).toBeGreaterThan(refAssignmentIndex);
    expect(dataSeedIndex).toBeGreaterThan(refAssignmentIndex);
  });
});
