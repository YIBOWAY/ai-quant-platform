import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def test_playwright_backend_uses_isolated_test_environment() -> None:
    config = Path("src/frontend/playwright.config.ts").read_text(encoding="utf-8")

    backend_block_start = config.index("QUANT_API_COMMAND")
    backend_block_end = config.index("NEXT_PUBLIC_QUANT_API_BASE_URL", backend_block_start)
    backend_block = config[backend_block_start:backend_block_end]
    compact_backend_block = " ".join(backend_block.split())
    frontend_block = config[backend_block_end:]

    assert 'QS_ENVIRONMENT: "test"' in backend_block
    assert 'QS_DATABASE_ENABLED: "false"' in backend_block
    assert 'QS_DATABASE_AUTO_MIGRATE: "false"' in backend_block
    assert 'QS_AIHOT_ENABLED: "false"' in backend_block
    assert "QS_HERMES_ARTIFACT_FEED_PATH: hermesArtifactFixture" in backend_block
    assert "QS_HERMES_ARTIFACT_FRESHNESS_BUDGET_SECONDS" in backend_block
    assert "QS_API_CORS_ORIGINS: JSON.stringify(e2eCorsOrigins)" in backend_block
    assert "frontendUrl" in backend_block
    assert (
        'const e2eDataRootBase = path.join(frontendRoot, ".tmp", "e2e-data")'
        in config
    )
    assert "const e2eRunIdentity = buildE2ERunIdentity({" in config
    assert "rawRunId: process.env.PW_E2E_RUN_ID" in config
    assert "const e2eDataRoot = e2eRunIdentity.dataRoot" in config
    assert "QS_DATA_DIR: e2eDataRoot" in backend_block
    assert 'QS_AGENT_OUTPUT_DIR: path.join(e2eDataRoot, "agent-output")' in backend_block
    assert 'QS_PARQUET_DIR: path.join(e2eDataRoot, "parquet")' in backend_block
    assert 'QS_DUCKDB_PATH: path.join(e2eDataRoot, "quant_system.duckdb")' in backend_block
    assert (
        'QS_OPTIONS_RADAR_OUTPUT_DIR: path.join( e2eDataRoot, "options_scans", )'
        in compact_backend_block
    )
    assert "QS_OPTIONS_RADAR_UNIVERSE_PATH" in compact_backend_block
    assert "QS_OPTIONS_RADAR_EARNINGS_CALENDAR_PATH" in compact_backend_block
    assert "QS_OPTIONS_RADAR_VIX_HISTORY_PATH" in compact_backend_block
    assert "QS_DATABASE_ENABLED" not in frontend_block


def test_playwright_supervises_per_run_data_root_and_binds_safe_provenance() -> None:
    config = Path("src/frontend/playwright.config.ts").read_text(encoding="utf-8")
    runner = Path(
        "src/frontend/tests/support/hermes-e2e-backend-runner.mjs"
    ).read_text(encoding="utf-8")
    ownership = Path(
        "src/frontend/tests/support/hermes-e2e-run-root.mjs"
    ).read_text(encoding="utf-8")

    assert "const backendCommand = buildSupervisedBackendCommand()" in config
    assert "hermes-e2e-backend-runner.mjs" in config
    assert "backendPort" in config
    assert "frontendPort" in config
    assert "runId: e2eRunIdentity.runId" in config
    assert "dataRoot: e2eDataRoot" in config
    assert "fixture: fixtureIdentity" in config
    assert 'gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 }' in config
    assert "prepareE2ERunRoot(identity" in runner
    assert "cleanupE2ERunRoot(identity, {" in runner
    assert "fixture: payload.fixture ?? null" in runner
    assert "crypto.randomBytes(32)" in runner
    assert "result.signal === forwardedShutdownSignal" in runner
    assert "assertBoundedChild(identity.baseRoot, identity.dataRoot)" in ownership
    assert "provenance mismatch; cleanup refused" in ownership


