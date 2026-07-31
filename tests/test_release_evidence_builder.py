from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from quant_system.config.settings import Settings
from quant_system.hermes import release_evidence_builder
from quant_system.hermes.candidate_evidence import (
    candidate_preflight_evidence_observation,
)
from quant_system.hermes.release_evidence_builder import (
    EvidenceBuildConflict,
    EvidenceBuildError,
    build_candidate_preflight,
    build_release_evidence,
    run_test_suite,
)
from quant_system.hermes.release_runtime import (
    ReleaseRuntimeProbeError,
    release_evidence_observation,
)
from quant_system.hermes.test_execution_evidence import (
    TestExecutionEvidenceError as ExecutionEvidenceError,
)
from quant_system.hermes.test_execution_evidence import (
    parse_junit_counts,
    validate_argv,
    validate_test_execution_receipt,
)


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _runtime_digest(name: str, commit: str) -> str:
    payload = b"agent-v0.2-runtime\x00" + name.encode("ascii")
    payload += b"\x00commit\x00" + commit.encode("ascii") + b"\x00"
    return hashlib.sha256(payload).hexdigest()


def _run(*argv: str, cwd: Path) -> str:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_repo(path: Path, *, seed: str) -> tuple[Path, str]:
    path.mkdir()
    _run("git", "init", "-q", cwd=path)
    _run("git", "config", "user.name", "Evidence Test", cwd=path)
    _run("git", "config", "user.email", "evidence@example.invalid", cwd=path)
    (path / "tracked.txt").write_text(seed, encoding="utf-8")
    (path / ".gitignore").write_text(
        ".pytest_cache/\n__pycache__/\nsrc/frontend/node_modules/\n",
        encoding="utf-8",
    )
    tests_dir = path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_release_receipt.py").write_text(
        "import os\n\n"
        "def test_release_receipt():\n"
        "    assert 'PYTHONPATH' not in os.environ\n"
        "    assert 'PYTEST_ADDOPTS' not in os.environ\n"
        "    assert 'PYTEST_PLUGINS' not in os.environ\n"
        "    assert 'PYTHONSTARTUP' not in os.environ\n"
        "    assert 'COVERAGE_PROCESS_START' not in os.environ\n"
        "    assert 'OPENAI_API_KEY' not in os.environ\n"
        "    assert 'QS_DATABASE_URL' not in os.environ\n"
        "    assert os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'\n",
        encoding="utf-8",
    )
    if seed == "hermes":
        plugin = path / "pytest_asyncio"
        plugin.mkdir()
        (plugin / "__init__.py").write_text("", encoding="utf-8")
        (plugin / "plugin.py").write_text("", encoding="utf-8")
        for relative, marker in (
            ("tests/gateway/test_api_server.py", "api_server"),
            (
                "tests/gateway/test_api_server_managed_runs.py",
                "managed_runs",
            ),
            ("tests/tools/test_local_env_session_leak.py", "local_env"),
        ):
            target = path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f"def test_{marker}():\n    assert True\n",
                encoding="utf-8",
            )
    if seed == "platform":
        frontend = path / "src" / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text(
            '{"scripts":{"test":"vitest run"},"type":"module"}\n',
            encoding="utf-8",
        )
        (frontend / "release-receipt.test.js").write_text(
            "import { expect, test } from 'vitest';\n"
            "test('release receipt', () => {\n"
            "  expect(process.env.PYTHONPATH).toBeUndefined();\n"
            "  expect(process.env.PYTEST_ADDOPTS).toBeUndefined();\n"
            "  expect(process.env.PYTEST_PLUGINS).toBeUndefined();\n"
            "  expect(process.env.PYTEST_DISABLE_PLUGIN_AUTOLOAD).toBe('1');\n"
            "});\n",
            encoding="utf-8",
        )
        frontend_modules = Path(__file__).resolve().parents[1] / "src/frontend/node_modules"
        assert frontend_modules.is_dir()
        (frontend / "node_modules").symlink_to(
            frontend_modules,
            target_is_directory=True,
        )
    _run("git", "add", ".", cwd=path)
    _run("git", "commit", "-q", "-m", "fixture", cwd=path)
    return path, _run("git", "rev-parse", "HEAD", cwd=path)


def _runtime_roots(tmp_path: Path) -> tuple[dict[str, Path], dict[str, dict[str, str]]]:
    roots: dict[str, Path] = {}
    runtime: dict[str, dict[str, str]] = {}
    for name in ("platform", "hqa", "hermes"):
        root, commit = _git_repo(tmp_path / f"{name}-repo", seed=name)
        roots[name] = root
        runtime[name] = {
            "commit": commit,
            "digest": _runtime_digest(name, commit),
        }
    return roots, runtime


def _node_executable() -> Path:
    configured = os.environ.get("QS_QUANT_FRONTEND_NODE_BIN")
    observed = configured or shutil.which("node")
    assert observed is not None
    node = Path(observed).expanduser().resolve()
    assert node.is_file()
    return node


def _test_receipts(
    tmp_path: Path,
    roots: dict[str, Path],
    *,
    reuse: bool = True,
) -> tuple[Path, ...]:
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    names = ("platform", "hqa", "hermes_focused", "frontend")
    if reuse:
        existing: list[Path] = []
        for name in names:
            matches = list(output_dir.glob(f"test-{name.replace('_', '-')}-receipt-*.json"))
            if len(matches) != 1:
                break
            existing.append(matches[0])
        if len(existing) == len(names):
            return tuple(existing)
    paths: list[Path] = []
    for name in names:
        if name == "frontend":
            cwd = roots["platform"] / "src/frontend"
            argv = (
                str(_node_executable()),
                str(cwd / "node_modules" / "vitest" / "vitest.mjs"),
                "run",
                "--reporter=junit",
                "--outputFile={junit}",
            )
        else:
            selectors = (
                (
                    "tests/gateway/test_api_server.py",
                    "tests/gateway/test_api_server_managed_runs.py",
                    "tests/tools/test_local_env_session_leak.py",
                )
                if name == "hermes_focused"
                else ("tests",)
            )
            argv = (
                sys.executable,
                "-m",
                "pytest",
                *(("-p", "pytest_asyncio.plugin") if name == "hermes_focused" else ()),
                *selectors,
                "--junitxml={junit}",
            )
            cwd = roots[
                {
                    "platform": "platform",
                    "hqa": "hqa",
                    "hermes_focused": "hermes",
                }[name]
            ]
        result = run_test_suite(
            name=name,
            argv=argv,
            output_dir=output_dir,
            runtime_roots=roots,
            cwd=cwd,
        )
        paths.append(result.receipt_path)
    return tuple(paths)


