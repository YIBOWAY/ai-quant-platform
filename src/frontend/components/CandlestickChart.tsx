'use client';

import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import type { OhlcvRow } from "@/lib/api";
import { terminalChartTheme, type ChartTheme } from "@/lib/chartTokens";

type CandlestickChartProps = {
  rows: OhlcvRow[];
  /** Optional fixed height in px. When omitted the chart fills its parent. */
  height?: number;
  locale?: "en" | "zh";
  theme?: ChartTheme;
};

export function CandlestickChart({
  rows,
  height: fixedHeight,
  locale = "en",
  theme = terminalChartTheme,
}: CandlestickChartProps) {
  const chartHostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const chartData = useMemo(
    () => normalizeRows(rows, theme.volumeUp, theme.volumeDown),
    [rows, theme.volumeUp, theme.volumeDown],
  );
  const latestThemeRef = useRef(theme);
  const latestChartDataRef = useRef(chartData);

  useEffect(() => {
    latestThemeRef.current = theme;
    latestChartDataRef.current = chartData;
  });

  useEffect(() => {
    const host = chartHostRef.current;
    if (!host || chartRef.current) {
      return;
    }

    const chart = createChart(host, {
      autoSize: false,
      height: fixedHeight ?? Math.max(host.clientHeight, 240),
      width: host.clientWidth,
      layout: {
        background: { color: terminalChartTheme.background },
        textColor: terminalChartTheme.text,
      },
      grid: {
        vertLines: { color: terminalChartTheme.grid },
        horzLines: { color: terminalChartTheme.grid },
      },
      rightPriceScale: {
        borderColor: terminalChartTheme.border,
      },
      timeScale: {
        borderColor: terminalChartTheme.border,
        timeVisible: false,
      },
      crosshair: {
        mode: 1,
      },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: terminalChartTheme.up,
      downColor: terminalChartTheme.down,
      borderUpColor: terminalChartTheme.up,
      borderDownColor: terminalChartTheme.down,
      wickUpColor: terminalChartTheme.up,
      wickDownColor: terminalChartTheme.down,
    });
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: terminalChartTheme.volumeUp,
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.78,
        bottom: 0,
      },
    });
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    applyThemeToChart(chart, candleSeries, volumeSeries, latestThemeRef.current);
    applyChartDataToChart(chart, candleSeries, volumeSeries, latestChartDataRef.current);

    // Drive both width AND height from the host element's real box, so the
    // chart fills whatever space its flex parent gives it.
    const applySize = () => {
      const width = host.clientWidth;
      const height = fixedHeight ?? Math.max(host.clientHeight, 240);
      if (width > 0 && height > 0) {
        chart.applyOptions({ width, height });
      }
    };
    applySize();
    const observer = new ResizeObserver(applySize);
    observer.observe(host);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, [fixedHeight]);

  useEffect(() => {
    const currentTheme: CandlestickTheme = {
      background: theme.background,
      text: theme.text,
      grid: theme.grid,
      border: theme.border,
      up: theme.up,
      down: theme.down,
      volumeUp: theme.volumeUp,
      volumeDown: theme.volumeDown,
    };
    applyThemeToChart(chartRef.current, candleSeriesRef.current, volumeSeriesRef.current, currentTheme);
  }, [
    theme.background,
    theme.text,
    theme.grid,
    theme.border,
    theme.up,
    theme.down,
    theme.volumeUp,
    theme.volumeDown,
  ]);

  useEffect(() => {
    applyChartDataToChart(chartRef.current, candleSeriesRef.current, volumeSeriesRef.current, chartData);
  }, [chartData]);

  if (!rows.length) {
    return null;
  }
  const labels =
    locale === "zh" ? { candles: "K 线", volume: "成交量" } : { candles: "Candles", volume: "Volume" };

  return (
    <div
      className="flex h-full min-h-0 flex-col rounded-lg border border-border-subtle bg-bg-surface-muted/40 p-3"
      data-testid="ohlcv-candlestick-chart"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="font-label-caps text-text-secondary">{labels.candles}</span>
        <span className="font-label-caps text-info">{labels.volume}</span>
      </div>
      {/* flex-1 + min-h-0 lets this host absorb all remaining height; the
          ResizeObserver above feeds that pixel height into lightweight-charts. */}
      <div
        ref={chartHostRef}
        className="min-h-[240px] flex-1"
        style={fixedHeight ? { height: fixedHeight } : undefined}
      />
    </div>
  );
}

