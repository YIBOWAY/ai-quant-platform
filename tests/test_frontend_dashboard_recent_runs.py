from pathlib import Path


def test_legacy_dashboard_keeps_recent_runs_while_root_can_redirect_to_hermes() -> None:
    api_client = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")
    home = Path("src/frontend/app/page.tsx").read_text(encoding="utf-8")
    dashboard = Path(
        "src/frontend/components/dashboard/LegacyDashboard.tsx"
    ).read_text(encoding="utf-8")
    dashboard_helpers = Path("src/frontend/lib/dashboardRuns.ts").read_text(encoding="utf-8")

    assert (
        'export type RecentRunKind = "backtest" | "factor" | "paper" | "replication";'
        in api_client
    )
    assert "export function getRecentRuns" in api_client
    assert "/api/runs/recent?" in api_client

    assert "hermesFeatureFlags().shell" in home
    assert "redirect(hermesHomeHref" in home
    assert "<LegacyDashboard />" in home
    assert "getRecentRuns" in dashboard
    assert "recentRuns.apiError" in dashboard
    assert "recentRuns.runs.length > 0" in dashboard
    assert "dashboardRunSummary(run)" in dashboard
    assert "dashboardRunHref" in dashboard
    assert "localizePath(dashboardRunHref(run), locale)" in dashboard
    assert "dashboardRunKindLabel(run, locale)" in dashboard
    assert 'if (run.kind === "replication")' in dashboard_helpers
    assert "`/strategies/${run.run_id}`" in dashboard_helpers
