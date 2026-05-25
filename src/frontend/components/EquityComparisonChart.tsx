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
};

export function EquityComparisonChart({ rows, height = 360 }: EquityComparisonChartProps) {
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
      className="h-[360px] rounded border border-border-subtle bg-surface-muted p-3"
      data-testid="equity-comparison-chart"
      ref={containerRef}
      style={{ height }}
    >
      <LineChart data={rows} height={height - 24} margin={{ bottom: 8, left: 0, right: 16, top: 12 }} width={width}>
        <CartesianGrid stroke="rgba(148, 163, 184, 0.12)" vertical={false} />
        <XAxis
          dataKey="timestamp"
          minTickGap={34}
          stroke="#64748B"
          tick={{ fill: "#94A3B8", fontSize: 11 }}
          tickLine={false}
        />
        <YAxis
          domain={["auto", "auto"]}
          stroke="#64748B"
          tick={{ fill: "#94A3B8", fontSize: 11 }}
          tickFormatter={(value) => Number(value).toFixed(2)}
          tickLine={false}
          width={54}
        />
        <Tooltip
          contentStyle={{
            background: "#101614",
            border: "1px solid rgba(148, 163, 184, 0.24)",
            borderRadius: 4,
            color: "#E2E8F0",
          }}
          formatter={(value) => Number(value).toFixed(4)}
          labelStyle={{ color: "#94A3B8" }}
        />
        <Legend wrapperStyle={{ color: "#CBD5E1", fontSize: 12 }} />
        <Line
          activeDot={{ r: 4 }}
          connectNulls
          dataKey="strategy"
          dot={false}
          name="Strategy"
          stroke="#10C89B"
          strokeWidth={2}
          type="monotone"
        />
        <Line
          connectNulls
          dataKey="benchmark"
          dot={false}
          name="Benchmark"
          stroke="#38BDF8"
          strokeWidth={2}
          type="monotone"
        />
      </LineChart>
    </div>
  );
}
