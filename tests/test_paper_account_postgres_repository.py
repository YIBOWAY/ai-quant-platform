from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import time
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
from quant_system.execution.account_storage import PaperAccountStorage
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
    account = _account_with_position(account_id=account_id)
    path = tmp_path / f"{account_id}.json"
    return _write_account(path, account)


def _account_with_position(*, account_id: str = "acct-pgtest") -> PaperAccount:
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
    return account


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
        self._fetchone_results: list[Any] = []
        self._raise_on_execute: Exception | None = None

    def queue_fetchone(self, *rows: Any) -> None:
        self._fetchone_results.extend(rows)

    def raise_on_execute(self, exc: Exception) -> None:
        self._raise_on_execute = exc

    def execute(
        self,
        query: str,
        params: tuple[Any, ...] | list[Any] | None = None,
    ) -> _FakeConnection:
        if self._raise_on_execute is not None:
            raise self._raise_on_execute
        normalized_params = tuple(params) if params is not None else None
        self.calls.append(_ExecuteCall(_compact(query), normalized_params))
        return self

    def fetchone(self) -> Any:
        if not self._fetchone_results:
            return None
        return self._fetchone_results.pop(0)


class _FakeDatabase:
    def __init__(self) -> None:
        self.connection = _FakeConnection()
        self._healthy = True
        self._can_attempt = True

    def healthy(self) -> bool:
        return self._healthy

    def can_attempt_connect(self) -> bool:
        return self._can_attempt

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
            f"QS_TEST_DATABASE_URL must point at a throwaway test database (got {dbname!r})"
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
            conn.execute(pg_sql.SQL("CREATE DATABASE {}").format(pg_sql.Identifier(dbname)))


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
    assert "DROP INDEX IF EXISTS quant_system.idx_paper_ledger_account_seq" in compact
    assert "CREATE INDEX IF NOT EXISTS idx_paper_ledger_account_seq" not in compact
    assert "CREATE INDEX IF NOT EXISTS idx_paper_snapshots_account_time" in compact
    assert "REFERENCES quant_system.paper_accounts(account_id) ON DELETE CASCADE" in compact
    assert (
        "REFERENCES quant_system.paper_position_snapshots(snapshot_id) ON DELETE CASCADE"
    ) in compact


def test_backfill_requires_enabled_optional_database(tmp_path: Path) -> None:
    account_path = _write_account_file(tmp_path)
    backfill = _load_backfill_module()
    settings = Settings(database=DatabaseSettings(enabled=False, url=None))

    with pytest.raises(RuntimeError, match="PostgreSQL database is disabled"):
        backfill.backfill_account_file(account_path, settings=settings)


def test_postgres_repository_save_reuses_backfill_writer_and_returns_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)

    account = _account_with_position(account_id="acct-pg-repo")
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id=account.account_id,
    )

    result = repository.save(account)

    assert result == {
        "accounts": 1,
        "ledger_entries": 2,
        "positions": 1,
        "pending_orders": 1,
    }
    written_sql = " ".join(call.sql for call in fake_database.connection.calls)
    assert "INSERT INTO quant_system.paper_accounts" in written_sql
    assert "INSERT INTO quant_system.paper_account_ledger" in written_sql
    assert "INSERT INTO quant_system.paper_positions_current" in written_sql
    assert "INSERT INTO quant_system.paper_position_snapshots" in written_sql
    assert "account_json" not in str(fake_database.connection.calls)
    assert "api_dual_write" in str(fake_database.connection.calls)


def test_postgres_repository_mutation_lock_sets_session_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-lock-timeout",
        source="api_canonical",
    )

    with repository.mutation_lock(timeout_seconds=1.25):
        pass

    timeout_call = next(
        call for call in fake_database.connection.calls if "set_config('lock_timeout'" in call.sql
    )
    lock_call = next(
        call for call in fake_database.connection.calls if "pg_advisory_lock" in call.sql
    )
    assert timeout_call.params == ("1250ms",)
    assert fake_database.connection.calls.index(timeout_call) < (
        fake_database.connection.calls.index(lock_call)
    )


def test_postgres_repository_mutation_lock_preserves_business_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-lock-business-error",
        source="api_canonical",
    )

    with (
        pytest.raises(ValueError, match="domain validation failed"),
        repository.mutation_lock(),
    ):
        raise ValueError("domain validation failed")

    assert any("pg_advisory_unlock" in call.sql for call in fake_database.connection.calls)


