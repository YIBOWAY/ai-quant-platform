from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from quant_system.execution.account import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_INITIAL_CASH,
    PaperAccount,
)
from quant_system.execution.account_backfill import ROOT_OWNER_USER_ID, _write_account
from quant_system.execution.account_repository import (
    PaperAccountBootstrapRequired,
    PaperAccountReconciliationDifference,
    PaperAccountReconciliationResult,
    PaperAccountStorageCorrupt,
    paper_account_reconciliation_result,
    validate_paper_account_identity,
)
from quant_system.execution.account_storage import validate_paper_account_id
from quant_system.storage.database import Database, get_database

if TYPE_CHECKING:
    from quant_system.config.settings import Settings

logger = logging.getLogger(__name__)
_EXPECTED_ACCOUNT_UNSET = object()
_SNAPSHOT_UNSET = object()
_TIMESTAMP_KEYS = {
    "as_of",
    "created_at",
    "price_as_of",
    "snapshot_at",
    "timestamp",
    "updated_at",
}


class PostgresPaperAccountRepository:
    """PostgreSQL paper-account repository.

    Slice 6 supports DB-authoritative load/open/reset when selected by the
    factory in ``canonical`` mode. Mirror dual-write continues to use ``save``.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        account_id: str = DEFAULT_ACCOUNT_ID,
        source: str = "api_dual_write",
    ) -> None:
        self.settings = settings
        self.account_id = validate_paper_account_id(account_id)
        self.source = source
        self._last_reconciliation: PaperAccountReconciliationResult | None = None

    def _require_database(self) -> Database:
        database = get_database(self.settings)
        if database is None:
            raise RuntimeError(self._unavailable_message("load"))
        return database

    def _is_canonical(self) -> bool:
        return self.source == "api_canonical"

    def _unavailable_message(self, action: str) -> str:
        # Keep messages free of raw driver/exc text (API/log hygiene).
        # Canonical uses action-specific wording; mirror save keeps fail-open wording.
        if action in {"save", "write", "reset"} and not self._is_canonical():
            return (
                "PostgreSQL database is disabled or not configured; "
                "paper account mirror write skipped"
                if action in {"save", "write"}
                else (f"PostgreSQL database is unavailable for paper account mirror {action}")
            )
        if self._is_canonical() and action in {"save", "write", "reset", "lock"}:
            return f"PostgreSQL database is unavailable for paper account canonical {action}"
        return f"PostgreSQL database is unavailable for paper account {action}"

    def _wrap_db_error(self, exc: Exception, *, action: str) -> RuntimeError:
        if isinstance(exc, RuntimeError):
            return exc
        message = self._unavailable_message(action)
        logger.warning("%s: %s", message, exc, exc_info=True)
        return RuntimeError(message)

    def _row_to_account(self, raw: object) -> PaperAccount:
        # psycopg may return dict already for jsonb; tolerate str
        if isinstance(raw, str):
            raw = json.loads(raw)
        return validate_paper_account_identity(
            PaperAccount.model_validate(raw),
            expected_account_id=self.account_id,
        )

    @contextmanager
    def mutation_lock(
        self,
        *,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> Iterator[None]:
        del poll_seconds
        database = get_database(self.settings)
        if database is None:
            # Canonical callers fail closed via available_for_mutation /
            # load-save errors; keep lock acquisition non-raising here so
            # process-local locks still wrap the critical section.
            yield
            return

        stack = ExitStack()
        try:
            conn = stack.enter_context(database.connect())
            # Session-level advisory lock held for the critical section while
            # other short-lived connections perform load/save work.
            if timeout_seconds and timeout_seconds > 0:
                ms = max(int(timeout_seconds * 1000), 1)
                # ``Database.connect`` uses autocommit, so ``SET LOCAL``
                # would be discarded outside an explicit transaction and
                # leave pg_advisory_lock able to wait forever. Configure
                # this short-lived lock session directly instead.
                conn.execute(
                    "SELECT set_config('lock_timeout', %s, false)",
                    (f"{ms}ms",),
                )
            conn.execute(
                "SELECT pg_advisory_lock(hashtext(%s))",
                (self.account_id,),
            )
        except RuntimeError:
            stack.close()
            raise
        except Exception as exc:  # noqa: BLE001
            stack.close()
            raise self._wrap_db_error(exc, action="lock") from exc

        try:
            yield
        finally:
            try:
                conn.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s))",
                    (self.account_id,),
                )
            except Exception as unlock_exc:  # noqa: BLE001
                logger.warning(
                    "failed to release paper account advisory lock for %s: %s",
                    self.account_id,
                    unlock_exc,
                )
            finally:
                stack.close()

    def available_for_mutation(self) -> bool:
        database = get_database(self.settings)
        if database is None:
            return False
        can_attempt = getattr(database, "can_attempt_connect", None)
        if callable(can_attempt):
            return bool(can_attempt())
        healthy = getattr(database, "healthy", None)
        if callable(healthy):
            return bool(healthy())
        return True

    def load(self) -> PaperAccount | None:
        database = self._require_database()
        try:
            with database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT raw
                    FROM quant_system.paper_accounts
                    WHERE account_id = %s
                    """,
                    (self.account_id,),
                ).fetchone()
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_db_error(exc, action="load") from exc

        if row is None:
            return None
        raw = row[0] if not isinstance(row, Mapping) else row["raw"]
        try:
            return self._row_to_account(raw)
        except (TypeError, ValueError) as exc:
            raise PaperAccountStorageCorrupt(self.account_id) from exc

    def reconciliation(
        self,
        *,
        expected_account: PaperAccount | None | object = _EXPECTED_ACCOUNT_UNSET,
    ) -> PaperAccountReconciliationResult:
        """Compare file/canonical raw state with DB materialized paper tables."""
        explicit_expected = expected_account is not _EXPECTED_ACCOUNT_UNSET
        source = "file" if explicit_expected else "postgres_raw"
        try:
            row = self._read_reconciliation_row()
            result = self._materialize_reconciliation(
                row,
                explicit_expected=explicit_expected,
                expected_account=expected_account,
                source=source,
            )
        except Exception as exc:  # noqa: BLE001 - reconciliation is observational
            logger.warning(
                "paper account reconciliation unavailable for %s: %s",
                self.account_id,
                exc,
                exc_info=True,
            )
            result = paper_account_reconciliation_result(
                status="unavailable",
                account_id=self.account_id,
                source=source,
                target="postgres",
                differences=[
                    {
                        "field": "database",
                        "expected": "available",
                        "actual": "unavailable",
                    }
                ],
            )
            self._last_reconciliation = result
            return result
        self._last_reconciliation = result
        return result

    def _materialize_reconciliation(
        self,
        row,
        *,
        explicit_expected: bool,
        expected_account: PaperAccount | None | object,
        source: str,
    ) -> PaperAccountReconciliationResult:
        if row is None:
            expected = expected_account if explicit_expected else None
            expected_exists = isinstance(expected, PaperAccount)
            differences: list[PaperAccountReconciliationDifference] = []
            if expected_exists:
                differences.append(
                    {
                        "field": "account_exists",
                        "expected": True,
                        "actual": False,
                    }
                )
            result = paper_account_reconciliation_result(
                status="different" if differences else "in_sync",
                account_id=self.account_id,
                source=source,
                target="postgres",
                expected_summary={"account_exists": expected_exists},
                actual_summary={"account_exists": False},
                differences=differences,
            )
            return result

        raw, account_materialized, ledger, positions, pending_orders, snapshot = row
        database_account = self._row_to_account(raw)
        expected = expected_account if explicit_expected else database_account
        if expected is None:
            result = paper_account_reconciliation_result(
                status="different",
                account_id=self.account_id,
                source=source,
                target="postgres",
                expected_summary={"account_exists": False},
                actual_summary={"account_exists": True},
                differences=[
                    {
                        "field": "account_exists",
                        "expected": False,
                        "actual": True,
                    }
                ],
            )
            return result
        if not isinstance(expected, PaperAccount):
            raise TypeError("expected_account must be a PaperAccount or None")

        expected_summary = _account_summary(expected)
        actual_summary = _account_summary(
            database_account,
            account_materialized=_decode_json(account_materialized, {}),
            ledger=_decode_json(ledger, []),
            positions=_decode_json(positions, {}),
            pending_orders=_decode_json(pending_orders, []),
            snapshot=_decode_json(snapshot, None),
            allowed_snapshot_sources={
                self.source,
                "account_json",
                "account_json_initial_backfill",
            },
        )
        differences = _summary_differences(expected_summary, actual_summary)
        result = paper_account_reconciliation_result(
            status="different" if differences else "in_sync",
            account_id=self.account_id,
            source=source,
            target="postgres",
            expected_summary=expected_summary,
            actual_summary=actual_summary,
            differences=differences,
        )
        return result

    def _read_reconciliation_row(self):
        database = self._require_database()
        try:
            with database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT
                        accounts.raw,
                        jsonb_build_object(
                            'account_id', accounts.account_id,
                            'owner_user_id', accounts.owner_user_id::text,
                            'base_currency', accounts.base_currency,
                            'initial_cash', accounts.initial_cash,
                            'cash', accounts.cash,
                            'realized_pnl', accounts.realized_pnl,
                            'kill_switch', accounts.kill_switch,
                            'version', accounts.version,
                            'created_at', accounts.created_at,
                            'updated_at', accounts.updated_at
                        ) AS account_materialized_signature,
                        COALESCE(
                            (
                                SELECT jsonb_agg(
                                    jsonb_build_object(
                                        'entry_id', ledger.entry_id,
                                        'seq', ledger.seq,
                                        'timestamp', ledger.timestamp,
                                        'kind', ledger.kind,
                                        'source', ledger.source,
                                        'symbol', ledger.symbol,
                                        'side', ledger.side,
                                        'quantity', ledger.quantity,
                                        'price', ledger.price,
                                        'gross_value', ledger.gross_value,
                                        'commission', ledger.commission,
                                        'price_kind', ledger.price_kind,
                                        'realized_pnl_delta', ledger.realized_pnl_delta,
                                        'cash_after', ledger.cash_after,
                                        'note', ledger.note,
                                        'raw', ledger.raw
                                    ) ORDER BY ledger.seq
                                )
                                FROM quant_system.paper_account_ledger ledger
                                WHERE ledger.account_id = accounts.account_id
                            ),
                            '[]'::jsonb
                        ) AS ledger_signature,
                        COALESCE(
                            (
                                SELECT jsonb_object_agg(
                                    positions.symbol,
                                    jsonb_build_object(
                                        'quantity', positions.quantity,
                                        'avg_cost', positions.avg_cost,
                                        'source_quantity', positions.source_quantity
                                    )
                                )
                                FROM quant_system.paper_positions_current positions
                                WHERE positions.account_id = accounts.account_id
                            ),
                            '{}'::jsonb
                        ) AS positions_signature,
                        COALESCE(
                            (
                                SELECT jsonb_agg(pending.payload ORDER BY pending.order_id)
                                FROM quant_system.paper_pending_orders pending
                                WHERE pending.account_id = accounts.account_id
                            ),
                            '[]'::jsonb
                        ) AS pending_signature,
                        (
                            SELECT jsonb_build_object(
                                'snapshot_at', snapshots.snapshot_at,
                                'equity', snapshots.equity,
                                'cash', snapshots.cash,
                                'source', snapshots.source,
                                'metadata', snapshots.metadata,
                                'rows', COALESCE(
                                    (
                                        SELECT jsonb_object_agg(
                                            rows.symbol,
                                            jsonb_build_object(
                                                'quantity', rows.quantity,
                                                'avg_cost', rows.avg_cost,
                                                'last_price', rows.last_price,
                                                'market_value', rows.market_value,
                                                'unrealized_pnl', rows.unrealized_pnl,
                                                'source_breakdown', rows.source_breakdown
                                            )
                                        )
                                        FROM quant_system.paper_position_snapshot_rows rows
                                        WHERE rows.snapshot_id = snapshots.snapshot_id
                                    ),
                                    '{}'::jsonb
                                )
                            )
                            FROM quant_system.paper_position_snapshots snapshots
                            WHERE snapshots.account_id = accounts.account_id
                            ORDER BY snapshots.snapshot_at DESC, snapshots.snapshot_id DESC
                            LIMIT 1
                        ) AS latest_snapshot
                    FROM quant_system.paper_accounts accounts
                    WHERE accounts.account_id = %s
                    """,
                    (self.account_id,),
                ).fetchone()
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_db_error(exc, action="reconciliation") from exc

        if row is None:
            return None
        if isinstance(row, Mapping):
            return (
                row["raw"],
                row["account_materialized_signature"],
                row["ledger_signature"],
                row["positions_signature"],
                row["pending_signature"],
                row["latest_snapshot"],
            )
        return row

    def is_stale(self) -> bool:
        result = self._last_reconciliation or self.reconciliation()
        return result["status"] in {"different", "unavailable"}

    def load_or_open(
        self,
        *,
        initial_cash: float = DEFAULT_INITIAL_CASH,
    ) -> PaperAccount:
        account = self.load()
        if account is not None:
            return account
        if self._is_canonical():
            raise PaperAccountBootstrapRequired(self.account_id)
        account = PaperAccount.open_new(
            account_id=self.account_id,
            initial_cash=initial_cash,
        )
        self.save(account)
        return account

    def save(
        self,
        account: PaperAccount,
        *,
        prices: dict[str, float] | None = None,
        price_metadata: Mapping[str, Mapping[str, str | None]] | None = None,
    ) -> dict[str, int]:
        del price_metadata
        validate_paper_account_identity(
            account,
            expected_account_id=self.account_id,
        )
        database = get_database(self.settings)
        if database is None:
            raise RuntimeError(self._unavailable_message("save"))

        payload = account.model_dump(mode="json")
        try:
            with database.connect() as conn:
                transaction = getattr(conn, "transaction", None)
                if transaction is None:
                    _write_account(
                        conn,
                        account,
                        payload,
                        source=self.source,
                        prices=prices,
                    )
                else:
                    with conn.transaction():
                        _write_account(
                            conn,
                            account,
                            payload,
                            source=self.source,
                            prices=prices,
                        )
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001 - failures are reported upstream
            raise self._wrap_db_error(exc, action="save") from exc

        self._last_reconciliation = None
        return {
            "accounts": 1,
            "ledger_entries": len(account.ledger),
            "positions": len(account.positions),
            "pending_orders": len(account.pending_orders),
        }

    def reset(
        self,
        *,
        initial_cash: float = DEFAULT_INITIAL_CASH,
    ) -> PaperAccount:
        # Intentionally do not archive to file in Slice 6.
        # History remains in append-only paper_position_snapshots.
        account = PaperAccount.open_new(
            account_id=self.account_id,
            initial_cash=initial_cash,
        )
        account.record_event(kind="reset", note="account reset to initial cash")
        self.save(account)
        return account


def _decode_json(value: object, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _json_hash(value: object) -> str:
    encoded = json.dumps(
        _normalize_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_json(value: object) -> object:
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            text_key = str(key)
            normalized_item = _normalize_json(item)
            if text_key in _TIMESTAMP_KEYS and isinstance(normalized_item, str):
                normalized_item = _timestamp(normalized_item)
            normalized[text_key] = normalized_item
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return value


def _timestamp(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat()
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    normalized = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _account_materialized_state(account: PaperAccount) -> dict[str, object]:
    return {
        "account_id": account.account_id,
        "owner_user_id": ROOT_OWNER_USER_ID,
        "base_currency": account.base_currency,
        "initial_cash": account.initial_cash,
        "cash": account.cash,
        "realized_pnl": account.realized_pnl,
        "kill_switch": account.kill_switch,
        "version": 1,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def _snapshot_position_state(account: PaperAccount) -> dict[str, object]:
    return {
        symbol.upper(): {
            "quantity": position.quantity,
            "avg_cost": position.avg_cost,
            "source_breakdown": position.source_breakdown(),
        }
        for symbol, position in sorted(account.positions.items())
    }


def _expected_snapshot_state(account: PaperAccount) -> dict[str, object]:
    return {
        "cash": account.cash,
        "positions": _snapshot_position_state(account),
        "metadata": {
            "ledger_entries": len(account.ledger),
            "pending_orders": len(account.pending_orders),
            "position_count": len(account.positions),
        },
    }


def _actual_snapshot_state(snapshot: object) -> dict[str, object] | None:
    if not isinstance(snapshot, Mapping):
        return None
    rows = snapshot.get("rows")
    if not isinstance(rows, Mapping):
        return None
    positions: dict[str, object] = {}
    for symbol, raw_row in rows.items():
        if not isinstance(raw_row, Mapping):
            return None
        positions[str(symbol).upper()] = {
            "quantity": raw_row.get("quantity"),
            "avg_cost": raw_row.get("avg_cost"),
            "source_breakdown": raw_row.get("source_breakdown"),
        }
    return {
        "cash": snapshot.get("cash"),
        "positions": positions,
        "metadata": snapshot.get("metadata"),
    }


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _close_number(left: object, right: object) -> bool:
    left_number = _finite_float(left)
    right_number = _finite_float(right)
    if left_number is None or right_number is None:
        return False
    return math.isclose(left_number, right_number, rel_tol=1e-9, abs_tol=1e-7)


def _snapshot_integrity(snapshot: object, account: PaperAccount) -> bool:
    if not isinstance(snapshot, Mapping):
        return False
    rows = snapshot.get("rows")
    metadata = snapshot.get("metadata")
    if not isinstance(rows, Mapping) or not isinstance(metadata, Mapping):
        return False
    if not isinstance(snapshot.get("source"), str) or not snapshot.get("source"):
        return False
    if metadata.get("ledger_entries") != len(account.ledger):
        return False
    if metadata.get("pending_orders") != len(account.pending_orders):
        return False
    if metadata.get("position_count") != len(account.positions):
        return False

    market_value_total = 0.0
    for raw_row in rows.values():
        if not isinstance(raw_row, Mapping):
            return False
        quantity = _finite_float(raw_row.get("quantity"))
        avg_cost = _finite_float(raw_row.get("avg_cost"))
        last_price = _finite_float(raw_row.get("last_price"))
        market_value = _finite_float(raw_row.get("market_value"))
        unrealized_pnl = _finite_float(raw_row.get("unrealized_pnl"))
        if None in (quantity, avg_cost, last_price, market_value, unrealized_pnl):
            return False
        assert quantity is not None
        assert avg_cost is not None
        assert last_price is not None
        assert market_value is not None
        assert unrealized_pnl is not None
        if not _close_number(market_value, quantity * last_price):
            return False
        if not _close_number(unrealized_pnl, (last_price - avg_cost) * quantity):
            return False
        market_value_total += market_value

    cash = _finite_float(snapshot.get("cash"))
    equity = _finite_float(snapshot.get("equity"))
    if cash is None or equity is None:
        return False
    return _close_number(equity, cash + market_value_total)


def _snapshot_source_valid(
    snapshot: object,
    allowed_sources: set[str] | None,
) -> bool:
    if not isinstance(snapshot, Mapping):
        return False
    source = snapshot.get("source")
    if not isinstance(source, str) or not source:
        return False
    return allowed_sources is None or source in allowed_sources


def _account_summary(
    account: PaperAccount,
    *,
    account_materialized: object | None = None,
    ledger: object | None = None,
    positions: object | None = None,
    pending_orders: object | None = None,
    snapshot: object = _SNAPSHOT_UNSET,
    allowed_snapshot_sources: set[str] | None = None,
) -> dict[str, object]:
    raw = account.model_dump(mode="json")
    materialized_value = account_materialized
    if materialized_value is None:
        materialized_value = _account_materialized_state(account)
    ledger_value = ledger
    if ledger_value is None:
        ledger_value = [
            {
                "seq": seq,
                **entry.model_dump(mode="json"),
                "raw": entry.model_dump(mode="json"),
            }
            for seq, entry in enumerate(account.ledger, start=1)
        ]
    positions_value = positions
    if positions_value is None:
        positions_value = {
            symbol.upper(): {
                "quantity": position.quantity,
                "avg_cost": position.avg_cost,
                "source_quantity": position.source_quantity,
            }
            for symbol, position in sorted(account.positions.items())
        }
    pending_value = pending_orders
    if pending_value is None:
        pending_value = [
            order.model_dump(mode="json")
            for order in sorted(account.pending_orders, key=lambda item: item.order_id)
        ]
    if snapshot is _SNAPSHOT_UNSET:
        snapshot_state = _expected_snapshot_state(account)
        snapshot_integrity = True
        snapshot_source_valid = True
        snapshot_at = None
    else:
        snapshot_state = _actual_snapshot_state(snapshot)
        snapshot_integrity = _snapshot_integrity(snapshot, account)
        snapshot_source_valid = _snapshot_source_valid(
            snapshot,
            allowed_snapshot_sources,
        )
        snapshot_at = snapshot.get("snapshot_at") if isinstance(snapshot, Mapping) else None
    return {
        "account_exists": True,
        "raw_sha256": _json_hash(raw),
        "account_materialized_sha256": _json_hash(materialized_value),
        "ledger_entries": len(ledger_value),
        "ledger_sha256": _json_hash(ledger_value),
        "positions": len(positions_value),
        "positions_sha256": _json_hash(positions_value),
        "pending_orders": len(pending_value),
        "pending_orders_sha256": _json_hash(pending_value),
        "snapshot_state_sha256": (
            _json_hash(snapshot_state) if snapshot_state is not None else None
        ),
        "snapshot_integrity": snapshot_integrity,
        "snapshot_source_valid": snapshot_source_valid,
        "updated_at": _timestamp(account.updated_at),
        "snapshot_at": _timestamp(snapshot_at),
    }


def _summary_differences(
    expected: dict[str, object],
    actual: dict[str, object],
) -> list[PaperAccountReconciliationDifference]:
    differences: list[PaperAccountReconciliationDifference] = []
    comparisons = {
        "raw": ("raw_sha256",),
        "account_materialized": ("account_materialized_sha256",),
        "ledger": ("ledger_entries", "ledger_sha256"),
        "positions": ("positions", "positions_sha256"),
        "pending_orders": ("pending_orders", "pending_orders_sha256"),
        "snapshot": (
            "snapshot_state_sha256",
            "snapshot_integrity",
            "snapshot_source_valid",
        ),
    }
    for field, keys in comparisons.items():
        expected_value = {key: expected.get(key) for key in keys}
        actual_value = {key: actual.get(key) for key in keys}
        if expected_value != actual_value:
            differences.append({"field": field, "expected": expected_value, "actual": actual_value})

    expected_updated_at = _timestamp(expected.get("updated_at"))
    actual_snapshot_at = _timestamp(actual.get("snapshot_at"))
    if expected_updated_at is not None and (
        actual_snapshot_at is None or actual_snapshot_at < expected_updated_at
    ):
        differences.append(
            {
                "field": "snapshot_freshness",
                "expected": {"at_least": expected_updated_at},
                "actual": {"snapshot_at": actual_snapshot_at},
            }
        )
    return differences
