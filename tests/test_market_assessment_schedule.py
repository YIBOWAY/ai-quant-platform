"""Scheduler transport tests replay captured real market documents only."""

import importlib.util
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "assessment_schedule", ROOT / "scripts/refresh_market_assessments.py"
)
schedule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedule)


def test_schedule_submits_each_scope_once_and_reports_real_snapshot_results():
    requests = []

    def transport(request):
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("owner/session"):
            return httpx.Response(200, headers={"set-cookie": "qs_aw_csrf=test-csrf; Path=/"})
        if request.method == "POST":
            assert request.headers["x-csrf-token"] == "test-csrf"
            assert json.loads(request.content)["include_ai"] is True
            return httpx.Response(202, json={"status": "updating"})
        scope = request.url.params["scope"]
        document = json.loads(
            (ROOT / "artifacts/market-outlook-2026-09-05" / f"{scope}-final.json").read_text()
        )
        return httpx.Response(200, json=document)

    with httpx.Client(
        base_url="http://127.0.0.1:8765", transport=httpx.MockTransport(transport)
    ) as client:
        results = schedule.refresh_all(client)
    assert [item["scope"] for item in results] == ["asia", "us"]
    assert all(item["ai_ready"] for item in results)
    assert sum(method == "POST" for method, _ in requests) == 2
    assert requests[0] == ("GET", "/api/auth/owner/session")


def test_existing_daily_job_runs_market_analysis_even_when_asia_price_refresh_fails():
    script = (ROOT / "scripts/run_asia_radar_refresh.sh").read_text()
    assert "data asia-radar-refresh || result=$?" in script
    assert '"$ROOT/scripts/refresh_market_assessments.py" || result=$?' in script
    assert 'exit "$result"' in script
