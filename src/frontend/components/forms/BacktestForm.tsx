'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm, useWatch, type FieldError } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type {
  BacktestJobStateResponse,
  BacktestRunResponse,
  FactorMetadata,
  StrategyMetadata,
  UniverseDefinition,
} from "@/lib/api";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { isBacktestJobState, waitForBacktestJob } from "@/lib/backtestJobs";
import { useIsHydrated } from "@/lib/hydration";
import { localizePath } from "@/lib/locale";
import {
  TerminalToolbarButton,
  terminalInputClass,
  terminalInputCompactClass,
} from "@/components/ui/primitives";
import { FutuUnavailableHint, futuOptionLabel } from "./FutuProviderHint";

type Locale = "en" | "zh";

const copy = {
  en: {
    scopeGroup: "Strategy & Universe",
    windowGroup: "Window & Data",
    factorGroup: "Factor Mix",
    costGroup: "Capital & Costs",
    strategy: "Strategy",
    universe: "Universe",
    benchmark: "Benchmark",
    customSymbols: "Custom Symbols",
    start: "Start",
    end: "End",
    dataSource: "Data Source",
    lookback: "Lookback",
    topN: "Top N",
    factorHelp: "Select registered backend factors and set blend weights.",
    weight: "Weight",
    initialCash: "Initial Cash",
    commissionBps: "Commission bps",
    slippageBps: "Slippage bps",
    minOrderValue: "Min order value",
    wholeShareOrders: "Whole-share orders",
    wholeShareHelp: "Floor generated and cash-constrained fills to whole shares.",
    customSymbolsHelp: "Optional override. Leave blank to use the selected universe.",
    universeHelp: "The selected universe defines the default comparison basket.",
    singleSymbolWarning:
      "A one-symbol run can stay flat because the strategy needs peer tickers to rank and buy positive signals.",
    running: "Running...",
    runBacktest: "Run Backtest",
    created: (id: string) => `Backtest created: ${id}`,
    rebalanceFreq: "Rebalance",
    everyBar: "Every bar",
    weekly: "Weekly",
    monthly: "Monthly",
    maxWeight: "Max weight / name",
    capHelp: "Optional. 0–1 per-name weight cap; leave blank for no cap.",
  },
  zh: {
    scopeGroup: "策略与股票池",
    windowGroup: "区间与数据",
    factorGroup: "因子组合",
    costGroup: "资金与成本",
    strategy: "策略",
    universe: "股票池",
    benchmark: "基准",
    customSymbols: "自定义标的",
    start: "开始日期",
    end: "结束日期",
    dataSource: "数据源",
    lookback: "回看窗口",
    topN: "Top N",
    factorHelp: "选择后端已登记的因子，并设置组合权重。",
    weight: "权重",
    initialCash: "初始资金",
    commissionBps: "佣金 bps",
    slippageBps: "滑点 bps",
    minOrderValue: "最小订单金额",
    wholeShareOrders: "整股下单",
    wholeShareHelp: "生成订单和现金不足的部分成交都会向下取整到整股。",
    customSymbolsHelp: "可选。留空时使用上面选择的股票池。",
    universeHelp: "股票池决定默认比较范围。",
    singleSymbolWarning:
      "单个标的可能不会产生交易，因为当前策略需要同类标的排序后才会买入正信号。",
    running: "运行中...",
    runBacktest: "运行回测",
    created: (id: string) => `回测已创建：${id}`,
    rebalanceFreq: "再平衡频率",
    everyBar: "每根K线",
    weekly: "每周",
    monthly: "每月",
    maxWeight: "单标的上限",
    capHelp: "可选。0–1 之间的单标的权重上限；留空表示不限制。",
  },
} as const;

const capString = z
  .string()
  .optional()
  .refine(
    (value) => {
      if (value === undefined || value.trim() === "") {
        return true;
      }
      const parsed = Number(value);
      return Number.isFinite(parsed) && parsed > 0 && parsed <= 1;
    },
    { message: "Enter a weight between 0 and 1" },
  );

