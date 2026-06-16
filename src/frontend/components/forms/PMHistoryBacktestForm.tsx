'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import Image from "next/image";
import { useState } from "react";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type {
  PredictionMarketCollectResponse,
  PredictionMarketTimeseriesBacktestRunResponse,
} from "@/lib/api";
import { API_BASE_URL, ApiClientError, apiPost } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

const fieldLabel = "flex flex-col gap-1 font-body-sm text-text-primary";
const selectClass =
  "rounded-lg border border-border-subtle bg-bg-surface px-3 py-2 text-text-primary";
const inputClass =
  "rounded-lg border border-border-subtle bg-bg-surface px-2 py-2 font-data-mono text-text-primary";

const copy = {
  en: {
    sectionTitle: "Historical Snapshot Replay",
    sectionIntro:
      "Read-only history collection and simulated replay only. No real fills, no real trading, no signing, no account custody.",
    collectHistory: "Collect History",
    provider: "Provider",
    polymarketReadOnly: "polymarket read-only",
    polymarketHistory: "polymarket history",
    cacheMode: "Cache mode",
    durationS: "Duration s",
    intervalS: "Interval s",
    auto: "auto",
    markets: "Markets",
    collecting: "Collecting...",
    collectSnapshots: "Collect snapshots",
    latestCollection: "Latest collection",
    collectToast: "Historical snapshot collection finished",
    timeSeriesTitle: "Time-Series Quasi-Backtest",
    timeSeriesWarning:
      "Simulated snapshot replay. No real fills. No live execution.",
    startTime: "Start time",
    endTime: "End time",
    optional: "optional",
    yesNoScanner: "yes/no scanner",
    completeSetScanner: "complete-set scanner",
    minEdge: "Min edge bps",
    capitalLimit: "Capital limit",
    maxLegs: "Max legs",
    maxMarkets: "Max markets",
    feeBps: "Fee bps",
    sizeMultiplier: "Size multiplier",
    replaying: "Replaying...",
    runReplay: "Run historical replay",
    backtestToast: "Historical quasi-backtest finished",
    snapshots: "Snapshots",
    opportunities: "Opportunities",
    simulatedTrades: "Simulated trades",
    estimatedProfit: "Estimated profit",
    openReport: "Open report",
  },
  zh: {
    sectionTitle: "历史快照回放",
    sectionIntro:
      "仅进行只读历史采集与模拟回放。无真实成交、无实盘交易、不签名、无账户托管。",
    collectHistory: "采集历史",
    provider: "数据源",
    polymarketReadOnly: "polymarket 只读",
    polymarketHistory: "polymarket 历史",
    cacheMode: "缓存模式",
    durationS: "时长（秒）",
    intervalS: "间隔（秒）",
    auto: "自动",
    markets: "市场数",
    collecting: "采集中…",
    collectSnapshots: "采集快照",
    latestCollection: "最新采集",
    collectToast: "历史快照采集已完成",
    timeSeriesTitle: "时间序列准回测",
    timeSeriesWarning: "模拟快照回放。无真实成交。无实盘执行。",
    startTime: "开始时间",
    endTime: "结束时间",
    optional: "可选",
    yesNoScanner: "yes/no 扫描器",
    completeSetScanner: "完整集扫描器",
    minEdge: "最小价差 (bps)",
    capitalLimit: "资金上限",
    maxLegs: "最大腿数",
    maxMarkets: "最大市场数",
    feeBps: "费用 (bps)",
    sizeMultiplier: "仓位倍数",
    replaying: "回放中…",
    runReplay: "运行历史回放",
    backtestToast: "历史准回测已完成",
    snapshots: "快照数",
    opportunities: "机会数",
    simulatedTrades: "模拟交易数",
    estimatedProfit: "预计收益",
    openReport: "打开报告",
  },
} as const;