def test_run_suite_executes_without_shell_and_seals_recomputable_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)
    monkeypatch.setenv("PYTHONPATH", "/tmp/untrusted-shadow")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k no_tests")
    monkeypatch.setenv("PYTEST_PLUGINS", "untrusted_plugin")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "0")
    monkeypatch.setenv("PYTHONSTARTUP", "/tmp/untrusted-startup.py")
    monkeypatch.setenv("COVERAGE_PROCESS_START", "/tmp/untrusted-coverage.ini")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-tests")
    monkeypatch.setenv("QS_DATABASE_URL", "must-not-reach-tests")
    result = run_test_suite(
        name="platform",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "--junitxml={junit}",
        ),
        output_dir=output_dir,
        runtime_roots=roots,
        cwd=roots["platform"],
    )

    assert result.name == "platform"
    assert result.passed == 1
    assert result.failed == 0
    assert result.skipped == 0
    assert result.runtime == runtime
    assert result.receipt_path.name.startswith("test-platform-receipt-")
    receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert receipt["argv"][0] == sys.executable
    assert all("{junit}" not in argument for argument in receipt["argv"])
    assert result.output_sha256 in result.output_path.name
    assert result.junit_sha256 in result.junit_path.name
    assert result.receipt_sha256 in result.receipt_path.name
    assert {stat.S_IMODE(path.stat().st_mode) for path in output_dir.iterdir()} == {0o600}


@pytest.mark.parametrize("runner_name", ["uv", "node"])
def test_sealed_absolute_runner_receipt_validates_without_runner_on_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_name: str,
) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)
    runner_path = tmp_path / "approved-bin" / runner_name
    runner_path.parent.mkdir()
    runner_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runner_path.chmod(0o700)
    runner = str(runner_path)
    monkeypatch.setenv(
        "PATH",
        f"{runner_path.parent}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    if runner_name == "uv":
        name = "platform"
        cwd = roots["platform"]
        argv = (
            runner,
            "run",
            "--frozen",
            "--extra",
            "dev",
            "pytest",
            "tests",
            "--junitxml={junit}",
        )
        junit_prefix = "--junitxml="
    else:
        name = "frontend"
        cwd = roots["platform"] / "src/frontend"
        argv = (
            runner,
            str(cwd / "node_modules" / "vitest" / "vitest.mjs"),
            "run",
            "--reporter=junit",
            "--outputFile={junit}",
        )
        junit_prefix = "--outputFile="

    def execute_with_passing_junit(
        executed_argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: int,
    ) -> tuple[int, bytes]:
        del cwd, env, timeout_seconds
        target = Path(
            next(
                argument.split("=", 1)[1]
                for argument in executed_argv
                if argument.startswith(junit_prefix)
            )
        )
        target.write_bytes(
            b'<testsuite tests="1" failures="0" errors="0" skipped="0">'
            b'<testcase name="release"/></testsuite>'
        )
        target.chmod(0o600)
        return 0, b"passed\n"

    monkeypatch.setattr(
        release_evidence_builder,
        "_execute_bounded",
        execute_with_passing_junit,
    )
    result = run_test_suite(
        name=name,
        argv=argv,
        output_dir=output_dir,
        runtime_roots=roots,
        cwd=cwd,
    )

    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    validated = validate_test_execution_receipt(
        result.receipt_path,
        expected_name=name,
        expected_runtime=runtime,
        expected_runtime_roots=roots,
    )

    assert validated.executable_path == Path(runner).resolve()
    assert validated.argv[0] == runner


def test_sanitized_environment_binds_managed_python_outside_private_home(
    tmp_path: Path,
) -> None:
    scratch = tmp_path / "evidence"
    scratch.mkdir()
    managed_root = tmp_path / "operator" / ".local" / "share" / "uv" / "python"
    interpreter = managed_root / "cpython-3.11-test" / "bin" / "python3.11"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("#!/bin/sh\nprintf managed-python-ok\n", encoding="utf-8")
    interpreter.chmod(0o700)
    runtime = tmp_path / "runtime"
    venv_python = runtime / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(interpreter)
    poisoned_git = venv_python.parent / "git"
    poisoned_git.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    poisoned_git.chmod(0o700)

    env = release_evidence_builder._sanitized_test_environment(
        scratch,
        executable=venv_python,
        working_directory=runtime,
    )

    assert env["HOME"] == str(scratch)
    assert env["HQA_UV_MANAGED_PYTHON_ROOT"] == str(managed_root)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTHONINTMAXSTRDIGITS"] == "0"
    assert env["UV_PYTHON_DOWNLOADS"] == "never"
    assert str(venv_python.parent) not in env["PATH"].split(os.pathsep)
    assert str(interpreter.parent) in env["PATH"].split(os.pathsep)
    completed = subprocess.run(
        ("/usr/bin/env", "python3.11"),
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )
    assert completed.stdout == "managed-python-ok"


def test_frontend_release_suite_never_executes_node_from_ambient_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)
    attacker_bin = tmp_path / "attacker-bin"
    attacker_bin.mkdir()
    attacker_marker = tmp_path / "attacker-node-executed"
    attacker_node = attacker_bin / "node"
    attacker_node.write_text(
        "#!/bin/sh\n"
        f"printf attacked > {str(attacker_marker)!r}\n"
        'for argument in "$@"; do\n'
        '  case "$argument" in\n'
        "    --outputFile=*)\n"
        '      target=${argument#--outputFile=}\n'
        "      printf '%s' '<testsuite tests=\"1\" failures=\"0\" "
        "errors=\"0\" skipped=\"0\"><testcase name=\"attacker\"/></testsuite>' "
        '> "$target"\n'
        "      chmod 600 \"$target\"\n"
        "      ;;\n"
        "  esac\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    attacker_node.chmod(0o700)
    monkeypatch.setenv(
        "PATH",
        f"{attacker_bin}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    frontend = roots["platform"] / "src/frontend"

    with pytest.raises(
        EvidenceBuildError,
        match="Node|node|Vitest|approved suite runner|exit code",
    ):
        run_test_suite(
            name="frontend",
            argv=(
                str(frontend / "node_modules" / ".bin" / "vitest"),
                "run",
                "--reporter=junit",
                "--outputFile={junit}",
            ),
            output_dir=output_dir,
            runtime_roots=roots,
            cwd=frontend,
        )

    assert not attacker_marker.exists()
    assert not list(output_dir.iterdir())


def test_frontend_release_suite_seals_absolute_node_and_vitest_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)
    node_root = tmp_path / "trusted-node"
    node_root.mkdir(mode=0o700)
    node_bin = node_root / "bin"
    node_bin.mkdir(mode=0o700)
    node = node_bin / "node"
    node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    node.chmod(0o700)
    frontend = roots["platform"] / "src/frontend"
    vitest_entry = frontend / "node_modules" / "vitest" / "vitest.mjs"
    captured_argv: tuple[str, ...] | None = None

    def execute_with_passing_junit(
        executed_argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: int,
    ) -> tuple[int, bytes]:
        nonlocal captured_argv
        del cwd, env, timeout_seconds
        captured_argv = executed_argv
        target = Path(
            next(
                argument.split("=", 1)[1]
                for argument in executed_argv
                if argument.startswith("--outputFile=")
            )
        )
        target.write_bytes(
            b'<testsuite tests="1" failures="0" errors="0" skipped="0">'
            b'<testcase name="release"/></testsuite>'
        )
        target.chmod(0o600)
        return 0, b"passed\n"

    monkeypatch.setattr(
        release_evidence_builder,
        "_execute_bounded",
        execute_with_passing_junit,
    )
    result = run_test_suite(
        name="frontend",
        argv=(
            str(node),
            str(vitest_entry),
            "run",
            "--reporter=junit",
            "--outputFile={junit}",
        ),
        output_dir=output_dir,
        runtime_roots=roots,
        cwd=frontend,
    )

    receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    node_realpath = node.resolve()
    entry_realpath = vitest_entry.resolve()
    assert captured_argv is not None
    assert captured_argv[:3] == (str(node), str(vitest_entry), "run")
    assert receipt["contract"] == "agent-v0.2-test-execution-receipt/v2"
    assert receipt["runner_kind"] == "node_vitest"
    assert receipt["argv"][:3] == [str(node), str(vitest_entry), "run"]
    assert receipt["executable"] == {
        "mode": "0700",
        "nlink": 1,
        "realpath": str(node_realpath),
        "relative": "bin/node",
        "root": {
            "mode": "0700",
            "realpath": str(node_root.resolve()),
            "uid": os.geteuid(),
        },
        "sha256": hashlib.sha256(node.read_bytes()).hexdigest(),
        "uid": os.geteuid(),
    }
    assert receipt["suite_entry"] == {
        "mode": f"{stat.S_IMODE(entry_realpath.stat().st_mode):04o}",
        "nlink": 1,
        "realpath": str(entry_realpath),
        "relative": "vitest.mjs",
        "root": {
            "mode": (
                f"{stat.S_IMODE(entry_realpath.parent.stat().st_mode):04o}"
            ),
            "realpath": str(entry_realpath.parent),
            "uid": entry_realpath.parent.stat().st_uid,
        },
        "sha256": hashlib.sha256(entry_realpath.read_bytes()).hexdigest(),
        "uid": entry_realpath.stat().st_uid,
    }
    validated = validate_test_execution_receipt(
        result.receipt_path,
        expected_name="frontend",
        expected_runtime=runtime,
        expected_runtime_roots=roots,
    )
    assert validated.runner_kind == "node_vitest"
    assert validated.executable_path == node_realpath
    assert validated.suite_entry_path == entry_realpath
    assert validated.suite_entry_sha256 == receipt["suite_entry"]["sha256"]


def test_run_suite_seals_large_but_bounded_full_suite_junit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)
    junit = (
        b'<testsuite tests="1" failures="0" errors="0" skipped="0">'
        b'<testcase name="'
        + (b"x" * (4 * 1024 * 1024))
        + b'"/></testsuite>'
    )
    assert 4 * 1024 * 1024 < len(junit) < 8 * 1024 * 1024

    def execute_with_large_junit(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: int,
    ) -> tuple[int, bytes]:
        del cwd, env, timeout_seconds
        target = Path(
            next(
                arg.split("=", 1)[1]
                for arg in argv
                if arg.startswith("--junitxml=")
            )
        )
        target.write_bytes(junit)
        target.chmod(0o600)
        return 0, b""

    monkeypatch.setattr(
        release_evidence_builder,
        "_execute_bounded",
        execute_with_large_junit,
    )
    result = run_test_suite(
        name="platform",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "--junitxml={junit}",
        ),
        output_dir=output_dir,
        runtime_roots=roots,
        cwd=roots["platform"],
    )

    assert result.passed == 1
    assert result.failed == 0
    assert result.junit_path.stat().st_size == len(junit)
    assert stat.S_IMODE(result.junit_path.stat().st_mode) == 0o600


