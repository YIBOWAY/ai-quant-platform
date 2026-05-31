'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
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
    initialCash: "Initial Cash",
    lookback: "Lookback",
    topN: "Top N",
    maxFillRatio: "Max Fill Ratio",
    killSwitchEnabled: "kill_switch enabled",
    readOnly: "READ ONLY",
    running: "Running...",
    runPaperTrading: "Run Paper Trading",
    created: (id: string) => `Paper run created: ${id}`,
    dialogTitle: "Kill switch is read-only here",
    dialogBody:
      "kill_switch is enabled on the backend; the API will reject runs that disable it. Edit `QS_KILL_SWITCH` in `.env` to change.",
    close: "Close",
  },
  zh: {
    symbols: "标的",
    start: "开始日期",
    end: "结束日期",
    dataSource: "数据源",
    initialCash: "初始现金",
    lookback: "回看窗口",
    topN: "Top N",
    maxFillRatio: "最大成交比例",
    killSwitchEnabled: "kill_switch 已启用",
    readOnly: "只读",
    running: "运行中...",
    runPaperTrading: "运行模拟交易",
    created: (id: string) => `模拟运行已创建：${id}`,
    dialogTitle: "终止开关在此为只读",
    dialogBody:
      "后端已启用 kill_switch；API 会拒绝任何尝试关闭它的运行。请修改 `.env` 中的 `QS_KILL_SWITCH` 进行调整。",
    close: "关闭",
  },
} as const;

const paperSchema = z.object({
  symbols: z.string().min(1, "Enter at least one symbol"),
  start: z.string().min(1, "Start date is required"),
  end: z.string().min(1, "End date is required"),
  provider: z.enum(["sample", "futu", "tiingo"]),
  initial_cash: z.coerce.number().positive(),
  lookback: z.coerce.number().int().positive(),
  top_n: z.coerce.number().int().positive(),
  max_fill_ratio_per_tick: z.coerce.number().positive().max(1),
});

type PaperFormValues = z.infer<typeof paperSchema>;

type PaperRunResponse = {
  run_id: string;
};

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const DEFAULTS: PaperFormValues = {
  symbols: "SPY,QQQ",
  start: "2024-01-02",
  end: "2024-02-15",
  provider: "futu",
  initial_cash: 100000,
  lookback: 5,
  top_n: 1,
  max_fill_ratio_per_tick: 1,
};

export function PaperRunForm({ locale = "en" }: { locale?: Locale }) {
  const router = useRouter();
  const [dialogOpen, setDialogOpen] = useState(false);
  const isHydrated = useIsHydrated();
  const text = copy[locale];
  const form = useForm<PaperFormValues>({
    resolver: zodResolver(paperSchema),
    defaultValues: DEFAULTS,
  });
  const mutation = useMutation({
    mutationFn: (values: PaperFormValues) =>
      apiPost<PaperRunResponse>("/api/paper/run", {
        ...values,
        symbols: splitSymbols(values.symbols),
        enable_kill_switch: true,
      }),
    onSuccess: (payload) => {
      toast.success(text.created(payload.run_id));
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;

  const runPaper = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <>
      <form className="flex flex-col gap-4" onSubmit={runPaper}>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.symbols}
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.symbols} {...form.register("symbols")} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.start}
            <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.start} type="date" {...form.register("start")} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.end}
            <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.end} type="date" {...form.register("end")} />
          </label>
        </div>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.dataSource}
          <select
            className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
            defaultValue={DEFAULTS.provider}
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
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.initialCash}
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.initial_cash} type="number" {...form.register("initial_cash", { valueAsNumber: true })} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.lookback}
            <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.lookback} type="number" {...form.register("lookback", { valueAsNumber: true })} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.topN}
            <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.top_n} type="number" {...form.register("top_n", { valueAsNumber: true })} />
          </label>
        </div>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.maxFillRatio}
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.max_fill_ratio_per_tick} max={1} min={0.01} step={0.01} type="number" {...form.register("max_fill_ratio_per_tick", { valueAsNumber: true })} />
        </label>
        <button
          aria-pressed="true"
          className="flex items-center justify-between rounded border border-warning/40 bg-warning/10 px-3 py-2 font-body-sm text-warning"
          disabled={!isHydrated}
          onClick={() => setDialogOpen(true)}
          type="button"
        >
          {text.killSwitchEnabled}
          <span className="rounded-full bg-warning px-2 py-0.5 font-data-mono text-[10px] text-on-primary">
            {text.readOnly}
          </span>
        </button>
        {error ? <p className="font-body-sm text-danger">{error}</p> : null}
        <button
          className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || mutation.isPending}
          type="submit"
        >
          {mutation.isPending ? text.running : text.runPaperTrading}
        </button>
      </form>

      {dialogOpen ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded border border-warning/40 bg-bg-surface p-5 shadow-xl" role="alertdialog" aria-modal="true">
            <h3 className="font-headline-lg text-text-primary">{text.dialogTitle}</h3>
            <p className="mt-3 font-body-sm text-text-secondary">
              {text.dialogBody}
            </p>
            <button
              className="mt-5 rounded border border-border-subtle px-4 py-2 font-body-sm text-text-primary"
              onClick={() => setDialogOpen(false)}
              type="button"
            >
              {text.close}
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
