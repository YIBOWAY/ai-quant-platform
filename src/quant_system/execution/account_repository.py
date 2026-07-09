from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Protocol

from quant_system.execution.account import PaperAccount


class PaperAccountRepository(Protocol):
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
