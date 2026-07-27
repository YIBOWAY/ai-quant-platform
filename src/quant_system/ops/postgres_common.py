"""Disposable PostgreSQL safety and catalog helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.ops.common import ReleaseOperationError, canonical_json_bytes
from quant_system.storage import database as database_module
from quant_system.storage.database import Database, schema_fingerprint

_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


def validate_loopback_connection_url(url: str, *, require_disposable: bool) -> dict[str, str]:
    try:
        params = conninfo_to_dict(url)
    except Exception as exc:
        raise ReleaseOperationError("PostgreSQL connection URL is invalid") from exc
    host = params.get("host", "")
    database = params.get("dbname", "")
    if params.get("hostaddr") or params.get("service"):
        raise ReleaseOperationError("PostgreSQL connection indirection is forbidden")
    if host not in _LOOPBACK_HOSTS:
        raise ReleaseOperationError("PostgreSQL host must be a literal loopback IP")
    if not database or _SAFE_NAME.fullmatch(database) is None:
        raise ReleaseOperationError("PostgreSQL database name is invalid")
    if require_disposable and not (
        database.startswith("agent_v02_") and database.endswith("_tmp")
    ):
        raise ReleaseOperationError("PostgreSQL database is outside the owned temporary namespace")
    return params


def temporary_database_name(*, purpose: str) -> str:
    normalized = re.sub("[^a-z0-9]+", "_", purpose.lower()).strip("_")[:20]
    if not normalized:
        raise ReleaseOperationError("temporary database purpose is invalid")
    return f"agent_v02_{normalized}_{uuid4().hex[:12]}_tmp"


def maintenance_url(admin_url: str) -> str:
    params = validate_loopback_connection_url(admin_url, require_disposable=False)
    params["dbname"] = "postgres"
    return make_conninfo(**params)


def database_url(admin_url: str, database_name: str) -> str:
    if _SAFE_NAME.fullmatch(database_name) is None:
        raise ReleaseOperationError("temporary database name is unsafe")
    if not database_name.startswith("agent_v02_") or not database_name.endswith("_tmp"):
        raise ReleaseOperationError("temporary database name is outside the owned namespace")
    params = validate_loopback_connection_url(admin_url, require_disposable=False)
    params["dbname"] = database_name
    return make_conninfo(**params)


def create_database(admin_url: str, database_name: str) -> str:
    target_url = database_url(admin_url, database_name)
    with psycopg.connect(maintenance_url(admin_url), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (database_name,),
        ).fetchone()
        if exists is not None:
            raise ReleaseOperationError("refusing to reuse an existing temporary database")
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database_name))
        )
    return target_url


def drop_database(admin_url: str, database_name: str) -> None:
    if not database_name.startswith("agent_v02_") or not database_name.endswith("_tmp"):
        raise ReleaseOperationError("refusing to drop outside the owned temporary namespace")
    with psycopg.connect(maintenance_url(admin_url), autocommit=True) as conn:
        conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s
              AND pid <> pg_backend_pid()
            """,
            (database_name,),
        )
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))
        remains = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (database_name,),
        ).fetchone()
        if remains is not None:
            raise ReleaseOperationError("temporary database drop did not complete")


