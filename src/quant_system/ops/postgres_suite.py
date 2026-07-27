"""Canonical unique disposable-PostgreSQL Agent v0.2 verification suite."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from quant_system.ops.backup_restore import verify_backup_restore_in_owned_container
from quant_system.ops.common import (
    ReleaseOperationError,
    canonical_json_bytes,
    ensure_private_directory,
    git_identity,
    sha256_bytes,
    utc_now,
    write_immutable,
)
from quant_system.ops.postgres_common import (
    create_database,
    drop_database,
    role_facts,
    temporary_database_name,
)
from quant_system.ops.postgres_container import DisposablePostgresContainer
from quant_system.storage.database import Database, run_migrations

DISPATCH_NODES = (
    "tests/test_hermes_connector_dispatch.py::test_pg_supervised_happy_path_delivers_and_links_run",
    "tests/test_hermes_connector_dispatch.py::test_pg_timeout_is_outcome_unknown_and_not_reclaimed",
    "tests/test_hermes_connector_dispatch.py::test_pg_gate_reject_never_calls_hermes",
    "tests/test_hermes_connector_dispatch.py::test_pg_accept_drop_ack_then_recover_same_run_identity",
    "tests/test_hermes_connector_dispatch.py::test_pg_empty_queue_zero_provider_and_hermes",
)
COVERAGE = {
    "migration": (
        "tests/test_database.py",
        "tests/test_agent_v02_migrations_025_026_postgres.py",
    ),
    "authority": (
        "tests/test_hermes_workflow_binding.py",
        "tests/test_hermes_session_registry.py",
    ),
    "claim_dispatch": DISPATCH_NODES,
    "approval_stop": ("tests/test_run_control_outcome_postgres.py",),
    "release": (
        "tests/test_hermes_release_authority.py",
        "tests/test_release_authority_hardening.py",
    ),
    "replay": (
        "tests/test_run_control_outcome_postgres.py",
        "tests/test_hermes_release_authority.py",
    ),
    "restore": (
        "quant_system.ops.backup_restore.verify_backup_restore_in_owned_container",
    ),
}


def pg_marked_test_files(repository_root: Path) -> tuple[str, ...]:
    """Return every repository test module that declares the PostgreSQL marker.

    Passing the explicit files avoids importing unrelated module-level skips
    before pytest's marker filter can deselect them.  The source scan remains
    additive: a newly introduced PostgreSQL module is automatically included.
    """

    test_root = repository_root / "tests"
    files = tuple(
        path.relative_to(repository_root).as_posix()
        for path in sorted(test_root.glob("test_*.py"))
        if "pytest.mark.pg" in path.read_text(encoding="utf-8")
    )
    if not files:
        raise ReleaseOperationError("no PostgreSQL-marked test modules were discovered")
    return files


def _verify_pg_coverage(files: tuple[str, ...]) -> None:
    required = {
        path
        for covered in COVERAGE.values()
        for path in covered
        if isinstance(path, str) and path.startswith("tests/") and "::" not in path
    }
    missing = sorted(required.difference(files))
    if missing:
        raise ReleaseOperationError(
            "PostgreSQL test discovery missed required coverage: " + ",".join(missing)
        )


def _safe_test_environment(
    *,
    repository_root: Path,
    database_url: str,
) -> dict[str, str]:
    inherited = os.environ
    env = {
        name: inherited[name]
        for name in ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR", "TZ", "USER")
        if name in inherited
    }
    env.update(
        {
            "PYTHONPATH": str(repository_root / "src"),
            "QS_TEST_DATABASE_URL": database_url,
            "QS_TEST_DATABASE_ADMIN_URL": database_url,
            "QS_DATABASE_AUTO_MIGRATE": "false",
            "QS_FUTU_ENABLED": "false",
            "QS_LLM_PROVIDER": "stub",
            "QS_LIVE_TRADING_ENABLED": "false",
            "QS_KILL_SWITCH": "true",
            "QS_TEST_FUTU_OPEND": "0",
        }
    )
    return env


def _run_pytest(
    *,
    python: Path,
    repository_root: Path,
    env: dict[str, str],
    arguments: tuple[str, ...],
    log_path: Path,
) -> dict[str, object]:
    argv = (str(python), "-m", "pytest", "-q", "-rA", *arguments)
    completed = subprocess.run(
        argv,
        cwd=repository_root,
        env=env,
        check=False,
        capture_output=True,
    )
    payload = completed.stdout + completed.stderr
    write_immutable(log_path, payload)
    text = payload.decode("utf-8", "replace")
    skipped = sum(int(value) for value in re.findall(r"(\d+) skipped", text))
    if completed.returncode != 0:
        raise ReleaseOperationError(f"disposable PostgreSQL pytest failed: {log_path.name}")
    if skipped:
        raise ReleaseOperationError(f"disposable PostgreSQL pytest has unexpected skips: {skipped}")
    return {
        "argv": list(argv),
        "exit_code": completed.returncode,
        "stdout_stderr_sha256": sha256_bytes(payload),
        "stdout_stderr_bytes": len(payload),
        "unexpected_skips": skipped,
        "log_path": str(log_path),
    }


def verify_postgres_suite(
    *,
    repository_root: Path,
    output_dir: Path,
    python: Path | None = None,
) -> dict[str, object]:
    repository_root = repository_root.resolve()
    output_dir = ensure_private_directory(output_dir)
    receipt_path = output_dir / "postgres-suite-receipt.json"
    if receipt_path.exists():
        raise ReleaseOperationError("PostgreSQL suite receipt already exists")
    executable = (python or Path(sys.executable)).absolute()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ReleaseOperationError("PostgreSQL suite Python is not executable")
    identity = git_identity(repository_root, require_clean=True)

    container = DisposablePostgresContainer()
    container_identity = container.start()
    container_cleanup_proven = False
    try:
        database_name = temporary_database_name(purpose="suite")
        source_url = create_database(container.url, database_name)
        database_cleanup_proven = False
        try:
            # Establish the final migration ladder once before the role baseline.
            # Tests then cover repeatability, authority, crash/replay, and security.
            run_migrations(Database(source_url, connect_timeout=1))
            roles_before = role_facts(source_url)
            env = _safe_test_environment(
                repository_root=repository_root,
                database_url=source_url,
            )
            marked_files = pg_marked_test_files(repository_root)
            _verify_pg_coverage(marked_files)
            marked = _run_pytest(
                python=executable,
                repository_root=repository_root,
                env=env,
                arguments=("-m", "pg", *marked_files),
                log_path=output_dir / "pytest-pg-marked.log",
            )
            dispatch = _run_pytest(
                python=executable,
                repository_root=repository_root,
                env=env,
                arguments=DISPATCH_NODES,
                log_path=output_dir / "pytest-pg-dispatch.log",
            )
            run_migrations(Database(source_url, connect_timeout=1))
            roles_after = role_facts(source_url)
            if roles_before["sha256"] != roles_after["sha256"]:
                raise ReleaseOperationError("PostgreSQL suite leaked global role changes")
        finally:
            drop_database(container.url, database_name)
            database_cleanup_proven = True
        if not database_cleanup_proven:
            raise ReleaseOperationError("PostgreSQL suite database cleanup is unproven")
    finally:
        container.stop()
        container_cleanup_proven = True

    if not container_cleanup_proven:
        raise ReleaseOperationError("PostgreSQL suite container cleanup is unproven")
    backup = verify_backup_restore_in_owned_container(
        output_dir=output_dir / "backup-restore",
        repository_root=repository_root,
    )
    receipt: dict[str, object] = {
        "schema_version": "agent-v0.2.2-disposable-postgres-suite.v1",
        "status": "passed",
        "completed_at": utc_now(),
        "repository": asdict(identity),
        "python": str(executable),
        "database_name": database_name,
        "database_was_unique_disposable": True,
        "database_created": True,
        "database_dropped": True,
        "container": {
            **asdict(container_identity),
            "removed": True,
            "network_pull_allowed": False,
        },
        "admin_input_database_contacted": False,
        "canonical_database_contacted": False,
        "pytest_environment_policy": {
            "inherited_names": [
                "HOME",
                "LANG",
                "LC_ALL",
                "PATH",
                "TMPDIR",
                "TZ",
                "USER",
            ],
            "provider_config": "stub",
            "futu_enabled": False,
            "live_trading_enabled": False,
            "kill_switch": True,
            "provider_or_broker_credentials_forwarded": False,
        },
        "operating_system_network_sandbox_enforced": False,
        "intended_network_scope": "literal-loopback disposable PostgreSQL only",
        "coverage": COVERAGE,
        "pytest_pg_modules": list(marked_files),
        "pytest_pg_marked": marked,
        "pytest_pg_dispatch": dispatch,
        "backup_restore": backup,
        "role_facts_before_sha256": roles_before["sha256"],
        "role_facts_after_sha256": roles_after["sha256"],
        "role_facts_unchanged": True,
    }
    write_immutable(receipt_path, canonical_json_bytes(receipt))
    return receipt
