"""Explicit backfill from a file-backed paper account into PostgreSQL.

The file-backed ``PaperAccount`` remains the source of truth. This module only
mirrors a caller-provided account JSON file into the optional database; it is
not imported by API routes and never opens or creates an account.

Mirror semantics are intentionally asymmetric:
- account, pending orders, and current positions are current-state mirrors;
- ledger rows are replaced from the current JSON ledger on every backfill;
- position snapshots are append-only audit points for each backfill run.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_system.config.settings import Settings
from quant_system.execution.account import PaperAccount
from quant_system.storage.database import SCHEMA, get_database

ROOT_OWNER_USER_ID = "00000000-0000-0000-0000-000000000001"


def backfill_account_file(
    account_path: Path,
    *,
    settings: Settings,
    source: str = "account_json",
) -> dict[str, int]:
    """Load a PaperAccount JSON file and mirror it into Postgres.

    The ledger is deleted and reinserted for the account inside the same
    transaction. PostgreSQL is only a mirror here; replacing the ledger avoids
    stale rows and entry_id/sequence reorder conflicts after resets or corrected
    account files.
    """

    payload = json.loads(Path(account_path).read_text(encoding="utf-8"))
    account = PaperAccount.model_validate(payload)

    database = get_database(settings)
    if database is None:
        raise RuntimeError(
            "PostgreSQL database is disabled or not configured; "
            "paper account backfill requires the optional database"
        )

    try:
        with database.connect() as conn:
            transaction = getattr(conn, "transaction", None)
            if transaction is None:
                _write_account(conn, account, payload, source=source)
            else:
                with conn.transaction():
                    _write_account(conn, account, payload, source=source)
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a clear domain failure
        raise RuntimeError(
            "PostgreSQL database is unavailable for paper account backfill: "
            f"{exc}"
        ) from exc

    return {
        "accounts": 1,
        "ledger_entries": len(account.ledger),
        "positions": len(account.positions),
        "pending_orders": len(account.pending_orders),
    }


def _write_account(
    conn: Any,
    account: PaperAccount,
    payload: dict[str, Any],
    *,
    source: str,
) -> None:
    account_id = account.account_id
    now = datetime.now(UTC).isoformat()
    raw_account = _json(payload)

    conn.execute(
        f"""
        INSERT INTO {SCHEMA}.paper_accounts
            (
                account_id,
                owner_user_id,
                base_currency,
                initial_cash,
                cash,
                realized_pnl,
                kill_switch,
                version,
                raw,
                created_at,
                updated_at
            )
        VALUES (
            %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb,
            %s::timestamptz, %s::timestamptz
        )
        ON CONFLICT (account_id) DO UPDATE
        SET owner_user_id = EXCLUDED.owner_user_id,
            base_currency = EXCLUDED.base_currency,
            initial_cash = EXCLUDED.initial_cash,
            cash = EXCLUDED.cash,
            realized_pnl = EXCLUDED.realized_pnl,
            kill_switch = EXCLUDED.kill_switch,
            version = EXCLUDED.version,
            raw = EXCLUDED.raw,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at
        """,
        (
            account_id,
            ROOT_OWNER_USER_ID,
            account.base_currency,
            account.initial_cash,
            account.cash,
            account.realized_pnl,
            account.kill_switch,
            int(payload.get("version") or 1),
            raw_account,
            account.created_at,
            account.updated_at,
        ),
    )
    _replace_ledger(conn, account)
    _upsert_pending_orders(conn, account)
    _upsert_current_positions(conn, account)
    _insert_position_snapshot(conn, account, source=source, snapshot_at=now)


def _replace_ledger(conn: Any, account: PaperAccount) -> None:
    conn.execute(
        f"DELETE FROM {SCHEMA}.paper_account_ledger WHERE account_id = %s",
        (account.account_id,),
    )
    for seq, entry in enumerate(account.ledger, start=1):
        raw = entry.model_dump(mode="json")
        conn.execute(
            f"""
            INSERT INTO {SCHEMA}.paper_account_ledger
                (
                    account_id,
                    entry_id,
                    seq,
                    timestamp,
                    kind,
                    source,
                    symbol,
                    side,
                    quantity,
                    price,
                    gross_value,
                    commission,
                    price_kind,
                    realized_pnl_delta,
                    cash_after,
                    note,
                    raw
                )
            VALUES (
                %s, %s, %s, %s::timestamptz, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s::jsonb
            )
            """,
            (
                account.account_id,
                entry.entry_id,
                seq,
                entry.timestamp,
                entry.kind,
                entry.source,
                entry.symbol,
                entry.side,
                entry.quantity,
                entry.price,
                entry.gross_value,
                entry.commission,
                entry.price_kind,
                entry.realized_pnl_delta,
                entry.cash_after,
                entry.note,
                _json(raw),
            ),
        )


def _upsert_pending_orders(conn: Any, account: PaperAccount) -> None:
    order_ids: list[str] = []
    for order in account.pending_orders:
        raw = order.model_dump(mode="json")
        order_ids.append(order.order_id)
        conn.execute(
            f"""
            INSERT INTO {SCHEMA}.paper_pending_orders
                (account_id, order_id, payload, created_at)
            VALUES (%s, %s, %s::jsonb, %s::timestamptz)
            ON CONFLICT (account_id, order_id) DO UPDATE
            SET payload = EXCLUDED.payload,
                created_at = EXCLUDED.created_at
            """,
            (account.account_id, order.order_id, _json(raw), order.created_at),
        )
    _delete_missing(
        conn,
        table="paper_pending_orders",
        account_id=account.account_id,
        key_column="order_id",
        current_keys=order_ids,
    )


def _upsert_current_positions(conn: Any, account: PaperAccount) -> None:
    symbols: list[str] = []
    for symbol, position in sorted(account.positions.items()):
        normalized_symbol = symbol.upper()
        symbols.append(normalized_symbol)
        conn.execute(
            f"""
            INSERT INTO {SCHEMA}.paper_positions_current
                (
                    account_id,
                    symbol,
                    quantity,
                    avg_cost,
                    source_quantity,
                    updated_at
                )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::timestamptz)
            ON CONFLICT (account_id, symbol) DO UPDATE
            SET quantity = EXCLUDED.quantity,
                avg_cost = EXCLUDED.avg_cost,
                source_quantity = EXCLUDED.source_quantity,
                updated_at = EXCLUDED.updated_at
            """,
            (
                account.account_id,
                normalized_symbol,
                position.quantity,
                position.avg_cost,
                _json(position.source_quantity),
                account.updated_at,
            ),
        )
    _delete_missing(
        conn,
        table="paper_positions_current",
        account_id=account.account_id,
        key_column="symbol",
        current_keys=symbols,
    )


def _insert_position_snapshot(
    conn: Any,
    account: PaperAccount,
    *,
    source: str,
    snapshot_at: str,
) -> None:
    snapshot_id = str(uuid.uuid4())
    prices = {
        symbol: position.avg_cost
        for symbol, position in account.positions.items()
    }
    equity = account.equity(prices)
    metadata = {
        "ledger_entries": len(account.ledger),
        "pending_orders": len(account.pending_orders),
        "position_count": len(account.positions),
    }
    conn.execute(
        f"""
        INSERT INTO {SCHEMA}.paper_position_snapshots
            (snapshot_id, account_id, snapshot_at, equity, cash, source, metadata)
        VALUES (%s::uuid, %s, %s::timestamptz, %s, %s, %s, %s::jsonb)
        """,
        (
            snapshot_id,
            account.account_id,
            snapshot_at,
            equity,
            account.cash,
            source,
            _json(metadata),
        ),
    )
    for symbol, position in sorted(account.positions.items()):
        last_price = position.avg_cost
        market_value = position.market_value(last_price)
        conn.execute(
            f"""
            INSERT INTO {SCHEMA}.paper_position_snapshot_rows
                (
                    snapshot_id,
                    symbol,
                    quantity,
                    avg_cost,
                    last_price,
                    market_value,
                    unrealized_pnl,
                    source_breakdown
                )
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                snapshot_id,
                symbol.upper(),
                position.quantity,
                position.avg_cost,
                last_price,
                market_value,
                position.unrealized_pnl(last_price),
                _json(position.source_breakdown()),
            ),
        )


def _delete_missing(
    conn: Any,
    *,
    table: str,
    account_id: str,
    key_column: str,
    current_keys: list[str],
) -> None:
    if current_keys:
        conn.execute(
            f"""
            DELETE FROM {SCHEMA}.{table}
            WHERE account_id = %s
              AND NOT ({key_column} = ANY(%s))
            """,
            (account_id, current_keys),
        )
        return
    conn.execute(
        f"DELETE FROM {SCHEMA}.{table} WHERE account_id = %s",
        (account_id,),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
