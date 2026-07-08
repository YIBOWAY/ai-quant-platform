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
import { terminalChartTheme, type ChartTheme } from "@/lib/chartTokens";

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
  theme?: ChartTheme;
};

export function EquityComparisonChart({
  rows,
  height = 360,
  labels = { strategy: "Strategy", benchmark: "Benchmark" },
  theme = terminalChartTheme,
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
        <CartesianGrid stroke={theme.rechartsGrid} vertical={false} />
        <XAxis
          dataKey="timestamp"
          minTickGap={34}
          stroke={theme.axis}
          tick={{ fill: theme.tick, fontSize: 11 }}
          tickLine={false}
        />
        <YAxis
          domain={["auto", "auto"]}
          stroke={theme.axis}
          tick={{ fill: theme.tick, fontSize: 11 }}
          tickFormatter={(value) => Number(value).toFixed(2)}
          tickLine={false}
          width={54}
        />
        <Tooltip
          contentStyle={{
            background: theme.tooltipBg,
            border: `1px solid ${theme.tooltipBorder}`,
            borderRadius: theme.tooltipBorderRadius,
            color: theme.tooltipText,
          }}
          formatter={(value) => Number(value).toFixed(4)}
          labelStyle={{ color: theme.tick }}
        />
        <Legend wrapperStyle={{ color: theme.legendText, fontSize: 12 }} />
        <Line
          activeDot={{ r: 4 }}
          connectNulls
          dataKey="strategy"
          dot={false}
          name={labels.strategy}
          stroke={theme.strategy}
          strokeWidth={2}
          type="monotone"
        />
        <Line
          connectNulls
          dataKey="benchmark"
          dot={false}
          name={labels.benchmark}
          stroke={theme.benchmark}
          strokeWidth={2}
          type="monotone"
        />
      </LineChart>
    </div>
  );
}
