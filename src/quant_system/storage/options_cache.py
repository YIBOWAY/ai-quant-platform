from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


@dataclass(frozen=True)
class OptionQuotesCacheKey:
    provider: str
    host: str
    port: int
    underlying: str
    start_expiration: str
    end_expiration: str
    option_type: str

    def fingerprint(self) -> str:
        payload = {
            "provider": self.provider.lower().strip(),
            "host": self.host.strip(),
            "port": int(self.port),
            "underlying": self.underlying.upper().strip(),
            "start_expiration": self.start_expiration,
            "end_expiration": self.end_expiration,
            "option_type": self.option_type.upper().strip(),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def snapshot_id(self) -> str:
        return sha256(self.fingerprint().encode("utf-8")).hexdigest()


class OptionQuotesCache:
    """DuckDB-backed cache for normalized option quote windows."""

    def __init__(self, duckdb_path: str | Path) -> None:
        self.duckdb_path = Path(duckdb_path)
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def read_option_quotes(
        self,
        key: OptionQuotesCacheKey,
        *,
        as_of: pd.Timestamp | None = None,
    ) -> pd.DataFrame | None:
        snapshot_id = key.snapshot_id()
        now = _utc_timestamp(as_of or pd.Timestamp.now(tz="UTC"))
        with duckdb.connect(str(self.duckdb_path)) as connection:
            self._ensure_schema(connection)
            metadata = connection.execute(
                """
                SELECT expires_at, columns_json
                FROM option_chain_snapshots
                WHERE snapshot_id = ?
                """,
                [snapshot_id],
            ).fetchone()
            if metadata is None:
                return None
            expires_at = _utc_timestamp(pd.Timestamp(metadata[0]))
            if expires_at <= now:
                return None
            rows = connection.execute(
                """
                SELECT payload_json
                FROM option_contract_quotes
                WHERE snapshot_id = ?
                ORDER BY row_index
                """,
                [snapshot_id],
            ).fetchall()

        columns = json.loads(metadata[1])
        if not rows:
            return pd.DataFrame(columns=columns)
        frame = pd.DataFrame([json.loads(row[0]) for row in rows])
        for column in columns:
            if column not in frame.columns:
                frame[column] = None
        frame = frame.loc[:, columns]
        for column in _NUMERIC_COLUMNS:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame

    def write_option_quotes(
        self,
        key: OptionQuotesCacheKey,
        frame: pd.DataFrame,
        *,
        ttl_seconds: float,
        fetched_at: pd.Timestamp | None = None,
        source_label: str = "futu_option_quotes",
    ) -> None:
        snapshot_id = key.snapshot_id()
        fetched = _utc_timestamp(fetched_at or pd.Timestamp.now(tz="UTC"))
        expires = fetched + pd.Timedelta(seconds=float(ttl_seconds))
        records = _frame_records(frame)
        columns = [str(column) for column in frame.columns]

        with duckdb.connect(str(self.duckdb_path)) as connection:
            self._ensure_schema(connection)
            connection.execute(
                "DELETE FROM option_contract_quotes WHERE snapshot_id = ?",
                [snapshot_id],
            )
            connection.execute(
                "DELETE FROM option_chain_snapshots WHERE snapshot_id = ?",
                [snapshot_id],
            )
            connection.execute(
                """
                INSERT INTO option_chain_snapshots (
                    snapshot_id,
                    provider,
                    host,
                    port,
                    ticker,
                    start_expiration,
                    end_expiration,
                    option_type,
                    fetched_at,
                    expires_at,
                    source_label,
                    row_count,
                    columns_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    snapshot_id,
                    key.provider.lower().strip(),
                    key.host.strip(),
                    int(key.port),
                    key.underlying.upper().strip(),
                    key.start_expiration,
                    key.end_expiration,
                    key.option_type.upper().strip(),
                    fetched.isoformat(),
                    expires.isoformat(),
                    source_label,
                    len(records),
                    json.dumps(columns, separators=(",", ":")),
                ],
            )
            if records:
                connection.executemany(
                    """
                    INSERT INTO option_contract_quotes (
                        snapshot_id,
                        row_index,
                        symbol,
                        underlying,
                        option_type,
                        expiry,
                        strike,
                        bid,
                        ask,
                        last,
                        mid,
                        volume,
                        open_interest,
                        implied_volatility,
                        delta,
                        gamma,
                        theta,
                        vega,
                        rho,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        _contract_quote_row(snapshot_id, index, record)
                        for index, record in enumerate(records)
                    ],
                )

    def prune_expired(self, *, as_of: pd.Timestamp | None = None) -> int:
        now = _utc_timestamp(as_of or pd.Timestamp.now(tz="UTC"))
        with duckdb.connect(str(self.duckdb_path)) as connection:
            self._ensure_schema(connection)
            snapshot_ids = [
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT snapshot_id
                    FROM option_chain_snapshots
                    WHERE expires_at <= ?
                    """,
                    [now.isoformat()],
                ).fetchall()
            ]
            if not snapshot_ids:
                return 0
            connection.executemany(
                "DELETE FROM option_contract_quotes WHERE snapshot_id = ?",
                [(snapshot_id,) for snapshot_id in snapshot_ids],
            )
            connection.executemany(
                "DELETE FROM option_chain_snapshots WHERE snapshot_id = ?",
                [(snapshot_id,) for snapshot_id in snapshot_ids],
            )
            return len(snapshot_ids)

    def _ensure_schema(self, connection: duckdb.DuckDBPyConnection | None = None) -> None:
        owns_connection = connection is None
        active_connection = connection or duckdb.connect(str(self.duckdb_path))
        try:
            active_connection.execute(
                """
                CREATE TABLE IF NOT EXISTS option_chain_snapshots (
                    snapshot_id VARCHAR PRIMARY KEY,
                    provider VARCHAR NOT NULL,
                    host VARCHAR NOT NULL,
                    port INTEGER NOT NULL,
                    ticker VARCHAR NOT NULL,
                    start_expiration VARCHAR NOT NULL,
                    end_expiration VARCHAR NOT NULL,
                    option_type VARCHAR NOT NULL,
                    fetched_at VARCHAR NOT NULL,
                    expires_at VARCHAR NOT NULL,
                    source_label VARCHAR NOT NULL,
                    row_count INTEGER NOT NULL,
                    columns_json VARCHAR NOT NULL
                )
                """
            )
            active_connection.execute(
                """
                CREATE TABLE IF NOT EXISTS option_contract_quotes (
                    snapshot_id VARCHAR NOT NULL,
                    row_index INTEGER NOT NULL,
                    symbol VARCHAR,
                    underlying VARCHAR,
                    option_type VARCHAR,
                    expiry VARCHAR,
                    strike DOUBLE,
                    bid DOUBLE,
                    ask DOUBLE,
                    last DOUBLE,
                    mid DOUBLE,
                    volume DOUBLE,
                    open_interest DOUBLE,
                    implied_volatility DOUBLE,
                    delta DOUBLE,
                    gamma DOUBLE,
                    theta DOUBLE,
                    vega DOUBLE,
                    rho DOUBLE,
                    payload_json VARCHAR NOT NULL,
                    PRIMARY KEY (snapshot_id, row_index)
                )
                """
            )
        finally:
            if owns_connection:
                active_connection.close()


def _contract_quote_row(
    snapshot_id: str,
    row_index: int,
    record: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        snapshot_id,
        row_index,
        _text_value(record, "symbol", "code"),
        _text_value(record, "underlying", "stock_owner"),
        _text_value(record, "option_type"),
        _text_value(record, "expiry", "strike_time", "expiration"),
        _float_value(record, "strike", "strike_price"),
        _float_value(record, "bid", "bid_price"),
        _float_value(record, "ask", "ask_price"),
        _float_value(record, "last", "last_price"),
        _float_value(record, "mid", "mid_price"),
        _float_value(record, "volume"),
        _float_value(record, "open_interest", "option_open_interest"),
        _float_value(record, "implied_volatility", "option_implied_volatility"),
        _float_value(record, "delta", "option_delta"),
        _float_value(record, "gamma", "option_gamma"),
        _float_value(record, "theta", "option_theta"),
        _float_value(record, "vega", "option_vega"),
        _float_value(record, "rho", "option_rho"),
        json.dumps(record, sort_keys=True, separators=(",", ":")),
    )


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_value(value) for key, value in record.items()}
        for record in frame.to_dict(orient="records")
    ]


def _json_value(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return value


def _text_value(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _float_value(record: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = record.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


_NUMERIC_COLUMNS: frozenset[str] = frozenset(
    {
        "strike",
        "bid",
        "ask",
        "last",
        "mid",
        "bid_size",
        "ask_size",
        "volume",
        "turnover",
        "market_val",
        "open_interest",
        "implied_volatility",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "contract_size",
    }
)
