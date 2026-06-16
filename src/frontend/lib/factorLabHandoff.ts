import { localizePath, type Locale } from "./locale";

export type FactorLabBacktestHandoff = {
  benchmarkSymbol: string;
  end: string;
  factorIds: string[];
  locale: Locale;
  lookback: number;
  provider: string;
  start: string;
  universeId: string;
};

export function buildFactorLabBacktestHref({
  benchmarkSymbol,
  end,
  factorIds,
  locale,
  lookback,
  provider,
  start,
  universeId,
}: FactorLabBacktestHandoff) {
  const params = new URLSearchParams();
  params.set("provider", provider);
  params.set("universe_id", universeId);
  params.set("benchmark_symbol", benchmarkSymbol.toUpperCase());
  params.set("start", start);
  params.set("end", end);
  params.set("lookback", String(lookback));

  const cleanFactorIds = factorIds.map((factorId) => factorId.trim()).filter(Boolean);
  if (cleanFactorIds.length) {
    params.set("factor_ids", cleanFactorIds.join(","));
  }

  return localizePath(`/backtest?${params.toString()}`, locale);
}
