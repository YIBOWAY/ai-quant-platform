import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import reload_settings


def test_every_json_response_has_safety_footer(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    for path in ["/api/health", "/api/settings", "/api/factors", "/api/orders/submit"]:
        response = client.get(path)
        payload = response.json()
        assert "safety" in payload
        assert payload["safety"]["live_trading_enabled"] is False


def test_settings_masks_secret_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_TIINGO_API_TOKEN", "super-secret-token")
    reload_settings()
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/settings")

    assert response.status_code == 200
    payload_text = response.text
    assert "super-secret-token" not in payload_text
    assert payload_text.count("***") >= 1


def test_forbidden_order_submit_route_does_not_exist(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post("/api/orders/submit", json={})

    assert response.status_code == 404
    assert response.json()["safety"]["dry_run"] is True


def test_repository_does_not_contain_live_trading_redlines() -> None:
    redlines = (
        "OpenSecTradeContext",
        "TradeContext",
        "trd_open",
        "unlock_trade(",
        "ctx.place_order(",
        "ctx.modify_order(",
        "ctx.cancel_order(",
        "trd_env=TrdEnv.REAL",
        "TrdEnv.REAL",
    )
    allowed_files = {
        Path("tests/test_api_safety.py"),
    }
    executable_roots = ("src/", "scripts/", "tests/")
    tracked = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    hits: list[str] = []
    for raw_path in [*tracked, *untracked]:
        if not raw_path.startswith(executable_roots):
            continue
        path = Path(raw_path)
        if not path.is_file() or path.suffix.lower() not in {
            ".py",
            ".md",
            ".ts",
            ".tsx",
            ".js",
            ".html",
        }:
            continue
        normalized = Path(path.as_posix())
        if normalized in allowed_files:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in redlines:
            if marker in text:
                hits.append(f"{path}:{marker}")

    assert hits == []


def test_futu_skill_does_not_ship_mutating_trade_scripts() -> None:
    redlines = (
        ".place_order(",
        ".modify_order(",
        ".cancel_all_order(",
        "unlock_trade(",
    )
    hits: list[str] = []
    skill_root = Path(".agents/skills/futuapi")
    for path in skill_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in redlines:
            if marker in text:
                hits.append(f"{path}:{marker}")

    assert hits == []
