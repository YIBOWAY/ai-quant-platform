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
_SETTING_NAME = re.compile(r"^[a-z][a-z0-9_.]*$")
_LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
_DATABASE_PRIVILEGES = frozenset({"CONNECT", "CREATE", "TEMPORARY"})
SUITE_OWNED_TEST_ROLES = frozenset(
    {
        "aqp_agent_workspace_runtime_test",
        "aqp_connector_liveness_readonly_test",
        "aqp_connector_liveness_runtime_test",
    }
)


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
    if require_disposable and not (database.startswith("agent_v02_") and database.endswith("_tmp")):
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


def _role_rows_by_name(facts: dict[str, object]) -> dict[str, list[object]]:
    document = facts.get("document")
    if not isinstance(document, dict):
        raise ReleaseOperationError("PostgreSQL role facts document is malformed")
    rows = document.get("roles")
    if not isinstance(rows, list):
        raise ReleaseOperationError("PostgreSQL role facts rows are malformed")
    roles: dict[str, list[object]] = {}
    for row in rows:
        if not isinstance(row, list) or not row:
            raise ReleaseOperationError("PostgreSQL role facts row is malformed")
        name = str(row[0])
        if _SAFE_NAME.fullmatch(name) is None:
            raise ReleaseOperationError("PostgreSQL role name is unsafe")
        if name in roles:
            raise ReleaseOperationError("PostgreSQL role facts contain a duplicate role")
        roles[name] = row
    return roles


def _membership_rows(facts: dict[str, object]) -> frozenset[tuple[object, ...]]:
    document = facts.get("document")
    if not isinstance(document, dict):
        raise ReleaseOperationError("PostgreSQL role facts document is malformed")
    rows = document.get("memberships")
    if not isinstance(rows, list):
        raise ReleaseOperationError("PostgreSQL membership facts rows are malformed")
    memberships: set[tuple[object, ...]] = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != 6:
            raise ReleaseOperationError("PostgreSQL membership facts row is malformed")
        if any(_SAFE_NAME.fullmatch(str(name)) is None for name in row[:3]):
            raise ReleaseOperationError("PostgreSQL membership role name is unsafe")
        memberships.add(tuple(row))
    return frozenset(memberships)


