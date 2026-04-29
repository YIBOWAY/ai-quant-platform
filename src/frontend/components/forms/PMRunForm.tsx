'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiClientError, apiPost } from "@/lib/apiClient";

const pmSchema = z.object({
  min_edge_bps: z.coerce.number().nonnegative(),
  max_capital_per_leg: z.coerce.number().nonnegative(),
  max_legs: z.coerce.number().int().positive(),
});

type PMFormValues = z.infer<typeof pmSchema>;
type PMAction = "scan" | "dry-arbitrage";

export function PMRunForm() {
  const [result, setResult] = useState<string>("");
  const form = useForm<PMFormValues>({
    resolver: zodResolver(pmSchema),
    defaultValues: {
      min_edge_bps: 200,
      max_capital_per_leg: 1000,
      max_legs: 3,
    },
  });
  const mutation = useMutation({
    mutationFn: ({ action, values }: { action: PMAction; values: PMFormValues }) =>
      apiPost<Record<string, unknown>>(
        action === "scan" ? "/api/prediction-market/scan" : "/api/prediction-market/dry-arbitrage",
        {
          ...values,
          optimizer: "greedy",
          polymarket_api_key: null,
        },
      ),
    onSuccess: (payload) => {
      setResult(JSON.stringify(payload, null, 2));
      toast.success("Prediction-market dry workflow completed");
    },
  });
  const error = mutation.error instanceof ApiClientError ? mutation.error.message : undefined;

  function submit(action: PMAction) {
    return form.handleSubmit((values) => mutation.mutate({ action, values }))();
  }

  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-4">
      <h2 className="font-headline-lg text-text-primary">Sample Scanner</h2>
      <p className="mt-1 font-body-sm text-text-secondary">
        This form never accepts or sends a Polymarket API key.
      </p>
      <form className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Min edge bps
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("min_edge_bps", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Max capital per leg
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("max_capital_per_leg", { valueAsNumber: true })} />
        </label>
        <label className="flex flex-col gap-1 font-body-sm text-text-primary">
          Max legs
          <input className="rounded border border-border-subtle bg-surface-muted px-3 py-2 font-data-mono text-text-primary" type="number" {...form.register("max_legs", { valueAsNumber: true })} />
        </label>
      </form>
      {error ? <p className="mt-3 font-body-sm text-danger">{error}</p> : null}
      <div className="mt-4 flex gap-2">
        <button
          className="rounded border border-border-subtle px-4 py-2 font-body-sm text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={mutation.isPending}
          onClick={() => submit("scan")}
          type="button"
        >
          {mutation.isPending ? "Running..." : "Run scanner"}
        </button>
        <button
          className="rounded bg-accent-success px-4 py-2 font-body-sm font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={mutation.isPending}
          onClick={() => submit("dry-arbitrage")}
          type="button"
        >
          {mutation.isPending ? "Running..." : "Generate dry arbitrage"}
        </button>
      </div>
      {result ? (
        <pre className="mt-4 max-h-64 overflow-auto rounded border border-border-subtle bg-surface-muted p-3 font-code-sm text-text-primary">
          {result}
        </pre>
      ) : null}
    </div>
  );
}