def test_playwright_fixture_readiness_is_separate_from_gateway_truth() -> None:
    config = Path("src/frontend/playwright.config.ts").read_text(encoding="utf-8")
    fixture_server = Path(
        "src/frontend/tests/support/hermes-fixture-api.mjs"
    ).read_text(encoding="utf-8")

    assert '`${backendUrl}/api/hermes/fixture-ready`' in config
    assert '`${backendUrl}/api/hermes/gateway`' in config
    assert 'pathname === "/api/hermes/fixture-ready"' in fixture_server
    assert 'transport: "loopback_get_only_fixture"' in fixture_server
    assert 'pathname === "/api/hermes/gateway"' in fixture_server
    assert "includeFixtureGateway: true" in fixture_server
    assert 'readOptionalFlag( "PW_HERMES_LIFECYCLE_FIXTURE", )' in " ".join(
        config.split()
    )
    assert "lifecycleFixtureMode && hermesWorkbenchFixture !== null" in config
    assert 'QS_HERMES_CHAT_ENABLED: "true"' in config
    assert 'QUANT_API_REWRITE_ORIGIN: backendUrl' in config
    assert 'includeLifecycle: mode === "lifecycle"' in fixture_server
    assert 'transport: "loopback_lifecycle_fixture"' in fixture_server


def test_hermes_closure_specs_declare_only_exact_mode_tests_without_skips() -> None:
    specs = {
        "matrix": Path(
            "src/frontend/tests/e2e/hermes-closure-matrix.spec.ts"
        ).read_text(encoding="utf-8"),
        "quality": Path(
            "src/frontend/tests/e2e/hermes-closure-quality.spec.ts"
        ).read_text(encoding="utf-8"),
        "lifecycle": Path(
            "src/frontend/tests/e2e/hermes-lifecycle.spec.ts"
        ).read_text(encoding="utf-8"),
    }
    forbidden = re.compile(r"test\.(?:skip|fixme)\b|\btodo\b", re.IGNORECASE)

    for name, spec in specs.items():
        assert "const modeMatches =" in spec, name
        assert "if (modeMatches) {" in spec, name
        first_test = re.search(r"\btest(?:\.describe)?\(", spec)
        assert first_test is not None, name
        assert spec.index("if (modeMatches) {") < first_test.start(), name
        assert forbidden.search(spec) is None, name
        assert "requires PW_E2E" not in spec, name

    assert 'process.env.PW_HERMES_WORKBENCH_FIXTURE === "normal"' in specs["matrix"]
    assert "closureFixtures.has(fixture)" in specs["quality"]
    assert 'process.env.PW_HERMES_LIFECYCLE_FIXTURE === "1"' in specs["lifecycle"]


def test_hermes_e2e_fixture_covers_all_read_only_artifact_kinds() -> None:
    fixture = json.loads(
        Path("src/frontend/tests/fixtures/hermes-artifacts.v1.json").read_text(
            encoding="utf-8"
        )
    )
    spec = Path("src/frontend/tests/e2e/hermes-artifacts.spec.ts").read_text(
        encoding="utf-8"
    )

    expected_kinds = {
        "portfolio_risk",
        "prediction",
        "market_foresight",
        "weekly_review",
        "opportunity_summary",
        "automation_status",
    }
    assert fixture["schema_version"] == "1.1"
    assert {item["kind"] for item in fixture["items"]} == expected_kinds
    assert {source["kind"] for source in fixture["sources"]} == expected_kinds
    candidate = next(
        item for item in fixture["items"] if item["kind"] == "market_foresight"
    )["data"]["candidates"][0]
    assert candidate["proposal_only"] is True
    assert candidate["requires_human_confirmation"] is True
    assert candidate["trading_allowed"] is False
    for kind in ("weekly_review", "opportunity_summary", "automation_status"):
        data = next(item for item in fixture["items"] if item["kind"] == kind)[
            "data"
        ]
        assert data["proposal_only"] is True
        assert data["trading_allowed"] is False
    assert 'page.goto("/zh/hermes")' in spec
    for visible_text in ("周报复盘", "机会复盘", "自动化状态"):
        assert visible_text in spec
    assert "toBeDisabled()" in spec


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
    assert 'const backendPort = readPort("PW_BACKEND_PORT", 8765)' in playwright_config
    assert 'const frontendPort = readPort("PW_FRONTEND_PORT", 3001)' in playwright_config
    assert "baseURL: frontendUrl" in playwright_config
    assert "const e2eCorsOrigins = Array.from(" in playwright_config
    assert "const frontendCommand = buildFrontendCommand(frontendPort)" in playwright_config
    assert "port === 3001" in playwright_config
    assert '? "npm run dev"' in playwright_config
    assert ': `npx next dev --hostname 127.0.0.1 --port ${port}`' in playwright_config
    assert 'url: `${backendUrl}/api/health`' in playwright_config
    assert "url: frontendUrl" in playwright_config
    assert "NEXT_PUBLIC_QUANT_API_BASE_URL: backendUrl" in playwright_config
    assert 'command: "npm run dev -- --hostname 127.0.0.1 --port 3001"' not in playwright_config


