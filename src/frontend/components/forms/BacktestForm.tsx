'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";

const backtestSchema = z.object({
  symbols: z.string().min(1, "Enter at least one symbol"),
  start: z.string().min(1, "Start date is required"),
  end: z.string().min(1, "End date is required"),
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

export function BacktestForm() {
  const router = useRouter();
  const form = useForm<BacktestFormValues>({
    resolver: zodResolver(backtestSchema),
    defaultValues: {
      symbols: "SPY,QQQ",
      start: "2024-01-02",
      end: "2024-02-15",
      lookback: 5,
      top_n: 1,
      initial_cash: 100000,
      commission_bps: 1,
      slippage_bps: 5,
    },
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

  return (
    <form className="flex flex-col gap-4" onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Symbols
        <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" {...form.register("symbols")} />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Start
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="date" {...form.register("start")} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          End
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="date" {...form.register("end")} />
        </label>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Lookback
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="number" {...form.register("lookback", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Top N
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="number" {...form.register("top_n", { valueAsNumber: true })} />
        </label>
      </div>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Initial Cash
        <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("initial_cash", { valueAsNumber: true })} />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Commission bps
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="number" {...form.register("commission_bps", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Slippage bps
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" type="number" {...form.register("slippage_bps", { valueAsNumber: true })} />
        </label>
      </div>
      {error ? <p className="font-body-sm text-danger">{error}</p> : null}
      <button
        className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
        disabled={mutation.isPending}
        type="submit"
      >
        {mutation.isPending ? "Running..." : "Run Backtest"}
      </button>
    </form>
  );
}