const backtestSchema = z.object({
  symbols: z.string().optional(),
  universe_id: z.string().min(1, "Select a universe"),
  strategy_id: z.string().min(1, "Select a strategy"),
  benchmark_symbol: z.string().min(1, "Enter a benchmark"),
  factor_ids: z.array(z.string()).min(1, "Select at least one factor"),
  weights: z.record(z.coerce.number()),
  start: z.string().min(1, "Start date is required"),
  end: z.string().min(1, "End date is required"),
  provider: z.enum(["sample", "futu", "tiingo"]),
  lookback: z.coerce.number().int().positive(),
  top_n: z.coerce.number().int().positive(),
  initial_cash: z.coerce.number().positive(),
  commission_bps: z.coerce.number().nonnegative(),
  slippage_bps: z.coerce.number().nonnegative(),
  min_order_value: z.coerce.number().nonnegative(),
  whole_share_orders: z.boolean(),
  rebalance_frequency: z.enum(["every_bar", "weekly", "monthly"]),
  max_weight_per_symbol: capString,
});

function parseCap(value: string | undefined): number | undefined {
  if (value === undefined || value.trim() === "") {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

type BacktestFormValues = z.infer<typeof backtestSchema>;
export type BacktestFormInitialValues = Partial<BacktestFormValues>;

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function recentDefaults(): BacktestFormValues {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 180);
  return {
    symbols: "",
    universe_id: "etf",
    strategy_id: "cross_sectional_top_n",
    benchmark_symbol: "SPY",
    factor_ids: ["momentum", "volatility", "liquidity"],
    weights: { momentum: 1, volatility: 0.5, liquidity: 0.5 },
    start: isoDate(start),
    end: isoDate(end),
    provider: "futu",
    lookback: 20,
    top_n: 3,
    initial_cash: 100000,
    commission_bps: 1,
    slippage_bps: 5,
    min_order_value: 0,
    whole_share_orders: false,
    rebalance_frequency: "every_bar",
  };
}

const inputClass = terminalInputClass;
const inputClassCompact = terminalInputCompactClass;
const fieldsetClass = "flex flex-col gap-3 rounded-lg border border-border-subtle p-3";
const legendClass = "px-1 font-label-caps text-text-secondary";

type BacktestFormProps = {
  initialValues?: BacktestFormInitialValues;
  locale?: Locale;
  factors?: FactorMetadata[];
  strategies?: StrategyMetadata[];
  universes?: UniverseDefinition[];
  futuReachable?: boolean;
};

export function BacktestForm({
  initialValues,
  locale = "en",
  factors = [],
  strategies = [],
  universes = [],
  futuReachable = true,
}: BacktestFormProps) {
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const text = copy[locale];
  const defaults = mergeDefaults(initialValues);
  const form = useForm<BacktestFormValues>({
    resolver: zodResolver(backtestSchema),
    defaultValues: defaults,
  });
  const mutation = useMutation({
    mutationFn: async (values: BacktestFormValues) => {
      const { max_weight_per_symbol, ...rest } = values;
      const body: Record<string, unknown> = {
        ...rest,
        symbols: splitSymbols(values.symbols ?? ""),
        weights: selectedWeights(values.factor_ids, values.weights),
      };
      const maxWeight = parseCap(max_weight_per_symbol);
      if (maxWeight !== undefined) {
        body.max_weight_per_symbol = maxWeight;
      }
      const payload = await apiPost<BacktestRunResponse | BacktestJobStateResponse>(
        "/api/backtests/run",
        body,
      );
      return isBacktestJobState(payload) ? waitForBacktestJob(payload) : payload;
    },
    onSuccess: (payload) => {
      toast.success(text.created(payload.run_id));
      router.push(localizePath(`/backtest/${payload.run_id}`, locale));
      router.refresh();
    },
  });

  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
  const errors = form.formState.errors;
  const watchedSymbols = useWatch({ control: form.control, name: "symbols" });
  const watchedFactorIds = useWatch({ control: form.control, name: "factor_ids" }) ?? [];
  const symbols = splitSymbols(watchedSymbols ?? "");
  const showSingleSymbolWarning = symbols.length === 1;
  const runnableStrategies = strategies.filter((strategy) => strategy.result_type === "backtest");
  const activeStrategies = runnableStrategies.length ? runnableStrategies : fallbackStrategies();
  const activeUniverses = universes.length ? universes : fallbackUniverses();
  const activeFactors = factors.length ? factors : fallbackFactors();

  const runBacktest = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <form className="flex flex-col gap-4" onSubmit={runBacktest}>
      <fieldset className={fieldsetClass}>
        <legend className={legendClass}>{text.scopeGroup}</legend>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.strategy}
          <select className={inputClass} {...form.register("strategy_id")}>
            {activeStrategies.map((strategy) => (
              <option key={strategy.id} value={strategy.id}>
                {strategy.name}
              </option>
            ))}
          </select>
          <FieldErrorText error={errors.strategy_id} />
        </label>

        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.universe}
          <select className={inputClass} {...form.register("universe_id")}>
            {activeUniverses.map((universe) => (
              <option key={universe.id} value={universe.id}>
                {universe.name}
              </option>
            ))}
          </select>
          <span className="text-text-secondary">{text.universeHelp}</span>
          <FieldErrorText error={errors.universe_id} />
        </label>

        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.benchmark}
          <input className={inputClass} {...form.register("benchmark_symbol")} />
          <FieldErrorText error={errors.benchmark_symbol} />
        </label>

        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.customSymbols}
          <input className={inputClass} {...form.register("symbols")} />
          <span className="text-text-secondary">{text.customSymbolsHelp}</span>
        </label>

        {showSingleSymbolWarning ? (
          <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
            {text.singleSymbolWarning}
          </div>
        ) : null}
      </fieldset>

      <fieldset className={fieldsetClass}>
        <legend className={legendClass}>{text.windowGroup}</legend>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.start}
            <input className={inputClassCompact} type="date" {...form.register("start")} />
            <FieldErrorText error={errors.start} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.end}
            <input className={inputClassCompact} type="date" {...form.register("end")} />
            <FieldErrorText error={errors.end} />
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

        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.lookback}
            <input
              className={inputClassCompact}
              type="number"
              {...form.register("lookback", { valueAsNumber: true })}
            />
            <FieldErrorText error={errors.lookback} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.topN}
            <input
              className={inputClassCompact}
              type="number"
              {...form.register("top_n", { valueAsNumber: true })}
            />
            <FieldErrorText error={errors.top_n} />
          </label>
        </div>
      </fieldset>

      <fieldset className={fieldsetClass}>
        <legend className={legendClass}>{text.factorGroup}</legend>
        <div className="font-body-sm text-text-secondary">{text.factorHelp}</div>
        <div className="flex flex-col gap-2">
          {activeFactors.map((factor) => (
            <label
              className="grid grid-cols-[1fr_84px] items-center gap-2 font-body-sm text-text-primary"
              key={factor.factor_id}
            >
              <span className="inline-flex min-w-0 items-center gap-2">
                <input type="checkbox" value={factor.factor_id} {...form.register("factor_ids")} />
                <span className="truncate">{factor.factor_name}</span>
              </span>
              <input
                aria-label={`${factor.factor_id} ${text.weight}`}
                className="rounded-lg border border-border-subtle bg-bg-base px-2 py-1 font-data-mono text-text-primary disabled:opacity-40"
                step="0.1"
                type="number"
                {...form.register(`weights.${factor.factor_id}`)}
                disabled={!watchedFactorIds.includes(factor.factor_id)}
              />
            </label>
          ))}
        </div>
        <FieldErrorText error={errors.factor_ids as FieldError | undefined} />
      </fieldset>

      <fieldset className={fieldsetClass}>
        <legend className={legendClass}>{text.costGroup}</legend>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.initialCash}
          <input
            className={inputClass}
            type="number"
            {...form.register("initial_cash", { valueAsNumber: true })}
          />
          <FieldErrorText error={errors.initial_cash} />
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.commissionBps}
            <input
              className={inputClassCompact}
              type="number"
              {...form.register("commission_bps", { valueAsNumber: true })}
            />
            <FieldErrorText error={errors.commission_bps} />
          </label>
          <label className="flex flex-col gap-1 font-body-sm text-text-primary">
            {text.slippageBps}
            <input
              className={inputClassCompact}
              type="number"
              {...form.register("slippage_bps", { valueAsNumber: true })}
            />
            <FieldErrorText error={errors.slippage_bps} />
          </label>
        </div>

        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.minOrderValue}
          <input
            className={inputClassCompact}
            type="number"
            {...form.register("min_order_value", { valueAsNumber: true })}
          />
          <FieldErrorText error={errors.min_order_value} />
        </label>

        <label className="flex items-start gap-2 font-body-sm text-text-primary">
          <input className="mt-1" type="checkbox" {...form.register("whole_share_orders")} />
          <span className="flex flex-col gap-1">
            <span>{text.wholeShareOrders}</span>
            <span className="text-text-secondary">{text.wholeShareHelp}</span>
          </span>
        </label>

        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.rebalanceFreq}
          <select className={inputClass} {...form.register("rebalance_frequency")}>
            <option value="every_bar">{text.everyBar}</option>
            <option value="weekly">{text.weekly}</option>
            <option value="monthly">{text.monthly}</option>
          </select>
        </label>

        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.maxWeight}
          <input
            className={inputClassCompact}
            type="number"
            step="0.05"
            placeholder="—"
            {...form.register("max_weight_per_symbol")}
          />
          <span className="text-text-secondary">{text.capHelp}</span>
          <FieldErrorText error={errors.max_weight_per_symbol} />
        </label>
      </fieldset>

      {error ? <p className="font-body-sm text-danger">{error}</p> : null}
      <TerminalToolbarButton
        className="h-9"
        disabled={!isHydrated || mutation.isPending}
        type="submit"
        tone="info"
      >
        {mutation.isPending ? text.running : text.runBacktest}
      </TerminalToolbarButton>
    </form>
  );
}

