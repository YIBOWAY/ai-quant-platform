'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type { ExperimentRunResponse } from "@/lib/api";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import { Card, TerminalToolbarButton, terminalInputClass } from "@/components/ui/primitives";
import { buildExperimentRunPayload, type ExperimentProvider } from "@/lib/experimentRunPayload";
import { useIsHydrated } from "@/lib/hydration";
import type { Locale } from "@/lib/locale";

const experimentSchema = z.object({
  symbols: z.string().min(1, "Enter at least two symbols"),
  start: z.string().min(1, "Start date is required"),
  end: z.string().min(1, "End date is required"),
  provider: z.enum(["sample", "futu", "tiingo"]),
  lookbacks: z.string().min(1, "Enter at least one lookback"),
  top_ns: z.string().min(1, "Enter at least one Top N"),
  walk_forward_enabled: z.boolean(),
  walk_forward_train_bars: z.coerce.number().int().positive(),
  walk_forward_validation_bars: z.coerce.number().int().positive(),
  walk_forward_step_bars: z.coerce.number().int().positive(),
  initial_cash: z.coerce.number().nonnegative(),
  commission_bps: z.coerce.number().nonnegative(),
  slippage_bps: z.coerce.number().nonnegative(),
});

type ExperimentFormValues = z.infer<typeof experimentSchema>;

