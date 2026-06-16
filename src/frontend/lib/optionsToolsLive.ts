import type {
  OptionContract,
  OptionsAlertsEvaluationResponse,
  OptionsBullPutSignalResponse,
  OptionsChainResponse,
  OptionsContractScoreResponse,
  OptionsEarningsCrushResponse,
  OptionsFearScoreResponse,
  OptionsGreeksResponse,
  OptionsHedgeAdvisorResponse,
  OptionsImpliedVolatilityResponse,
  OptionsMarketSentimentResponse,
  OptionsResearchHealthCheckResponse,
  OptionsSimulationResponse,
  OptionsSnapshotResponse,
  OptionsStrategyBuildResponse,
  OptionsStrategyRankResponse,
  OptionsStrategyTemplatesResponse,
  OptionsUnusualActivityResponse,
  OptionsVolSmileResponse,
  OptionsVolSurfaceResponse,
  OptionsWatchlistResponse,
} from "@/lib/api";
import { apiPost, apiRequest } from "@/lib/apiClient";

export type LiveContract = OptionContract;

export type HedgeAdvisorInput = {
  shares: number;
  costBasis: number;
  purpose?: string;
};

type LiveContext = {
  ticker: string;
  spot: number;
  expiry: string;
  dte: number;
  atmIv: number | null;
  hv30d: number | null;
  ivRank: number | null;
  contracts: LiveContract[];
};

export async function calculateLiveGreeks(ticker: string): Promise<{
  contract: LiveContract;
  payload: OptionsGreeksResponse;
}> {
  const context = await loadLiveContext(ticker);
  const contract = pickAtmContract(context.contracts, context.spot, "CALL");
  if (!contract?.strike || !contract.implied_volatility) {
    throw new Error(`No usable live at-the-money call was found for ${context.ticker}.`);
  }
  const payload = await apiPost<OptionsGreeksResponse>("/api/options/tools/greeks", {
    spot: context.spot,
    strike: contract.strike,
    expiry_days: context.dte,
    iv: normalizeIv(contract.implied_volatility),
    option_type: "call",
  });
  return { contract, payload };
}

export async function rankLiveStrategies(ticker: string): Promise<OptionsStrategyRankResponse> {
  const context = await loadLiveContext(ticker);
  return apiPost<OptionsStrategyRankResponse>("/api/options/tools/strategy/rank", {
    market_view: "bullish",
    spot: context.spot,
    expiry_days: context.dte,
    strikes: liveStrikes(context),
    iv: context.atmIv ?? 0.3,
    symbol: context.ticker,
  });
}

export async function scoreLiveContracts(ticker: string): Promise<OptionsContractScoreResponse> {
  const context = await loadLiveContext(ticker);
  return apiPost<OptionsContractScoreResponse>("/api/options/tools/score-contracts", {
    spot: context.spot,
    objective: "sell_premium",
    top_n: 10,
    contracts: context.contracts,
  });
}

export async function simulateLiveCallSpread(ticker: string): Promise<OptionsSimulationResponse> {
  const context = await loadLiveContext(ticker);
  const [longCall, shortCall] = buildLiveCallSpread(context);
  return apiPost<OptionsSimulationResponse>("/api/options/tools/simulate", {
    symbol: context.ticker,
    spot: context.spot,
    legs: [
      {
        action: "buy",
        option_type: "call",
        strike: longCall.strike,
        expiry_days: context.dte,
        iv: normalizeIv(longCall.implied_volatility),
        entry_price: midPrice(longCall),
      },
      {
        action: "sell",
        option_type: "call",
        strike: shortCall.strike,
        expiry_days: context.dte,
        iv: normalizeIv(shortCall.implied_volatility),
        entry_price: midPrice(shortCall),
      },
    ],
  });
}

export function loadVolSurface(ticker: string): Promise<OptionsVolSurfaceResponse> {
  return apiRequest<OptionsVolSurfaceResponse>(
    `/api/options/tools/vol-surface/${encodeURIComponent(ticker.trim().toUpperCase())}?max_expirations=3`,
  );
}

export function loadVolSmile(ticker: string): Promise<OptionsVolSmileResponse> {
  return apiRequest<OptionsVolSmileResponse>(
    `/api/options/tools/vol-smile/${encodeURIComponent(ticker.trim().toUpperCase())}`,
  );
}

export async function liveImpliedVolatility(ticker: string): Promise<OptionsImpliedVolatilityResponse> {
  const context = await loadLiveContext(ticker);
  const contract = pickAtmContract(context.contracts, context.spot, "CALL");
  const marketPrice = contract ? midPrice(contract) : null;
  if (!contract || marketPrice === null) {
    throw new Error(`No usable live call quote was found for ${context.ticker}.`);
  }
  return apiPost<OptionsImpliedVolatilityResponse>("/api/options/tools/implied-volatility", {
    market_price: marketPrice,
    spot: context.spot,
    strike: contract.strike,
    expiry_days: context.dte,
    option_type: "call",
  });
}

