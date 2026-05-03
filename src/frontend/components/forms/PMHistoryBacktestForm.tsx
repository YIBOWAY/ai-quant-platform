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
  PredictionMarketTimeseriesResponse,
} from "@/lib/api";
import { API_BASE_URL, ApiClientError, apiPost } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

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

export function PMHistoryBacktestForm() {
  const isHydrated = useIsHydrated();
  const [collectResult, setCollectResult] = useState<PredictionMarketCollectResponse | null>(
    null,
  );
  const [backtestResult, setBacktestResult] =
    useState<PredictionMarketTimeseriesResponse | null>(null);

  const collectForm = useForm<CollectValues>({
    resolver: zodResolver(collectSchema),
    defaultValues: {
      provider: "sample",
      cache_mode: "prefer_cache",
      duration_seconds: 0,
      interval_seconds: "",
      limit: 10,
    },
  });

  const backtestForm = useForm<BacktestValues>({
    resolver: zodResolver(backtestSchema),
    defaultValues: {
      provider: "sample",
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
      toast.success("Historical snapshot collection finished");
    },
  });

  const backtestMutation = useMutation({
    mutationFn: (values: BacktestValues) =>
      apiPost<PredictionMarketTimeseriesResponse>(
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
      toast.success("Historical quasi-backtest finished");
    },
  });

  const collectError =
    collectMutation.error instanceof ApiClientError ? collectMutation.error.message : undefined;
  const backtestError =
    backtestMutation.error instanceof ApiClientError ? backtestMutation.error.message : undefined;

  return (
    <section className="rounded border border-border-subtle bg-bg-surface p-4">
      <div className="mb-4">
        <h2 className="font-headline-lg text-text-primary">Historical Snapshot Replay</h2>
        <p className="mt-1 font-body-sm text-text-secondary">
          Read-only history collection and simulated replay only. No real fills, no real
          trading, no signing, no account custody.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <form
          className="rounded border border-border-subtle bg-surface-muted p-4"
          onSubmit={(event) => event.preventDefault()}
        >
          <h3 className="font-label-caps text-text-primary">Collect History</h3>
          <div className="mt-3 grid grid-cols-1 gap-3">
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              Provider
              <select
                className="rounded border border-border-subtle bg-bg-surface px-3 py-2 text-text-primary"
                {...collectForm.register("provider")}
              >
                <option style={optionStyle} value="sample">
                  sample
                </option>
                <option style={optionStyle} value="polymarket">
                  polymarket read-only
                </option>
              </select>
            </label>
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              Cache mode
              <select
                className="rounded border border-border-subtle bg-bg-surface px-3 py-2 text-text-primary"
                {...collectForm.register("cache_mode")}
              >
                <option style={optionStyle} value="prefer_cache">
                  prefer_cache
                </option>
                <option style={optionStyle} value="refresh">
                  refresh
                </option>
                <option style={optionStyle} value="network_only">
                  network_only
                </option>
              </select>
            </label>
            <div className="grid grid-cols-3 gap-2">
              <label className="flex flex-col gap-1 font-body-sm text-text-primary">
                Duration s
                <input
                  className="rounded border border-border-subtle bg-bg-surface px-2 py-2 font-data-mono text-text-primary"
                  type="number"
                  {...collectForm.register("duration_seconds", { valueAsNumber: true })}
                />
              </label>
              <label className="flex flex-col gap-1 font-body-sm text-text-primary">
                Interval s
                <input
                  className="rounded border border-border-subtle bg-bg-surface px-2 py-2 font-data-mono text-text-primary"
                  placeholder="auto"
                  {...collectForm.register("interval_seconds")}
                />
              </label>
              <label className="flex flex-col gap-1 font-body-sm text-text-primary">
                Markets
                <input
                  className="rounded border border-border-subtle bg-bg-surface px-2 py-2 font-data-mono text-text-primary"
                  type="number"
                  {...collectForm.register("limit", { valueAsNumber: true })}
                />
              </label>
            </div>
          </div>
          {collectError ? <p className="mt-3 font-body-sm text-danger">{collectError}</p> : null}
          <button
            className="mt-4 rounded border border-border-subtle px-4 py-2 font-body-sm text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!isHydrated || collectMutation.isPending}
            onClick={() => void collectForm.handleSubmit((values) => collectMutation.mutate(values))()}
            type="button"
          >
            {collectMutation.isPending ? "Collecting..." : "Collect snapshots"}
          </button>

          {collectResult ? (
            <div className="mt-4 rounded border border-border-subtle bg-bg-surface p-3">
              <div className="font-body-sm text-text-secondary">Latest collection</div>
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
          className="rounded border border-border-subtle bg-surface-muted p-4"
          onSubmit={(event) => event.preventDefault()}
        >
          <h3 className="font-label-caps text-text-primary">Time-Series Quasi-Backtest</h3>
          <p className="mt-2 font-body-sm text-warning">
            Simulated snapshot replay. No real fills. No live execution.
          </p>
          <div className="mt-3 grid grid-cols-1 gap-3">
            <label className="flex flex-col gap-1 font-body-sm text-text-primary">
              Provider
              <select
                className="rounded border border-border-subtle bg-bg-surface px-3 py-2 text-text-primary"
                {...backtestForm.register("provider")}
              >
                <option style={optionStyle} value="sample">
                  sample
                </option>
                <option style={optionStyle} value="polymarket">
                  polymarket history
                </option>
              </select>
            </label>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              <label className="flex flex-col gap-1 font-body-sm text-text-primary">
                Start time
                <input
                  className="rounded border border-border-subtle bg-bg-surface px-2 py-2 font-data-mono text-text-primary"
                  placeholder="optional"
                  {...backtestForm.register("start_time")}
                />
              </label>
              <label className="flex flex-col gap-1 font-body-sm text-text-primary">
                End time
                <input
                  className="rounded border border-border-subtle bg-bg-surface px-2 py-2 font-data-mono text-text-primary"
                  placeholder="optional"
                  {...backtestForm.register("end_time")}
                />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-2 font-body-sm text-text-primary">
              <label className="flex items-center gap-2">
                <input type="checkbox" {...backtestForm.register("use_yes_no")} />
                yes/no scanner
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" {...backtestForm.register("use_complete_set")} />
                complete-set scanner
              </label>
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              <NumberField label="Min edge bps" register={backtestForm.register("min_edge_bps", { valueAsNumber: true })} />
              <NumberField label="Capital limit" register={backtestForm.register("capital_limit", { valueAsNumber: true })} />
              <NumberField label="Max legs" register={backtestForm.register("max_legs", { valueAsNumber: true })} />
              <NumberField label="Max markets" register={backtestForm.register("max_markets", { valueAsNumber: true })} />
              <NumberField label="Fee bps" register={backtestForm.register("fee_bps", { valueAsNumber: true })} />
              <NumberField
                label="Size multiplier"
                register={backtestForm.register("display_size_multiplier", { valueAsNumber: true })}
              />
            </div>
          </div>
          {backtestError ? <p className="mt-3 font-body-sm text-danger">{backtestError}</p> : null}
          <button
            className="mt-4 rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!isHydrated || backtestMutation.isPending}
            onClick={() => void backtestForm.handleSubmit((values) => backtestMutation.mutate(values))()}
            type="button"
          >
            {backtestMutation.isPending ? "Replaying..." : "Run historical replay"}
          </button>
        </form>
      </div>

      {backtestResult ? (
        <div className="mt-4 rounded border border-border-subtle bg-surface-muted p-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric label="Snapshots" value={String(backtestResult.metrics.snapshot_count)} />
            <Metric
              label="Opportunities"
              value={String(backtestResult.metrics.opportunity_count)}
            />
            <Metric
              label="Simulated trades"
              value={String(backtestResult.metrics.simulated_trade_count)}
            />
            <Metric
              label="Estimated profit"
              value={backtestResult.metrics.cumulative_estimated_profit.toFixed(2)}
            />
          </div>
          <a
            className="mt-4 inline-flex rounded border border-border-subtle px-3 py-2 font-body-sm text-text-primary"
            href={`${API_BASE_URL}${backtestResult.report_url}`}
            rel="noreferrer"
            target="_blank"
          >
            Open report
          </a>
          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
            {backtestResult.chart_index.charts.map((chart) => (
              <figure
                key={chart.name}
                className="rounded border border-border-subtle bg-bg-surface p-3"
              >
                <figcaption className="mb-2 font-body-sm text-text-secondary">
                  {chart.title}
                </figcaption>
                <Image
                  alt={chart.title}
                  className="w-full rounded border border-border-subtle"
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
    <div className="rounded border border-border-subtle bg-bg-surface p-3">
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
    <label className="flex flex-col gap-1 font-body-sm text-text-primary">
      {label}
      <input
        className="rounded border border-border-subtle bg-bg-surface px-2 py-2 font-data-mono text-text-primary"
        type="number"
        {...register}
      />
    </label>
  );
}
