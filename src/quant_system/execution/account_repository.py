from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Protocol

from quant_system.execution.account import PaperAccount


class PaperAccountRepository(Protocol):
    """Paper account persistence protocol.

    Optional duck-typed helpers used by API routes:
    - ``available_for_mutation() -> bool`` (defaults to True when absent)
    - ``last_warning: str | None`` (dual-write mirror warnings)
    - ``is_stale() -> bool`` (reserved for later reconciliation)
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
