'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

const controlSchema = z.object({
  symbol: z.string().min(1),
  start: z.string().min(1),
  end: z.string().min(1),
  freq: z.enum(["1d", "1h", "30m", "15m", "5m", "1m"]),
  provider: z.enum(["sample", "futu", "tiingo"]),
});

type ControlValues = z.infer<typeof controlSchema>;

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const labels = {
  en: {
    ticker: "Ticker",
    start: "Start",
    end: "End",
    frequency: "Frequency",
    source: "Source",
    load: "Load",
    helper: "Type any US ticker, or pick a common ETF from suggestions.",
  },
  zh: {
    ticker: "标的代码",
    start: "开始日期",
    end: "结束日期",
    frequency: "周期",
    source: "数据源",
    load: "加载数据",
    helper: "可输入任意美股代码，也可从常用 ETF 建议中选择。",
  },
};

export function DataExplorerControls({
  symbols,
  initial,
  locale = "en",
}: {
  symbols: string[];
  initial: ControlValues;
  locale?: "en" | "zh";
}) {
  const router = useRouter();
  const text = labels[locale];
  const form = useForm<ControlValues>({
    resolver: zodResolver(controlSchema),
    defaultValues: initial,
  });

  return (
    <form
      className="flex flex-wrap items-end gap-4"
      onSubmit={form.handleSubmit((values) => {
        const params = new URLSearchParams({
          ...values,
          symbol: values.symbol.trim().toUpperCase(),
        });
        if (locale === "zh") {
          params.set("lang", "zh");
        }
        router.push(`/data-explorer?${params.toString()}`);
      })}
    >
      <label className="flex min-w-[160px] flex-col gap-1 font-body-sm text-text-primary">
        {text.ticker}
        <input
          className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono uppercase text-text-primary focus:border-info focus:ring-1 focus:ring-info"
          list="market-data-symbols"
          {...form.register("symbol")}
        />
        <datalist id="market-data-symbols">
          {symbols.map((symbol) => (
            <option key={symbol} value={symbol} />
          ))}
        </datalist>
        <span className="max-w-[220px] font-body-sm text-[11px] text-text-secondary">
          {text.helper}
        </span>
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.start}
        <input className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info" type="date" {...form.register("start")} />
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.end}
        <input className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info" type="date" {...form.register("end")} />
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.frequency}
        <select className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info" {...form.register("freq")}>
          <option style={optionStyle}>1d</option>
          <option style={optionStyle}>1h</option>
          <option style={optionStyle}>30m</option>
          <option style={optionStyle}>15m</option>
          <option style={optionStyle}>5m</option>
          <option style={optionStyle}>1m</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.source}
        <select className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info" {...form.register("provider")}>
          <option style={optionStyle}>futu</option>
          <option style={optionStyle}>sample</option>
          <option style={optionStyle}>tiingo</option>
        </select>
      </label>
      <button
        className="h-8 rounded bg-accent-success px-4 font-body-sm font-semibold text-on-primary"
        type="submit"
      >
        {text.load}
      </button>
    </form>
  );
}
