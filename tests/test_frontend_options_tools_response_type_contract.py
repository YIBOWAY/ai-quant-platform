from pathlib import Path

API_TYPES = Path("src/frontend/lib/api.ts")
WORKBENCH = Path("src/frontend/components/forms/OptionsToolsWorkbench.tsx")


def test_options_tools_surface_smile_use_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = WORKBENCH.read_text(encoding="utf-8")

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
    assert "apiRequest<OptionsVolSurfaceResponse>" in component
    assert "apiRequest<OptionsVolSmileResponse>" in component


def test_options_tools_greeks_simulation_use_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = WORKBENCH.read_text(encoding="utf-8")

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
    assert "apiPost<OptionsGreeksResponse>" in component
    assert "apiPost<OptionsSimulationResponse>" in component


def test_options_tools_strategy_score_use_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = WORKBENCH.read_text(encoding="utf-8")

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
    assert "apiPost<OptionsStrategyRankResponse>" in component
    assert "apiPost<OptionsContractScoreResponse>" in component


def test_options_tools_signals_use_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = WORKBENCH.read_text(encoding="utf-8")

    for type_name in [
        "OptionsImpliedVolatilityResponse",
        "OptionsBullPutSignalResponse",
        "OptionsFearScoreResponse",
        "OptionsIvRankResponse",
        "OptionsEarningsCrushResponse",
        "OptionsUnusualActivityResponse",
        "OptionsSignalsResponse",
    ]:
        assert f"export type {type_name}" in api_types

    for type_name in [
        "OptionsImpliedVolatilityResponse",
        "OptionsBullPutSignalResponse",
        "OptionsFearScoreResponse",
        "OptionsSnapshotResponse",
        "OptionsEarningsCrushResponse",
        "OptionsUnusualActivityResponse",
    ]:
        assert type_name in component

    assert "payload: OptionsSignalsResponse" in component
    assert "request: () => Promise<OptionsSignalsResponse>" in component
    assert "apiPost<OptionsImpliedVolatilityResponse>" in component
    assert "apiPost<OptionsFearScoreResponse>" in component
    assert "apiPost<OptionsBullPutSignalResponse>" in component
    assert "apiPost<OptionsEarningsCrushResponse>" in component
    assert "apiPost<OptionsUnusualActivityResponse>" in component
    assert "apiRequest<OptionsSnapshotResponse>" in component
    assert "apiPost<{ fear_score: number }>" not in component


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
        "sample_count: number;",
        "iv_percentile?: number | null;",
        "strategy_tag: string;",
        "events: Array<Record<string, unknown>>;",
        "| OptionsImpliedVolatilityResponse",
        "| OptionsBullPutSignalResponse",
        "| OptionsFearScoreResponse",
        "| OptionsSnapshotResponse",
        "| OptionsEarningsCrushResponse",
        "| OptionsUnusualActivityResponse",
    ]:
        assert field in api_types
