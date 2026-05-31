'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

type Locale = "en" | "zh";

const copy = {
  en: {
    symbols: "Symbols",
    start: "Start",
    end: "End",
    dataSource: "Data Source",
    lookback: "Lookback",
    topN: "Top N",
    initialCash: "Initial Cash",
    commissionBps: "Commission bps",
    slippageBps: "Slippage bps",
    running: "Running...",
    runBacktest: "Run Backtest",
    created: (id: string) => `Backtest created: ${id}`,
  },
  zh: {
    symbols: "标的",
    start: "开始日期",
    end: "结束日期",
    dataSource: "数据源",
    lookback: "回看窗口",
    topN: "Top N",
    initialCash: "初始资金",
    commissionBps: "佣金（基点）",
    slippageBps: "滑点（基点）",
    running: "运行中...",
    runBacktest: "运行回测",
    created: (id: string) => `回测已创建：${id}`,
  },
} as const;

const backtestSchema = z.object({
  symbols: z.string().min(1, "Enter at least one symbol"),
  start: z.string().min(1, "Start date is required"),
  end: z.string().min(1, "End date is required"),
  provider: z.enum(["sample", "futu", "tiingo"]),
  lookback: z.coerce.number().int().positive(),
  top_n: z.coerce.number().int().positive(),
  initial_cash: z.coerce.number().positive(),
  commission_bps: z.coerce.number().nonnegative(),
  slippage_bps: z.coerce.number().nonnegative(),
});

type BacktestFormValues = z.infer<typeof backtestSchema>;
export type BacktestFormInitialValues = Partial<BacktestFormValues>;

type BacktestRunResponse = {
  run_id: string;
};

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const DEFAULTS: BacktestFormValues = {
  symbols: "SPY,QQQ",
  start: "2024-01-02",
  end: "2024-02-15",
  provider: "futu",
  lookback: 5,
  top_n: 1,
  initial_cash: 100000,
  commission_bps: 1,
  slippage_bps: 5,
};

type BacktestFormProps = {
  initialValues?: BacktestFormInitialValues;
  locale?: Locale;
};

export function BacktestForm({ initialValues, locale = "en" }: BacktestFormProps) {
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const text = copy[locale];
  const defaults = { ...DEFAULTS, ...initialValues };
  const form = useForm<BacktestFormValues>({
    resolver: zodResolver(backtestSchema),
    defaultValues: defaults,
  });
  const mutation = useMutation({
    mutationFn: (values: BacktestFormValues) =>
      apiPost<BacktestRunResponse>("/api/backtests/run", {
        ...values,
        symbols: splitSymbols(values.symbols),
      }),
    onSuccess: (payload) => {
      toast.success(text.created(payload.run_id));
      router.refresh();
    },
  });

  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;

  const runBacktest = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <form className="flex flex-col gap-4" onSubmit={runBacktest}>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.symbols}
        <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" defaultValue={defaults.symbols} {...form.register("symbols")} />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.start}
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={defaults.start} type="date" {...form.register("start")} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.end}
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={defaults.end} type="date" {...form.register("end")} />
        </label>
      </div>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.dataSource}
        <select
          className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
          defaultValue={defaults.provider}
          {...form.register("provider")}
        >
          <option value="futu" style={optionStyle}>
            futu
          </option>
          <option value="sample" style={optionStyle}>
            sample
          </option>
          <option value="tiingo" style={optionStyle}>
            tiingo
          </option>
        </select>
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.lookback}
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={defaults.lookback} type="number" {...form.register("lookback", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.topN}
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={defaults.top_n} type="number" {...form.register("top_n", { valueAsNumber: true })} />
        </label>
      </div>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.initialCash}
        <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" defaultValue={defaults.initial_cash} type="number" {...form.register("initial_cash", { valueAsNumber: true })} />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.commissionBps}
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={defaults.commission_bps} type="number" {...form.register("commission_bps", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.slippageBps}
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={defaults.slippage_bps} type="number" {...form.register("slippage_bps", { valueAsNumber: true })} />
        </label>
      </div>
      {error ? <p className="font-body-sm text-danger">{error}</p> : null}
      <button
        className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!isHydrated || mutation.isPending}
        type="submit"
      >
        {mutation.isPending ? text.running : text.runBacktest}
      </button>
    </form>
  );
}
