from pathlib import Path

API_TYPES = Path("src/frontend/lib/api.ts")
COMPONENT = Path("src/frontend/components/forms/BuySideOptionsAssistant.tsx")


def test_buy_side_assistant_uses_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    component = COMPONENT.read_text(encoding="utf-8")

    for type_name in [
        "BuySideAssistantResponse",
        "BuySideDecisionThesis",
        "BuySideRecommendation",
        "BuySideStrategyLeg",
        "BuySideScenarioSummary",
        "BuySideScenarioEv",
    ]:
        assert f"export type {type_name}" in api_types

    assert "BuySideAssistantResponse" in component
    assert "BuySideRecommendation" in component
    assert "BuySideStrategyLeg" in component
    assert '"@/lib/api"' in component
    assert "type AssistantResponse =" not in component
    assert "type Recommendation =" not in component
    assert "type StrategyLeg =" not in component


def test_shared_buy_side_types_include_backend_response_model_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for field in [
        "thesis: BuySideDecisionThesis;",
        "recommendations: BuySideRecommendation[];",
        "assumptions: string[];",
        "strategy_type: BuySideStrategyType;",
        "legs: BuySideStrategyLeg[];",
        "risk_attribution: Record<BuySidePrimaryRiskSource, number>;",
        "primary_risk_source: BuySidePrimaryRiskSource;",
        "scenario_summary?: BuySideScenarioSummary | null;",
        "scenario_ev?: BuySideScenarioEv | null;",
        "probability_not_calculated: boolean;",
        "expected_value_contribution: number;",
    ]:
        assert field in api_types
