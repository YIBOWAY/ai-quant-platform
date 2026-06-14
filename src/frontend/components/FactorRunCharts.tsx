'use client';

import { useEffect, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PreviewRecord } from "@/lib/api";

type Locale = "en" | "zh";

// Mirrors @theme tokens.
const COLORS = {
  ic: "#60A5FA",
  rankIc: "#00C896",
  positive: "#00C896",
  negative: "#FF4D4F",
  axis: "#64748B",
  tick: "#94A3B8",
  grid: "rgba(148, 163, 184, 0.12)",
  tooltipBg: "#111827",
  tooltipBorder: "rgba(148, 163, 184, 0.24)",
};

const copy = {
  en: {
    icTitle: "Rank IC over time",
    icDesc: "Per-date cross-sectional correlation between factor values and next-period returns. Stable positive = useful ordering.",
    quantileTitle: "Mean forward return by quantile",
    quantileDesc: "Average next-period return per factor bucket (Q1 = lowest factor values). A monotonic ladder = good separation.",
    ic: "IC",
    rankIc: "Rank IC",
    quantile: "Q",
  },
  zh: {
    icTitle: "Rank IC 时间序列",
    icDesc: "每个交易日因子值排序与下一期收益的相关性。持续为正 = 排序有用。",
    quantileTitle: "分位组平均未来收益",
    quantileDesc: "按因子分组后各组的下一期平均收益（Q1 = 因子值最低组）。单调阶梯 = 区分度好。",
    ic: "IC",
    rankIc: "Rank IC",
    quantile: "Q",
  },
} as const;

function useContainerWidth(initial = 640) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => setWidth(Math.max(Math.floor(element.clientWidth) - 8, 280));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

const tooltipStyle = {
  background: COLORS.tooltipBg,
  border: `1px solid ${COLORS.tooltipBorder}`,
  borderRadius: 8,
  color: "#E2E8F0",
  fontSize: 12,
};

/** IC / Rank-IC line chart from a factor run's information_coefficients rows
 *  ({factor_id, signal_ts, ic, rank_ic, n}). Renders nothing if unusable. */
export function ICLineChart({ rows, locale = "en" }: { rows: PreviewRecord[]; locale?: Locale }) {
  const text = copy[locale];
  const { ref, width } = useContainerWidth();
  const data = rows
    .map((row) => ({
      date: String(row.signal_ts ?? row.timestamp ?? "").slice(0, 10),
      ic: toNumber(row.ic),
      rank_ic: toNumber(row.rank_ic),
    }))
    .filter((row) => row.date && (row.ic !== null || row.rank_ic !== null));
  if (data.length < 2) {
    return null;
  }
  return (
    <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
      <h3 className="font-label-caps text-text-primary">{text.icTitle}</h3>
      <p className="mb-3 mt-1 font-body-sm text-text-secondary">{text.icDesc}</p>
      <div ref={ref}>
        <LineChart data={data} height={240} margin={{ bottom: 4, left: 0, right: 12, top: 8 }} width={width}>
          <CartesianGrid stroke={COLORS.grid} vertical={false} />
          <XAxis dataKey="date" minTickGap={42} stroke={COLORS.axis} tick={{ fill: COLORS.tick, fontSize: 11 }} tickLine={false} />
          <YAxis stroke={COLORS.axis} tick={{ fill: COLORS.tick, fontSize: 11 }} tickFormatter={(v) => Number(v).toFixed(2)} tickLine={false} width={46} />
          <Tooltip contentStyle={tooltipStyle} formatter={(value) => Number(value).toFixed(4)} labelStyle={{ color: COLORS.tick }} />
          <ReferenceLine stroke={COLORS.axis} strokeDasharray="4 4" y={0} />
          <Line connectNulls dataKey="rank_ic" dot={false} name={text.rankIc} stroke={COLORS.rankIc} strokeWidth={2} type="monotone" />
          <Line connectNulls dataKey="ic" dot={false} name={text.ic} stroke={COLORS.ic} strokeOpacity={0.7} strokeWidth={1.5} type="monotone" />
        </LineChart>
      </div>
    </section>
  );
}

/** Quantile mean-forward-return bar chart from quantile_returns rows
 *  ({factor_id, quantile, mean_forward_return, ...}). Averages across dates if needed. */
export function QuantileReturnChart({ rows, locale = "en" }: { rows: PreviewRecord[]; locale?: Locale }) {
  const text = copy[locale];
  const { ref, width } = useContainerWidth();
  const buckets = new Map<number, { sum: number; count: number }>();
  for (const row of rows) {
    const quantile = toNumber(row.quantile);
    const value = toNumber(row.mean_forward_return) ?? toNumber(row.forward_return);
    if (quantile === null || value === null) continue;
    const bucket = buckets.get(quantile) ?? { sum: 0, count: 0 };
    bucket.sum += value;
    bucket.count += 1;
    buckets.set(quantile, bucket);
  }
  const data = Array.from(buckets.entries())
    .sort(([a], [b]) => a - b)
    .map(([quantile, { sum, count }]) => ({
      bucket: `${text.quantile}${quantile + 1}`,
      value: sum / count,
    }));
  if (data.length < 2) {
    return null;
  }
  return (
    <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
      <h3 className="font-label-caps text-text-primary">{text.quantileTitle}</h3>
      <p className="mb-3 mt-1 font-body-sm text-text-secondary">{text.quantileDesc}</p>
      <div ref={ref}>
        <BarChart data={data} height={220} margin={{ bottom: 4, left: 0, right: 12, top: 8 }} width={width}>
          <CartesianGrid stroke={COLORS.grid} vertical={false} />
          <XAxis dataKey="bucket" stroke={COLORS.axis} tick={{ fill: COLORS.tick, fontSize: 11 }} tickLine={false} />
          <YAxis stroke={COLORS.axis} tick={{ fill: COLORS.tick, fontSize: 11 }} tickFormatter={(v) => `${(Number(v) * 100).toFixed(2)}%`} tickLine={false} width={62} />
          <Tooltip contentStyle={tooltipStyle} formatter={(value) => `${(Number(value) * 100).toFixed(3)}%`} labelStyle={{ color: COLORS.tick }} />
          <ReferenceLine stroke={COLORS.axis} strokeDasharray="4 4" y={0} />
          <Bar dataKey="value" radius={[3, 3, 0, 0]}>
            {data.map((entry) => (
              <Cell fill={entry.value >= 0 ? COLORS.positive : COLORS.negative} key={entry.bucket} />
            ))}
          </Bar>
        </BarChart>
      </div>
    </section>
  );
}

function toNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
