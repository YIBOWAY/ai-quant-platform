'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type { PaperRunResponse } from "@/lib/api";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";
import { FutuUnavailableHint, futuOptionLabel } from "./FutuProviderHint";

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
    killSwitchDisabled: "replay kill_switch disabled",
    readOnly: "READ ONLY",
    replayReady: "READY",
    running: "Running...",
    runPaperTrading: "Run Paper Trading",
    replayLocked: "Historical replay is locked while backend kill_switch is on.",
    created: (id: string) => `Paper run created: ${id}`,
    dialogTitle: "Kill switch is read-only here",
    dialogBody:
      "kill_switch is enabled on the backend; the API will reject runs that disable it. Edit `QS_KILL_SWITCH` in `.env` to change.",
    dialogTitleReady: "Replay can submit",
    dialogBodyReady:
      "Backend kill_switch is off for this local simulation. Historical replay will submit with replay kill_switch disabled.",
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
    killSwitchDisabled: "历史回放 kill_switch 已关闭",
    readOnly: "只读",
    replayReady: "可提交",
    running: "运行中...",
    runPaperTrading: "运行模拟交易",
    replayLocked: "后端 kill_switch 开启时，历史回放不会提交。",
    created: (id: string) => `模拟运行已创建：${id}`,
    dialogTitle: "终止开关在此为只读",
    dialogBody:
      "后端已启用 kill_switch；API 会拒绝任何尝试关闭它的运行。请修改 `.env` 中的 `QS_KILL_SWITCH` 进行调整。",
    dialogTitleReady: "历史回放可提交",
    dialogBodyReady: "后端 kill_switch 已为本地模拟关闭。历史回放会以 replay kill_switch 关闭状态提交。",
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

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function recentDefaults(): PaperFormValues {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 180);
  return {
    symbols: "SPY,QQQ",
    start: isoDate(start),
    end: isoDate(end),
    provider: "futu",
    initial_cash: 100000,
    lookback: 5,
    top_n: 1,
    max_fill_ratio_per_tick: 1,
  };
}

const inputClass =
  "rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 font-data-mono text-text-primary";
const inputClassCompact =
  "rounded-lg border border-border-subtle bg-bg-surface-muted px-2 py-2 font-data-mono text-text-primary";

export function PaperRunForm({
  locale = "en",
  futuReachable = true,
  replayKillSwitch = true,
}: {
  locale?: Locale;
  futuReachable?: boolean;
  replayKillSwitch?: boolean;
}) {
  const router = useRouter();
  const [dialogOpen, setDialogOpen] = useState(false);
  const isHydrated = useIsHydrated();
  const text = copy[locale];
  const form = useForm<PaperFormValues>({
    resolver: zodResolver(paperSchema),
    defaultValues: recentDefaults(),
  });
  const mutation = useMutation({
    mutationFn: (values: PaperFormValues) =>
      apiPost<PaperRunResponse>("/api/paper/run", {
        ...values,
        symbols: splitSymbols(values.symbols),
        enable_kill_switch: false,
      }),
    onSuccess: (payload) => {
      toast.success(text.created(payload.run_id));
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  const fieldError = (name: keyof PaperFormValues) => {
    const message = form.formState.errors[name]?.message;
    return message ? <span className="font-body-sm text-danger">{String(message)}</span> : null;
  };

  const runPaper = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <>
      <form className="flex flex-col gap-4" onSubmit={runPaper}>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.symbols}
          <input className={inputClass} {...form.register("symbols")} />
          {fieldError("symbols")}
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.start}
            <input className={inputClassCompact} type="date" {...form.register("start")} />
            {fieldError("start")}
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.end}
            <input className={inputClassCompact} type="date" {...form.register("end")} />
            {fieldError("end")}
          </label>
        </div>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.dataSource}
          <select className={inputClass} {...form.register("provider")}>
            <option value="futu" disabled={!futuReachable}>
              {futuOptionLabel(futuReachable, locale)}
            </option>
            <option value="sample">sample</option>
            <option value="tiingo">tiingo</option>
          </select>
          <FutuUnavailableHint reachable={futuReachable} locale={locale} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.initialCash}
          <input className={inputClass} type="number" {...form.register("initial_cash", { valueAsNumber: true })} />
          {fieldError("initial_cash")}
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.lookback}
            <input className={inputClassCompact} type="number" {...form.register("lookback", { valueAsNumber: true })} />
            {fieldError("lookback")}
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.topN}
            <input className={inputClassCompact} type="number" {...form.register("top_n", { valueAsNumber: true })} />
            {fieldError("top_n")}
          </label>
        </div>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.maxFillRatio}
          <input className={inputClass} max={1} min={0.01} step={0.01} type="number" {...form.register("max_fill_ratio_per_tick", { valueAsNumber: true })} />
          {fieldError("max_fill_ratio_per_tick")}
        </label>
        <button
          aria-pressed="true"
          className={`flex items-center justify-between rounded-lg border px-3 py-2 font-body-sm ${
            replayKillSwitch
              ? "border-warning/40 bg-warning/10 text-warning"
              : "border-accent-success/40 bg-accent-success/10 text-accent-success"
          }`}
          disabled={!isHydrated}
          onClick={() => setDialogOpen(true)}
          type="button"
        >
          {replayKillSwitch ? text.killSwitchEnabled : text.killSwitchDisabled}
          <span
            className={`rounded-full px-2 py-0.5 font-data-mono text-[10px] text-on-primary ${
              replayKillSwitch ? "bg-warning" : "bg-accent-success"
            }`}
          >
            {replayKillSwitch ? text.readOnly : text.replayReady}
          </span>
        </button>
        {replayKillSwitch ? (
          <p className="font-body-sm text-warning">{text.replayLocked}</p>
        ) : null}
        {error ? <p className="font-body-sm text-danger">{error}</p> : null}
        <button
          className="rounded-lg bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || mutation.isPending || replayKillSwitch}
          type="submit"
        >
          {mutation.isPending ? text.running : text.runPaperTrading}
        </button>
      </form>

      {dialogOpen ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-lg border border-warning/40 bg-bg-surface p-5 shadow-xl" role="alertdialog" aria-modal="true">
            <h3 className="font-headline-lg text-text-primary">
              {replayKillSwitch ? text.dialogTitle : text.dialogTitleReady}
            </h3>
            <p className="mt-3 font-body-sm text-text-secondary">
              {replayKillSwitch ? text.dialogBody : text.dialogBodyReady}
            </p>
            <button
              className="mt-5 rounded-lg border border-border-subtle px-4 py-2 font-body-sm text-text-primary"
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
