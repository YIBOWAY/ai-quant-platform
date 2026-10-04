from __future__ import annotations

import json
import os
import plistlib
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _production_python311() -> str:
    # The runner pins python 3.11. Worktree suites may run under a different
    # interpreter, so resolve the interpreter the runner itself would use:
    # an explicit override, this tree's .venv, the main checkout's shared
    # .venv (worktrees do not carry their own), then PATH.
    candidates = []
    override = os.environ.get("QS_D34_TEST_PYTHON_311")
    if override:
        candidates.append(override)
    candidates.append(str(ROOT / ".venv" / "bin" / "python"))
    git_dir = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if git_dir.returncode == 0:
        candidates.append(str(Path(git_dir.stdout.strip()).parent / ".venv" / "bin" / "python"))
    path_python = shutil.which("python3.11")
    if path_python:
        candidates.append(path_python)
    for candidate in candidates:
        if not Path(candidate).is_file():
            continue
        probe = subprocess.run(
            [
                candidate,
                "-c",
                "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)",
            ],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if probe.returncode == 0:
            return candidate
    pytest.skip("no python 3.11 interpreter available for the --check probe")


def test_paper_cycle_runner_cds_to_release_root() -> None:
    runner = (ROOT / "scripts" / "run_d34_paper_cycle.sh").read_text(encoding="utf-8")
    assert 'cd "$ROOT"' in runner
    assert "d34 paper-cycle" in runner


def test_paper_cycle_plist_covers_signal_and_execution_windows() -> None:
    template = plistlib.loads((ROOT / "scripts" / "com.aiquant.d34-paper-cycle.plist").read_bytes())
    slots = {
        (int(item["Weekday"]), int(item["Hour"]), int(item["Minute"]))
        for item in template["StartCalendarInterval"]
    }
    signal_slots = {(weekday, 6, 15) for weekday in (2, 3, 4, 5, 6)}
    execution_slots = {(weekday, 22, 35) for weekday in (1, 2, 3, 4, 5, 6)}

    assert slots == signal_slots | execution_slots
    assert (1, 6, 15) not in slots
    assert all(weekday != 0 for weekday, _hour, _minute in slots)
    assert template.get("RunAtLoad") is not True
    assert template.get("KeepAlive") is not True
    assert template["ProgramArguments"] == [
        "/bin/bash",
        "SCRIPT_ROOT/run_d34_paper_cycle.sh",
    ]


def test_d34_research_launchagent_template_is_research_only_and_uninstalled() -> None:
    runner = (ROOT / "scripts" / "run_d34_research_worker.sh").read_text(encoding="utf-8")
    template = plistlib.loads(
        (ROOT / "scripts" / "launchd" / "com.aiquant.d34-research-worker.plist.template")
        .read_bytes()
        .replace(b"__ROOT__", str(ROOT).encode("utf-8"))
    )
    stack = (ROOT / "scripts" / "local_mac_stack.sh").read_text(encoding="utf-8")

    assert 'PYTHONPATH="$ROOT/src' in runner
    assert "QS_DATABASE_AUTO_MIGRATE=false" in runner
    assert "-m quant_system.d34.research_cli" in runner
    assert "--platform-root" in runner
    assert "--hqa-root" in runner
    assert 'case "${1:-}" in' in runner
    assert "--check" in runner
    assert "paper-cycle" not in runner
    assert "canary" not in runner
    assert "install_d34_research_worker" not in stack
    assert "install_d34_worker_launchagent.sh" not in stack
    assert template["RunAtLoad"] is True
    assert template["StartInterval"] == 300
    assert template["ProcessType"] == "Background"
    assert template["ProgramArguments"] == [
        "/bin/bash",
        str(ROOT / "scripts" / "run_d34_research_worker.sh"),
    ]
    assert "KeepAlive" not in template


def test_local_stack_does_not_install_the_research_worker() -> None:
    stack = (ROOT / "scripts" / "local_mac_stack.sh").read_text(encoding="utf-8")

    assert "install_d34_research_worker" not in stack
    assert "install_d34_worker_launchagent.sh" not in stack


def test_hermes_oauth_proxy_is_a_persistent_project_launchagent() -> None:
    runner = (ROOT / "scripts" / "run_hermes_oauth_proxy.sh").read_text(encoding="utf-8")
    template = plistlib.loads(
        (ROOT / "scripts" / "launchd" / "com.aiquant.hermes-oauth-proxy.plist.template")
        .read_bytes()
        .replace(b"__ROOT__", str(ROOT).encode("utf-8"))
    )
    stack = (ROOT / "scripts" / "local_mac_stack.sh").read_text(encoding="utf-8")

    assert "/Users/sunyibo/.local/bin/hermes" in runner
    assert "hermes proxy status" not in runner
    assert '"$HERMES_BIN" proxy status' in runner
    assert '"$HERMES_BIN" proxy start --provider xai --host 127.0.0.1 --port 8645' in runner
    assert 'case "${1:-}" in' in runner
    assert "--check" in runner
    assert template["RunAtLoad"] is True
    assert template["KeepAlive"] is True
    assert template["ProcessType"] == "Background"
    assert template["ProgramArguments"] == [
        "/bin/bash",
        str(ROOT / "scripts" / "run_hermes_oauth_proxy.sh"),
    ]
    assert 'bash "$ROOT/scripts/install_hermes_oauth_proxy_launchagent.sh"' in stack
    assert "bootout_job com.aiquant.hermes-oauth-proxy" in stack
    assert "print_job_status com.aiquant.hermes-oauth-proxy" in stack
    assert "hermes_oauth_proxy_log=" in stack
    assert "http://127.0.0.1:8645/v1/models" in stack


def test_d34_research_runner_check_imports_release_without_installing(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "backend.env"
    env_file.write_text("QS_DATABASE_AUTO_MIGRATE=false\n", encoding="utf-8")
    env_file.chmod(0o600)
    hqa_root = tmp_path / "hqa-root"
    (hqa_root / "hqa").mkdir(parents=True)

    completed = subprocess.run(
        [str(ROOT / "scripts" / "run_d34_research_worker.sh"), "--check"],
        cwd=ROOT,
        env={
            **os.environ,
            "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
            "QS_D34_HQA_ROOT": str(hqa_root),
            "QS_D34_WORKER_PYTHON": _production_python311(),
            "QS_MAIN_REPO_ROOT": str(ROOT),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "d34_research_worker_ready=true" in completed.stdout
    assert str(ROOT) in completed.stdout


def test_d34_runner_rejects_an_explicit_non_pinned_python(tmp_path: Path) -> None:
    env_file = tmp_path / "backend.env"
    env_file.write_text("QS_DATABASE_AUTO_MIGRATE=false\n", encoding="utf-8")
    env_file.chmod(0o600)
    hqa_root = tmp_path / "hqa-root"
    (hqa_root / "hqa").mkdir(parents=True)
    wrong_python = tmp_path / "python-3.12"
    wrong_python.write_text(
        '#!/bin/sh\nif [ "$1" = "-I" ]; then exit 12; fi\nexit 0\n',
        encoding="utf-8",
    )
    wrong_python.chmod(0o700)

    completed = subprocess.run(
        [str(ROOT / "scripts" / "run_d34_research_worker.sh"), "--check"],
        cwd=ROOT,
        env={
            **os.environ,
            "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
            "QS_D34_HQA_ROOT": str(hqa_root),
            "QS_D34_WORKER_PYTHON": str(wrong_python),
            "QS_MAIN_REPO_ROOT": str(ROOT),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 78
    assert completed.stdout == ""
    assert completed.stderr.strip() == ("d34_research_worker_config_error=python_must_be_3_11")


def test_d34_runner_defers_research_configuration_until_after_worker_start(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "backend.env"
    env_file.write_text("QS_DATABASE_AUTO_MIGRATE=true\n", encoding="utf-8")
    env_file.chmod(0o600)
    marker = tmp_path / "worker-argv"
    fake_python = tmp_path / "python-3.11"
    fake_python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-I" ]; then exit 0; fi\n'
        f'printf "%s\\n" "$*" > "{marker}"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o700)

    completed = subprocess.run(
        [str(ROOT / "scripts" / "run_d34_research_worker.sh")],
        cwd=ROOT,
        env={
            **os.environ,
            "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
            "QS_D34_HQA_ROOT": str(tmp_path / "missing-hqa-runtime"),
            "QS_D34_WORKER_PYTHON": str(fake_python),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.read_text(encoding="utf-8").strip().startswith(
        "-m quant_system.d34.research_cli"
    )


def test_d34_research_worker_installer_renders_retires_and_bootstraps(
    tmp_path: Path,
) -> None:
    # The owner-run installer must render the research-worker plist, boot out
    # and archive the retired com.aiquant.d34-worker label (its entrypoint
    # scripts/run_d34_worker.sh is removed by this release), and bootstrap the
    # new label. Run the real script against fake launchctl/plutil and a tmp
    # HOME and assert the consequences, not the script text.
    tmp_root = tmp_path / "repo"
    scripts_dir = tmp_root / "scripts"
    (scripts_dir / "launchd").mkdir(parents=True)
    installer = scripts_dir / "install_d34_research_worker_launchagent.sh"
    installer.write_text(
        (ROOT / "scripts" / "install_d34_research_worker_launchagent.sh").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (scripts_dir / "launchd" / "com.aiquant.d34-research-worker.plist.template").write_text(
        (
            ROOT
            / "scripts"
            / "launchd"
            / "com.aiquant.d34-research-worker.plist.template"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launchctl_log = tmp_path / "launchctl.log"
    launchctl = bin_dir / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \""
        + str(launchctl_log)
        + "\"\n"
        "if [ \"${1:-}\" = print ]; then echo 'Could not find service' >&2; exit 113; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o700)
    plutil = bin_dir / "plutil"
    plutil.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    plutil.chmod(0o700)

    home = tmp_path / "home"
    retired_dir = home / "Library" / "LaunchAgents"
    retired_dir.mkdir(parents=True)
    retired_plist = retired_dir / "com.aiquant.d34-worker.plist"
    retired_plist.write_bytes(b"retired-worker-once-plist")
    retired_factor = retired_dir / "com.aiquant.factor-automation.plist"
    retired_factor.write_bytes(b"retired-factor-automation-plist")

    env = {
        **os.environ,
        "HOME": str(home),
        "QS_LAUNCHCTL_BIN": str(launchctl),
        "QS_PLUTIL_BIN": str(plutil),
    }
    for _round in range(2):  # idempotent: second run must also succeed
        completed = subprocess.run(
            ["/bin/bash", str(installer)],
            cwd=tmp_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        assert completed.returncode == 0, completed.stderr
    assert "installed=" in completed.stdout
    assert "retired=com.aiquant.d34-worker" in completed.stdout

    rendered = retired_dir / "com.aiquant.d34-research-worker.plist"
    document = plistlib.loads(rendered.read_bytes())
    assert document["Label"] == "com.aiquant.d34-research-worker"
    assert document["ProgramArguments"] == [
        "/bin/bash",
        str(tmp_root / "scripts" / "run_d34_research_worker.sh"),
    ]

    # The retired label is gone from LaunchAgents and preserved as a receipt.
    assert not retired_plist.exists()
    assert not retired_factor.exists()
    archived = (
        tmp_root
        / "data"
        / "_runtime"
        / "launchd-retired"
        / "com.aiquant.d34-worker.plist"
    )
    assert archived.read_bytes() == b"retired-worker-once-plist"
    assert (
        tmp_root
        / "data/_runtime/launchd-retired/com.aiquant.factor-automation.plist"
    ).read_bytes() == b"retired-factor-automation-plist"

    calls = launchctl_log.read_text(encoding="utf-8").splitlines()
    domain = f"gui/{os.getuid()}"
    assert f"bootout {domain}/com.aiquant.d34-research-worker" in calls
    assert f"bootout {domain}/com.aiquant.d34-worker" in calls
    assert f"bootout {domain}/com.aiquant.factor-automation" in calls
    assert f"print {domain}/com.aiquant.d34-worker" in calls
    assert f"print {domain}/com.aiquant.factor-automation" in calls
    assert f"print {domain}/com.aiquant.d34-research-worker" in calls
    assert f"bootstrap {domain} {rendered}" in calls
    assert calls.index(f"bootstrap {domain} {rendered}") > calls.index(
        f"bootout {domain}/com.aiquant.d34-worker"
    )

    out_log = tmp_root / "data" / "_runtime" / "logs" / "d34-research-worker.launchd.out.log"
    assert out_log.exists()
    assert (out_log.stat().st_mode & 0o777) == 0o600


def test_d34_research_worker_installer_stops_on_nonbenign_bootout_failure(
    tmp_path: Path,
) -> None:
    tmp_root = tmp_path / "repo"
    scripts_dir = tmp_root / "scripts"
    (scripts_dir / "launchd").mkdir(parents=True)
    installer = scripts_dir / "install_d34_research_worker_launchagent.sh"
    installer.write_text(
        (ROOT / "scripts/install_d34_research_worker_launchagent.sh").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (scripts_dir / "launchd/com.aiquant.d34-research-worker.plist.template").write_bytes(
        (ROOT / "scripts/launchd/com.aiquant.d34-research-worker.plist.template").read_bytes()
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "launchctl.log"
    launchctl = bin_dir / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \""
        + str(calls)
        + "\"\necho 'permission denied' >&2\nexit 5\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o700)
    plutil = bin_dir / "plutil"
    plutil.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    plutil.chmod(0o700)

    completed = subprocess.run(
        ["/bin/bash", str(installer)],
        cwd=tmp_root,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "QS_LAUNCHCTL_BIN": str(launchctl),
            "QS_PLUTIL_BIN": str(plutil),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 5
    assert "launchctl_bootout_failed=com.aiquant.d34-worker" in completed.stderr
    assert "bootstrap" not in calls.read_text(encoding="utf-8")


def _paper_cycle_fixture(tmp_path: Path, python_body: str) -> tuple[Path, dict[str, str]]:
    # The runner derives ROOT from its own path, so copy it into a scratch
    # tree and point it at a fake "python" that behaves like the CLI under
    # test. No env file -> the backend-env gate stays out of the way.
    tmp_root = tmp_path / "repo"
    scripts_dir = tmp_root / "scripts"
    scripts_dir.mkdir(parents=True)
    runner = scripts_dir / "run_d34_paper_cycle.sh"
    runner.write_text(
        (ROOT / "scripts" / "run_d34_paper_cycle.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    fake_python = tmp_path / "fake-python"
    fake_python.write_text("#!/bin/sh\n" + python_body, encoding="utf-8")
    fake_python.chmod(0o700)
    env = {
        **os.environ,
        "QS_D34_WORKER_PYTHON": str(fake_python),
        "QS_AGENT_V02_BACKEND_ENV_FILE": str(tmp_path / "absent.env"),
    }
    return runner, env


def _failure_receipt(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines, "runner produced no stdout receipt at all"
    receipt = json.loads(lines[-1])
    assert receipt["contract"] == "hqa.d34_paper_cycle_failure/v1"
    return receipt


def test_paper_cycle_runner_emits_a_receipt_when_the_cycle_crashes(
    tmp_path: Path,
) -> None:
    # Regression for 2026-08-20: a DatabaseUnavailable crash left no receipt
    # in the launchd log. The wrapper must pass the traceback through AND end
    # with a failure receipt carrying the original exit code.
    runner, env = _paper_cycle_fixture(
        tmp_path,
        'echo "Traceback (most recent call last):" >&2\n'
        'echo "quant_system.DatabaseUnavailable: connection refused" >&2\n'
        "exit 3\n",
    )
    completed = subprocess.run(
        ["/bin/bash", str(runner)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert completed.returncode == 3
    assert "DatabaseUnavailable: connection refused" in completed.stdout
    receipt = _failure_receipt(completed)
    assert receipt["outcome"] == "crash"
    assert receipt["exit_code"] == 3
    assert "DatabaseUnavailable: connection refused" in receipt["detail"]
    for key in ("started_at", "finished_at"):
        time.strptime(str(receipt[key]), "%Y-%m-%dT%H:%M:%SZ")


def test_paper_cycle_runner_emits_a_receipt_on_config_error(tmp_path: Path) -> None:
    tmp_root = tmp_path / "repo"
    scripts_dir = tmp_root / "scripts"
    scripts_dir.mkdir(parents=True)
    runner = scripts_dir / "run_d34_paper_cycle.sh"
    runner.write_text(
        (ROOT / "scripts" / "run_d34_paper_cycle.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    env_file = tmp_path / "backend.env"
    env_file.write_text("QS_DATABASE_AUTO_MIGRATE=false\n", encoding="utf-8")
    env_file.chmod(0o644)  # wrong mode: the runner must refuse

    completed = subprocess.run(
        ["/bin/bash", str(runner)],
        env={
            **os.environ,
            "QS_AGENT_V02_BACKEND_ENV_FILE": str(env_file),
            "QS_D34_WORKER_PYTHON": str(tmp_path / "never-used"),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert completed.returncode == 78
    assert "d34_paper_cycle_config_error=backend_env_mode_must_be_600" in completed.stderr
    receipt = _failure_receipt(completed)
    assert receipt["outcome"] == "config_error"
    assert receipt["exit_code"] == 78
    assert receipt["detail"] == "backend_env_mode_must_be_600"


def test_paper_cycle_runner_emits_a_receipt_on_sigterm(tmp_path: Path) -> None:
    marker = tmp_path / "python-started"
    runner, env = _paper_cycle_fixture(
        tmp_path,
        f'touch "{marker}"\nexec sleep 30\n',
    )
    process = subprocess.Popen(
        ["/bin/bash", str(runner)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 10
    while not marker.exists():
        assert time.monotonic() < deadline, "fake python never started"
        assert process.poll() is None
        time.sleep(0.05)
    process.send_signal(signal.SIGTERM)
    stdout, _stderr = process.communicate(timeout=10)

    assert process.returncode == 143
    lines = [line for line in stdout.splitlines() if line.strip()]
    receipt = json.loads(lines[-1])
    assert receipt["contract"] == "hqa.d34_paper_cycle_failure/v1"
    assert receipt["outcome"] == "signal"
    assert receipt["exit_code"] == 143
    assert receipt["detail"] == "SIGTERM"


def test_paper_cycle_runner_passes_through_a_clean_success(tmp_path: Path) -> None:
    runner, env = _paper_cycle_fixture(
        tmp_path,
        'echo "{\\"contract\\":\\"hqa.d34_paper_cycle/v1\\",\\"status\\":\\"ok\\"}"\nexit 0\n',
    )
    completed = subprocess.run(
        ["/bin/bash", str(runner)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert completed.returncode == 0
    receipt = json.loads(completed.stdout.strip())
    assert receipt["contract"] == "hqa.d34_paper_cycle/v1"
    assert receipt["status"] == "ok"