def test_run_suite_rejects_unapproved_executable_or_suite_cwd(
    tmp_path: Path,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)
    fake_runner = tmp_path / "fake-runner"
    fake_runner.write_text(
        "#!/bin/sh\nexit 0\n",
        encoding="utf-8",
    )
    fake_runner.chmod(0o700)
    spoofed_pytest = tmp_path / "untrusted" / ".venv" / "bin" / "pytest"
    spoofed_pytest.parent.mkdir(parents=True)
    spoofed_pytest.write_text(
        "#!/bin/sh\nexit 0\n",
        encoding="utf-8",
    )
    spoofed_pytest.chmod(0o700)

    for executable in (fake_runner, spoofed_pytest):
        with pytest.raises(EvidenceBuildError, match="approved suite runner"):
            run_test_suite(
                name="platform",
                argv=(str(executable), "--junitxml={junit}"),
                output_dir=output_dir,
                runtime_roots=roots,
                cwd=roots["platform"],
            )
    with pytest.raises(EvidenceBuildError, match="cwd"):
        run_test_suite(
            name="platform",
            argv=(
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "--junitxml={junit}",
            ),
            output_dir=output_dir,
            runtime_roots=roots,
            cwd=roots["hqa"],
        )
    with pytest.raises(
        EvidenceBuildError,
        match="approved suite runner|absolute Vitest entry",
    ):
        run_test_suite(
            name="frontend",
            argv=(
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "--junitxml={junit}",
            ),
            output_dir=output_dir,
            runtime_roots=roots,
            cwd=roots["platform"] / "src/frontend",
        )

    assert not list(output_dir.iterdir())


