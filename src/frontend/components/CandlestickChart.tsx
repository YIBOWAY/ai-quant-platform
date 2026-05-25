'use client';

import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import type { OhlcvRow } from "@/lib/api";

type CandlestickChartProps = {
  rows: OhlcvRow[];
  height?: number;
};

export function CandlestickChart({ rows, height = 360 }: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const chartData = useMemo(() => normalizeRows(rows), [rows]);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) {
      return;
    }

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { color: "#101614" },
        textColor: "#94A3B8",
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.12)" },
        horzLines: { color: "rgba(148, 163, 184, 0.12)" },
      },
      rightPriceScale: {
        borderColor: "rgba(148, 163, 184, 0.22)",
      },
      timeScale: {
        borderColor: "rgba(148, 163, 184, 0.22)",
        timeVisible: false,
      },
      crosshair: {
        mode: 1,
      },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10C89B",
      downColor: "#EF4444",
      borderUpColor: "#10C89B",
      borderDownColor: "#EF4444",
      wickUpColor: "#10C89B",
      wickDownColor: "#EF4444",
    });
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "rgba(56, 189, 248, 0.42)",
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

    const resize = () => {
      const width = containerRef.current?.clientWidth ?? 0;
      if (width > 0) {
        chart.applyOptions({ width, height });
      }
    };
    resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, [height]);

  useEffect(() => {
    candleSeriesRef.current?.setData(chartData.candles);
    volumeSeriesRef.current?.setData(chartData.volume);
    chartRef.current?.timeScale().fitContent();
  }, [chartData]);

  if (!rows.length) {
    return null;
  }

  return (
    <div
      className="rounded border border-border-subtle bg-surface-muted p-3"
      data-testid="ohlcv-candlestick-chart"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="font-label-caps text-text-secondary">Candles</span>
        <span className="font-label-caps text-info">Volume</span>
      </div>
      <div ref={containerRef} style={{ height }} />
    </div>
  );
}

function normalizeRows(rows: OhlcvRow[]) {
  const candles = rows.map((row) => ({
    time: row.timestamp.slice(0, 10),
    open: row.open,
    high: row.high,
    low: row.low,
    close: row.close,
  }));
  const volume = rows.map((row) => ({
    time: row.timestamp.slice(0, 10),
    value: row.volume,
    color: row.close >= row.open ? "rgba(16, 200, 155, 0.36)" : "rgba(239, 68, 68, 0.36)",
  }));
  return { candles, volume };
}
