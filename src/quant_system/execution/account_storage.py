from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quant_system.execution.account import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_INITIAL_CASH,
    PaperAccount,
)


class PaperAccountStorage:
    """Local persistence for the single ongoing paper account.

    Layout (under ``api_runs_dir/paper_account/<account_id>/``)::

        account.json              full account incl. materialised ledger
        positions_snapshot.parquet  latest positions for the Position Map
        archive/account-<ts>.json   archived copies (on reset)

    The account is a long-lived MUTABLE entity (unlike immutable runs), so
    every save overwrites ``account.json`` atomically.
    """

    def __init__(self, base_dir: str | Path, *, account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        self.account_id = account_id
        self.account_dir = Path(base_dir) / "paper_account" / account_id

    @property
    def account_path(self) -> Path:
        return self.account_dir / "account.json"

    @property
    def account_backup_path(self) -> Path:
        return self.account_dir / "account.json.bak"

    @property
    def positions_snapshot_path(self) -> Path:
        return self.account_dir / "positions_snapshot.parquet"

    @property
    def lock_path(self) -> Path:
        return self.account_dir / "account.lock"

    @contextmanager
    def mutation_lock(
        self,
        *,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> Iterator[None]:
        """Serialize mutations across the API, CLI, and scheduler processes."""
        self.account_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()

            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    self._lock_file(handle)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"timed out waiting for paper account lock {self.lock_path}"
                        ) from None
                    time.sleep(poll_seconds)
            try:
                yield
            finally:
                self._unlock_file(handle)

    @staticmethod
    def _lock_file(handle) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_file(handle) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def load(self) -> PaperAccount | None:
        if not self.account_path.exists():
            return None
        try:
            return self._load_account_file(self.account_path)
        except (json.JSONDecodeError, OSError, ValueError):
            self._preserve_corrupt_account_file()
            return self._restore_backup_account()

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
    ) -> Path:
        self.account_dir.mkdir(parents=True, exist_ok=True)
        payload = account.model_dump(mode="json")
        if self.account_path.exists():
            self.account_backup_path.write_text(
                self.account_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        # Unique tmp name per write so concurrent writers don't clobber each
        # other's temp file (which on Windows raises PermissionError on rename).
        tmp_path = self.account_path.with_suffix(f".json.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._atomic_replace(tmp_path, self.account_path)
        self._write_positions_snapshot(account, prices, price_metadata)
        return self.account_path

    @staticmethod
    def _atomic_replace(src: Path, dst: Path) -> None:
        # os.replace can transiently fail on Windows if the destination is being
        # read by another handle; retry briefly before giving up.
        last_error: OSError | None = None
        for attempt in range(10):
            try:
                os.replace(src, dst)
                return
            except PermissionError as exc:  # noqa: PERF203 - rare retry path
                last_error = exc
                time.sleep(0.02 * (attempt + 1))
        if last_error is not None:
            with suppress(OSError):
                src.unlink(missing_ok=True)
            raise last_error

    def reset(
        self,
        *,
        initial_cash: float = DEFAULT_INITIAL_CASH,
    ) -> PaperAccount:
        """Archive the existing account (if any) and open a fresh one."""
        existing = self.load()
        if existing is not None:
            self._archive(existing)
        account = PaperAccount.open_new(
            account_id=self.account_id,
            initial_cash=initial_cash,
        )
        account.record_event(kind="reset", note="account reset to initial cash")
        self.save(account)
        return account

    def _archive(self, account: PaperAccount) -> Path:
        archive_dir = self.account_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        # Microsecond + short uuid so rapid successive resets never collide.
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
        path = archive_dir / f"account-{stamp}-{uuid.uuid4().hex[:6]}.json"
        path.write_text(
            json.dumps(account.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def _preserve_corrupt_account_file(self) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
        path = self.account_dir / f"account.corrupt-{stamp}-{uuid.uuid4().hex[:6]}.json"
        os.replace(self.account_path, path)
        return path

    @staticmethod
    def _load_account_file(path: Path) -> PaperAccount:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PaperAccount.model_validate(data)

    def _restore_backup_account(self) -> PaperAccount | None:
        if not self.account_backup_path.exists():
            return None
        try:
            account = self._load_account_file(self.account_backup_path)
            backup_text = self.account_backup_path.read_text(encoding="utf-8")
        except (json.JSONDecodeError, OSError, ValueError):
            return None
        tmp_path = self.account_path.with_suffix(f".json.restore-{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(backup_text, encoding="utf-8")
        self._atomic_replace(tmp_path, self.account_path)
        return account

    def _write_positions_snapshot(
        self,
        account: PaperAccount,
        prices: dict[str, float] | None = None,
        price_metadata: Mapping[str, Mapping[str, str | None]] | None = None,
    ) -> Path:
        normalized = {k.upper(): float(v) for k, v in (prices or {}).items()}
        metadata = self._snapshot_price_metadata(account, price_metadata)
        equity = account.equity(normalized)
        rows = []
        for symbol, position in sorted(account.positions.items()):
            last_price = normalized.get(symbol, position.avg_cost)
            market_value = position.market_value(last_price)
            rows.append(
                {
                    "symbol": symbol,
                    "quantity": position.quantity,
                    "avg_cost": position.avg_cost,
                    "last_price": last_price,
                    "market_value": market_value,
                    "weight": (market_value / equity) if equity else 0.0,
                    "unrealized_pnl": position.unrealized_pnl(last_price),
                    "source_breakdown": json.dumps(position.source_breakdown()),
                    "price_kind": metadata.get(symbol, {}).get("kind"),
                    "price_as_of": metadata.get(symbol, {}).get("as_of"),
                }
            )
        frame = pd.DataFrame(
            rows,
            columns=[
                "symbol",
                "quantity",
                "avg_cost",
                "last_price",
                "market_value",
                "weight",
                "unrealized_pnl",
                "source_breakdown",
                "price_kind",
                "price_as_of",
            ],
        )
        self.account_dir.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(self.positions_snapshot_path, index=False)
        return self.positions_snapshot_path

    @staticmethod
    def _snapshot_price_metadata(
        account: PaperAccount,
        price_metadata: Mapping[str, Mapping[str, str | None]] | None,
    ) -> dict[str, Mapping[str, str | None]]:
        metadata = {k.upper(): v for k, v in (price_metadata or {}).items()}
        for entry in reversed(account.ledger):
            symbol = entry.symbol.upper() if entry.symbol else None
            if symbol and entry.price_kind and symbol not in metadata:
                metadata[symbol] = {
                    "kind": entry.price_kind,
                    "as_of": entry.timestamp,
                }
        return metadata
