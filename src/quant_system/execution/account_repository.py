from __future__ import annotations

import hashlib
import json
import math
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


class PaperAccountAllocationIntegrityResult(TypedDict):
    status: Literal[
        "in_sync",
        "missing",
        "partition_invalid",
        "allocation_ledger_invalid",
        "corrupt",
    ]
    account_id: str
    raw_sha256: str | None
    cash: float | None
    manual_cash: float | None
    partition_sum: float | None
    ledger_count: int | None
    invalid_sleeve_ids: list[str]


def inspect_persisted_paper_account_allocation(
    raw: object,
    *,
    account_id: str,
    persisted_ledger: object | None = None,
) -> PaperAccountAllocationIntegrityResult:
    """Inspect persisted raw cash partitions without constructing PaperAccount."""

    def result(
        status: Literal[
            "in_sync",
            "partition_invalid",
            "allocation_ledger_invalid",
            "corrupt",
        ],
        *,
        raw_sha256: str | None = None,
        cash: float | None = None,
        manual_cash: float | None = None,
        partition_sum: float | None = None,
        ledger_count: int | None = None,
        invalid_sleeve_ids: list[str] | None = None,
    ) -> PaperAccountAllocationIntegrityResult:
        return {
            "status": status,
            "account_id": account_id,
            "raw_sha256": raw_sha256,
            "cash": cash,
            "manual_cash": manual_cash,
            "partition_sum": partition_sum,
            "ledger_count": ledger_count,
            "invalid_sleeve_ids": invalid_sleeve_ids or [],
        }

    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(payload, Mapping):
            return result("corrupt")
        if payload.get("account_id") != account_id:
            return result("corrupt")
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        raw_sha256 = hashlib.sha256(encoded).hexdigest()
        cash_value = float(payload["cash"])
        sleeve_cash = payload["sleeve_cash"]
        ledger = payload["ledger"]
        if not math.isfinite(cash_value) or not isinstance(sleeve_cash, Mapping):
            return result("corrupt", raw_sha256=raw_sha256)
        if not isinstance(ledger, list):
            return result("corrupt", raw_sha256=raw_sha256)
        materialized_ledger = (
            json.loads(persisted_ledger)
            if isinstance(persisted_ledger, str)
            else persisted_ledger
        )
        if materialized_ledger is not None and not isinstance(
            materialized_ledger,
            list,
        ):
            return result("corrupt", raw_sha256=raw_sha256)
        partitions: dict[str, float] = {}
        for sleeve_id, value in sleeve_cash.items():
            amount = float(value)
            if not math.isfinite(amount) or amount < 0:
                return result("corrupt", raw_sha256=raw_sha256)
            partitions[str(sleeve_id)] = amount
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return result("corrupt")

    partition_sum = sum(partitions.values())
    manual_cash = partitions.get("manual")
    common = {
        "raw_sha256": raw_sha256,
        "cash": cash_value,
        "manual_cash": manual_cash,
        "partition_sum": partition_sum,
        "ledger_count": len(ledger),
    }
    if manual_cash is None or not math.isclose(
        partition_sum,
        cash_value,
        rel_tol=1e-9,
        abs_tol=1e-7,
    ):
        return result("partition_invalid", **common)

    invalid: list[str] = []
    for sleeve_id in sorted(item for item in partitions if item != "manual"):
        source = f"strategy:{sleeve_id}"
        raw_matches = [
            entry
            for entry in ledger
            if isinstance(entry, Mapping)
            and entry.get("kind") == "sleeve_cash_allocated"
            and entry.get("source") == source
        ]
        materialized_matches = (
            [
                entry
                for entry in materialized_ledger
                if isinstance(entry, Mapping)
                and entry.get("kind") == "sleeve_cash_allocated"
                and entry.get("source") == source
            ]
            if materialized_ledger is not None
            else raw_matches
        )
        if len(raw_matches) != 1 or len(materialized_matches) != 1:
            invalid.append(sleeve_id)
    if invalid:
        return result(
            "allocation_ledger_invalid",
            invalid_sleeve_ids=invalid,
            **common,
        )
    return result("in_sync", **common)


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

    def allocation_integrity(self) -> PaperAccountAllocationIntegrityResult: ...
