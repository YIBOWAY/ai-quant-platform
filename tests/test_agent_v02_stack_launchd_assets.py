from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _copy_script(tmp_path: Path, name: str) -> tuple[Path, Path]:
    release_root = tmp_path / "release"
    scripts_dir = release_root / "scripts"
    scripts_dir.mkdir(parents=True)
    script = scripts_dir / name
    shutil.copy2(ROOT / "scripts" / name, script)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return release_root, script


def _write_frontend_env(release_root: Path, *, mode: int = 0o600) -> Path:
    env_file = release_root / "data" / "_runtime" / "agent-v0.2-frontend.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "QS_HERMES_CHAT_ENABLED=true\n"
        "NEXT_PUBLIC_QUANT_API_BASE_URL=http://127.0.0.1:8765\n",
        encoding="utf-8",
    )
    env_file.chmod(mode)
    return env_file


def _write_bash_node_shim(tmp_path: Path) -> Path:
    node_bin = tmp_path / "node-shim"
    node_bin.write_text(
        "#!/bin/sh\n"
        'exec /bin/bash "$@"\n',
        encoding="utf-8",
    )
    node_bin.chmod(0o700)
    return node_bin


def _prepare_stack_installer(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, str]]:
    release_root = tmp_path / "release"
    scripts_dir = release_root / "scripts"
    launchd_dir = scripts_dir / "launchd"
    launchd_dir.mkdir(parents=True)
    for name in (
        "run_quant_backend.sh",
        "run_quant_frontend.sh",
        "install_agent_v02_stack_launchagents.sh",
    ):
        target = scripts_dir / name
        shutil.copy2(ROOT / "scripts" / name, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    for name in (
        "com.aiquant.backend.plist.template",
        "com.aiquant.frontend.plist.template",
    ):
        shutil.copy2(ROOT / "scripts" / "launchd" / name, launchd_dir / name)

    (release_root / "src" / "quant_system").mkdir(parents=True)
    build_id = release_root / "src" / "frontend" / ".next" / "BUILD_ID"
    build_id.parent.mkdir(parents=True)
    build_id.write_text("release-build\n", encoding="utf-8")
    env_file = release_root / "data" / "_runtime" / "agent-v0.2-backend.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("QS_DATABASE_AUTO_MIGRATE=false\n", encoding="utf-8")
    env_file.chmod(0o600)
    frontend_env_file = _write_frontend_env(release_root)

    main_root = tmp_path / "main"
    python = main_root / "ai-quant" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    python.chmod(0o700)
    next_bin = main_root / "src" / "frontend" / "node_modules" / ".bin" / "next"
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    next_bin.chmod(0o700)
    node_bin = _write_bash_node_shim(tmp_path)

    home = tmp_path / "home"
    home.mkdir()
    return (
        release_root,
        scripts_dir / "install_agent_v02_stack_launchagents.sh",
        home,
        {
            **os.environ,
            "HOME": str(home),
            "QS_MAIN_REPO_ROOT": str(main_root),
            "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
            "QS_AGENT_V02_FRONTEND_ENV_FILE": str(frontend_env_file),
            "QS_QUANT_FRONTEND_NODE_BIN": str(node_bin),
        },
    )


def _write_eio_launchctl(
    tmp_path: Path,
    *,
    always_fail: bool,
) -> tuple[Path, Path]:
    launchctl_log = tmp_path / "launchctl.log"
    state_dir = tmp_path / "launchctl-state"
    state_dir.mkdir()
    launchctl = tmp_path / "launchctl"
    failure_condition = "true" if always_fail else '[[ "$attempt" -eq 1 ]]'
    launchctl.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{launchctl_log}"\n'
        '[[ "${1:-}" == "bootstrap" ]] || exit 0\n'
        f'STATE_DIR="{state_dir}"\n'
        'state="$STATE_DIR/${3##*/}.count"\n'
        'attempt=0\n'
        '[[ ! -f "$state" ]] || attempt="$(cat "$state")"\n'
        'attempt=$((attempt + 1))\n'
        'printf "%s\\n" "$attempt" > "$state"\n'
        f"if {failure_condition}; then\n"
        '  echo "Bootstrap failed: 5: Input/output error" >&2\n'
        "  exit 5\n"
        "fi\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o700)
    return launchctl, launchctl_log


def test_backend_check_uses_release_source_with_main_repo_python(
    tmp_path: Path,
) -> None:
    release_root, script = _copy_script(tmp_path, "run_quant_backend.sh")
    (release_root / "src" / "quant_system").mkdir(parents=True)

    main_root = tmp_path / "main"
    python = main_root / "ai-quant" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    python.chmod(0o700)

    env_file = release_root / "data" / "_runtime" / "agent-v0.2-backend.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("QS_DATABASE_ENABLED=true\n", encoding="utf-8")
    env_file.chmod(0o600)

    result = subprocess.run(
        [str(script), "--check"],
        cwd=release_root,
        env={
            **os.environ,
            "QS_MAIN_REPO_ROOT": str(main_root),
            "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "backend_ready=true" in result.stdout
    assert f"release_root={release_root}" in result.stdout
    assert f"python={python}" in result.stdout


def test_backend_rejects_non_owner_only_env_before_start(
    tmp_path: Path,
) -> None:
    release_root, script = _copy_script(tmp_path, "run_quant_backend.sh")
    (release_root / "src" / "quant_system").mkdir(parents=True)

    main_root = tmp_path / "main"
    python = main_root / "ai-quant" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    python.chmod(0o700)

    env_file = release_root / "data" / "_runtime" / "agent-v0.2-backend.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("QS_DATABASE_ENABLED=true\n", encoding="utf-8")
    env_file.chmod(0o640)

    result = subprocess.run(
        [str(script), "--check"],
        cwd=release_root,
        env={
            **os.environ,
            "QS_MAIN_REPO_ROOT": str(main_root),
            "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 78
    assert result.stdout == ""
    assert "backend_config_error=backend_env_mode_must_be_600" in result.stderr


def test_backend_rejects_startup_auto_migration_even_when_env_requests_it(
    tmp_path: Path,
) -> None:
    release_root, script = _copy_script(tmp_path, "run_quant_backend.sh")
    (release_root / "src" / "quant_system").mkdir(parents=True)

    main_root = tmp_path / "main"
    python = main_root / "ai-quant" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    python.chmod(0o700)

    env_file = release_root / "data" / "_runtime" / "agent-v0.2-backend.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("QS_DATABASE_AUTO_MIGRATE=true\n", encoding="utf-8")
    env_file.chmod(0o600)

    result = subprocess.run(
        [str(script), "--check"],
        cwd=release_root,
        env={
            **os.environ,
            "QS_MAIN_REPO_ROOT": str(main_root),
            "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 78
    assert "backend_config_error=database_auto_migrate_forbidden" in result.stderr


def test_frontend_check_uses_release_build_with_main_repo_next(
    tmp_path: Path,
) -> None:
    release_root, script = _copy_script(tmp_path, "run_quant_frontend.sh")
    env_file = _write_frontend_env(release_root)
    build_id = release_root / "src" / "frontend" / ".next" / "BUILD_ID"
    build_id.parent.mkdir(parents=True)
    build_id.write_text("release-build\n", encoding="utf-8")

    main_root = tmp_path / "main"
    next_bin = main_root / "src" / "frontend" / "node_modules" / ".bin" / "next"
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    next_bin.chmod(0o700)
    node_bin = _write_bash_node_shim(tmp_path)

    result = subprocess.run(
        [str(script), "--check"],
        cwd=release_root,
        env={
            **os.environ,
            "QS_MAIN_REPO_ROOT": str(main_root),
            "QS_AGENT_V02_FRONTEND_ENV_FILE": str(env_file),
            "QS_QUANT_FRONTEND_NODE_BIN": str(node_bin),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "frontend_ready=true" in result.stdout
    assert f"release_root={release_root}" in result.stdout
    assert f"next={next_bin}" in result.stdout


def test_frontend_check_resolves_node_outside_launchd_minimal_path(
    tmp_path: Path,
) -> None:
    release_root, script = _copy_script(tmp_path, "run_quant_frontend.sh")
    env_file = _write_frontend_env(release_root)
    build_id = release_root / "src" / "frontend" / ".next" / "BUILD_ID"
    build_id.parent.mkdir(parents=True)
    build_id.write_text("release-build\n", encoding="utf-8")

    main_root = tmp_path / "main"
    next_bin = main_root / "src" / "frontend" / "node_modules" / ".bin" / "next"
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text(
        "#!/usr/bin/env node\n"
        "throw new Error('the fake node executable must run this file');\n",
        encoding="utf-8",
    )
    next_bin.chmod(0o700)

    home = tmp_path / "home"
    node_bin = home / ".local" / "bin" / "node"
    node_bin.parent.mkdir(parents=True)
    node_bin.write_text(
        "#!/bin/sh\n"
        'test "$1" = "$QS_EXPECTED_NEXT_BIN" || exit 91\n'
        'test "$2" = "--version" || exit 92\n',
        encoding="utf-8",
    )
    node_bin.chmod(0o700)

    result = subprocess.run(
        [str(script), "--check"],
        cwd=release_root,
        env={
            "HOME": str(home),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "QS_MAIN_REPO_ROOT": str(main_root),
            "QS_AGENT_V02_FRONTEND_ENV_FILE": str(env_file),
            "QS_EXPECTED_NEXT_BIN": str(next_bin),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "frontend_ready=true" in result.stdout
    assert f"next={next_bin}" in result.stdout
    assert f"node={node_bin}" in result.stdout


def test_frontend_rejects_non_owner_only_env_before_start(
    tmp_path: Path,
) -> None:
    release_root, script = _copy_script(tmp_path, "run_quant_frontend.sh")
    env_file = _write_frontend_env(release_root, mode=0o640)

    result = subprocess.run(
        [str(script), "--check"],
        cwd=release_root,
        env={
            **os.environ,
            "QS_AGENT_V02_FRONTEND_ENV_FILE": str(env_file),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 78
    assert result.stdout == ""
    assert "frontend_config_error=frontend_env_mode_must_be_600" in result.stderr


def test_backend_start_is_release_bound_and_disables_auto_migration(
    tmp_path: Path,
) -> None:
    release_root, script = _copy_script(tmp_path, "run_quant_backend.sh")
    (release_root / "src" / "quant_system").mkdir(parents=True)

    main_root = tmp_path / "main"
    python = main_root / "ai-quant" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/usr/bin/env bash\n"
        'printf "pythonpath=%s\\n" "$PYTHONPATH"\n'
        'printf "auto_migrate=%s\\n" "$QS_DATABASE_AUTO_MIGRATE"\n'
        'printf "args=%s\\n" "$*"\n',
        encoding="utf-8",
    )
    python.chmod(0o700)

    env_file = release_root / "data" / "_runtime" / "agent-v0.2-backend.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        "QS_DATABASE_ENABLED=true\nQS_DATABASE_AUTO_MIGRATE=false\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    result = subprocess.run(
        [str(script)],
        cwd=release_root,
        env={
            **os.environ,
            "QS_MAIN_REPO_ROOT": str(main_root),
            "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    log_path = release_root / "data" / "_runtime" / "logs" / "backend-api.launchd.log"
    log = log_path.read_text(encoding="utf-8")
    assert f"pythonpath={release_root / 'src'}" in log
    assert "auto_migrate=false" in log
    assert "args=-m quant_system.cli serve --host 127.0.0.1 --port 8765" in log
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(log_path.parent.stat().st_mode) == 0o700


def test_frontend_start_serves_release_build_with_main_repo_modules(
    tmp_path: Path,
) -> None:
    release_root, script = _copy_script(tmp_path, "run_quant_frontend.sh")
    env_file = _write_frontend_env(release_root)
    frontend_dir = release_root / "src" / "frontend"
    build_id = frontend_dir / ".next" / "BUILD_ID"
    build_id.parent.mkdir(parents=True)
    build_id.write_text("release-build\n", encoding="utf-8")

    main_root = tmp_path / "main"
    main_modules = main_root / "src" / "frontend" / "node_modules"
    next_bin = main_modules / ".bin" / "next"
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text(
        "#!/usr/bin/env node\n"
        "throw new Error('the fake node executable must run this file');\n",
        encoding="utf-8",
    )
    next_bin.chmod(0o700)

    home = tmp_path / "home"
    node_bin = home / ".local" / "bin" / "node"
    node_bin.parent.mkdir(parents=True)
    node_bin.write_text(
        "#!/bin/sh\n"
        'test "$1" = "$QS_EXPECTED_NEXT_BIN" || exit 91\n'
        "shift\n"
        'printf "cwd=%s\\n" "$PWD"\n'
        'printf "node_path=%s\\n" "$NODE_PATH"\n'
        'printf "hermes_chat=%s\\n" "$QS_HERMES_CHAT_ENABLED"\n'
        'printf "args=%s\\n" "$*"\n',
        encoding="utf-8",
    )
    node_bin.chmod(0o700)

    result = subprocess.run(
        [str(script)],
        cwd=release_root,
        env={
            "HOME": str(home),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "QS_MAIN_REPO_ROOT": str(main_root),
            "QS_AGENT_V02_FRONTEND_ENV_FILE": str(env_file),
            "QS_EXPECTED_NEXT_BIN": str(next_bin),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    log_path = release_root / "data" / "_runtime" / "logs" / "frontend-next.launchd.log"
    log = log_path.read_text(encoding="utf-8")
    assert f"cwd={frontend_dir}" in log
    assert f"node_path={main_modules}" in log
    assert "hermes_chat=true" in log
    assert "args=start -H 127.0.0.1 -p 3001" in log
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(log_path.parent.stat().st_mode) == 0o700


def test_stack_installer_is_replay_safe_and_never_installs_strategy_jobs(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    scripts_dir = release_root / "scripts"
    launchd_dir = scripts_dir / "launchd"
    launchd_dir.mkdir(parents=True)
    for name in (
        "run_quant_backend.sh",
        "run_quant_frontend.sh",
        "install_agent_v02_stack_launchagents.sh",
    ):
        target = scripts_dir / name
        shutil.copy2(ROOT / "scripts" / name, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    for name in (
        "com.aiquant.backend.plist.template",
        "com.aiquant.frontend.plist.template",
    ):
        shutil.copy2(ROOT / "scripts" / "launchd" / name, launchd_dir / name)

    (release_root / "src" / "quant_system").mkdir(parents=True)
    build_id = release_root / "src" / "frontend" / ".next" / "BUILD_ID"
    build_id.parent.mkdir(parents=True)
    build_id.write_text("release-build\n", encoding="utf-8")
    env_file = release_root / "data" / "_runtime" / "agent-v0.2-backend.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("QS_DATABASE_AUTO_MIGRATE=false\n", encoding="utf-8")
    env_file.chmod(0o600)
    frontend_env_file = _write_frontend_env(release_root)

    main_root = tmp_path / "main"
    python = main_root / "ai-quant" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    python.chmod(0o700)
    next_bin = (
        main_root / "src" / "frontend" / "node_modules" / ".bin" / "next"
    )
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    next_bin.chmod(0o700)
    node_bin = _write_bash_node_shim(tmp_path)

    launchctl_log = tmp_path / "launchctl.log"
    launchctl = tmp_path / "launchctl"
    launchctl.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{launchctl_log}"\n',
        encoding="utf-8",
    )
    launchctl.chmod(0o700)
    home = tmp_path / "home"
    home.mkdir()
    run_env = {
        **os.environ,
        "HOME": str(home),
        "QS_MAIN_REPO_ROOT": str(main_root),
        "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
        "QS_AGENT_V02_FRONTEND_ENV_FILE": str(frontend_env_file),
        "QS_QUANT_FRONTEND_NODE_BIN": str(node_bin),
        "QS_LAUNCHCTL_BIN": str(launchctl),
    }

    for _ in range(2):
        result = subprocess.run(
            [str(scripts_dir / "install_agent_v02_stack_launchagents.sh")],
            cwd=release_root,
            env=run_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    installed = {
        path.name
        for path in (home / "Library" / "LaunchAgents").glob("com.aiquant*.plist")
    }
    assert installed == {
        "com.aiquant.backend.plist",
        "com.aiquant.frontend.plist",
    }
    assert "paper-sleeves" not in launchctl_log.read_text(encoding="utf-8")
    assert launchctl_log.read_text(encoding="utf-8").count("bootstrap ") == 4

    logs_dir = release_root / "data" / "_runtime" / "logs"
    assert stat.S_IMODE(logs_dir.stat().st_mode) == 0o700
    for name in (
        "backend-api.launchd.log",
        "backend-api.launchd.out.log",
        "backend-api.launchd.err.log",
        "frontend-next.launchd.log",
        "frontend-next.launchd.out.log",
        "frontend-next.launchd.err.log",
    ):
        assert stat.S_IMODE((logs_dir / name).stat().st_mode) == 0o600


def test_stack_installer_retries_transient_launchctl_bootstrap_eio(
    tmp_path: Path,
) -> None:
    release_root, installer, _, run_env = _prepare_stack_installer(tmp_path)
    launchctl, launchctl_log = _write_eio_launchctl(
        tmp_path,
        always_fail=False,
    )
    run_env["QS_LAUNCHCTL_BIN"] = str(launchctl)

    result = subprocess.run(
        [str(installer)],
        cwd=release_root,
        env=run_env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    calls = launchctl_log.read_text(encoding="utf-8")
    assert calls.count("bootout ") == 2
    assert calls.count("bootstrap ") == 4
    assert result.stderr.count("launchctl_bootstrap_eio") == 2


def test_stack_installer_exhausts_bounded_eio_retries_and_fails(
    tmp_path: Path,
) -> None:
    release_root, installer, _, run_env = _prepare_stack_installer(tmp_path)
    launchctl, launchctl_log = _write_eio_launchctl(
        tmp_path,
        always_fail=True,
    )
    run_env["QS_LAUNCHCTL_BIN"] = str(launchctl)

    result = subprocess.run(
        [str(installer)],
        cwd=release_root,
        env=run_env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    calls = launchctl_log.read_text(encoding="utf-8")
    assert calls.count("bootout ") == 1
    assert calls.count("bootstrap ") == 5
    assert "Bootstrap failed: 5: Input/output error" in result.stderr
    assert "launchctl_bootstrap_eio_exhausted" in result.stderr


def test_stack_uninstaller_removes_only_backend_and_frontend(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    scripts_dir = release_root / "scripts"
    scripts_dir.mkdir(parents=True)
    uninstaller = scripts_dir / "uninstall_agent_v02_stack_launchagents.sh"
    shutil.copy2(
        ROOT / "scripts" / "uninstall_agent_v02_stack_launchagents.sh",
        uninstaller,
    )
    uninstaller.chmod(uninstaller.stat().st_mode | stat.S_IXUSR)

    home = tmp_path / "home"
    launchagents = home / "Library" / "LaunchAgents"
    launchagents.mkdir(parents=True)
    for label in (
        "com.aiquant.backend",
        "com.aiquant.frontend",
        "com.aiquant.paper-sleeves.signals",
    ):
        (launchagents / f"{label}.plist").write_text(label, encoding="utf-8")

    launchctl_log = tmp_path / "launchctl.log"
    launchctl = tmp_path / "launchctl"
    launchctl.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{launchctl_log}"\n',
        encoding="utf-8",
    )
    launchctl.chmod(0o700)
    run_env = {
        **os.environ,
        "HOME": str(home),
        "QS_LAUNCHCTL_BIN": str(launchctl),
    }

    for _ in range(2):
        result = subprocess.run(
            [str(uninstaller)],
            cwd=release_root,
            env=run_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    assert not (launchagents / "com.aiquant.backend.plist").exists()
    assert not (launchagents / "com.aiquant.frontend.plist").exists()
    assert (launchagents / "com.aiquant.paper-sleeves.signals.plist").exists()
    launchctl_calls = launchctl_log.read_text(encoding="utf-8")
    assert "paper-sleeves" not in launchctl_calls
    assert launchctl_calls.count("bootout ") == 4
