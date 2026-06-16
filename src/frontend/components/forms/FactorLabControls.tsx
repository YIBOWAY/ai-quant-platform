'use client';

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import type { UniverseDefinition } from "@/lib/api";
import { localizePath, type Locale } from "@/lib/locale";

const copy = {
  en: {
    provider: "Data Source",
    universe: "Universe",
    timingSymbol: "Timing Symbol",
    benchmark: "Benchmark",
    start: "Start",
    end: "End",
    lookback: "Lookback",
    forceRefresh: "Refresh cache",
    apply: "Apply",
    applying: "Applying...",
    hint: "Changes the read-only diagnostics query below. Futu = real data (requires OpenD). Refresh cache bypasses the saved dashboard once.",
  },
  zh: {
    provider: "数据源",
    universe: "股票池",
    timingSymbol: "择时标的",
    benchmark: "基准",
    start: "开始",
    end: "结束",
    lookback: "回看",
    forceRefresh: "刷新缓存",
    apply: "应用",
    applying: "应用中...",
    hint: "调整下方只读体检的查询。futu = 真实数据（需 OpenD 在线）。刷新缓存只会绕过一次已保存面板。",
  },
} as const;

const inputClass =
  "rounded-lg border border-border-subtle bg-bg-surface-muted px-2 py-1.5 font-data-mono text-xs text-text-primary";

export type FactorLabControlsInitial = {
  provider: string;
  universeId: string;
  symbol: string;
  benchmarkSymbol: string;
  start: string;
  end: string;
  lookback: number;
  forceRefresh: boolean;
};

export function FactorLabControls({
  locale,
  initial,
  universes,
}: {
  locale: Locale;
  initial: FactorLabControlsInitial;
  universes: UniverseDefinition[];
}) {
  const router = useRouter();
  const text = copy[locale];
  const [isPending, startTransition] = useTransition();
  const [provider, setProvider] = useState(initial.provider);
  const [universeId, setUniverseId] = useState(initial.universeId);
  const [symbol, setSymbol] = useState(initial.symbol);
  const [benchmark, setBenchmark] = useState(initial.benchmarkSymbol);
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [lookback, setLookback] = useState(String(initial.lookback));
  const [forceRefresh, setForceRefresh] = useState(initial.forceRefresh);

  const apply = () => {
    const parsedLookback = Number.parseInt(lookback, 10);
    const params = new URLSearchParams({
      provider,
      universe_id: universeId,
      symbol: symbol.trim().toUpperCase() || "QQQ",
      benchmark_symbol: benchmark.trim().toUpperCase() || symbol.trim().toUpperCase() || "QQQ",
      start: start.trim() || "2024-01-02",
      end: end.trim() || "2024-12-31",
      lookback: String(Number.isFinite(parsedLookback) && parsedLookback > 0 ? parsedLookback : 20),
    });
    if (forceRefresh) {
      params.set("force_refresh", "true");
    }
    startTransition(() => {
      router.push(localizePath(`/factor-lab?${params.toString()}`, locale));
    });
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.provider}
          <select className={inputClass} onChange={(e) => setProvider(e.target.value)} value={provider}>
            <option value="futu">futu</option>
            <option value="tiingo">tiingo</option>
            <option value="sample">sample</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.universe}
          <select className={inputClass} onChange={(e) => setUniverseId(e.target.value)} value={universeId}>
            {universes.length ? (
              universes.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))
            ) : (
              <option value={universeId}>{universeId}</option>
            )}
          </select>
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.timingSymbol}
          <input className={inputClass} onChange={(e) => setSymbol(e.target.value)} value={symbol} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.benchmark}
          <input className={inputClass} onChange={(e) => setBenchmark(e.target.value)} value={benchmark} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.start}
          <input className={inputClass} onChange={(e) => setStart(e.target.value)} type="date" value={start} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.end}
          <input className={inputClass} onChange={(e) => setEnd(e.target.value)} type="date" value={end} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.lookback}
          <input
            className={inputClass}
            min={1}
            onChange={(e) => setLookback(e.target.value)}
            type="number"
            value={lookback}
          />
        </label>
        <label className="flex items-center gap-2 pt-5 font-body-sm text-text-primary">
          <input
            checked={forceRefresh}
            className="h-4 w-4 rounded border-border-subtle bg-bg-surface-muted"
            onChange={(e) => setForceRefresh(e.target.checked)}
            type="checkbox"
          />
          {text.forceRefresh}
        </label>
      </div>
      <button
        className="rounded-lg border border-accent-success bg-accent-success/10 px-3 py-1.5 font-body-sm font-semibold text-accent-success transition-colors hover:bg-accent-success/20 disabled:opacity-50"
        disabled={isPending}
        onClick={apply}
        type="button"
      >
        {isPending ? text.applying : text.apply}
      </button>
      <p className="font-body-sm text-text-secondary">{text.hint}</p>
    </div>
  );
}
