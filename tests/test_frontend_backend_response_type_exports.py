import re
from pathlib import Path

API_SCHEMAS = Path("src/quant_system/api/schemas")
FRONTEND_API_TYPES = Path("src/frontend/lib/api.ts")


def test_frontend_exports_every_backend_response_schema_name() -> None:
    frontend_types = FRONTEND_API_TYPES.read_text(encoding="utf-8")
    backend_response_names: list[tuple[str, Path]] = []

    for schema_path in sorted(API_SCHEMAS.glob("*.py")):
        schema_text = schema_path.read_text(encoding="utf-8")
        for type_name in re.findall(r"^class\s+(\w+Response)\b", schema_text, re.M):
            backend_response_names.append((type_name, schema_path))

    missing = [
        f"{type_name} ({schema_path})"
        for type_name, schema_path in backend_response_names
        if f"export type {type_name}" not in frontend_types
        and f"export interface {type_name}" not in frontend_types
    ]

    assert not missing


def test_frontend_paper_account_contract_exposes_repository_state() -> None:
    frontend_types = FRONTEND_API_TYPES.read_text(encoding="utf-8")

    assert 'storage_mode?: "file" | "mirror" | "canonical" | null;' in frontend_types
    assert "stale?: boolean;" in frontend_types
    assert "warnings?: string[];" in frontend_types
    assert "export type PaperAccountReconciliationResponse" in frontend_types
    assert (
        "reconciliation?: PaperAccountReconciliationResponse | null;"
        in frontend_types
    )
