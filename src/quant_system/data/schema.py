from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

BASE_OHLCV_COLUMNS: tuple[str, ...] = (
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
)

REQUIRED_OHLCV_COLUMNS: tuple[str, ...] = (
    *BASE_OHLCV_COLUMNS,
    "provider",
    "interval",
    "event_ts",
    "knowledge_ts",
)


def _missing_columns(columns: Iterable[str], required: Iterable[str]) -> list[str]:
    present = set(columns)
    return [column for column in required if column not in present]


def normalize_ohlcv_dataframe(
    frame: pd.DataFrame,
    *,
    provider: str,
    interval: str,
) -> pd.DataFrame:
    """Normalize raw OHLCV data into the Phase 1 canonical schema."""
    missing = _missing_columns(frame.columns, BASE_OHLCV_COLUMNS)
    if missing:
        raise ValueError(f"missing required OHLCV columns: {', '.join(missing)}")

    normalized = frame.copy()
    normalized["symbol"] = normalized["symbol"].astype(str).str.upper().str.strip()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], utc=True)
    normalized["provider"] = provider
    normalized["interval"] = interval

    if "event_ts" not in normalized.columns:
        normalized["event_ts"] = normalized["timestamp"]
    else:
        normalized["event_ts"] = pd.to_datetime(normalized["event_ts"], utc=True)

    if "knowledge_ts" not in normalized.columns:
        normalized["knowledge_ts"] = normalized["event_ts"]
    else:
        normalized["knowledge_ts"] = pd.to_datetime(normalized["knowledge_ts"], utc=True)

    numeric_columns = ["open", "high", "low", "close", "volume"]
    for column in numeric_columns:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    return normalized.loc[:, list(REQUIRED_OHLCV_COLUMNS)].sort_values(
        ["symbol", "timestamp"],
        ignore_index=True,
    )

