from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
import pytest
from psycopg import sql as pg_sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.execution.account import PaperAccount, PendingAccountOrder
from quant_system.execution.models import ExecutionFill, OrderSide
from quant_system.storage import database as db

MIGRATION_PATH = Path("scripts/sql/004_paper_account_tables.sql")
ROOT_USER_ID = "00000000-0000-0000-0000-000000000001"


def _compact(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _load_backfill_module():
    module_name = "quant_system.execution.account_backfill"
    assert importlib.util.find_spec(module_name) is not None, (
        "expected account_backfill module to exist"
    )
    return importlib.import_module(module_name)


def _fill(symbol: str, side: OrderSide, qty: float, price: float) -> ExecutionFill:
    return ExecutionFill(
        fill_id=f"fill-{symbol}-{side}",
        order_id=f"order-{symbol}-{side}",
        timestamp=pd.Timestamp("2026-07-09T09:30:00Z"),
        symbol=symbol,
        side=side,
        quantity=qty,
        fill_price=price,
        gross_value=qty * price,
        commission=1.25,
    )


def _write_account_file(tmp_path: Path, *, account_id: str = "acct-pgtest") -> Path:
    account = PaperAccount.open_new(account_id=account_id, initial_cash=10_000.0)
    account.apply_fill(
        _fill("AAPL", OrderSide.BUY, 10, 150.0),
        source="manual",
        price_kind="futu_snapshot",
    )
    account.pending_orders.append(
        PendingAccountOrder(
            order_id="pending-aapl-buy",
            created_at="2026-07-09T10:00:00+00:00",
            symbol="AAPL",
            side="buy",
            quantity=2,
            limit_price=140.0,
            reserved_cash=280.0,
            reason="manual_order",
        )
    )
    path = tmp_path / f"{account_id}.json"
    return _write_account(path, account)


def _write_account(path: Path, account: PaperAccount) -> Path:
    path.write_text(
        json.dumps(account.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


@dataclass(frozen=True)
class _ExecuteCall:
    sql: str
    params: tuple[Any, ...] | None


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[_ExecuteCall] = []

    def execute(
        self,
        query: str,
        params: tuple[Any, ...] | list[Any] | None = None,
    ) -> _FakeConnection:
        normalized_params = tuple(params) if params is not None else None
        self.calls.append(_ExecuteCall(_compact(query), normalized_params))
        return self


class _FakeDatabase:
    def __init__(self) -> None:
        self.connection = _FakeConnection()

    @contextmanager
    def connect(self) -> Iterator[_FakeConnection]:
        yield self.connection


def _enabled_settings() -> Settings:
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url="postgresql://user:pass@localhost:5432/quant_system_test_tmp",
            auto_migrate=False,
            connect_timeout_seconds=1,
        )
    )


def _ensure_test_database(url: str) -> None:
    params = conninfo_to_dict(url)
    dbname = params.get("dbname")
    if not dbname or not (dbname.endswith("_tmp") or "test" in dbname):
        pytest.fail(
            "QS_TEST_DATABASE_URL must point at a throwaway test database "
            f"(got {dbname!r})"
        )

    maintenance_params = dict(params)
    maintenance_params["dbname"] = "postgres"
    maintenance_url = make_conninfo(**maintenance_params)
    with psycopg.connect(maintenance_url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (dbname,),
        ).fetchone()
        if exists is None:
            conn.execute(
                pg_sql.SQL("CREATE DATABASE {}").format(pg_sql.Identifier(dbname))
            )


def _postgres_settings() -> Settings:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    _ensure_test_database(url)
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=url,
            auto_migrate=True,
            connect_timeout_seconds=1,
        )
    )