export async function liveFearScore(ticker: string): Promise<OptionsFearScoreResponse> {
  const context = await loadLiveContext(ticker);
  return apiPost<OptionsFearScoreResponse>("/api/options/tools/fear-score", {
    iv_rank: context.ivRank,
  });
}

export function liveIvRankSnapshot(ticker: string): Promise<OptionsSnapshotResponse> {
  return apiRequest<OptionsSnapshotResponse>(
    `/api/options/snapshot/${encodeURIComponent(ticker.trim().toUpperCase())}`,
  );
}

export function runMarketSentiment(): Promise<OptionsMarketSentimentResponse> {
  return apiPost<OptionsMarketSentimentResponse>("/api/options/tools/market-sentiment", {});
}

export async function liveBullPutSignal(ticker: string): Promise<OptionsBullPutSignalResponse> {
  const context = await loadLiveContext(ticker);
  const fear = await apiPost<OptionsFearScoreResponse>("/api/options/tools/fear-score", {
    iv_rank: context.ivRank,
  });
  return apiPost<OptionsBullPutSignalResponse>("/api/options/tools/bull-put-signal", {
    contracts: context.contracts,
    spot: context.spot,
    fear_score: fear.fear_score,
  });
}

export async function liveEarningsCrush(ticker: string): Promise<OptionsEarningsCrushResponse> {
  const context = await loadLiveContext(ticker);
  const contract = pickAtmContract(context.contracts, context.spot, "CALL");
  const currentIv = context.atmIv ?? contract?.implied_volatility ?? null;
  if (currentIv === null) {
    throw new Error(`No live IV was found for ${context.ticker}.`);
  }
  return apiPost<OptionsEarningsCrushResponse>("/api/options/tools/earnings-crush", {
    ticker: context.ticker,
    current_iv: currentIv,
    historical_pre_post_iv: [],
  });
}

export async function liveUnusualActivity(ticker: string): Promise<OptionsUnusualActivityResponse> {
  const context = await loadLiveContext(ticker);
  return apiPost<OptionsUnusualActivityResponse>("/api/options/tools/unusual-activity", {
    contracts: context.contracts,
    min_volume_oi_ratio: 2,
    min_volume: 100,
  });
}

export async function liveHedgeAdvisor(
  ticker: string,
  input: HedgeAdvisorInput,
): Promise<OptionsHedgeAdvisorResponse> {
  const shares = Math.trunc(input.shares);
  if (!Number.isFinite(shares) || shares <= 0) {
    throw new Error("Shares must be a positive number.");
  }
  if (!Number.isFinite(input.costBasis) || input.costBasis <= 0) {
    throw new Error("Cost basis must be a positive number.");
  }

  const context = await loadLiveContext(ticker);
  return apiPost<OptionsHedgeAdvisorResponse>("/api/options/tools/hedge-advisor", {
    ticker: context.ticker,
    shares,
    cost_basis: input.costBasis,
    spot: context.spot,
    purpose: input.purpose?.trim() || "protect",
    contracts: context.contracts,
  });
}

export function loadStrategyTemplates(): Promise<OptionsStrategyTemplatesResponse> {
  return apiRequest<OptionsStrategyTemplatesResponse>("/api/options/tools/strategy/templates");
}

export async function liveBuildStrategy(ticker: string): Promise<OptionsStrategyBuildResponse> {
  const context = await loadLiveContext(ticker);
  return apiPost<OptionsStrategyBuildResponse>("/api/options/tools/strategy/build", {
    mode: "template",
    template_id: "bull_call_spread",
    spot: context.spot,
    expiry_days: context.dte,
    strikes: liveStrikes(context),
    iv: context.atmIv ?? 0.3,
    symbol: context.ticker,
  });
}

export function addWatchlistTicker(ticker: string): Promise<OptionsWatchlistResponse> {
  return apiPost<OptionsWatchlistResponse>("/api/options/tools/watchlist", {
    ticker,
    tags: ["local-research"],
  });
}

export function loadWatchlist(): Promise<OptionsWatchlistResponse> {
  return apiRequest<OptionsWatchlistResponse>("/api/options/tools/watchlist");
}

export async function liveEvaluateAlerts(ticker: string): Promise<OptionsAlertsEvaluationResponse> {
  const context = await loadLiveContext(ticker);
  return apiPost<OptionsAlertsEvaluationResponse>("/api/options/tools/alerts/evaluate", {
    alerts: [
      {
        id: "price-plus-5pct",
        ticker: context.ticker,
        type: "price_above",
        threshold: Number((context.spot * 1.05).toFixed(2)),
      },
      {
        id: "iv-rank-high",
        ticker: context.ticker,
        type: "iv_rank_above",
        threshold: 70,
      },
    ],
    context: {
      ticker: context.ticker,
      price: context.spot,
      iv_rank: context.ivRank,
      unusual_activity_count: 0,
    },
  });
}

