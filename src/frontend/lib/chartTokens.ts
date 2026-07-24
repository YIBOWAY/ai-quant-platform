export type ChartTheme = {
  background: string;
  text: string;
  grid: string;
  rechartsGrid: string;
  border: string;
  up: string;
  down: string;
  volumeUp: string;
  volumeDown: string;
  strategy: string;
  benchmark: string;
  ic: string;
  rankIc: string;
  positive: string;
  negative: string;
  axis: string;
  tick: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  tooltipBorderRadius: number;
  legendText: string;
};

export const terminalChartTheme: ChartTheme = {
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
};

export const editorialChartTheme: ChartTheme = {
  background: "#1A1916",
  text: "#A39E92",
  grid: "#3A3733",
  rechartsGrid: "#3A3733",
  border: "#3A3733",
  up: "#2E9E6A",
  down: "#C84A52",
  volumeUp: "rgba(46, 158, 106, 0.28)",
  volumeDown: "rgba(200, 74, 82, 0.28)",
  strategy: "#2E9E6A",
  benchmark: "#7B8FD0",
  ic: "#7B8FD0",
  rankIc: "#2E9E6A",
  positive: "#2E9E6A",
  negative: "#C84A52",
  axis: "#A39E92",
  tick: "#A39E92",
  tooltipBg: "#222019",
  tooltipBorder: "#3A3733",
  tooltipText: "#EDE7DA",
  tooltipBorderRadius: 2,
  legendText: "#EDE7DA",
};

export function readCssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") {
    return fallback;
  }

  const value = window.getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}
