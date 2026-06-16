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
