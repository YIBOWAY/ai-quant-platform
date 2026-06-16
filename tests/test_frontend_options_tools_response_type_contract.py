from pathlib import Path

API_TYPES = Path("src/frontend/lib/api.ts")
WORKBENCH = Path("src/frontend/components/forms/OptionsToolsWorkbench.tsx")
LIVE_HELPERS = Path("src/frontend/lib/optionsToolsLive.ts")


def test_options_tools_workbench_delegates_live_requests_to_helper_module() -> None:
    component = WORKBENCH.read_text(encoding="utf-8")
    helpers = LIVE_HELPERS.read_text(encoding="utf-8")

    assert 'from "@/lib/optionsToolsLive"' in component
    assert "apiPost<" not in component
    assert "apiRequest<" not in component
    assert "apiPost<" in helpers
    assert "apiRequest<" in helpers


def test_options_tools_surface_smile_use_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = WORKBENCH.read_text(encoding="utf-8")
    helpers = LIVE_HELPERS.read_text(encoding="utf-8")

    for type_name in [
        "OptionsVolSurface",
        "OptionsVolSurfaceResponse",
        "OptionsVolSmile",
        "OptionsVolSmileResponse",
    ]:
        assert f"export type {type_name}" in api_types

    assert "OptionsVolSurfaceResponse" in component
    assert "OptionsVolSmileResponse" in component
    assert "type SurfaceResult =" not in component
    assert "type SmileResult =" not in component
    assert "loadVolSurface" in component
    assert "loadVolSmile" in component
    assert "apiRequest<OptionsVolSurfaceResponse>" in helpers
    assert "apiRequest<OptionsVolSmileResponse>" in helpers


def test_options_tools_greeks_simulation_use_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = WORKBENCH.read_text(encoding="utf-8")
    helpers = LIVE_HELPERS.read_text(encoding="utf-8")

    for type_name in [
        "OptionsGreeksResponse",
        "OptionsSimulationPnlAtExpiry",
        "OptionsSimulationResponse",
    ]:
        assert f"export type {type_name}" in api_types

    assert "OptionsGreeksResponse" in component
    assert "OptionsSimulationResponse" in component
    assert "type GreeksResult =" not in component
    assert "type SimulationResult =" not in component
    assert "calculateLiveGreeks" in component
    assert "simulateLiveCallSpread" in component
    assert "apiPost<OptionsGreeksResponse>" in helpers
    assert "apiPost<OptionsSimulationResponse>" in helpers


def test_options_tools_strategy_score_use_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = WORKBENCH.read_text(encoding="utf-8")
    helpers = LIVE_HELPERS.read_text(encoding="utf-8")

    for type_name in [
        "OptionsStrategyRank",
        "OptionsStrategyRankResponse",
        "OptionsContractRank",
        "OptionsContractScoreResponse",
    ]:
        assert f"export type {type_name}" in api_types

    assert "OptionsStrategyRankResponse" in component
    assert "OptionsContractScoreResponse" in component
    assert "type StrategyRank =" not in component
    assert "type StrategyRankResult =" not in component
    assert "type ContractRank =" not in component
    assert "type ScoreContractsResult =" not in component
    assert "rankLiveStrategies" in component
    assert "scoreLiveContracts" in component
    assert "apiPost<OptionsStrategyRankResponse>" in helpers
    assert "apiPost<OptionsContractScoreResponse>" in helpers


def test_options_tools_signals_use_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = WORKBENCH.read_text(encoding="utf-8")
    helpers = LIVE_HELPERS.read_text(encoding="utf-8")

    for type_name in [
        "OptionsImpliedVolatilityResponse",
        "OptionsBullPutSignalResponse",
        "OptionsFearScoreResponse",
        "OptionsIvRankResponse",
        "OptionsMarketSentimentResponse",
        "OptionsEarningsCrushResponse",
        "OptionsHedgeAdvisorResponse",
        "OptionsUnusualActivityResponse",
        "OptionsSignalsResponse",
    ]:
        assert f"export type {type_name}" in api_types

    for type_name in [
        "OptionsImpliedVolatilityResponse",
        "OptionsBullPutSignalResponse",
        "OptionsFearScoreResponse",
        "OptionsSnapshotResponse",
        "OptionsMarketSentimentResponse",
        "OptionsEarningsCrushResponse",
        "OptionsUnusualActivityResponse",
    ]:
        assert type_name in helpers

    assert "payload: OptionsSignalsResponse" in component
    assert "request: () => Promise<OptionsSignalsResponse>" in component
    assert "liveImpliedVolatility" in component
    assert "liveBullPutSignal" in component
    assert "liveFearScore" in component
    assert "liveIvRankSnapshot" in component
    assert "runMarketSentiment" in component
    assert "liveEarningsCrush" in component
    assert "liveUnusualActivity" in component
    assert "apiPost<OptionsImpliedVolatilityResponse>" in helpers
    assert "apiPost<OptionsFearScoreResponse>" in helpers
    assert "apiPost<OptionsBullPutSignalResponse>" in helpers
    assert "apiPost<OptionsMarketSentimentResponse>" in helpers
    assert "apiPost<OptionsEarningsCrushResponse>" in helpers
    assert "apiPost<OptionsUnusualActivityResponse>" in helpers
    assert "apiRequest<OptionsSnapshotResponse>" in helpers
    assert "apiPost<{ fear_score: number }>" not in component
    assert "apiPost<{ fear_score: number }>" not in helpers


