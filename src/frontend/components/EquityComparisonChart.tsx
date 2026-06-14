'use client';

import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type EquityPoint = {
  timestamp: string;
  strategy?: number | null;
  benchmark?: number | null;
};

type EquityComparisonChartProps = {
  rows: EquityPoint[];
  height?: number;
  /** Localized series names; defaults to English. */
  labels?: { strategy: string; benchmark: string };
};

// Mirrors @theme tokens (accent-success / info / bg-surface).
const COLORS = {
  strategy: "#00C896",
  benchmark: "#60A5FA",
  axis: "#64748B",
  tick: "#94A3B8",
  grid: "rgba(148, 163, 184, 0.12)",
  tooltipBg: "#111827",
  tooltipBorder: "rgba(148, 163, 184, 0.24)",
};

export function EquityComparisonChart({
  rows,
  height = 360,
  labels = { strategy: "Strategy", benchmark: "Benchmark" },
}: EquityComparisonChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(720);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }
    const update = () => {
      setWidth(Math.max(Math.floor(element.clientWidth), 320));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  if (!rows.length) {
    return null;
  }

  return (
    <div
      className="overflow-hidden rounded-lg border border-border-subtle bg-bg-surface-muted/40 p-3"
      data-testid="equity-comparison-chart"
      ref={containerRef}
      style={{ height }}
    >
      <LineChart data={rows} height={height - 24} margin={{ bottom: 8, left: 0, right: 16, top: 12 }} width={width}>
        <CartesianGrid stroke={COLORS.grid} vertical={false} />
        <XAxis
          dataKey="timestamp"
          minTickGap={34}
          stroke={COLORS.axis}
          tick={{ fill: COLORS.tick, fontSize: 11 }}
          tickLine={false}
        />
        <YAxis
          domain={["auto", "auto"]}
          stroke={COLORS.axis}
          tick={{ fill: COLORS.tick, fontSize: 11 }}
          tickFormatter={(value) => Number(value).toFixed(2)}
          tickLine={false}
          width={54}
        />
        <Tooltip
          contentStyle={{
            background: COLORS.tooltipBg,
            border: `1px solid ${COLORS.tooltipBorder}`,
            borderRadius: 8,
            color: "#E2E8F0",
          }}
          formatter={(value) => Number(value).toFixed(4)}
          labelStyle={{ color: COLORS.tick }}
        />
        <Legend wrapperStyle={{ color: "#CBD5E1", fontSize: 12 }} />
        <Line
          activeDot={{ r: 4 }}
          connectNulls
          dataKey="strategy"
          dot={false}
          name={labels.strategy}
          stroke={COLORS.strategy}
          strokeWidth={2}
          type="monotone"
        />
        <Line
          connectNulls
          dataKey="benchmark"
          dot={false}
          name={labels.benchmark}
          stroke={COLORS.benchmark}
          strokeWidth={2}
          type="monotone"
        />
      </LineChart>
    </div>
  );
}
