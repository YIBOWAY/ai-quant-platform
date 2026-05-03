export type SafetyFooter = {
  dry_run: boolean;
  paper_trading: boolean;
  live_trading_enabled: boolean;
  kill_switch: boolean;
  bind_address: string;
};

export type ApiEnvelope = {
  safety?: SafetyFooter;
  apiError?: string;
};

export type HealthResponse = ApiEnvelope & {
  status: string;
  app_name: string;
  environment: string;
};

export type SymbolsResponse = ApiEnvelope & {
  symbols: string[];
  source: string;
};

export type OhlcvRow = {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type OhlcvResponse = ApiEnvelope & {
  symbol: string;
  source: string;
  rows: OhlcvRow[];
};

export type MarketDataHistoryResponse = ApiEnvelope & {
  symbol: string;
  ticker: string;
  source: string;
  frequency: string;
  row_count: number;
  rows: OhlcvRow[];
  metadata: {
    provider: string;
    requested_provider: string;
    fetched_at: string | null;
  };
};

export type FactorMetadata = {
  factor_id: string;
  factor_name: string;
  factor_version: string;
  lookback: number;
  direction: string;
  description: string;
};

export type FactorsResponse = ApiEnvelope & {
  factors: FactorMetadata[];
};

export type PreviewRecord = Record<string, unknown>;

export type FactorRunSummary = {
  id: string;
  source?: string;
  row_count: number;
  signal_count: number;
  paths?: Record<string, string>;
};

export type FactorRunsResponse = ApiEnvelope & {
  runs: FactorRunSummary[];
};

export type FactorRunDetailResponse = ApiEnvelope & {
  run_id: string;
  metadata: Record<string, unknown>;
  factor_results: PreviewRecord[];
  signals: PreviewRecord[];
  information_coefficients: PreviewRecord[];
  quantile_returns: PreviewRecord[];
};

export type BacktestSummary = {
  id: string;
  source?: string;
  metrics?: {
    total_return?: number;
    sharpe?: number;
    max_drawdown?: number;
  };
};

export type BacktestsResponse = ApiEnvelope & {
  backtests: BacktestSummary[];
};

export type BacktestDetailResponse = ApiEnvelope & {
  id: string;
  metadata: Record<string, unknown>;
  metrics: Record<string, unknown>;
  equity_curve: PreviewRecord[];
  orders: PreviewRecord[];
  positions: PreviewRecord[];
  trade_blotter: PreviewRecord[];
};

export type BenchmarkResponse = ApiEnvelope & {
  symbol: string;
  source: string;
  equity_curve: Array<{ timestamp: string; equity: number }>;
  metrics: {
    total_return: number;
    annualized_return: number;
    volatility: number;
    sharpe: number;
    max_drawdown: number;
    turnover: number;
  };
};

export type PaperRunSummary = {
  id: string;
  source?: string;
  summary?: {
    order_count?: number;
    trade_count?: number;
    risk_breach_count?: number;
    final_equity?: number;
    signal_count?: number;
  };
};

export type PaperRunsResponse = ApiEnvelope & {
  paper_runs: PaperRunSummary[];
};

export type PaperRunDetailResponse = ApiEnvelope & {
  id: string;
  metadata: Record<string, unknown>;
  orders: PreviewRecord[];
  order_events: PreviewRecord[];
  trades: PreviewRecord[];
  risk_breaches: PreviewRecord[];
};

export type ExperimentsResponse = ApiEnvelope & {
  experiments: Array<{ id: string; path: string }>;
};

export type CandidateSummary = {
  candidate_id: string;
  artifact_type: string;
  status: string;
  goal?: string;
};

export type AgentCandidatesResponse = ApiEnvelope & {
  candidates: CandidateSummary[];
};

export type AgentCandidateDetailResponse = ApiEnvelope & {
  candidate_id: string;
  metadata: Record<string, unknown>;
  source_preview: string;
  audit: string[];
  reviews: string[];
};

export type AgentLlmConfigResponse = ApiEnvelope & {
  provider: string;
  model: string | null;
  base_url: string | null;
  timeout: number;
  has_api_key: boolean;
};

export type PredictionMarketResponse = ApiEnvelope & {
  markets: Array<{ market_id: string; question: string; outcomes: Array<{ name: string; token_id?: string }> }>;
  order_books: Array<{
    market_id?: string;
    token_id: string;
    bids: Array<{ price?: number; size?: number }>;
    asks: Array<{ price?: number; size?: number }>;
  }>;
  provider: string;
  cache_status?: string;
};

export type PredictionMarketBacktestResponse = ApiEnvelope & {
  run_id: string;
  provider: string;
  cache_status?: string;
  metrics: {
    market_count: number;
    opportunity_count: number;
    trigger_rate: number;
    mean_edge_bps: number;
    max_edge_bps: number;
    total_estimated_edge: number;
    max_drawdown: number;
  };
  chart_index: { charts: Array<{ name: string; path: string; title: string }> };
  report_path: string;
};

export type PredictionMarketCollectResponse = ApiEnvelope & {
  provider: string;
  iteration_count: number;
  market_count: number;
  snapshot_record_count: number;
  history_dir: string;
  first_timestamp: string | null;
  last_timestamp: string | null;
  cache_status?: string;
};

export type PredictionMarketTimeseriesResponse = ApiEnvelope & {
  run_id: string;
  provider: string;
  metrics: {
    provider: string;
    market_count: number;
    snapshot_count: number;
    market_snapshot_count: number;
    opportunity_count: number;
    simulated_trade_count: number;
    trigger_rate: number;
    mean_edge_bps: number;
    median_edge_bps: number;
    max_edge_bps: number;
    cumulative_estimated_profit: number;
    max_drawdown: number;
    daily_volatility_proxy: number;
  };
  chart_index: {
    charts: Array<{ name: string; path: string; title: string; url: string }>;
  };
  report_path: string;
  report_url: string;
  history_dir: string;
};

export type PredictionMarketTimeseriesDetailResponse = ApiEnvelope & {
  run_id: string;
  result: Record<string, unknown>;
  chart_index: {
    charts: Array<{ name: string; path: string; title: string; url: string }>;
  };
  report_path: string;
  report_url: string;
};

export type OptionsRadarCandidate = {
  ticker: string;
  sector: string | null;
  strategy: "sell_put" | "covered_call";
  symbol: string;
  expiry: string;
  strike: number;
  mid: number | null;
  annualized_yield: number | null;
  implied_volatility: number | null;
  iv_rank: number | null;
  delta: number | null;
  open_interest: number | null;
  spread_pct: number | null;
  earnings_date: string | null;
  earnings_in_window: boolean;
  global_score: number;
  rating: string;
  notes: string[];
  market_regime?: string | null;
  market_regime_penalty?: number | null;
};

export type OptionsRadarDatesResponse = ApiEnvelope & {
  dates: string[];
};

export type OptionsRadarResponse = ApiEnvelope & {
  run_date: string;
  universe_size: number;
  scanned_tickers: number;
  failed_tickers: Array<[string, string]>;
  candidates: OptionsRadarCandidate[];
};

export type SettingsResponse = ApiEnvelope & Record<string, unknown>;

const API_BASE_URL = process.env.NEXT_PUBLIC_QUANT_API_BASE_URL ?? "http://127.0.0.1:8765";

const FALLBACK_SAFETY: SafetyFooter = {
  dry_run: true,
  paper_trading: true,
  live_trading_enabled: false,
  kill_switch: true,
  bind_address: "127.0.0.1",
};

async function apiGet<T extends ApiEnvelope>(path: string, fallback: T): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return (await response.json()) as T;
  } catch (error) {
    return {
      ...fallback,
      safety: fallback.safety ?? FALLBACK_SAFETY,
      apiError: error instanceof Error ? error.message : "API unavailable",
    };
  }
}

