from pathlib import Path

RUN_FORMS = {
    "BacktestRunResponse": Path("src/frontend/components/forms/BacktestForm.tsx"),
    "FactorRunResponse": Path("src/frontend/components/forms/FactorRunForm.tsx"),
    "ExperimentRunResponse": Path(
        "src/frontend/components/forms/ExperimentRunForm.tsx"
    ),
    "PaperRunResponse": Path("src/frontend/components/forms/PaperRunForm.tsx"),
}


def test_core_run_forms_use_shared_api_response_types() -> None:
    api_types = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")

    for type_name, path in RUN_FORMS.items():
        component = path.read_text(encoding="utf-8")

        assert f"export type {type_name} = ApiEnvelope &" in api_types
        assert f"type {type_name} = {{" not in component
        assert type_name in component
        assert '"@/lib/api"' in component


def test_shared_run_response_types_include_backend_response_model_fields() -> None:
    api_types = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")

    for field in [
        "timings_ms: Record<string, unknown>;",
        "attribution: PreviewRecord[];",
        "raw_experiment_id: string;",
        "provider: string;",
        "source: string;",
        "execution_status: string;",
        "risk_breach_count: number;",
        "warnings: string[];",
        "paths: Record<string, unknown>;",
    ]:
        assert field in api_types
