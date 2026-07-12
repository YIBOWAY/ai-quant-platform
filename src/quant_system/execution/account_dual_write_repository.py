from __future__ import annotations

import logging
from collections.abc import Mapping

from quant_system.execution.account import DEFAULT_INITIAL_CASH, PaperAccount
from quant_system.execution.account_repository import (
    PaperAccountReconciliationResult,
    PaperAccountRepository,
    paper_account_reconciliation_result,
)

logger = logging.getLogger(__name__)

# Public, non-secret warning code surfaced in API responses.
MIRROR_UNAVAILABLE_WARNING = "paper_account_db_mirror_unavailable"


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
        self._last_reconciliation: PaperAccountReconciliationResult | None = None

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
        account = self.file_repo.load()
        file_warning = getattr(self.file_repo, "last_warning", None)
        if isinstance(file_warning, str) and file_warning:
            self.last_warning = file_warning
        elif self.last_warning != MIRROR_UNAVAILABLE_WARNING:
            self.last_warning = None
        return account

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
        self._last_reconciliation = None
        try:
            self.postgres_repo.save(account, **kwargs)
        except Exception as exc:  # noqa: BLE001 - mirror must not break file writes
            # Keep raw exception details in server logs only.
            logger.warning(
                "paper account DB mirror write skipped for %s: %s",
                account.account_id,
                exc,
                exc_info=True,
            )
            self.last_warning = MIRROR_UNAVAILABLE_WARNING
        else:
            self.last_warning = None

    def reconciliation(self) -> PaperAccountReconciliationResult:
        if self._last_reconciliation is not None:
            return self._last_reconciliation
        expected_account = self.file_repo.load()
        reconcile = getattr(self.postgres_repo, "reconciliation", None)
        if not callable(reconcile):
            result = paper_account_reconciliation_result(
                status="unavailable",
                account_id=self.account_id,
                source="file",
                target="postgres",
                differences=[
                    {
                        "field": "reconciliation",
                        "expected": "supported",
                        "actual": "unavailable",
                    }
                ],
            )
        else:
            try:
                result = reconcile(expected_account=expected_account)
            except Exception as exc:  # noqa: BLE001 - mirror reads remain fail-open
                logger.warning(
                    "paper account DB reconciliation skipped for %s: %s",
                    self.account_id,
                    exc,
                    exc_info=True,
                )
                result = paper_account_reconciliation_result(
                    status="unavailable",
                    account_id=self.account_id,
                    source="file",
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

    def is_stale(self) -> bool:
        return self.reconciliation()["status"] in {"different", "unavailable"}

    def available_for_mutation(self) -> bool:
        # Mirror mode remains fail-open for mutations.
        return True