@pytest.mark.parametrize("runner_name", ["uv", "pnpm"])
def test_execution_plan_rejects_absolute_runner_name_spoof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_name: str,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)
    spoofed_runner = tmp_path / "untrusted" / runner_name
    spoofed_runner.parent.mkdir()
    spoofed_target = spoofed_runner.with_name(f"{runner_name}.real")
    spoofed_target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    spoofed_target.chmod(0o700)
    spoofed_runner.symlink_to(spoofed_target.name)
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    if runner_name == "uv":
        name = "platform"
        cwd = roots["platform"]
        argv = (
            str(spoofed_runner),
            "run",
            "--frozen",
            "--extra",
            "dev",
            "pytest",
            "tests",
            "--junitxml={junit}",
        )
    else:
        name = "frontend"
        cwd = roots["platform"] / "src/frontend"
        argv = (
            str(spoofed_runner),
            "vitest",
            "run",
            "--reporter=junit",
            "--outputFile={junit}",
        )

    with pytest.raises(
        EvidenceBuildError,
        match="approved suite runner|absolute Vitest entry",
    ):
        run_test_suite(
            name=name,
            argv=argv,
            output_dir=output_dir,
            runtime_roots=roots,
            cwd=cwd,
        )

    assert not list(output_dir.iterdir())


def test_argv_secret_screen_allows_benign_test_names_but_rejects_secret_options() -> None:
    argv = validate_argv(
        (
            sys.executable,
            "-m",
            "pytest",
            "tests/test_token_stream.py",
            "--junitxml={junit}",
        ),
        require_junit_placeholder=True,
    )

    assert "tests/test_token_stream.py" in argv
    with pytest.raises(ExecutionEvidenceError, match="sensitive"):
        validate_argv(
            (
                sys.executable,
                "-m",
                "pytest",
                "--auth-token=must-not-persist",
                "--junitxml={junit}",
            ),
            require_junit_placeholder=True,
        )


def test_run_suite_rejects_partial_or_substituted_suite_selectors(
    tmp_path: Path,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="approved suite selector"):
        run_test_suite(
            name="platform",
            argv=(
                sys.executable,
                "-m",
                "pytest",
                "tests/test_release_receipt.py",
                "--junitxml={junit}",
            ),
            output_dir=output_dir,
            runtime_roots=roots,
            cwd=roots["platform"],
        )
    with pytest.raises(EvidenceBuildError, match="unapproved selector|full approved"):
        frontend = roots["platform"] / "src/frontend"
        run_test_suite(
            name="frontend",
            argv=(
                str(_node_executable()),
                str(frontend / "node_modules" / "vitest" / "vitest.mjs"),
                "run",
                "release-receipt.test.js",
                "--reporter=junit",
                "--outputFile={junit}",
            ),
            output_dir=output_dir,
            runtime_roots=roots,
            cwd=frontend,
        )

    assert not list(output_dir.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract")
def test_process_cleanup_kills_descendants_after_group_leader_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed_groups: list[int] = []

    class _ExitedLeader:
        pid = 4242

        @staticmethod
        def poll() -> int:
            return 0

    monkeypatch.setattr(
        os,
        "killpg",
        lambda process_group, _signal: killed_groups.append(process_group),
    )

    release_evidence_builder._terminate_process(  # noqa: SLF001
        cast(Any, _ExitedLeader())
    )

    assert killed_groups == [4242]


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract")
@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("success", None),
        ("timeout", "timed out"),
        ("oversize", "output is oversized"),
    ],
)
def test_bounded_runner_cleans_process_group_after_leader_exit(
    tmp_path: Path,
    mode: str,
    error: str | None,
) -> None:
    survived_file = tmp_path / f"{mode}.survived"
    if mode == "oversize":
        child_source = (
            "import pathlib,sys,time;"
            "sys.stdout.buffer.write(b'x'*(4*1024*1024+65536));"
            "sys.stdout.buffer.flush();time.sleep(1.5);"
            f"pathlib.Path({str(survived_file)!r}).write_text('survived')"
        )
        redirect = ""
    else:
        child_source = (
            "import pathlib,time;time.sleep(1.5);"
            f"pathlib.Path({str(survived_file)!r}).write_text('survived')"
        )
        redirect = (
            ",stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL"
            if mode == "success"
            else ""
        )
    leader_source = (
        "import subprocess,sys;"
        f"subprocess.Popen([sys.executable,'-c',{child_source!r}]{redirect})"
    )
    invocation = (
        sys.executable,
        "-c",
        leader_source,
    )

    if error is None:
        exit_code, _output = release_evidence_builder._execute_bounded(  # noqa: SLF001
            invocation,
            cwd=tmp_path,
            env={"PATH": os.defpath},
            timeout_seconds=5,
        )
        assert exit_code == 0
    else:
        with pytest.raises(EvidenceBuildError, match=error):
            release_evidence_builder._execute_bounded(  # noqa: SLF001
                invocation,
                cwd=tmp_path,
                env={"PATH": os.defpath},
                timeout_seconds=1 if mode == "timeout" else 5,
            )

    time.sleep(2)
    assert not survived_file.exists()


def test_run_suite_rejects_nonzero_exit_without_sealing_artifacts(
    tmp_path: Path,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    failing_test = roots["platform"] / "tests" / "test_release_receipt.py"
    failing_test.write_text(
        "def test_release_receipt():\n    assert False\n",
        encoding="utf-8",
    )
    _run("git", "add", ".", cwd=roots["platform"])
    _run("git", "commit", "-q", "-m", "failing fixture", cwd=roots["platform"])
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="exit code"):
        run_test_suite(
            name="platform",
            argv=(
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "--junitxml={junit}",
            ),
            output_dir=output_dir,
            runtime_roots=roots,
            cwd=roots["platform"],
        )

    assert not list(output_dir.iterdir())


def test_run_suite_rejects_oversized_output_without_sealing_artifacts(
    tmp_path: Path,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    noisy_test = roots["platform"] / "tests" / "test_release_receipt.py"
    noisy_test.write_text(
        "def test_release_receipt():\n    print('x' * (4 * 1024 * 1024 + 1), flush=True)\n",
        encoding="utf-8",
    )
    _run("git", "add", ".", cwd=roots["platform"])
    _run("git", "commit", "-q", "-m", "noisy fixture", cwd=roots["platform"])
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="output is oversized"):
        run_test_suite(
            name="platform",
            argv=(
                sys.executable,
                "-m",
                "pytest",
                "-s",
                "tests",
                "--junitxml={junit}",
            ),
            output_dir=output_dir,
            runtime_roots=roots,
            cwd=roots["platform"],
        )

    assert not list(output_dir.iterdir())


