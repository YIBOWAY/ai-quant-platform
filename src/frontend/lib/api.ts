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
  futu_opend?: {
    enabled: boolean;
    reachable?: boolean;
    host?: string;
    port?: number;
    error?: string | null;
  };
  database?: {
    enabled: boolean;
    reachable?: boolean;
    error?: string | null;
  };
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

export type FactorRunResponse = ApiEnvelope & {
  run_id: string;
  source: string;
  row_count: number;
  signal_count: number;
  warnings: string[];
  request: Record<string, unknown>;
  paths: Record<string, unknown>;
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

export type BacktestRunResponse = ApiEnvelope & {
  run_id: string;
  source: string;
  trade_count: number;
  order_count: number;
  warnings: string[];
  timings_ms: Record<string, unknown>;
  request: Record<string, unknown>;
  metrics: Record<string, unknown>;
  attribution: PreviewRecord[];
  benchmark: Record<string, unknown>;
  paths: Record<string, unknown>;
};

export type BenchmarkMetrics = {
  total_return: number;
  annualized_return: number;
  volatility: number;
  sharpe: number;
  max_drawdown: number;
  turnover: number;
};

export type BenchmarkSnapshot = ApiEnvelope & {
  symbol: string;
  source: string;
  equity_curve: Array<{ timestamp: string; equity: number }>;
  metrics: BenchmarkMetrics;
};

export type BacktestDetailResponse = ApiEnvelope & {
  id: string;
  metadata: Record<string, unknown>;
  metrics: Record<string, unknown>;
  equity_curve: PreviewRecord[];
  benchmark: BenchmarkSnapshot | null;
  orders: PreviewRecord[];
  positions: PreviewRecord[];
  trade_blotter: PreviewRecord[];
  attribution: PreviewRecord[];
};

export type ReversalMomentumReplicationDetailResponse = ApiEnvelope & {
  run_id: string;
  metadata: Record<string, unknown>;
  result: Record<string, unknown>;
};

export type StrategyMetadata = {
  id: string;
  name: string;
  description: string;
  paper_source: string | null;
  run_endpoint: string;
  result_type: string;
  supports_account_rebalance?: boolean;
  parameter_schema: {
    fields?: Record<string, Record<string, unknown>>;
  };
  default_payload: Record<string, unknown>;
};

export type StrategiesResponse = ApiEnvelope & {
  strategies: StrategyMetadata[];
};

export type UniverseDefinition = {
  id: string;
  name: string;
  description: string;
  symbols: string[];
  benchmark_symbol: string;
};

export type UniversesResponse = ApiEnvelope & {
  universes: UniverseDefinition[];
};

export type FactorLabRow = Record<string, string | number | boolean | null>;

export type FactorLabResponse = ApiEnvelope & {
  generated_at?: string;
  source: string;
  benchmark_symbol: string;
  universe: UniverseDefinition;
  factors: FactorMetadata[];
  guardrails: Record<string, unknown>;
  cache: Record<string, unknown>;
  cross_sectional: {
    engine: string;
    rows: FactorLabRow[];
  };
  timing: {
    engine: string;
    symbol: string;
    rows: FactorLabRow[];
  };
};

export type BenchmarkResponse = ApiEnvelope & {
  symbol: string;
  source: string;
  equity_curve: Array<{ timestamp: string; equity: number }>;
  metrics: BenchmarkMetrics;
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
    execution_status?: string;
    execution_note?: string;
  };
};

export type PaperRunsResponse = ApiEnvelope & {
  paper_runs: PaperRunSummary[];
};

export type PaperRunResponse = ApiEnvelope & {
  run_id: string;
  source: string;
  signal_count: number;
  order_count: number;
  trade_count: number;
  risk_breach_count: number;
  final_equity: number;
  execution_status: string;
  execution_note?: string | null;
  request: Record<string, unknown>;
  paths: Record<string, unknown>;
};

export type PaperRunDetailResponse = ApiEnvelope & {
  id: string;
  metadata: Record<string, unknown>;
  orders: PreviewRecord[];
  order_events: PreviewRecord[];
  trades: PreviewRecord[];
  risk_breaches: PreviewRecord[];
};

export type RecentRunKind = "backtest" | "factor" | "paper";

export type RecentRun = {
  kind: RecentRunKind;
  run_id: string;
  source?: string | null;
  created_at?: string | null;
  summary: Record<string, unknown>;
};

export type RecentRunsResponse = ApiEnvelope & {
  total: number;
  generated_at: string;
  runs: RecentRun[];
};

export type AccountPositionView = {
  symbol: string;
  quantity: number;
  avg_cost: number;
  last_price: number;
  market_value: number;
  weight: number;
  unrealized_pnl: number;
  source_breakdown: Record<string, number>;
  price_kind: string;
  price_as_of: string | null;
};

