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
    assert 'const e2eDataRoot = path.join(frontendRoot, ".tmp", "e2e-data")' in config
    assert "QS_DATA_DIR: e2eDataRoot" in backend_block
    assert 'QS_PARQUET_DIR: path.join(e2eDataRoot, "parquet")' in backend_block
    assert 'QS_DUCKDB_PATH: path.join(e2eDataRoot, "quant_system.duckdb")' in backend_block
    assert (
        'QS_OPTIONS_RADAR_OUTPUT_DIR: path.join(e2eDataRoot, "options_scans")'
        in backend_block
    )
    assert "QS_OPTIONS_RADAR_UNIVERSE_PATH" in compact_backend_block
    assert "QS_OPTIONS_RADAR_EARNINGS_CALENDAR_PATH" in compact_backend_block
    assert "QS_OPTIONS_RADAR_VIX_HISTORY_PATH" in compact_backend_block
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


def test_dev_scripts_use_project_ports_and_docker_database_probe() -> None:
    dev_script = Path("scripts/dev.ps1").read_text(encoding="utf-8")
    stop_script = Path("scripts/dev-stop.ps1").read_text(encoding="utf-8")

    assert '[int]$BackendPort = 8765' in dev_script
    assert '[int]$FrontendPort = 3001' in dev_script
    assert '[string]$DatabaseContainer = "quantplatform-db"' in dev_script
    assert "docker start $DatabaseContainer" in dev_script
    assert "docker exec $DatabaseContainer pg_isready" in dev_script
    assert 'Join-Path $CondaBase "envs\\ai-quant\\python.exe"' in dev_script
    assert dev_script.index('Join-Path $CondaBase "envs\\ai-quant\\python.exe"') < dev_script.index(
        'Join-Path $env:CONDA_PREFIX "python.exe"'
    )
    assert '$env:PYTHONPATH = (Join-Path $Root "src")' in dev_script
    assert '$env:NEXT_PUBLIC_QUANT_API_BASE_URL = "http://$BackendHost`:$BackendPort"' in dev_script
    assert "backend_url=http://$BackendHost`:$BackendPort" in dev_script
    assert "frontend_url=http://$FrontendHost`:$FrontendPort" in dev_script
    assert 'Join-Path $Root "data\\_runtime\\pids"' in stop_script
    assert "function Stop-ProcessTree" in stop_script
    assert "Where-Object { $_.ParentProcessId -eq $RootProcessId }" in stop_script
    assert 'foreach ($Name in @("frontend", "backend"))' in stop_script


def test_options_radar_scheduler_script_uses_env_python_and_runtime_log() -> None:
    script = Path("scripts/run_options_radar.ps1").read_text(encoding="utf-8")

    assert "D:\\anaconda3" not in script
    assert "conda info --base" in script
    assert 'Join-Path $CondaBase "envs\\ai-quant\\python.exe"' in script
    assert 'Join-Path $env:CONDA_PREFIX "python.exe"' in script
    assert 'Join-Path $Root "data\\_runtime\\logs"' in script
    assert '"options-radar.log"' in script
    assert "Tee-Object" in script
    assert "options daily-task --top 100" in script
    assert "--universe-source public" in script
    assert "--earnings-source public" in script
    assert "--vix-source public" in script


def test_options_radar_task_registration_script_targets_scheduler_entrypoint() -> None:
    script = Path("scripts/register_options_radar_task.ps1").read_text(
        encoding="utf-8"
    )

    assert '[string]$TaskName = "AIQuant Options Radar Daily Task"' in script
    assert '[string]$StartTime = "06:30"' in script
    assert 'Join-Path $Root "scripts\\run_options_radar.ps1"' in script
    assert "schtasks.exe /Create" in script
    assert "/SC" in script
    assert "WEEKLY" in script
    assert "/D" in script
    assert "MON,TUE,WED,THU,FRI" in script
    assert "/ST" in script
    assert "$StartTime" in script
    assert "/TN" in script
    assert "$TaskName" in script
    assert "/TR" in script
    assert "powershell.exe" in script
    assert "run_options_radar.ps1" in script
    assert "/F" in script
    assert "Start-ScheduledTask" not in script
    assert "run_options_radar.ps1 2>&1" not in script


def test_frontend_package_has_no_ai_studio_template_residue() -> None:
    package = json.loads(
        Path("src/frontend/package.json").read_text(encoding="utf-8")
    )
    env_example = Path("src/frontend/.env.example").read_text(encoding="utf-8")
    next_config = Path("src/frontend/next.config.ts").read_text(encoding="utf-8")
    playwright_config = Path("src/frontend/playwright.config.ts").read_text(
        encoding="utf-8"
    )
    app_metadata = Path("src/frontend/metadata.json")

    assert package["name"] == "ai-quant-platform-frontend"
    assert "@google/genai" not in package["dependencies"]
    assert "firebase-tools" not in package["devDependencies"]
    assert not app_metadata.exists()
    assert "AI Studio" not in env_example
    assert "GEMINI_API_KEY" not in env_example
    assert "Cloud Run" not in env_example
    assert "APP_URL" not in env_example
    assert "ignoreDuringBuilds" not in next_config
    assert "DISABLE_HMR" not in next_config
    assert "DISABLE_HMR" not in playwright_config