def test_run_suite_fails_closed_if_runtime_changes_during_execution(
    tmp_path: Path,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    mutating_test = roots["platform"] / "tests" / "test_release_receipt.py"
    mutating_test.write_text(
        "from pathlib import Path\n\n"
        "def test_release_receipt():\n"
        "    Path('tracked.txt').write_text('mutated during suite')\n",
        encoding="utf-8",
    )
    _run("git", "add", ".", cwd=roots["platform"])
    _run("git", "commit", "-q", "-m", "mutating fixture", cwd=roots["platform"])
    output_dir = tmp_path / "receipts"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="clean"):
        run_test_suite(
            name="platform",
            argv=(
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "--junitxml={junit}",
            ),
            output_dir=output_dir,
            runtime_roots=roots,
            cwd=roots["platform"],
        )

    assert not list(output_dir.iterdir())


@pytest.mark.parametrize(
    "xml",
    [
        "<testsuite><testcase></testsuite>",
        (
            '<testsuite tests="999" failures="0" errors="0" skipped="0">'
            '<testcase name="only-one"/></testsuite>'
        ),
        (
            '<!DOCTYPE testsuite [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            '<testsuite><testcase name="bad">&xxe;</testcase></testsuite>'
        ),
    ],
)
def test_junit_parser_rejects_malformed_or_entity_bearing_xml(xml: str) -> None:
    with pytest.raises(ExecutionEvidenceError, match="JUnit"):
        parse_junit_counts(xml.encode("utf-8"))


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_junit_parser_rejects_non_utf8_dtd_before_xml_parsing(
    encoding: str,
) -> None:
    xml = (
        '<!DOCTYPE testsuite [<!ENTITY x "forbidden">]>'
        '<testsuite tests="1"><testcase name="bad">&x;</testcase></testsuite>'
    )

    with pytest.raises(ExecutionEvidenceError, match="UTF-8"):
        parse_junit_counts(xml.encode(encoding))


@pytest.mark.parametrize(
    "xml",
    [
        (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<testsuite tests="1"><testcase name="bad"/></testsuite>'
        ),
        (
            '<testsuite tests="1" failures="0" errors="0" skipped="0">'
            '<testcase name="bad" failures="1"/></testsuite>'
        ),
        (
            '<testsuite tests="1" failures="1" errors="0" skipped="0">'
            '<testcase name="bad"><failure/><failure/></testcase></testsuite>'
        ),
        (
            '<testsuites tests="1" failures="0" errors="0" skipped="0">'
            '<testsuite tests="1" failures="1" errors="0" skipped="0">'
            '<testcase name="bad"><failure/></testcase></testsuite></testsuites>'
        ),
    ],
)
def test_junit_parser_rejects_encoding_or_declared_outcome_drift(
    xml: str,
) -> None:
    with pytest.raises(ExecutionEvidenceError, match="UTF-8|outcome|conflicting|counts"):
        parse_junit_counts(xml.encode("utf-8"))


