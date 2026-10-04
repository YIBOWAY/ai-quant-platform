"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { getMarketDataHistory, type MarketDataHistoryResponse, type OhlcvRow } from "@/lib/api";
import { localizePath } from "@/lib/locale";
import { useHermesDesk } from "./HermesDeskContext";

export const DUTY_TAPE_SYMBOLS = ["SPY", "QQQ", "SOXX"] as const;
export type DutyTapeSymbol = (typeof DUTY_TAPE_SYMBOLS)[number];

const freq = "1d";
const TAPE_WINDOW_DAYS = 60;
const TAPE_REFETCH_MS = 60_000;

type HistoryRow = Pick<OhlcvRow, "timestamp" | "close">;

export function rejectedHistorySource(source: string | undefined): boolean {
  return typeof source === "string" && source.toLowerCase().startsWith("sample");
}

export function acceptDutyHistory(response: {
  source?: string;
  apiError?: string;
  rows?: HistoryRow[];
  metadata?: { provider?: string };
}): boolean {
  if (response.apiError) return false;
  if (rejectedHistorySource(response.source)) return false;
  const provider = (response.metadata?.provider || response.source || "").toLowerCase();
  if (provider !== "futu") return false;
  return usableRows(response.rows).length > 0;
}

export function rebaseClosesToZeroPercent(closes: number[]): number[] {
  const first = closes.find((value) => Number.isFinite(value) && value > 0);
  if (first === undefined) return [];
  return closes.map((value) => ((value / first) - 1) * 100);
}

export function asOfFromLastBar(rows: Array<{ timestamp: string }>): string | undefined {
  const last = rows.at(-1)?.timestamp;
  if (!last) return undefined;
  const day = last.slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : undefined;
}

export function walkSeries(cum: number[], t: number) {
  if (cum.length === 0) {
    return { values: [], headIndex: 0, headValue: 0 };
  }
  if (cum.length === 1) {
    return { values: [cum[0]], headIndex: 0, headValue: cum[0] };
  }
  const maxI = cum.length - 1;
  const f = Math.max(0, Math.min(1, t)) * maxI;
  const i = Math.min(Math.floor(f), maxI);
  const frac = f - i;
  const values = cum.slice(0, i + 1);
  if (frac > 0 && i < maxI) {
    values.push(cum[i] + (cum[i + 1] - cum[i]) * frac);
  }
  return { values, headIndex: f, headValue: values[values.length - 1] ?? 0 };
}

function usableRows(rows: HistoryRow[] | undefined): HistoryRow[] {
  return (rows ?? []).filter((row) => Number.isFinite(row.close) && row.close > 0);
}

function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function tapeRange(days = TAPE_WINDOW_DAYS) {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - days);
  return { start: isoDate(start), end: isoDate(end) };
}

function formatSignedPct(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value).toFixed(2);
  return `${value >= 0 ? "▲" : "▼"} ${abs}%`;
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduced(media.matches);
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);
  return reduced;
}

