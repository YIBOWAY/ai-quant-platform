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
