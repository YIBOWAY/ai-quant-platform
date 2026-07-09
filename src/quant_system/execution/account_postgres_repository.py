from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING

from quant_system.execution.account import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_INITIAL_CASH,
    PaperAccount,
)
from quant_system.execution.account_backfill import _write_account
from quant_system.storage.database import Database, get_database

if TYPE_CHECKING:
    from quant_system.config.settings import Settings

logger = logging.getLogger(__name__)


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
        self.account_id = account_id
        self.source = source

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
                else (
                    "PostgreSQL database is unavailable for paper account "
                    f"mirror {action}"
                )
            )
        if self._is_canonical() and action in {"save", "write", "reset", "lock"}:
            return (
                "PostgreSQL database is unavailable for paper account "
                f"canonical {action}"
            )
        return (
            "PostgreSQL database is unavailable for paper account "
            f"{action}"
        )

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
        return PaperAccount.model_validate(raw)

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

        try:
            with database.connect() as conn:
                # Session-level advisory lock held for the critical section while
                # other short-lived connections perform load/save work.
                try:
                    if timeout_seconds and timeout_seconds > 0:
                        ms = max(int(timeout_seconds * 1000), 1)
                        conn.execute(f"SET LOCAL lock_timeout = '{ms}ms'")
                except Exception:  # noqa: BLE001 - optional hint only
                    pass
                conn.execute(
                    "SELECT pg_advisory_lock(hashtext(%s))",
                    (self.account_id,),
                )
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
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_db_error(exc, action="lock") from exc

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
        return self._row_to_account(raw)

    def load_or_open(
        self,
        *,
        initial_cash: float = DEFAULT_INITIAL_CASH,
    ) -> PaperAccount:
        account = self.load()
        if account is not None:
            return account
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
