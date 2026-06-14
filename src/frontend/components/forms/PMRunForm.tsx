'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type { PredictionMarketBacktestResponse } from "@/lib/api";
import { ApiClientError, apiPost } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

const fieldLabel = "flex flex-col gap-1 font-body-sm text-text-primary";
const selectClass =
  "rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 text-text-primary";
const inputClass =
  "rounded-lg border border-border-subtle bg-bg-surface-muted px-3 py-2 font-data-mono text-text-primary";

const copy = {
  en: {
    title: "Read-Only Scanner",
    intro:
      "Polymarket mode fetches public market data only. This form never accepts or sends keys, custody access, signatures, or orders.",
    provider: "Provider",
    polymarketReadOnly: "polymarket read-only",
    cacheMode: "Cache mode",
    minEdge: "Min edge bps",
    maxCapitalPerLeg: "Max capital per leg",
    capitalLimit: "Capital limit",
    maxLegs: "Max legs",
    maxMarkets: "Max markets",
    feeBps: "Fee bps",
    running: "Running...",
    runScanner: "Run scanner",
    generateDryArb: "Generate dry arbitrage",
    runQuasiBacktest: "Run quasi-backtest",
    completedToast: "Prediction-market read-only workflow completed",
    opportunities: "Opportunities",
    triggerRate: "Trigger rate",
    totalEdge: "Total est. edge",
    cacheStatus: "Cache status",
    report: "Report",
  },
  zh: {
    title: "只读扫描器",
    intro:
      "Polymarket 模式仅获取公开市场数据。本表单从不接受或发送密钥、托管权限、签名或订单。",
    provider: "数据源",
    polymarketReadOnly: "polymarket 只读",
    cacheMode: "缓存模式",
    minEdge: "最小价差 (bps)",
    maxCapitalPerLeg: "每腿最大资金",
    capitalLimit: "资金上限",
    maxLegs: "最大腿数",
    maxMarkets: "最大市场数",
    feeBps: "费用 (bps)",
    running: "运行中…",
    runScanner: "运行扫描器",
    generateDryArb: "生成模拟套利",
    runQuasiBacktest: "运行准回测",
    completedToast: "预测市场只读流程已完成",
    opportunities: "机会数",
    triggerRate: "触发率",
    totalEdge: "预计总价差",
    cacheStatus: "缓存状态",
    report: "报告",
  },
} as const;

const pmSchema = z.object({
  provider: z.enum(["sample", "polymarket"]),
  cache_mode: z.enum(["prefer_cache", "refresh", "network_only"]),
  min_edge_bps: z.coerce.number().nonnegative(),
  max_capital_per_leg: z.coerce.number().nonnegative(),
  capital_limit: z.coerce.number().nonnegative(),
  max_legs: z.coerce.number().int().positive(),
  max_markets: z.coerce.number().int().positive(),
  fee_bps: z.coerce.number().nonnegative(),
});

type PMFormValues = z.infer<typeof pmSchema>;
type PMAction = "scan" | "dry-arbitrage" | "backtest";