export type PendingAccountOrderView = {
  order_id: string;
  created_at: string;
  symbol: string;
  side: string;
  quantity: number;
  limit_price: number;
  reserved_cash: number;
  reserved_quantity: number;
  source: string;
  reason: string;
  last_checked_price?: number | null;
  last_checked_price_kind?: string | null;
  last_checked_at?: string | null;
};

export type PaperAccountResponse = ApiEnvelope & {
  account_id: string;
  base_currency: string;
  initial_cash: number;
  cash: number;
  reserved_cash: number;
  available_cash: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  pnl_abs: number;
  pnl_pct: number;
  invested_pct: number;
  kill_switch: boolean;
  price_source: { kind: string; as_of: string | null };
  positions: AccountPositionView[];
  pending_orders: PendingAccountOrderView[];
  created_at: string;
  updated_at: string;
};

export type LedgerEntryView = {
  entry_id: string;
  timestamp: string;
  kind: string;
  source: string;
  symbol?: string | null;
  side?: string | null;
  quantity?: number | null;
  price?: number | null;
  gross_value?: number | null;
  commission?: number;
  price_kind?: string | null;
  realized_pnl_delta?: number;
  cash_after?: number;
  note?: string;
};

export type PaperLedgerResponse = ApiEnvelope & {
  total: number;
  limit: number;
  offset: number;
  entries: LedgerEntryView[];
};

export type ExperimentSummary = {
  id: string;
  path: string;
  best_run_id?: string | null;
  created_at?: string | null;
};

export type ExperimentsResponse = ApiEnvelope & {
  experiments: ExperimentSummary[];
};

export type ExperimentRunResponse = ApiEnvelope & {
  experiment_id: string;
  raw_experiment_id: string;
  provider: string;
  source: string;
  run_count: number;
  best_run_id?: string | null;
  paths: Record<string, unknown>;
};

