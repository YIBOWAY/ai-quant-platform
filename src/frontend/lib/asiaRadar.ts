import { apiRequest } from "./apiClient";

export type AsiaRadarDataStatus = "real";
export type AsiaRadarCoverage = "proxy";
export type AsiaRadarLeg = "winner" | "middle" | "laggard";
export type AsiaRadarProvenance = "futu" | "futu_cache";

export type AsiaRadarMarket = {
  market_id: string;
  name_en: string;
  name_zh: string;
  symbol: string;
  data_status: AsiaRadarDataStatus;
  market_coverage: AsiaRadarCoverage;
  rank: number;
  k_leg: AsiaRadarLeg;
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
    provenance: AsiaRadarProvenance;
  };
};

export type AsiaRadarOverview = {
  schema_version: "1.0" | "1.1";
  provider: "futu";
  as_of: string;
  timezone: "America/New_York";
  fetched_at: string;
  provenance: AsiaRadarProvenance;
  methodology: Record<string, string>;
  markets: AsiaRadarMarket[];
  k_shape: {
    winners: string[];
    laggards: string[];
    series: Array<{
      date: string;
      winner_avg_pct: number;
      laggard_avg_pct: number;
      spread_pct: number;
    }>;
  };
};

export type AsiaRadarMarketSummary = {
  symbol: string;
  market_id: string;
  name_en: string;
  name_zh: string;
  rank: number;
  k_leg: AsiaRadarLeg;
  ytd_pct: number;
  week_pct: number;
  month_pct: number;
  volatility_pct: number;
  max_drawdown_pct: number;
  as_of: string;
};

export type AsiaRadarSummary = {
  schema_version: "1.1";
  provider: "futu";
  as_of: string;
  timezone: "America/New_York";
  fetched_at: string;
  provenance: AsiaRadarProvenance;
  status: "available" | "unavailable";
  market_count: number;
  winner_symbols: string[];
  laggard_symbols: string[];
  spread_pct: number | null;
  top_ytd_symbol: string | null;
  top_ytd_pct: number | null;
  bottom_ytd_symbol: string | null;
  bottom_ytd_pct: number | null;
  markets: AsiaRadarMarketSummary[];
};

export function getAsiaRadarOverview() {
  return apiRequest<AsiaRadarOverview>(
    "/api/asia-radar/overview?provider=futu",
    { cache: "no-store" },
  );
}

export function getAsiaRadarSummary() {
  return apiRequest<AsiaRadarSummary>(
    "/api/asia-radar/summary?provider=futu",
    { cache: "no-store" },
  );
}

export type AsiaRadarSummaryEnvelope = {
  summary?: AsiaRadarSummary;
  apiError?: string;
};

export async function getAsiaRadarSummarySafe(): Promise<AsiaRadarSummaryEnvelope> {
  try {
    const summary = await getAsiaRadarSummary();
    return { summary };
  } catch (error) {
    return {
      apiError:
        error instanceof Error ? error.message : "Asia Radar summary unavailable",
    };
  }
}
