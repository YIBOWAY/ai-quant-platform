"""Full disposable PostgreSQL backup/restore verification."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import psycopg
from psycopg import sql

from quant_system.ops.common import (
    CommandResult,
    ReleaseOperationError,
    canonical_json_bytes,
    ensure_private_directory,
    git_identity,
    run_command,
    sha256_file,
    utc_now,
    write_immutable,
)
from quant_system.ops.postgres_common import (
    assert_catalog_equal,
    catalog_facts,
    create_database,
    drop_database,
    role_facts,
    temporary_database_name,
    validate_loopback_connection_url,
)
from quant_system.ops.postgres_container import DisposablePostgresContainer
from quant_system.storage.database import Database, run_migrations

_AUTHORITY_ROLES = frozenset({"quant_migrator", "quant_readonly", "quant_runtime"})


def _minimal_process_environment() -> dict[str, str]:
    return {
        name: os.environ[name]
        for name in ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR", "TZ", "USER")
        if name in os.environ
    }


@dataclass(frozen=True)
class PostgresToolIdentity:
    mode: str
    dump_tool: str
    restore_tool: str
    roles_dump_tool: str
    sql_restore_tool: str
    version: str
    container: str | None
    container_image: str | None


class PostgresTools:
    def __init__(
        self,
        *,
        dump_binary: str | None,
        restore_binary: str | None,
        container: str | None,
    ) -> None:
        self._container = container
        self._docker: str | None = None
        if container:
            if not container.startswith("agent-v02-pg-") or not container.endswith("-tmp"):
                raise ReleaseOperationError(
                    "PostgreSQL tools container is outside the owned temporary namespace"
                )
            docker = shutil.which("docker")
            if docker is None:
                raise ReleaseOperationError("docker is unavailable for PostgreSQL tools")
            inspect = subprocess.run(
                [
                    docker,
                    "inspect",
                    "--format",
                    "{{.State.Running}} {{.Image}}",
                    container,
                ],
                check=False,
                capture_output=True,
                text=True,
                env=_minimal_process_environment(),
            )
            if inspect.returncode != 0:
                raise ReleaseOperationError("PostgreSQL tools container is unavailable")
            parts = inspect.stdout.strip().split()
            if len(parts) != 2 or parts[0] != "true":
                raise ReleaseOperationError("PostgreSQL tools container is not running")
            self._docker = docker
            self._image = parts[1]
            self._dump = "pg_dump"
            self._restore = "pg_restore"
            self._roles_dump = "pg_dumpall"
            self._sql_restore = "psql"
            self._mode = "docker_exec"
        else:
            dump = dump_binary or shutil.which("pg_dump")
            restore = restore_binary or shutil.which("pg_restore")
            if not dump or not restore:
                raise ReleaseOperationError(
                    "pg_dump and pg_restore are required; configure explicit binaries "
                    "or QS_AGENT_V02_PG_TOOLS_CONTAINER"
                )
            if not Path(dump).is_file() or not os.access(dump, os.X_OK):
                raise ReleaseOperationError("pg_dump binary is not executable")
            if not Path(restore).is_file() or not os.access(restore, os.X_OK):
                raise ReleaseOperationError("pg_restore binary is not executable")
            roles_dump = shutil.which("pg_dumpall")
            sql_restore = shutil.which("psql")
            if not roles_dump or not sql_restore:
                raise ReleaseOperationError("pg_dumpall and psql are required")
            self._dump = str(Path(dump).resolve())
            self._restore = str(Path(restore).resolve())
            self._roles_dump = str(Path(roles_dump).resolve())
            self._sql_restore = str(Path(sql_restore).resolve())
            self._image = None
            self._mode = "local_binaries"

    def _base(self, tool: str, *, interactive: bool = False) -> list[str]:
        if self._container is None:
            return [tool]
        assert self._docker is not None
        argv = [self._docker, "exec"]
        if interactive:
            argv.append("-i")
        for name in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"):
            argv.extend(("-e", name))
        argv.extend((self._container, tool))
        return argv

    def identity(self, env: Mapping[str, str], *, cwd: Path) -> PostgresToolIdentity:
        argv = self._base(self._dump) + ["--version"]
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=dict(env),
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise ReleaseOperationError("pg_dump --version failed")
        return PostgresToolIdentity(
            mode=self._mode,
            dump_tool=self._dump,
            restore_tool=self._restore,
            roles_dump_tool=self._roles_dump,
            sql_restore_tool=self._sql_restore,
            version=completed.stdout.strip(),
            container=self._container,
            container_image=self._image,
        )

    def dump(
        self,
        *,
        env: Mapping[str, str],
        cwd: Path,
        output: Path,
        stderr_path: Path,
    ) -> CommandResult:
        argv = self._base(self._dump) + ["-Fc", "--no-owner", "--no-privileges"]
        return run_command(
            argv,
            cwd=cwd,
            env=env,
            stdout_path=output,
            stderr_path=stderr_path,
        )

    def list_archive(
        self,
        *,
        env: Mapping[str, str],
        cwd: Path,
        archive: Path,
        stderr_path: Path,
    ) -> CommandResult:
        argv = self._base(self._restore, interactive=True) + ["--list"]
        return run_command(
            argv,
            cwd=cwd,
            env=env,
            stdin_path=archive,
            stderr_path=stderr_path,
        )

    def restore(
        self,
        *,
        env: Mapping[str, str],
        cwd: Path,
        archive: Path,
        stderr_path: Path,
    ) -> CommandResult:
        database_name = env.get("PGDATABASE")
        if not database_name:
            raise ReleaseOperationError("pg_restore target database is absent")
        argv = self._base(self._restore, interactive=True) + [
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            database_name,
        ]
        return run_command(
            argv,
            cwd=cwd,
            env=env,
            stdin_path=archive,
            stderr_path=stderr_path,
        )

    def restore_data(
        self,
        *,
        env: Mapping[str, str],
        cwd: Path,
        archive: Path,
        stderr_path: Path,
    ) -> CommandResult:
        database_name = env.get("PGDATABASE")
        if not database_name:
            raise ReleaseOperationError("pg_restore data target database is absent")
        argv = self._base(self._restore, interactive=True) + [
            "--data-only",
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            database_name,
        ]
        return run_command(
            argv,
            cwd=cwd,
            env=env,
            stdin_path=archive,
            stderr_path=stderr_path,
        )

    def dump_roles(
        self,
        *,
        env: Mapping[str, str],
        cwd: Path,
        output: Path,
        stderr_path: Path,
    ) -> CommandResult:
        argv = self._base(self._roles_dump) + [
            "--roles-only",
            "--no-role-passwords",
            "--no-comments",
            "--no-security-labels",
        ]
        return run_command(
            argv,
            cwd=cwd,
            env=env,
            stdout_path=output,
            stderr_path=stderr_path,
        )

    def restore_roles(
        self,
        *,
        env: Mapping[str, str],
        cwd: Path,
        script: Path,
        stderr_path: Path,
    ) -> CommandResult:
        database_name = env.get("PGDATABASE")
        if not database_name:
            raise ReleaseOperationError("role restore database is absent")
        argv = self._base(self._sql_restore, interactive=True) + [
            "--no-psqlrc",
            "--set=ON_ERROR_STOP=1",
            "--dbname",
            database_name,
        ]
        return run_command(
            argv,
            cwd=cwd,
            env=env,
            stdin_path=script,
            stderr_path=stderr_path,
        )


def _pg_environment(url: str, *, container_mode: bool) -> dict[str, str]:
    params = validate_loopback_connection_url(url, require_disposable=True)
    env = _minimal_process_environment()
    mapping = {
        "host": "PGHOST",
        "port": "PGPORT",
        "user": "PGUSER",
        "password": "PGPASSWORD",
        "dbname": "PGDATABASE",
    }
    for source, target in mapping.items():
        value = params.get(source)
        if value:
            env[target] = value
        else:
            env.pop(target, None)
    if container_mode:
        # Container mode is intentionally limited to a PostgreSQL server in
        # that same named container.  The host URL remains loopback-only for
        # psycopg; pg tools address the server through the container loopback.
        env["PGHOST"] = "127.0.0.1"
        env["PGPORT"] = "5432"
    return env


def _sanitized_authority_role_dump(
    *,
    source: Path,
    destination: Path,
    container_admin_role: str,
) -> dict[str, object]:
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseOperationError("PostgreSQL role dump is not UTF-8") from exc
    if re.search(r"(?i)\bPASSWORD\b", text):
        raise ReleaseOperationError("PostgreSQL role dump contains password material")
    kept: list[str] = []
    skipped_admin_lines = 0
    for line in text.splitlines(keepends=True):
        if line == f"CREATE ROLE {container_admin_role};\n" or line.startswith(
            f"ALTER ROLE {container_admin_role} WITH "
        ):
            skipped_admin_lines += 1
            continue
        kept.append(line)
    sanitized = "".join(kept)
    if re.search(rf"\b{re.escape(container_admin_role)}\b", sanitized):
        raise ReleaseOperationError("container admin leaked into authority role restore")
    created = frozenset(re.findall(r"(?m)^CREATE ROLE ([a-z][a-z0-9_]*);$", sanitized))
    altered = frozenset(
        re.findall(r"(?m)^ALTER ROLE ([a-z][a-z0-9_]*) WITH ", sanitized)
    )
    if created != _AUTHORITY_ROLES or altered != _AUTHORITY_ROLES:
        raise ReleaseOperationError("role dump does not contain the exact authority role set")
    if skipped_admin_lines != 2:
        raise ReleaseOperationError("role dump container-admin shape is unexpected")
    write_immutable(destination, sanitized.encode("utf-8"))
    return {
        "source_sha256": sha256_file(source),
        "sanitized_sha256": sha256_file(destination),
        "authority_roles": sorted(_AUTHORITY_ROLES),
        "container_admin_lines_removed": skipped_admin_lines,
        "password_material_present": False,
    }


def _restore_trigger_mode(
    conn: psycopg.Connection,
    *,
    table_name: str,
    trigger_name: str,
    mode: str,
) -> None:
    actions = {
        "O": sql.SQL("ENABLE TRIGGER"),
        "A": sql.SQL("ENABLE ALWAYS TRIGGER"),
        "R": sql.SQL("ENABLE REPLICA TRIGGER"),
        "D": sql.SQL("DISABLE TRIGGER"),
    }
    action = actions.get(mode)
    if action is None:
        raise ReleaseOperationError("unknown PostgreSQL trigger mode")
    conn.execute(
        sql.SQL("ALTER TABLE {}.{} {} {}").format(
            sql.Identifier("quant_system"),
            sql.Identifier(table_name),
            action,
            sql.Identifier(trigger_name),
        )
    )


def _prepare_exact_data_replay(url: str) -> list[tuple[str, str, str]]:
    """Empty restored tables while preserving exact user-trigger modes."""

    with psycopg.connect(url, autocommit=True) as conn:
        table_names = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT relation.relname
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'quant_system'
                  AND relation.relkind IN ('r', 'p')
                ORDER BY relation.relname
                """
            ).fetchall()
        ]
        trigger_modes = [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in conn.execute(
                """
                SELECT relation.relname, trigger_row.tgname, trigger_row.tgenabled
                FROM pg_trigger AS trigger_row
                JOIN pg_class AS relation
                  ON relation.oid = trigger_row.tgrelid
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'quant_system'
                  AND NOT trigger_row.tgisinternal
                ORDER BY relation.relname, trigger_row.tgname
                """
            ).fetchall()
        ]
        for table_name in table_names:
            conn.execute(
                sql.SQL("ALTER TABLE {}.{} DISABLE TRIGGER USER").format(
                    sql.Identifier("quant_system"),
                    sql.Identifier(table_name),
                )
            )
        if table_names:
            conn.execute("SET session_replication_role = replica")
            conn.execute(
                sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(
                        sql.SQL("{}.{}").format(
                            sql.Identifier("quant_system"),
                            sql.Identifier(name),
                        )
                        for name in table_names
                    )
                )
            )
            conn.execute("RESET session_replication_role")
    return trigger_modes