@pytest.mark.pg
def test_postgres_repository_mutation_lock_timeout_is_enforced() -> None:
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )

    settings = _postgres_settings()
    db.reset_database_cache()
    first = PostgresPaperAccountRepository(
        settings=settings,
        account_id="acct-pg-lock-timeout",
        source="api_canonical",
    )
    second = PostgresPaperAccountRepository(
        settings=settings,
        account_id="acct-pg-lock-timeout",
        source="api_canonical",
    )

    try:
        with first.mutation_lock(timeout_seconds=1):
            started_at = time.monotonic()
            with (
                pytest.raises(RuntimeError, match="canonical lock"),
                second.mutation_lock(timeout_seconds=0.1),
            ):
                pytest.fail("a contending advisory lock must not be acquired")
            assert time.monotonic() - started_at < 2
    finally:
        db.reset_database_cache()


def test_file_repository_reconciliation_is_structured_and_read_only(
    tmp_path: Path,
) -> None:
    repository = PaperAccountStorage(tmp_path, account_id="acct-file-reconcile")

    result = repository.reconciliation()

    assert result["status"] == "not_applicable"
    assert result["account_id"] == "acct-file-reconcile"
    assert result["source"] == "file"
    assert result["target"] is None
    assert result["differences"] == []
    assert not repository.account_dir.exists()


def test_postgres_repository_reconciliation_reports_structured_differences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    expected = _account_with_position(account_id="acct-reconcile-diff")
    fake_database.connection.queue_fetchone(
        (
            expected.model_dump(mode="json"),
            module._account_materialized_state(expected),
            [{"entry_id": expected.ledger[0].entry_id, "seq": 1}],
            {},
            [],
            None,
        )
    )
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-reconcile-diff",
    )

    result = repository.reconciliation(expected_account=expected)

    assert result["status"] == "different"
    assert result["source"] == "file"
    assert result["target"] == "postgres"
    assert {
        "ledger",
        "positions",
        "pending_orders",
    } <= {item["field"] for item in result["differences"]}
    assert result["expected_summary"]["ledger_entries"] == 2
    assert result["actual_summary"]["ledger_entries"] == 1


def test_reconciliation_hash_normalizes_equivalent_iso_timestamps() -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")

    with_trailing_zero = {
        "timestamp": "2026-07-02T20:31:34.769820+00:00",
        "raw": {"timestamp": "2026-07-02T20:31:34.769820+00:00"},
    }
    postgres_rendering = {
        "timestamp": "2026-07-02T20:31:34.76982+00:00",
        "raw": {"timestamp": "2026-07-02T20:31:34.76982+00:00"},
    }

    assert module._json_hash(with_trailing_zero) == module._json_hash(postgres_rendering)


