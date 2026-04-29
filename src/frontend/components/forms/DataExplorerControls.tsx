'use client';

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

const controlSchema = z.object({
  symbol: z.string().min(1),
  start: z.string().min(1),
  end: z.string().min(1),
  provider: z.enum(["sample", "tiingo"]),
});

type ControlValues = z.infer<typeof controlSchema>;

const optionStyle = { background: "#0E1511", color: "#F1F5F9" };

export function DataExplorerControls({
  symbols,
  initial,
}: {
  symbols: string[];
  initial: ControlValues;
}) {
  const router = useRouter();
  const form = useForm<ControlValues>({
    resolver: zodResolver(controlSchema),
    defaultValues: initial,
  });

  return (
    <form
      className="flex flex-wrap items-end gap-4"
      onSubmit={form.handleSubmit((values) => {
        const params = new URLSearchParams(values);
        router.push(`/data-explorer?${params.toString()}`);
      })}
    >
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Universe
        <select className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info" {...form.register("symbol")}>
          {symbols.map((symbol) => (
            <option key={symbol} style={optionStyle}>
              {symbol}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Start
        <input className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info" type="date" {...form.register("start")} />
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        End
        <input className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info" type="date" {...form.register("end")} />
      </label>
      <label className="flex flex-col gap-1 font-body-sm text-text-primary">
        Source
        <select className="h-8 rounded border border-border-subtle bg-surface-muted px-2 font-data-mono text-data-mono text-text-primary focus:border-info focus:ring-1 focus:ring-info" {...form.register("provider")}>
          <option style={optionStyle}>sample</option>
          <option style={optionStyle}>tiingo</option>
        </select>
      </label>
      <button
        className="h-8 rounded bg-accent-success px-3 font-body-sm font-semibold text-on-primary"
        type="submit"
      >
        Load
      </button>
    </form>
  );
}
