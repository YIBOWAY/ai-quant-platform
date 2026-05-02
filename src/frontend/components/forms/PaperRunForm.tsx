'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

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

type PaperRunResponse = {
  run_id: string;
};

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const DEFAULTS: PaperFormValues = {
  symbols: "SPY,QQQ",
  start: "2024-01-02",
  end: "2024-02-15",
  provider: "futu",
  initial_cash: 100000,
  lookback: 5,
  top_n: 1,
  max_fill_ratio_per_tick: 1,
};

export function PaperRunForm() {
  const router = useRouter();
  const [dialogOpen, setDialogOpen] = useState(false);
  const isHydrated = useIsHydrated();
  const form = useForm<PaperFormValues>({
    resolver: zodResolver(paperSchema),
    defaultValues: DEFAULTS,
  });
  const mutation = useMutation({
    mutationFn: (values: PaperFormValues) =>
      apiPost<PaperRunResponse>("/api/paper/run", {
        ...values,
        symbols: splitSymbols(values.symbols),
        enable_kill_switch: true,
      }),
    onSuccess: (payload) => {
      toast.success(`Paper run created: ${payload.run_id}`);
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;

  const runPaper = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <>
      <form className="flex flex-col gap-4" onSubmit={runPaper}>
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
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Initial Cash
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.initial_cash} type="number" {...form.register("initial_cash", { valueAsNumber: true })} />
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
          Max Fill Ratio
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.max_fill_ratio_per_tick} max={1} min={0.01} step={0.01} type="number" {...form.register("max_fill_ratio_per_tick", { valueAsNumber: true })} />
        </label>
        <button
          aria-pressed="true"
          className="flex items-center justify-between rounded border border-warning/40 bg-warning/10 px-3 py-2 font-body-sm text-warning"
          disabled={!isHydrated}
          onClick={() => setDialogOpen(true)}
          type="button"
        >
          kill_switch enabled
          <span className="rounded-full bg-warning px-2 py-0.5 font-data-mono text-[10px] text-on-primary">
            READ ONLY
          </span>
        </button>
        {error ? <p className="font-body-sm text-danger">{error}</p> : null}
        <button
          className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isHydrated || mutation.isPending}
          type="submit"
        >
          {mutation.isPending ? "Running..." : "Run Paper Trading"}
        </button>
      </form>

      {dialogOpen ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded border border-warning/40 bg-bg-surface p-5 shadow-xl" role="alertdialog" aria-modal="true">
            <h3 className="font-headline-lg text-text-primary">Kill switch is read-only here</h3>
            <p className="mt-3 font-body-sm text-text-secondary">
              kill_switch is enabled on the backend; the API will reject runs that disable it.
              Edit `QS_KILL_SWITCH` in `.env` to change.
            </p>
            <button
              className="mt-5 rounded border border-border-subtle px-4 py-2 font-body-sm text-text-primary"
              onClick={() => setDialogOpen(false)}
              type="button"
            >
              Close
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