def test_paper_account_migration_defines_required_tables_and_columns() -> None:
    assert MIGRATION_PATH.exists(), f"{MIGRATION_PATH} does not exist"

    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    compact = _compact(sql)

    assert "CREATE SCHEMA IF NOT EXISTS quant_system" in compact
    for table in (
        "paper_accounts",
        "paper_account_ledger",
        "paper_pending_orders",
        "paper_positions_current",
        "paper_position_snapshots",
        "paper_position_snapshot_rows",
    ):
        assert f"CREATE TABLE IF NOT EXISTS quant_system.{table}" in compact

    expected_fragments = (
        "account_id TEXT PRIMARY KEY",
        "owner_user_id UUID NOT NULL REFERENCES quant_system.app_users(id)",
        "base_currency TEXT NOT NULL",
        "initial_cash DOUBLE PRECISION NOT NULL",
        "cash DOUBLE PRECISION NOT NULL",
        "realized_pnl DOUBLE PRECISION NOT NULL",
        "kill_switch BOOLEAN NOT NULL",
        "version INTEGER NOT NULL",
        "raw JSONB NOT NULL",
        "PRIMARY KEY (account_id, entry_id)",
        "UNIQUE (account_id, seq)",
        "PRIMARY KEY (account_id, order_id)",
        "PRIMARY KEY (account_id, symbol)",
        "snapshot_id UUID PRIMARY KEY",
        "metadata JSONB NOT NULL DEFAULT '{}'::jsonb",
        "PRIMARY KEY (snapshot_id, symbol)",
    )
    for fragment in expected_fragments:
        assert fragment in compact


def test_paper_account_migration_is_idempotent() -> None:
    assert MIGRATION_PATH.name.startswith("004_")
    assert MIGRATION_PATH.exists(), f"{MIGRATION_PATH} does not exist"

    compact = _compact(MIGRATION_PATH.read_text(encoding="utf-8"))

    assert "CREATE TABLE IF NOT EXISTS" in compact
    assert "CREATE INDEX IF NOT EXISTS idx_paper_ledger_account_seq" in compact
    assert "CREATE INDEX IF NOT EXISTS idx_paper_snapshots_account_time" in compact
    assert "REFERENCES quant_system.paper_accounts(account_id) ON DELETE CASCADE" in compact
    assert (
        "REFERENCES quant_system.paper_position_snapshots(snapshot_id) "
        "ON DELETE CASCADE"
    ) in compact


def test_backfill_requires_enabled_optional_database(tmp_path: Path) -> None:
    account_path = _write_account_file(tmp_path)
    backfill = _load_backfill_module()
    settings = Settings(database=DatabaseSettings(enabled=False, url=None))

    with pytest.raises(RuntimeError, match="PostgreSQL database is disabled"):
        backfill.backfill_account_file(account_path, settings=settings)


def test_backfill_uses_parameterized_upserts_and_returns_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_path = _write_account_file(tmp_path)
    backfill = _load_backfill_module()
    fake_database = _FakeDatabase()
    monkeypatch.setattr(backfill, "get_database", lambda settings: fake_database)

    result = backfill.backfill_account_file(
        account_path,
        settings=_enabled_settings(),
        source="test_backfill",
    )

    assert result == {
        "accounts": 1,
        "ledger_entries": 2,
        "positions": 1,
        "pending_orders": 1,
    }

    calls = fake_database.connection.calls
    inserts = [call for call in calls if "INSERT INTO quant_system." in call.sql]
    assert inserts, "expected backfill to write with explicit INSERT statements"
    assert all(call.params is not None for call in inserts)

    written_sql = " ".join(call.sql for call in calls)
    for table in (
        "paper_accounts",
        "paper_account_ledger",
        "paper_pending_orders",
        "paper_positions_current",
        "paper_position_snapshots",
        "paper_position_snapshot_rows",
    ):
        assert f"quant_system.{table}" in written_sql

    account_insert = next(
        call for call in inserts if "quant_system.paper_accounts" in call.sql
    )
    assert ROOT_USER_ID in account_insert.params
    assert any("ON CONFLICT" in call.sql for call in inserts)