def _restore_user_trigger_modes(
    url: str,
    trigger_modes: list[tuple[str, str, str]],
) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        for table_name, trigger_name, mode in trigger_modes:
            _restore_trigger_mode(
                conn,
                table_name=table_name,
                trigger_name=trigger_name,
                mode=mode,
            )


def _verify_backup_restore_between_containers(
    *,
    source_url: str,
    destination_admin_url: str,
    output_dir: Path,
    repository_root: Path,
    source_tools_container: str,
    destination_tools_container: str,
    source_container_admin_role: str,
    destination_container_admin_role: str,
) -> dict[str, object]:
    """Restore one disposable cluster into a second independent cluster."""

    source_params = validate_loopback_connection_url(source_url, require_disposable=True)
    source_name = source_params["dbname"]
    validate_loopback_connection_url(destination_admin_url, require_disposable=True)
    if source_tools_container == destination_tools_container:
        raise ReleaseOperationError("backup/restore requires two independent containers")
    if source_container_admin_role != destination_container_admin_role:
        raise ReleaseOperationError("container admin role identities do not match")
    output_dir = ensure_private_directory(output_dir)
    dump_path = output_dir / "quant-system-authority.dump"
    raw_roles_path = output_dir / "source-roles.sql"
    restored_roles_path = output_dir / "restored-authority-roles.sql"
    receipt_path = output_dir / "backup-restore-receipt.json"
    if any(
        path.exists()
        for path in (dump_path, raw_roles_path, restored_roles_path, receipt_path)
    ):
        raise ReleaseOperationError("backup/restore output paths already exist")

    source_tools = PostgresTools(
        dump_binary=None,
        restore_binary=None,
        container=source_tools_container,
    )
    destination_tools = PostgresTools(
        dump_binary=None,
        restore_binary=None,
        container=destination_tools_container,
    )
    source_env = _pg_environment(source_url, container_mode=True)
    source_tool_identity = source_tools.identity(source_env, cwd=repository_root)
    destination_admin_env = _pg_environment(
        destination_admin_url,
        container_mode=True,
    )
    destination_tool_identity = destination_tools.identity(
        destination_admin_env,
        cwd=repository_root,
    )
    source_catalog = catalog_facts(source_url)
    source_roles = role_facts(
        source_url,
        excluded_roles=frozenset({source_container_admin_role}),
    )
    source_role_names = {
        str(row[0])
        for row in source_roles["document"]["roles"]  # type: ignore[index]
    }
    if source_role_names != _AUTHORITY_ROLES:
        raise ReleaseOperationError("source cluster has an unexpected authority role set")

    dump_result = source_tools.dump(
        env=source_env,
        cwd=repository_root,
        output=dump_path,
        stderr_path=output_dir / "pg-dump.stderr.log",
    )
    if dump_result.exit_code != 0 or not dump_path.is_file() or dump_path.stat().st_size == 0:
        dump_path.unlink(missing_ok=True)
        raise ReleaseOperationError("pg_dump failed closed")
    dump_path.chmod(0o600)
    list_result = source_tools.list_archive(
        env=source_env,
        cwd=repository_root,
        archive=dump_path,
        stderr_path=output_dir / "pg-restore-list.stderr.log",
    )
    if list_result.exit_code != 0:
        raise ReleaseOperationError("pg_restore --list rejected the archive")

    roles_dump_result = source_tools.dump_roles(
        env=source_env,
        cwd=repository_root,
        output=raw_roles_path,
        stderr_path=output_dir / "pg-dumpall-roles.stderr.log",
    )
    if (
        roles_dump_result.exit_code != 0
        or not raw_roles_path.is_file()
        or raw_roles_path.stat().st_size == 0
    ):
        raw_roles_path.unlink(missing_ok=True)
        raise ReleaseOperationError("pg_dumpall --roles-only failed closed")
    raw_roles_path.chmod(0o600)
    roles_sanitization = _sanitized_authority_role_dump(
        source=raw_roles_path,
        destination=restored_roles_path,
        container_admin_role=source_container_admin_role,
    )
    roles_restore_result = destination_tools.restore_roles(
        env=destination_admin_env,
        cwd=repository_root,
        script=restored_roles_path,
        stderr_path=output_dir / "psql-restore-roles.stderr.log",
    )
    if roles_restore_result.exit_code != 0:
        raise ReleaseOperationError("authority role restore failed closed")
    destination_roles_before_database = role_facts(
        destination_admin_url,
        excluded_roles=frozenset({destination_container_admin_role}),
    )
    if source_roles["sha256"] != destination_roles_before_database["sha256"]:
        raise ReleaseOperationError("authority role restore changed attributes or memberships")

    destination_name = temporary_database_name(purpose="restore")
    destination_url = ""
    destination_created = False
    destination_dropped = False
    pending_receipt: dict[str, object] | None = None
    try:
        destination_url = create_database(destination_admin_url, destination_name)
        destination_created = True
        destination_env = _pg_environment(
            destination_url,
            container_mode=True,
        )
        restore_result = destination_tools.restore(
            env=destination_env,
            cwd=repository_root,
            archive=dump_path,
            stderr_path=output_dir / "pg-restore.stderr.log",
        )
        if restore_result.exit_code != 0:
            raise ReleaseOperationError("pg_restore failed closed")

        # --no-owner/--no-privileges is a mandatory secret-safe portable
        # archive contract. Replaying the final idempotent migrations restores
        # repository-defined grants/role bindings before exact comparison.
        run_migrations(Database(destination_url, connect_timeout=1))
        trigger_modes = _prepare_exact_data_replay(destination_url)
        replay_env = dict(destination_env)
        replay_env["PGOPTIONS"] = "-c session_replication_role=replica"
        data_restore_result = destination_tools.restore_data(
            env=replay_env,
            cwd=repository_root,
            archive=dump_path,
            stderr_path=output_dir / "pg-restore-data.stderr.log",
        )
        if data_restore_result.exit_code != 0:
            raise ReleaseOperationError("pg_restore data replay failed closed")
        _restore_user_trigger_modes(destination_url, trigger_modes)
        restored_catalog = catalog_facts(destination_url)
        restored_roles = role_facts(
            destination_url,
            excluded_roles=frozenset({destination_container_admin_role}),
        )
        write_immutable(
            output_dir / "source-catalog.json",
            canonical_json_bytes(source_catalog),
        )
        write_immutable(
            output_dir / "restored-catalog.json",
            canonical_json_bytes(restored_catalog),
        )
        write_immutable(
            output_dir / "source-role-facts.json",
            canonical_json_bytes(source_roles),
        )
        write_immutable(
            output_dir / "restored-role-facts.json",
            canonical_json_bytes(restored_roles),
        )
        assert_catalog_equal(source_catalog, restored_catalog)
        if source_roles["sha256"] != restored_roles["sha256"]:
            raise ReleaseOperationError("runtime role attributes or memberships changed")
        source_catalog_summary = {
            key: value for key, value in source_catalog.items() if key != "schema_rows"
        }
        restored_catalog_summary = {
            key: value for key, value in restored_catalog.items() if key != "schema_rows"
        }
        source_role_summary = {
            key: value for key, value in source_roles.items() if key != "document"
        }
        restored_role_summary = {
            key: value for key, value in restored_roles.items() if key != "document"
        }

        pending_receipt = {
            "schema_version": "agent-v0.2.2-postgres-backup-restore.v1",
            "status": "verified_pending_container_cleanup",
            "comparison_completed_at": utc_now(),
            "source_database": source_name,
            "destination_database": destination_name,
            "source_is_disposable": True,
            "destination_is_disposable": True,
            "dump": {
                "path": str(dump_path),
                "bytes": dump_path.stat().st_size,
                "sha256": sha256_file(dump_path),
                "format": "custom",
                "flags": ["-Fc", "--no-owner", "--no-privileges"],
                "command": asdict(dump_result),
                "archive_list_command": asdict(list_result),
            },
            "roles": {
                "source_dump": asdict(roles_dump_result),
                "source_dump_bytes": raw_roles_path.stat().st_size,
                "sanitization": roles_sanitization,
                "destination_restore": asdict(roles_restore_result),
                "restored_before_database_sha256": destination_roles_before_database[
                    "sha256"
                ],
            },
            "restore": {
                "flags": [
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-privileges",
                ],
                "command": asdict(restore_result),
                "post_restore_privilege_reconciliation": "final_idempotent_migrations",
                "exact_data_replay": {
                    "source": "same custom archive",
                    "command": asdict(data_restore_result),
                    "session_replication_role": "replica",
                    "user_trigger_modes_restored": len(trigger_modes),
                },
            },
            "tools": {
                "source": asdict(source_tool_identity),
                "destination": asdict(destination_tool_identity),
                "independent_containers": True,
            },
            "source_catalog": source_catalog_summary,
            "restored_catalog": restored_catalog_summary,
            "source_role_facts": source_role_summary,
            "restored_role_facts": restored_role_summary,
            "exact_catalog_match": True,
            "exact_role_facts_match": True,
        }
    finally:
        if destination_created:
            drop_database(destination_admin_url, destination_name)
            destination_dropped = True
    if pending_receipt is None:
        raise ReleaseOperationError("backup/restore comparison did not complete")
    if not destination_dropped:
        raise ReleaseOperationError("destination database cleanup was not proven")
    pending_receipt["cleanup"] = {
        "destination_database_dropped": True,
        "source_database_dropped": False,
        "source_container_removed": False,
        "destination_container_removed": False,
        "success_receipt_written_after_all_cleanup": False,
    }
    return pending_receipt