type CandlestickChartData = ReturnType<typeof normalizeRows>;
type CandlestickTheme = Pick<
  ChartTheme,
  "background" | "text" | "grid" | "border" | "up" | "down" | "volumeUp" | "volumeDown"
>;

function applyThemeToChart(
  chart: IChartApi | null,
  candleSeries: ISeriesApi<"Candlestick"> | null,
  volumeSeries: ISeriesApi<"Histogram"> | null,
  theme: CandlestickTheme,
) {
  chart?.applyOptions({
    layout: {
      background: { color: theme.background },
      textColor: theme.text,
    },
    grid: {
      vertLines: { color: theme.grid },
      horzLines: { color: theme.grid },
    },
    rightPriceScale: {
      borderColor: theme.border,
    },
    timeScale: {
      borderColor: theme.border,
    },
  });
  candleSeries?.applyOptions({
    upColor: theme.up,
    downColor: theme.down,
    borderUpColor: theme.up,
    borderDownColor: theme.down,
    wickUpColor: theme.up,
    wickDownColor: theme.down,
  });
  volumeSeries?.applyOptions({
    color: theme.volumeUp,
  });
}

function applyChartDataToChart(
  chart: IChartApi | null,
  candleSeries: ISeriesApi<"Candlestick"> | null,
  volumeSeries: ISeriesApi<"Histogram"> | null,
  chartData: CandlestickChartData,
) {
  // setData asserts on unsorted/duplicate times; normalizeRows guarantees
  // ordering, but guard anyway so a data edge case can never blank the app.
  try {
    chart?.timeScale().applyOptions({ timeVisible: chartData.intraday });
    candleSeries?.setData(chartData.candles);
    volumeSeries?.setData(chartData.volume);
    chart?.timeScale().fitContent();
  } catch (error) {
    console.error("CandlestickChart setData failed", error);
  }
}

function normalizeRows(rows: OhlcvRow[], volumeUp: string, volumeDown: string) {
  // Daily bars can use the date string; intraday bars MUST use epoch seconds,
  // otherwise multiple bars of one day collapse onto the same time key and
  // lightweight-charts throws ("data must be asc ordered by time").
  const intraday = isIntraday(rows);
  const entries = rows
    .map((row) => {
      const epoch = Date.parse(row.timestamp);
      if (!Number.isFinite(epoch)) {
        return null;
      }
      const time: Time = intraday
        ? (Math.floor(epoch / 1000) as Time)
        : (row.timestamp.slice(0, 10) as Time);
      return { row, epoch, time };
    })
    .filter((entry): entry is { row: OhlcvRow; epoch: number; time: Time } => entry !== null)
    .sort((a, b) => a.epoch - b.epoch);

  // Drop duplicate time keys (keep the last occurrence).
  const deduped: typeof entries = [];
  for (const entry of entries) {
    const prev = deduped[deduped.length - 1];
    if (prev && prev.time === entry.time) {
      deduped[deduped.length - 1] = entry;
    } else {
      deduped.push(entry);
    }
  }

  const candles = deduped.map(({ row, time }) => ({
    time,
    open: row.open,
    high: row.high,
    low: row.low,
    close: row.close,
  }));
  const volume = deduped.map(({ row, time }) => ({
    time,
    value: row.volume,
    color: row.close >= row.open ? volumeUp : volumeDown,
  }));
  return { candles, volume, intraday };
}

function isIntraday(rows: OhlcvRow[]) {
  const seenDates = new Set<string>();
  for (const row of rows) {
    const date = row.timestamp.slice(0, 10);
    if (seenDates.has(date)) {
      return true;
    }
    seenDates.add(date);
  }
  return false;
}
