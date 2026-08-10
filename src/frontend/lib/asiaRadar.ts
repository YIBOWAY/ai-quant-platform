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

export function getAsiaRadarOverview() {
  return apiRequest<AsiaRadarOverview>(
    "/api/asia-radar/overview?provider=futu",
    { cache: "no-store" },
  );
}