function useFollowProgress(dest: number, reduced: boolean) {
  const [progress, setProgress] = useState(reduced ? dest : 0);
  const nowRef = useRef(reduced ? dest : 0);

  useEffect(() => {
    if (reduced) {
      nowRef.current = dest;
      return;
    }
    let frame = 0;
    const tick = () => {
      const next = nowRef.current + (dest - nowRef.current) * 0.16;
      const settled = Math.abs(dest - next) < 0.001;
      const value = settled ? dest : next;
      nowRef.current = value;
      setProgress(value);
      if (!settled) frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [dest, reduced]);

  return reduced ? dest : progress;
}

type PreparedSeries = {
  symbol: DutyTapeSymbol;
  percents: number[];
  lastPct: number;
  asOf?: string;
};

function prepareSeries(
  symbol: DutyTapeSymbol,
  response: MarketDataHistoryResponse | undefined,
): PreparedSeries | { symbol: DutyTapeSymbol; reason: string } {
  if (!response || !acceptDutyHistory(response)) {
    return { symbol, reason: rejectedHistorySource(response?.source) ? "sample" : "futu" };
  }
  const rows = usableRows(response.rows);
  const percents = rebaseClosesToZeroPercent(rows.map((row) => row.close));
  if (percents.length === 0) {
    return { symbol, reason: "futu" };
  }
  return {
    symbol,
    percents,
    lastPct: percents[percents.length - 1] ?? 0,
    asOf: asOfFromLastBar(rows),
  };
}

export function DutyMarketTape() {
  const { locale } = useHermesDesk();
  const isZh = locale === "zh";
  const reduced = usePrefersReducedMotion();
  const range = useMemo(() => tapeRange(), []);
  const query = useQuery({
    queryKey: ["duty-market-tape", range.start, range.end, freq],
    queryFn: () =>
      Promise.all(
        DUTY_TAPE_SYMBOLS.map((symbol) =>
          getMarketDataHistory(symbol, range.start, range.end, freq, "futu"),
        ),
      ),
    refetchInterval: TAPE_REFETCH_MS,
  });

  const prepared = useMemo(() => {
    const items = (query.data ?? []).map((response, index) =>
      prepareSeries(DUTY_TAPE_SYMBOLS[index], response),
    );
    return items;
  }, [query.data]);

  const series = prepared.filter((item): item is PreparedSeries => "percents" in item);
  const rejected = prepared.filter((item): item is { symbol: DutyTapeSymbol; reason: string } =>
    "reason" in item,
  );
  const dest = series.length > 0 ? 1 : 0;
  const progress = useFollowProgress(dest, reduced);
  const asOf = series
    .map((item) => item.asOf)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);

  return (
    <section
      className="dp-tape"
      data-testid="duty-market-tape"
      aria-label={isZh ? "今日盯盘" : "Today's market watch"}
    >
      <div className="dp-tape-head">
        <div>
          <div className="dp-caps">
            {isZh ? "盯盘" : "Market watch"} · SPY / QQQ / SOXX
          </div>
          <p className="dp-tape-note">
            {isZh
              ? "真 Futu 日线，首日归零 0%。不是策略效果，也不是假分时。"
              : "Real Futu daily bars rebased to 0% on day one. This is not strategy performance or fake intraday data."}
            {asOf
              ? isZh
                ? ` 行情截至 ${asOf}。`
                : ` Market data through ${asOf}.`
              : ""}
          </p>
        </div>
        <div className="dp-tape-chips">
          {DUTY_TAPE_SYMBOLS.map((symbol) => {
            const item = series.find((row) => row.symbol === symbol);
            return (
              <Link
                key={symbol}
                className="dp-chip"
                data-symbol={symbol}
                href={localizePath(`/watch?symbol=${symbol}`, locale)}
              >
                <span className="name">{symbol}</span>
                <span className="dp-num">{formatSignedPct(item?.lastPct)}</span>
              </Link>
            );
          })}
        </div>
      </div>
      {series.length > 0 ? (
        <DutyTapeChart series={series} progress={progress} isZh={isZh} />
      ) : (
        <p className="dp-tape-empty">
          {query.isError || rejected.length === DUTY_TAPE_SYMBOLS.length
            ? isZh
              ? "盯盘读不到 Futu 日线。没有用 sample 回退顶上。"
              : "Futu daily bars are unavailable. No sample fallback is shown."
            : isZh
              ? "正在读 Futu 日线…"
              : "Loading Futu daily bars…"}
        </p>
      )}
    </section>
  );
}

function DutyTapeChart({
  series,
  progress,
  isZh,
}: {
  series: PreparedSeries[];
  progress: number;
  isZh: boolean;
}) {
  const width = 640;
  const height = 140;
  const pad = { l: 8, r: 8, t: 10, b: 16 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const all = series.flatMap((item) => item.percents);
  const min = Math.min(...all, 0);
  const max = Math.max(...all, 0);
  const span = Math.max(max - min, 0.0001);
  const x = (index: number, n: number) => pad.l + (index / Math.max(n - 1, 1)) * innerW;
  const y = (value: number) => pad.t + (max - value) * (innerH / span);
  const zeroY = y(0);

  return (
    <svg
      className="dp-tape-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={
        isZh
          ? "SPY、QQQ、SOXX 日线累计收益，首日归零"
          : "SPY, QQQ, and SOXX cumulative daily returns, rebased to zero on day one"
      }
    >
      <line className="axis" x1={pad.l} y1={zeroY} x2={width - pad.r} y2={zeroY} />
      {series.map((item) => {
        const n = item.percents.length;
        const walk = walkSeries(item.percents, progress);
        const points = walk.values
          .map((value, idx) => {
            const xi = idx === walk.values.length - 1 ? walk.headIndex : idx;
            return `${x(xi, n).toFixed(1)},${y(value).toFixed(1)}`;
          })
          .join(" ");
        return (
          <g key={item.symbol} data-symbol={item.symbol} data-dir={item.lastPct >= 0 ? "up" : "down"}>
            <polyline fill="none" points={points} />
            <circle
              className="head"
              cx={x(walk.headIndex, n)}
              cy={y(walk.headValue)}
              r="2.4"
            />
          </g>
        );
      })}
    </svg>
  );
}
