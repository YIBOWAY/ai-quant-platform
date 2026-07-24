from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Literal, Protocol, TypedDict

from quant_system.execution.account import PaperAccount


class PaperAccountBootstrapRequired(RuntimeError):
    """Canonical storage is missing an account that must be migrated explicitly."""

    code = "paper_account_bootstrap_required"

    def __init__(self, account_id: str) -> None:
        super().__init__(
            f"paper account {account_id!r} is missing from canonical storage; "
            "run the explicit account backfill and reconciliation before cutover"
        )
        self.account_id = account_id


class PaperAccountStorageCorrupt(RuntimeError):
    """Persisted canonical account state exists but cannot be decoded safely."""

    code = "paper_account_storage_corrupt"

    def __init__(self, account_id: str) -> None:
        super().__init__(
            f"paper account {account_id!r} storage is corrupt and has no valid readable state"
        )
        self.account_id = account_id


def validate_paper_account_identity(
    account: PaperAccount,
    *,
    expected_account_id: str,
) -> PaperAccount:
    """Reject repository-key/payload identity drift before it can cross accounts."""
    if account.account_id != expected_account_id:
        raise ValueError(
            "paper account id mismatch: "
            f"repository={expected_account_id!r} payload={account.account_id!r}"
        )
    return account


class PaperAccountReconciliationDifference(TypedDict):
    field: str
    expected: object
    actual: object


class PaperAccountReconciliationResult(TypedDict):
    status: Literal["in_sync", "different", "unavailable", "not_applicable"]
    account_id: str
    source: str
    target: str | None
    checked_at: str
    expected_summary: dict[str, object]
    actual_summary: dict[str, object]
    differences: list[PaperAccountReconciliationDifference]


def paper_account_reconciliation_result(
    *,
    status: Literal["in_sync", "different", "unavailable", "not_applicable"],
    account_id: str,
    source: str,
    target: str | None,
    expected_summary: dict[str, object] | None = None,
    actual_summary: dict[str, object] | None = None,
    differences: list[PaperAccountReconciliationDifference] | None = None,
) -> PaperAccountReconciliationResult:
    return {
        "status": status,
        "account_id": account_id,
        "source": source,
        "target": target,
        "checked_at": datetime.now(UTC).isoformat(),
        "expected_summary": expected_summary or {},
        "actual_summary": actual_summary or {},
        "differences": differences or [],
    }


class PaperAccountRepository(Protocol):
    """Paper account persistence protocol.

    ``load`` is observational and must not create, repair, rename, or persist
    account state. Mutation callers use ``load_or_open``/``save``/``reset``
    while holding ``mutation_lock``.

    Optional duck-typed helpers used by API routes:
    - ``available_for_mutation() -> bool`` (defaults to True when absent)
    - ``last_warning: str | None`` (dual-write mirror warnings)
    - ``reconciliation()`` returns a structured source/target comparison
    - ``is_stale() -> bool`` derives from reconciliation status
    """

    account_id: str

    def mutation_lock(
        self,
        *,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> Iterator[None]: ...

    def load(self) -> PaperAccount | None: ...

    def load_or_open(self, *, initial_cash: float) -> PaperAccount: ...

    def save(
        self,
        account: PaperAccount,
        *,
        prices: dict[str, float] | None = None,
        price_metadata: Mapping[str, Mapping[str, str | None]] | None = None,
    ) -> object: ...

    def reset(self, *, initial_cash: float) -> PaperAccount: ...

    def reconciliation(self) -> PaperAccountReconciliationResult: ...
