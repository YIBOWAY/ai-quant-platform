from __future__ import annotations

import logging
from collections.abc import Mapping

from quant_system.execution.account import DEFAULT_INITIAL_CASH, PaperAccount
from quant_system.execution.account_repository import PaperAccountRepository

logger = logging.getLogger(__name__)


class DualWritePaperAccountRepository:
    """File-canonical repository with best-effort PostgreSQL mirror writes."""

    def __init__(
        self,
        *,
        file_repo: PaperAccountRepository,
        postgres_repo: PaperAccountRepository,
    ) -> None:
        self.file_repo = file_repo
        self.postgres_repo = postgres_repo
        self.account_id = file_repo.account_id
        self.last_warning: str | None = None

    def mutation_lock(
        self,
        *,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ):
        return self.file_repo.mutation_lock(
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )

    def load(self) -> PaperAccount | None:
        return self.file_repo.load()

    def load_or_open(
        self,
        *,
        initial_cash: float = DEFAULT_INITIAL_CASH,
    ) -> PaperAccount:
        should_mirror = self.file_repo.load() is None
        account = self.file_repo.load_or_open(initial_cash=initial_cash)
        if should_mirror:
            self._mirror(account)
        return account

    def save(
        self,
        account: PaperAccount,
        *,
        prices: dict[str, float] | None = None,
        price_metadata: Mapping[str, Mapping[str, str | None]] | None = None,
    ) -> object:
        file_result = self.file_repo.save(
            account,
            prices=prices,
            price_metadata=price_metadata,
        )
        self._mirror(
            account,
            prices=prices,
            price_metadata=price_metadata,
        )
        return file_result

    def reset(
        self,
        *,
        initial_cash: float = DEFAULT_INITIAL_CASH,
    ) -> PaperAccount:
        account = self.file_repo.reset(initial_cash=initial_cash)
        self._mirror(account)
        return account

    def _mirror(self, account: PaperAccount, **kwargs: object) -> None:
        try:
            self.postgres_repo.save(account, **kwargs)
        except Exception as exc:  # noqa: BLE001 - mirror must not break file writes
            self.last_warning = f"paper account DB mirror write skipped: {exc}"
            logger.warning(self.last_warning, exc_info=True)
        else:
            self.last_warning = None
