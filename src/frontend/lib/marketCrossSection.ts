import { apiRequest } from "./apiClient";

export type MarketCrossSectionProvenance = "futu" | "futu_cache";

export type MarketCrossSectionRow = {
  symbol: string;
  rank: number;
  returns: {
    week_pct: number;
    month_pct: number;
    ytd_pct: number;
  };
  volatility_pct: number;
  max_drawdown_pct: number;
  history: Array<{
    date: string;
    close: number;
    indexed_return_pct: number;
  }>;
  meta: {
    provider: "futu";
    symbol: string;
    currency: "USD";
    timezone: "America/New_York";
    as_of: string;
    adjustment: "qfq";
    provenance: MarketCrossSectionProvenance;
  };
};

export type MarketCrossSectionResponse = {
  schema_version: "1.0";
  provider: "futu";
  as_of: string;
  timezone: "America/New_York";
  fetched_at: string;
  provenance: MarketCrossSectionProvenance;
  basket: string | null;
  basket_label: { en: string; zh: string } | null;
  methodology: Record<string, string>;
  rows: MarketCrossSectionRow[];
};

export function getMarketCrossSection(params?: {
  basket?: string;
  symbols?: string[];
}) {
  const search = new URLSearchParams({ provider: "futu" });
  if (params?.basket) {
    search.set("basket", params.basket);
  }
  if (params?.symbols?.length) {
    search.set("symbols", params.symbols.join(","));
  }
  return apiRequest<MarketCrossSectionResponse>(
    `/api/market-cross-section?${search.toString()}`,
    { cache: "no-store" },
  );
}

export type MarketCrossSectionEnvelope = {
  crossSection?: MarketCrossSectionResponse;
  apiError?: string;
};

export async function getMarketCrossSectionSafe(params?: {
  basket?: string;
  symbols?: string[];
}): Promise<MarketCrossSectionEnvelope> {
  try {
    const crossSection = await getMarketCrossSection(params);
    return { crossSection };
  } catch (error) {
    return {
      apiError:
        error instanceof Error
          ? error.message
          : "Market cross-section unavailable",
    };
  }
}
