from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_paper_run_rejects_disabling_global_kill_switch(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/paper/run",
        json={
            "symbols": ["SPY"],
            "start": "2024-01-02",
            "end": "2024-01-08",
            "enable_kill_switch": False,
        },
    )

    assert response.status_code == 409
    assert "kill switch" in response.json()["detail"].lower()
    assert response.json()["safety"]["kill_switch"] is True


def test_paper_run_list_and_detail_with_kill_switch_on(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    run_response = client.post(
        "/api/paper/run",
        json={
            "symbols": ["SPY"],
            "start": "2024-01-02",
            "end": "2024-01-08",
            "enable_kill_switch": True,
        },
    )

    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    list_response = client.get("/api/paper")
    assert list_response.status_code == 200
    assert run_id in {item["id"] for item in list_response.json()["paper_runs"]}

    detail_response = client.get(f"/api/paper/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["orders"]
    assert detail["risk_breaches"]
    assert detail["trades"] == []


def test_paper_detail_404_for_unknown_run(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/paper/does-not-exist")

    assert response.status_code == 404
    assert response.json()["safety"]["kill_switch"] is True
