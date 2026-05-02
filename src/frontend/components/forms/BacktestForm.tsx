'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

const backtestSchema = z.object({
  symbols: z.string().min(1, "Enter at least one symbol"),
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

type BacktestRunResponse = {
  run_id: string;
};

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const DEFAULTS: BacktestFormValues = {
  symbols: "SPY,QQQ",
  start: "2024-01-02",
  end: "2024-02-15",
  provider: "futu",
  lookback: 5,
  top_n: 1,
  initial_cash: 100000,
  commission_bps: 1,
  slippage_bps: 5,
};

export function BacktestForm() {
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const form = useForm<BacktestFormValues>({
    resolver: zodResolver(backtestSchema),
    defaultValues: DEFAULTS,
  });
  const mutation = useMutation({
    mutationFn: (values: BacktestFormValues) =>
      apiPost<BacktestRunResponse>("/api/backtests/run", {
        ...values,
        symbols: splitSymbols(values.symbols),
      }),
    onSuccess: (payload) => {
      toast.success(`Backtest created: ${payload.run_id}`);
      router.refresh();
    },
  });

  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;

  const runBacktest = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <form className="flex flex-col gap-4" onSubmit={runBacktest}>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Symbols
        <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.symbols} {...form.register("symbols")} />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Start
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.start} type="date" {...form.register("start")} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          End
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.end} type="date" {...form.register("end")} />
        </label>
      </div>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Data Source
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
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Lookback
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.lookback} type="number" {...form.register("lookback", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Top N
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.top_n} type="number" {...form.register("top_n", { valueAsNumber: true })} />
        </label>
      </div>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Initial Cash
        <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.initial_cash} type="number" {...form.register("initial_cash", { valueAsNumber: true })} />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Commission bps
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.commission_bps} type="number" {...form.register("commission_bps", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Slippage bps
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.slippage_bps} type="number" {...form.register("slippage_bps", { valueAsNumber: true })} />
        </label>
      </div>
      {error ? <p className="font-body-sm text-danger">{error}</p> : null}
      <button
        className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!isHydrated || mutation.isPending}
        type="submit"
      >
        {mutation.isPending ? "Running..." : "Run Backtest"}
      </button>
    </form>
  );
}
