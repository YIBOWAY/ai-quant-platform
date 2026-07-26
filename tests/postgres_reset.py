"""PostgreSQL reset helpers for migration-tolerant integration tests."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.storage import database as db


@contextmanager
def isolated_test_database_url(base_url: str, *, purpose: str) -> Iterator[str]:
    """Yield a fresh sibling database URL and remove the database afterwards."""

    params = conninfo_to_dict(base_url)
    base_name = params.get("dbname")
    if not base_name or not (base_name.endswith("_tmp") or "test" in base_name):
        raise ValueError(f"base URL is not a throwaway test database: {base_name!r}")
    digest = hashlib.sha256(
        f"{base_name}\0{purpose}\0{os.getpid()}\0{uuid4().hex}".encode()
    ).hexdigest()[:10]
    database_name = f"{base_name[:42]}_{purpose[:8]}_{digest}_tmp"
    maintenance_params = dict(params)
    maintenance_params["dbname"] = "postgres"
    maintenance_url = make_conninfo(**maintenance_params)
    database_params = dict(params)
    database_params["dbname"] = database_name

    with psycopg.connect(maintenance_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        yield make_conninfo(**database_params)
    finally:
        with psycopg.connect(maintenance_url, autocommit=True) as conn:
            conn.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s
                  AND pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )


def truncate_with_fk_dependents(
    database: db.Database,
    table_names: Iterable[str],
    *,
    restart_identity: bool = True,
) -> None:
    """Truncate existing roots and every FK-dependent table atomically.

    Later Agent v0.2 migrations add append-only authority tables that
    reference older Hermes tables.  PostgreSQL requires those tables to be
    included in the same ``TRUNCATE`` statement, while their ``ALWAYS``
    truncate guards must be disabled by the test database owner.  Catalog
    discovery keeps old tests compatible with databases that have applied
    only part of the migration ladder.

    Non-internal triggers are restored to their exact pre-reset mode
    (origin, always, replica, or disabled) before the transaction commits.
    """

    requested = tuple(dict.fromkeys(table_names))
    if not requested:
        return

    with database.connect() as conn, conn.transaction():
        rows = conn.execute(
            """
            WITH RECURSIVE roots(relid) AS (
                SELECT to_regclass(table_name)::oid
                FROM unnest(%s::text[]) AS requested(table_name)
                WHERE to_regclass(table_name) IS NOT NULL
            ),
            closure(relid) AS (
                SELECT relid
                FROM roots
                UNION
                SELECT constraint_row.conrelid
                FROM pg_constraint AS constraint_row
                JOIN closure AS parent
                  ON constraint_row.confrelid = parent.relid
                WHERE constraint_row.contype = 'f'
            )
            SELECT
                closure.relid,
                namespace.nspname,
                relation.relname
            FROM closure
            JOIN pg_class AS relation
              ON relation.oid = closure.relid
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE relation.relkind IN ('r', 'p')
            ORDER BY namespace.nspname, relation.relname
            """,
            (list(requested),),
        ).fetchall()
        if not rows:
            return

        relations = {
            int(relid): (str(schema_name), str(table_name))
            for relid, schema_name, table_name in rows
        }
        trigger_rows = conn.execute(
            """
            SELECT
                trigger_row.tgrelid,
                trigger_row.tgname,
                trigger_row.tgenabled
            FROM pg_trigger AS trigger_row
            WHERE trigger_row.tgrelid = ANY(%s::oid[])
              AND NOT trigger_row.tgisinternal
            ORDER BY trigger_row.tgrelid, trigger_row.tgname
            """,
            (list(relations),),
        ).fetchall()

        for relid, trigger_name, trigger_mode in trigger_rows:
            if trigger_mode == "D":
                continue
            schema_name, table_name = relations[int(relid)]
            conn.execute(
                sql.SQL("ALTER TABLE {}.{} DISABLE TRIGGER {}").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                    sql.Identifier(str(trigger_name)),
                )
            )

        truncate_statement = sql.SQL("TRUNCATE TABLE {}").format(
            sql.SQL(", ").join(
                sql.SQL("{}.{}").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                )
                for schema_name, table_name in relations.values()
            )
        )
        if restart_identity:
            truncate_statement += sql.SQL(" RESTART IDENTITY")
        conn.execute(truncate_statement)

        restore_modes = {
            "O": sql.SQL("ENABLE TRIGGER"),
            "A": sql.SQL("ENABLE ALWAYS TRIGGER"),
            "R": sql.SQL("ENABLE REPLICA TRIGGER"),
        }
        for relid, trigger_name, trigger_mode in trigger_rows:
            restore = restore_modes.get(str(trigger_mode))
            if restore is None:
                continue
            schema_name, table_name = relations[int(relid)]
            conn.execute(
                sql.SQL("ALTER TABLE {}.{} {} {}").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                    restore,
                    sql.Identifier(str(trigger_name)),
                )
            )
