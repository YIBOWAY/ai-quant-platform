'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { TerminalToolbarButton, terminalFilterInputClass } from "@/components/ui/primitives";
import { localizePath } from "@/lib/locale";

const controlSchema = z
  .object({
    symbol: z.string().min(1),
    start: z.string().min(1),
    end: z.string().min(1),
    freq: z.enum(["1d", "1h", "30m", "15m", "5m", "1m"]),
    provider: z.enum(["sample", "futu", "tiingo"]),
  })
  .refine((v) => v.start <= v.end, { message: "range", path: ["end"] });

type ControlValues = z.infer<typeof controlSchema>;

const labels = {
  en: {
    ticker: "Ticker",
    start: "Start",
    end: "End",
    frequency: "Frequency",
    source: "Source",
    load: "Load",
    loading: "Loading...",
    symbolRequired: "Enter a ticker",
    rangeInvalid: "Start must be on or before end",
    intradayHint: "Intraday bars require the futu source (OpenD online).",
    presets: { "1M": 30, "3M": 90, "6M": 180, "1Y": 365 } as Record<string, number>,
  },
  zh: {
    ticker: "标的代码",
    start: "开始日期",
    end: "结束日期",
    frequency: "周期",
    source: "数据源",
    load: "加载数据",
    loading: "加载中...",
    symbolRequired: "请输入标的代码",
    rangeInvalid: "开始日期不能晚于结束日期",
    intradayHint: "盘中周期仅 futu 数据源支持（需 OpenD 在线）。",
    presets: { "1月": 30, "3月": 90, "6月": 180, "1年": 365 } as Record<string, number>,
  },
};

const fieldClass = terminalFilterInputClass;

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

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
  const [isPending, startTransition] = useTransition();
  const form = useForm<ControlValues>({
    resolver: zodResolver(controlSchema),
    defaultValues: initial,
  });
  const errors = form.formState.errors;
  const freq = useWatch({ control: form.control, name: "freq" });
  const provider = useWatch({ control: form.control, name: "provider" });
  // sample/tiingo only deliver daily bars; intraday over them would be
  // silently mislabeled, so constrain the combination in the UI.
  const intradayBlocked = freq !== "1d" && provider !== "futu";

  const applyPreset = (days: number) => {
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - days);
    form.setValue("start", isoDate(start), { shouldValidate: true });
    form.setValue("end", isoDate(end), { shouldValidate: true });
  };

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={form.handleSubmit((values) => {
        const params = new URLSearchParams({
          ...values,
          symbol: values.symbol.trim().toUpperCase(),
        });
        startTransition(() => {
          router.push(localizePath(`/data-explorer?${params.toString()}`, locale));
        });
      })}
    >
      <label className="flex min-w-[150px] flex-col gap-1 font-body-sm text-text-primary">
        {text.ticker}
        <input className={`${fieldClass} uppercase`} list="market-data-symbols" {...form.register("symbol")} />
        <datalist id="market-data-symbols">
          {symbols.map((symbol) => (
            <option key={symbol} value={symbol} />
          ))}
        </datalist>
        {errors.symbol ? <span className="text-danger">{text.symbolRequired}</span> : null}
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.start}
        <input className={fieldClass} type="date" {...form.register("start")} />
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.end}
        <input className={fieldClass} type="date" {...form.register("end")} />
        {errors.end ? <span className="text-danger">{text.rangeInvalid}</span> : null}
      </label>
      <div className="flex items-center gap-1 pb-1">
        {Object.entries(text.presets).map(([label, days]) => (
          <button
            className="rounded-lg border border-border-subtle px-2 py-1 font-data-mono text-[11px] text-text-secondary transition-colors hover:border-info/50 hover:text-info"
            key={label}
            onClick={() => applyPreset(days)}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.frequency}
        <select className={fieldClass} {...form.register("freq")}>
          <option>1d</option>
          <option>1h</option>
          <option>30m</option>
          <option>15m</option>
          <option>5m</option>
          <option>1m</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.source}
        <select className={fieldClass} {...form.register("provider")}>
          <option>futu</option>
          <option>sample</option>
          <option>tiingo</option>
        </select>
      </label>
      <TerminalToolbarButton
        className="h-8"
        disabled={isPending || intradayBlocked}
        type="submit"
        tone="info"
      >
        {isPending ? text.loading : text.load}
      </TerminalToolbarButton>
      {intradayBlocked ? (
        <span className="pb-1.5 font-body-sm text-warning">{text.intradayHint}</span>
      ) : null}
    </form>
  );
}
