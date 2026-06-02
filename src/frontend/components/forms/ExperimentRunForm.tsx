'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";
import type { Locale } from "@/lib/locale";

const experimentSchema = z.object({
  symbols: z.string().min(1, "Enter at least two symbols"),
  start: z.string().min(1, "Start date is required"),
  end: z.string().min(1, "End date is required"),
  lookbacks: z.string().min(1, "Enter at least one lookback"),
  top_ns: z.string().min(1, "Enter at least one Top N"),
  initial_cash: z.coerce.number().nonnegative(),
  commission_bps: z.coerce.number().nonnegative(),
  slippage_bps: z.coerce.number().nonnegative(),
});

type ExperimentFormValues = z.infer<typeof experimentSchema>;

type ExperimentRunResponse = {
  experiment_id: string;
  run_count: number;
  best_run_id?: string | null;
};

const copy = {
  en: {
    title: "Run Experiment",
    subtitle: "Sample-data parameter sweep for comparing lookback and Top N settings.",
    symbols: "Symbols",
    symbolsHelp: "Use at least two symbols so the factor ranks can compare a universe.",
    start: "Start",
    end: "End",
    lookbacks: "Lookbacks",
    topNs: "Top N values",
    initialCash: "Initial Cash",
    commissionBps: "Commission bps",
    slippageBps: "Slippage bps",
    running: "Running...",
    run: "Run Experiment",
    created: (id: string, count: number) => `Experiment created: ${id} (${count} runs)`,
  },
  zh: {
    title: "运行实验",
    subtitle: "用样本数据做参数扫描，对比 lookback 和 Top N 设置。",
    symbols: "标的",
    symbolsHelp: "至少输入两个标的，这样因子排序才有可比较对象。",
    start: "开始",
    end: "结束",
    lookbacks: "回看窗口",
    topNs: "Top N 数值",
    initialCash: "初始资金",
    commissionBps: "佣金（基点）",
    slippageBps: "滑点（基点）",
    running: "运行中...",
    run: "运行实验",
    created: (id: string, count: number) => `实验已创建：${id}（${count} 次运行）`,
  },
} as const;

const DEFAULTS: ExperimentFormValues = {
  symbols: "SPY,QQQ,IWM,DIA",
  start: "2024-01-02",
  end: "2024-02-15",
  lookbacks: "3,5,10",
  top_ns: "1,2",
  initial_cash: 100000,
  commission_bps: 1,
  slippage_bps: 5,
};

export function ExperimentRunForm({ locale = "en" }: { locale?: Locale }) {
  const text = copy[locale];
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const form = useForm<ExperimentFormValues>({
    resolver: zodResolver(experimentSchema),
    defaultValues: DEFAULTS,
  });
  const mutation = useMutation({
    mutationFn: (values: ExperimentFormValues) =>
      apiPost<ExperimentRunResponse>("/api/experiments/run", {
        symbols: splitSymbols(values.symbols),
        start: values.start,
        end: values.end,
        provider: "sample",
        lookbacks: splitPositiveInts(values.lookbacks),
        top_ns: splitPositiveInts(values.top_ns),
        initial_cash: values.initial_cash,
        commission_bps: values.commission_bps,
        slippage_bps: values.slippage_bps,
      }),
    onSuccess: (payload) => {
      toast.success(text.created(payload.experiment_id, payload.run_count));
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  const submit = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <form className="rounded border border-border-subtle bg-surface-container p-3" onSubmit={submit}>
      <div>
        <h3 className="font-headline-lg text-text-primary">{text.title}</h3>
        <p className="mt-1 font-body-sm text-text-secondary">{text.subtitle}</p>
      </div>
      <div className="mt-4 flex flex-col gap-3">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.symbols}
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" {...form.register("symbols")} />
          <span className="text-text-secondary">{text.symbolsHelp}</span>
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.start}
            <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="date" {...form.register("start")} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.end}
            <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="date" {...form.register("end")} />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.lookbacks}
            <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" {...form.register("lookbacks")} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.topNs}
            <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" {...form.register("top_ns")} />
          </label>
        </div>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.initialCash}
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("initial_cash", { valueAsNumber: true })} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.commissionBps}
            <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="number" {...form.register("commission_bps", { valueAsNumber: true })} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.slippageBps}
            <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="number" {...form.register("slippage_bps", { valueAsNumber: true })} />
          </label>
        </div>
        {error ? <p className="font-body-sm text-danger">{error}</p> : null}
        <button
          className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || mutation.isPending}
          type="submit"
        >
          {mutation.isPending ? text.running : text.run}
        </button>
      </div>
    </form>
  );
}

function splitPositiveInts(value: string) {
  return value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isInteger(item) && item > 0);
}