def test_playwright_frontend_uses_an_isolated_workspace() -> None:
    config = Path("src/frontend/playwright.config.ts").read_text(encoding="utf-8")

    assert "const frontendCommand = buildFrontendCommand(frontendPort)" in config
    assert "node scripts/prepare-e2e-workspace.mjs ${port}" in config
    assert 'cd ".tmp/e2e-frontend-${port}"' in config
    assert "cwd: frontendRoot" in config
    assert "cwd: e2eFrontendRoot" not in config
    assert "prepareE2EFrontend" not in config


def test_e2e_workspace_preparer_refreshes_stale_copy_without_touching_source() -> None:
    frontend = Path("src/frontend").resolve()
    port = 60_000 + os.getpid() % 5_000
    workspace = frontend / ".tmp" / f"e2e-frontend-{port}"
    guarded_sources = [frontend / "next-env.d.ts", frontend / "tsconfig.json"]
    before = {path: path.read_bytes() for path in guarded_sources}

    try:
        shutil.rmtree(workspace, ignore_errors=True)
        subprocess.run(
            ["node", "scripts/prepare-e2e-workspace.mjs", str(port)],
            cwd=frontend,
            check=True,
            capture_output=True,
            text=True,
        )
        assert (workspace / "node_modules").exists()
        assert (workspace / ".source-fingerprint").is_file()

        (workspace / "next.config.ts").write_text("stale", encoding="utf-8")
        (workspace / ".source-fingerprint").write_text("stale", encoding="utf-8")
        subprocess.run(
            ["node", "scripts/prepare-e2e-workspace.mjs", str(port)],
            cwd=frontend,
            check=True,
            capture_output=True,
            text=True,
        )

        assert (workspace / "next.config.ts").read_bytes() == (
            frontend / "next.config.ts"
        ).read_bytes()
        assert {path: path.read_bytes() for path in guarded_sources} == before
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


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


def test_frontend_uses_single_flat_eslint_config() -> None:
    package = json.loads(
        Path("src/frontend/package.json").read_text(encoding="utf-8")
    )
    flat_config = Path("src/frontend/eslint.config.mjs")
    legacy_config = Path("src/frontend/.eslintrc.json")

    assert flat_config.exists()
    assert not legacy_config.exists()
    assert "eslint.config.mjs" in package["scripts"]["lint"]
    assert "eslint-config-next" in flat_config.read_text(encoding="utf-8")


def test_playwright_specs_avoid_fixed_waits_and_forced_clicks() -> None:
    offenders: list[str] = []

    for spec_path in sorted(Path("src/frontend/tests/e2e").glob("*.spec.ts")):
        spec = spec_path.read_text(encoding="utf-8")
        if "waitForTimeout(" in spec:
            offenders.append(f"{spec_path}: waitForTimeout")
        if re.search(r"\.click\(\s*\{[^}]*force\s*:\s*true", spec, re.S):
            offenders.append(f"{spec_path}: click force=true")

    assert not offenders
