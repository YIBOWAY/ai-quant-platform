"""Canonical unique disposable-PostgreSQL Agent v0.2 verification suite."""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
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
    cleanup_roles_created_since,
    create_database,
    drop_database,
    role_facts,
    temporary_database_name,
)
from quant_system.ops.postgres_container import (
    DisposablePostgresContainer,
    owned_process_environment,
)
from quant_system.storage.database import Database, run_migrations

DISPATCH_NODES = (
    "tests/test_hermes_connector_dispatch.py::test_pg_supervised_happy_path_delivers_and_links_run",
    "tests/test_hermes_connector_dispatch.py::test_pg_timeout_is_outcome_unknown_and_not_reclaimed",
    "tests/test_hermes_connector_dispatch.py::test_pg_gate_reject_never_calls_hermes",
    "tests/test_hermes_connector_dispatch.py::test_pg_accept_drop_ack_then_recover_same_run_identity",
    "tests/test_hermes_connector_dispatch.py::test_pg_empty_queue_zero_provider_and_hermes",
)
MINIMUM_PG_MARKED_TESTS = 245
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
    "restore": ("quant_system.ops.backup_restore.verify_backup_restore_in_owned_container",),
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
    process_root: Path,
) -> dict[str, str]:
    env = owned_process_environment(process_root)
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
    minimum_tests: int,
) -> dict[str, object]:
    basetemp = Path(env["TMPDIR"]) / log_path.stem
    cache_dir = Path(env["XDG_CACHE_HOME"]) / "pytest" / log_path.stem
    junit_path = log_path.with_suffix(".junit.xml")
    node_manifest_path = log_path.with_suffix(".nodes.json")
    if junit_path.exists() or node_manifest_path.exists():
        raise ReleaseOperationError("PostgreSQL pytest population artifact already exists")
    argv = (
        str(python),
        "-m",
        "pytest",
        "-q",
        "-rA",
        "--basetemp",
        str(basetemp),
        "-o",
        f"cache_dir={cache_dir}",
        "-o",
        "junit_family=xunit2",
        "--junitxml",
        str(junit_path),
        *arguments,
    )
    completed = subprocess.run(
        argv,
        cwd=repository_root,
        env=env,
        check=False,
        capture_output=True,
    )
    payload = completed.stdout + completed.stderr
    write_immutable(log_path, payload)
    if not junit_path.is_file():
        raise ReleaseOperationError(
            f"disposable PostgreSQL pytest omitted JUnit: {log_path.name}"
        )
    junit_path.chmod(0o600)
    population = parse_pytest_junit(junit_path)
    write_immutable(node_manifest_path, canonical_json_bytes(population))
    if completed.returncode != 0:
        raise ReleaseOperationError(f"disposable PostgreSQL pytest failed: {log_path.name}")
    if population["tests"] < minimum_tests:
        raise ReleaseOperationError(
            f"disposable PostgreSQL pytest population shrank: {population['tests']}"
        )
    unexpected = sum(
        population[field]
        for field in ("failed", "errors", "skipped", "xfailed")
    )
    if unexpected:
        raise ReleaseOperationError(
            f"disposable PostgreSQL pytest has unexpected outcomes: {unexpected}"
        )
    text = payload.decode("utf-8", "strict")
    if "XPASS" in text:
        raise ReleaseOperationError("disposable PostgreSQL pytest has unexpected xpass")
    return {
        "argv": list(argv),
        "exit_code": completed.returncode,
        "junit_path": str(junit_path),
        "junit_sha256": sha256_bytes(junit_path.read_bytes()),
        "node_manifest_path": str(node_manifest_path),
        "node_manifest_sha256": sha256_bytes(node_manifest_path.read_bytes()),
        "population": population,
        "stdout_stderr_sha256": sha256_bytes(payload),
        "stdout_stderr_bytes": len(payload),
        "unexpected_skips": population["skipped"] + population["xfailed"],
        "log_path": str(log_path),
    }