const collectSchema = z.object({
  provider: z.enum(["sample", "polymarket"]),
  cache_mode: z.enum(["prefer_cache", "refresh", "network_only"]),
  duration_seconds: z.coerce.number().nonnegative(),
  interval_seconds: z.string().trim(),
  limit: z.coerce.number().int().positive(),
});

const backtestSchema = z.object({
  provider: z.enum(["sample", "polymarket"]),
  start_time: z.string().trim(),
  end_time: z.string().trim(),
  use_yes_no: z.boolean(),
  use_complete_set: z.boolean(),
  min_edge_bps: z.coerce.number().nonnegative(),
  capital_limit: z.coerce.number().positive(),
  max_legs: z.coerce.number().int().positive(),
  max_markets: z.coerce.number().int().positive(),
  fee_bps: z.coerce.number().nonnegative(),
  display_size_multiplier: z.coerce.number().positive(),
}).refine((values) => values.use_yes_no || values.use_complete_set, {
  message: "Select at least one scanner",
  path: ["use_yes_no"],
});

type CollectValues = z.infer<typeof collectSchema>;
type BacktestValues = z.infer<typeof backtestSchema>;

export function PMHistoryBacktestForm({ locale = "en" }: { locale?: "en" | "zh" }) {
  const text = copy[locale];
  const isHydrated = useIsHydrated();
  const [collectResult, setCollectResult] = useState<PredictionMarketCollectResponse | null>(
    null,
  );
  const [backtestResult, setBacktestResult] =
    useState<PredictionMarketTimeseriesBacktestRunResponse | null>(null);

  const collectForm = useForm<CollectValues>({
    resolver: zodResolver(collectSchema),
    defaultValues: {
      provider: "polymarket",
      cache_mode: "prefer_cache",
      duration_seconds: 0,
      interval_seconds: "",
      limit: 10,
    },
  });

  const backtestForm = useForm<BacktestValues>({
    resolver: zodResolver(backtestSchema),
    defaultValues: {
      provider: "polymarket",
      start_time: "",
      end_time: "",
      use_yes_no: true,
      use_complete_set: true,
      min_edge_bps: 200,
      capital_limit: 1000,
      max_legs: 3,
      max_markets: 50,
      fee_bps: 0,
      display_size_multiplier: 1,
    },
  });

  const collectMutation = useMutation({
    mutationFn: (values: CollectValues) =>
      apiPost<PredictionMarketCollectResponse>("/api/prediction-market/collect", {
        provider: values.provider,
        cache_mode: values.cache_mode,
        duration_seconds: values.duration_seconds,
        interval_seconds: values.interval_seconds ? Number(values.interval_seconds) : null,
        limit: values.limit,
        polymarket_api_key: null,
      }),
    onSuccess: (payload) => {
      setCollectResult(payload);
      if (payload.first_timestamp) {
        backtestForm.setValue("start_time", payload.first_timestamp);
      }
      if (payload.last_timestamp) {
        backtestForm.setValue("end_time", payload.last_timestamp);
      }
      backtestForm.setValue("provider", payload.provider === "polymarket" ? "polymarket" : "sample");
      toast.success(text.collectToast);
    },
  });

  const backtestMutation = useMutation({
    mutationFn: (values: BacktestValues) =>
      apiPost<PredictionMarketTimeseriesBacktestRunResponse>(
        "/api/prediction-market/timeseries-backtest",
        {
          provider: values.provider,
          start_time: values.start_time || null,
          end_time: values.end_time || null,
          scanners: [
            values.use_yes_no ? "yes_no_arbitrage" : null,
            values.use_complete_set ? "outcome_set_consistency" : null,
          ].filter(Boolean),
          min_edge_bps: values.min_edge_bps,
          capital_limit: values.capital_limit,
          max_legs: values.max_legs,
          max_markets: values.max_markets,
          fee_bps: values.fee_bps,
          display_size_multiplier: values.display_size_multiplier,
          polymarket_api_key: null,
        },
      ),
    onSuccess: (payload) => {
      setBacktestResult(payload);
      toast.success(text.backtestToast);
    },
  });

  const collectError =
    collectMutation.error instanceof ApiClientError ? collectMutation.error.message : undefined;
  const backtestError =
    backtestMutation.error instanceof ApiClientError ? backtestMutation.error.message : undefined;

  return (
    <section className="rounded-lg border border-border-subtle bg-bg-surface p-4">
      <div className="mb-4">
        <h2 className="font-headline-lg text-text-primary">{text.sectionTitle}</h2>
        <p className="mt-1 font-body-sm text-text-secondary">
          {text.sectionIntro}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <form
          className="rounded-lg border border-border-subtle bg-bg-surface-muted p-4"
          onSubmit={(event) => event.preventDefault()}
        >
          <h3 className="font-label-caps text-text-primary">{text.collectHistory}</h3>
          <div className="mt-3 grid grid-cols-1 gap-3">
            <label className={fieldLabel}>
              {text.provider}
              <select
                className={selectClass}
                {...collectForm.register("provider")}
              >
                <option value="polymarket">
                  {text.polymarketReadOnly}
                </option>
                <option value="sample">
                  sample
                </option>
              </select>
            </label>
            <label className={fieldLabel}>
              {text.cacheMode}
              <select
                className={selectClass}
                {...collectForm.register("cache_mode")}
              >
                <option value="prefer_cache">
                  prefer_cache
                </option>
                <option value="refresh">
                  refresh
                </option>
                <option value="network_only">
                  network_only
                </option>
              </select>
            </label>
            <div className="grid grid-cols-3 gap-2">
              <label className={fieldLabel}>
                {text.durationS}
                <input
                  className={inputClass}
                  type="number"
                  {...collectForm.register("duration_seconds", { valueAsNumber: true })}
                />
              </label>
              <label className={fieldLabel}>
                {text.intervalS}
                <input
                  className={inputClass}
                  placeholder={text.auto}
                  {...collectForm.register("interval_seconds")}
                />
              </label>
              <label className={fieldLabel}>
                {text.markets}
                <input
                  className={inputClass}
                  type="number"
                  {...collectForm.register("limit", { valueAsNumber: true })}
                />
              </label>
            </div>
          </div>
          {collectError ? <p className="mt-3 font-body-sm text-danger">{collectError}</p> : null}
          <button
            className="mt-4 rounded-lg border border-border-subtle px-4 py-2 font-body-sm text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!isHydrated || collectMutation.isPending}
            onClick={() => void collectForm.handleSubmit((values) => collectMutation.mutate(values))()}
            type="button"
          >
            {collectMutation.isPending ? text.collecting : text.collectSnapshots}
          </button>

          {collectResult ? (
            <div className="mt-4 rounded-lg border border-border-subtle bg-bg-surface p-3">
              <div className="font-body-sm text-text-secondary">{text.latestCollection}</div>
              <div className="mt-2 font-data-mono text-xs text-text-primary">
                records={collectResult.snapshot_record_count} markets={collectResult.market_count}
              </div>
              <div className="mt-1 break-all font-data-mono text-[10px] text-text-secondary">
                {collectResult.history_dir}
              </div>
            </div>
          ) : null}
        </form>

        <form
          className="rounded-lg border border-border-subtle bg-bg-surface-muted p-4"
          onSubmit={(event) => event.preventDefault()}
        >
          <h3 className="font-label-caps text-text-primary">{text.timeSeriesTitle}</h3>
          <p className="mt-2 font-body-sm text-warning">
            {text.timeSeriesWarning}
          </p>
          <div className="mt-3 grid grid-cols-1 gap-3">
            <label className={fieldLabel}>
              {text.provider}
              <select
                className={selectClass}
                {...backtestForm.register("provider")}
              >
                <option value="polymarket">
                  {text.polymarketHistory}
                </option>
                <option value="sample">
                  sample
                </option>
              </select>
            </label>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              <label className={fieldLabel}>
                {text.startTime}
                <input
                  className={inputClass}
                  placeholder={text.optional}
                  {...backtestForm.register("start_time")}
                />
              </label>
              <label className={fieldLabel}>
                {text.endTime}
                <input
                  className={inputClass}
                  placeholder={text.optional}
                  {...backtestForm.register("end_time")}
                />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-2 font-body-sm text-text-primary">
              <label className="flex items-center gap-2">
                <input type="checkbox" {...backtestForm.register("use_yes_no")} />
                {text.yesNoScanner}
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" {...backtestForm.register("use_complete_set")} />
                {text.completeSetScanner}
              </label>
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              <NumberField label={text.minEdge} register={backtestForm.register("min_edge_bps", { valueAsNumber: true })} />
              <NumberField label={text.capitalLimit} register={backtestForm.register("capital_limit", { valueAsNumber: true })} />
              <NumberField label={text.maxLegs} register={backtestForm.register("max_legs", { valueAsNumber: true })} />
              <NumberField label={text.maxMarkets} register={backtestForm.register("max_markets", { valueAsNumber: true })} />
              <NumberField label={text.feeBps} register={backtestForm.register("fee_bps", { valueAsNumber: true })} />
              <NumberField
                label={text.sizeMultiplier}
                register={backtestForm.register("display_size_multiplier", { valueAsNumber: true })}
              />
            </div>
          </div>
          {backtestError ? <p className="mt-3 font-body-sm text-danger">{backtestError}</p> : null}
          <button
            className="mt-4 rounded-lg bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!isHydrated || backtestMutation.isPending}
            onClick={() => void backtestForm.handleSubmit((values) => backtestMutation.mutate(values))()}
            type="button"
          >
            {backtestMutation.isPending ? text.replaying : text.runReplay}
          </button>
        </form>
      </div>

      {backtestResult ? (
        <div className="mt-4 rounded-lg border border-border-subtle bg-bg-surface-muted p-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric label={text.snapshots} value={String(backtestResult.metrics.snapshot_count)} />
            <Metric
              label={text.opportunities}
              value={String(backtestResult.metrics.opportunity_count)}
            />
            <Metric
              label={text.simulatedTrades}
              value={String(backtestResult.metrics.simulated_trade_count)}
            />
            <Metric
              label={text.estimatedProfit}
              value={backtestResult.metrics.cumulative_estimated_profit.toFixed(2)}
            />
          </div>
          <a
            className="mt-4 inline-flex rounded-lg border border-border-subtle px-3 py-2 font-body-sm text-text-primary"
            href={`${API_BASE_URL}${backtestResult.report_url}`}
            rel="noreferrer"
            target="_blank"
          >
            {text.openReport}
          </a>
          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
            {backtestResult.chart_index.charts.map((chart) => (
              <figure
                key={chart.name}
                className="rounded-lg border border-border-subtle bg-bg-surface p-3"
              >
                <figcaption className="mb-2 font-body-sm text-text-secondary">
                  {chart.title}
                </figcaption>
                <Image
                  alt={chart.title}
                  className="w-full rounded-lg border border-border-subtle"
                  height={360}
                  src={`${API_BASE_URL}${chart.url}`}
                  unoptimized
                  width={640}
                />
              </figure>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface p-3">
      <div className="font-body-sm text-text-secondary">{label}</div>
      <div className="mt-1 font-data-mono text-lg text-text-primary">{value}</div>
    </div>
  );
}

function NumberField({
  label,
  register,
}: {
  label: string;
  register: UseFormRegisterReturn;
}) {
  return (
    <label className={fieldLabel}>
      {label}
      <input
        className={inputClass}
        type="number"
        {...register}
      />
    </label>
  );
}
