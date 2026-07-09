from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING

from quant_system.execution.account import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_INITIAL_CASH,
    PaperAccount,
)
from quant_system.execution.account_backfill import _write_account
from quant_system.storage.database import get_database

if TYPE_CHECKING:
    from quant_system.config.settings import Settings


class PostgresPaperAccountRepository:
    """PostgreSQL paper-account mirror.

    Slice 5 only writes a mirror from an already-mutated ``PaperAccount``.
    DB-canonical load/reset behavior remains a later migration step.
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

    @contextmanager
    def mutation_lock(
        self,
        *,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> Iterator[None]:
        del timeout_seconds, poll_seconds
        yield

    def load(self) -> PaperAccount | None:
        raise NotImplementedError(
            "DB-canonical paper account reads are deferred to Slice 6"
        )

    def load_or_open(
        self,
        *,
        initial_cash: float = DEFAULT_INITIAL_CASH,
    ) -> PaperAccount:
        del initial_cash
        raise NotImplementedError(
            "DB-canonical paper account open is deferred to Slice 6"
        )

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
            raise RuntimeError(
                "PostgreSQL database is disabled or not configured; "
                "paper account mirror write skipped"
            )

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
        except Exception as exc:  # noqa: BLE001 - mirror failures are reported upstream
            raise RuntimeError(
                "PostgreSQL database is unavailable for paper account mirror: "
                f"{exc}"
            ) from exc

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
        del initial_cash
        raise NotImplementedError(
            "DB-canonical paper account reset is deferred to Slice 6"
        )