def test_options_tools_research_ops_use_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = WORKBENCH.read_text(encoding="utf-8")
    helpers = LIVE_HELPERS.read_text(encoding="utf-8")

    for type_name in [
        "OptionsStrategyTemplatesResponse",
        "OptionsStrategyBuildResponse",
        "OptionsWatchlistResponse",
        "OptionsAlertsEvaluationResponse",
        "OptionsResearchHealthCheckResponse",
        "OptionsResearchOpsResponse",
    ]:
        assert f"export type {type_name}" in api_types

    for type_name in [
        "OptionsStrategyTemplatesResponse",
        "OptionsStrategyBuildResponse",
        "OptionsWatchlistResponse",
        "OptionsAlertsEvaluationResponse",
        "OptionsResearchHealthCheckResponse",
    ]:
        assert type_name in helpers

    assert "payload: OptionsResearchOpsResponse" in component
    assert "request: () => Promise<OptionsResearchOpsResponse>" in component
    assert "loadStrategyTemplates" in component
    assert "liveBuildStrategy" in component
    assert "addWatchlistTicker" in component
    assert "loadWatchlist" in component
    assert "liveEvaluateAlerts" in component
    assert "liveResearchHealthCheck" in component
    assert "apiRequest<OptionsStrategyTemplatesResponse>" in helpers
    assert "apiPost<OptionsStrategyBuildResponse>" in helpers
    assert "apiPost<OptionsWatchlistResponse>" in helpers
    assert "apiRequest<OptionsWatchlistResponse>" in helpers
    assert "apiPost<OptionsAlertsEvaluationResponse>" in helpers
    assert "apiPost<OptionsResearchHealthCheckResponse>" in helpers
    assert "Promise<unknown>" not in component
    assert "Promise<unknown>" not in helpers


def test_shared_options_surface_smile_types_include_backend_response_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for field in [
        "success: boolean;",
        "source: string;",
        "atm_term_structure: Record<string, number>;",
        "points: Array<Record<string, unknown>>;",
        "dte: number;",
        "deltas: Array<number | null>;",
        "moneyness: Array<number | null>;",
        "skew_metrics: Record<string, number | null>;",
        "assumptions: string[];",
    ]:
        assert field in api_types


def test_shared_options_strategy_score_types_include_backend_response_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for field in [
        "success: boolean;",
        "market_view: string;",
        "rankings: OptionsStrategyRank[];",
        "template_id: string;",
        "net_debit?: number | null;",
        "breakevens: number[];",
        "objective: string;",
        "spot: number;",
        "ranked_contracts: OptionsContractRank[];",
        "bid?: number | null;",
        "ask?: number | null;",
        "spread_pct?: number | null;",
        "volume?: number | null;",
        "open_interest?: number | null;",
        "subscores: Record<string, number>;",
        "warnings: string[];",
        "[key: string]: unknown;",
    ]:
        assert field in api_types


def test_shared_options_greeks_simulation_types_include_backend_response_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for field in [
        "charm: number;",
        "vanna: number;",
        "volga: number;",
        "position: Record<string, unknown>;",
        "pnl_at_expiry: OptionsSimulationPnlAtExpiry;",
        "price_axis: number[];",
        "pnl_axis: number[];",
        "risk_reward_ratio?: number | null;",
        "scenarios: Record<string, unknown>;",
    ]:
        assert field in api_types


def test_shared_options_signal_types_include_backend_response_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for field in [
        "implied_volatility: number;",
        "enter_signal: boolean;",
        "selected_spread?: Record<string, unknown> | null;",
        "reasons: string[];",
        "tier: string;",
        "components: Record<string, unknown>;",
        "bull_put_spread_signal: boolean;",
        "sentiment_score: number;",
        "regime: string;",
        "sample_count: number;",
        "iv_percentile?: number | null;",
        "strategy_tag: string;",
        "situation: Record<string, unknown>;",
        "structures: Array<Record<string, unknown>>;",
        "events: Array<Record<string, unknown>>;",
        "| OptionsImpliedVolatilityResponse",
        "| OptionsBullPutSignalResponse",
        "| OptionsFearScoreResponse",
        "| OptionsMarketSentimentResponse",
        "| OptionsSnapshotResponse",
        "| OptionsEarningsCrushResponse",
        "| OptionsHedgeAdvisorResponse",
        "| OptionsUnusualActivityResponse",
    ]:
        assert field in api_types


def test_shared_options_research_ops_types_include_backend_response_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for field in [
        "templates: Array<Record<string, unknown>>;",
        "mode: string;",
        "template_id: string;",
        "legs: Array<Record<string, unknown>>;",
        "net_debit: number;",
        "watchlist: Array<Record<string, unknown>>;",
        "triggered_alerts: Array<Record<string, unknown>>;",
        "health_score: number;",
        "stale_profiles: string[];",
        "missing_thesis: string[];",
        "| OptionsStrategyTemplatesResponse",
        "| OptionsStrategyBuildResponse",
        "| OptionsWatchlistResponse",
        "| OptionsAlertsEvaluationResponse",
        "| OptionsResearchHealthCheckResponse",
    ]:
        assert field in api_types
