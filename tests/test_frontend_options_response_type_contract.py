from pathlib import Path

OPTIONS_LIVE_COMPONENTS = [
    Path("src/frontend/components/forms/OptionsRadarSymbolLive.tsx"),
    # Live option-chain handling for the tools workbench was extracted into this
    # helper; the workbench itself no longer references OptionsChainResponse.
    Path("src/frontend/lib/optionsToolsLive.ts"),
]


def test_options_live_components_use_shared_response_types() -> None:
    api_types = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")

    for type_name in [
        "OptionContract",
        "OptionsSnapshotResponse",
        "OptionsExpirationsResponse",
        "OptionsChainResponse",
    ]:
        assert f"export type {type_name}" in api_types

    for path in OPTIONS_LIVE_COMPONENTS:
        component = path.read_text(encoding="utf-8")

        assert "OptionsChainResponse" in component
        assert '"@/lib/api"' in component
        assert "type OptionsSnapshotResponse =" not in component
        assert "type OptionsExpirationsResponse =" not in component
        assert "type OptionChainResponse =" not in component
        assert "type OptionsChainResponse =" not in component


def test_shared_options_live_types_include_backend_response_model_fields() -> None:
    api_types = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")

    for field in [
        "success: boolean;",
        "source: string;",
        "nearest_expiry: string;",
        "iv_rank_source: string;",
        "assumptions: string[];",
        "option_type: string;",
        "contracts: OptionContract[];",
        "[key: string]: unknown;",
    ]:
        assert field in api_types
