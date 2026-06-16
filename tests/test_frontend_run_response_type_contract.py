from pathlib import Path

RUN_FORMS = {
    "BacktestRunResponse": Path("src/frontend/components/forms/BacktestForm.tsx"),
    "FactorRunResponse": Path("src/frontend/components/forms/FactorRunForm.tsx"),
    "ExperimentRunResponse": Path(
        "src/frontend/components/forms/ExperimentRunForm.tsx"
    ),
    "PaperRunResponse": Path("src/frontend/components/forms/PaperRunForm.tsx"),
}

AGENT_FORM = Path("src/frontend/components/forms/AgentTaskForm.tsx")


def test_core_run_forms_use_shared_api_response_types() -> None:
    api_types = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")

    for type_name, path in RUN_FORMS.items():
        component = path.read_text(encoding="utf-8")

        assert f"export type {type_name} = ApiEnvelope &" in api_types
        assert f"type {type_name} = {{" not in component
        assert type_name in component
        assert '"@/lib/api"' in component


def test_agent_task_form_uses_shared_api_response_types() -> None:
    api_types = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")
    component = AGENT_FORM.read_text(encoding="utf-8")

    for type_name in ("AgentTaskResponse", "AgentReviewResponse"):
        assert f"export type {type_name} = ApiEnvelope &" in api_types
        assert f"type {type_name} = {{" not in component
        assert type_name in component
    assert '"@/lib/api"' in component
    assert "apiPost<AgentReviewResponse>" in component


def test_shared_run_response_types_include_backend_response_model_fields() -> None:
    api_types = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")

    assert "export type BacktestRunTimingsResponse = {" in api_types
    assert "data_fetch: number;" in api_types
    assert "timings_ms: BacktestRunTimingsResponse;" in api_types
    assert "timings_ms: Record<string, unknown>;" not in api_types
    assert "export type BacktestRunRequestEchoResponse = {" in api_types
    assert "request: BacktestRunRequestEchoResponse;" in api_types
    assert "metrics: BacktestRunMetricsResponse;" in api_types
    assert "benchmark: BacktestRunBenchmarkResponse;" in api_types
    assert "paths: BacktestRunPathsResponse;" in api_types
    assert "export type FactorRunRequestEchoResponse = {" in api_types
    assert "export type FactorRunPathsResponse = {" in api_types
    assert "request: FactorRunRequestEchoResponse;" in api_types
    assert "paths: FactorRunPathsResponse;" in api_types
    assert "export type ExperimentRunPathsResponse = {" in api_types
    assert "paths: ExperimentRunPathsResponse;" in api_types
    assert "export type PaperRunRequestEchoResponse = {" in api_types
    assert "export type PaperRunPathsResponse = {" in api_types
    assert "request: PaperRunRequestEchoResponse;" in api_types
    assert "paths: PaperRunPathsResponse;" in api_types

    for field in [
        "attribution: PreviewRecord[];",
        "raw_experiment_id: string;",
        "provider: string;",
        "source: string;",
        "execution_status: string;",
        "risk_breach_count: number;",
        "warnings: string[];",
    ]:
        assert field in api_types


def test_shared_agent_response_types_include_backend_response_model_fields() -> None:
    api_types = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")

    for field in [
        "candidate_id: string;",
        "status: string;",
        "path: string;",
        "metadata: Record<string, unknown>;",
        'decision: "approve" | "reject";',
        'registration: "manual_required";',
    ]:
        assert field in api_types