def role_facts(
    url: str,
    *,
    excluded_roles: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Read global non-system role facts without password material."""

    with psycopg.connect(url, autocommit=True) as conn:
        roles = conn.execute(
            """
            SELECT
                rolname,
                rolsuper,
                rolinherit,
                rolcreaterole,
                rolcreatedb,
                rolcanlogin,
                rolreplication,
                rolbypassrls,
                rolconnlimit,
                COALESCE(rolvaliduntil::text, '')
            FROM pg_roles
            WHERE rolname !~ '^pg_'
            ORDER BY rolname
            """
        ).fetchall()
        memberships = conn.execute(
            """
            SELECT parent.rolname, member.rolname, membership.admin_option
            FROM pg_auth_members AS membership
            JOIN pg_roles AS parent ON parent.oid = membership.roleid
            JOIN pg_roles AS member ON member.oid = membership.member
            WHERE parent.rolname !~ '^pg_'
              AND member.rolname !~ '^pg_'
            ORDER BY parent.rolname, member.rolname, membership.admin_option
            """
        ).fetchall()
    roles = [row for row in roles if str(row[0]) not in excluded_roles]
    memberships = [
        row
        for row in memberships
        if str(row[0]) not in excluded_roles and str(row[1]) not in excluded_roles
    ]
    document = {
        "roles": [list(row) for row in roles],
        "memberships": [list(row) for row in memberships],
    }
    return {
        "count": len(roles),
        "membership_count": len(memberships),
        "sha256": hashlib.sha256(canonical_json_bytes(document)).hexdigest(),
        "document": document,
    }


def _table_rows(conn: psycopg.Connection, table_name: str) -> tuple[int, str]:
    rows = conn.execute(
        sql.SQL(
            "SELECT to_jsonb(row_value)::text "
            "FROM {}.{} AS row_value "
            "ORDER BY to_jsonb(row_value)::text"
        ).format(sql.Identifier("quant_system"), sql.Identifier(table_name))
    ).fetchall()
    digest = hashlib.sha256()
    for (row_text,) in rows:
        digest.update(str(row_text).encode("utf-8"))
        digest.update(b"\n")
    return len(rows), digest.hexdigest()


def catalog_facts(url: str) -> dict[str, object]:
    database = Database(url, connect_timeout=1, failure_cooldown_seconds=0)
    fingerprint = schema_fingerprint(database)
    if fingerprint in {"<db-disabled>", "<unavailable>"}:
        raise ReleaseOperationError("quant_system schema fingerprint is unavailable")
    with psycopg.connect(url, autocommit=True) as conn:
        schema_rows = sorted(
            [
                ["" if value is None else str(value) for value in row]
                for row in conn.execute(
                    database_module._SCHEMA_FINGERPRINT_SQL,  # noqa: SLF001
                    ("quant_system",),
                ).fetchall()
            ]
        )
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
                  AND NOT relation.relispartition
                ORDER BY relation.relname
                """
            ).fetchall()
        ]
        tables = {
            name: {
                "row_count": (facts := _table_rows(conn, name))[0],
                "rows_sha256": facts[1],
            }
            for name in table_names
        }
        sequence_rows = conn.execute(
            """
            SELECT
                relation.relname,
                sequence.seqstart,
                sequence.seqincrement,
                sequence.seqmax,
                sequence.seqmin,
                sequence.seqcache,
                sequence.seqcycle
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_sequence AS sequence
              ON sequence.seqrelid = relation.oid
            WHERE namespace.nspname = 'quant_system'
            ORDER BY relation.relname
            """
        ).fetchall()
        sequences: dict[str, object] = {}
        for row in sequence_rows:
            name = str(row[0])
            state = conn.execute(
                sql.SQL("SELECT last_value, is_called FROM {}.{}").format(
                    sql.Identifier("quant_system"),
                    sql.Identifier(name),
                )
            ).fetchone()
            sequences[name] = {
                "definition": list(row[1:]),
                "last_value": state[0] if state is not None else None,
                "is_called": state[1] if state is not None else None,
            }
    tables_digest = hashlib.sha256(canonical_json_bytes(tables)).hexdigest()
    sequences_digest = hashlib.sha256(canonical_json_bytes(sequences)).hexdigest()
    return {
        "schema_fingerprint": fingerprint,
        "schema_rows": schema_rows,
        "table_count": len(tables),
        "total_row_count": sum(
            int(value["row_count"])
            for value in tables.values()  # type: ignore[index]
        ),
        "tables_sha256": tables_digest,
        "sequence_count": len(sequences),
        "sequences_sha256": sequences_digest,
        "tables": tables,
        "sequences": sequences,
    }


@dataclass(frozen=True)
class DatabaseHandle:
    name: str
    url: str


def assert_catalog_equal(source: dict[str, object], restored: dict[str, object]) -> None:
    fields = (
        "schema_fingerprint",
        "table_count",
        "total_row_count",
        "tables_sha256",
        "sequence_count",
        "sequences_sha256",
    )
    mismatches = [field for field in fields if source[field] != restored[field]]
    if mismatches:
        raise ReleaseOperationError("backup/restore catalog mismatch: " + ",".join(mismatches))
