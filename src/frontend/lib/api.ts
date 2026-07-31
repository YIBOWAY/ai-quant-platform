import {
  buildBriefIssuePath,
  buildLatestBriefIssuePath,
  type BriefIssue,
  type BriefIssueEnvelope,
  type BriefSnapshot,
} from "./briefArchive";
import type { components as GeneratedApiComponents } from "./api.generated";
import {
  normalizeCandidateDetailResponse,
  normalizeCandidateListResponse,
} from "./hermes/candidateReadModel";
import {
  isHermesResultKind,
  isHermesResultResourceId,
} from "./hermes/resultsTypes";
import {
  normalizeHermesResultDetailResponse,
  normalizeHermesResultsResponse,
} from "./hermes/resultsReadModel";
import type {
  HermesResultKind,
  HermesResultsQuery,
} from "./hermes/resultsTypes";

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

export type BriefIssueResponse = BriefIssue;
export type BriefSnapshotResponse = BriefSnapshot;
export type BriefIssueEnvelopeResponse = BriefIssueEnvelope;
export type BriefIssueListResponse = {
  items: BriefIssue[];
  total: number;
  limit: number;
  offset: number;
  apiError?: string;
};

function buildBriefIssueListPath(locale: string, limit: number, offset: number) {
  const params = new URLSearchParams();
  params.set("locale", locale || "zh");
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return `/api/brief/issues?${params.toString()}`;
}

export type ErrorResponse = {
  detail: string;
  safety?: SafetyFooter | null;
};

