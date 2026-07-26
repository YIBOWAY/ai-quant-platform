from __future__ import annotations

import os
import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _copy_connector_assets(tmp_path: Path) -> tuple[Path, Path, Path]:
    release_root = tmp_path / "release"
    scripts_dir = release_root / "scripts"
    launchd_dir = scripts_dir / "launchd"
    launchd_dir.mkdir(parents=True)
    for name in (
        "run_agent_v02_connector.sh",
        "install_agent_v02_connector_launchagent.sh",
    ):
        target = scripts_dir / name
        shutil.copy2(ROOT / "scripts" / name, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    shutil.copy2(
        ROOT
        / "scripts"
        / "launchd"
        / "com.aiquant.agent-v02-connector.plist.template",
        launchd_dir / "com.aiquant.agent-v02-connector.plist.template",
    )
    (release_root / "src" / "quant_system").mkdir(parents=True)
    return (
        release_root,
        scripts_dir / "run_agent_v02_connector.sh",
        scripts_dir / "install_agent_v02_connector_launchagent.sh",
    )


def _write_connector_env(
    release_root: Path,
    *,
    contents: str = "QS_DATABASE_AUTO_MIGRATE=false\n",
    mode: int = 0o600,
) -> Path:
    env_file = release_root / "data" / "_runtime" / "agent-v0.2-connector.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(contents, encoding="utf-8")
    env_file.chmod(mode)
    return env_file


def _write_fake_python(path: Path, capture: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        "{\n"
        '  printf "args=%s\\n" "$*"\n'
        '  printf "pythonpath=%s\\n" "${PYTHONPATH:-}"\n'
        '  printf "auto_migrate=%s\\n" "${QS_DATABASE_AUTO_MIGRATE:-}"\n'
        '  printf "database_url=%s\\n" "${QS_DATABASE_URL:-}"\n'
        f"}} >> {capture!s}\n"
        'if [[ "${1:-}" == "-" ]]; then\n'
        "  cat >/dev/null\n"
        "fi\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _write_eio_launchctl(
    tmp_path: Path,
    *,
    always_fail: bool,
) -> tuple[Path, Path]:
    launchctl_log = tmp_path / "launchctl.log"
    state_file = tmp_path / "launchctl-bootstrap.count"
    launchctl = tmp_path / "launchctl"
    failure_condition = "true" if always_fail else '[[ "$attempt" -eq 1 ]]'
    launchctl.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{launchctl_log}"\n'
        '[[ "${1:-}" == "bootstrap" ]] || exit 0\n'
        "attempt=0\n"
        f'[[ ! -f "{state_file}" ]] || attempt="$(cat "{state_file}")"\n'
        "attempt=$((attempt + 1))\n"
        f'printf "%s\\n" "$attempt" > "{state_file}"\n'
        f"if {failure_condition}; then\n"
        '  echo "Bootstrap failed: 5: Input/output error" >&2\n'
        "  exit 5\n"
        "fi\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o700)
    return launchctl, launchctl_log


def test_launchagent_is_supervised_without_fixed_smoke_input() -> None:
    wrapper = (ROOT / "scripts" / "run_agent_v02_connector.sh").read_text(
        encoding="utf-8"
    )
    template = plistlib.loads(
        (ROOT / "scripts" / "launchd" / "com.aiquant.agent-v02-connector.plist.template")
        .read_bytes()
        .replace(b"__ROOT__", str(ROOT).encode("utf-8"))
    )

    assert "--mode supervised_dispatch" in wrapper
    assert "--poll-interval-seconds" in wrapper
    assert "--fixed-input" not in wrapper
    assert 'PYTHONPATH="$ROOT/src' in wrapper
    assert template["RunAtLoad"] is True
    assert template["KeepAlive"] is True
    assert template["ProgramArguments"] == [
        str(ROOT / "scripts" / "run_agent_v02_connector.sh")
    ]


def test_check_imports_exact_release_without_contacting_configured_services(
    tmp_path: Path,
) -> None:
    secret = "postgres-secret-must-not-be-logged"
    env_file = tmp_path / "connector.env"
    env_file.write_text(
        "QS_DATABASE_AUTO_MIGRATE=false\n"
        f"QS_DATABASE_URL=postgresql://runtime:{secret}@127.0.0.1:1/never-contact\n"
        "QS_HERMES_GATEWAY_BASE_URL=http://127.0.0.1:1/never-contact\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    result = subprocess.run(
        [str(ROOT / "scripts" / "run_agent_v02_connector.sh"), "--check"],
        cwd=ROOT,
        env={
            **os.environ,
            "QS_AGENT_V02_CONNECTOR_ENV_FILE": str(env_file),
            "QS_AGENT_V02_CONNECTOR_PYTHON": sys.executable,
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "connector_ready=true" in result.stdout
    assert f"release_root={ROOT}" in result.stdout
    assert f"python={sys.executable}" in result.stdout
    assert secret not in result.stdout
    assert secret not in result.stderr


@pytest.mark.parametrize(
    ("setup", "error_code"),
    (
        ("missing", "connector_env_missing"),
        ("directory", "connector_env_not_regular"),
        ("symlink", "connector_env_not_regular"),
        ("mode", "connector_env_mode_must_be_600"),
    ),
)
def test_check_requires_regular_non_symlink_exact_mode_600_env(
    tmp_path: Path,
    setup: str,
    error_code: str,
) -> None:
    release_root, wrapper, _ = _copy_connector_assets(tmp_path)
    env_file = release_root / "connector.env"
    if setup == "directory":
        env_file.mkdir()
    elif setup == "symlink":
        target = release_root / "real.env"
        target.write_text("QS_DATABASE_AUTO_MIGRATE=false\n", encoding="utf-8")
        target.chmod(0o600)
        env_file.symlink_to(target)
    elif setup == "mode":
        env_file.write_text("QS_DATABASE_AUTO_MIGRATE=false\n", encoding="utf-8")
        env_file.chmod(0o640)

    result = subprocess.run(
        [str(wrapper), "--check"],
        cwd=release_root,
        env={
            **os.environ,
            "QS_AGENT_V02_CONNECTOR_ENV_FILE": str(env_file),
            "QS_AGENT_V02_CONNECTOR_PYTHON": sys.executable,
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 78
    assert result.stdout == ""
    assert f"connector_config_error={error_code}" in result.stderr


def test_check_rejects_startup_auto_migration_before_python(
    tmp_path: Path,
) -> None:
    release_root, wrapper, _ = _copy_connector_assets(tmp_path)
    env_file = _write_connector_env(
        release_root,
        contents="QS_DATABASE_AUTO_MIGRATE=true\n",
    )
    capture = tmp_path / "python.log"
    python = _write_fake_python(tmp_path / "python", capture)

    result = subprocess.run(
        [str(wrapper), "--check"],
        cwd=release_root,
        env={
            **os.environ,
            "QS_AGENT_V02_CONNECTOR_ENV_FILE": str(env_file),
            "QS_AGENT_V02_CONNECTOR_PYTHON": str(python),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 78
    assert "connector_config_error=database_auto_migrate_forbidden" in result.stderr
    assert not capture.exists()


def test_start_preserves_keychain_command_dotenv_and_uses_exact_supervised_args(
    tmp_path: Path,
) -> None:
    release_root, wrapper, _ = _copy_connector_assets(tmp_path)
    capture = tmp_path / "python.log"
    python = _write_fake_python(tmp_path / "python", capture)
    secret = "keychain-only-secret"
    keychain = tmp_path / "keychain"
    keychain.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' '{secret}'\n",
        encoding="utf-8",
    )
    keychain.chmod(0o700)
    env_file = _write_connector_env(
        release_root,
        contents=(
            'QS_DATABASE_URL="postgresql://runtime:'
            '$("$TEST_KEYCHAIN_BIN" password)'
            '@127.0.0.1:5432/quantplatform"\n'
            "QS_DATABASE_AUTO_MIGRATE=false\n"
            "QS_AGENT_V02_CONNECTOR_POLL_INTERVAL_SECONDS=7.5\n"
            "QS_AGENT_V02_CONNECTOR_WORKER_ID=release-connector\n"
        ),
    )

    result = subprocess.run(
        [str(wrapper)],
        cwd=release_root,
        env={
            **os.environ,
            "TEST_KEYCHAIN_BIN": str(keychain),
            "QS_AGENT_V02_CONNECTOR_ENV_FILE": str(env_file),
            "QS_AGENT_V02_CONNECTOR_PYTHON": str(python),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    output = capture.read_text(encoding="utf-8")
    assert (
        f"args=- {release_root / 'src'} 7.5 release-connector"
        in output
    )
    assert (
        "args=-m quant_system.cli hermes connector-worker "
        "--mode supervised_dispatch --poll-interval-seconds 7.5 "
        "--reconcile-limit 100 --worker-id release-connector"
    ) in output
    assert f"pythonpath={release_root / 'src'}" in output
    assert "auto_migrate=false" in output
    assert f"database_url=postgresql://runtime:{secret}@127.0.0.1:5432/quantplatform" in output
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_installer_checks_before_launchd_mutation_and_is_replay_safe(
    tmp_path: Path,
) -> None:
    release_root, _, installer = _copy_connector_assets(tmp_path)
    env_file = _write_connector_env(
        release_root,
        contents="QS_DATABASE_AUTO_MIGRATE=true\n",
    )
    python = _write_fake_python(tmp_path / "python", tmp_path / "python.log")
    launchctl_log = tmp_path / "launchctl.log"
    launchctl = tmp_path / "launchctl"
    launchctl.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{launchctl_log}"\n',
        encoding="utf-8",
    )
    launchctl.chmod(0o700)
    plutil = tmp_path / "plutil"
    plutil.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    plutil.chmod(0o700)
    home = tmp_path / "home"
    home.mkdir()
    run_env = {
        **os.environ,
        "HOME": str(home),
        "QS_AGENT_V02_CONNECTOR_ENV_FILE": str(env_file),
        "QS_AGENT_V02_CONNECTOR_PYTHON": str(python),
        "QS_LAUNCHCTL_BIN": str(launchctl),
        "QS_PLUTIL_BIN": str(plutil),
    }

    failed = subprocess.run(
        [str(installer)],
        cwd=release_root,
        env=run_env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert failed.returncode == 78
    assert "database_auto_migrate_forbidden" in failed.stderr
    assert not launchctl_log.exists()
    assert not (home / "Library" / "LaunchAgents").exists()

    env_file.write_text("QS_DATABASE_AUTO_MIGRATE=false\n", encoding="utf-8")
    env_file.chmod(0o600)
    for _ in range(2):
        result = subprocess.run(
            [str(installer)],
            cwd=release_root,
            env=run_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    launchctl_calls = launchctl_log.read_text(encoding="utf-8")
    assert launchctl_calls.count("bootstrap ") == 2
    assert launchctl_calls.count("bootout ") == 2
    target = (
        home
        / "Library"
        / "LaunchAgents"
        / "com.aiquant.agent-v02-connector.plist"
    )
    assert target.is_file()
    assert not target.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600

    logs_dir = release_root / "data" / "_runtime" / "logs"
    assert stat.S_IMODE(logs_dir.stat().st_mode) == 0o700
    for name in (
        "agent-v02-connector.launchd.out.log",
        "agent-v02-connector.launchd.err.log",
    ):
        log = logs_dir / name
        assert log.is_file()
        assert not log.is_symlink()
        assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_connector_installer_retries_transient_launchctl_bootstrap_eio(
    tmp_path: Path,
) -> None:
    release_root, _, installer = _copy_connector_assets(tmp_path)
    env_file = _write_connector_env(release_root)
    python = _write_fake_python(tmp_path / "python", tmp_path / "python.log")
    launchctl, launchctl_log = _write_eio_launchctl(
        tmp_path,
        always_fail=False,
    )
    plutil = tmp_path / "plutil"
    plutil.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    plutil.chmod(0o700)
    home = tmp_path / "home"
    home.mkdir()

    result = subprocess.run(
        [str(installer)],
        cwd=release_root,
        env={
            **os.environ,
            "HOME": str(home),
            "QS_AGENT_V02_CONNECTOR_ENV_FILE": str(env_file),
            "QS_AGENT_V02_CONNECTOR_PYTHON": str(python),
            "QS_LAUNCHCTL_BIN": str(launchctl),
            "QS_PLUTIL_BIN": str(plutil),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    calls = launchctl_log.read_text(encoding="utf-8")
    assert calls.count("bootout ") == 1
    assert calls.count("bootstrap ") == 2
    assert result.stderr.count("launchctl_bootstrap_eio") == 1


def test_connector_installer_exhausts_bounded_eio_retries_and_fails(
    tmp_path: Path,
) -> None:
    release_root, _, installer = _copy_connector_assets(tmp_path)
    env_file = _write_connector_env(release_root)
    python = _write_fake_python(tmp_path / "python", tmp_path / "python.log")
    launchctl, launchctl_log = _write_eio_launchctl(
        tmp_path,
        always_fail=True,
    )
    plutil = tmp_path / "plutil"
    plutil.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    plutil.chmod(0o700)
    home = tmp_path / "home"
    home.mkdir()

    result = subprocess.run(
        [str(installer)],
        cwd=release_root,
        env={
            **os.environ,
            "HOME": str(home),
            "QS_AGENT_V02_CONNECTOR_ENV_FILE": str(env_file),
            "QS_AGENT_V02_CONNECTOR_PYTHON": str(python),
            "QS_LAUNCHCTL_BIN": str(launchctl),
            "QS_PLUTIL_BIN": str(plutil),
        },
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
