from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "install_agent_v02_stack_launchagents.sh",
    "install_agent_v02_connector_launchagent.sh",
    "uninstall_agent_v02_stack_launchagents.sh",
    "uninstall_agent_v02_connector_launchagent.sh",
)


def write_launchctl(path: Path, *, exit_code: int, message: str) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' {message!r} >&2\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


def test_launchagent_scripts_have_no_blanket_success_mask() -> None:
    for name in SCRIPTS:
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")

        assert "|| true" not in source
        assert "bootout_if_loaded()" in source
        assert "Boot-out failed: 3: No such process" in source
        assert (
            "Boot-out failed: 113: Could not find specified service"
            in source
        )


@pytest.mark.parametrize(
    "script_name",
    (
        "uninstall_agent_v02_stack_launchagents.sh",
        "uninstall_agent_v02_connector_launchagent.sh",
    ),
)
def test_uninstallers_preserve_unexpected_bootout_failure(
    tmp_path: Path,
    script_name: str,
) -> None:
    home = tmp_path / "home"
    launchagents = home / "Library" / "LaunchAgents"
    launchagents.mkdir(parents=True)
    label = (
        "com.aiquant.backend"
        if "stack" in script_name
        else "com.aiquant.agent-v02-connector"
    )
    target = launchagents / f"{label}.plist"
    target.write_text("must remain", encoding="utf-8")
    script = tmp_path / script_name
    shutil.copy2(ROOT / "scripts" / script_name, script)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    launchctl = tmp_path / "launchctl"
    write_launchctl(
        launchctl,
        exit_code=42,
        message="Boot-out failed: 42: Operation not permitted",
    )

    completed = subprocess.run(
        [str(script)],
        check=False,
        cwd=tmp_path,
        env={
            **os.environ,
            "HOME": str(home),
            "QS_LAUNCHCTL_BIN": str(launchctl),
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert completed.returncode == 42
    assert "Operation not permitted" in completed.stderr
    assert target.read_text(encoding="utf-8") == "must remain"


@pytest.mark.parametrize(
    ("exit_code", "message"),
    (
        (3, "Boot-out failed: 3: No such process"),
        (113, "Boot-out failed: 113: Could not find specified service"),
    ),
)
def test_connector_uninstaller_accepts_only_exact_absent_service(
    tmp_path: Path,
    exit_code: int,
    message: str,
) -> None:
    home = tmp_path / "home"
    launchagents = home / "Library" / "LaunchAgents"
    launchagents.mkdir(parents=True)
    target = launchagents / "com.aiquant.agent-v02-connector.plist"
    target.write_text("old", encoding="utf-8")
    script = tmp_path / "uninstall.sh"
    shutil.copy2(
        ROOT / "scripts" / "uninstall_agent_v02_connector_launchagent.sh",
        script,
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    launchctl = tmp_path / "launchctl"
    write_launchctl(launchctl, exit_code=exit_code, message=message)

    completed = subprocess.run(
        [str(script)],
        check=False,
        cwd=tmp_path,
        env={
            **os.environ,
            "HOME": str(home),
            "QS_LAUNCHCTL_BIN": str(launchctl),
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"already_unloaded=gui/{os.getuid()}/" in completed.stdout
    assert not target.exists()
