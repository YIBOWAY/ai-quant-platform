from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "backend_non_postgres_gate.py"


def _gate_helper():
    spec = importlib.util.spec_from_file_location(
        "backend_non_postgres_gate_environment_repairs",
        HELPER,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_environment_preserves_product_feature_and_provider_defaults(
    tmp_path: Path,
) -> None:
    helper = _gate_helper()
    transient_paths = helper._transient_paths(tmp_path / "runtime")
    environment = helper._test_environment(
        transient_paths,
        tmp_path / "uv-bin" / "uv",
        tmp_path / "node-bin" / "node",
    )

    for semantic_override in (
        "QS_AIHOT_ENABLED",
        "QS_DEFAULT_DATA_PROVIDER",
        "QS_FUTU_ENABLED",
        "QS_HORIZON_ENABLED",
        "QS_LLM_PROVIDER",
        "QS_OPTIONS_RADAR_ENABLED",
        "QS_OPTIONS_RADAR_PROVIDER",
        "QS_PREDICTION_MARKET_PROVIDER",
    ):
        assert semantic_override not in environment

    assert {
        name: environment[name]
        for name in (
            "QS_DATABASE_AUTO_MIGRATE",
            "QS_DATABASE_ENABLED",
            "QS_DRY_RUN",
            "QS_KILL_SWITCH",
            "QS_LIVE_TRADING_ENABLED",
            "QS_LOCAL_MUTATION_ENABLED",
            "QS_PAPER_ACCOUNT_DB_MODE",
            "QS_PAPER_TRADING",
            "QS_TEST_FUTU_OPEND",
        )
    } == {
        "QS_DATABASE_AUTO_MIGRATE": "false",
        "QS_DATABASE_ENABLED": "false",
        "QS_DRY_RUN": "true",
        "QS_KILL_SWITCH": "true",
        "QS_LIVE_TRADING_ENABLED": "false",
        "QS_LOCAL_MUTATION_ENABLED": "false",
        "QS_PAPER_ACCOUNT_DB_MODE": "file",
        "QS_PAPER_TRADING": "true",
        "QS_TEST_FUTU_OPEND": "0",
    }
