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

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

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

export function PMRunForm() {
  const [result, setResult] = useState<string>("");
  const [backtestResult, setBacktestResult] = useState<PredictionMarketBacktestResponse | null>(null);
  const isHydrated = useIsHydrated();
  const form = useForm<PMFormValues>({
    resolver: zodResolver(pmSchema),
    defaultValues: {
      provider: "sample",
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
      toast.success("Prediction-market read-only workflow completed");
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;

  function submit(action: PMAction) {
    return form.handleSubmit((values) => mutation.mutate({ action, values }))();
  }

  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-4">
      <h2 className="font-headline-lg text-text-primary">Read-Only Scanner</h2>
      <p className="mt-1 font-body-sm text-text-secondary">
        Polymarket mode fetches public market data only. This form never accepts or sends keys, wallets, signatures, or orders.
      </p>
      <form className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3" onSubmit={(event) => event.preventDefault()}>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Provider
          <select className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary" {...form.register("provider")}>
            <option style={optionStyle} value="sample">sample</option>
            <option style={optionStyle} value="polymarket">polymarket read-only</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Cache mode
          <select className="rounded border border-border-subtle bg-surface-muted px-3 py-2 text-text-primary" {...form.register("cache_mode")}>
            <option style={optionStyle} value="prefer_cache">prefer_cache</option>
            <option style={optionStyle} value="refresh">refresh</option>
            <option style={optionStyle} value="network_only">network_only</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Min edge bps
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("min_edge_bps", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Max capital per leg
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("max_capital_per_leg", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Capital limit
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("capital_limit", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Max legs
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("max_legs", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Max markets
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("max_markets", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Fee bps
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("fee_bps", { valueAsNumber: true })} />
        </label>
      </form>
      {error ? <p className="mt-3 font-body-sm text-danger">{error}</p> : null}
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className="rounded border border-border-subtle px-4 py-2 font-body-sm text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || mutation.isPending}
          onClick={() => submit("scan")}
          type="button"
        >
          {mutation.isPending ? "Running..." : "Run scanner"}
        </button>
        <button
          className="rounded border border-border-subtle px-4 py-2 font-body-sm text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || mutation.isPending}
          onClick={() => submit("dry-arbitrage")}
          type="button"
        >
          {mutation.isPending ? "Running..." : "Generate dry arbitrage"}
        </button>
        <button
          className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || mutation.isPending}
          onClick={() => submit("backtest")}
          type="button"
        >
          {mutation.isPending ? "Running..." : "Run quasi-backtest"}
        </button>
      </div>
      {backtestResult ? (
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
          <Metric label="Opportunities" value={String(backtestResult.metrics.opportunity_count)} />
          <Metric label="Trigger rate" value={`${(backtestResult.metrics.trigger_rate * 100).toFixed(2)}%`} />
          <Metric label="Total est. edge" value={backtestResult.metrics.total_estimated_edge.toFixed(2)} />
          <Metric label="Cache status" value={backtestResult.cache_status ?? "live"} />
          <div className="rounded border border-border-subtle bg-surface-muted p-3 md:col-span-3">
            <div className="font-body-sm text-text-secondary">Report</div>
            <div className="mt-1 break-all font-data-mono text-xs text-text-primary">{backtestResult.report_path}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {backtestResult.chart_index.charts.map((chart) => (
                <span key={chart.name} className="rounded border border-border-subtle px-2 py-1 font-data-mono text-[10px] text-text-secondary">
                  {chart.title}: {chart.path}
                </span>
              ))}
            </div>
          </div>
        </div>
      ) : null}
      {result ? (
        <pre className="mt-4 max-h-64 overflow-auto rounded border border-border-subtle bg-surface-muted p-3 font-code-sm text-text-primary">
          {result}
        </pre>
      ) : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-subtle bg-surface-muted p-3">
      <div className="font-body-sm text-text-secondary">{label}</div>
      <div className="mt-1 font-data-mono text-lg text-text-primary">{value}</div>
    </div>
  );
}
