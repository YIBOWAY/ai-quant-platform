'use client';

import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

type ControlValues = {
  provider: "sample" | "polymarket";
  cache_mode: "prefer_cache" | "refresh" | "network_only";
  limit: string;
};

export function PredictionMarketDataControls({
  initial,
}: {
  initial: ControlValues;
}) {
  const router = useRouter();
  const form = useForm<ControlValues>({
    defaultValues: initial,
  });

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={form.handleSubmit((values) => {
        const params = new URLSearchParams(values);
        router.push(`/order-book?${params.toString()}`);
      })}
    >
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Provider
        <select
          className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary"
          {...form.register("provider")}
        >
          <option style={optionStyle} value="sample">
            sample
          </option>
          <option style={optionStyle} value="polymarket">
            polymarket
          </option>
        </select>
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Cache
        <select
          className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary"
          {...form.register("cache_mode")}
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
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Markets
        <input
          className="h-8 w-24 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary"
          type="number"
          min={1}
          max={20}
          {...form.register("limit")}
        />
      </label>
      <button
        className="h-8 rounded bg-accent-success px-3 font-body-sm font-semibold text-on-primary"
        type="submit"
      >
        Load markets
      </button>
    </form>
  );
}
