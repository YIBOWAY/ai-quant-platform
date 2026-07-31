from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "verify_backend_non_postgres.sh"
HELPER = ROOT / "scripts" / "backend_non_postgres_gate.py"


def _git(cwd: Path, *arguments: str) -> None:
    subprocess.run(
        ["/usr/bin/git", "-C", str(cwd), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def _gate_helper():
    spec = importlib.util.spec_from_file_location("backend_non_postgres_gate", HELPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_minimal_gate_contract(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        """
[tool.quant_system.release.backend_non_postgres]
python = "3.11"
marker_expression = "not pg and not futu_opend and not provider and not network"
expected_skip_node_ids = []
""".lstrip(),
        encoding="utf-8",
    )
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")


def _runner_environment(tmp_path: Path) -> dict[str, str]:
    runtime_bin = tmp_path / "runner-runtime-bin"
    runtime_bin.mkdir()
    python = runtime_bin / "python3.11"
    python.symlink_to(Path(sys.executable).resolve())
    for name in ("uv", "node"):
        executable = runtime_bin / name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{runtime_bin}{os.pathsep}{os.defpath}",
    }


def test_runner_describes_commit_bound_gate2_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        ["bash", str(RUNNER), "--describe"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_runner_environment(tmp_path),
    )

    assert completed.returncode == 0, completed.stderr
    contract = json.loads(completed.stdout)
    assert contract == {
        "artifact_policy": {
            "evidence_output": "sealed-files-only",
            "recursive_cleanup_by_runner": False,
            "transient_root": "checkout/.tmp",
        },
        "branch": "codex/agent-v0-2-release",
        "contract": "quant-system-backend-non-postgres/v1",
        "entrypoint": "scripts/verify_backend_non_postgres.sh",
        "expected_commit_required": True,
        "expected_skip_node_ids": [],
        "install": {
            "all_extras": True,
            "environment_location": "checkout",
            "frozen": True,
            "no_editable": True,
            "runner": "uv",
        },
        "python": "3.11",
        "publication_remote": {
            "name": "github",
            "url": "https://github.com/YIBOWAY/ai-quant-platform.git",
        },
        "sanitized_environment": {
            "QS_DATABASE_AUTO_MIGRATE": "false",
            "QS_DATABASE_ENABLED": "false",
            "QS_DEFAULT_DATA_PROVIDER": "sample",
            "QS_FUTU_ENABLED": "false",
            "QS_KILL_SWITCH": "true",
            "QS_LIVE_TRADING_ENABLED": "false",
            "QS_TEST_FUTU_OPEND": "0",
            "strategy": "allowlist",
        },
        "suite": {
            "junit_required": True,
            "marker_expression": (
                "not pg and not futu_opend and not provider and not network"
            ),
            "nonzero_collection_required": True,
            "selector": "tests",
            "strict_markers": True,
            "unexpected_skips_fail": True,
        },
    }


def test_runner_self_test_exercises_fail_closed_result_validation(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        ["bash", str(RUNNER), "--self-test"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_runner_environment(tmp_path),
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "cases": {
            "declared_skip": "accepted",
            "network_sandbox": "accepted",
            "nonzero_collection": "accepted",
            "pytest_failure": "rejected",
            "transient_hygiene": "accepted",
            "undeclared_skip": "rejected",
            "zero_collection": "rejected",
        },
        "contract": "quant-system-backend-non-postgres/v1",
        "status": "ok",
    }


@pytest.mark.parametrize(
    "forbidden_arguments",
    [
        ("--repository-root", str(ROOT)),
        ("--uv", sys.executable),
    ],
)
def test_public_runner_rejects_helper_only_arguments(
    forbidden_arguments: tuple[str, str],
) -> None:
    completed = subprocess.run(
        ["bash", str(RUNNER), "--describe", *forbidden_arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 78
    assert (
        "backend_non_postgres_error=public_argument_forbidden"
        in completed.stderr
    )
    assert completed.stdout == ""


@pytest.mark.parametrize(
    "arguments",
    [
        ("--describe", "--describe"),
        ("--self-test", "--self-test"),
        (
            "--output-dir",
            "/tmp/gate2-duplicate-output-a",
            "--output-dir=/tmp/gate2-duplicate-output-b",
            "--expected-commit",
            "0" * 40,
        ),
        (
            "--output-dir",
            "/tmp/gate2-duplicate-commit-output",
            "--expected-commit",
            "0" * 40,
            f"--expected-commit={'1' * 40}",
        ),
    ],
)
def test_public_runner_rejects_duplicate_public_arguments(
    arguments: tuple[str, ...],
) -> None:
    completed = subprocess.run(
        ["bash", str(RUNNER), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 78
    assert (
        "backend_non_postgres_error=public_argument_duplicate"
        in completed.stderr
    )
    assert completed.stdout == ""


def test_public_runner_forwards_exact_public_argv_to_helper(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    scripts = release_root / "scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / RUNNER.name
    shutil.copy2(RUNNER, wrapper)
    wrapper.chmod(0o755)
    helper = scripts / HELPER.name
    helper.write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    public_argv = (
        "--expected-commit=" + "a" * 40,
        "--output-dir",
        "/tmp/gate2-public-argv",
    )

    completed = subprocess.run(
        ["bash", str(wrapper), *public_argv],
        cwd=release_root,
        check=False,
        capture_output=True,
        text=True,
        env=_runner_environment(tmp_path),
    )

    assert completed.returncode == 0, completed.stderr
    helper_argv = json.loads(completed.stdout)
    boundary = helper_argv.index("--public-argv")
    assert helper_argv[boundary + 1 :] == list(public_argv)
    assert helper_argv[boundary - 2 : boundary] == [
        "--public-entrypoint",
        str(wrapper),
    ]


def test_gate_receipt_records_exact_public_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _gate_helper()
    root = tmp_path / "repository"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    _write_minimal_gate_contract(root)
    for name in (HELPER.name, RUNNER.name):
        (scripts / name).write_text(f"# {name}\n", encoding="utf-8")
    fake_uv = root / "fake-uv"
    fake_uv.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_uv.chmod(0o700)
    evidence_parent = tmp_path / "evidence"
    evidence_parent.mkdir(mode=0o700)
    output = evidence_parent / "gate2"
    commit = "a" * 40
    repository_identity = {
        "branch": "codex/agent-v0-2-release",
        "clean": True,
        "commit": commit,
        "git_toplevel": str(root),
        "publication_remote": "github",
        "publication_remote_url": (
            "https://github.com/YIBOWAY/ai-quant-platform.git"
        ),
        "root": str(root),
        "tracked_tree": {},
        "tree": "b" * 40,
    }

    monkeypatch.setattr(
        helper,
        "_require_expected_commit",
        lambda _root, _commit: repository_identity,
    )
    monkeypatch.setattr(helper, "_git_identity", lambda _root: repository_identity)
    monkeypatch.setattr(helper, "_require_sandbox_exec", lambda: fake_uv)
    monkeypatch.setattr(
        helper,
        "_validate_import_probe",
        lambda _document, **_kwargs: {
            "quant_system_file": str(root / "installed" / "__init__.py")
        },
    )
    monkeypatch.setattr(
        helper,
        "installed_quant_system_tree_identity",
        lambda _module: {
            "file_count": 1,
            "root": str(root / "installed"),
            "tree_sha256": "c" * 64,
        },
    )
    monkeypatch.setattr(
        helper,
        "installed_environment_tree_identity",
        lambda _venv: {
            "entry_count": 1,
            "root": str(root / "venv"),
            "tree_sha256": "d" * 64,
        },
    )
    monkeypatch.setattr(
        helper,
        "normalize_installed_environment_lock",
        lambda _venv: {
            "after_mode": "600",
            "before_mode": "666",
            "owner_uid": 501,
            "path": ".lock",
        },
    )

    def fake_run_logged(*, argv, env, name, output, **_kwargs):
        stdout = b""
        if name == "uv-version":
            stdout = b"uv 0.test\n"
        elif name == "uv-sync":
            python = Path(env["UV_PROJECT_ENVIRONMENT"]) / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\n", encoding="utf-8")
            python.chmod(0o700)
        elif name == "dependency-inventory":
            stdout = b"quant-system==0.1.0\n"
        elif name == "pytest-backend-non-postgres":
            stdout = b"1 passed\n"
            (output / "pytest-backend-non-postgres.junit.xml").write_bytes(
                b'<testsuite tests="1" failures="0" errors="0" skipped="0">'
                b'<testcase classname="tests.test_gate" name="test_pass"/>'
                b"</testsuite>"
            )
        return (
            subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b""),
            {"argv": list(argv), "exit_code": 0},
        )

    def fake_json_probe(*, argv, **_kwargs):
        return (
            subprocess.CompletedProcess(argv, 0, stdout=b"{}", stderr=b""),
            {"argv": list(argv), "exit_code": 0},
        )

    monkeypatch.setattr(helper, "_run_logged", fake_run_logged)
    monkeypatch.setattr(helper, "_run_json_probe", fake_json_probe)
    public_entrypoint = str(root / "scripts" / RUNNER.name)
    public_argv = (
        f"--expected-commit={commit}",
        "--output-dir",
        str(output),
    )

    result = helper.run_gate(
        root=root,
        output_argument=output,
        expected_commit=commit,
        uv_argument=fake_uv,
        marker_expression=(
            "not pg and not futu_opend and not provider and not network"
        ),
        expected_skip_node_ids=(),
        public_entrypoint=public_entrypoint,
        public_argv=public_argv,
    )

    receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
    assert receipt["command"]["argv"] == [public_entrypoint, *public_argv]


def test_helper_rejects_repository_root_that_does_not_contain_executed_helper(
    tmp_path: Path,
) -> None:
    substituted_root = tmp_path / "substituted-root"
    substituted_root.mkdir()
    _write_minimal_gate_contract(substituted_root)

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(HELPER),
            "--repository-root",
            str(substituted_root),
            "--uv",
            sys.executable,
            "--public-entrypoint",
            str(HELPER),
            "--public-argv",
            "--describe",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 78
    assert "backend_non_postgres_error=helper_path_mismatch" in completed.stderr
    assert completed.stdout == ""


def test_helper_rejects_repository_root_below_git_toplevel(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    substituted_root = repository / "nested-platform"
    scripts = substituted_root / "scripts"
    scripts.mkdir(parents=True)
    substituted_helper = scripts / HELPER.name
    substituted_helper.write_bytes(HELPER.read_bytes())
    _write_minimal_gate_contract(substituted_root)
    _git(repository, "init", "-q", "-b", "codex/agent-v0-2-release")

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(substituted_helper),
            "--repository-root",
            str(substituted_root),
            "--uv",
            sys.executable,
            "--public-entrypoint",
            str(substituted_helper),
            "--public-argv",
            "--describe",
        ],
        cwd=substituted_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 78
    assert "backend_non_postgres_error=git_toplevel_mismatch" in completed.stderr
    assert completed.stdout == ""


def test_helper_rejects_noncanonical_public_entrypoint(tmp_path: Path) -> None:
    substituted_entrypoint = tmp_path / RUNNER.name
    substituted_entrypoint.write_text("# substituted\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(HELPER),
            "--repository-root",
            str(ROOT),
            "--uv",
            sys.executable,
            "--public-entrypoint",
            str(substituted_entrypoint),
            "--public-argv",
            "--describe",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 78
    assert (
        "backend_non_postgres_error=public_entrypoint_mismatch"
        in completed.stderr
    )
    assert completed.stdout == ""


def test_runner_rejects_a_checkout_that_does_not_match_expected_commit(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            "bash",
            str(RUNNER),
            "--output-dir",
            str(tmp_path / "evidence"),
            "--expected-commit",
            "0" * 40,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_runner_environment(tmp_path),
    )

    assert completed.returncode == 78
    assert "backend_non_postgres_error=expected_commit_mismatch" in completed.stderr


def test_gate2_collection_excludes_declared_external_nodes_without_skips() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-vv",
            "--strict-markers",
            "-m",
            "not pg and not futu_opend and not provider and not network",
            "tests/test_hermes_connector_dispatch.py",
            "tests/test_paper_strategy_sleeves_futu_integration.py",
            "tests/test_api_safety.py",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = completed.stdout + completed.stderr
    assert "test_pg_supervised_happy_path_delivers_and_links_run" not in output
    assert "test_pg_timeout_is_outcome_unknown_and_not_reclaimed" not in output
    assert "test_pg_gate_reject_never_calls_hermes" not in output
    assert "test_pg_accept_drop_ack_then_recover_same_run_identity" not in output
    assert "test_pg_empty_queue_zero_provider_and_hermes" not in output
    assert "test_real_futu_opend_generates_strategy_sleeve_signal" not in output
    assert "test_real_futu_opend_supports_next_open_execution_processor" not in output
    assert "test_futu_skill_mutating_trade_entrypoints_are_disabled" not in output
    assert "skipped" not in output


@pytest.mark.parametrize("hidden_flag", ["--assume-unchanged", "--skip-worktree"])
def test_repository_identity_rejects_hidden_tracked_changes(
    tmp_path: Path,
    hidden_flag: str,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q", "-b", "codex/agent-v0-2-release")
    _git(repository, "config", "user.name", "Gate 2 Test")
    _git(repository, "config", "user.email", "gate2@example.invalid")
    _git(
        repository,
        "remote",
        "add",
        "github",
        "https://github.com/YIBOWAY/ai-quant-platform.git",
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-q", "-m", "fixture")
    _git(repository, "update-index", hidden_flag, "tracked.txt")
    tracked.write_text("hidden change\n", encoding="utf-8")

    helper = _gate_helper()
    with pytest.raises(helper.GateError, match="tracked_index_flags_hidden"):
        helper._git_identity(repository)