function FieldErrorText({ error }: { error?: FieldError }) {
  if (!error?.message) {
    return null;
  }
  return <span className="font-body-sm text-danger">{error.message}</span>;
}

function mergeDefaults(initialValues?: BacktestFormInitialValues): BacktestFormValues {
  const defaults = recentDefaults();
  return {
    ...defaults,
    ...initialValues,
    weights: {
      ...defaults.weights,
      ...(initialValues?.weights ?? {}),
    },
    factor_ids: initialValues?.factor_ids ?? defaults.factor_ids,
  };
}

function selectedWeights(factorIds: string[], weights: Record<string, number>) {
  return Object.fromEntries(
    factorIds.map((factorId) => [factorId, Number(weights[factorId] ?? 1)]),
  );
}

function fallbackFactors(): FactorMetadata[] {
  return [
    {
      factor_id: "momentum",
      factor_name: "Momentum",
      factor_version: "0.1.0",
      lookback: 20,
      direction: "higher_is_better",
      description: "",
    },
    {
      factor_id: "volatility",
      factor_name: "Volatility",
      factor_version: "0.1.0",
      lookback: 20,
      direction: "lower_is_better",
      description: "",
    },
    {
      factor_id: "liquidity",
      factor_name: "Liquidity",
      factor_version: "0.1.0",
      lookback: 20,
      direction: "higher_is_better",
      description: "",
    },
  ];
}

function fallbackStrategies(): StrategyMetadata[] {
  return [
    {
      id: "cross_sectional_top_n",
      name: "Cross-Sectional Top-N",
      description: "",
      paper_source: null,
      run_endpoint: "/api/backtests/run",
      result_type: "backtest",
      parameter_schema: { fields: {} },
      default_payload: {},
    },
  ];
}

function fallbackUniverses(): UniverseDefinition[] {
  return [
    {
      id: "etf",
      name: "ETF Core",
      description: "",
      symbols: ["SPY", "QQQ"],
      benchmark_symbol: "SPY",
    },
  ];
}
