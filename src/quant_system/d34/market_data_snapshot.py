"""Canonical Futu Parquet snapshots for the D-34 dual-engine contract."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

from quant_system.data.schema import REQUIRED_OHLCV_COLUMNS, normalize_ohlcv_dataframe

SNAPSHOT_CONTRACT = "hqa.market_data_snapshot/v1"
_CANONICAL_TIMEZONE = "America/New_York"
_CANONICAL_CALENDAR = "XNYS"
_CANONICAL_ADJUSTMENT = "qfq"


class MarketDataSnapshotError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FutuOhlcvPort(Protocol):
    provider_name: str

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str,
    ) -> pd.DataFrame: ...


@dataclass(frozen=True)
class MarketDataSnapshot:
    contract: str
    snapshot_id: str
    snapshot_digest: str
    parquet_digest: str
    provider_receipt_digest: str
    provider: str
    universe: tuple[str, ...]
    symbol_codes: dict[str, str]
    timezone: str
    calendar: str
    adjustment: str
    row_count: int
    parquet_path: Path
    manifest_path: Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest_document(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _normalize_universe(symbols: Sequence[str]) -> tuple[str, ...]:
    universe = tuple(str(symbol).strip().upper() for symbol in symbols)
    if (
        not universe
        or len(universe) > 64
        or len(set(universe)) != len(universe)
        or any(not symbol or not symbol.replace("-", "").isalnum() for symbol in universe)
    ):
        raise MarketDataSnapshotError("snapshot_invalid_universe", "snapshot universe is invalid")
    return universe


def _validate_frame(frame: pd.DataFrame, universe: tuple[str, ...]) -> pd.DataFrame:
    try:
        normalized = normalize_ohlcv_dataframe(frame, provider="futu", interval="1d")
    except (TypeError, ValueError) as exc:
        raise MarketDataSnapshotError(
            "snapshot_schema_invalid", "Futu OHLCV does not match the canonical schema"
        ) from exc
    required = [*REQUIRED_OHLCV_COLUMNS, "price_adjustment"]
    if any(column not in normalized.columns for column in required):
        raise MarketDataSnapshotError(
            "snapshot_schema_invalid", "Futu snapshot is missing canonical metadata"
        )
    if normalized.empty:
        raise MarketDataSnapshotError("snapshot_empty", "Futu returned no OHLCV rows")
    observed = set(normalized["symbol"].astype(str))
    if observed != set(universe):
        raise MarketDataSnapshotError(
            "snapshot_universe_mismatch", "Futu snapshot does not contain the exact universe"
        )
    if normalized[required].isna().any().any():
        raise MarketDataSnapshotError(
            "snapshot_missing_values", "Futu snapshot contains missing values"
        )
    if set(normalized["provider"].astype(str)) != {"futu"}:
        raise MarketDataSnapshotError(
            "snapshot_provider_mismatch", "snapshot provider must be Futu"
        )
    if set(normalized["interval"].astype(str)) != {"1d"}:
        raise MarketDataSnapshotError(
            "snapshot_interval_mismatch", "snapshot interval must be daily"
        )
    if set(normalized["price_adjustment"].astype(str).str.lower()) != {_CANONICAL_ADJUSTMENT}:
        raise MarketDataSnapshotError(
            "snapshot_adjustment_mismatch", "snapshot must use Futu QFQ adjustment"
        )
    if normalized.duplicated(subset=["symbol", "timestamp"]).any():
        raise MarketDataSnapshotError("snapshot_duplicate_bar", "snapshot contains duplicate bars")
    if (normalized["knowledge_ts"] < normalized["event_ts"]).any():
        raise MarketDataSnapshotError(
            "snapshot_temporal_invalid", "knowledge time cannot precede event time"
        )
    if (
        (normalized["high"] < normalized[["open", "close", "low"]].max(axis=1)).any()
        or (normalized["low"] > normalized[["open", "close", "high"]].min(axis=1)).any()
        or (normalized[["open", "high", "low", "close"]] <= 0).any().any()
        or (normalized["volume"] < 0).any()
    ):
        raise MarketDataSnapshotError(
            "snapshot_bar_invalid", "snapshot contains invalid OHLCV bars"
        )
    rank = {symbol: index for index, symbol in enumerate(universe)}
    normalized = normalized.assign(_symbol_rank=normalized["symbol"].map(rank))
    return normalized.sort_values(["_symbol_rank", "timestamp"], ignore_index=True).drop(
        columns=["_symbol_rank"]
    )


def _from_manifest(directory: Path, manifest: dict[str, object]) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        contract=str(manifest["contract"]),
        snapshot_id=str(manifest["snapshot_id"]),
        snapshot_digest=str(manifest["snapshot_digest"]),
        parquet_digest=str(manifest["parquet_digest"]),
        provider_receipt_digest=str(manifest["provider_receipt_digest"]),
        provider=str(manifest["provider"]),
        universe=tuple(str(item) for item in manifest["universe"]),  # type: ignore[union-attr]
        symbol_codes={
            str(key): str(value)
            for key, value in dict(manifest["symbol_codes"]).items()  # type: ignore[arg-type]
        },
        timezone=str(manifest["timezone"]),
        calendar=str(manifest["calendar"]),
        adjustment=str(manifest["adjustment"]),
        row_count=int(manifest["row_count"]),  # type: ignore[arg-type]
        parquet_path=directory / "ohlcv.parquet",
        manifest_path=directory / "manifest.json",
    )


def create_market_data_snapshot(
    *,
    provider: FutuOhlcvPort,
    symbols: Sequence[str],
    start: str,
    end: str,
    output_root: str | Path,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> MarketDataSnapshot:
    """Fetch exact Futu bars and atomically publish one content-addressed snapshot."""
    if getattr(provider, "provider_name", None) != "futu":
        raise MarketDataSnapshotError(
            "snapshot_provider_mismatch", "D-34 snapshots require the Futu provider"
        )
    universe = _normalize_universe(symbols)
    observed_at = now()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise MarketDataSnapshotError(
            "snapshot_clock_invalid", "snapshot clock must be timezone-aware"
        )
    try:
        raw = provider.fetch_ohlcv(list(universe), start=start, end=end, interval="1d")
    except MarketDataSnapshotError:
        raise
    except Exception as exc:  # noqa: BLE001 - provider failures have one stable boundary
        raise MarketDataSnapshotError(
            "snapshot_futu_unavailable", "Futu OHLCV fetch failed"
        ) from exc
    frame = _validate_frame(raw, universe)

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=root))
    try:
        parquet_path = temp_dir / "ohlcv.parquet"
        frame.to_parquet(parquet_path, index=False)
        parquet_digest = _sha256_file(parquet_path)
        rows_by_symbol = {
            str(key): int(value)
            for key, value in sorted(frame.groupby("symbol", sort=True).size().items())
        }
        fetched_at = pd.Timestamp(frame["knowledge_ts"].max()).to_pydatetime().astimezone(UTC)
        event_min = pd.Timestamp(frame["event_ts"].min()).to_pydatetime().astimezone(UTC)
        event_max = pd.Timestamp(frame["event_ts"].max()).to_pydatetime().astimezone(UTC)
        symbol_codes = {symbol: f"US.{symbol}" for symbol in universe}
        provider_receipt = {
            "provider": "futu",
            "symbols": symbol_codes,
            "start": start,
            "end": end,
            "interval": "1d",
            "adjustment": _CANONICAL_ADJUSTMENT,
            "fetched_at": fetched_at.isoformat(),
            "row_count": len(frame),
        }
        provider_receipt_digest = _digest_document(provider_receipt)
        identity = {
            "contract": SNAPSHOT_CONTRACT,
            "provider": "futu",
            "universe": list(universe),
            "symbol_codes": symbol_codes,
            "timezone": _CANONICAL_TIMEZONE,
            "calendar": _CANONICAL_CALENDAR,
            "adjustment": _CANONICAL_ADJUSTMENT,
            "schema": list(frame.columns),
            "start": start,
            "end": end,
            "event_min": event_min.isoformat(),
            "event_max": event_max.isoformat(),
            "fetched_at": fetched_at.isoformat(),
            "row_count": len(frame),
            "rows_by_symbol": rows_by_symbol,
            "missing_values": int(frame.isna().sum().sum()),
            "provider_receipt_digest": provider_receipt_digest,
            "parquet_digest": parquet_digest,
        }
        snapshot_digest = _digest_document(identity)
        snapshot_id = f"snapshot-{snapshot_digest[:32]}"
        manifest = {
            **identity,
            "snapshot_id": snapshot_id,
            "snapshot_digest": snapshot_digest,
            "observed_at": observed_at.astimezone(UTC).isoformat(),
            "provider_receipt": provider_receipt,
            "parquet_file": "ohlcv.parquet",
        }
        (temp_dir / "manifest.json").write_bytes(_canonical_json(manifest) + b"\n")
        target_dir = root / snapshot_id
        if target_dir.exists():
            try:
                existing = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise MarketDataSnapshotError(
                    "snapshot_collision", "existing content-addressed snapshot is unreadable"
                ) from exc
            if (
                existing.get("snapshot_digest") != snapshot_digest
                or _sha256_file(target_dir / "ohlcv.parquet") != parquet_digest
            ):
                raise MarketDataSnapshotError(
                    "snapshot_collision", "existing snapshot bytes do not match their identity"
                )
            return _from_manifest(target_dir, existing)
        temp_dir.rename(target_dir)
        return _from_manifest(target_dir, manifest)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


__all__ = [
    "MarketDataSnapshot",
    "MarketDataSnapshotError",
    "SNAPSHOT_CONTRACT",
    "create_market_data_snapshot",
]
