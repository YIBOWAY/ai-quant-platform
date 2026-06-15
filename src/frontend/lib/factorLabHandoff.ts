import { localizePath, type Locale } from "./locale";

export type FactorLabBacktestHandoff = {
  benchmarkSymbol: string;
  factorIds: string[];
  locale: Locale;
  provider: string;
  universeId: string;
};

export function buildFactorLabBacktestHref({
  benchmarkSymbol,
  factorIds,
  locale,
  provider,
  universeId,
}: FactorLabBacktestHandoff) {
  const params = new URLSearchParams();
  params.set("provider", provider);
  params.set("universe_id", universeId);
  params.set("benchmark_symbol", benchmarkSymbol.toUpperCase());

  const cleanFactorIds = factorIds.map((factorId) => factorId.trim()).filter(Boolean);
  if (cleanFactorIds.length) {
    params.set("factor_ids", cleanFactorIds.join(","));
  }

  return localizePath(`/backtest?${params.toString()}`, locale);
}