def test_backfill_replaces_ledger_entries_for_same_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = "acct-pgtest-ledger-prune"
    account_path = _write_account_file(tmp_path, account_id=account_id)
    backfill = _load_backfill_module()
    fake_database = _FakeDatabase()
    monkeypatch.setattr(backfill, "get_database", lambda settings: fake_database)

    backfill.backfill_account_file(account_path, settings=_enabled_settings())
    fake_database.connection.calls.clear()

    current_account = PaperAccount.open_new(account_id=account_id, initial_cash=10_000.0)
    _write_account(account_path, current_account)
    result = backfill.backfill_account_file(account_path, settings=_enabled_settings())

    assert result == {
        "accounts": 1,
        "ledger_entries": 1,
        "positions": 0,
        "pending_orders": 0,
    }
    ledger_operations = [
        (index, call)
        for index, call in enumerate(fake_database.connection.calls)
        if "quant_system.paper_account_ledger" in call.sql
    ]
    assert ledger_operations
    first_ledger_index, first_ledger_call = ledger_operations[0]
    assert "DELETE FROM quant_system.paper_account_ledger" in first_ledger_call.sql
    assert first_ledger_call.params == (account_id,)

    ledger_inserts = [
        (index, call)
        for index, call in ledger_operations
        if "INSERT INTO quant_system.paper_account_ledger" in call.sql
    ]
    assert len(ledger_inserts) == 1
    ledger_insert_index, ledger_insert_call = ledger_inserts[0]
    assert first_ledger_index < ledger_insert_index
    assert ledger_insert_call.params[:3] == (
        account_id,
        current_account.ledger[0].entry_id,
        1,
    )
    assert "ON CONFLICT" not in ledger_insert_call.sql

    delete_missing_calls = [
        call
        for call in fake_database.connection.calls
        if "DELETE FROM quant_system.paper_account_ledger" in call.sql
        and "ANY" in call.sql
    ]
    assert delete_missing_calls == []


@pytest.mark.pg
def test_backfill_inserts_idempotent_rows_in_postgres(tmp_path: Path) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    account_path = _write_account_file(tmp_path, account_id="acct-pgtest-idempotent")
    backfill = _load_backfill_module()

    try:
        db.run_migrations(database)
        with database.connect() as conn:
            conn.execute(
                "DELETE FROM quant_system.paper_accounts WHERE account_id = %s",
                ("acct-pgtest-idempotent",),
            )

        first = backfill.backfill_account_file(account_path, settings=settings)
        second = backfill.backfill_account_file(account_path, settings=settings)

        with database.connect() as conn:
            representative = conn.execute(
                """
                SELECT
                    ledger.seq,
                    ledger.kind,
                    ledger.source,
                    ledger.raw ->> 'kind',
                    positions.symbol,
                    positions.quantity,
                    positions.avg_cost,
                    positions.source_quantity ->> 'manual',
                    pending.payload ->> 'order_id'
                FROM quant_system.paper_account_ledger ledger
                JOIN quant_system.paper_positions_current positions
                  ON positions.account_id = ledger.account_id
                 AND positions.symbol = 'AAPL'
                JOIN quant_system.paper_pending_orders pending
                  ON pending.account_id = ledger.account_id
                 AND pending.order_id = 'pending-aapl-buy'
                WHERE ledger.account_id = %s
                  AND ledger.seq = 2
                """,
                ("acct-pgtest-idempotent",),
            ).fetchone()
            counts = conn.execute(
                """
                SELECT
                    (SELECT count(*)
                     FROM quant_system.paper_accounts
                     WHERE account_id = %s),
                    (SELECT count(*)
                     FROM quant_system.paper_account_ledger
                     WHERE account_id = %s),
                    (SELECT count(*)
                     FROM quant_system.paper_positions_current
                     WHERE account_id = %s),
                    (SELECT count(*)
                     FROM quant_system.paper_pending_orders
                     WHERE account_id = %s),
                    (SELECT count(*)
                     FROM quant_system.paper_position_snapshots
                     WHERE account_id = %s),
                    (SELECT count(*)
                     FROM quant_system.paper_position_snapshot_rows rows
                     JOIN quant_system.paper_position_snapshots snapshots
                       ON snapshots.snapshot_id = rows.snapshot_id
                     WHERE snapshots.account_id = %s)
                """,
                (
                    "acct-pgtest-idempotent",
                    "acct-pgtest-idempotent",
                    "acct-pgtest-idempotent",
                    "acct-pgtest-idempotent",
                    "acct-pgtest-idempotent",
                    "acct-pgtest-idempotent",
                ),
            ).fetchone()

        assert first == second == {
            "accounts": 1,
            "ledger_entries": 2,
            "positions": 1,
            "pending_orders": 1,
        }
        assert representative is not None
        assert representative[:6] == (2, "fill", "manual", "fill", "AAPL", 10.0)
        assert representative[6] == pytest.approx(150.125)
        assert float(representative[7]) == pytest.approx(10.0)
        assert representative[8] == "pending-aapl-buy"
        assert counts == (1, 2, 1, 1, 2, 2)

        current_account = PaperAccount.open_new(
            account_id="acct-pgtest-idempotent",
            initial_cash=10_000.0,
        )
        _write_account(account_path, current_account)
        third = backfill.backfill_account_file(account_path, settings=settings)

        with database.connect() as conn:
            shrunk_counts = conn.execute(
                """
                SELECT
                    (SELECT count(*)
                     FROM quant_system.paper_account_ledger
                     WHERE account_id = %s),
                    (SELECT count(*)
                     FROM quant_system.paper_positions_current
                     WHERE account_id = %s),
                    (SELECT count(*)
                     FROM quant_system.paper_pending_orders
                     WHERE account_id = %s),
                    (SELECT count(*)
                     FROM quant_system.paper_position_snapshots
                     WHERE account_id = %s)
                """,
                (
                    "acct-pgtest-idempotent",
                    "acct-pgtest-idempotent",
                    "acct-pgtest-idempotent",
                    "acct-pgtest-idempotent",
                ),
            ).fetchone()
            ledger_ids = [
                row[0]
                for row in conn.execute(
                    """
                    SELECT entry_id
                    FROM quant_system.paper_account_ledger
                    WHERE account_id = %s
                    ORDER BY seq
                    """,
                    ("acct-pgtest-idempotent",),
                ).fetchall()
            ]

        assert third == {
            "accounts": 1,
            "ledger_entries": 1,
            "positions": 0,
            "pending_orders": 0,
        }
        assert shrunk_counts == (1, 0, 0, 3)
        assert ledger_ids == [current_account.ledger[0].entry_id]
    finally:
        try:
            with database.connect() as conn:
                conn.execute(
                    "DELETE FROM quant_system.paper_accounts WHERE account_id = %s",
                    ("acct-pgtest-idempotent",),
                )
        finally:
            db.reset_database_cache()