const copy = {
  en: {
    title: "Run Experiment",
    subtitle: "Parameter sweep using the selected data source for lookback and Top N comparison.",
    symbols: "Symbols",
    symbolsHelp: "Use at least two symbols so the factor ranks can compare a universe.",
    start: "Start",
    end: "End",
    dataSource: "Data Source",
    sourceHelp: "Futu requires OpenD; sample is for explicit offline testing only.",
    lookbacks: "Lookbacks",
    topNs: "Top N values",
    walkForward: "Walk-forward folds",
    walkForwardHelp: "Optional validation folds; keep off for the faster parameter sweep.",
    trainBars: "Train bars",
    validationBars: "Validation bars",
    stepBars: "Step bars",
    initialCash: "Initial Cash",
    commissionBps: "Commission bps",
    slippageBps: "Slippage bps",
    running: "Running...",
    run: "Run Experiment",
    created: (id: string, count: number) => `Experiment created: ${id} (${count} runs)`,
  },
  zh: {
    title: "运行实验",
    subtitle: "使用所选数据源做参数扫描，对比 lookback 和 Top N 设置。",
    symbols: "标的",
    symbolsHelp: "至少输入两个标的，这样因子排序才有可比较对象。",
    start: "开始",
    end: "结束",
    dataSource: "数据源",
    sourceHelp: "Futu 需要 OpenD 在线；sample 仅用于明确的离线测试。",
    lookbacks: "回看窗口",
    topNs: "Top N 数值",
    walkForward: "滚动验证折",
    walkForwardHelp: "可选验证折；关闭时参数扫描更快。",
    trainBars: "训练 bars",
    validationBars: "验证 bars",
    stepBars: "步长 bars",
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
  provider: "futu",
  lookbacks: "3,5,10",
  top_ns: "1,2",
  walk_forward_enabled: false,
  walk_forward_train_bars: 12,
  walk_forward_validation_bars: 5,
  walk_forward_step_bars: 5,
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
      apiPost<ExperimentRunResponse>("/api/experiments/run", buildExperimentRunPayload(values)),
    onSuccess: (payload) => {
      toast.success(text.created(payload.experiment_id, payload.run_count));
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  const submit = form.handleSubmit((values) => mutation.mutate(values));
  const selectedProvider = useWatch({ control: form.control, name: "provider" }) ?? "futu";
  const walkForwardEnabled =
    useWatch({ control: form.control, name: "walk_forward_enabled" }) ?? false;

  const fieldLabel = "flex flex-col gap-1 font-body-sm text-text-primary";
  const fieldInput = terminalInputClass;
  const fieldError = (name: keyof ExperimentFormValues) => {
    const message = form.formState.errors[name]?.message;
    return message ? <span className="font-body-sm text-danger">{String(message)}</span> : null;
  };

  return (
    <Card padded={false} className="p-4">
      <form onSubmit={submit}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="font-headline-lg text-text-primary">{text.title}</h3>
            <p className="mt-1 font-body-sm text-text-secondary">{text.subtitle}</p>
          </div>
          <span className="shrink-0 rounded-lg border border-warning/40 bg-warning/10 px-2 py-1 font-data-mono text-[10px] uppercase text-warning">
            {selectedProvider}
          </span>
        </div>
        <div className="mt-4 flex flex-col gap-3">
          <label className={fieldLabel}>
            {text.symbols}
            <input className={fieldInput} {...form.register("symbols")} />
            <span className="text-text-secondary">{text.symbolsHelp}</span>
            {fieldError("symbols")}
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className={fieldLabel}>
              {text.start}
              <input className={fieldInput} type="date" {...form.register("start")} />
              {fieldError("start")}
            </label>
            <label className={fieldLabel}>
              {text.end}
              <input className={fieldInput} type="date" {...form.register("end")} />
              {fieldError("end")}
            </label>
          </div>
          <label className={fieldLabel}>
            {text.dataSource}
            <select className={fieldInput} {...form.register("provider")}>
              {(["futu", "sample", "tiingo"] satisfies ExperimentProvider[]).map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
            <span className="text-text-secondary">{text.sourceHelp}</span>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className={fieldLabel}>
              {text.lookbacks}
              <input className={fieldInput} {...form.register("lookbacks")} />
              {fieldError("lookbacks")}
            </label>
            <label className={fieldLabel}>
              {text.topNs}
              <input className={fieldInput} {...form.register("top_ns")} />
              {fieldError("top_ns")}
            </label>
          </div>
          <div className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
            <label className="flex items-start gap-2 font-body-sm text-text-primary">
              <input
                className="mt-1"
                type="checkbox"
                {...form.register("walk_forward_enabled")}
              />
              <span>
                <span className="block font-semibold">{text.walkForward}</span>
                <span className="block text-text-secondary">{text.walkForwardHelp}</span>
              </span>
            </label>
            {walkForwardEnabled ? (
              <div className="mt-3 grid grid-cols-3 gap-2">
                <label className={fieldLabel}>
                  {text.trainBars}
                  <input
                    className={fieldInput}
                    min={1}
                    type="number"
                    {...form.register("walk_forward_train_bars", { valueAsNumber: true })}
                  />
                </label>
                <label className={fieldLabel}>
                  {text.validationBars}
                  <input
                    className={fieldInput}
                    min={1}
                    type="number"
                    {...form.register("walk_forward_validation_bars", { valueAsNumber: true })}
                  />
                </label>
                <label className={fieldLabel}>
                  {text.stepBars}
                  <input
                    className={fieldInput}
                    min={1}
                    type="number"
                    {...form.register("walk_forward_step_bars", { valueAsNumber: true })}
                  />
                </label>
              </div>
            ) : null}
          </div>
          <label className={fieldLabel}>
            {text.initialCash}
            <input className={fieldInput} type="number" {...form.register("initial_cash", { valueAsNumber: true })} />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className={fieldLabel}>
              {text.commissionBps}
              <input className={fieldInput} type="number" {...form.register("commission_bps", { valueAsNumber: true })} />
            </label>
            <label className={fieldLabel}>
              {text.slippageBps}
              <input className={fieldInput} type="number" {...form.register("slippage_bps", { valueAsNumber: true })} />
            </label>
          </div>
          {error ? <p className="font-body-sm text-danger">{error}</p> : null}
          <TerminalToolbarButton
            className="h-9"
            disabled={!isHydrated || mutation.isPending}
            type="submit"
            tone="info"
          >
            {mutation.isPending ? text.running : text.run}
          </TerminalToolbarButton>
        </div>
      </form>
    </Card>
  );
}
