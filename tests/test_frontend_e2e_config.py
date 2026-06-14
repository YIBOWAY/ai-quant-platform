import json
from pathlib import Path


def test_playwright_backend_uses_isolated_test_environment() -> None:
    config = Path("src/frontend/playwright.config.ts").read_text(encoding="utf-8")
    compact = " ".join(config.split())

    backend_block_start = config.index("QUANT_API_COMMAND")
    backend_block_end = config.index('command: "npm run dev', backend_block_start)
    backend_block = config[backend_block_start:backend_block_end]
    compact_backend_block = " ".join(backend_block.split())

    assert 'QS_ENVIRONMENT: "test"' in backend_block
    assert 'QS_DATABASE_ENABLED: "false"' in backend_block
    assert 'QS_DATABASE_AUTO_MIGRATE: "false"' in backend_block
    assert 'QS_DATA_DIR: path.join(frontendRoot, ".tmp", "e2e-data")' in backend_block
    assert 'QS_PARQUET_DIR: path.join(frontendRoot, ".tmp", "e2e-data", "parquet")' in backend_block
    assert (
        'QS_DUCKDB_PATH: path.join( frontendRoot, ".tmp", "e2e-data", "quant_system.duckdb", )'
        in compact_backend_block
    )
    assert "QS_DATABASE_ENABLED" not in compact.split('command: "npm run dev', maxsplit=1)[1]


def test_frontend_dev_defaults_to_project_ports() -> None:
    package = json.loads(
        Path("src/frontend/package.json").read_text(encoding="utf-8")
    )
    start_script = Path("scripts/start_phase9_full_stack.ps1").read_text(
        encoding="utf-8"
    )
    playwright_config = Path("src/frontend/playwright.config.ts").read_text(
        encoding="utf-8"
    )

    assert package["scripts"]["dev"] == "next dev --hostname 127.0.0.1 --port 3001"
    assert '[int]$BackendPort = 8765' in start_script
    assert '[int]$FrontendPort = 3001' in start_script
    assert '-ArgumentList @("run", "dev")' in start_script
    assert 'command: "npm run dev"' in playwright_config
    assert 'command: "npm run dev -- --hostname 127.0.0.1 --port 3001"' not in playwright_config


def test_frontend_package_has_no_ai_studio_template_residue() -> None:
    package = json.loads(
        Path("src/frontend/package.json").read_text(encoding="utf-8")
    )
    next_config = Path("src/frontend/next.config.ts").read_text(encoding="utf-8")
    playwright_config = Path("src/frontend/playwright.config.ts").read_text(
        encoding="utf-8"
    )

    assert package["name"] == "ai-quant-platform-frontend"
    assert "@google/genai" not in package["dependencies"]
    assert "firebase-tools" not in package["devDependencies"]
    assert "ignoreDuringBuilds" not in next_config
    assert "DISABLE_HMR" not in next_config
    assert "DISABLE_HMR" not in playwright_config