export function PMRunForm({ locale = "en" }: { locale?: "en" | "zh" }) {
  const text = copy[locale];
  const [result, setResult] = useState<string>("");
  const [backtestResult, setBacktestResult] = useState<PredictionMarketBacktestResponse | null>(null);
  const isHydrated = useIsHydrated();
  const form = useForm<PMFormValues>({
    resolver: zodResolver(pmSchema),
    defaultValues: {
      provider: "polymarket",
      cache_mode: "prefer_cache",
      min_edge_bps: 200,
      max_capital_per_leg: 1000,
      capital_limit: 1000,
      max_legs: 3,
      max_markets: 20,
      fee_bps: 0,
    },
  });
  const mutation = useMutation({
    mutationFn: ({ action, values }: { action: PMAction; values: PMFormValues }) =>
      apiPost<Record<string, unknown>>(
        action === "scan"
          ? "/api/prediction-market/scan"
          : action === "backtest"
            ? "/api/prediction-market/backtest"
            : "/api/prediction-market/dry-arbitrage",
        {
          ...values,
          optimizer: "greedy",
          polymarket_api_key: null,
        },
      ),
    onSuccess: (payload) => {
      setResult(JSON.stringify(payload, null, 2));
      if ("metrics" in payload && "run_id" in payload) {
        setBacktestResult(payload as PredictionMarketBacktestResponse);
      }
      toast.success(text.completedToast);
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;

  function submit(action: PMAction) {
    return form.handleSubmit((values) => mutation.mutate({ action, values }))();
  }

  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface p-4">
      <h2 className="font-headline-lg text-text-primary">{text.title}</h2>
      <p className="mt-1 font-body-sm text-text-secondary">
        {text.intro}
      </p>
      <form className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3" onSubmit={(event) => event.preventDefault()}>
        <label className={fieldLabel}>
          {text.provider}
          <select className={selectClass} {...form.register("provider")}>
            <option value="polymarket">{text.polymarketReadOnly}</option>
            <option value="sample">sample</option>
          </select>
        </label>
        <label className={fieldLabel}>
          {text.cacheMode}
          <select className={selectClass} {...form.register("cache_mode")}>
            <option value="prefer_cache">prefer_cache</option>
            <option value="refresh">refresh</option>
            <option value="network_only">network_only</option>
          </select>
        </label>
        <label className={fieldLabel}>
          {text.minEdge}
          <input className={inputClass} type="number" {...form.register("min_edge_bps", { valueAsNumber: true })} />
        </label>
        <label className={fieldLabel}>
          {text.maxCapitalPerLeg}
          <input className={inputClass} type="number" {...form.register("max_capital_per_leg", { valueAsNumber: true })} />
        </label>
        <label className={fieldLabel}>
          {text.capitalLimit}
          <input className={inputClass} type="number" {...form.register("capital_limit", { valueAsNumber: true })} />
        </label>
        <label className={fieldLabel}>
          {text.maxLegs}
          <input className={inputClass} type="number" {...form.register("max_legs", { valueAsNumber: true })} />
        </label>
        <label className={fieldLabel}>
          {text.maxMarkets}
          <input className={inputClass} type="number" {...form.register("max_markets", { valueAsNumber: true })} />
        </label>
        <label className={fieldLabel}>
          {text.feeBps}
          <input className={inputClass} type="number" {...form.register("fee_bps", { valueAsNumber: true })} />
        </label>
      </form>
      {error ? <p className="mt-3 font-body-sm text-danger">{error}</p> : null}
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className="rounded-lg border border-border-subtle px-4 py-2 font-body-sm text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || mutation.isPending}
          onClick={() => submit("scan")}
          type="button"
        >
          {mutation.isPending ? text.running : text.runScanner}
        </button>
        <button
          className="rounded-lg border border-border-subtle px-4 py-2 font-body-sm text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || mutation.isPending}
          onClick={() => submit("dry-arbitrage")}
          type="button"
        >
          {mutation.isPending ? text.running : text.generateDryArb}
        </button>
        <button
          className="rounded-lg bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || mutation.isPending}
          onClick={() => submit("backtest")}
          type="button"
        >
          {mutation.isPending ? text.running : text.runQuasiBacktest}
        </button>
      </div>
      {backtestResult ? (
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
          <Metric label={text.opportunities} value={String(backtestResult.metrics.opportunity_count)} />
          <Metric label={text.triggerRate} value={`${(backtestResult.metrics.trigger_rate * 100).toFixed(2)}%`} />
          <Metric label={text.totalEdge} value={backtestResult.metrics.total_estimated_edge.toFixed(2)} />
          <Metric label={text.cacheStatus} value={backtestResult.cache_status ?? "live"} />
          <div className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3 md:col-span-3">
            <div className="font-body-sm text-text-secondary">{text.report}</div>
            <div className="mt-1 break-all font-data-mono text-xs text-text-primary">{backtestResult.report_path}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {backtestResult.chart_index.charts.map((chart) => (
                <span key={chart.name} className="rounded-lg border border-border-subtle px-2 py-1 font-data-mono text-[10px] text-text-secondary">
                  {chart.title}: {chart.path}
                </span>
              ))}
            </div>
          </div>
        </div>
      ) : null}
      {result ? (
        <pre className="mt-4 max-h-64 overflow-auto rounded-lg border border-border-subtle bg-bg-surface-muted p-3 font-code-sm text-text-primary">
          {result}
        </pre>
      ) : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface-muted p-3">
      <div className="font-body-sm text-text-secondary">{label}</div>
      <div className="mt-1 font-data-mono text-lg text-text-primary">{value}</div>
    </div>
  );
}
