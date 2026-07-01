'use client';

import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { TerminalToolbarButton, terminalFilterInputClass } from "@/components/ui/primitives";
import { localizePath } from "@/lib/locale";

const copy = {
  en: {
    provider: "Provider",
    cache: "Cache",
    markets: "Markets",
    load: "Load markets",
  },
  zh: {
    provider: "数据源",
    cache: "缓存",
    markets: "市场数量",
    load: "加载市场",
  },
} as const;

type ControlValues = {
  provider: "sample" | "polymarket";
  cache_mode: "prefer_cache" | "refresh" | "network_only";
  limit: string;
};

export function PredictionMarketDataControls({
  initial,
  locale = "en",
}: {
  initial: ControlValues;
  locale?: "en" | "zh";
}) {
  const text = copy[locale];
  const router = useRouter();
  const form = useForm<ControlValues>({
    defaultValues: initial,
  });

  const fieldClass = terminalFilterInputClass;
  const labelClass =
    "flex flex-col gap-1 font-label-caps text-[10px] uppercase text-text-secondary";

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={form.handleSubmit((values) => {
        const params = new URLSearchParams(values);
        router.push(localizePath(`/polymarket?${params.toString()}`, locale));
      })}
    >
      <label className={labelClass}>
        {text.provider}
        <select className={fieldClass} {...form.register("provider")}>
          <option value="polymarket">polymarket</option>
          <option value="sample">sample</option>
        </select>
      </label>
      <label className={labelClass}>
        {text.cache}
        <select className={fieldClass} {...form.register("cache_mode")}>
          <option value="prefer_cache">prefer_cache</option>
          <option value="refresh">refresh</option>
          <option value="network_only">network_only</option>
        </select>
      </label>
      <label className={labelClass}>
        {text.markets}
        <input
          className={`${fieldClass} w-24`}
          type="number"
          min={1}
          max={20}
          {...form.register("limit")}
        />
      </label>
      <TerminalToolbarButton className="h-8" type="submit" tone="info">
        {text.load}
      </TerminalToolbarButton>
    </form>
  );
}
