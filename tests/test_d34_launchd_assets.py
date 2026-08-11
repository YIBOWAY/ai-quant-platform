from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_d34_launchagent_runs_one_bounded_cycle_from_release_checkout() -> None:
    runner = (ROOT / "scripts" / "run_d34_worker.sh").read_text(encoding="utf-8")
    template = plistlib.loads(
        (
            ROOT
            / "scripts"
            / "launchd"
            / "com.aiquant.d34-worker.plist.template"
        )
        .read_bytes()
        .replace(b"__ROOT__", str(ROOT).encode("utf-8"))
    )

    assert 'PYTHONPATH="$ROOT/src' in runner
    assert "QS_DATABASE_AUTO_MIGRATE=false" in runner
    assert "-m quant_system.cli d34 worker-once" in runner
    assert "--platform-root" in runner
    assert "--hqa-root" in runner
    assert 'case "${1:-}" in' in runner
    assert "--check" in runner
    assert template["RunAtLoad"] is True
    assert template["StartInterval"] == 300
    assert template["ProcessType"] == "Background"
    assert template["ProgramArguments"] == [
        "/bin/bash",
        str(ROOT / "scripts" / "run_d34_worker.sh"),
    ]
    assert "KeepAlive" not in template


def test_local_stack_owns_d34_worker_lifecycle_and_stable_logs() -> None:
    stack = (ROOT / "scripts" / "local_mac_stack.sh").read_text(encoding="utf-8")

    assert 'bash "$ROOT/scripts/install_d34_worker_launchagent.sh"' in stack
    assert "bootout_job com.aiquant.d34-worker" in stack
    assert "print_job_status com.aiquant.d34-worker" in stack
    assert "d34_worker_log=" in stack
    assert "Codex" in stack and "Claude Code" in stack


def test_d34_install_assets_are_user_launchagent_only() -> None:
    installer = (ROOT / "scripts" / "install_d34_worker_launchagent.sh").read_text(
        encoding="utf-8"
    )
    uninstaller = (
        ROOT / "scripts" / "uninstall_d34_worker_launchagent.sh"
    ).read_text(encoding="utf-8")

    assert "Library/LaunchAgents" in installer
    assert "Library/LaunchAgents" in uninstaller
    assert "launchctl" in installer
    assert "launchctl" in uninstaller
    assert "|| true" not in installer + uninstaller
    assert "bootout_if_loaded()" in installer + uninstaller
    assert "sudo" not in installer + uninstaller


def test_d34_runner_check_imports_release_without_using_an_agent_terminal(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "backend.env"
    env_file.write_text("QS_DATABASE_AUTO_MIGRATE=false\n", encoding="utf-8")
    env_file.chmod(0o600)
    hqa_root = tmp_path / "hqa-root"
    (hqa_root / "hqa").mkdir(parents=True)

    completed = subprocess.run(
        [str(ROOT / "scripts" / "run_d34_worker.sh"), "--check"],
        cwd=ROOT,
        env={
            **os.environ,
            "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
            "QS_D34_HQA_ROOT": str(hqa_root),
            "QS_D34_WORKER_PYTHON": sys.executable,
            "QS_MAIN_REPO_ROOT": str(ROOT),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "d34_worker_ready=true" in completed.stdout
    assert str(ROOT) in completed.stdout