def test_preflight_rejects_invented_receipt_and_stale_commit_rebinding(
    tmp_path: Path,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    valid_receipts = _test_receipts(tmp_path, roots)
    receipts = list(valid_receipts)
    invented = b'{"contract":"agent-v0.2-test-execution-receipt/v1"}'
    invented_path = (
        tmp_path / "receipts" / f"test-platform-receipt-{hashlib.sha256(invented).hexdigest()}.json"
    )
    invented_path.write_bytes(invented)
    invented_path.chmod(0o600)
    receipts[0] = invented_path
    output_dir = tmp_path / "preflight"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(
        EvidenceBuildError,
        match="v1 lacks required runner identity",
    ):
        build_candidate_preflight(
            output_dir=output_dir,
            runtime_roots=roots,
            test_receipts=tuple(receipts),
        )

    (roots["hqa"] / "tracked.txt").write_text("new commit", encoding="utf-8")
    _run("git", "add", "tracked.txt", cwd=roots["hqa"])
    _run("git", "commit", "-q", "-m", "new runtime", cwd=roots["hqa"])
    with pytest.raises(EvidenceBuildError, match="current clean runtimes"):
        build_candidate_preflight(
            output_dir=output_dir,
            runtime_roots=roots,
            test_receipts=valid_receipts,
        )


@pytest.mark.parametrize("missing_field", ["runner_kind", "suite_entry"])
def test_preflight_rejects_frontend_receipt_missing_node_identity(
    tmp_path: Path,
    missing_field: str,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    receipts = list(_test_receipts(tmp_path, roots))
    receipt = json.loads(receipts[3].read_text(encoding="utf-8"))
    receipt.pop(missing_field)
    content = json.dumps(
        receipt,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    missing_identity = receipts[3].parent / (
        f"test-frontend-receipt-{hashlib.sha256(content).hexdigest()}.json"
    )
    missing_identity.write_bytes(content)
    missing_identity.chmod(0o600)
    receipts[3] = missing_identity
    output_dir = tmp_path / "preflight"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="field root"):
        build_candidate_preflight(
            output_dir=output_dir,
            runtime_roots=roots,
            test_receipts=tuple(receipts),
        )


def test_preflight_rejects_stale_but_content_addressed_execution_receipt(
    tmp_path: Path,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    receipts = list(_test_receipts(tmp_path, roots))
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    stale = datetime.now(UTC) - timedelta(days=2)
    timestamp = stale.isoformat(timespec="microseconds").replace("+00:00", "Z")
    receipt["started_at"] = timestamp
    receipt["completed_at"] = timestamp
    content = json.dumps(
        receipt,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    stale_path = receipts[0].parent / (
        f"test-platform-receipt-{hashlib.sha256(content).hexdigest()}.json"
    )
    stale_path.write_bytes(content)
    stale_path.chmod(0o600)
    receipts[0] = stale_path
    output_dir = tmp_path / "preflight"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="freshness"):
        build_candidate_preflight(
            output_dir=output_dir,
            runtime_roots=roots,
            test_receipts=tuple(receipts),
        )


@pytest.mark.parametrize(
    "attack",
    ["future", "excessive_duration", "executable_digest", "suite_entry_digest"],
)
def test_preflight_rejects_time_or_executable_rebinding(
    tmp_path: Path,
    attack: str,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    receipts = list(_test_receipts(tmp_path, roots))
    receipt_index = 3 if attack == "suite_entry_digest" else 0
    receipt = json.loads(receipts[receipt_index].read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    if attack == "future":
        future = (now + timedelta(minutes=10)).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
        receipt["started_at"] = future
        receipt["completed_at"] = future
    elif attack == "excessive_duration":
        receipt["started_at"] = (now - timedelta(hours=23, minutes=56)).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
        receipt["completed_at"] = (now + timedelta(minutes=5)).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
    elif attack == "executable_digest":
        receipt["executable"]["sha256"] = _digest("substituted executable")
    else:
        receipt["suite_entry"]["sha256"] = _digest("substituted suite entry")
    content = json.dumps(
        receipt,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    rebound = receipts[receipt_index].parent / (
        f"test-{receipt['name']}-receipt-{hashlib.sha256(content).hexdigest()}.json"
    )
    rebound.write_bytes(content)
    rebound.chmod(0o600)
    receipts[receipt_index] = rebound
    output_dir = tmp_path / "preflight"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="freshness|executable|suite_entry"):
        build_candidate_preflight(
            output_dir=output_dir,
            runtime_roots=roots,
            test_receipts=tuple(receipts),
        )


@pytest.mark.parametrize("kind", ["output", "junit"])
def test_preflight_recomputes_and_rejects_tampered_test_files(
    tmp_path: Path,
    kind: str,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    receipts = _test_receipts(tmp_path, roots)
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    target = receipts[0].parent / receipt[kind]["path"]
    target.write_bytes(target.read_bytes() + b"tamper")
    target.chmod(0o600)
    output_dir = tmp_path / "preflight"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="digest or size"):
        build_candidate_preflight(
            output_dir=output_dir,
            runtime_roots=roots,
            test_receipts=receipts,
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX link/mode contract")
@pytest.mark.parametrize(
    "attack",
    [
        "receipt_symlink",
        "receipt_parent_symlink",
        "output_hardlink",
        "junit_mode",
    ],
)
def test_preflight_rejects_link_or_mode_weakened_execution_evidence(
    tmp_path: Path,
    attack: str,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    receipts = _test_receipts(tmp_path, roots)
    receipt = receipts[0]
    document = json.loads(receipt.read_text(encoding="utf-8"))
    if attack == "receipt_symlink":
        original = receipt.with_suffix(".original")
        receipt.rename(original)
        receipt.symlink_to(original)
    elif attack == "receipt_parent_symlink":
        original_parent = receipt.parent.with_name("receipts-original")
        receipt.parent.rename(original_parent)
        receipt.parent.symlink_to(original_parent, target_is_directory=True)
    elif attack == "output_hardlink":
        target = receipt.parent / document["output"]["path"]
        os.link(target, target.with_suffix(".alias"))
    else:
        target = receipt.parent / document["junit"]["path"]
        target.chmod(0o640)
    output_dir = tmp_path / "preflight"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(
        EvidenceBuildError,
        match="regular file|single-link|symlink",
    ):
        build_candidate_preflight(
            output_dir=output_dir,
            runtime_roots=roots,
            test_receipts=receipts,
        )


def test_preflight_rejects_duplicate_keys_in_execution_receipt(
    tmp_path: Path,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    receipts = list(_test_receipts(tmp_path, roots))
    original = receipts[0].read_text(encoding="utf-8")
    duplicate = (original[:-1] + ',"contract":"agent-v0.2-test-execution-receipt/v1"}').encode(
        "utf-8"
    )
    duplicate_path = (
        receipts[0].parent / f"test-platform-receipt-{hashlib.sha256(duplicate).hexdigest()}.json"
    )
    duplicate_path.write_bytes(duplicate)
    duplicate_path.chmod(0o600)
    receipts[0] = duplicate_path
    output_dir = tmp_path / "preflight"
    output_dir.mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="duplicate JSON"):
        build_candidate_preflight(
            output_dir=output_dir,
            runtime_roots=roots,
            test_receipts=tuple(receipts),
        )


def _facts(runtime: dict[str, dict[str, str]]) -> dict[str, object]:
    return {
        "admission_digest": _digest("admission"),
        "admission_id": "admission-test",
        "contract": "agent-v0.2-candidate-evidence-facts/v1",
        "database_schema_fingerprint": _digest("schema"),
        "final_order_snapshot_digest": _digest("zero-orders"),
        "flows": {
            "web_chat_multi_turn": {
                "assistant_message_count": 2,
                "command_ids": ["command-1", "command-2"],
                "hermes_session_id": "hermes-web",
                "message_count": 4,
                "platform_session_id": "platform-web",
                "route": "/hermes",
                "run_ids": ["run-1", "run-2"],
                "terminal_event_ids": [11, 12],
                "transcript_digest": _digest("private-transcript"),
                "user_message_count": 2,
                "command_approval_exact_cas": {
                    "action_digest": _digest("approval-action"),
                    "approval_id": "approval-core-1",
                    "challenge_id": "approval-challenge-1",
                    "choice": "once",
                    "command_digest": _digest("approved-command"),
                    "control_command_id": "control-approval-1",
                    "decision": "allow_once",
                    "event_ids": [
                        "approval-event-1",
                        "approval-event-2",
                        "approval-event-3",
                        "approval-event-4",
                    ],
                    "expected_expires_at": "2099-01-01T00:00:00.000000Z",
                    "platform_command_id": "command-approved-run",
                    "platform_command_state": "succeeded",
                    "route": "/hermes",
                    "run_id": "run-approved",
                    "run_status": "succeeded",
                    "waiter_signal_status": "confirmed",
                },
                "run_stop_recovery": {
                    "action_digest": _digest("stop-action"),
                    "control_command_id": "control-stop-1",
                    "idempotent_recovery_proven": True,
                    "platform_command_id": "command-stopped-run",
                    "platform_command_state": "cancelled",
                    "post_restart_instance_id": "2" * 32,
                    "route": "/hermes",
                    "run_id": "run-stopped",
                    "status": "stopped",
                    "stop_requested_at": "2026-07-24T01:00:00.000000Z",
                    "stop_requested_event_id": "stop-event-1",
                    "terminal_event": "run.cancelled",
                    "terminal_event_id": "stop-event-2",
                },
            },
            "hermes_restart_recovery": {
                "after_observation_id": "restart-after",
                "before_observation_id": "restart-before",
                "hermes_session_id": "hermes-web",
                "message_count": 4,
                "platform_session_id": "platform-web",
                "post_restart_instance_id": "2" * 32,
                "pre_restart_instance_id": "1" * 32,
                "route": "/hermes",
                "transcript_digest": _digest("private-transcript"),
            },
            "exact_message_fork": {
                "child_hermes_session_id": "hermes-child",
                "child_platform_session_id": "platform-child",
                "fork_point": "message:2",
                "provisioning_receipt_digest": _digest("fork-receipt"),
                "route": "/hermes",
                "source_channel": "discord",
                "source_hermes_session_id": "hermes-source",
                "source_message_count": 3,
                "source_platform_session_id": "platform-source",
                "source_transcript_digest": _digest("source-transcript"),
            },
            "options_vertical_live_futu_ro": {
                "admission_digest": _digest("admission"),
                "capture_digest": _digest("capture"),
                "claim_id": "claim-options",
                "command_id": "command-options",
                "hermes_run_id": "run-options",
                "hermes_session_id": "hermes-web",
                "orders_created": 0,
                "platform_session_id": "platform-web",
                "provider": "futu",
                "provider_receipt_digest": _digest("provider-receipt"),
                "provider_receipt_id": "provider-receipt-1",
                "provider_request_id": "provider-request-1",
                "request_id": "options-request-1",
                "result_id": "options-result-1",
                "result_payload_digest": _digest("options-result"),
                "route": "/hermes",
                "sample_or_real": "real",
            },
            "paper_factor_gate_1_2_3_via_hermes": {
                "attempt_ref": "attempt:paper",
                "candidate_digest": _digest("paper-candidate"),
                "candidate_id": "paper-candidate",
                "command_id": "command-paper",
                "final_backtest_receipt_id": "backtest-receipt-1",
                "gate1_confirmation_id": "gate1-confirmation",
                "gate1_hqa_ref": "gate:hqa-1",
                "gate1_id": "gate-platform-1",
                "gate1_receipt_digest": _digest("gate1-receipt"),
                "gate1_receipt_ref": "receipt:gate1",
                "gate1_source_digest": _digest("paper-source"),
                "gate2_hqa_ref": "gate:hqa-2",
                "gate2_id": "gate-platform-2",
                "gate2_receipt_digest": _digest("gate2-receipt"),
                "gate2_receipt_ref": "receipt:gate2",
                "gate3_hqa_ref": "gate:hqa-3",
                "gate3_id": "gate-platform-3",
                "gate3_receipt_digest": _digest("gate3-receipt"),
                "gate3_receipt_ref": "receipt:gate3",
                "hermes_run_id": "run-paper",
                "hermes_session_id": "hermes-web",
                "orders_created": 0,
                "platform_session_id": "platform-web",
                "promotion_id": "promotion-paper",
                "provider": "futu",
                "reviewed_commit": "e" * 40,
                "route": "/hermes",
                "task_ref": "task:paper",
                "workflow_audit_status": "consistent",
            },
        },
        "runtime": {name: item["digest"] for name, item in runtime.items()},
        "workspace_id": "workspace-root",
    }


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self.row = row
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> _Cursor:
        self.queries.append((statement, parameters))
        return _Cursor(self.row)


class _Database:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self.connection = _Connection(row)

    @contextmanager
    def connect(self) -> Iterator[_Connection]:
        yield self.connection


def _database(
    *,
    facts: dict[str, object],
    facts_digest: str | None = None,
) -> _Database:
    evidence_digest = facts_digest or _digest("evidence-set")
    runtime = cast(dict[str, str], facts["runtime"])
    row: tuple[object, ...] = (
        "evidence-test",
        "admission-test",
        _digest("admission"),
        None,
        "workspace-root",
        runtime["platform"],
        runtime["hqa"],
        runtime["hermes"],
        _digest("zero-orders"),
        _digest("zero-orders"),
        facts,
        evidence_digest,
        evidence_digest,
        datetime(2026, 7, 24, 2, 0, tzinfo=UTC),
        "open",
        None,
        None,
        None,
    )
    return _Database(row)


def _build_final(
    *,
    tmp_path: Path,
    roots: dict[str, Path],
    database: _Database,
    test_receipts: tuple[Path, ...] | None = None,
):
    receipts = test_receipts or _test_receipts(tmp_path, roots)
    row = database.connection.row
    if row is not None and row[3] is None:
        preflight_dir = tmp_path / "admitted-preflight"
        preflight_dir.mkdir(mode=0o700, exist_ok=True)
        preflight = build_candidate_preflight(
            output_dir=preflight_dir,
            runtime_roots=roots,
            test_receipts=receipts,
        )
        mutable_row = list(row)
        mutable_row[3] = preflight.digest
        database.connection.row = tuple(mutable_row)
    return build_release_evidence(
        cast(Settings, object()),
        output_dir=tmp_path / "evidence",
        runtime_roots=roots,
        test_receipts=receipts,
        admission_id="admission-test",
        admission_digest=_digest("admission"),
        evidence_set_id="evidence-test",
        evidence_set_digest=_digest("evidence-set"),
        database=cast(Any, database),
        runtime_security_probe=lambda _settings: True,
    )


def test_build_release_evidence_maps_exact_verified_facts_and_self_validates(
    tmp_path: Path,
) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    database = _database(facts=_facts(runtime))
    (tmp_path / "evidence").mkdir(mode=0o700)

    result = _build_final(tmp_path=tmp_path, roots=roots, database=database)

    assert result.idempotent_replay is False
    observation = release_evidence_observation(result.manifest_path)
    assert observation.digest == result.digest
    assert observation.candidate_admission_id == "admission-test"
    assert observation.evidence_set_id == "evidence-test"
    assert observation.evidence_set_digest == _digest("evidence-set")
    assert observation.final_order_snapshot_digest == _digest("zero-orders")
    assert len(list((tmp_path / "evidence").glob("*.json"))) == 12
    assert {
        oct(path.stat().st_mode & 0o777) for path in (tmp_path / "evidence").glob("*.json")
    } == {"0o600"}
    manifest_text = result.manifest_path.read_text(encoding="utf-8")
    assert "private-transcript" not in manifest_text
    flow = json.loads(
        (tmp_path / "evidence" / "real-flow-hermes-restart-recovery.json").read_text(
            encoding="utf-8"
        )
    )
    assert flow["evidence"]["before_transcript_digest"] == _digest("private-transcript")
    assert flow["evidence"]["after_transcript_digest"] == _digest("private-transcript")
    assert len(database.connection.queries) == 1
    query, parameters = database.connection.queries[0]
    assert "agent_v02_candidate_evidence_sets" in query
    assert parameters[-4:] == (
        "admission-test",
        _digest("admission"),
        "evidence-test",
        _digest("evidence-set"),
    )


def test_build_release_evidence_rejects_missing_flow(tmp_path: Path) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    facts = _facts(runtime)
    cast(dict[str, object], facts["flows"]).pop("exact_message_fork")
    database = _database(facts=facts)
    (tmp_path / "evidence").mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="required flow"):
        _build_final(tmp_path=tmp_path, roots=roots, database=database)

    assert not list((tmp_path / "evidence").iterdir())


def test_build_release_evidence_requires_exact_database_row(tmp_path: Path) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    database = _Database(None)
    (tmp_path / "evidence").mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="exact verified"):
        _build_final(tmp_path=tmp_path, roots=roots, database=database)


def test_build_release_evidence_rejects_dirty_runtime(tmp_path: Path) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    (roots["hqa"] / "untracked.txt").write_text("dirty", encoding="utf-8")
    database = _database(facts=_facts(runtime))
    (tmp_path / "evidence").mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="clean"):
        _build_final(tmp_path=tmp_path, roots=roots, database=database)

    assert not list((tmp_path / "evidence").iterdir())


def test_build_release_evidence_rejects_runtime_digest_mismatch(
    tmp_path: Path,
) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    facts = _facts(runtime)
    cast(dict[str, str], facts["runtime"])["hermes"] = _digest("other-hermes")
    database = _database(facts=facts)
    (tmp_path / "evidence").mkdir(mode=0o700)

    with pytest.raises(EvidenceBuildError, match="runtime"):
        _build_final(tmp_path=tmp_path, roots=roots, database=database)


def test_build_release_evidence_detects_tamper_and_conflicting_replay(
    tmp_path: Path,
) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    database = _database(facts=_facts(runtime))
    (tmp_path / "evidence").mkdir(mode=0o700)
    result = _build_final(tmp_path=tmp_path, roots=roots, database=database)
    artifact = tmp_path / "evidence" / "real-flow-web-chat-multi-turn.json"
    artifact.write_bytes(b"{}")
    artifact.chmod(0o600)

    with pytest.raises(ReleaseRuntimeProbeError):
        release_evidence_observation(result.manifest_path)
    with pytest.raises(EvidenceBuildConflict, match="different"):
        _build_final(tmp_path=tmp_path, roots=roots, database=database)


@pytest.mark.parametrize("kind", ["output", "junit"])
def test_final_release_validator_reopens_copied_test_evidence(
    tmp_path: Path,
    kind: str,
) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    database = _database(facts=_facts(runtime))
    (tmp_path / "evidence").mkdir(mode=0o700)
    result = _build_final(tmp_path=tmp_path, roots=roots, database=database)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    receipt_ref = manifest["tests"]["suites"][0]["receipt"]
    receipt_path = result.manifest_path.parent / receipt_ref["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    target = result.manifest_path.parent / receipt[kind]["path"]
    target.write_bytes(target.read_bytes() + b"tamper")
    target.chmod(0o600)

    with pytest.raises(ReleaseRuntimeProbeError, match="digest or size"):
        release_evidence_observation(result.manifest_path)


def test_build_release_evidence_replay_is_idempotent_and_drift_conflicts(
    tmp_path: Path,
) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    database = _database(facts=_facts(runtime))
    (tmp_path / "evidence").mkdir(mode=0o700)
    first = _build_final(tmp_path=tmp_path, roots=roots, database=database)
    replay = _build_final(tmp_path=tmp_path, roots=roots, database=database)

    assert replay.manifest_path == first.manifest_path
    assert replay.digest == first.digest
    assert replay.idempotent_replay is True

    changed = _test_receipts(
        tmp_path / "changed",
        roots,
        reuse=False,
    )
    with pytest.raises(EvidenceBuildError, match="admitted candidate preflight"):
        _build_final(
            tmp_path=tmp_path,
            roots=roots,
            database=database,
            test_receipts=changed,
        )


def test_build_candidate_preflight_is_valid_and_idempotent(tmp_path: Path) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    output_dir = tmp_path / "preflight"
    output_dir.mkdir(mode=0o700)
    receipts = _test_receipts(tmp_path, roots)

    first = build_candidate_preflight(
        output_dir=output_dir,
        runtime_roots=roots,
        test_receipts=receipts,
    )
    replay = build_candidate_preflight(
        output_dir=output_dir,
        runtime_roots=roots,
        test_receipts=receipts,
    )

    observation = candidate_preflight_evidence_observation(first.manifest_path)
    assert observation.digest == first.digest
    assert observation.test_passed_count == 6
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert replay.digest == first.digest


def test_final_build_reuses_exact_preflight_test_artifacts(tmp_path: Path) -> None:
    roots, runtime = _runtime_roots(tmp_path)
    output_dir = tmp_path / "evidence"
    output_dir.mkdir(mode=0o700)
    receipts = _test_receipts(tmp_path, roots)
    preflight = build_candidate_preflight(
        output_dir=output_dir,
        runtime_roots=roots,
        test_receipts=receipts,
    )
    database = _database(facts=_facts(runtime))

    final = _build_final(
        tmp_path=tmp_path,
        roots=roots,
        database=database,
        test_receipts=receipts,
    )

    assert preflight.manifest_path.is_file()
    assert final.manifest_path.is_file()
    assert final.idempotent_replay is False
    # Preflight and final manifests intentionally share the exact four
    # content-addressed test receipts.  The final manifest additionally emits
    # the seven required real-flow artifacts, so no duplicate test receipt is
    # introduced when the admitted preflight is promoted.
    assert len(list(output_dir.glob("*.json"))) == 13


def test_build_candidate_preflight_rejects_symlink_and_sensitive_argv(
    tmp_path: Path,
) -> None:
    roots, _runtime = _runtime_roots(tmp_path)
    real_output = tmp_path / "real-output"
    real_output.mkdir(mode=0o700)
    linked_output = tmp_path / "linked-output"
    linked_output.symlink_to(real_output, target_is_directory=True)
    receipts = _test_receipts(tmp_path, roots)

    with pytest.raises(EvidenceBuildError, match="symlink"):
        build_candidate_preflight(
            output_dir=linked_output,
            runtime_roots=roots,
            test_receipts=receipts,
        )

    with pytest.raises(EvidenceBuildError, match="sensitive"):
        run_test_suite(
            name="platform",
            argv=("pytest", "--api-key=must-not-be-persisted", "{junit}"),
            output_dir=tmp_path / "receipts",
            runtime_roots=roots,
            cwd=roots["platform"],
        )
    assert not list(real_output.iterdir())


def test_release_evidence_builder_module_help() -> None:
    environment = {**os.environ, "PYTHONPATH": "src"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quant_system.hermes.release_evidence_builder",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert "run-suite" in result.stdout
    assert "build-preflight" in result.stdout
    assert "build-final" in result.stdout
    for command in ("build-preflight", "build-final"):
        command_help = subprocess.run(
            [
                sys.executable,
                "-m",
                "quant_system.hermes.release_evidence_builder",
                command,
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert command_help.returncode == 0, command_help.stderr
        assert "--test-receipt" in command_help.stdout
        assert "--tests-json" not in command_help.stdout