@pytest.mark.pg
def test_postgres_repository_reconciliation_detects_materialized_drift() -> None:
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )

    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    account_id = "acct-pg-reconcile-live"
    account = _account_with_position(account_id=account_id)

    try:
        db.run_migrations(database)
        repository = PostgresPaperAccountRepository(
            settings=settings,
            account_id=account_id,
        )
        repository.save(account)

        in_sync = repository.reconciliation(expected_account=account)
        assert in_sync["differences"] == []
        assert in_sync["status"] == "in_sync"

        with database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.paper_positions_current
                SET quantity = quantity + 1
                WHERE account_id = %s AND symbol = 'AAPL'
                """,
                (account_id,),
            )
            conn.execute(
                """
                UPDATE quant_system.paper_account_ledger
                SET note = note || ' materialized-drift'
                WHERE account_id = %s AND seq = 1
                """,
                (account_id,),
            )
            conn.execute(
                """
                UPDATE quant_system.paper_accounts
                SET cash = cash + 1
                WHERE account_id = %s
                """,
                (account_id,),
            )
            conn.execute(
                """
                UPDATE quant_system.paper_position_snapshot_rows AS rows
                SET market_value = rows.market_value + 1
                FROM quant_system.paper_position_snapshots AS snapshots
                WHERE rows.snapshot_id = snapshots.snapshot_id
                  AND snapshots.account_id = %s
                """,
                (account_id,),
            )

        fresh_repository = PostgresPaperAccountRepository(
            settings=settings,
            account_id=account_id,
        )
        different = fresh_repository.reconciliation(expected_account=account)
        assert different["status"] == "different"
        assert {"account_materialized", "ledger", "positions", "snapshot"} <= {
            item["field"] for item in different["differences"]
        }
    finally:
        try:
            with database.connect() as conn:
                conn.execute(
                    "DELETE FROM quant_system.paper_accounts WHERE account_id = %s",
                    (account_id,),
                )
        finally:
            db.reset_database_cache()


@pytest.mark.pg
def test_postgres_canonical_missing_account_requires_backfill_without_insert() -> None:
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )
    from quant_system.execution.account_repository import (
        PaperAccountBootstrapRequired,
    )

    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    account_id = "acct-pg-canonical-bootstrap-required"

    try:
        db.run_migrations(database)
        with database.connect() as conn:
            conn.execute(
                "DELETE FROM quant_system.paper_accounts WHERE account_id = %s",
                (account_id,),
            )
        repository = PostgresPaperAccountRepository(
            settings=settings,
            account_id=account_id,
            source="api_canonical",
        )

        with pytest.raises(PaperAccountBootstrapRequired, match="backfill"):
            repository.load_or_open()

        with database.connect() as conn:
            count = conn.execute(
                "SELECT count(*) FROM quant_system.paper_accounts WHERE account_id = %s",
                (account_id,),
            ).fetchone()[0]
        assert count == 0
    finally:
        try:
            with database.connect() as conn:
                conn.execute(
                    "DELETE FROM quant_system.paper_accounts WHERE account_id = %s",
                    (account_id,),
                )
        finally:
            db.reset_database_cache()


@pytest.mark.pg
def test_reconciliation_detects_snapshot_source_and_metadata_drift() -> None:
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )

    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    account_id = "acct-pg-snapshot-provenance"
    account = _account_with_position(account_id=account_id)

    try:
        db.run_migrations(database)
        repository = PostgresPaperAccountRepository(
            settings=settings,
            account_id=account_id,
            source="api_dual_write",
        )
        repository.save(account)
        assert repository.reconciliation(expected_account=account)["status"] == "in_sync"

        with database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.paper_position_snapshots
                SET source = 'tampered-source'
                WHERE account_id = %s
                """,
                (account_id,),
            )
        source_drift = PostgresPaperAccountRepository(
            settings=settings,
            account_id=account_id,
            source="api_dual_write",
        ).reconciliation(expected_account=account)
        assert "snapshot" in {item["field"] for item in source_drift["differences"]}

        repository.save(account)
        with database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.paper_position_snapshots
                SET metadata = jsonb_set(metadata, '{position_count}', '999'::jsonb)
                WHERE account_id = %s
                  AND snapshot_at = (
                      SELECT max(snapshot_at)
                      FROM quant_system.paper_position_snapshots
                      WHERE account_id = %s
                  )
                """,
                (account_id, account_id),
            )
        metadata_drift = PostgresPaperAccountRepository(
            settings=settings,
            account_id=account_id,
            source="api_dual_write",
        ).reconciliation(expected_account=account)
        assert "snapshot" in {item["field"] for item in metadata_drift["differences"]}
    finally:
        try:
            with database.connect() as conn:
                conn.execute(
                    "DELETE FROM quant_system.paper_accounts WHERE account_id = %s",
                    (account_id,),
                )
        finally:
            db.reset_database_cache()


def test_dual_write_repository_reconciliation_compares_file_to_postgres(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("quant_system.execution.account_dual_write_repository")
    file_repo = PaperAccountStorage(tmp_path, account_id="acct-mirror-reconcile")
    account = _account_with_position(account_id="acct-mirror-reconcile")
    file_repo.save(account)
    compared: list[PaperAccount | None] = []

    class RecordingPostgresRepository:
        def reconciliation(self, *, expected_account):
            compared.append(expected_account)
            return {
                "status": "in_sync",
                "account_id": "acct-mirror-reconcile",
                "source": "file",
                "target": "postgres",
                "checked_at": "2026-07-10T00:00:00+00:00",
                "expected_summary": {},
                "actual_summary": {},
                "differences": [],
            }

    repository = module.DualWritePaperAccountRepository(
        file_repo=file_repo,
        postgres_repo=RecordingPostgresRepository(),
    )

    result = repository.reconciliation()

    assert result["status"] == "in_sync"
    assert compared == [account]


def test_dual_write_repository_save_keeps_file_result_when_postgres_fails(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    module = importlib.import_module("quant_system.execution.account_dual_write_repository")
    from quant_system.execution.account_storage import PaperAccountStorage

    class FailingPostgresRepository:
        def save(self, account: PaperAccount, **_kwargs: object) -> None:
            raise RuntimeError(f"db down for {account.account_id}")

    file_repo = PaperAccountStorage(tmp_path, account_id="acct-mirror-failure")
    repository = module.DualWritePaperAccountRepository(
        file_repo=file_repo,
        postgres_repo=FailingPostgresRepository(),
    )
    account = _account_with_position(account_id="acct-mirror-failure")

    caplog.set_level("WARNING")
    result = repository.save(account)

    assert result == file_repo.account_path
    assert file_repo.load() is not None
    assert repository.last_warning == "paper_account_db_mirror_unavailable"
    assert "paper account DB mirror write skipped" in caplog.text
    assert "db down for acct-mirror-failure" in caplog.text


def test_postgres_repository_save_uses_supplied_snapshot_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    account = _account_with_position(account_id="acct-pg-priced-snapshot")
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id=account.account_id,
    )

    repository.save(account, prices={"AAPL": 222.0})

    snapshot_call = next(
        call
        for call in fake_database.connection.calls
        if "INSERT INTO quant_system.paper_position_snapshots" in call.sql
    )
    row_call = next(
        call
        for call in fake_database.connection.calls
        if "INSERT INTO quant_system.paper_position_snapshot_rows" in call.sql
    )
    assert snapshot_call.params is not None
    assert row_call.params is not None
    assert snapshot_call.params[3] == pytest.approx(account.equity({"AAPL": 222.0}))
    assert row_call.params[4] == pytest.approx(222.0)
    assert row_call.params[5] == pytest.approx(2220.0)
    assert row_call.params[6] == pytest.approx(account.positions["AAPL"].unrealized_pnl(222.0))


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

    account_insert = next(call for call in inserts if "quant_system.paper_accounts" in call.sql)
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
        if "DELETE FROM quant_system.paper_account_ledger" in call.sql and "ANY" in call.sql
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

        assert (
            first
            == second
            == {
                "accounts": 1,
                "ledger_entries": 2,
                "positions": 1,
                "pending_orders": 1,
            }
        )
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


def test_postgres_repository_load_reads_raw_jsonb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)

    account = _account_with_position(account_id="acct-pg-load")
    raw = account.model_dump(mode="json")
    fake_database.connection.queue_fetchone((raw,))

    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-pg-load",
        source="api_canonical",
    )
    loaded = repository.load()

    assert loaded is not None
    assert loaded.account_id == account.account_id
    assert loaded.cash == pytest.approx(account.cash)
    assert loaded.positions["AAPL"].quantity == pytest.approx(10)
    assert loaded.pending_orders[0].order_id == "pending-aapl-buy"
    select_calls = [
        call
        for call in fake_database.connection.calls
        if "SELECT raw FROM quant_system.paper_accounts" in call.sql
    ]
    assert len(select_calls) == 1
    assert select_calls[0].params == ("acct-pg-load",)


def test_postgres_repository_load_classifies_invalid_raw_as_storage_corrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    from quant_system.execution.account_repository import (
        PaperAccountStorageCorrupt,
    )

    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    fake_database.connection.queue_fetchone(("{invalid-json",))
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-corrupt-raw",
        source="api_canonical",
    )

    with pytest.raises(PaperAccountStorageCorrupt) as excinfo:
        repository.load()

    assert excinfo.value.code == "paper_account_storage_corrupt"
    assert "invalid-json" not in str(excinfo.value)


def test_postgres_repository_load_rejects_raw_account_id_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    from quant_system.execution.account_repository import PaperAccountStorageCorrupt

    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    foreign = PaperAccount.open_new(account_id="foreign-account")
    fake_database.connection.queue_fetchone((foreign.model_dump(mode="json"),))
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="expected-account",
        source="api_canonical",
    )

    with pytest.raises(PaperAccountStorageCorrupt):
        repository.load()


def test_postgres_repository_reconciliation_decode_failure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    account = PaperAccount.open_new(account_id="acct-reconcile-corrupt")
    fake_database.connection.queue_fetchone(
        (account.model_dump(mode="json"),),
        ("{invalid-reconciliation-raw", {}, [], {}, [], None),
    )
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id=account.account_id,
        source="api_canonical",
    )

    loaded = repository.load()
    result = repository.reconciliation()

    assert loaded == account
    assert result["status"] == "unavailable"
    assert result["source"] == "postgres_raw"
    assert result["differences"] == [
        {
            "field": "database",
            "expected": "available",
            "actual": "unavailable",
        }
    ]


def test_postgres_repository_save_rejects_account_id_mismatch_before_db_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="expected-account",
        source="api_canonical",
    )
    foreign = PaperAccount.open_new(account_id="foreign-account")

    with pytest.raises(ValueError, match="account id mismatch"):
        repository.save(foreign)

    assert fake_database.connection.calls == []


def test_postgres_repository_load_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    fake_database.connection.queue_fetchone(None)

    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-missing",
    )
    assert repository.load() is None


def test_postgres_repository_canonical_load_or_open_requires_explicit_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    fake_database.connection.queue_fetchone(None)

    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-open-new",
        source="api_canonical",
    )
    with pytest.raises(module.PaperAccountBootstrapRequired, match="backfill"):
        repository.load_or_open(initial_cash=25_000.0)

    written_sql = " ".join(call.sql for call in fake_database.connection.calls)
    assert "SELECT raw FROM quant_system.paper_accounts" in written_sql
    assert "INSERT INTO quant_system.paper_accounts" not in written_sql


def test_postgres_repository_load_or_open_returns_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)

    existing = _account_with_position(account_id="acct-existing")
    fake_database.connection.queue_fetchone((existing.model_dump(mode="json"),))

    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-existing",
        source="api_canonical",
    )
    account = repository.load_or_open(initial_cash=99_000.0)

    assert account.account_id == "acct-existing"
    assert account.cash == pytest.approx(existing.cash)
    assert not any(
        "INSERT INTO quant_system.paper_accounts" in call.sql
        for call in fake_database.connection.calls
    )


def test_postgres_repository_reset_writes_fresh_account_with_reset_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)

    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-reset",
        source="api_canonical",
    )
    account = repository.reset(initial_cash=12_345.0)

    assert account.account_id == "acct-reset"
    assert account.initial_cash == pytest.approx(12_345.0)
    assert account.cash == pytest.approx(12_345.0)
    assert any(entry.kind == "reset" for entry in account.ledger)
    written_sql = " ".join(call.sql for call in fake_database.connection.calls)
    assert "INSERT INTO quant_system.paper_accounts" in written_sql
    assert "api_canonical" in str(fake_database.connection.calls)


def test_postgres_repository_available_for_mutation_false_when_db_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    monkeypatch.setattr(module, "get_database", lambda settings: None)
    repository = module.PostgresPaperAccountRepository(
        settings=Settings(database=DatabaseSettings(enabled=False, url=None)),
        account_id="acct-disabled",
    )
    assert repository.available_for_mutation() is False


def test_postgres_repository_available_for_mutation_uses_can_attempt_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-health",
    )

    fake_database._can_attempt = True
    assert repository.available_for_mutation() is True
    fake_database._can_attempt = False
    assert repository.available_for_mutation() is False


def test_postgres_repository_load_wraps_connect_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    fake_database.connection.raise_on_execute(OSError("connection refused"))
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-fail",
    )

    with pytest.raises(RuntimeError, match="unavailable for paper account load"):
        repository.load()


def test_postgres_repository_canonical_save_error_message_avoids_mirror_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    monkeypatch.setattr(module, "get_database", lambda settings: None)
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-msg",
        source="api_canonical",
    )
    account = _account_with_position(account_id="acct-msg")
    with pytest.raises(RuntimeError, match="canonical save"):
        repository.save(account)


def test_postgres_repository_load_error_omits_raw_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("quant_system.execution.account_postgres_repository")
    fake_database = _FakeDatabase()
    fake_database.connection.raise_on_execute(OSError("password=supersecret connection refused"))
    monkeypatch.setattr(module, "get_database", lambda settings: fake_database)
    repository = module.PostgresPaperAccountRepository(
        settings=_enabled_settings(),
        account_id="acct-fail-secret",
        source="api_canonical",
    )
    with pytest.raises(RuntimeError) as excinfo:
        repository.load()
    message = str(excinfo.value)
    assert "password=supersecret" not in message
    assert "unavailable for paper account load" in message