export type HealthResponse = ApiEnvelope & {
  status: string;
  app_name: string;
  environment: string;
  data_provider: {
    configured_default: string;
    tiingo_token_present: boolean;
  };
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
  hermes_command_ledger: {
    database_configured: boolean;
    schema_ready: boolean;
    schema_version: number | null;
    workflow_binding_schema_ready: boolean;
    workflow_binding_schema_version: number | null;
    mutation_enabled: boolean;
    admission_mode?: "closed" | "candidate" | "release";
    admission_workspace_id?: string;
    configured_release_workspace_id?: string;
    candidate_admission_id?: string | null;
    candidate_admission_digest?: string | null;
    connector_liveness_ready?: boolean;
    connector_liveness_reason?: string;
    connector_worker_id?: string | null;
    connector_mode?: string | null;
    connector_heartbeat_age_seconds?: number | null;
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

export type OHLCVResponse = ApiEnvelope & {
  symbol: string;
  source: string;
  rows: OhlcvRow[];
};

export type OhlcvResponse = OHLCVResponse;

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

export type FactorCatalogResponse = ApiEnvelope & {
  factors: FactorMetadata[];
};

export type FactorsResponse = FactorCatalogResponse;

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

export type FactorRunRequestEchoResponse = {
  symbols: string[];
  start: string;
  end: string;
  provider: "sample" | "futu" | "tiingo";
  lookback: number;
  quantiles: number;
};

export type FactorRunPathsResponse = {
  factor_results: string;
  signals: string;
  ic: string;
  quantiles: string;
  report: string;
};

export type FactorRunResponse = ApiEnvelope & {
  run_id: string;
  source: string;
  row_count: number;
  signal_count: number;
  warnings: string[];
  request: FactorRunRequestEchoResponse;
  paths: FactorRunPathsResponse;
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

export type BacktestRunTimingsResponse = {
  data_fetch: number;
  engine: number;
  persist: number;
  total: number;
};

export type BacktestRunRequestEchoResponse = {
  symbols: string[];
  start: string;
  end: string;
  provider: "sample" | "futu" | "tiingo";
  strategy_id: string;
  universe_id?: string | null;
  factor_ids: string[];
  weights: Record<string, number>;
  benchmark_symbol: string;
  lookback: number;
  top_n: number;
  initial_cash: number;
  commission_bps: number;
  slippage_bps: number;
  min_order_value: number;
  whole_share_orders: boolean;
  rebalance_frequency: "every_bar" | "weekly" | "monthly";
  max_weight_per_symbol?: number | null;
  sector_cap?: number | null;
  sector_map: Record<string, string>;
};

export type BacktestRunMetricsResponse = {
  total_return: number;
  sharpe: number;
  max_drawdown: number;
};

export type BacktestPerformanceMetricsResponse = {
  total_return: number;
  annualized_return: number;
  volatility: number;
  sharpe: number;
  max_drawdown: number;
  turnover: number;
  attribution: Array<Record<string, number | string>>;
};

export type BacktestRunBenchmarkResponse = {
  symbol: string;
  source: string;
  metrics: BenchmarkMetrics;
};

export type BacktestRunPathsResponse = {
  equity_curve: string;
  trade_blotter: string;
  orders: string;
  positions: string;
  attribution: string;
  metrics: string;
  benchmark_curve: string;
  benchmark_metrics: string;
  report: string;
};

export type BacktestRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelling"
  | "cancelled";

export type BacktestRunResponse = ApiEnvelope & {
  run_id: string;
  kind: "backtest";
  status: "completed";
  created_at?: string | null;
  source: string;
  trade_count: number;
  order_count: number;
  warnings: string[];
  timings_ms: BacktestRunTimingsResponse;
  request: BacktestRunRequestEchoResponse;
  metrics: BacktestRunMetricsResponse;
  attribution: PreviewRecord[];
  benchmark: BacktestRunBenchmarkResponse;
  paths: BacktestRunPathsResponse;
};

export type BacktestJobStateResponse = ApiEnvelope & {
  run_id: string;
  kind: "backtest";
  status: BacktestRunStatus;
  created_at?: string | null;
  updated_at?: string | null;
  poll_url: string;
  result_url?: string | null;
  error?: Record<string, unknown> | null;
};

export type BacktestRunResultResponse = BacktestRunResponse | BacktestJobStateResponse;

export type BenchmarkMetrics = {
  total_return: number;
  annualized_return: number;
  volatility: number;
  sharpe: number;
  max_drawdown: number;
  turnover: number;
  attribution?: Array<Record<string, number | string>>;
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

export type ReversalMomentumReplicationRunResponse = ApiEnvelope & {
  paper: Record<string, unknown>;
  methodology: Record<string, unknown>;
  metrics: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  equity_curve: PreviewRecord[];
  monthly_returns: PreviewRecord[];
  positions: PreviewRecord[];
  legs: PreviewRecord[];
  warnings: string[];
  run_id: string;
  result_type: string;
  source: string;
  request: Record<string, unknown>;
  paths: Record<string, unknown>;
  artifact_path: string;
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

export type StrategyCatalogResponse = ApiEnvelope & {
  strategies: StrategyMetadata[];
};

export type StrategiesResponse = StrategyCatalogResponse;

export type StrategyRunResponse =
  | BacktestRunResponse
  | BacktestJobStateResponse
  | ReversalMomentumReplicationRunResponse;

export type UniverseDefinition = {
  id: string;
  name: string;
  description: string;
  symbols: string[];
  benchmark_symbol: string;
};

export type UniverseCatalogResponse = ApiEnvelope & {
  universes: UniverseDefinition[];
};

export type UniversesResponse = UniverseCatalogResponse;

export type FactorLabRow = Record<string, string | number | boolean | null>;

export type FactorLabWalkForwardResponse = {
  enabled: boolean;
  train_bars: number;
  validation_bars: number;
  step_bars: number;
  fold_count: number;
};

export type FactorLabLeakageAuditResponse = {
  status: "basic_passed" | "failed" | "empty";
  checked: boolean;
  rule?: string | null;
};

export type FactorLabGuardrailsResponse = {
  exploratory_only: boolean;
  warning: string;
  walk_forward: FactorLabWalkForwardResponse;
  leakage_audit: FactorLabLeakageAuditResponse;
};

export type FactorLabCacheKeyResponse = {
  provider: string;
  universe_id: string;
  symbol: string;
  benchmark_symbol: string;
  start: string;
  end: string;
  lookback: number;
};

export type FactorLabCacheResponse = {
  status: "cached" | "recomputed";
  path: string;
  key: FactorLabCacheKeyResponse;
};

export type FactorLabResponse = ApiEnvelope & {
  generated_at?: string;
  source: string;
  benchmark_symbol: string;
  universe: UniverseDefinition;
  factors: FactorMetadata[];
  guardrails: FactorLabGuardrailsResponse;
  cache: FactorLabCacheResponse;
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

export type PaperRunRequestEchoResponse = {
  symbols: string[];
  start: string;
  end: string;
  provider: "sample" | "futu" | "tiingo";
  initial_cash: number;
  lookback: number;
  top_n: number;
  max_fill_ratio_per_tick: number;
  enable_kill_switch: boolean;
};

export type PaperRunPathsResponse = {
  orders: string;
  order_events: string;
  trades: string;
  risk_breaches: string;
  report: string;
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
  request: PaperRunRequestEchoResponse;
  paths: PaperRunPathsResponse;
};

export type PaperRunDetailResponse = ApiEnvelope & {
  id: string;
  metadata: Record<string, unknown>;
  orders: PreviewRecord[];
  order_events: PreviewRecord[];
  trades: PreviewRecord[];
  risk_breaches: PreviewRecord[];
};

export type RecentRunKind = "backtest" | "factor" | "paper" | "replication";

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

export type AccountPositionResponse = {
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
  previous_close?: number | null;
  day_change_ratio?: number | null;
  day_change_source?: string | null;
  day_change_as_of?: string | null;
};

export type AccountPositionView = AccountPositionResponse;

export type PendingAccountOrderResponse = {
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

export type PendingAccountOrderView = PendingAccountOrderResponse;

export type PaperAccountPriceSourceResponse = {
  kind: string;
  as_of: string | null;
};

export type PaperAccountReconciliationDifferenceResponse = {
  field: string;
  expected: unknown;
  actual: unknown;
};

export type PaperAccountReconciliationResponse = {
  status: "in_sync" | "different" | "unavailable" | "not_applicable";
  account_id: string;
  source: string;
  target: string | null;
  checked_at: string;
  expected_summary: Record<string, unknown>;
  actual_summary: Record<string, unknown>;
  differences: PaperAccountReconciliationDifferenceResponse[];
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
  price_source: PaperAccountPriceSourceResponse;
  positions: AccountPositionResponse[];
  pending_orders: PendingAccountOrderResponse[];
  created_at: string;
  updated_at: string;
  storage_mode?: "file" | "mirror" | "canonical" | null;
  stale?: boolean;
  warnings?: string[];
  reconciliation?: PaperAccountReconciliationResponse | null;
};

export type PaperAccountSnapshotResponse = ApiEnvelope & {
  account_id: string;
  account_exists: boolean;
  account: PaperAccountResponse | null;
};

export type PaperAccountOrderOutcomeResponse = {
  order_id?: string | null;
  status: string;
  symbol: string;
  side: string;
  requested_quantity: number;
  filled_quantity: number;
  price?: number | null;
  price_kind?: string | null;
  rejected_reason?: string | null;
};

export type PaperAccountOrderOutcome = PaperAccountOrderOutcomeResponse;

export type PaperAccountOrderResponse = ApiEnvelope & {
  order: PaperAccountOrderOutcomeResponse;
  account: PaperAccountResponse;
};

export type PaperAccountOrdersProcessResponse = ApiEnvelope & {
  orders: PaperAccountOrderOutcomeResponse[];
  account: PaperAccountResponse;
};

export type PaperAccountRebalanceSummaryResponse = {
  strategy_id: string;
  as_of?: string | null;
  aborted: boolean;
  target_weights: Record<string, number>;
  note?: string | null;
  orders: PaperAccountOrderOutcomeResponse[];
};

export type PaperAccountRebalanceSummary = PaperAccountRebalanceSummaryResponse;

export type PaperAccountRebalanceResponse = ApiEnvelope & {
  rebalance: PaperAccountRebalanceSummaryResponse;
  account: PaperAccountResponse;
};

export type PaperStrategyConfigResponse = {
  strategy_config_id: string;
  version: number;
  name: string;
  description: string;
  strategy_id: string;
  universe_id?: string | null;
  symbols: string[];
  factor_ids: string[];
  weights: Record<string, number>;
  lookback: number;
  top_n: number;
  rebalance_frequency: string;
  max_weight_per_symbol: number;
  min_order_value: number;
  data_provider: string;
  execution_timing: string;
  created_at: string;
  updated_at: string;
  archived: boolean;
  tags: string[];
  metadata: Record<string, unknown>;
};

export type PaperStrategyConfigMutationResponse = ApiEnvelope & {
  config: PaperStrategyConfigResponse;
};

export type PaperStrategyConfigsResponse = ApiEnvelope & {
  configs: PaperStrategyConfigResponse[];
};

export type PaperStrategySleeveMode = "signal_only" | "allocated";
export type PaperStrategySleeveStatus = "running" | "paused" | "stopped";

export type PaperStrategySleeveResponse = {
  sleeve_id: string;
  account_id: string;
  strategy_config_id: string;
  strategy_config_version: number;
  mode: PaperStrategySleeveMode;
  status: PaperStrategySleeveStatus;
  initial_allocated_cash: number;
  cash: number;
  created_at: string;
  updated_at: string;
  paused_at?: string | null;
  stopped_at?: string | null;
  stop_reason?: string | null;
  metadata: Record<string, unknown>;
};

export type PaperStrategySleeveMutationResponse = ApiEnvelope & {
  sleeve: PaperStrategySleeveResponse;
  account: PaperAccountResponse;
};

export type PaperStrategySleevesResponse = ApiEnvelope & {
  sleeves: PaperStrategySleeveResponse[];
};

export type PaperStrategySleeveLotResponse = {
  lot_id: string;
  account_id: string;
  sleeve_id: string;
  symbol: string;
  quantity: number;
  avg_cost: number;
  opened_at: string;
  updated_at: string;
  source: string;
};

export type PaperStrategySignalResponse = {
  signal_id: string;
  sleeve_id: string;
  strategy_config_id: string;
  strategy_config_version: number;
  signal_date: string;
  generated_at: string;
  data_provider: string;
  data_as_of?: string | null;
  target_weights: Record<string, number>;
  proposed_orders: Array<Record<string, unknown>>;
  warnings: string[];
  status: "generated" | "data_unavailable" | "invalid";
  execution_blocked_reason?: string | null;
  metadata: Record<string, unknown>;
};

export type PaperStrategySignalMutationResponse = ApiEnvelope & {
  signal: PaperStrategySignalResponse;
};

export type PaperStrategyExecutionStatus =
  | "pending"
  | "filled"
  | "partially_filled"
  | "skipped"
  | "blocked"
  | "missed_window"
  | "failed"
  | "cancelled";

export type PaperStrategyExecutionOrderResponse = {
  symbol: string;
  side: string;
  target_weight?: number | null;
  current_value?: number | null;
  target_value?: number | null;
  notional_delta?: number | null;
  reference_price?: number | null;
  estimated_quantity?: number | null;
  reason?: string | null;
  account_id?: string | null;
  metadata: Record<string, unknown>;
};

export type PaperStrategyExecutionFillResponse = {
  fill_id: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  gross_value: number;
  price_kind: string;
  filled_at: string;
  metadata: Record<string, unknown>;
};

export type PaperStrategyExecutionPlanResponse = {
  execution_id: string;
  sleeve_id: string;
  account_id: string;
  signal_id: string;
  strategy_config_id: string;
  strategy_config_version: number;
  execution_window: string;
  target_date?: string | null;
  created_at: string;
  updated_at: string;
  status: PaperStrategyExecutionStatus;
  blocked_reason?: string | null;
  orders: PaperStrategyExecutionOrderResponse[];
  fills: PaperStrategyExecutionFillResponse[];
  warnings: string[];
  metadata: Record<string, unknown>;
};

export type PaperStrategyExecutionMutationResponse = ApiEnvelope & {
  execution: PaperStrategyExecutionPlanResponse;
};

export type PaperStrategyExecutionProcessResponse = ApiEnvelope & {
  processed_count: number;
  filled_count: number;
  blocked_count: number;
  executions: PaperStrategyExecutionPlanResponse[];
  account: PaperAccountResponse;
};

export type PaperStrategySleeveDetailResponse = ApiEnvelope & {
  sleeve: PaperStrategySleeveResponse;
  lots: PaperStrategySleeveLotResponse[];
  signals: PaperStrategySignalResponse[];
  executions: PaperStrategyExecutionPlanResponse[];
};

export type PaperStrategyOpsStatus = {
  target_date: string;
  sleeve_count: number;
  pending_sleeve_count: number;
  running_sleeve_count: number;
  pending_execution_count: number;
  pending_due_count: number;
  filled_count: number;
  blocked_count: number;
  recovery_required_count: number;
  pending_journal_count: number;
  corrupt_journal_count: number;
};

export type StrategyConfigResponse = PaperStrategyConfigResponse;
export type StrategySleeveResponse = PaperStrategySleeveResponse;
export type SleeveLotResponse = PaperStrategySleeveLotResponse;
export type StrategySignalResponse = PaperStrategySignalResponse;
export type StrategyExecutionOrderResponse = PaperStrategyExecutionOrderResponse;
export type StrategyExecutionFillResponse = PaperStrategyExecutionFillResponse;
export type StrategyExecutionPlanResponse = PaperStrategyExecutionPlanResponse;
export type StrategyConfigMutationResponse = PaperStrategyConfigMutationResponse;
export type StrategyConfigsResponse = PaperStrategyConfigsResponse;
export type StrategySleevesResponse = PaperStrategySleevesResponse;
export type StrategySleeveDetailResponse = PaperStrategySleeveDetailResponse;
export type StrategySignalMutationResponse = PaperStrategySignalMutationResponse;
export type StrategyExecutionMutationResponse = PaperStrategyExecutionMutationResponse;
export type StrategyExecutionProcessResponse = PaperStrategyExecutionProcessResponse;
export type StrategyOpsStatusResponse = ApiEnvelope & {
  status: PaperStrategyOpsStatus;
};
export type StrategySleeveMutationResponse = PaperStrategySleeveMutationResponse;

export type LedgerEntryResponse = {
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

export type LedgerEntryView = LedgerEntryResponse;

export type PaperLedgerResponse = ApiEnvelope & {
  total: number;
  limit: number;
  offset: number;
  entries: LedgerEntryResponse[];
};

export type PaperAccountOrderHistoryRowResponse = {
  event_id: string;
  order_id?: string | null;
  timestamp: string;
  status: string;
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
  cash_after?: number | null;
  note?: string | null;
};

export type PaperAccountBalanceHistoryRowResponse = {
  event_id: string;
  timestamp: string;
  kind: string;
  source: string;
  cash_after: number;
  cash_delta: number;
  note?: string | null;
};

export type PaperAccountActivityResponse = ApiEnvelope & {
  account: PaperAccountResponse;
  pending_orders: PendingAccountOrderResponse[];
  order_history: PaperAccountOrderHistoryRowResponse[];
  balance_history: PaperAccountBalanceHistoryRowResponse[];
  trade_log: LedgerEntryResponse[];
  pending_order_total: number;
  order_history_total: number;
  balance_history_total: number;
  trade_log_total: number;
  limit: number;
  offset: number;
};

export type PaperAccountEquityCurvePointResponse = {
  timestamp: string;
  equity: number;
  cash: number;
  market_value: number;
  realized_pnl: number;
  source: "ledger" | "current_quote";
  event_id?: string | null;
  event_kind?: string | null;
  symbol?: string | null;
  side?: string | null;
  quantity?: number | null;
  price?: number | null;
  price_source: PaperAccountPriceSourceResponse;
};

export type PaperAccountEquityCurveResponse = ApiEnvelope & {
  account_id: string;
  account_exists: boolean;
  total: number;
  limit: number;
  offset: number;
  points: PaperAccountEquityCurvePointResponse[];
};

export type PaperPerformanceRange = "7d" | "1m" | "3m";

export type PaperAccountPerformancePointResponse = {
  date: string;
  return_ratio: number;
  equity: number | null;
  close: number | null;
};

export type PaperAccountPerformanceSeriesResponse = {
  id: string;
  kind: "paper" | "benchmark";
  label: string;
  symbol: string | null;
  status: "available" | "partial" | "unavailable";
  source: string | null;
  as_of: string | null;
  error_code: string | null;
  points: PaperAccountPerformancePointResponse[];
};

export type PaperAccountPerformanceResponse = ApiEnvelope & {
  account_id: string;
  account_exists: boolean;
  range: PaperPerformanceRange;
  granularity: "1d";
  benchmarks: Array<"SPY" | "QQQ">;
  requested_start: string;
  requested_end: string;
  actual_start: string | null;
  actual_end: string | null;
  coverage_complete: boolean;
  series: PaperAccountPerformanceSeriesResponse[];
  warnings: string[];
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

export type ExperimentRunPathsResponse = {
  config: string;
  runs: string;
  folds: string;
  agent_summary: string;
  report: string;
};

export type ExperimentRunResponse = ApiEnvelope & {
  experiment_id: string;
  raw_experiment_id: string;
  provider: string;
  source: string;
  run_count: number;
  best_run_id?: string | null;
  paths: ExperimentRunPathsResponse;
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

type HermesSchemas = GeneratedApiComponents["schemas"];

export type CandidateSummary = HermesSchemas["CandidateSummary"];
export type HermesArtifact = HermesSchemas["HermesArtifactItemResponse"];
export type HermesArtifactKind =
  HermesSchemas["HermesArtifactSourceResponse"]["kind"];
export type HermesArtifactQuality = HermesArtifact["quality"];
export type HermesPortfolioRiskArtifactData =
  HermesSchemas["HermesPortfolioRiskData"];
export type HermesPredictionArtifactData = HermesSchemas["HermesPredictionData"];
export type HermesForesightCandidateData =
  HermesSchemas["HermesForesightCandidate"];
export type HermesMarketForesightArtifactData =
  HermesSchemas["HermesMarketForesightData"];
export type HermesWeeklyReviewArtifactData =
  HermesSchemas["HermesWeeklyReviewData"];
export type HermesOpportunitySummaryArtifactData =
  HermesSchemas["HermesOpportunitySummaryData"];
export type HermesAutomationStatusArtifactData =
  HermesSchemas["HermesAutomationStatusData"];
export type HermesArtifactSource =
  HermesSchemas["HermesArtifactSourceResponse"];
export type HermesArtifactWarning =
  HermesSchemas["HermesArtifactWarningResponse"];
export type HermesArtifactShelfEnvelope = ApiEnvelope &
  HermesSchemas["HermesArtifactFeedResponse"];

export type AgentCandidatesResponse = ApiEnvelope &
  HermesSchemas["AgentCandidatesResponse"];

export type AgentCandidateDetailResponse = ApiEnvelope &
  HermesSchemas["AgentCandidateDetailResponse"];

export type AgentTaskResponse = ApiEnvelope & {
  candidate_id: string;
  status: string;
  path: string;
  metadata: Record<string, unknown>;
  manifest_digest?: string | null;
};

export type AgentReviewResponse = ApiEnvelope & {
  candidate_id: string;
  decision: "approve" | "reject";
  registration: "manual_required";
  manifest_digest?: string | null;
};

export type AgentReviewRequest = {
  decision: "approve" | "reject";
  note: string;
  expected_manifest_digest: string;
  expected_status: "pending";
};

export type AgentLLMConfigResponse = ApiEnvelope & {
  provider: string;
  model: string | null;
  base_url: string | null;
  timeout: number;
  has_api_key: boolean;
};

export type AgentLlmConfigResponse = AgentLLMConfigResponse;

export type PredictionMarketMarketsResponse = ApiEnvelope & {
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

export type PredictionMarketResponse = PredictionMarketMarketsResponse;

export type PredictionMarketCandidateResponse = {
  market_id: string;
  condition_id: string;
  scanner_id: string;
  description: string;
  edge_bps: number;
  prices: Record<string, number>;
  direction: "underpriced_complete_set" | "overpriced_complete_set";
  created_at: string;
  candidate_id: string;
};

export type PredictionMarketCandidate = PredictionMarketCandidateResponse;

export type PredictionMarketScanResponse = ApiEnvelope & {
  candidates: PredictionMarketCandidate[];
  report_path: string;
  provider: string;
  cache_status?: string;
};

export type PredictionMarketProposedLeg = {
  token_id: string;
  side: "buy" | "sell";
  price: number;
  size: number;
};

export type PredictionMarketProposedTrade = {
  proposal_id: string;
  opportunity: PredictionMarketCandidate;
  legs: PredictionMarketProposedLeg[];
  capital: number;
  expected_profit: number;
  dry_run: boolean;
  threshold_passed: boolean;
  created_at: string;
};

export type PredictionMarketDryArbitrageResponse = ApiEnvelope & {
  proposed_trades: PredictionMarketProposedTrade[];
  report_path: string;
  provider: string;
  cache_status?: string;
};

export type PredictionMarketBacktestRunResponse = ApiEnvelope & {
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

export type PredictionMarketBacktestResponse = PredictionMarketBacktestRunResponse;

export type PredictionMarketRunResponse =
  | PredictionMarketScanResponse
  | PredictionMarketDryArbitrageResponse
  | PredictionMarketBacktestRunResponse;

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

export type PredictionMarketTimeseriesBacktestRunResponse = ApiEnvelope & {
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

export type PredictionMarketTimeseriesResponse = PredictionMarketTimeseriesBacktestRunResponse;

export type PredictionMarketBacktestResultResponse = ApiEnvelope & {
  run_id: string;
  result: Record<string, unknown>;
  chart_index: {
    charts: Array<{ name: string; path: string; title: string; url?: string }>;
  };
  report_path: string;
};

export type PredictionMarketBacktestDetailResponse = PredictionMarketBacktestResultResponse;

export type PredictionMarketTimeseriesBacktestResultResponse = ApiEnvelope & {
  run_id: string;
  result: Record<string, unknown>;
  chart_index: {
    charts: Array<{ name: string; path: string; title: string; url: string }>;
  };
  report_path: string;
  report_url: string;
};

export type PredictionMarketTimeseriesDetailResponse =
  PredictionMarketTimeseriesBacktestResultResponse;

export type OptionsRadarCandidateResponse = {
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

export type OptionsRadarCandidate = OptionsRadarCandidateResponse;

export type OptionsScreenerCandidate = {
  symbol: string;
  underlying: string;
  strategy_type: "sell_put" | "covered_call";
  option_type: "PUT" | "CALL";
  expiry: string;
  strike: number;
  underlying_price: number;
  bid?: number | null;
  ask?: number | null;
  mid?: number | null;
  volume?: number | null;
  open_interest?: number | null;
  implied_volatility?: number | null;
  historical_volatility?: number | null;
  hv_iv_ratio?: number | null;
  delta?: number | null;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
  premium_per_contract?: number | null;
  moneyness?: number | null;
  distance_pct?: number | null;
  days_to_expiry?: number | null;
  annualized_yield?: number | null;
  spread_pct?: number | null;
  trend_pass?: boolean | null;
  hv_iv_pass?: boolean | null;
  avg_daily_volume?: number | null;
  market_cap?: number | null;
  iv_rank?: number | null;
  earnings_date?: string | null;
  market_regime?: "Normal" | "Elevated" | "Panic" | "Unknown" | null;
  market_regime_penalty: number;
  rating: "Strong" | "Watch" | "Avoid";
  notes: string[];
};

export type OptionsScreenerResult = ApiEnvelope & {
  ticker: string;
  provider: "futu";
  strategy_type: "sell_put" | "covered_call";
  expiration?: string | null;
  scanned_expirations: string[];
  expiration_count: number;
  underlying_price: number;
  historical_volatility?: number | null;
  trend_reference?: number | null;
  ema_21?: number | null;
  sma_50?: number | null;
  hv_iv_threshold?: number | null;
  hv_iv_pass_count: number;
  hv_iv_contract_count: number;
  hv_iv_min?: number | null;
  hv_iv_max?: number | null;
  market_regime?: "Normal" | "Elevated" | "Panic" | "Unknown" | null;
  market_regime_penalty: number;
  market_regime_w_vix?: number | null;
  market_regime_vix_density?: number | null;
  market_regime_term_ratio?: number | null;
  candidates: OptionsScreenerCandidate[];
  rejected_count: number;
  rejection_summary: Record<string, number>;
  assumptions: string[];
};

export type BuySideStrategyType =
  | "long_call"
  | "bull_call_spread"
  | "leaps_call"
  | "leaps_call_spread";

export type BuySideViewType =
  | "long_term_aggressive_bullish"
  | "long_term_conservative_bullish"
  | "short_term_speculative_bullish"
  | "short_term_conservative_bullish"
  | "event_driven_bullish";

export type BuySideVolatilityView =
  | "auto"
  | "prefer_low_iv"
  | "expect_iv_crush"
  | "expect_iv_expansion";

export type BuySideRiskPreference = "aggressive" | "balanced" | "conservative";

export type BuySideEventRisk =
  | "none"
  | "earnings"
  | "fomc"
  | "cpi"
  | "product_event"
  | "user_defined";

export type BuySidePrimaryRiskSource =
  | "direction"
  | "time"
  | "volatility"
  | "liquidity";

export type BuySideMarketRegime = "Normal" | "Elevated" | "Panic" | "Unknown";

export type BuySideUserScenarioPnL = {
  label: string;
  probability: number;
  spot_change_pct: number;
  iv_change_vol_points: number;
  days_passed: number;
};

export type BuySideDecisionThesis = {
  ticker: string;
  spot_price: number;
  view_type: BuySideViewType;
  target_price: number;
  target_date: string;
  max_loss_budget?: number | null;
  risk_preference: BuySideRiskPreference;
  allow_capped_upside: boolean;
  avoid_high_iv: boolean;
  volatility_view: BuySideVolatilityView;
  event_risk: BuySideEventRisk;
  expected_iv_change_vol_points?: number | null;
  preferred_dte_range?: [number, number] | null;
  iv_rank?: number | null;
  historical_volatility?: number | null;
  as_of_date?: string | null;
  user_scenarios?: BuySideUserScenarioPnL[];
  scenario_spot_changes?: number[];
  scenario_iv_changes?: number[];
  scenario_days_passed?: number[];
};

export type BuySideStrategyLeg = {
  symbol: string;
  option_type: "CALL" | "PUT" | "call" | "put";
  side: "long" | "short";
  action?: "buy" | "sell";
  expiry: string;
  expiration?: string;
  strike: number;
  spot?: number;
  as_of_date?: string | null;
  bid?: number | null;
  ask?: number | null;
  last?: number | null;
  mid_price?: number | null;
  premium?: number | null;
  quantity: number;
  contract_size: number;
  implied_volatility?: number | null;
  delta?: number | null;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
  rho?: number | null;
  volume?: number | null;
  open_interest?: number | null;
  update_time?: string | null;
  warnings?: string[];
  spread_abs?: number | null;
  spread_pct?: number | null;
  call_moneyness?: number;
  dte?: number;
  is_tradable?: boolean;
};

export type BuySideScenarioSummary = {
  best_case_pnl?: number | null;
  worst_case_pnl?: number | null;
  flat_spot_iv_crush_pnl?: number | null;
  spot_up_iv_down_pnl?: number | null;
  theta_only_pnl?: number | null;
  probability_not_calculated: boolean;
};

export type BuySideScenarioContribution = {
  label: string;
  probability: number;
  pnl: number;
  expected_value_contribution: number;
  weighted_pnl?: number;
};

export type BuySideScenarioEv = {
  expected_value: number;
  contributions: BuySideScenarioContribution[];
};

export type BuySideRecommendation = {
  strategy_type: BuySideStrategyType;
  score: number;
  rank: number;
  one_line_summary: string;
  key_reasons: string[];
  key_risks: string[];
  max_loss?: number | null;
  max_profit?: number | null;
  net_debit?: number | null;
  legs: BuySideStrategyLeg[];
  break_even?: number | null;
  required_move_pct?: number | null;
  theta_burn_7d_pct?: number | null;
  estimated_iv_crush_loss_pct?: number | null;
  liquidity_score?: number | null;
  risk_reward?: number | null;
  expected_move_pct?: number | null;
  target_vs_expected_move_ratio?: number | null;
  buyer_friendliness_score?: number | null;
  iv_crash_risk_score?: number | null;
  risk_attribution: Record<BuySidePrimaryRiskSource, number>;
  primary_risk_source: BuySidePrimaryRiskSource;
  market_regime?: BuySideMarketRegime | null;
  market_regime_penalty?: number | null;
  warnings: string[];
  scenario_summary?: BuySideScenarioSummary | null;
  scenario_ev?: BuySideScenarioEv | null;
  demotion_badge?: string | null;
  demotion_reason?: string | null;
};

export type BuySideAssistantResponse = ApiEnvelope & {
  ticker: string;
  generated_at?: string;
  thesis: BuySideDecisionThesis;
  recommendations: BuySideRecommendation[];
  assumptions: string[];
  warnings?: string[];
};

export type OptionContract = {
  symbol?: string;
  option_type: string;
  expiry?: string;
  strike?: number | null;
  bid?: number | null;
  ask?: number | null;
  last?: number | null;
  volume?: number | null;
  open_interest?: number | null;
  implied_volatility?: number | null;
  delta?: number | null;
  [key: string]: unknown;
};

export type OptionsSnapshotResponse = ApiEnvelope & {
  success: boolean;
  ticker: string;
  source: string;
  price: number;
  nearest_expiry: string;
  atm_iv?: number | null;
  hv_30d?: number | null;
  iv_rank?: number | null;
  iv_percentile?: number | null;
  iv_rank_source: string;
  vrp?: number | null;
  vrp_level?: string | null;
  assumptions: string[];
};

export type OptionsExpirationsResponse = ApiEnvelope & {
  ticker: string;
  source: string;
  expirations: Array<Record<string, unknown>>;
};

export type OptionsChainResponse = ApiEnvelope & {
  ticker: string;
  source: string;
  expiration: string;
  option_type: string;
  contracts: OptionContract[];
};

export type OptionsVolSurface = {
  moneyness_axis: number[];
  expiry_axis: string[];
  iv_grid: Array<Array<number | null>>;
  points: Array<Record<string, unknown>>;
};

export type OptionsVolSurfaceResponse = ApiEnvelope & {
  success: boolean;
  ticker: string;
  source: string;
  price: number;
  surface: OptionsVolSurface;
  atm_term_structure: Record<string, number>;
  shape: string;
  assumptions: string[];
};

export type OptionsVolSmile = {
  strikes: Array<number | null>;
  ivs: Array<number | null>;
  deltas: Array<number | null>;
  option_types: string[];
  moneyness: Array<number | null>;
};

export type OptionsVolSmileResponse = ApiEnvelope & {
  success: boolean;
  ticker: string;
  source: string;
  price: number;
  expiry: string;
  dte: number;
  smile: OptionsVolSmile;
  skew_metrics: Record<string, number | null>;
  shape: string;
  assumptions: string[];
};

export type OptionsGreeksResponse = ApiEnvelope & {
  price: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho: number;
  charm: number;
  vanna: number;
  volga: number;
};

export type OptionsImpliedVolatilityResponse = ApiEnvelope & {
  implied_volatility: number;
};

export type OptionsSimulationPnlAtExpiry = {
  price_axis: number[];
  pnl_axis: number[];
  [key: string]: unknown;
};

export type OptionsSimulationResponse = ApiEnvelope & {
  ticker: string;
  price: number;
  position: Record<string, unknown>;
  pnl_at_expiry: OptionsSimulationPnlAtExpiry;
  breakevens: number[];
  max_profit?: number | null;
  max_loss?: number | null;
  risk_reward_ratio?: number | null;
  scenarios: Record<string, unknown>;
  assumptions: string[];
};

export type OptionsStrategyTemplatesResponse = ApiEnvelope & {
  templates: Array<Record<string, unknown>>;
};

export type OptionsStrategyBuildResponse = ApiEnvelope & {
  mode: string;
  template_id: string;
  strategy: string;
  spot: number;
  expiry_days: number;
  legs: Array<Record<string, unknown>>;
  net_debit: number;
  max_profit?: number | null;
  max_loss?: number | null;
  breakevens: number[];
  risk_reward_ratio?: number | null;
  assumptions: string[];
};

export type OptionsStrategyRank = {
  template_id: string;
  strategy: string;
  score: number;
  net_debit?: number | null;
  max_profit?: number | null;
  max_loss?: number | null;
  breakevens: number[];
  rating: string;
  [key: string]: unknown;
};

export type OptionsStrategyRankResponse = ApiEnvelope & {
  success: boolean;
  market_view: string;
  rankings: OptionsStrategyRank[];
  assumptions: string[];
};

export type OptionsContractRank = {
  symbol: string;
  option_type: string;
  strike?: number | null;
  bid?: number | null;
  ask?: number | null;
  mid?: number | null;
  spread_pct?: number | null;
  volume?: number | null;
  open_interest?: number | null;
  implied_volatility?: number | null;
  delta?: number | null;
  score: number;
  rating: string;
  subscores: Record<string, number>;
  warnings: string[];
  [key: string]: unknown;
};

export type OptionsContractScoreResponse = ApiEnvelope & {
  success: boolean;
  objective: string;
  spot: number;
  ranked_contracts: OptionsContractRank[];
  assumptions: string[];
};

export type OptionsBullPutSignalResponse = ApiEnvelope & {
  success: boolean;
  fear_score: number;
  enter_signal: boolean;
  selected_spread?: Record<string, unknown> | null;
  reasons: string[];
  assumptions: string[];
};

export type OptionsFearScoreResponse = ApiEnvelope & {
  success: boolean;
  fear_score: number;
  tier: string;
  components: Record<string, unknown>;
  bull_put_spread_signal: boolean;
  assumptions: string[];
};

export type OptionsMarketSentimentResponse = ApiEnvelope & {
  success: boolean;
  sentiment_score: number;
  regime: string;
  components: Record<string, unknown>;
  assumptions: string[];
};

export type OptionsIvRankResponse = ApiEnvelope & {
  success: boolean;
  ticker: string;
  current_iv?: number | null;
  sample_count: number;
  iv_rank?: number | null;
  iv_percentile?: number | null;
  zone: string;
  assumptions: string[];
};

export type OptionsEarningsCrushResponse = ApiEnvelope & {
  success: boolean;
  ticker: string;
  sample_count: number;
  average_crush_pct?: number | null;
  expected_post_event_iv?: number | null;
  implied_move_pct?: number | null;
  strategy_tag: string;
  assumptions: string[];
};

export type OptionsHedgeAdvisorResponse = ApiEnvelope & {
  success: boolean;
  ticker: string;
  situation: Record<string, unknown>;
  structures: Array<Record<string, unknown>>;
  assumptions: string[];
};

export type OptionsUnusualActivityResponse = ApiEnvelope & {
  success: boolean;
  events: Array<Record<string, unknown>>;
  assumptions: string[];
};

export type OptionsWatchlistResponse = ApiEnvelope & {
  watchlist: Array<Record<string, unknown>>;
};

export type OptionsAlertsEvaluationResponse = ApiEnvelope & {
  success: boolean;
  ticker: string;
  triggered_alerts: Array<Record<string, unknown>>;
  assumptions: string[];
};

export type OptionsResearchHealthCheckResponse = ApiEnvelope & {
  success: boolean;
  health_score: number;
  stale_profiles: string[];
  missing_thesis: string[];
  assumptions: string[];
};

export type OptionsSignalsResponse =
  | OptionsImpliedVolatilityResponse
  | OptionsBullPutSignalResponse
  | OptionsFearScoreResponse
  | OptionsIvRankResponse
  | OptionsMarketSentimentResponse
  | OptionsSnapshotResponse
  | OptionsEarningsCrushResponse
  | OptionsHedgeAdvisorResponse
  | OptionsUnusualActivityResponse;

export type OptionsResearchOpsResponse =
  | OptionsStrategyTemplatesResponse
  | OptionsStrategyBuildResponse
  | OptionsWatchlistResponse
  | OptionsAlertsEvaluationResponse
  | OptionsResearchHealthCheckResponse
  | OptionsHedgeAdvisorResponse;

export type OptionsDailyScanDatesResponse = ApiEnvelope & {
  dates: string[];
};

export type OptionsRadarDatesResponse = OptionsDailyScanDatesResponse;

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

export type OptionsDailyScanStatusResponse = ApiEnvelope & {
  exists: boolean;
  status_path: string;
  status: OptionsDailyTaskStatus | null;
};

export type OptionsDailyTaskStatusResponse = OptionsDailyScanStatusResponse;

export type OptionsDailyScanResponse = ApiEnvelope & {
  run_date: string;
  universe_size: number;
  scanned_tickers: number;
  failed_tickers: Array<[string, string]>;
  is_stale: boolean;
  snapshot_age_days: number;
  expired_candidate_count: number;
  candidates: OptionsRadarCandidate[];
};

export type OptionsRadarResponse = OptionsDailyScanResponse;

export type OptionsDailyScanRunResponse = ApiEnvelope & {
  run_date: string;
  provider: "sample" | "futu";
  universe_size: number;
  scanned_tickers: number;
  failed_tickers: Array<[string, string]>;
  candidate_count: number;
  data_path: string;
  meta_path: string;
};

export type OptionsRadarRunResponse = OptionsDailyScanRunResponse;

export type OptionsRefreshResponse = ApiEnvelope & {
  kind: "universe" | "earnings" | "vix";
  source: string;
  status: string;
  row_count: number;
  output_path: string;
  fetched_at: string;
  warning?: string | null;
};

export type OptionsDailyScanSymbolResponse = ApiEnvelope & {
  ticker: string;
  run_date: string;
  candidate_count: number;
  candidates: OptionsRadarCandidate[];
};

export type OptionsRadarSymbolResponse = OptionsDailyScanSymbolResponse;

export type AiHotResearchSafety = {
  research_only: boolean;
  not_investment_advice: boolean;
  does_not_trigger_trading: boolean;
  verify_original_source: boolean;
};

export type NewsPreference = "auto" | "aihot" | "horizon";
export type NewsServedFrom = "primary" | "failover" | "cache" | "forced";

export type NewsFailoverStatus = {
  auto_enabled?: boolean;
  order?: string[];
};

export type AiHotItem = {
  id: string;
  title: string;
  title_en?: string | null;
  url: string;
  source: string;
  published_at?: string | null;
  summary?: string | null;
  category?: string | null;
  score?: number | null;
  selected?: boolean | null;
  raw?: Record<string, unknown>;
};

export type AiHotItemResponse = AiHotItem;

export type AiHotItemsResponse = ApiEnvelope & {
  provider: "aihot" | string;
  provider_beta: boolean;
  fetched_at: string;
  count: number;
  has_next: boolean;
  next_cursor?: string | null;
  items: AiHotItem[];
  warnings: string[];
  research_safety: AiHotResearchSafety;
  preference?: NewsPreference | string;
  served_from?: NewsServedFrom;
};

export type AiHotDailyResponse = ApiEnvelope & {
  provider: "aihot" | string;
  provider_beta: boolean;
  fetched_at: string;
  date: string;
  generated_at?: string | null;
  window_start?: string | null;
  window_end?: string | null;
  lead?: Record<string, unknown> | null;
  sections: Array<Record<string, unknown>>;
  flashes: Array<Record<string, unknown>>;
  warnings: string[];
  research_safety: AiHotResearchSafety;
  raw?: Record<string, unknown>;
  preference?: NewsPreference | string;
  served_from?: NewsServedFrom;
};

export type AiHotDailyIndex = {
  date: string;
  generated_at?: string | null;
  lead_title?: string | null;
  raw?: Record<string, unknown>;
};

export type AiHotDailyIndexResponse = AiHotDailyIndex;

export type AiHotDailiesResponse = ApiEnvelope & {
  provider: "aihot" | string;
  provider_beta: boolean;
  fetched_at: string;
  count: number;
  items: AiHotDailyIndex[];
  warnings: string[];
  research_safety: AiHotResearchSafety;
  preference?: NewsPreference | string;
  served_from?: NewsServedFrom;
};

export type AiHotStatusResponse = ApiEnvelope & {
  provider: "aihot" | string;
  provider_beta: boolean;
  enabled: boolean;
  base_url: string;
  timeout_seconds: number;
  cache_ttl_seconds: number;
  last_error?: Record<string, unknown> | null;
  warnings: string[];
  research_safety: AiHotResearchSafety;
  /** Aggregated dual-source status (§6.5); optional for forward compat. */
  preference_default?: NewsPreference | string;
  research_only?: boolean;
  providers?: Record<string, unknown>;
  failover?: NewsFailoverStatus;
};

export type NewsStatusResponse = AiHotStatusResponse;

export type SettingsResponse = ApiEnvelope & {
  settings?: Record<string, unknown>;
};

export type EffectivePaperSafetyResponse = ApiEnvelope & {
  owner_user_id: string;
  workspace_id: string;
  global_kill_switch: boolean;
  canonical_account_count: number | null;
  canonical_account_frozen: boolean | null;
  current_paper_authority_epoch: number | null;
  effective: boolean;
  blockers: string[];
};

export type HermesGatewayWarningResponse =
  HermesSchemas["HermesGatewayWarningResponse"];
export type HermesGatewayWarning = HermesGatewayWarningResponse;
export type HermesGatewayStatusResponse = ApiEnvelope &
  HermesSchemas["HermesGatewayStatusResponse"];
export type HermesSessionSummaryResponse =
  HermesSchemas["HermesSessionSummaryResponse"];
export type HermesSessionSummary = HermesSessionSummaryResponse;
export type HermesSessionsResponse = ApiEnvelope &
  HermesSchemas["HermesSessionsResponse"];
export type HermesExternalSessionForkContextResponse =
  HermesSchemas["HermesExternalSessionForkContextResponse"];
export type HermesSessionDetailResponse = ApiEnvelope &
  HermesSchemas["HermesSessionDetailResponse"];
export type HermesMessageResponse = HermesSchemas["HermesMessageResponse"];
export type HermesSessionMessage = HermesMessageResponse;
export type HermesSessionMessagesResponse = ApiEnvelope &
  HermesSchemas["HermesSessionMessagesResponse"];
export type HermesResultsResponse = ApiEnvelope &
  HermesSchemas["HermesResultsResponse"];
export type HermesResultDetailResponse = ApiEnvelope &
  HermesSchemas["HermesResultDetailResponse"];

// Agent v0.2 HTTP contracts. These names intentionally mirror the backend's
// Pydantic components so generated-contract audits catch drift at either side.
export type OwnerSessionStatusResponse =
  GeneratedApiComponents["schemas"]["OwnerSessionStatusResponse"];
export type OwnerBootstrapResponse =
  GeneratedApiComponents["schemas"]["OwnerBootstrapResponse"];
export type OwnerLogoutResponse =
  GeneratedApiComponents["schemas"]["OwnerLogoutResponse"];
export type WorkspaceRefResponse =
  GeneratedApiComponents["schemas"]["WorkspaceRefResponse"];
export type DualVerticalAcceptanceResponse =
  GeneratedApiComponents["schemas"]["DualVerticalAcceptanceResponse"];
export type CanaryGrantResponse =
  GeneratedApiComponents["schemas"]["CanaryGrantResponse"];
export type PublicCutoverResponse =
  GeneratedApiComponents["schemas"]["PublicCutoverResponse"];
export type DurablePublicCutoverResponse =
  GeneratedApiComponents["schemas"]["DurablePublicCutoverResponse"];
export type WorkspacePublicCutoverResponse = NonNullable<
  GeneratedApiComponents["schemas"]["WorkspaceSnapshotResponse"]["public_cutovers"]
>[number];
export type GateProjectionResponse =
  GeneratedApiComponents["schemas"]["GateProjectionResponse"];
export type Gate1SourceEvidenceResponse =
  GeneratedApiComponents["schemas"]["Gate1SourceEvidenceResponse"];
export type OptionsRequestResponse =
  GeneratedApiComponents["schemas"]["OptionsRequestResponse"];
export type ManagedSessionProjectionResponse =
  GeneratedApiComponents["schemas"]["ManagedSessionProjectionResponse"];
export type WorkspaceSnapshotResponse =
  GeneratedApiComponents["schemas"]["WorkspaceSnapshotResponse"];
export type WorkspaceFollowResponse =
  GeneratedApiComponents["schemas"]["WorkspaceFollowResponse"];
export type WorkspaceAuthoritiesResponse =
  GeneratedApiComponents["schemas"]["WorkspaceAuthoritiesResponse"];
export type WorkspaceActionReceiptResponse =
  GeneratedApiComponents["schemas"]["WorkspaceActionReceiptResponse"];
export type CompositeTurnReceiptResponse =
  GeneratedApiComponents["schemas"]["CompositeTurnReceiptResponse"];

const API_BASE_URL = process.env.NEXT_PUBLIC_QUANT_API_BASE_URL ?? "http://127.0.0.1:8765";

const FALLBACK_SAFETY: SafetyFooter = {
  dry_run: true,
  paper_trading: true,
  live_trading_enabled: false,
  kill_switch: true,
  bind_address: "127.0.0.1",
};

const AIHOT_RESEARCH_SAFETY: AiHotResearchSafety = {
  research_only: true,
  not_investment_advice: true,
  does_not_trigger_trading: true,
  verify_original_source: true,
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
    data_provider: {
      configured_default: "unknown",
      tiingo_token_present: false,
    },
    hermes_command_ledger: {
      database_configured: false,
      schema_ready: false,
      schema_version: null,
      workflow_binding_schema_ready: false,
      workflow_binding_schema_version: null,
      mutation_enabled: false,
    },
    safety: FALLBACK_SAFETY,
  });
}

export function getSettings() {
  return apiGet<SettingsResponse>("/api/settings", {
    safety: FALLBACK_SAFETY,
  });
}

export function getEffectivePaperSafety() {
  return apiGet<EffectivePaperSafetyResponse>("/api/safety/effective", {
    owner_user_id: "",
    workspace_id: "",
    global_kill_switch: true,
    canonical_account_count: null,
    canonical_account_frozen: null,
    current_paper_authority_epoch: null,
    effective: false,
    blockers: ["canonical_paper_authority_unavailable"],
    safety: FALLBACK_SAFETY,
  });
}

export function getBriefIssue(publicId: string) {
  return apiGet<BriefIssueEnvelopeResponse>(buildBriefIssuePath(publicId), {
    issue: {
      issue_id: "",
      public_id: publicId,
      issue_date: "",
      locale: "",
      status: "unavailable",
    },
    snapshot: {
      snapshot_id: "",
      version: 0,
      payload: {},
      source_watermark: {},
    },
    warnings: ["Brief archive issue is unavailable."],
    safety: FALLBACK_SAFETY,
  });
}

export function getLatestBriefIssue(query: { locale?: string } = {}) {
  const locale = query.locale ?? "zh";
  return apiGet<BriefIssueEnvelopeResponse>(buildLatestBriefIssuePath(locale), {
    issue: {
      issue_id: "",
      public_id: "",
      issue_date: "",
      locale,
      status: "unavailable",
    },
    snapshot: {
      snapshot_id: "",
      version: 0,
      payload: {},
      source_watermark: {},
    },
    warnings: ["Brief archive issue is unavailable."],
    safety: FALLBACK_SAFETY,
  });
}

export function getBriefIssueList(query: { locale?: string; limit?: number; offset?: number } = {}) {
  const locale = query.locale ?? "zh";
  const limit = query.limit ?? 30;
  const offset = query.offset ?? 0;
  return apiGet<BriefIssueListResponse>(buildBriefIssueListPath(locale, limit, offset), {
    items: [],
    total: 0,
    limit,
    offset,
  });
}

export type AiHotItemsQuery = {
  mode?: "selected" | "all";
  category?: string;
  q?: string;
  since?: string;
  cursor?: string;
  take?: number;
  preference?: NewsPreference;
};

export type NewsItemsQuery = AiHotItemsQuery;

export function getNewsItems(query: NewsItemsQuery = {}) {
  const params = new URLSearchParams();
  params.set("mode", query.mode ?? "selected");
  if (query.category) {
    params.set("category", query.category);
  }
  if (query.q) {
    params.set("q", query.q);
  }
  if (query.since) {
    params.set("since", query.since);
  }
  if (query.cursor) {
    params.set("cursor", query.cursor);
  }
  if (query.preference) {
    params.set("preference", query.preference);
  }
  params.set("take", String(query.take ?? 50));
  return apiGet<AiHotItemsResponse>(`/api/news/items?${params.toString()}`, {
    provider: "aihot",
    provider_beta: true,
    fetched_at: "",
    count: 0,
    has_next: false,
    next_cursor: null,
    items: [],
    warnings: ["AI news feed is unavailable."],
    research_safety: AIHOT_RESEARCH_SAFETY,
    preference: query.preference ?? "auto",
    safety: FALLBACK_SAFETY,
  });
}

export function getNewsDaily(date?: string, preference?: NewsPreference) {
  const params = new URLSearchParams();
  if (date) {
    params.set("date", date);
  }
  if (preference) {
    params.set("preference", preference);
  }
  const query = params.toString();
  return apiGet<AiHotDailyResponse>(`/api/news/daily${query ? `?${query}` : ""}`, {
    provider: "aihot",
    provider_beta: true,
    fetched_at: "",
    date: date ?? "",
    generated_at: null,
    window_start: null,
    window_end: null,
    lead: null,
    sections: [],
    flashes: [],
    warnings: ["AI news daily report is unavailable."],
    research_safety: AIHOT_RESEARCH_SAFETY,
    raw: {},
    preference: preference ?? "auto",
    safety: FALLBACK_SAFETY,
  });
}

export function getNewsDailies(take = 14, preference?: NewsPreference) {
  const params = new URLSearchParams({ take: String(take) });
  if (preference) {
    params.set("preference", preference);
  }
  return apiGet<AiHotDailiesResponse>(`/api/news/dailies?${params.toString()}`, {
    provider: "aihot",
    provider_beta: true,
    fetched_at: "",
    count: 0,
    items: [],
    warnings: ["AI news daily archive is unavailable."],
    research_safety: AIHOT_RESEARCH_SAFETY,
    preference: preference ?? "auto",
    safety: FALLBACK_SAFETY,
  });
}

/** Local-only status fallback — does not invent a live probe. */
export function getNewsStatus() {
  return apiGet<NewsStatusResponse>("/api/news/status", {
    provider: "aihot",
    provider_beta: true,
    enabled: false,
    base_url: "",
    timeout_seconds: 0,
    cache_ttl_seconds: 0,
    last_error: null,
    warnings: ["AI news status is unavailable."],
    research_safety: AIHOT_RESEARCH_SAFETY,
    preference_default: "auto",
    research_only: true,
    providers: {},
    failover: { auto_enabled: false, order: [] },
    safety: FALLBACK_SAFETY,
  });
}

/** @deprecated Prefer getNewsItems — aliases the neutral /api/news/* facade. */
export function getAiHotItems(query: AiHotItemsQuery = {}) {
  return getNewsItems(query);
}

/** @deprecated Prefer getNewsDaily — aliases the neutral /api/news/* facade. */
export function getAiHotDaily(date?: string) {
  return getNewsDaily(date);
}

/** @deprecated Prefer getNewsDailies — aliases the neutral /api/news/* facade. */
export function getAiHotDailies(take = 14) {
  return getNewsDailies(take);
}

/** @deprecated Prefer getNewsStatus — aliases the neutral /api/news/* facade. */
export function getAiHotStatus() {
  return getNewsStatus();
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
  return apiGet<OHLCVResponse>(`/api/ohlcv?${params.toString()}`, {
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
  return apiGet<FactorCatalogResponse>("/api/factors", {
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
  return apiGet<StrategyCatalogResponse>("/api/strategies", {
    strategies: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getUniverses() {
  return apiGet<UniverseCatalogResponse>("/api/universes", {
    universes: [],
    safety: FALLBACK_SAFETY,
  });
}

export type FactorLabQuery = {
  provider?: string;
  universeId?: string;
  symbol?: string;
  benchmarkSymbol?: string;
  start?: string;
  end?: string;
  lookback?: number;
  forceRefresh?: boolean;
};

export function getFactorLabDashboard(query: FactorLabQuery = {}) {
  const provider = query.provider ?? "futu";
  const universeId = query.universeId ?? "etf";
  const symbol = (query.symbol ?? "QQQ").toUpperCase();
  const benchmarkSymbol = (query.benchmarkSymbol ?? symbol).toUpperCase();
  const start = query.start ?? "2024-01-02";
  const end = query.end ?? "2024-12-31";
  const lookback = query.lookback ?? 20;
  const params = new URLSearchParams({
    provider,
    universe_id: universeId,
    symbol,
    benchmark_symbol: benchmarkSymbol,
    start,
    end,
    lookback: String(lookback),
  });
  if (query.forceRefresh !== undefined) {
    params.set("force_refresh", String(query.forceRefresh));
  }
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
    guardrails: {
      exploratory_only: true,
      warning: "Factor Lab fallback response; backend data is unavailable.",
      walk_forward: {
        enabled: false,
        train_bars: 0,
        validation_bars: 0,
        step_bars: 0,
        fold_count: 0,
      },
      leakage_audit: {
        status: "empty",
        checked: false,
      },
    },
    cache: {
      status: "recomputed",
      path: "",
      key: {
        provider,
        universe_id: universeId,
        symbol,
        benchmark_symbol: benchmarkSymbol,
        start,
        end,
        lookback,
      },
    },
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

export function getPaperAccountActivity(limit = 200, offset = 0) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiGet<PaperAccountActivityResponse>(`/api/paper/account/activity?${params.toString()}`, {
    account: FALLBACK_ACCOUNT,
    pending_orders: [],
    order_history: [],
    balance_history: [],
    trade_log: [],
    pending_order_total: 0,
    order_history_total: 0,
    balance_history_total: 0,
    trade_log_total: 0,
    limit,
    offset,
    safety: FALLBACK_SAFETY,
  });
}

export function getPaperAccountEquityCurve(days = 7, limit = 200, offset = 0) {
  const params = new URLSearchParams({
    days: String(days),
    limit: String(limit),
    offset: String(offset),
  });
  return apiGet<PaperAccountEquityCurveResponse>(
    `/api/paper/account/equity-curve?${params.toString()}`,
    {
      account_id: "default",
      account_exists: false,
      total: 0,
      limit,
      offset,
      points: [],
      safety: FALLBACK_SAFETY,
    },
  );
}

export function getPaperAccountPerformance(range: PaperPerformanceRange = "7d") {
  const params = new URLSearchParams({
    range,
    granularity: "1d",
    benchmarks: "SPY,QQQ",
  });
  return apiGet<PaperAccountPerformanceResponse>(
    `/api/paper/account/performance?${params.toString()}`,
    {
      account_id: "default",
      account_exists: false,
      range,
      granularity: "1d",
      benchmarks: ["SPY", "QQQ"],
      requested_start: "",
      requested_end: "",
      actual_start: null,
      actual_end: null,
      coverage_complete: false,
      series: [],
      warnings: [],
      safety: FALLBACK_SAFETY,
    },
  );
}

export function getPaperStrategyConfigs() {
  return apiGet<PaperStrategyConfigsResponse>("/api/paper/strategy-configs", {
    configs: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getPaperStrategySleeves() {
  return apiGet<PaperStrategySleevesResponse>("/api/paper/strategy-sleeves", {
    sleeves: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getPaperStrategySleeveDetail(sleeveId: string) {
  return apiGet<PaperStrategySleeveDetailResponse>(
    `/api/paper/strategy-sleeves/${encodeURIComponent(sleeveId)}`,
    {
      sleeve: {
        sleeve_id: sleeveId,
        account_id: "default",
        strategy_config_id: "",
        strategy_config_version: 1,
        mode: "signal_only",
        status: "stopped",
        initial_allocated_cash: 0,
        cash: 0,
        created_at: "",
        updated_at: "",
        metadata: {},
      },
      lots: [],
      signals: [],
      executions: [],
      safety: FALLBACK_SAFETY,
    },
  );
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

export async function getAgentCandidates() {
  const response = await apiGet<AgentCandidatesResponse>("/api/agent/candidates", {
    candidates: [],
    safety: FALLBACK_SAFETY,
  });
  return normalizeCandidateListResponse(response);
}

export function getHermesArtifacts(limit = 20) {
  const safeLimit = Math.min(50, Math.max(1, Math.trunc(limit)));
  return apiGet<HermesArtifactShelfEnvelope>(`/api/hermes/artifacts?limit=${safeLimit}`, {
    schema_version: "1.0",
    read_status: "unavailable",
    as_of: null,
    items: [],
    sources: [],
    warnings: [{ source: "artifact_feed", code: "api_unavailable" }],
    safety: FALLBACK_SAFETY,
  });
}

export async function getHermesResults(query: HermesResultsQuery = {}) {
  const limit = Number.isFinite(query.limit)
    ? Math.min(100, Math.max(1, Math.trunc(query.limit as number)))
    : 20;
  const offset = Number.isFinite(query.offset)
    ? Math.min(10_000, Math.max(0, Math.trunc(query.offset as number)))
    : 0;
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (query.kind) params.set("kind", query.kind);
  const status = query.status?.trim();
  if (status && status.length <= 128) params.set("status", status);
  if (query.source) params.set("source", query.source);
  const search = query.search?.trim();
  if (search && search.length <= 256) params.set("search", search);

  const response = await apiGet<HermesResultsResponse>(
    `/api/hermes/results?${params.toString()}`,
    {
      read_status: "unavailable",
      total: null,
      total_is_exact: false,
      limit,
      offset,
      has_more: false,
      items: [],
      sources: [],
      warnings: [
        {
          source: "results_catalog",
          code: "api_unavailable",
          kind: null,
          resource_id: null,
        },
      ],
      safety: FALLBACK_SAFETY,
    },
  );
  return normalizeHermesResultsResponse(response, { limit, offset });
}

export async function getHermesResultDetail(
  kind: HermesResultKind,
  resourceId: string,
) {
  if (!isHermesResultKind(kind) || !isHermesResultResourceId(resourceId)) {
    return {
      read_status: "unavailable",
      item: null,
      resource: null,
      warnings: [
        {
          source: "results_catalog",
          code: "invalid_result_identity",
          kind: null,
          resource_id: null,
        },
      ],
      safety: FALLBACK_SAFETY,
      apiError: "invalid_result_identity",
    } satisfies HermesResultDetailResponse;
  }
  const response = await apiGet<HermesResultDetailResponse>(
    `/api/hermes/results/${encodeURIComponent(kind)}/${encodeURIComponent(resourceId)}`,
    {
      read_status: "unavailable",
      item: null,
      resource: null,
      warnings: [
        {
          source: "results_catalog",
          code: "api_unavailable",
          kind,
          resource_id: resourceId,
        },
      ],
      safety: FALLBACK_SAFETY,
    },
  );
  return normalizeHermesResultDetailResponse(response, { kind, resourceId });
}

export function getHermesGatewayStatus() {
  return apiGet<HermesGatewayStatusResponse>("/api/hermes/gateway", {
    read_status: "unavailable",
    connected: false,
    model: null,
    session_api_available: false,
    chat_write_ready: false,
    features: {},
    upstream_blockers: ["api_unavailable"],
    platform_delivery_blockers: ["api_unavailable"],
    blockers: ["api_unavailable"],
    warnings: [{ code: "api_unavailable", message: "Platform BFF unavailable" }],
    safety: FALLBACK_SAFETY,
  });
}

export function getHermesSessions(limit = 50, offset = 0) {
  const safeLimit = Math.min(200, Math.max(1, Math.trunc(limit)));
  const safeOffset = Math.min(1_000_000, Math.max(0, Math.trunc(offset)));
  return apiGet<HermesSessionsResponse>(
    `/api/hermes/sessions?limit=${safeLimit}&offset=${safeOffset}`,
    {
      read_status: "unavailable",
      sessions: [],
      limit: safeLimit,
      offset: safeOffset,
      has_more: false,
      warnings: [{ code: "api_unavailable", message: "Platform BFF unavailable" }],
      safety: FALLBACK_SAFETY,
    },
  );
}

export function getHermesSessionDetail(sessionId: string) {
  const encodedId = encodeURIComponent(sessionId);
  return apiGet<HermesSessionDetailResponse>(`/api/hermes/sessions/${encodedId}`, {
    read_status: "unavailable",
    session: null,
    fork_context: {
      eligible: false,
      source_channel: null,
      reason_code: "api_unavailable",
    },
    warnings: [{ code: "api_unavailable", message: "Platform BFF unavailable" }],
    safety: FALLBACK_SAFETY,
  });
}

export function getHermesSessionMessages(sessionId: string) {
  const encodedId = encodeURIComponent(sessionId);
  return apiGet<HermesSessionMessagesResponse>(
    `/api/hermes/sessions/${encodedId}/messages`,
    {
      read_status: "unavailable",
      session_id: sessionId,
      messages: [],
      omitted_message_count: 0,
      warnings: [{ code: "api_unavailable", message: "Platform BFF unavailable" }],
      safety: FALLBACK_SAFETY,
    },
  );
}

export async function getAgentCandidateDetail(candidateId: string) {
  const encodedCandidateId = encodeURIComponent(candidateId);
  const response = await apiGet<AgentCandidateDetailResponse>(
    `/api/agent/candidates/${encodedCandidateId}`,
    {
      candidate_id: candidateId,
      metadata: null,
      source_preview: null,
      audit: [],
      reviews: [],
      evidence_truncated: false,
      integrity_state: "corrupt",
      manifest_digest: null,
      observed_manifest_digest: null,
      approval_binding: null,
      approval_enabled: false,
      integrity_error_code: "api_unavailable",
      status: null,
      safety: FALLBACK_SAFETY,
    },
  );
  return normalizeCandidateDetailResponse(response, candidateId);
}

export function getAgentLlmConfig() {
  return apiGet<AgentLLMConfigResponse>("/api/agent/llm-config", {
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
  return apiGet<PredictionMarketMarketsResponse>(
    `/api/prediction-market/markets?${params.toString()}`,
    {
    markets: [],
    order_books: [],
    provider: "fallback",
    cache_status: "unavailable",
    safety: FALLBACK_SAFETY,
    },
  );
}

export function getOptionsRadarDates() {
  return apiGet<OptionsRadarDatesResponse>("/api/options/daily-scan/dates", {
    dates: [],
    safety: FALLBACK_SAFETY,
  });
}

export function getOptionsDailyScanStatus() {
  return apiGet<OptionsDailyScanStatusResponse>("/api/options/daily-scan/status", {
    exists: false,
    status_path: "",
    status: null,
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

export function getOptionsDailyScanSymbol(ticker: string, date?: string) {
  const query = new URLSearchParams();
  if (date) {
    query.set("date", date);
  }
  return apiGet<OptionsDailyScanSymbolResponse>(
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

export const getOptionsRadarSymbol = getOptionsDailyScanSymbol;

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