export function getHealth() {
  return apiGet<HealthResponse>("/api/health", {
    status: "offline",
    app_name: "AI Quant Research Platform",
    environment: "local",
    safety: FALLBACK_SAFETY,
  });
}

export function getSettings() {
  return apiGet<SettingsResponse>("/api/settings", {
    safety: FALLBACK_SAFETY,
  });
}

export function getSymbols() {
  return apiGet<SymbolsResponse>("/api/symbols", {
    symbols: ["SPY", "QQQ"],
    source: "fallback",
    safety: FALLBACK_SAFETY,
  });
}

export function getOhlcv(symbol = "SPY", start = "2024-01-02", end = "2024-01-12", provider?: string) {
  const params = new URLSearchParams({ symbol, start, end });
  if (provider) {
    params.set("provider", provider);
  }
  return apiGet<OhlcvResponse>(`/api/ohlcv?${params.toString()}`, {
    symbol,
    source: "fallback",
    rows: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getMarketDataHistory(
  ticker = "SPY",
  start = "2024-01-02",
  end = "2024-01-12",
  freq = "1d",
  provider = "futu",
) {
  const params = new URLSearchParams({ ticker, start, end, freq, provider });
  return apiGet<MarketDataHistoryResponse>(`/api/market-data/history?${params.toString()}`, {
    symbol: ticker,
    ticker,
    source: "fallback",
    frequency: freq,
    row_count: 0,
    rows: [],
    metadata: {
      provider: "fallback",
      requested_provider: provider,
      fetched_at: null,
    },
    safety: FALLBACK_SAFETY,
  });
}

export function getFactors() {
  return apiGet<FactorsResponse>("/api/factors", {
    factors: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getFactorRuns() {
  return apiGet<FactorRunsResponse>("/api/factors/runs", {
    runs: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getFactorRunDetail(runId: string) {
  return apiGet<FactorRunDetailResponse>(`/api/factors/${runId}`, {
    run_id: runId,
    metadata: {},
    factor_results: [],
    signals: [],
    information_coefficients: [],
    quantile_returns: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getBacktests() {
  return apiGet<BacktestsResponse>("/api/backtests", {
    backtests: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getBacktestDetail(runId: string) {
  return apiGet<BacktestDetailResponse>(`/api/backtests/${runId}`, {
    id: runId,
    metadata: {},
    metrics: {},
    equity_curve: [],
    orders: [],
    positions: [],
    trade_blotter: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getBenchmark(
  symbol = "SPY",
  start = "2024-01-02",
  end = "2024-01-12",
  provider?: string,
) {
  const params = new URLSearchParams({ symbol, start, end });
  if (provider) {
    params.set("provider", provider);
  }
  return apiGet<BenchmarkResponse>(`/api/benchmark?${params.toString()}`, {
    symbol,
    source: "fallback",
    equity_curve: [],
    metrics: {
      total_return: 0,
      annualized_return: 0,
      volatility: 0,
      sharpe: 0,
      max_drawdown: 0,
      turnover: 0,
    },
    safety: FALLBACK_SAFETY,
  });
}

export function getPaperRuns() {
  return apiGet<PaperRunsResponse>("/api/paper", {
    paper_runs: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getPaperRunDetail(runId: string) {
  return apiGet<PaperRunDetailResponse>(`/api/paper/${runId}`, {
    id: runId,
    metadata: {},
    orders: [],
    order_events: [],
    trades: [],
    risk_breaches: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getExperiments() {
  return apiGet<ExperimentsResponse>("/api/experiments", {
    experiments: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getAgentCandidates() {
  return apiGet<AgentCandidatesResponse>("/api/agent/candidates", {
    candidates: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getAgentCandidateDetail(candidateId: string) {
  return apiGet<AgentCandidateDetailResponse>(`/api/agent/candidates/${candidateId}`, {
    candidate_id: candidateId,
    metadata: {},
    source_preview: "",
    audit: [],
    reviews: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getAgentLlmConfig() {
  return apiGet<AgentLlmConfigResponse>("/api/agent/llm-config", {
    provider: "stub",
    model: null,
    base_url: null,
    timeout: 60,
    has_api_key: false,
    safety: FALLBACK_SAFETY,
  });
}

export function getPredictionMarkets(
  provider = "sample",
  cacheMode = "prefer_cache",
  limit = 6,
) {
  const params = new URLSearchParams({
    provider,
    cache_mode: cacheMode,
    limit: String(limit),
  });
  return apiGet<PredictionMarketResponse>(`/api/prediction-market/markets?${params.toString()}`, {
    markets: [],
    order_books: [],
    provider: "fallback",
    cache_status: "unavailable",
    safety: FALLBACK_SAFETY,
  });
}

export function getOptionsRadarDates() {
  return apiGet<OptionsRadarDatesResponse>("/api/options/daily-scan/dates", {
    dates: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getOptionsDailyScan(params: {
  date?: string;
  strategy?: string;
  sector?: string;
  top?: number;
  dte_bucket?: string;
}) {
  const query = new URLSearchParams();
  if (params.date) {
    query.set("date", params.date);
  }
  if (params.strategy) {
    query.set("strategy", params.strategy);
  }
  if (params.sector) {
    query.set("sector", params.sector);
  }
  if (params.top !== undefined) {
    query.set("top", String(params.top));
  }
  if (params.dte_bucket) {
    query.set("dte_bucket", params.dte_bucket);
  }
  return apiGet<OptionsRadarResponse>(`/api/options/daily-scan?${query.toString()}`, {
    run_date: params.date ?? "",
    universe_size: 0,
    scanned_tickers: 0,
    failed_tickers: [],
    candidates: [],
    safety: FALLBACK_SAFETY,
  });
}

export function formatPercent(value: number | undefined, digits = 2) {
  if (value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatMoney(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}
