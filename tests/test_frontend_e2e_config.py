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
