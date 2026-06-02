'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type { FactorMetadata, StrategyMetadata, UniverseDefinition } from "@/lib/api";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";
import { localizePath } from "@/lib/locale";
import { FutuUnavailableHint, futuOptionLabel } from "./FutuProviderHint";

type Locale = "en" | "zh";

const copy = {
  en: {
    strategy: "Strategy",
    universe: "Universe",
    benchmark: "Benchmark",
    customSymbols: "Custom Symbols",
    start: "Start",
    end: "End",
    dataSource: "Data Source",
    lookback: "Lookback",
    topN: "Top N",
    factorMix: "Factor Mix",
    factorHelp: "Select registered backend factors and set blend weights.",
    weight: "Weight",
    initialCash: "Initial Cash",
    commissionBps: "Commission bps",
    slippageBps: "Slippage bps",
    customSymbolsHelp: "Optional override. Leave blank to use the selected universe.",
    universeHelp: "The selected universe defines the default comparison basket.",
    singleSymbolWarning:
      "A one-symbol run can stay flat because the strategy needs peer tickers to rank and buy positive signals.",
    running: "Running...",
    runBacktest: "Run Backtest",
    created: (id: string) => `Backtest created: ${id}`,
  },
  zh: {
    strategy: "策略",
    universe: "股票池",
    benchmark: "基准",
    customSymbols: "自定义标的",
    start: "开始日期",
    end: "结束日期",
    dataSource: "数据源",
    lookback: "回看窗口",
    topN: "Top N",
    factorMix: "因子组合",
    factorHelp: "选择后端已登记的因子，并设置组合权重。",
    weight: "权重",
    initialCash: "初始资金",
    commissionBps: "佣金 bps",
    slippageBps: "滑点 bps",
    customSymbolsHelp: "可选。留空时使用上面选择的股票池。",
    universeHelp: "股票池决定默认比较范围。",
    singleSymbolWarning:
      "单个标的可能不会产生交易，因为当前策略需要同类标的排序后才会买入正信号。",
    running: "运行中...",
    runBacktest: "运行回测",
    created: (id: string) => `回测已创建：${id}`,
  },
} as const;

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
});

type BacktestFormValues = z.infer<typeof backtestSchema>;
export type BacktestFormInitialValues = Partial<BacktestFormValues>;

type BacktestRunResponse = {
  run_id: string;
};

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const DEFAULTS: BacktestFormValues = {
  symbols: "",
  universe_id: "etf",
  strategy_id: "cross_sectional_top_n",
  benchmark_symbol: "SPY",
  factor_ids: ["momentum", "volatility", "liquidity"],
  weights: { momentum: 1, volatility: 0.5, liquidity: 0.5 },
  start: "2024-01-02",
  end: "2024-06-28",
  provider: "sample",
  lookback: 20,
  top_n: 3,
  initial_cash: 100000,
  commission_bps: 1,
  slippage_bps: 5,
};

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
    mutationFn: (values: BacktestFormValues) =>
      apiPost<BacktestRunResponse>("/api/backtests/run", {
        ...values,
        symbols: splitSymbols(values.symbols ?? ""),
        weights: selectedWeights(values.factor_ids, values.weights),
      }),
    onSuccess: (payload) => {
      toast.success(text.created(payload.run_id));
      router.push(localizePath(`/backtest/${payload.run_id}`, locale));
      router.refresh();
    },
  });

  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;
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
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.strategy}
        <select
          className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
          {...form.register("strategy_id")}
        >
          {activeStrategies.map((strategy) => (
            <option key={strategy.id} value={strategy.id} style={optionStyle}>
              {strategy.name}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.universe}
        <select
          className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
          {...form.register("universe_id")}
        >
          {activeUniverses.map((universe) => (
            <option key={universe.id} value={universe.id} style={optionStyle}>
              {universe.name}
            </option>
          ))}
        </select>
        <span className="text-text-secondary">{text.universeHelp}</span>
      </label>

      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.benchmark}
        <input
          className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
          {...form.register("benchmark_symbol")}
        />
      </label>

      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.customSymbols}
        <input
          className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
          {...form.register("symbols")}
        />
        <span className="text-text-secondary">{text.customSymbolsHelp}</span>
      </label>

      {showSingleSymbolWarning ? (
        <div className="rounded border border-warning/40 bg-warning/10 p-3 font-body-sm text-warning">
          {text.singleSymbolWarning}
        </div>
      ) : null}

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

      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        {text.dataSource}
        <select
          className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary"
          {...form.register("provider")}
        >
          <option value="futu" style={optionStyle} disabled={!futuReachable}>
            {futuOptionLabel(futuReachable, locale)}
          </option>
          <option value="sample" style={optionStyle}>sample</option>
          <option value="tiingo" style={optionStyle}>tiingo</option>
        </select>
        <FutuUnavailableHint reachable={futuReachable} locale={locale} />
      </label>

      <div className="flex flex-col gap-2 rounded border border-border-subtle bg-surface-muted p-3">
        <div>
          <div className="font-label-caps text-text-primary">{text.factorMix}</div>
          <div className="mt-1 font-body-sm text-text-secondary">{text.factorHelp}</div>
        </div>
        <div className="flex flex-col gap-2">
          {activeFactors.map((factor) => (
            <label
              className="grid grid-cols-[1fr_84px] items-center gap-2 font-body-sm text-text-primary"
              key={factor.factor_id}
            >
              <span className="inline-flex min-w-0 items-center gap-2">
                <input
                  type="checkbox"
                  value={factor.factor_id}
                  {...form.register("factor_ids")}
                />
                <span className="truncate">{factor.factor_name}</span>
              </span>
              <input
                aria-label={`${factor.factor_id} ${text.weight}`}
                className="rounded border border-border-subtle bg-base px-2 py-1 font-data-mono text-text-primary disabled:opacity-40"
                step="0.1"
                type="number"
                {...form.register(`weights.${factor.factor_id}`)}
                disabled={!watchedFactorIds.includes(factor.factor_id)}
              />
            </label>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.lookback}
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="number" {...form.register("lookback", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          {text.topN}
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="number" {...form.register("top_n", { valueAsNumber: true })} />
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
        {mutation.isPending ? text.running : text.runBacktest}
      </button>
    </form>
  );
}

function mergeDefaults(initialValues?: BacktestFormInitialValues): BacktestFormValues {
  return {
    ...DEFAULTS,
    ...initialValues,
    weights: {
      ...DEFAULTS.weights,
      ...(initialValues?.weights ?? {}),
    },
    factor_ids: initialValues?.factor_ids ?? DEFAULTS.factor_ids,
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
