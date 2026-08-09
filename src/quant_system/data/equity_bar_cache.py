from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

_BAR_COLUMNS = (
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "provider",
    "interval",
    "event_ts",
    "knowledge_ts",
    "price_adjustment",
)


class EquityBarCache:
    """DuckDB cache for strict provider/interval/adjustment daily bars."""

    def __init__(
        self,
        duckdb_path: str | Path,
        *,
        ttl_seconds: float = 86_400.0,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.duckdb_path = Path(duckdb_path)
        self.ttl_seconds = float(ttl_seconds)
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def read(
        self,
        *,
        provider: str,
        symbols: list[str],
        interval: str,
        adjustment: str,
        start: str,
        end: str,
        as_of: pd.Timestamp | None = None,
    ) -> pd.DataFrame | None:
        normalized_provider = provider.lower().strip()
        normalized_symbols = [symbol.upper().strip() for symbol in symbols]
        normalized_interval = interval.lower().strip()
        normalized_adjustment = adjustment.lower().strip()
        now = _utc_timestamp(as_of or pd.Timestamp.now(tz="UTC"))

        with duckdb.connect(str(self.duckdb_path)) as connection:
            self._ensure_schema(connection)
            for symbol in normalized_symbols:
                coverage = connection.execute(
                    """
                    SELECT 1
                    FROM equity_bar_cache_requests
                    WHERE provider = ?
                      AND symbol = ?
                      AND interval = ?
                      AND adjustment = ?
                      AND requested_start <= ?
                      AND requested_end >= ?
                      AND expires_at > ?
                    ORDER BY fetched_at DESC
                    LIMIT 1
                    """,
                    [
                        normalized_provider,
                        symbol,
                        normalized_interval,
                        normalized_adjustment,
                        start,
                        end,
                        now.isoformat(),
                    ],
                ).fetchone()
                if coverage is None:
                    return None

            placeholders = ", ".join("?" for _ in normalized_symbols)
            rows = connection.execute(
                f"""
                SELECT symbol, timestamp, open, high, low, close, volume,
                       provider, interval, event_ts, knowledge_ts, adjustment
                FROM equity_bars
                WHERE provider = ?
                  AND interval = ?
                  AND adjustment = ?
                  AND symbol IN ({placeholders})
                  AND session_date >= ?
                  AND session_date <= ?
                ORDER BY symbol, session_date
                """,
                [
                    normalized_provider,
                    normalized_interval,
                    normalized_adjustment,
                    *normalized_symbols,
                    start,
                    end,
                ],
            ).fetchall()

        if not rows:
            return None
        frame = pd.DataFrame(rows, columns=_BAR_COLUMNS)
        if set(frame["symbol"]) != set(normalized_symbols):
            return None
        for column in ("timestamp", "event_ts", "knowledge_ts"):
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="raise")
        return frame

    def write(
        self,
        frame: pd.DataFrame,
        *,
        provider: str,
        symbols: list[str],
        interval: str,
        adjustment: str,
        start: str,
        end: str,
        fetched_at: pd.Timestamp | None = None,
    ) -> None:
        missing = [column for column in _BAR_COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"equity bar cache frame missing columns: {', '.join(missing)}")

        normalized_provider = provider.lower().strip()
        normalized_symbols = [symbol.upper().strip() for symbol in symbols]
        normalized_interval = interval.lower().strip()
        normalized_adjustment = adjustment.lower().strip()
        normalized = frame.loc[:, _BAR_COLUMNS].copy()
        normalized["symbol"] = normalized["symbol"].astype(str).str.upper().str.strip()
        normalized["provider"] = normalized["provider"].astype(str).str.lower().str.strip()
        normalized["interval"] = normalized["interval"].astype(str).str.lower().str.strip()
        normalized["price_adjustment"] = (
            normalized["price_adjustment"].astype(str).str.lower().str.strip()
        )
        if set(normalized["symbol"]) != set(normalized_symbols):
            raise ValueError("equity bar cache symbols do not match request")
        if set(normalized["provider"]) != {normalized_provider}:
            raise ValueError("equity bar cache provider does not match request")
        if set(normalized["interval"]) != {normalized_interval}:
            raise ValueError("equity bar cache interval does not match request")
        if set(normalized["price_adjustment"]) != {normalized_adjustment}:
            raise ValueError("equity bar cache adjustment does not match request")

        normalized["timestamp"] = pd.to_datetime(
            normalized["timestamp"],
            utc=True,
            errors="raise",
        )
        normalized["event_ts"] = pd.to_datetime(
            normalized["event_ts"],
            utc=True,
            errors="raise",
        )
        normalized["knowledge_ts"] = pd.to_datetime(
            normalized["knowledge_ts"],
            utc=True,
            errors="raise",
        )
        normalized["session_date"] = normalized["timestamp"].dt.date.astype(str)
        if (
            (normalized["session_date"] < start).any()
            or (normalized["session_date"] > end).any()
        ):
            raise ValueError("equity bar cache rows fall outside request")

        fetched = _utc_timestamp(
            fetched_at or normalized["knowledge_ts"].max() or pd.Timestamp.now(tz="UTC")
        )
        expires = fetched + pd.Timedelta(seconds=self.ttl_seconds)
        bar_rows = [
            (
                str(row.provider),
                str(row.symbol),
                str(row.interval),
                str(row.price_adjustment),
                str(row.session_date),
                row.timestamp.isoformat(),
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                float(row.volume),
                row.event_ts.isoformat(),
                row.knowledge_ts.isoformat(),
                fetched.isoformat(),
            )
            for row in normalized.itertuples(index=False)
        ]

        with duckdb.connect(str(self.duckdb_path)) as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.executemany(
                    """
                    DELETE FROM equity_bars
                    WHERE provider = ? AND symbol = ? AND interval = ?
                      AND adjustment = ? AND session_date = ?
                    """,
                    [row[:5] for row in bar_rows],
                )
                connection.executemany(
                    """
                    INSERT INTO equity_bars (
                        provider, symbol, interval, adjustment, session_date,
                        timestamp, open, high, low, close, volume,
                        event_ts, knowledge_ts, fetched_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    bar_rows,
                )
                for symbol in normalized_symbols:
                    connection.execute(
                        """
                        DELETE FROM equity_bar_cache_requests
                        WHERE provider = ? AND symbol = ? AND interval = ?
                          AND adjustment = ? AND requested_start = ?
                          AND requested_end = ?
                        """,
                        [
                            normalized_provider,
                            symbol,
                            normalized_interval,
                            normalized_adjustment,
                            start,
                            end,
                        ],
                    )
                    connection.execute(
                        """
                        INSERT INTO equity_bar_cache_requests (
                            provider, symbol, interval, adjustment,
                            requested_start, requested_end, fetched_at, expires_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            normalized_provider,
                            symbol,
                            normalized_interval,
                            normalized_adjustment,
                            start,
                            end,
                            fetched.isoformat(),
                            expires.isoformat(),
                        ],
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def _ensure_schema(
        self,
        connection: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        owns_connection = connection is None
        active = connection or duckdb.connect(str(self.duckdb_path))
        try:
            active.execute(
                """
                CREATE TABLE IF NOT EXISTS equity_bars (
                    provider VARCHAR NOT NULL,
                    symbol VARCHAR NOT NULL,
                    interval VARCHAR NOT NULL,
                    adjustment VARCHAR NOT NULL,
                    session_date VARCHAR NOT NULL,
                    timestamp VARCHAR NOT NULL,
                    open DOUBLE NOT NULL,
                    high DOUBLE NOT NULL,
                    low DOUBLE NOT NULL,
                    close DOUBLE NOT NULL,
                    volume DOUBLE NOT NULL,
                    event_ts VARCHAR NOT NULL,
                    knowledge_ts VARCHAR NOT NULL,
                    fetched_at VARCHAR NOT NULL,
                    PRIMARY KEY (
                        provider, symbol, interval, adjustment, session_date
                    )
                )
                """
            )
            active.execute(
                """
                CREATE TABLE IF NOT EXISTS equity_bar_cache_requests (
                    provider VARCHAR NOT NULL,
                    symbol VARCHAR NOT NULL,
                    interval VARCHAR NOT NULL,
                    adjustment VARCHAR NOT NULL,
                    requested_start VARCHAR NOT NULL,
                    requested_end VARCHAR NOT NULL,
                    fetched_at VARCHAR NOT NULL,
                    expires_at VARCHAR NOT NULL,
                    PRIMARY KEY (
                        provider, symbol, interval, adjustment,
                        requested_start, requested_end
                    )
                )
                """
            )
        finally:
            if owns_connection:
                active.close()


def _utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")
