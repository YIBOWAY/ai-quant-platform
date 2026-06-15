import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from quant_system.api.safety.masking import mask_secret_fields
from quant_system.api.server import create_app
from quant_system.config.settings import reload_settings


def test_every_json_response_has_safety_footer(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    for path in ["/api/health", "/api/settings", "/api/factors", "/api/orders/submit"]:
        response = client.get(path)
        payload = response.json()
        assert "safety" in payload
        assert payload["safety"]["live_trading_enabled"] is False


def test_safety_footer_overrides_route_payload_safety(tmp_path) -> None:
    app = create_app(output_dir=tmp_path)

    @app.get("/api/test-shadow-safety")
    def shadow_safety() -> dict:
        return {
            "status": "ok",
            "safety": {
                "dry_run": False,
                "paper_trading": False,
                "live_trading_enabled": True,
                "kill_switch": False,
                "bind_address": "0.0.0.0",
            },
        }

    client = TestClient(app)

    response = client.get("/api/test-shadow-safety")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["safety"]["dry_run"] is True
    assert payload["safety"]["paper_trading"] is True
    assert payload["safety"]["live_trading_enabled"] is False
    assert payload["safety"]["kill_switch"] is True
    assert payload["safety"]["bind_address"] == "127.0.0.1"


def test_settings_masks_secret_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_TIINGO_API_TOKEN", "super-secret-token")
    reload_settings()
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/settings")

    assert response.status_code == 200
    payload_text = response.text
    assert "super-secret-token" not in payload_text
    assert payload_text.count("***") >= 1


def test_secret_values_are_masked_even_without_secret_like_keys() -> None:
    payload = {
        "credential": SecretStr("not-in-key-name"),
        "nested": [{"value": SecretStr("nested-secret-value")}],
    }

    masked = mask_secret_fields(payload)

    assert masked == {
        "credential": "***",
        "nested": [{"value": "***"}],
    }
    assert "not-in-key-name" not in str(masked)
    assert "nested-secret-value" not in str(masked)


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
        ".cancel_order(",
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


def test_futu_skill_mutating_trade_entrypoints_are_disabled() -> None:
    trade_root = Path(".agents/skills/futuapi/scripts/trade")
    if not trade_root.is_dir():
        pytest.skip("local futuapi skill is not installed under .agents")

    scripts = (
        trade_root / "place_order.py",
        trade_root / "modify_order.py",
        trade_root / "cancel_order.py",
    )
    redlines = (
        "from futu",
        "OpenSecTradeContext",
        "create_trade_context",
        "TrdEnv.REAL",
        ".place_order(",
        ".modify_order(",
        ".cancel_order(",
        "unlock_trade(",
    )

    for script in scripts:
        assert script.is_file()
        text = script.read_text(encoding="utf-8")
        assert "disabled" in text.lower()
        assert "paper account APIs" in text
        for marker in redlines:
            assert marker not in text

        completed = subprocess.run(
            [sys.executable, str(script), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )

        assert completed.returncode == 2
        payload = json.loads(completed.stdout)
        assert "disabled" in payload["error"].lower()
