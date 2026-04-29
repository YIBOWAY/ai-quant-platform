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

export type BacktestSummary = {
  id: string;
  metrics?: {
    total_return?: number;
    sharpe?: number;
    max_drawdown?: number;
  };
};

export type BacktestsResponse = ApiEnvelope & {
  backtests: BacktestSummary[];
};

export type BenchmarkResponse = ApiEnvelope & {
  symbol: string;
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
  summary?: {
    order_count?: number;
    trade_count?: number;
    risk_breach_count?: number;
    final_equity?: number;
  };
};

export type PaperRunsResponse = ApiEnvelope & {
  paper_runs: PaperRunSummary[];
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

export type PredictionMarketResponse = ApiEnvelope & {
  markets: Array<{ market_id: string; question: string; outcomes: Array<{ name: string }> }>;
  order_books: Array<{ token_id: string; bids: unknown[]; asks: unknown[] }>;
  provider: string;
};

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

export function getSymbols() {
  return apiGet<SymbolsResponse>("/api/symbols", {
    symbols: ["SPY", "QQQ"],
    source: "fallback",
    safety: FALLBACK_SAFETY,
  });
}

export function getOhlcv(symbol = "SPY", start = "2024-01-02", end = "2024-01-12") {
  const params = new URLSearchParams({ symbol, start, end });
  return apiGet<OhlcvResponse>(`/api/ohlcv?${params.toString()}`, {
    symbol,
    source: "fallback",
    rows: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getFactors() {
  return apiGet<FactorsResponse>("/api/factors", {
    factors: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getBacktests() {
  return apiGet<BacktestsResponse>("/api/backtests", {
    backtests: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getBenchmark(symbol = "SPY", start = "2024-01-02", end = "2024-01-12") {
  const params = new URLSearchParams({ symbol, start, end });
  return apiGet<BenchmarkResponse>(`/api/benchmark?${params.toString()}`, {
    symbol,
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

export function getPredictionMarkets() {
  return apiGet<PredictionMarketResponse>("/api/prediction-market/markets", {
    markets: [],
    order_books: [],
    provider: "fallback",
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
