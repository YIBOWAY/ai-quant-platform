from pathlib import Path


def test_dashboard_uses_recent_runs_activity_log() -> None:
    api_client = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")
    dashboard = Path("src/frontend/app/page.tsx").read_text(encoding="utf-8")

    assert "export type RecentRunKind = \"backtest\" | \"factor\" | \"paper\";" in api_client
    assert "export function getRecentRuns" in api_client
    assert "/api/runs/recent?" in api_client

    assert "getRecentRuns" in dashboard
    assert "recentRuns.apiError" in dashboard
    assert "recentRuns.runs.length > 0" in dashboard
    assert "formatRunSummary" in dashboard
    assert "runHref(run)" in dashboard