export type ExperimentDetailResponse = ApiEnvelope & {
  id: string;
  path: string;
  experiment_config?: Record<string, unknown>;
  agent_summary?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  runs: PreviewRecord[];
  folds: PreviewRecord[];
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

export type AgentTaskResponse = ApiEnvelope & {
  candidate_id: string;
  status: string;
  path: string;
  metadata: Record<string, unknown>;
};

export type AgentReviewResponse = ApiEnvelope & {
  candidate_id: string;
  decision: "approve" | "reject";
  registration: "manual_required";
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

export type OptionsDailyTaskStatus = {
  status?: string | null;
  run_date?: string | null;
  provider?: string | null;
  strategies?: string[] | null;
  started_at?: string | null;
  finished_at?: string | null;
  failed_step?: string | null;
  error?: string | null;
  steps?: Record<string, Record<string, unknown>>;
  [key: string]: unknown;
};

export type OptionsDailyTaskStatusResponse = ApiEnvelope & {
  exists: boolean;
  status_path: string;
  status: OptionsDailyTaskStatus | null;
};

export type OptionsRadarResponse = ApiEnvelope & {
  run_date: string;
  universe_size: number;
  scanned_tickers: number;
  failed_tickers: Array<[string, string]>;
  is_stale?: boolean;
  snapshot_age_days?: number;
  expired_candidate_count?: number;
  candidates: OptionsRadarCandidate[];
};

export type OptionsRadarRunResponse = ApiEnvelope & {
  run_date: string;
  provider: string;
  universe_size: number;
  scanned_tickers: number;
  failed_tickers: Array<[string, string]>;
  candidate_count: number;
  data_path: string;
  meta_path: string;
};

export type OptionsRefreshResponse = ApiEnvelope & {
  kind: "universe" | "earnings" | "vix";
  source: string;
  status: string;
  row_count: number;
  output_path: string;
  fetched_at: string;
};

export type OptionsRadarSymbolResponse = ApiEnvelope & {
  ticker: string;
  run_date: string;
  candidate_count: number;
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
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 60_000);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      signal: controller.signal,
      headers: { accept: "application/json" },
    });
    if (!response.ok) {
      // Surface the backend's structured detail (e.g. {code, message}) instead
      // of an opaque "400 Bad Request" so users can tell a typo'd ticker from
      // OpenD being down.
      let detailText = "";
      try {
        const payload = (await response.json()) as { detail?: unknown };
        if (typeof payload.detail === "string") {
          detailText = payload.detail;
        } else if (payload.detail && typeof payload.detail === "object") {
          const detail = payload.detail as { message?: unknown; code?: unknown };
          const message = typeof detail.message === "string" ? detail.message : "";
          const code = typeof detail.code === "string" ? `[${detail.code}] ` : "";
          detailText = message ? `${code}${message}` : JSON.stringify(payload.detail);
        }
      } catch {
        // body not JSON — fall through to the status line
      }
      throw new Error(
        detailText ? `${response.status}: ${detailText}` : `${response.status} ${response.statusText}`,
      );
    }
    return (await response.json()) as T;
  } catch (error) {
    const aborted =
      (error instanceof DOMException && error.name === "AbortError") ||
      controller.signal.aborted;
    return {
      ...fallback,
      safety: fallback.safety ?? FALLBACK_SAFETY,
      apiError: aborted
        ? "Request timed out after 60s (backend may be waiting on a provider such as Futu OpenD)."
        : error instanceof Error
          ? error.message
          : "API unavailable",
    };
  } finally {
    clearTimeout(timeoutId);
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
  provider?: string,
) {
  const params = new URLSearchParams({ ticker, start, end, freq });
  if (provider) {
    params.set("provider", provider);
  }
  return apiGet<MarketDataHistoryResponse>(`/api/market-data/history?${params.toString()}`, {
    symbol: ticker,
    ticker,
    source: "fallback",
    frequency: freq,
    row_count: 0,
    rows: [],
    metadata: {
      provider: "fallback",
      requested_provider: provider ?? "default",
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
    benchmark: null,
    orders: [],
    positions: [],
    trade_blotter: [],
    attribution: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getReversalMomentumReplicationDetail(runId: string) {
  return apiGet<ReversalMomentumReplicationDetailResponse>(
    `/api/replications/reversal-momentum/${runId}`,
    {
      run_id: runId,
      metadata: {},
      result: {},
      safety: FALLBACK_SAFETY,
    },
  );
}

export function getStrategies() {
  return apiGet<StrategiesResponse>("/api/strategies", {
    strategies: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getUniverses() {
  return apiGet<UniversesResponse>("/api/universes", {
    universes: [],
    safety: FALLBACK_SAFETY,
  });
}

export type FactorLabQuery = {
  provider?: string;
  universeId?: string;
  symbol?: string;
  benchmarkSymbol?: string;
};

export function getFactorLabDashboard(query: FactorLabQuery = {}) {
  const provider = query.provider ?? "futu";
  const universeId = query.universeId ?? "etf";
  const symbol = (query.symbol ?? "QQQ").toUpperCase();
  const benchmarkSymbol = (query.benchmarkSymbol ?? symbol).toUpperCase();
  const params = new URLSearchParams({
    provider,
    universe_id: universeId,
    symbol,
    benchmark_symbol: benchmarkSymbol,
  });
  return apiGet<FactorLabResponse>(`/api/factors/lab?${params.toString()}`, {
    source: "fallback",
    benchmark_symbol: benchmarkSymbol,
    universe: {
      id: universeId,
      name: "--",
      description: "",
      symbols: [],
      benchmark_symbol: benchmarkSymbol,
    },
    factors: [],
    guardrails: {},
    cache: {},
    cross_sectional: { engine: "cross_sectional_health", rows: [] },
    timing: { engine: "single_symbol_timing", symbol, rows: [] },
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

export function getRecentRuns(limit = 6) {
  const params = new URLSearchParams({ limit: String(limit) });
  return apiGet<RecentRunsResponse>(`/api/runs/recent?${params.toString()}`, {
    total: 0,
    generated_at: "",
    runs: [],
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

const FALLBACK_ACCOUNT: PaperAccountResponse = {
  account_id: "default",
  base_currency: "USD",
  initial_cash: 1_000_000,
  cash: 1_000_000,
  reserved_cash: 0,
  available_cash: 1_000_000,
  equity: 1_000_000,
  realized_pnl: 0,
  unrealized_pnl: 0,
  pnl_abs: 0,
  pnl_pct: 0,
  invested_pct: 0,
  kill_switch: false,
  price_source: { kind: "none", as_of: null },
  positions: [],
  pending_orders: [],
  created_at: "",
  updated_at: "",
  safety: FALLBACK_SAFETY,
};

export function getPaperAccount() {
  return apiGet<PaperAccountResponse>("/api/paper/account", FALLBACK_ACCOUNT);
}

export function getPaperAccountLedger(limit = 50, offset = 0) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiGet<PaperLedgerResponse>(`/api/paper/account/ledger?${params.toString()}`, {
    total: 0,
    limit,
    offset,
    entries: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getExperiments() {
  return apiGet<ExperimentsResponse>("/api/experiments", {
    experiments: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getExperimentDetail(experimentId: string) {
  return apiGet<ExperimentDetailResponse>(`/api/experiments/${experimentId}`, {
    id: experimentId,
    path: "",
    runs: [],
    folds: [],
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
  provider = "polymarket",
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
    is_stale: false,
    snapshot_age_days: 0,
    expired_candidate_count: 0,
    candidates: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getOptionsRadarSymbol(ticker: string, date?: string) {
  const query = new URLSearchParams();
  if (date) {
    query.set("date", date);
  }
  return apiGet<OptionsRadarSymbolResponse>(
    `/api/options/daily-scan/symbol/${encodeURIComponent(ticker)}?${query.toString()}`,
    {
      ticker: ticker.toUpperCase(),
      run_date: date ?? "",
      candidate_count: 0,
      candidates: [],
      safety: FALLBACK_SAFETY,
    },
  );
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
