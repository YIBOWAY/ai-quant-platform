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

export type StrategiesResponse = ApiEnvelope & {
  strategies: StrategyMetadata[];
};

export type StrategyRunResponse =
  | BacktestRunResponse
  | ReversalMomentumReplicationRunResponse;

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

export type PaperAccountOrderOutcome = {
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

export type PaperAccountOrderResponse = ApiEnvelope & {
  order: PaperAccountOrderOutcome;
  account: PaperAccountResponse;
};

export type PaperAccountOrdersProcessResponse = ApiEnvelope & {
  orders: PaperAccountOrderOutcome[];
  account: PaperAccountResponse;
};

export type PaperAccountRebalanceSummary = {
  strategy_id: string;
  as_of?: string | null;
  aborted: boolean;
  target_weights: Record<string, number>;
  note?: string | null;
  orders: PaperAccountOrderOutcome[];
};

export type PaperAccountRebalanceResponse = ApiEnvelope & {
  rebalance: PaperAccountRebalanceSummary;
  account: PaperAccountResponse;
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

export type AgentLLMConfigResponse = ApiEnvelope & {
  provider: string;
  model: string | null;
  base_url: string | null;
  timeout: number;
  has_api_key: boolean;
};

export type AgentLlmConfigResponse = AgentLLMConfigResponse;

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

export type PredictionMarketCandidate = {
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

export type PredictionMarketTimeseriesDetailResponse = ApiEnvelope & {
  run_id: string;
  result: Record<string, unknown>;
  chart_index: {
    charts: Array<{ name: string; path: string; title: string; url: string }>;
  };
  report_path: string;
  report_url: string;
};

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
  | OptionsResearchHealthCheckResponse;

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
};

export type OptionsDailyScanSymbolResponse = ApiEnvelope & {
  ticker: string;
  run_date: string;
  candidate_count: number;
  candidates: OptionsRadarCandidate[];
};

export type OptionsRadarSymbolResponse = OptionsDailyScanSymbolResponse;

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