def parse_pytest_junit(path: Path) -> dict[str, object]:
    """Return an exact, duplicate-free pytest population from JUnit XML."""

    try:
        root = ET.fromstring(path.read_bytes())
    except (ET.ParseError, OSError) as exc:
        raise ReleaseOperationError(f"PostgreSQL pytest JUnit is invalid: {exc}") from exc
    cases = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "testcase"
    ]
    if not cases:
        raise ReleaseOperationError("PostgreSQL pytest JUnit has zero testcases")
    nodes: list[dict[str, str]] = []
    counts = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "xfailed": 0,
    }
    seen: set[str] = set()
    for case in cases:
        classname = case.attrib.get("classname")
        name = case.attrib.get("name")
        if not classname or not name:
            raise ReleaseOperationError("PostgreSQL pytest JUnit testcase identity is absent")
        node_id = f"{classname}::{name}"
        if node_id in seen:
            raise ReleaseOperationError(
                f"PostgreSQL pytest JUnit testcase is duplicated: {node_id}"
            )
        seen.add(node_id)
        terminal = [
            child
            for child in case
            if child.tag.rsplit("}", 1)[-1] in {"failure", "error", "skipped"}
        ]
        if len(terminal) > 1:
            raise ReleaseOperationError(
                f"PostgreSQL pytest JUnit testcase has multiple outcomes: {node_id}"
            )
        if not terminal:
            outcome = "passed"
        else:
            tag = terminal[0].tag.rsplit("}", 1)[-1]
            if tag == "failure":
                outcome = "failed"
            elif tag == "error":
                outcome = "errors"
            elif terminal[0].attrib.get("type") == "pytest.xfail":
                outcome = "xfailed"
            else:
                outcome = "skipped"
        counts[outcome] += 1
        nodes.append({"node_id": node_id, "outcome": outcome})
    nodes.sort(key=lambda value: value["node_id"])
    return {
        **counts,
        "tests": len(nodes),
        "node_ids": nodes,
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

    container = DisposablePostgresContainer(process_root=output_dir / "process" / "docker-suite")
    container_cleanup: dict[str, object] | None = None
    try:
        container_identity = container.start()
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
                process_root=output_dir / "process" / "pytest",
            )
            marked_files = pg_marked_test_files(repository_root)
            _verify_pg_coverage(marked_files)
            try:
                marked = _run_pytest(
                    python=executable,
                    repository_root=repository_root,
                    env=env,
                    arguments=("-m", "pg", *marked_files),
                    log_path=output_dir / "pytest-pg-marked.log",
                    minimum_tests=MINIMUM_PG_MARKED_TESTS,
                )
                dispatch = _run_pytest(
                    python=executable,
                    repository_root=repository_root,
                    env=env,
                    arguments=DISPATCH_NODES,
                    log_path=output_dir / "pytest-pg-dispatch.log",
                    minimum_tests=len(DISPATCH_NODES),
                )
                run_migrations(Database(source_url, connect_timeout=1))
            finally:
                roles_after_pytest = role_facts(source_url)
                cleaned_roles = cleanup_roles_created_since(
                    container.url,
                    roles_before,
                )
            roles_after = role_facts(source_url)
            write_immutable(
                output_dir / "global-role-facts-before.json",
                canonical_json_bytes(roles_before),
            )
            write_immutable(
                output_dir / "global-role-facts-after-pytest.json",
                canonical_json_bytes(roles_after_pytest),
            )
            write_immutable(
                output_dir / "global-role-facts-after-cleanup.json",
                canonical_json_bytes(roles_after),
            )
            if roles_before["sha256"] != roles_after["sha256"]:
                raise ReleaseOperationError(
                    "PostgreSQL suite leaked global role changes after owned cleanup"
                )
        finally:
            drop_database(container.url, database_name)
            database_cleanup_proven = True
        if not database_cleanup_proven:
            raise ReleaseOperationError("PostgreSQL suite database cleanup is unproven")
    finally:
        container.stop()
    container_cleanup = container.cleanup_facts

    if container_cleanup is None:
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
            "cleanup": container_cleanup,
            "network_pull_allowed": False,
        },
        "admin_input_database_contacted": False,
        "canonical_database_contacted": False,
        "pytest_environment_policy": {
            "inherited_names": [
                "LANG",
                "LC_ALL",
                "PATH",
                "TZ",
                "USER",
            ],
            "owned_writable_names": [
                "HOME",
                "TMPDIR",
                "TMP",
                "TEMP",
                "XDG_CACHE_HOME",
                "PIP_CACHE_DIR",
                "UV_CACHE_DIR",
                "PYTHONPYCACHEPREFIX",
            ],
            "explicit_pytest_basetemp": True,
            "explicit_pytest_cache_dir": True,
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
        "role_facts_after_pytest_sha256": roles_after_pytest["sha256"],
        "role_facts_after_sha256": roles_after["sha256"],
        "role_facts_unchanged": True,
        "role_facts_exact_document_match": (roles_before["document"] == roles_after["document"]),
        "suite_owned_roles_removed": list(cleaned_roles),
    }
    write_immutable(receipt_path, canonical_json_bytes(receipt))
    return receipt