def seed_backup_probe(url: str) -> None:
    """Add non-authority disposable facts proving row and sequence recovery."""

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            """
            CREATE SEQUENCE IF NOT EXISTS quant_system.agent_v02_backup_probe_seq
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quant_system.agent_v02_backup_probe (
                probe_id bigint PRIMARY KEY
                    DEFAULT nextval('quant_system.agent_v02_backup_probe_seq'),
                payload text NOT NULL
            )
            """
        )
        conn.execute(
            """
            ALTER SEQUENCE quant_system.agent_v02_backup_probe_seq
            OWNED BY quant_system.agent_v02_backup_probe.probe_id
            """
        )
        conn.execute(
            """
            INSERT INTO quant_system.agent_v02_backup_probe (payload)
            SELECT 'agent-v0.2.2-disposable-backup-proof'
            WHERE NOT EXISTS (
                SELECT 1
                FROM quant_system.agent_v02_backup_probe
            )
            """
        )


def verify_backup_restore_in_owned_container(
    *,
    output_dir: Path,
    repository_root: Path,
) -> dict[str, object]:
    """Provision source and destination as independent disposable clusters."""

    repository_identity = git_identity(repository_root.resolve(), require_clean=True)
    output_dir = ensure_private_directory(output_dir)
    command_receipt_path = output_dir / "owned-container-command-receipt.json"
    if command_receipt_path.exists():
        raise ReleaseOperationError("owned-container command receipt already exists")

    source_container = DisposablePostgresContainer()
    destination_container = DisposablePostgresContainer()
    source_identity = source_container.start()
    source_container_removed = False
    destination_container_removed = False
    source_dropped = False
    receipt: dict[str, object] | None = None
    try:
        destination_identity = destination_container.start()
        try:
            if source_identity.name == destination_identity.name:
                raise ReleaseOperationError("disposable clusters are not independent")
            source_name = temporary_database_name(purpose="backup_source")
            source_url = create_database(source_container.url, source_name)
            try:
                run_migrations(Database(source_url, connect_timeout=1))
                seed_backup_probe(source_url)
                run_migrations(Database(source_url, connect_timeout=1))
                receipt = _verify_backup_restore_between_containers(
                    source_url=source_url,
                    destination_admin_url=destination_container.url,
                    output_dir=output_dir,
                    repository_root=repository_root,
                    source_tools_container=source_identity.name,
                    destination_tools_container=destination_identity.name,
                    source_container_admin_role=source_identity.user,
                    destination_container_admin_role=destination_identity.user,
                )
            finally:
                drop_database(source_container.url, source_name)
                source_dropped = True
        finally:
            destination_container.stop()
            destination_container_removed = True
    finally:
        source_container.stop()
        source_container_removed = True
    if receipt is None:
        raise ReleaseOperationError("backup/restore drill did not complete")
    if not all(
        (source_dropped, source_container_removed, destination_container_removed)
    ):
        raise ReleaseOperationError("backup/restore cleanup is unproven")
    receipt["status"] = "passed"
    receipt["completed_at"] = utc_now()
    receipt["cleanup"] = {
        "destination_database_dropped": True,
        "source_database_dropped": True,
        "source_container_removed": True,
        "destination_container_removed": True,
        "success_receipt_written_after_all_cleanup": True,
    }
    write_immutable(
        output_dir / "backup-restore-receipt.json",
        canonical_json_bytes(receipt),
    )
    command_receipt = {
        "schema_version": "agent-v0.2.2-owned-postgres-backup-command.v1",
        "status": "passed",
        "completed_at": utc_now(),
        "repository": asdict(repository_identity),
        "backup_restore": receipt,
        "backup_restore_receipt_sha256": sha256_file(
            output_dir / "backup-restore-receipt.json"
        ),
        "owned_containers": {
            "source": {
                **asdict(source_identity),
                "removed": True,
            },
            "destination": {
                **asdict(destination_identity),
                "removed": True,
            },
            "independent": True,
            "network_pull_allowed": False,
        },
        "source_database_dropped": True,
        "success_receipt_written_after_all_cleanup": True,
    }
    write_immutable(
        command_receipt_path,
        canonical_json_bytes(command_receipt),
    )
    return command_receipt