@pytest.mark.pg
def test_backfill_replaces_ledger_when_retained_entry_moves_to_lower_seq(
    tmp_path: Path,
) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    account_id = "acct-pgtest-ledger-reorder"
    account_path = tmp_path / f"{account_id}.json"
    backfill = _load_backfill_module()

    account = PaperAccount.open_new(account_id=account_id, initial_cash=10_000.0)
    account.record_event(kind="adjustment", source="system", note="middle")
    account.record_event(kind="adjustment", source="system", note="retained")
    original_ledger_ids = [entry.entry_id for entry in account.ledger]
    _write_account(account_path, account)

    try:
        db.run_migrations(database)
        with database.connect() as conn:
            conn.execute(
                "DELETE FROM quant_system.paper_accounts WHERE account_id = %s",
                (account_id,),
            )

        backfill.backfill_account_file(account_path, settings=settings)

        current_account = account.model_copy(deep=True)
        current_account.ledger = [
            current_account.ledger[0],
            current_account.ledger[2],
        ]
        _write_account(account_path, current_account)

        result = backfill.backfill_account_file(account_path, settings=settings)

        with database.connect() as conn:
            ledger_rows = conn.execute(
                """
                SELECT entry_id, seq, note
                FROM quant_system.paper_account_ledger
                WHERE account_id = %s
                ORDER BY seq
                """,
                (account_id,),
            ).fetchall()
            snapshot_count = conn.execute(
                """
                SELECT count(*)
                FROM quant_system.paper_position_snapshots
                WHERE account_id = %s
                """,
                (account_id,),
            ).fetchone()[0]

        assert result == {
            "accounts": 1,
            "ledger_entries": 2,
            "positions": 0,
            "pending_orders": 0,
        }
        assert ledger_rows == [
            (
                original_ledger_ids[0],
                1,
                "open account with 10000.00 USD",
            ),
            (original_ledger_ids[2], 2, "retained"),
        ]
        assert snapshot_count == 2
    finally:
        try:
            with database.connect() as conn:
                conn.execute(
                    "DELETE FROM quant_system.paper_accounts WHERE account_id = %s",
                    (account_id,),
                )
        finally:
            db.reset_database_cache()
