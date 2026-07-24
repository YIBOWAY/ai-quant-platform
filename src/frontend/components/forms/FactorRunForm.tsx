'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type { FactorRunResponse } from "@/lib/api";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";
import { localizePath, type Locale } from "@/lib/locale";
import {
  TerminalToolbarButton,
  terminalInputClass,
  terminalInputCompactClass,
} from "@/components/ui/primitives";

const factorSchema = z.object({
  symbols: z.string().min(1, "Enter at least one symbol"),
  start: z.string().min(1, "Start date is required"),
  end: z.string().min(1, "End date is required"),
  provider: z.enum(["sample", "futu", "tiingo"]),
  lookback: z.coerce.number().int().positive(),
  quantiles: z.coerce.number().int().min(2),
});

type FactorFormValues = z.infer<typeof factorSchema>;

const copy = {
  en: {
    symbols: "Symbols",
    start: "Start",
    end: "End",
    dataSource: "Data Source",
    lookback: "Lookback",
    quantiles: "Quantiles",
    symbolHelp:
      "Use a comparison universe for scores and IC, for example NVDA,AAPL,MSFT,AMD,QQQ,SPY.",
    singleSymbolWarning:
      "One symbol can produce factor values, but scores and IC need peer tickers to avoid flat zero output.",
    running: "Running...",
    runFactor: "Run Factor",
    runCreated: (id: string) => `Factor run created: ${id}`,
  },
  zh: {
    symbols: "标的",
    start: "开始",
    end: "结束",
    dataSource: "数据源",
    lookback: "回看",
    quantiles: "分位",
    symbolHelp: "评分和 IC 需要一组可比较标的，例如 NVDA,AAPL,MSFT,AMD,QQQ,SPY。",
    singleSymbolWarning: "单个标的可以生成因子值，但评分和 IC 需要同类标的，否则容易显示为 0。",
    running: "运行中...",
    runFactor: "运行因子",
    runCreated: (id: string) => `已创建因子运行：${id}`,
  },
};

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function recentDefaults(): FactorFormValues {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 90);
  return {
    symbols: "SPY,QQQ,IWM,DIA",
    start: isoDate(start),
    end: isoDate(end),
    provider: "futu",
    lookback: 5,
    quantiles: 5,
  };
}

const inputClass = terminalInputClass;
const inputClassCompact = terminalInputCompactClass;

export function FactorRunForm({ locale = "en" }: { locale?: Locale }) {
  const text = copy[locale];
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const form = useForm<FactorFormValues>({
    resolver: zodResolver(factorSchema),
    defaultValues: recentDefaults(),
  });
  const mutation = useMutation({
    mutationFn: (values: FactorFormValues) =>
      apiPost<FactorRunResponse>("/api/factors/run", {
        ...values,
        symbols: splitSymbols(values.symbols),
      }),
    onSuccess: (payload) => {
      toast.success(text.runCreated(payload.run_id));
      router.push(localizePath(`/factor-lab/${payload.run_id}`, locale));
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  const watchedSymbols = useWatch({ control: form.control, name: "symbols" });
  const symbols = splitSymbols(watchedSymbols ?? "");
  const showSingleSymbolWarning = symbols.length === 1;

  const runFactor = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <form className="flex flex-col gap-4" onSubmit={runFactor}>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.symbols}
        <input className={inputClass} {...form.register("symbols")} />
        <span className="text-text-secondary">{text.symbolHelp}</span>
      </label>
      {showSingleSymbolWarning ? (
        <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
          {text.singleSymbolWarning}
        </div>
      ) : null}
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.start}
          <input className={inputClassCompact} type="date" {...form.register("start")} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.end}
          <input className={inputClassCompact} type="date" {...form.register("end")} />
        </label>
      </div>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.dataSource}
        <select className={inputClass} {...form.register("provider")}>
          <option value="futu">futu</option>
          <option value="sample">sample</option>
          <option value="tiingo">tiingo</option>
        </select>
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.lookback}
          <input className={inputClassCompact} type="number" {...form.register("lookback", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.quantiles}
          <input className={inputClassCompact} type="number" {...form.register("quantiles", { valueAsNumber: true })} />
        </label>
      </div>
      {error ? <p className="font-body-sm text-danger">{error}</p> : null}
      <TerminalToolbarButton
        className="h-9"
        disabled={!isHydrated || mutation.isPending}
        type="submit"
        tone="info"
      >
        {mutation.isPending ? text.running : text.runFactor}
      </TerminalToolbarButton>
    </form>
  );
}
