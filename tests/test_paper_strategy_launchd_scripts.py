from pathlib import Path


def test_paper_strategy_launchd_wrapper_is_scheduler_safe() -> None:
    script = Path("scripts/run_paper_strategy_sleeves.sh").read_text(
        encoding="utf-8"
    )

    assert "QS_PAPER_STRATEGY_PYTHON" in script
    assert 'PYTHONPATH="$ROOT/src' in script
    assert "data/_runtime/logs" in script
    assert "paper-strategy-sleeves.log" in script
    assert "paper strategies generate-due-signals" in script
    assert "paper strategies execute-due" in script
    assert "paper strategies ops-status --format json" in script
    assert "tee -a" in script
    assert "sudo" not in script


def test_mac_local_service_wrappers_bind_to_localhost_and_keep_logs() -> None:
    backend = Path("scripts/run_quant_backend.sh").read_text(encoding="utf-8")
    frontend = Path("scripts/run_quant_frontend.sh").read_text(encoding="utf-8")

    assert "quant-system serve --host 127.0.0.1 --port 8765" in backend
    assert "QS_API_BIND_ADDRESS=127.0.0.1" in backend
    assert "backend-api.launchd.log" in backend
    assert "NEXT_PUBLIC_QUANT_API_BASE_URL" in frontend
    assert 'exec "$NODE_BIN" "$NEXT_BIN" start -H 127.0.0.1 -p 3001' in frontend
    assert "release_build_missing" in frontend
    assert "frontend-next.launchd.log" in frontend
    assert "npm run dev" not in frontend
    assert "sudo" not in backend + frontend


def test_launchagent_templates_separate_services_from_one_shot_strategy_jobs() -> None:
    launchd_dir = Path("scripts/launchd")
    backend = (launchd_dir / "com.aiquant.backend.plist.template").read_text(
        encoding="utf-8"
    )
    frontend = (launchd_dir / "com.aiquant.frontend.plist.template").read_text(
        encoding="utf-8"
    )
    signals = (
        launchd_dir / "com.aiquant.paper-sleeves.signals.plist.template"
    ).read_text(encoding="utf-8")
    execute_due = (
        launchd_dir / "com.aiquant.paper-sleeves.execute-due.plist.template"
    ).read_text(encoding="utf-8")
    ops_status = (
        launchd_dir / "com.aiquant.paper-sleeves.ops-status.plist.template"
    ).read_text(encoding="utf-8")

    for template in [backend, frontend, signals, execute_due, ops_status]:
        assert "__ROOT__" in template
        assert "<key>StandardOutPath</key>" in template
        assert "<key>StandardErrorPath</key>" in template
        assert "LaunchDaemon" not in template

    assert "<key>KeepAlive</key>\n  <true/>" in backend
    assert "<key>KeepAlive</key>\n  <true/>" in frontend
    for template in [signals, execute_due, ops_status]:
        assert "<key>KeepAlive</key>\n  <false/>" in template
        assert "<key>StartCalendarInterval</key>" in template
    assert "generate-due-signals" in signals
    assert "execute-due" in execute_due
    assert "ops-status" in ops_status


def test_launchagent_install_scripts_do_not_require_sudo() -> None:
    install = Path("scripts/install_paper_strategy_sleeves_launchagent.sh").read_text(
        encoding="utf-8"
    )
    uninstall = Path(
        "scripts/uninstall_paper_strategy_sleeves_launchagent.sh"
    ).read_text(encoding="utf-8")

    assert "launchctl bootstrap gui/$(id -u)" in install
    assert "launchctl bootout gui/$(id -u)" in uninstall
    assert "Library/LaunchAgents" in install
    assert "Library/LaunchAgents" in uninstall
    assert "sudo" not in install
    assert "sudo" not in uninstall


def test_paper_strategy_launchd_runbook_keeps_paper_only_boundaries() -> None:
    runbook = Path("docs/execution/paper_strategy_sleeves_launchd.md").read_text(
        encoding="utf-8"
    )

    assert "LaunchAgent" in runbook
    assert "LaunchDaemon" in runbook
    assert "no sudo" in runbook.lower()
    assert "UI availability does not mean auto-execution is enabled" in runbook
    assert "KeepAlive=false" in runbook
    assert "live trading" in runbook.lower()