def cleanup_roles_created_since(
    admin_url: str,
    baseline: dict[str, object],
) -> tuple[str, ...]:
    """Remove only roles introduced inside an owned disposable cluster.

    PostgreSQL roles and memberships are cluster-global.  Some otherwise valid
    integration tests leave a dedicated login behind, so the canonical suite
    removes the exact post-baseline role-name delta in every connectable
    database before comparing the complete global facts.  Existing roles are
    never repaired or rewritten: any mutation to one remains visible and makes
    the final exact comparison fail closed.
    """

    params = validate_loopback_connection_url(admin_url, require_disposable=True)
    admin_role = params.get("user", "")
    if _SAFE_NAME.fullmatch(admin_role) is None:
        raise ReleaseOperationError("disposable PostgreSQL admin role is unsafe")
    current = role_facts(admin_url)
    baseline_roles = _role_rows_by_name(baseline)
    current_roles = _role_rows_by_name(current)
    missing = sorted(set(baseline_roles).difference(current_roles))
    mutated = sorted(
        name
        for name in set(baseline_roles).intersection(current_roles)
        if baseline_roles[name] != current_roles[name]
    )
    if missing or mutated:
        raise ReleaseOperationError(
            "PostgreSQL baseline roles changed before cleanup: "
            f"missing={','.join(missing) or '<none>'};"
            f"mutated={','.join(mutated) or '<none>'}"
        )
    introduced = tuple(sorted(set(current_roles).difference(baseline_roles)))
    unexpected = sorted(set(introduced).difference(SUITE_OWNED_TEST_ROLES))
    if unexpected:
        raise ReleaseOperationError(
            "PostgreSQL introduced roles are not suite-owned: " + ",".join(unexpected)
        )
    baseline_memberships = _membership_rows(baseline)
    current_memberships = _membership_rows(current)
    missing_memberships = baseline_memberships.difference(current_memberships)
    unexpected_memberships = {
        row
        for row in current_memberships.difference(baseline_memberships)
        if not any(str(role_name) in introduced for role_name in row[:2])
    }
    if missing_memberships or unexpected_memberships:
        raise ReleaseOperationError("PostgreSQL baseline memberships changed before cleanup")
    if not introduced:
        return ()
    if admin_role in introduced:
        raise ReleaseOperationError("refusing to clean the disposable cluster admin role")

    with psycopg.connect(admin_url, autocommit=True) as conn:
        identity = conn.execute("SELECT current_user").fetchone()
        if identity is None or str(identity[0]) != admin_role:
            raise ReleaseOperationError("disposable PostgreSQL admin identity mismatch")
        databases = tuple(
            str(row[0])
            for row in conn.execute(
                """
                SELECT datname
                FROM pg_database
                WHERE datallowconn
                  AND NOT datistemplate
                ORDER BY datname
                """
            ).fetchall()
        )
        conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE usename = ANY(%s)
              AND pid <> pg_backend_pid()
            """,
            (list(introduced),),
        )

    for database_name in databases:
        database_params = dict(params)
        database_params["dbname"] = database_name
        with psycopg.connect(make_conninfo(**database_params), autocommit=True) as conn:
            for role_name in introduced:
                conn.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(role_name)))

    with psycopg.connect(admin_url, autocommit=True) as conn:
        for role_name in introduced:
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))

    final = role_facts(admin_url)
    if baseline.get("sha256") != final.get("sha256"):
        raise ReleaseOperationError(
            "PostgreSQL global role facts differ after suite-owned role cleanup"
        )
    return introduced


def role_facts(
    url: str,
    *,
    excluded_roles: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Read complete global role and membership facts without password material."""

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
                COALESCE(rolvaliduntil::text, ''),
                COALESCE(rolconfig, ARRAY[]::text[])
            FROM pg_roles
            ORDER BY rolname
            """
        ).fetchall()
        memberships = conn.execute(
            """
            SELECT
                parent.rolname,
                member.rolname,
                grantor.rolname,
                membership.admin_option,
                membership.inherit_option,
                membership.set_option
            FROM pg_auth_members AS membership
            JOIN pg_roles AS parent ON parent.oid = membership.roleid
            JOIN pg_roles AS member ON member.oid = membership.member
            JOIN pg_roles AS grantor ON grantor.oid = membership.grantor
            ORDER BY
                parent.rolname,
                member.rolname,
                grantor.rolname,
                membership.admin_option,
                membership.inherit_option,
                membership.set_option
            """
        ).fetchall()
    roles = [
        (*row[:-1], sorted(str(value) for value in row[-1]))
        for row in roles
        if str(row[0]) not in excluded_roles
    ]
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


def database_authority_facts(url: str) -> dict[str, object]:
    """Read normalized current-database owner, ACL, and scoped settings facts."""

    validate_loopback_connection_url(url, require_disposable=True)
    with psycopg.connect(url, autocommit=True) as conn:
        database_row = conn.execute(
            """
            SELECT
                owner.rolname,
                database_row.datallowconn,
                database_row.datconnlimit
            FROM pg_database AS database_row
            JOIN pg_roles AS owner ON owner.oid = database_row.datdba
            WHERE database_row.datname = current_database()
            """
        ).fetchone()
        if database_row is None:
            raise ReleaseOperationError("current PostgreSQL database authority is absent")
        acl_rows = conn.execute(
            """
            SELECT
                grantor.rolname,
                CASE
                    WHEN access.grantee = 0 THEN 'PUBLIC'
                    ELSE grantee.rolname
                END,
                access.privilege_type,
                access.is_grantable
            FROM pg_database AS database_row
            CROSS JOIN LATERAL aclexplode(
                COALESCE(
                    database_row.datacl,
                    acldefault('d', database_row.datdba)
                )
            ) AS access
            JOIN pg_roles AS grantor ON grantor.oid = access.grantor
            LEFT JOIN pg_roles AS grantee ON grantee.oid = access.grantee
            WHERE database_row.datname = current_database()
            ORDER BY
                grantor.rolname,
                CASE
                    WHEN access.grantee = 0 THEN 'PUBLIC'
                    ELSE grantee.rolname
                END,
                access.privilege_type,
                access.is_grantable
            """
        ).fetchall()
        setting_rows = conn.execute(
            """
            SELECT
                CASE
                    WHEN setting.setrole = 0 THEN 'database'
                    ELSE 'role'
                END,
                COALESCE(role_row.rolname, ''),
                config.value
            FROM pg_db_role_setting AS setting
            LEFT JOIN pg_roles AS role_row ON role_row.oid = setting.setrole
            CROSS JOIN LATERAL unnest(setting.setconfig) AS config(value)
            WHERE setting.setdatabase = (
                SELECT oid
                FROM pg_database
                WHERE datname = current_database()
            )
            ORDER BY
                CASE
                    WHEN setting.setrole = 0 THEN 'database'
                    ELSE 'role'
                END,
                COALESCE(role_row.rolname, ''),
                config.value
            """
        ).fetchall()
    owner = str(database_row[0])
    if _SAFE_NAME.fullmatch(owner) is None:
        raise ReleaseOperationError("PostgreSQL database owner is unsafe")
    acl = [list(row) for row in acl_rows]
    settings = [list(row) for row in setting_rows]
    document = {
        "database": {
            "owner": owner,
            "allow_connections": bool(database_row[1]),
            "connection_limit": int(database_row[2]),
        },
        "acl": acl,
        "settings": settings,
    }
    return {
        "acl_count": len(acl),
        "setting_count": len(settings),
        "sha256": hashlib.sha256(canonical_json_bytes(document)).hexdigest(),
        "document": document,
    }


def _validated_database_authority(
    facts: dict[str, object],
) -> tuple[str, bool, int, list[list[object]], list[list[object]]]:
    document = facts.get("document")
    if not isinstance(document, dict):
        raise ReleaseOperationError("PostgreSQL database authority document is malformed")
    database = document.get("database")
    acl = document.get("acl")
    settings = document.get("settings")
    if (
        not isinstance(database, dict)
        or not isinstance(acl, list)
        or not isinstance(settings, list)
    ):
        raise ReleaseOperationError("PostgreSQL database authority facts are malformed")
    owner = database.get("owner")
    allow_connections = database.get("allow_connections")
    connection_limit = database.get("connection_limit")
    if not isinstance(owner, str) or _SAFE_NAME.fullmatch(owner) is None:
        raise ReleaseOperationError("PostgreSQL database authority owner is unsafe")
    if not isinstance(allow_connections, bool) or not isinstance(connection_limit, int):
        raise ReleaseOperationError("PostgreSQL database authority options are malformed")
    if not allow_connections or connection_limit < -1:
        raise ReleaseOperationError("PostgreSQL authority drill requires a connectable database")
    acl_tuples: list[tuple[object, ...]] = []
    for row in acl:
        if not isinstance(row, list) or len(row) != 4:
            raise ReleaseOperationError("PostgreSQL database ACL row is malformed")
        grantor, grantee, privilege, grantable = row
        if (
            not isinstance(grantor, str)
            or _SAFE_NAME.fullmatch(grantor) is None
            or grantor != owner
        ):
            raise ReleaseOperationError(
                "PostgreSQL database ACL has an unsupported non-owner grantor"
            )
        if not isinstance(grantee, str) or (
            grantee != "PUBLIC" and _SAFE_NAME.fullmatch(grantee) is None
        ):
            raise ReleaseOperationError("PostgreSQL database ACL grantee is unsafe")
        if privilege not in _DATABASE_PRIVILEGES or not isinstance(grantable, bool):
            raise ReleaseOperationError("PostgreSQL database ACL privilege is malformed")
        acl_tuples.append(tuple(row))
    if len(set(acl_tuples)) != len(acl_tuples) or acl_tuples != sorted(acl_tuples):
        raise ReleaseOperationError("PostgreSQL database ACL rows are not canonical")
    setting_tuples: list[tuple[object, ...]] = []
    for row in settings:
        if not isinstance(row, list) or len(row) != 3:
            raise ReleaseOperationError("PostgreSQL database setting row is malformed")
        scope, role_name, expression = row
        if scope not in {"database", "role"} or not isinstance(role_name, str):
            raise ReleaseOperationError("PostgreSQL database setting scope is malformed")
        if scope == "database" and role_name:
            raise ReleaseOperationError("database-scoped setting has an unexpected role")
        if scope == "role" and _SAFE_NAME.fullmatch(role_name) is None:
            raise ReleaseOperationError("role-scoped database setting role is unsafe")
        if not isinstance(expression, str) or "=" not in expression:
            raise ReleaseOperationError("PostgreSQL database setting is malformed")
        setting_name, _value = expression.split("=", 1)
        if _SETTING_NAME.fullmatch(setting_name) is None:
            raise ReleaseOperationError("PostgreSQL database setting name is unsafe")
        setting_tuples.append(tuple(row))
    if len(set(setting_tuples)) != len(setting_tuples) or setting_tuples != sorted(setting_tuples):
        raise ReleaseOperationError("PostgreSQL database settings are not canonical")
    expected_sha256 = hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    if (
        facts.get("sha256") != expected_sha256
        or facts.get("acl_count") != len(acl)
        or facts.get("setting_count") != len(settings)
    ):
        raise ReleaseOperationError("PostgreSQL database authority digest is invalid")
    return owner, allow_connections, connection_limit, acl, settings


def restore_database_authority(
    url: str,
    source_facts: dict[str, object],
) -> dict[str, object]:
    """Reconcile one owned destination database to exact normalized authority facts."""

    params = validate_loopback_connection_url(url, require_disposable=True)
    database_name = params["dbname"]
    owner, allow_connections, connection_limit, acl, settings = _validated_database_authority(
        source_facts
    )
    current = database_authority_facts(url)
    _current_owner, _current_allow, _current_limit, current_acl, current_settings = (
        _validated_database_authority(current)
    )
    with psycopg.connect(url, autocommit=True) as conn:
        identity = conn.execute("SELECT current_database(), current_user").fetchone()
        if identity is None or tuple(str(value) for value in identity) != (
            database_name,
            params.get("user", ""),
        ):
            raise ReleaseOperationError("PostgreSQL authority restore identity mismatch")
        conn.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(database_name),
                sql.Identifier(owner),
            )
        )
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(owner)))
        grantees = {str(row[1]) for row in (*current_acl, *acl)}
        for grantee in sorted(grantees):
            target = sql.SQL("PUBLIC") if grantee == "PUBLIC" else sql.Identifier(grantee)
            conn.execute(
                sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM {}").format(
                    sql.Identifier(database_name),
                    target,
                )
            )
        grants: dict[tuple[str, bool], list[str]] = {}
        for _grantor, grantee, privilege, grantable in acl:
            grants.setdefault((str(grantee), bool(grantable)), []).append(str(privilege))
        for (grantee, grantable), privileges in sorted(grants.items()):
            target = sql.SQL("PUBLIC") if grantee == "PUBLIC" else sql.Identifier(grantee)
            statement = sql.SQL("GRANT {} ON DATABASE {} TO {}").format(
                sql.SQL(", ").join(sql.SQL(value) for value in sorted(privileges)),
                sql.Identifier(database_name),
                target,
            )
            if grantable:
                statement += sql.SQL(" WITH GRANT OPTION")
            conn.execute(statement)
        conn.execute("RESET ROLE")

        current_setting_roles = {str(row[1]) for row in current_settings if row[0] == "role"}
        expected_setting_roles = {str(row[1]) for row in settings if row[0] == "role"}
        for role_name in sorted(current_setting_roles | expected_setting_roles):
            conn.execute(
                sql.SQL("ALTER ROLE {} IN DATABASE {} RESET ALL").format(
                    sql.Identifier(role_name),
                    sql.Identifier(database_name),
                )
            )
        if any(row[0] == "database" for row in (*current_settings, *settings)):
            conn.execute(
                sql.SQL("ALTER DATABASE {} RESET ALL").format(sql.Identifier(database_name))
            )
        for scope, role_name, expression in settings:
            setting_name, setting_value = str(expression).split("=", 1)
            if scope == "database":
                conn.execute(
                    sql.SQL("ALTER DATABASE {} SET {} TO {}").format(
                        sql.Identifier(database_name),
                        sql.Identifier(setting_name),
                        sql.Literal(setting_value),
                    )
                )
            else:
                conn.execute(
                    sql.SQL("ALTER ROLE {} IN DATABASE {} SET {} TO {}").format(
                        sql.Identifier(str(role_name)),
                        sql.Identifier(database_name),
                        sql.Identifier(setting_name),
                        sql.Literal(setting_value),
                    )
                )
        conn.execute(
            sql.SQL("ALTER DATABASE {} WITH ALLOW_CONNECTIONS {} CONNECTION LIMIT {}").format(
                sql.Identifier(database_name),
                sql.Literal(allow_connections),
                sql.Literal(connection_limit),
            )
        )
    restored = database_authority_facts(url)
    _validated_database_authority(restored)
    if source_facts["sha256"] != restored["sha256"]:
        raise ReleaseOperationError("restored PostgreSQL database authority does not match source")
    return restored


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
