"""Canonical PostgreSQL evidence that a read-only research call created no order.

The observation intentionally reads the four paper-account authorities that can
show an execution-side mutation:

* ``paper_accounts`` (account/version/cash/kill-switch authority);
* ``paper_account_ledger`` (append-only account events);
* ``paper_pending_orders`` (queued paper orders);
* ``paper_positions_current`` (materialized positions).

It does not call the paper-account repository, a processor, a broker, or a
provider.  Callers capture once immediately before and once immediately after a
bounded read-only provider call on a READ COMMITTED PostgreSQL transaction.
Any concurrent or accidental mutation changes a table digest and fails closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from quant_system.storage.database import SCHEMA

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ROWS_PER_TABLE = 100_000
_TABLES = (
    "paper_accounts",
    "paper_account_ledger",
    "paper_pending_orders",
    "paper_positions_current",
)


class ZeroOrderObservationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ZeroOrderObservationError(
            "canonical_snapshot_invalid",
            "paper authority returned a non-canonical value",
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_row(value: object) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ZeroOrderObservationError(
                "canonical_snapshot_invalid",
                "paper authority returned invalid JSON",
            ) from exc
    if not isinstance(value, dict):
        raise ZeroOrderObservationError(
            "canonical_snapshot_invalid",
            "paper authority row must be an object",
        )
    return {str(key): item for key, item in value.items()}


@dataclass(frozen=True)
class CanonicalZeroOrderSnapshot:
    owner_user_id: str
    account_count: int
    table_counts: dict[str, int]
    table_digests: dict[str, str]
    snapshot_digest: str

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "account_count": self.account_count,
            "owner_user_id": self.owner_user_id,
            "snapshot_digest": self.snapshot_digest,
            "table_counts": dict(self.table_counts),
            "table_digests": dict(self.table_digests),
        }


@dataclass(frozen=True)
class CanonicalZeroOrderProof:
    action_digest: str
    admission_digest: str | None
    begin: CanonicalZeroOrderSnapshot
    end: CanonicalZeroOrderSnapshot
    capture_digest: str
    orders_created: int = 0

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "action_digest": self.action_digest,
            "admission_digest": self.admission_digest,
            "begin": self.begin.to_storage_dict(),
            "capture_digest": self.capture_digest,
            "end": self.end.to_storage_dict(),
            "orders_created": self.orders_created,
        }


def _read_rows(
    conn: Any,
    *,
    table_name: str,
    owner_user_id: UUID,
) -> list[dict[str, object]]:
    if table_name == "paper_accounts":
        query = f"""
            SELECT to_jsonb(row_data)
            FROM (
                SELECT accounts.*
                FROM {SCHEMA}.paper_accounts AS accounts
                WHERE accounts.owner_user_id = %s
                ORDER BY accounts.account_id
                LIMIT %s
            ) AS row_data
        """
    elif table_name == "paper_account_ledger":
        query = f"""
            SELECT to_jsonb(row_data)
            FROM (
                SELECT ledger.*
                FROM {SCHEMA}.paper_account_ledger AS ledger
                JOIN {SCHEMA}.paper_accounts AS accounts
                  ON accounts.account_id = ledger.account_id
                WHERE accounts.owner_user_id = %s
                ORDER BY ledger.account_id, ledger.seq, ledger.entry_id
                LIMIT %s
            ) AS row_data
        """
    elif table_name == "paper_pending_orders":
        query = f"""
            SELECT to_jsonb(row_data)
            FROM (
                SELECT pending.*
                FROM {SCHEMA}.paper_pending_orders AS pending
                JOIN {SCHEMA}.paper_accounts AS accounts
                  ON accounts.account_id = pending.account_id
                WHERE accounts.owner_user_id = %s
                ORDER BY pending.account_id, pending.order_id
                LIMIT %s
            ) AS row_data
        """
    elif table_name == "paper_positions_current":
        query = f"""
            SELECT to_jsonb(row_data)
            FROM (
                SELECT positions.*
                FROM {SCHEMA}.paper_positions_current AS positions
                JOIN {SCHEMA}.paper_accounts AS accounts
                  ON accounts.account_id = positions.account_id
                WHERE accounts.owner_user_id = %s
                ORDER BY positions.account_id, positions.symbol
                LIMIT %s
            ) AS row_data
        """
    else:  # pragma: no cover - internal allowlist
        raise ZeroOrderObservationError(
            "canonical_snapshot_invalid",
            "unknown paper authority",
        )
    try:
        raw_rows = conn.execute(
            query,
            (owner_user_id, _MAX_ROWS_PER_TABLE + 1),
        ).fetchall()
    except Exception as exc:
        raise ZeroOrderObservationError(
            "canonical_snapshot_unavailable",
            f"{table_name} authority is unavailable",
        ) from exc
    if len(raw_rows) > _MAX_ROWS_PER_TABLE:
        raise ZeroOrderObservationError(
            "canonical_snapshot_too_large",
            f"{table_name} exceeds the bounded observation limit",
        )
    rows: list[dict[str, object]] = []
    for raw in raw_rows:
        if not isinstance(raw, (tuple, list)) or len(raw) != 1:
            raise ZeroOrderObservationError(
                "canonical_snapshot_invalid",
                f"{table_name} returned an invalid row shape",
            )
        rows.append(_json_row(raw[0]))
    return rows


def capture_canonical_zero_order_snapshot(
    conn: Any,
    *,
    owner_user_id: UUID,
) -> CanonicalZeroOrderSnapshot:
    """Read and hash all root-owned canonical paper execution facts."""

    rows_by_table = {
        table_name: _read_rows(
            conn,
            table_name=table_name,
            owner_user_id=owner_user_id,
        )
        for table_name in _TABLES
    }
    accounts = rows_by_table["paper_accounts"]
    if not accounts:
        raise ZeroOrderObservationError(
            "canonical_account_missing",
            "canonical paper account authority has no root-owned account",
        )
    if any(account.get("kill_switch") is not True for account in accounts):
        raise ZeroOrderObservationError(
            "canonical_account_kill_switch_off",
            "every canonical paper account must have kill_switch=true",
        )

    counts = {name: len(rows) for name, rows in rows_by_table.items()}
    digests = {name: _sha256(rows) for name, rows in rows_by_table.items()}
    document = {
        "account_count": len(accounts),
        "owner_user_id": str(owner_user_id),
        "table_counts": counts,
        "table_digests": digests,
    }
    return CanonicalZeroOrderSnapshot(
        owner_user_id=str(owner_user_id),
        account_count=len(accounts),
        table_counts=counts,
        table_digests=digests,
        snapshot_digest=_sha256(document),
    )


def prove_zero_orders(
    *,
    action_digest: str,
    admission_digest: str | None,
    begin: CanonicalZeroOrderSnapshot,
    end: CanonicalZeroOrderSnapshot,
) -> CanonicalZeroOrderProof:
    """Require exact begin/end equality and derive a content-addressed proof."""

    if _DIGEST_RE.fullmatch(action_digest) is None:
        raise ZeroOrderObservationError(
            "canonical_snapshot_invalid",
            "action_digest must be lowercase SHA-256",
        )
    if admission_digest is not None and _DIGEST_RE.fullmatch(admission_digest) is None:
        raise ZeroOrderObservationError(
            "canonical_snapshot_invalid",
            "admission_digest must be lowercase SHA-256 when present",
        )
    if begin.owner_user_id != end.owner_user_id:
        raise ZeroOrderObservationError(
            "zero_order_owner_mismatch",
            "begin/end paper authority owners differ",
        )
    if (
        begin.snapshot_digest != end.snapshot_digest
        or begin.table_counts != end.table_counts
        or begin.table_digests != end.table_digests
    ):
        raise ZeroOrderObservationError(
            "zero_order_delta_detected",
            "canonical paper authority changed during the provider capture",
        )
    document = {
        "action_digest": action_digest,
        "admission_digest": admission_digest,
        "begin_snapshot_digest": begin.snapshot_digest,
        "end_snapshot_digest": end.snapshot_digest,
        "orders_created": 0,
        "table_counts": begin.table_counts,
        "table_digests": begin.table_digests,
    }
    return CanonicalZeroOrderProof(
        action_digest=action_digest,
        admission_digest=admission_digest,
        begin=begin,
        end=end,
        capture_digest=_sha256(document),
    )


__all__ = [
    "CanonicalZeroOrderProof",
    "CanonicalZeroOrderSnapshot",
    "ZeroOrderObservationError",
    "capture_canonical_zero_order_snapshot",
    "prove_zero_orders",
]
