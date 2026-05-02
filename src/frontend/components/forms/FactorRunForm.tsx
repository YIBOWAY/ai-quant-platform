'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost, splitSymbols } from "@/lib/apiClient";
import { useIsHydrated } from "@/lib/hydration";

const factorSchema = z.object({
  symbols: z.string().min(1, "Enter at least one symbol"),
  start: z.string().min(1, "Start date is required"),
  end: z.string().min(1, "End date is required"),
  provider: z.enum(["sample", "futu", "tiingo"]),
  lookback: z.coerce.number().int().positive(),
  quantiles: z.coerce.number().int().min(2),
});

type FactorFormValues = z.infer<typeof factorSchema>;

type FactorRunResponse = {
  run_id: string;
};

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };
const DEFAULTS: FactorFormValues = {
  symbols: "SPY,QQQ",
  start: "2024-01-02",
  end: "2024-02-15",
  provider: "futu",
  lookback: 5,
  quantiles: 5,
};

export function FactorRunForm() {
  const router = useRouter();
  const isHydrated = useIsHydrated();
  const form = useForm<FactorFormValues>({
    resolver: zodResolver(factorSchema),
    defaultValues: DEFAULTS,
  });
  const mutation = useMutation({
    mutationFn: (values: FactorFormValues) =>
      apiPost<FactorRunResponse>("/api/factors/run", {
        ...values,
        symbols: splitSymbols(values.symbols),
      }),
    onSuccess: (payload) => {
      toast.success(`Factor run created: ${payload.run_id}`);
      router.refresh();
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;

  const runFactor = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <form className="flex flex-col gap-4" onSubmit={runFactor}>
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
          Quantiles
          <input className="rounded border border-border-subtle bg-surface-muted px-2 py-2 font-data-mono text-text-primary" defaultValue={DEFAULTS.quantiles} type="number" {...form.register("quantiles", { valueAsNumber: true })} />
        </label>
      </div>
      {error ? <p className="font-body-sm text-danger">{error}</p> : null}
      <button
        className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!isHydrated || mutation.isPending}
        type="submit"
      >
        {mutation.isPending ? "Running..." : "Run Factor"}
      </button>
    </form>
  );
}
