from pathlib import Path


def test_frontend_links_to_persisted_replication_runs() -> None:
    api_client = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")
    workbench = Path(
        "src/frontend/components/forms/StrategyCatalogWorkbench.tsx"
    ).read_text(encoding="utf-8")
    detail_page = Path("src/frontend/app/replications/[runId]/page.tsx")

    assert "getReversalMomentumReplicationDetail" in api_client
    assert "/api/replications/reversal-momentum/${runId}" in api_client
    assert "initialResult" in workbench
    assert "openReplication" in workbench
    assert "/replications/${String(result.run_id)}" in workbench
    assert detail_page.exists()


def test_strategy_catalog_uses_shared_run_response_types() -> None:
    api_client = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")
    workbench = Path(
        "src/frontend/components/forms/StrategyCatalogWorkbench.tsx"
    ).read_text(encoding="utf-8")
    detail_page = Path("src/frontend/app/replications/[runId]/page.tsx").read_text(
        encoding="utf-8"
    )

    assert "export type ReversalMomentumReplicationRunResponse" in api_client
    assert "export type StrategyRunResponse" in api_client
    assert "| BacktestRunResponse" in api_client
    assert "| ReversalMomentumReplicationRunResponse" in api_client
    assert "StrategyRunResponse" in workbench
    assert "initialResult?: StrategyRunResponse | null;" in workbench
    assert "useState<StrategyRunResponse | null>" in workbench
    assert "apiPost<StrategyRunResponse>" in workbench
    assert "apiPost<Record<string, unknown>>" not in workbench
    assert "ReversalMomentumReplicationRunResponse" in detail_page