export async function liveResearchHealthCheck(ticker: string): Promise<OptionsResearchHealthCheckResponse> {
  const normalized = ticker.trim().toUpperCase();
  if (!normalized) {
    throw new Error("Ticker is required.");
  }
  return apiPost<OptionsResearchHealthCheckResponse>("/api/options/tools/health-check", {
    profiles: [
      {
        ticker: normalized,
        updated_at: new Date().toISOString().slice(0, 10),
        thesis: "local research watch",
      },
    ],
  });
}

async function loadLiveContext(ticker: string): Promise<LiveContext> {
  const normalized = ticker.trim().toUpperCase();
  if (!normalized) {
    throw new Error("Ticker is required.");
  }
  const snapshot = await apiRequest<OptionsSnapshotResponse>(
    `/api/options/snapshot/${encodeURIComponent(normalized)}`,
  );
  const expiry = snapshot.nearest_expiry;
  const params = new URLSearchParams({
    ticker: snapshot.ticker || normalized,
    expiration: expiry,
    option_type: "ALL",
  });
  const chain = await apiRequest<OptionsChainResponse>(
    `/api/options/chain?${params.toString()}`,
  );
  return {
    ticker: snapshot.ticker || chain.ticker || normalized,
    spot: snapshot.price,
    expiry,
    dte: daysToExpiry(expiry),
    atmIv: normalizeOptionalIv(snapshot.atm_iv),
    hv30d: snapshot.hv_30d ?? null,
    ivRank: snapshot.iv_rank ?? null,
    contracts: chain.contracts.map((contract) => ({
      ...contract,
      expiry: contract.expiry ?? chain.expiration,
    })),
  };
}

function usableContracts(
  contracts: LiveContract[],
  optionType?: "CALL" | "PUT",
): Array<LiveContract & { strike: number; implied_volatility: number }> {
  return contracts
    .filter((contract) => !optionType || contract.option_type.toUpperCase() === optionType)
    .map((contract) => ({
      ...contract,
      strike: typeof contract.strike === "number" ? contract.strike : Number.NaN,
      implied_volatility: normalizeOptionalIv(contract.implied_volatility) ?? Number.NaN,
    }))
    .filter(
      (contract): contract is LiveContract & { strike: number; implied_volatility: number } =>
        Number.isFinite(contract.strike) &&
        contract.strike > 0 &&
        Number.isFinite(contract.implied_volatility) &&
        contract.implied_volatility > 0,
    );
}

function pickAtmContract(
  contracts: LiveContract[],
  spot: number,
  optionType: "CALL" | "PUT",
) {
  const available = usableContracts(contracts, optionType);
  return available.sort((left, right) => Math.abs(left.strike - spot) - Math.abs(right.strike - spot))[0];
}

function liveStrikes(context: LiveContext) {
  const strikes = [...new Set(usableContracts(context.contracts).map((contract) => contract.strike))]
    .sort((left, right) => Math.abs(left - context.spot) - Math.abs(right - context.spot))
    .slice(0, 9)
    .sort((left, right) => left - right);
  if (strikes.length < 2) {
    throw new Error(`No usable live strikes were found for ${context.ticker}.`);
  }
  return strikes;
}

function buildLiveCallSpread(context: LiveContext) {
  const callsByStrike = usableContracts(context.contracts, "CALL")
    .filter((contract) => midPrice(contract) !== null)
    .sort((left, right) => left.strike - right.strike);
  const longCall = [...callsByStrike].sort(
    (left, right) => Math.abs(left.strike - context.spot) - Math.abs(right.strike - context.spot),
  )[0];
  if (!longCall) {
    throw new Error(`No usable live call was found for ${context.ticker}.`);
  }
  const shortCall = callsByStrike.find((contract) => contract.strike > longCall.strike);
  if (!shortCall) {
    throw new Error(`No higher-strike live call was found for ${context.ticker}.`);
  }
  return [longCall, shortCall] as const;
}

function daysToExpiry(expiry: string) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const expiryDate = new Date(`${expiry}T00:00:00`);
  if (Number.isNaN(expiryDate.getTime())) {
    return 30;
  }
  return Math.max(1, Math.round((expiryDate.getTime() - today.getTime()) / 86_400_000));
}

function normalizeOptionalIv(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  return value > 5 ? value / 100 : value;
}

function normalizeIv(value: number | null | undefined) {
  return normalizeOptionalIv(value) ?? 0.3;
}

function midPrice(contract: LiveContract) {
  if (
    typeof contract.bid === "number" &&
    typeof contract.ask === "number" &&
    contract.bid > 0 &&
    contract.ask >= contract.bid
  ) {
    return (contract.bid + contract.ask) / 2;
  }
  return typeof contract.last === "number" && contract.last > 0 ? contract.last : null;
}
